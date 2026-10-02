#!/usr/bin/env python3
"""wudaozi —— aiping Kolors 云端文生图包装脚本（仅 t2i，不支持图生图）。

核心职责（纯 stdlib，无 GPU/本地模型依赖）：
1. 构造 aiping Kolors 请求（model/prompt + 可选 image_size）
2. 调 POST https://www.aiping.cn/api/v1/images/generations（Bearer 鉴权）
3. 下载返回的 url 存本地 PNG
4. 错误显式报错，不 fallback

⚠️ Kolors 仅支持文生图（t2i）——这是模型硬约束，不支持参考图编辑。
   图生图请走 agnes.py（ti2i）或 boogu.py（ti2i）。

使用：
    AIPING_API_KEY=QC-xxx python3 kolors.py t2i -i "一只宇航员在都市街头漫步"
    AIPING_API_KEY=QC-xxx python3 kolors.py t2i -i "..." --aspect 9:16
    AIPING_API_KEY=QC-xxx python3 kolors.py t2i -i "..." --dry-run
"""
# ponytail: 仅 t2i 是模型硬约束；CLI mode 强制 choices=["t2i"]，从入口拒绝图生图。
# provider 语义（端点/请求体/尺寸表）与 agnes.py 解耦，但 HTTP 传输骨架自 2026-10
# 起收敛到 _cloud_common（显式推翻此前的解耦声明，作者批准，见 _cloud_common 模块注释）。

import argparse
import os
import random
import sys
import time
import uuid
from pathlib import Path

import _cloud_common as _cc
import _prompt_variants as _pv

ENDPOINT = "https://www.aiping.cn/api/v1/images/generations"
MODEL = "Kolors"
TIMEOUT = 90  # ponytail: Kolors 单图通常 5-15s，给 90s 余量

BATCH_CONCURRENCY = 4  # --count 并发上限（与 agnes 同值，具名常量防漂移，性能审查 F6）

# Kolors 经 siliconflow 路由，常见 image_size；不传时服务端给默认 1024x1024。
# ponytail: 清单未必全（云端黑盒），HTTP 400 时换 --image-size，不强校验。
IMAGE_SIZES = {
    "1:1": "1024x1024",
    "3:4": "768x1024",   # 竖
    "4:3": "1024x768",   # 横
    "2:3": "768x1152",   # 竖
    "3:2": "1152x768",   # 横
    "9:16": "720x1280",  # 手机竖屏
    "16:9": "1280x720",  # 横
}


def resolve_image_size(a: argparse.Namespace) -> str | None:
    """aspect > 自定义 image_size > 不传（服务端默认）。"""
    if a.aspect:
        return IMAGE_SIZES[a.aspect]
    return a.image_size  # None 或用户自定义字符串（如 "1328x1328"）


