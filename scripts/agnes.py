#!/usr/bin/env python3
"""wudaozi — agnes-image cloud text-to-image/image-to-image wrapper script.

Core responsibilities (deterministic logic, pure stdlib, no local model/GPU dependency):
1. Construct agnes API request (model/prompt/size + optional reference image)
2. POST https://apihub.agnes-ai.com/v1/images/generations (Bearer auth)
3. Download URL or decode base64 to local PNG
4. Report errors explicitly for user decision, no automatic fallback to boogu

Usage:
    AGNES_API_KEY=agn-xxx python agnes.py t2i -i "..." --aspect 1:1
    AGNES_API_KEY=agn-xxx python agnes.py ti2i -i "change background" --input photo.jpg
    AGNES_API_KEY=agn-xxx python agnes.py t2i -i "..." --dry-run
"""
# ponytail: Cloud API passthrough; no local model/GPU dependency; no fallback on error (user decision, follows rule 12).
# agnes is a cloud black box, doesn't support seed/steps/cfg, so CLI is minimal — don't expose meaningless knobs.

import argparse
import json
import os
import random
import sys
import time
import uuid
from pathlib import Path

import _cloud_common as _cc
import _prompt_variants as _pv
import assets as _assets

ENDPOINT = "https://apihub.agnes-ai.com/v1/images/generations"
MODEL = "agnes-image-2.1-flash"
TIMEOUT = 60  # ponytail: Single value is sufficient; size-based timeout tiers are premature optimization

# Own aspect ratio table, decoupled from boogu (two providers evolve differently).
# ponytail: No 16-alignment assertion — agnes is cloud, unknown if 16-multiple is required, left for calibration.
# Same values as boogu.ASPECT_RATIOS, but intentionally not imported to avoid cross-provider coupling.
ASPECT_RATIOS = {
    # Tuple semantics (H, W); portrait H>W, landscape W>H. aspect means W:H.
    "1:1": (1024, 1024),
    "3:4": (1360, 1024),  # portrait
    "4:3": (1024, 1360),  # landscape
    "2:3": (1536, 1024),  # portrait
    "3:2": (1024, 1536),  # landscape
    "9:16": (1824, 1024),  # mobile portrait
    "16:9": (1024, 1824),  # landscape
}

# ── Absorbed from CookSleep/gpt_image_playground (2026-09-14) ──
# Custom sizes snap to model-safe alignment (multiples of 16) instead of being
# passed through raw or rejected; mirrors the playground's smart size control.
SNAP_MULTIPLE = 16
MIN_SIDE = 256
MAX_SIDE = 2048
# Batch generation: one turn, N images (playground: generate_image_batch).
BATCH_MAX = 8
BATCH_CONCURRENCY = 4
# Anti-rewrite guard: some providers lightly rewrite prompts; this prefix asks
# the model to treat the prompt verbatim (playground: prompt-rewrite protection).
PROMPT_GUARD = (
    "[Important] Please strictly follow the prompt below. Do not rewrite, extend, "
    "or optimize it; generate exactly what is described. Prompt:\n"
)
# Local chroma-key background removal for --transparent-mode post
# (playground: native transparent API param, or model paints solid chroma
# background that is then removed client-side).
CHROMA_RGB = {"magenta": (255, 0, 255), "green": (0, 255, 0)}
CHROMA_PROMPT = {
    "magenta": "The background must be a completely flat, uniform pure magenta (#FF00FF), with no gradients, shadows, or reflections on the background.",
    "green": "The background must be a completely flat, uniform pure green (#00FF00), with no gradients, shadows, or reflections on the background.",
}


def snap_size(height: int, width: int) -> tuple:
    """Snap custom H×W into the model-safe range: nearest multiple of 16,
    clamped to MIN_SIDE/MAX_SIDE. Returns (H, W, adjustments) where adjustments
    is a list of human-readable notices (empty when nothing changed).

    Absorbed from gpt_image_playground: raw custom sizes are auto-normalized
    (multiples of 16, total-pixel sanity) instead of hitting server 400s.
    """
    adjustments = []

    def _snap(v: int, label: str) -> int:
        snapped = max(MIN_SIDE, min(MAX_SIDE, round(v / SNAP_MULTIPLE) * SNAP_MULTIPLE))
        if snapped != v:
            adjustments.append(f"{label} {v} -> {snapped} (snapped to {SNAP_MULTIPLE}-multiple, range {MIN_SIDE}-{MAX_SIDE})")
        return snapped

    h = _snap(int(height), "height")
    w = _snap(int(width), "width")
    return h, w, adjustments