def resolve_output(a: argparse.Namespace, index: int = 1) -> Path:
    """输出路径：默认 $PWD/kolors-output/，文件名含 t2i+时间戳+uuid8 防覆盖；count>1 时追加序号。"""
    out_dir = (
        Path(a.output_dir).resolve() if a.output_dir else Path.cwd() / "kolors-output"
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = int(time.time())
    suffix = uuid.uuid4().hex[:8]
    idx = f"_{index:02d}" if getattr(a, "count", 1) > 1 else ""
    return out_dir / f"kolors_t2i_{ts}_{suffix}{idx}.png"


def build_body(a: argparse.Namespace, instruction: str | None = None) -> dict:
    """组装 Kolors 请求体。image_size 可选（不传走服务端默认）。
    instruction 缺省取 a.instruction（--count>1 变体展开时传每份变体）。"""
    body: dict = {"model": MODEL, "prompt": instruction if instruction is not None else a.instruction}
    sz = resolve_image_size(a)
    if sz:
        body["image_size"] = sz
    return body


def _download(url: str, out_path: Path) -> None:
    """下载 URL 到文件（共享传输；保留模块名供 tests mock）。Kolors 返回 siliconflow CDN 签名链接，urllib 自动跟随重定向。"""
    _cc.download_to_file(url, out_path, TIMEOUT, "kolors")


def call_api(body: dict, api_key: str) -> dict:
    """POST 到 ENDPOINT（共享传输）。失败 sys.exit 并给可执行提示，不 fallback。"""
    return _cc.post_json(ENDPOINT, body, api_key, TIMEOUT, label="kolors")


def save_image(resp_data: dict, out_path: Path) -> None:
    """响应处理（共享 extract_media）：data[0].url → 下载；data[0].b64_json → 解码；缺失即报错。"""
    _cc.extract_media(resp_data, out_path, label="kolors", min_bytes=1024, download=_download)


def to_curl(body: dict, api_key: str) -> str:
    """dry-run 等价 curl 命令（共享实现：key 掩码 + shlex.quote）。"""
    return _cc.to_curl(ENDPOINT, body, api_key)


# ============================================================================
# CLI
# ============================================================================
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="kolors.py",
        description="wudaozi —— aiping Kolors 云端文生图包装（仅 t2i，不支持图生图）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
示例：
  # 文生图（默认 1024x1024，输出到 $PWD/kolors-output/）
  AIPING_API_KEY=QC-xxx python3 kolors.py t2i -i "一只宇航员在都市街头漫步"

  # 竖屏手机壁纸
  AIPING_API_KEY=QC-xxx python3 kolors.py t2i -i "..." --aspect 9:16

  # 只看 curl 等价命令，不真调（调试用）
  AIPING_API_KEY=QC-xxx python3 kolors.py t2i -i "..." --dry-run

⚠️ Kolors 仅支持文生图；图生图请走 agnes.py / boogu.py。

宽高比预设: """
        + ", ".join(f"{k}={v}" for k, v in IMAGE_SIZES.items()),
    )
    # ponytail: mode 强制 choices=["t2i"]——从 CLI 入口拒绝图生图，Kolors 硬约束。
    p.add_argument(
        "mode", choices=["t2i"], help="t2i=文生图（Kolors 不支持图生图）"
    )
    p.add_argument(
        "--instruction", "-i", required=True, help="生成指令（建议先经 SKILL.md 结构化）"
    )
    p.add_argument(
        "--aspect",
        choices=list(IMAGE_SIZES),
        help="宽高比预设（优先于 --image-size）",
    )
    p.add_argument(
        "--image-size",
        default=None,
        help="自定义 image_size 字符串（如 1328x1328，须 provider 接受）",
    )
    p.add_argument(
        "--output-dir", "-o", default=None, help="输出目录（默认 $PWD/kolors-output/）"
    )
    p.add_argument("--dry-run", action="store_true", help="只打印 curl 不执行")
    p.add_argument(
        "--count",
        type=int,
        default=1,
        help="一次生成 N 张（1-8，并发 4；吸收自 gpt_image_playground 批量生成）",
    )
    a = p.parse_args()
    if not 1 <= a.count <= 8:
        p.error("--count 必须在 1-8 之间")
    return a


def _generate_once(a: argparse.Namespace, api_key: str, index: int, instruction: str | None = None) -> Path:
    """单轮生成（index 用于 count > 1 时的文件名序号），失败抛 SystemExit。
    instruction 缺省取 a.instruction；变体展开时由 main() 传入每份变体。"""
    instruction = instruction if instruction is not None else a.instruction
    out_path = resolve_output(a, index)
    body = build_body(a, instruction)
    label = f"[{index}/{a.count}] " if a.count > 1 else ""
    print(f"{label}[INFO] 输出={out_path}", file=sys.stderr)
    print(f"{label}[CMD] {to_curl(body, api_key)}", file=sys.stderr)
    try:
        # 跨进程并发闸（与 agnes 同理：多会话排队，防 429）
        with _cc.provider_slot("kolors"):
            resp = call_api(body, api_key)
            save_image(resp, out_path)
    except SystemExit as e:
        # 失败留痕：kolors 此前连 sidecar 机制都没有，错误路径先落盘再退出（调研建议#1）
        _cc.raise_with_trace(
            e, out_path, "kolors",
            {"instruction": instruction, "image_size": resolve_image_size(a),
             "count": a.count, "index": index},
        )
    # PNG 文本 chunk 元数据：kolors 此前零元数据，单发图床后参数即丢——内嵌补齐
    _cc.embed_png_metadata(
        out_path, instruction, None,
        {"provider": "kolors", "model": MODEL, "mode": "t2i",
         "image_size": resolve_image_size(a) or "server-default",
         "count": a.count if a.count > 1 else None,
         "index": index if a.count > 1 else None},
    )
    print(
        f"{label}[OK] 已生成: {out_path} ({out_path.stat().st_size // 1024} KB)",
        file=sys.stderr,
    )
    # stdout 管道契约：产物路径一行走 stdout（$(...) 可捕获）；单次 write 防多线程粘连
    sys.stdout.write(f"WUDAOZI_OUTPUT={out_path}\n")
    sys.stdout.flush()
    return out_path


def main() -> int:
    a = parse_args()

    api_key = os.environ.get("AIPING_API_KEY")
    if not api_key:
        _cc.fail(
            "auth_error",
            "未设置 AIPING_API_KEY 环境变量",
            "  → export AIPING_API_KEY=QC-xxx 后重试，或改用 agnes/boogu provider",
        )

    body = build_body(a)

    print(f"[INFO] provider=aiping-Kolors mode={a.mode} count={a.count}", file=sys.stderr)
    print(f"[CMD] {to_curl(body, api_key)}", file=sys.stderr)

    if a.dry_run:
        print("[DRY-RUN] 未执行（无 key / 调试时用）", file=sys.stderr)
        return 0

    # 变体展开：含 {a|b|c} / {_词库_} 语法时每份一份非重复变体；无语法 = 原样 N 份（历史行为）
    segs = _pv.parse_slots(a.instruction)
    instructions = _pv.sample_variants(a.instruction, a.count, random.Random(), segments=segs)
    if _pv.has_variant_syntax(a.instruction):
        print(f"[INFO] 变体展开: {a.count} 份（组合空间 {_pv.combo_count(segs)}，非重复抽样）", file=sys.stderr)

    if a.count == 1:
        _generate_once(a, api_key, 1, instructions[0])
        return 0

    from concurrent.futures import ThreadPoolExecutor

    failures = []
    ok = 0
    with ThreadPoolExecutor(max_workers=min(a.count, BATCH_CONCURRENCY)) as pool:
        futures = {
            pool.submit(_generate_once, a, api_key, i + 1, instructions[i]): i + 1
            for i in range(a.count)
        }
        for fut in futures:
            try:
                fut.result()
                ok += 1
            except SystemExit as e:
                failures.append(str(e))
    print(f"[BATCH] {ok}/{a.count} 已生成，{len(failures)} 失败", file=sys.stderr)
    for msg in failures:
        print(f"[BATCH-FAIL] {msg}", file=sys.stderr)
    if failures:
        sys.exit(1)
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] != "__selfcheck__":
        sys.exit(main())
    # ponytail: 自检 —— 验证纯函数 + 常量 + key 存在性，不打网络。
    from types import SimpleNamespace

    print("== wudaozi kolors self-check ==")
    for k, v in IMAGE_SIZES.items():
        assert isinstance(v, str) and "x" in v, k
    assert resolve_image_size(SimpleNamespace(aspect="9:16", image_size=None)) == "720x1280"
    assert resolve_image_size(SimpleNamespace(aspect=None, image_size="1328x1328")) == "1328x1328"
    assert resolve_image_size(SimpleNamespace(aspect=None, image_size=None)) is None
    body = build_body(SimpleNamespace(instruction="测试", aspect=None, image_size=None))
    assert body == {"model": "Kolors", "prompt": "测试"}  # 不传 image_size
    body2 = build_body(SimpleNamespace(instruction="x", aspect="1:1", image_size=None))
    assert body2["image_size"] == "1024x1024"
    assert resolve_output(SimpleNamespace(output_dir=None)).name.startswith("kolors_t2i_")
    # 变体展开：无语法 = 原样 N 份；有语法 = 非重复
    assert _pv.sample_variants("普通", 2, random.Random(1)) == ["普通", "普通"]
    assert len(set(_pv.sample_variants("{红|蓝|绿}", 3, random.Random(5)))) == 3
    print(f"  宽高比预设: {len(IMAGE_SIZES)} 种")
    print(f"  ENDPOINT: {ENDPOINT}")
    print(f"  MODEL: {MODEL}")
    print(f"  约束: 仅 t2i（Kolors 不支持图生图）")
    print(
        f"  AIPING_API_KEY: {'已设置' if os.environ.get('AIPING_API_KEY') else '未设置'}"
    )
    print("  self-check PASS")