def resolve_size(a: argparse.Namespace) -> tuple:
    """Resolve final H×W: aspect > height/width (must be provided together) > default 1:1.

    Custom sizes are snapped to 16-multiples via snap_size (absorbed from
    gpt_image_playground); aspect presets are already aligned and pass through.
    """
    if a.aspect:
        return ASPECT_RATIOS[a.aspect]
    if (a.height is None) != (a.width is None):
        sys.exit("[ERROR] --height and --width must be provided together; use --aspect presets for single dimension")
    if a.height and a.width:
        h, w, adj = snap_size(a.height, a.width)
        for notice in adj:
            print(f"[INFO] size snap: {notice}", file=sys.stderr)
        return h, w
    return ASPECT_RATIOS["1:1"]


def resolve_output(a: argparse.Namespace, height: int, width: int, index: int = 1) -> Path:
    """Output path: default $PWD/agnes-output/, filename includes mode+size+timestamp+uuid8 to prevent overwriting.

    When count > 1, a 1-based index suffix is appended for readability.
    """
    out_dir = (
        Path(a.output_dir).resolve() if a.output_dir else Path.cwd() / "agnes-output"
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = int(time.time())
    suffix = uuid.uuid4().hex[:8]
    idx = f"_{index:02d}" if getattr(a, "count", 1) > 1 else ""
    fname = f"agnes_{a.mode}_{width}x{height}_{ts}_{suffix}{idx}.png"
    return out_dir / fname


def image_to_data_uri(path: str) -> str:
    """Local file → data URI (shared impl; 20MB guard applies here too, M-5)."""
    return _cc.image_to_data_uri(path)


def build_body(a: argparse.Namespace, height: int, width: int, instruction: str | None = None) -> dict:
    """Assemble agnes request body.

    ⚠️ agnes size is a WxH string (documentation example 1024x768 is landscape), easy to reverse, must be tested and pinned.
    Default response_format=url (download); when --base64: t2i uses top-level return_base64,
    ti2i uses extra_body.response_format=b64_json.

    Absorbed from gpt_image_playground:
    - --strict-prompt: prefixes an anti-rewrite guard so the model treats the
      prompt verbatim (playground: prompt-rewrite protection)
    - --mask (ti2i): transparent-PNG mask as data URI in extra_body["mask"]
      (OpenAI edits convention); agnes support needs live calibration — if the
      provider rejects the field, drop --mask and use full-image ti2i
    - --transparent native: extra_body["background"] = "transparent"

    instruction 缺省取 a.instruction（--count>1 变体展开时由调用方传每份变体）。
    ti2i 且 --ref-role != subject 时先追加参考图角色子句，再套 strict-prompt 护栏。
    """
    if getattr(a, "mask", None) and a.mode != "ti2i":
        sys.exit("[ERROR] --mask is only valid for ti2i (inpainting); t2i has no reference image to mask")
    instruction = instruction if instruction is not None else a.instruction
    if a.mode == "ti2i" and getattr(a, "ref_role", "subject") != "subject":
        instruction = _cc.apply_ref_role(instruction, a.ref_role)
    if getattr(a, "strict_prompt", False):
        instruction = PROMPT_GUARD + instruction

    extra = {"response_format": "url"}
    if a.base64:
        extra = {} if a.mode == "t2i" else {"response_format": "b64_json"}

    body = {
        "model": MODEL,
        "prompt": instruction,
        "size": f"{width}x{height}",  # WxH
        "extra_body": extra,
    }
    if a.base64 and a.mode == "t2i":
        body["return_base64"] = True

    if getattr(a, "transparent", "off") == "native":
        extra["background"] = "transparent"

    if a.mode == "ti2i":
        refs = getattr(a, "_refs", None)
        if refs:
            # --ref 资产引用：多张参考图（上限 4 已在 resolve_refs 截断），全部转 data URI
            extra["image"] = [image_to_data_uri(str(r)) for r in refs]
        else:
            if not a.input:
                sys.exit("[ERROR] Image-to-image (ti2i) requires --input reference image path or URL")
            # Remote http(s) URL passthrough (SSRF-checked — the VLM/provider fetches it,
            # same exposure as vision.py); local path converted to Data URI
            if a.input.startswith(("http://", "https://")):
                _cc.assert_public_url(a.input, ctx="--input")
                ref = a.input
            else:
                ref = image_to_data_uri(a.input)
            extra["image"] = [ref]
        if getattr(a, "mask", None):
            mask_uri = image_to_data_uri(a.mask)
            if not mask_uri.startswith("data:image/png"):
                sys.exit("[ERROR] --mask must be a local PNG (transparent areas mark the region to redraw)")
            extra["mask"] = mask_uri

    return body


def call_api(body: dict, api_key: str) -> dict:
    """POST to ENDPOINT via the shared transport. Exit on failure with actionable
    hints, no fallback (thin wrapper kept so tests/ and future callers have one name)."""
    return _cc.post_json(ENDPOINT, body, api_key, TIMEOUT, label="agnes")


def _download(url: str, out_path: Path) -> None:
    """Download URL to file (shared transport; kept as a module name for tests to patch)."""
    _cc.download_to_file(url, out_path, TIMEOUT, "agnes")


def save_image(resp_data: dict, out_path: Path) -> dict:
    """Response handling via shared extract_media: data[0].url → download;
    data[0].b64_json → decode; missing → error.

    Returns the data[0] item so callers can build sidecar metadata.
    """
    return _cc.extract_media(resp_data, out_path, label="agnes", min_bytes=1024, download=_download)


def remove_chroma(png_path: Path, chroma: str, tolerance: int = 90) -> None:
    """--transparent-mode post: remove the solid chroma background client-side.

    Absorbed from gpt_image_playground's local post-processing mode: the model
    paints a flat magenta/green background, this strips it to transparency.
    Requires Pillow (optional dependency) — missing it fails loudly with the
    install hint instead of silently skipping. Limitations (same as upstream):
    hair-thin edges, semi-transparent materials, or subject colors close to the
    chroma may keep residue; prefer --transparent-mode native when supported.
    """
    try:
        from PIL import Image  # noqa: PLC0415 — optional dependency, imported lazily on purpose
    except ImportError:
        sys.exit(
            "[ERROR] --transparent-mode post requires Pillow (optional dependency)\n"
            "  → pip install Pillow and retry, or use --transparent-mode native"
        )
    img = Image.open(png_path).convert("RGBA")
    pr, pg, pb = CHROMA_RGB[chroma]
    pixels = img.load()
    w, h = img.size
    removed = 0
    for y in range(h):
        for x in range(w):
            r, g, b, a = pixels[x, y]
            if (
                abs(r - pr) <= tolerance
                and abs(g - pg) <= tolerance
                and abs(b - pb) <= tolerance
            ):
                pixels[x, y] = (r, g, b, 0)
                removed += 1
    img.save(png_path, "PNG")
    pct = removed * 100 // max(w * h, 1)
    print(f"[INFO] chroma removal ({chroma}): {pct}% pixels -> transparent", file=sys.stderr)


def write_sidecar(out_path: Path, meta: dict) -> Path:
    """Absorbed from gpt_image_playground: per-image sidecar metadata (request
    vs actually-effective parameters, elapsed time, revised prompt) for
    reproducibility and audits. Returns the sidecar path."""
    sidecar = out_path.with_suffix(".json")
    sidecar.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return sidecar


def to_curl(body: dict, api_key: str) -> str:
    """Dry-run equivalent curl (shared impl: masked key, truncated data URIs, shlex.quote)."""
    return _cc.to_curl(ENDPOINT, body, api_key)


# ============================================================================
# CLI
# ============================================================================
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="agnes.py",
        description="wudaozi — agnes-image cloud text-to-image/image-to-image wrapper (construct request + call API + save image)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  # Text-to-image (default url return and download, 1:1)
  AGNES_API_KEY=agn-xxx python agnes.py t2i -i "an orange cat under moonlight, cinematic"

  # Image-to-image (local reference image auto-converted to base64)
  AGNES_API_KEY=agn-xxx python agnes.py ti2i -i "change background to beach" --input photo.jpg

  # View curl equivalent command only, don't actually call (for debugging)
  AGNES_API_KEY=agn-xxx python agnes.py t2i -i "..." --dry-run

Aspect ratio presets: """
        + ", ".join(f"{k}={v[0]}x{v[1]}" for k, v in ASPECT_RATIOS.items()),
    )
    p.add_argument(
        "mode", choices=["t2i", "ti2i"], help="t2i=text-to-image, ti2i=image-to-image (editing)"
    )
    p.add_argument(
        "--instruction", "-i", required=True, help="Generation instruction (recommended to structure via SKILL.md first)"
    )
    p.add_argument("--input", help="ti2i reference image local path or public URL (required for ti2i)")
    p.add_argument(
        "--ref",
        nargs="+",
        default=None,
        metavar="ASSET",
        help="ti2i 引用资产库参考图（assets.py add 创建；与 --input 互斥；"
        "style 资产默认 --ref-role style；单次最多 4 张）",
    )
    p.add_argument(
        "--aspect",
        choices=list(ASPECT_RATIOS),
        help="Aspect ratio preset (takes priority over --height/--width)",
    )
    p.add_argument(
        "--height", type=int, help="Output height (must be provided with --width)"
    )
    p.add_argument("--width", type=int, help="Output width (must be provided with --height)")
    p.add_argument(
        "--output-dir", "-o", default=None, help="Output directory (default $PWD/agnes-output/)"
    )
    p.add_argument(
        "--base64",
        action="store_true",
        help="Force base64 return (default url download)",
    )
    p.add_argument("--dry-run", action="store_true", help="Only print curl, don't execute")
    # ── Absorbed from gpt_image_playground ──
    p.add_argument(
        "--mask",
        help="ti2i only: local PNG mask, transparent areas mark the region to redraw (OpenAI edits convention; agnes support needs calibration)",
    )
    p.add_argument(
        "--transparent",
        choices=["off", "native", "post"],
        default="off",
        help="transparent background: native = ask the API for an alpha channel; post = model paints flat chroma background, removed locally (needs Pillow). Ideal for icons/stickers",
    )
    p.add_argument(
        "--chroma",
        choices=["magenta", "green"],
        default="magenta",
        help="chroma color for --transparent post (default magenta)",
    )
    p.add_argument(
        "--count",
        type=int,
        default=1,
        help="generate N images in one turn, concurrent (1-8)",
    )
    p.add_argument(
        "--strict-prompt",
        action="store_true",
        help="prefix an anti-rewrite guard so the model renders the prompt verbatim",
    )
    p.add_argument(
        "--ref-role",
        choices=sorted(_cc.REF_ROLE_CLAUSES),
        default=None,
        help="ti2i 参考图角色语义（默认 subject；--ref 引用 style 资产时默认 style）: "
        "subject=参考图即主体(行为不变) / style=只借画风勿抄主体 / composition=只借构图与机角勿抄主体",
    )
    a = p.parse_args()
    if not 1 <= a.count <= BATCH_MAX:
        p.error(f"--count must be 1-{BATCH_MAX}")
    return a


def _generate_once(a: argparse.Namespace, api_key: str, index: int, instruction: str | None = None) -> Path:
    """One generation round (index is 1-based, used for filenames when count > 1).

    instruction 缺省取 a.instruction；变体展开时由 main() 传入每份变体（non-repeating）。
    Returns the output path on success; raises SystemExit on failure (fail
    loudly, per-image in batch mode).
    """
    instruction = instruction if instruction is not None else a.instruction
    height, width = resolve_size(a)
    out_path = resolve_output(a, height, width, index)
    started = time.monotonic()
    body = build_body(a, height, width, instruction)

    label = f"[{index}/{a.count}] " if a.count > 1 else ""
    print(f"{label}[INFO] provider=agnes mode={a.mode} size={width}x{height}", file=sys.stderr)
    print(f"{label}[INFO] output={out_path}", file=sys.stderr)
    print(f"{label}[CMD] {to_curl(body, api_key)}", file=sys.stderr)

    try:
        # 跨进程并发闸：锁只覆盖网络 IO（请求 + 产物下载），本地像素处理不占槽位
        with _cc.provider_slot("agnes"):
            resp = call_api(body, api_key)
            item = save_image(resp, out_path)
    except SystemExit as e:
        # 失败留痕：错误路径也落盘 sidecar（成功路径才有 sidecar 的盲区，调研建议#1）
        _cc.raise_with_trace(
            e, out_path, "agnes",
            {"mode": a.mode, "instruction": instruction, "size": f"{width}x{height}",
             "count": a.count, "index": index},
        )

    if a.transparent == "post":
        # 本地像素循环（157ms/1024² 实测），放在槽位外不拖累其他会话排队
        try:
            remove_chroma(out_path, a.chroma)
        except SystemExit as e:
            _cc.raise_with_trace(
                e, out_path, "agnes",
                {"stage": "chroma-removal", "mode": a.mode, "instruction": instruction,
                 "size": f"{width}x{height}", "count": a.count, "index": index},
            )

    # PNG 文本 chunk 元数据（webui 兼容）：remove_chroma 的 PIL 重存会丢 chunk，必须在它之后写
    _cc.embed_png_metadata(
        out_path, instruction, None,
        {"provider": "agnes", "model": MODEL, "mode": a.mode,
         "size": f"{width}x{height}", "aspect": a.aspect,
         "count": a.count if a.count > 1 else None,
         "index": index if a.count > 1 else None},
    )

    elapsed_ms = int((time.monotonic() - started) * 1000)
    sidecar = write_sidecar(
        out_path,
        {
            "provider": "agnes",
            "mode": a.mode,
            "request": {
                "instruction": instruction,
                "size": f"{width}x{height}",
                "aspect": a.aspect,
                "transparent": a.transparent,
                "chroma": a.chroma if a.transparent == "post" else None,
                "mask": a.mask,
                "strict_prompt": a.strict_prompt,
                "ref_role": getattr(a, "ref_role", "subject"),
                "ref": getattr(a, "ref", None),
                "count": a.count,
                "index": index,
            },
            "actual": {
                "output": str(out_path),
                "bytes": out_path.stat().st_size,
                "revised_prompt": item.get("revised_prompt"),
                "usage": item.get("usage"),
                "elapsed_ms": elapsed_ms,
            },
        },
    )
    print(
        f"{label}[OK] Generated: {out_path} ({out_path.stat().st_size // 1024} KB, "
        f"{elapsed_ms} ms) sidecar={sidecar.name}",
        file=sys.stderr,
    )
    # stdout 管道契约：产物路径一行走 stdout（$(...) 可捕获）；单次 write 保证批量
    # 多线程下行不被其他线程粘连
    sys.stdout.write(f"WUDAOZI_OUTPUT={out_path}\n")
    sys.stdout.flush()
    return out_path


def main() -> int:
    a = parse_args()

    # --ref 资产解析（ti2i）：refs 取自资产库（拷贝入库的副本）；kind 决定默认 ref-role
    if a.ref:
        if a.mode != "ti2i":
            sys.exit("[ERROR] --ref 仅支持 ti2i（角色/画风资产）")
        if a.input:
            sys.exit("[ERROR] --input 与 --ref 互斥（--ref 直接引用资产库）")
        kinds = [_assets.load_asset(n)["kind"] for n in a.ref]
        a._refs = _assets.resolve_refs(a.ref)
        if a.ref_role is None:
            a.ref_role = "style" if kinds[0] == "style" else "subject"
    a.ref_role = a.ref_role or "subject"

    api_key = os.environ.get("AGNES_API_KEY")
    if not api_key:
        _cc.fail(
            "auth_error",
            "AGNES_API_KEY environment variable not set",
            "  → export AGNES_API_KEY=agn-xxx and retry, or switch to boogu local provider",
        )

    height, width = resolve_size(a)
    body = build_body(a, height, width)

    print(f"[INFO] provider=agnes mode={a.mode} size={width}x{height} count={a.count}", file=sys.stderr)
    print(f"[CMD] {to_curl(body, api_key)}", file=sys.stderr)

    if a.dry_run:
        print("[DRY-RUN] Not executed (no key / for debugging)", file=sys.stderr)
        return 0

    # 变体展开：含 {a|b|c} / {_词库_} 语法时每份一份非重复变体；无语法 = 原样 N 份（历史行为）
    segs = _pv.parse_slots(a.instruction)
    instructions = _pv.sample_variants(a.instruction, a.count, random.Random(), segments=segs)
    if _pv.has_variant_syntax(a.instruction):
        print(f"[INFO] 变体展开: {a.count} 份（组合空间 {_pv.combo_count(segs)}，非重复抽样）", file=sys.stderr)

    if a.count == 1:
        _generate_once(a, api_key, 1, instructions[0])
        return 0

    # Batch: concurrent with a small pool (playground generate_image_batch).
    # Partial failures are collected and reported explicitly — never silently
    # swallowed, and successful images are kept (rule 12).
    from concurrent.futures import ThreadPoolExecutor

    failures = []
    results = []
    with ThreadPoolExecutor(max_workers=min(a.count, BATCH_CONCURRENCY)) as pool:
        futures = {
            pool.submit(_generate_once, a, api_key, i + 1, instructions[i]): i + 1
            for i in range(a.count)
        }
        for fut in futures:
            try:
                results.append(fut.result())
            except SystemExit as e:
                failures.append(str(e))
    ok = len(results)
    print(f"[BATCH] {ok}/{a.count} generated, {len(failures)} failed", file=sys.stderr)
    for msg in failures:
        print(f"[BATCH-FAIL] {msg}", file=sys.stderr)
    if failures:
        sys.exit(1)
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] != "__selfcheck__":
        sys.exit(main())
    # ponytail: Self-check — validates pure functions + constants + key existence, no network calls (no external dependencies).
    from types import SimpleNamespace

    print("== wudaozi agnes self-check ==")
    for k, (h, w) in ASPECT_RATIOS.items():
        assert isinstance(h, int) and isinstance(w, int), k
    assert resolve_size(SimpleNamespace(aspect="9:16", height=None, width=None)) == (
        1824,
        1024,
    )
    h, w, adj = snap_size(800, 600)
    assert (h, w) == (800, 608) and adj, "600 snaps to 608 (16-multiple)"
    assert snap_size(1024, 1024) == (1024, 1024, []), "aligned sizes pass through"
    assert resolve_size(SimpleNamespace(aspect=None, height=800, width=600)) == (
        800,
        608,
    )
    body_guard = build_body(SimpleNamespace(
        mode="t2i", instruction="x", input=None, base64=False, strict_prompt=True,
        transparent="off", mask=None,
    ), 1024, 1024)
    assert body_guard["prompt"].startswith("[Important]"), "anti-rewrite guard"
    body_tr = build_body(SimpleNamespace(
        mode="t2i", instruction="x", input=None, base64=False, strict_prompt=False,
        transparent="native", mask=None,
    ), 1024, 1024)
    assert body_tr["extra_body"]["background"] == "transparent"
    assert resolve_output(
        SimpleNamespace(mode="t2i", output_dir=None), 1024, 1024
    ).name.startswith("agnes_t2i_1024x1024_")
    body = build_body(SimpleNamespace(
        mode="t2i", instruction="x", input=None, base64=False
    ), 1024, 1024)
    assert body["size"] == "1024x1024"
    assert body["extra_body"]["response_format"] == "url"
    # --ref-role：subject 不加子句，style/composition 追加约束
    assert build_body(SimpleNamespace(
        mode="ti2i", instruction="x", input="https://e.com/a.png", base64=False,
        ref_role="subject",
    ), 1024, 1024)["prompt"] == "x"
    assert "style/aesthetic" in build_body(SimpleNamespace(
        mode="ti2i", instruction="x", input="https://e.com/a.png", base64=False,
        ref_role="style",
    ), 1024, 1024)["prompt"]
    # 变体展开：无语法 = 原样；有语法 = 非重复
    assert _pv.sample_variants("plain", 2, random.Random(1)) == ["plain", "plain"]
    assert sorted(_pv.sample_variants("{a|b}", 2, random.Random(7))) == ["a", "b"]
    print(f"  Aspect ratio presets: {len(ASPECT_RATIOS)}")
    print(f"  ENDPOINT: {ENDPOINT}")
    print(f"  MODEL: {MODEL}")
    print(
        f"  AGNES_API_KEY: {'set' if os.environ.get('AGNES_API_KEY') else 'not set'}"
    )
    print("  self-check PASS")
