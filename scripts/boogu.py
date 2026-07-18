#!/usr/bin/env python3
"""wudaozi — Boogu-Image text-to-image/image-to-image wrapper script.

Core responsibilities (deterministic logic, pure lookup table, not delegated to model):
1. Model matrix routing: select official script + model directory by (mode, turbo, quantized)
2. Default parameter filling: turbo (4 steps/no CFG) vs base (50 steps/CFG) key differences
3. Random seed: generate and echo when not specified (for reproducibility)
4. Output path: default $PWD/boogu-output/, filename includes mode+seed+timestamp to prevent overwriting
5. Resource detection: venv / model local availability / GPU availability, report errors explicitly when missing
6. Passthrough to official inference.py / inference_turbo.py, don't rewrite inference logic

Usage:
    python boogu.py t2i --instruction "..." --aspect 1:1
    python boogu.py ti2i --instruction "..." --input img.png --turbo
    python boogu.py t2i --instruction "..." --dry-run   # Only construct command, don't execute
"""
# ponytail: Passthrough to official scripts rather than rewriting inference; matrix decision is deterministic lookup table, follows CLAUDE.md "deterministic logic must not be delegated to model".

import argparse
import os
import random
import subprocess
import sys
import time
import uuid
from pathlib import Path

# ============================================================================
# Resource Location
# ============================================================================
BOOGU_DIR = Path(__file__).resolve().parents[3] / "software" / "Boogu-Image"
if not BOOGU_DIR.exists():
    BOOGU_DIR = Path(os.path.expanduser("~/software/Boogu-Image"))

VENV_PYTHON = BOOGU_DIR / ".venv" / "bin" / "python"
MODELS_DIR = BOOGU_DIR / "models"

# ============================================================================
# Model Matrix — 8 combinations (2 modes × 2 speeds × 2 quantizations)
# ============================================================================
MATRIX = {
    # (mode,    turbo,  quant) : Model directory name
    ("t2i", False, False): "Boogu-Image-0.1-Base",
    ("t2i", False, True): "Boogu-Image-0.1-Base-fp8",
    ("t2i", True, False): "Boogu-Image-0.1-Turbo",
    ("t2i", True, True): "Boogu-Image-0.1-Turbo-fp8",
    ("ti2i", False, False): "Boogu-Image-0.1-Edit",
    ("ti2i", False, True): "Boogu-Image-0.1-Edit-fp8",
    ("ti2i", True, False): "Boogu-Image-0.1-Edit-Turbo",
    ("ti2i", True, True): "Boogu-Image-0.1-Edit-Turbo-fp8",
}
SCRIPT_FOR_TURBO = {False: "inference.py", True: "inference_turbo.py"}

# Turbo's DMD default sigma (from official inference_turbo_simple.py / test_ti2i_turbo.sh)
TURBO_T2I_SIGMA = 0.001
TURBO_TI2I_SIGMA = 0.0

# A7: General negative prompt template. Passed through when --negative-instruction not specified, prevents LLM from forgetting.
DEFAULT_NEGATIVE = (
    "模糊, 低品质, 变形, 多余的手指, 透视错误, 水印, 文字, 签名, 过曝, JPEG 伪影"
)

# ============================================================================
# Aspect Ratio Presets — all aligned to 16 multiples, longest side ≤ 2048 (model native 2K limit)
# ============================================================================
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
assert all(h % 16 == 0 and w % 16 == 0 for h, w in ASPECT_RATIOS.values()), (
    "Aspect ratios must be 16-aligned"
)


def align16(n: int) -> int:
    """Align down to nearest multiple of 16 (model hard constraint)."""
    return max(16, (n // 16) * 16)


def gen_seed() -> int:
    """Generate random seed (used when not specified)."""
    return random.randint(0, 2**31 - 1)


# ============================================================================
# Resource Detection
# ============================================================================
def check_resources(mode: str, turbo: bool, quantized: bool, need_gpu: bool):
    """Detect venv / model / GPU; exit with actionable fix suggestions when missing."""
    errors, warnings = [], []

    if not BOOGU_DIR.exists():
        errors.append(f"Boogu-Image directory does not exist: {BOOGU_DIR}")
    if not VENV_PYTHON.exists():
        errors.append(
            f"venv python does not exist: {VENV_PYTHON} (create .venv under {BOOGU_DIR})"
        )

    model_name = MATRIX[(mode, turbo, quantized)]
    # B2: fp8 flag must match model directory name (mismatch causes official script to load wrong weight branch and crash)
    if model_name.endswith("-fp8") != quantized:
        errors.append(
            f"fp8 flag mismatch with model: model={model_name}, --quantized={quantized}"
        )
    model_path = MODELS_DIR / model_name
    if not model_path.exists():
        local = (
            sorted(p.name for p in MODELS_DIR.glob("Boogu-Image-0.1-*"))
            if MODELS_DIR.exists()
            else []
        )
        errors.append(
            f"Model not downloaded: models/{model_name}\n"
            f"  Local available: {local or '(none)'}\n"
            f"  Fix: download this model to {MODELS_DIR}/, or switch to locally available model combination"
        )

    if need_gpu:
        try:
            subprocess.run(
                ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                capture_output=True,
                check=True,
                timeout=5,
            )
        except (
            FileNotFoundError,
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
        ):
            warnings.append(
                "GPU detection failed (nvidia-smi unavailable / NVML blocked)."
                "If confirmed no CUDA, add --dry-run to only construct command; or use --device cpu (very slow)."
            )

    for w in warnings:
        print(f"[WARN] {w}", file=sys.stderr)
    if errors:
        print("[ERROR] Resource detection failed:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        sys.exit(2)


# ============================================================================
# Command Construction
# ============================================================================
def build_args(a: argparse.Namespace, height: int, width: int, out_path: Path) -> list:
    """Assemble parameter list for passthrough to official script (with default value differentiation)."""
    args = [
        "--pretrained_pipeline_name_or_path",
        str(MODELS_DIR / MATRIX[(a.mode, a.turbo, a.quantized)]),
        "--instruction",
        a.instruction,
        "--height",
        str(height),
        "--width",
        str(width),
        "--seed",
        str(a.seed),
        "--output_image_path",
        str(out_path),
        "--device",
        a.device,
        # max_input series: auto-calculated by official recommended formula (ensures native resolution clarity)
        "--max_input_image_pixels",
        str(height * width),
        "--max_input_image_side_length",
        str(2 * max(height, width)),
    ]

    # 16GB VRAM environment requires sequential CPU offload for 10B models
    args += ["--enable_sequential_cpu_offload_flag", "True"]

    # B5/A7: None → passthrough default negative template; non-empty → passthrough user value; empty string → explicitly disabled, don't passthrough
    if a.negative_instruction is None:
        args += ["--negative_instruction", DEFAULT_NEGATIVE]
    elif a.negative_instruction.strip():
        args += ["--negative_instruction", a.negative_instruction]

    if a.mode == "ti2i":
        args += ["--input_image_paths", str(a.input)]

    # Steps and CFG: key difference between turbo vs base
    if a.turbo:
        if a.steps is None:
            args += ["--num_inference_steps", "4"]
        if a.text_guidance is None:
            args += ["--text_guidance_scale", "1.0"]
        args += ["--image_guidance_scale", "1.0"]
        sigma = TURBO_TI2I_SIGMA if a.mode == "ti2i" else TURBO_T2I_SIGMA
        args += [
            "--dmd_conditioning_sigma",
            str(a.dmd_sigma if a.dmd_sigma is not None else sigma),
        ]
        if a.mode == "ti2i":
            args += ["--empty_instruction_guidance_scale", "0.0"]
    else:
        args += ["--num_inference_steps", str(a.steps if a.steps is not None else 50)]
        args += [
            "--text_guidance_scale",
            str(a.text_guidance if a.text_guidance is not None else 4.0),
        ]
        if a.mode == "ti2i":
            args += ["--image_guidance_scale", "1.0"]

    if a.quantized:
        args += ["--use_fp8_weights", "True"]

    return args


def resolve_size(a: argparse.Namespace) -> tuple:
    """Resolve final H×W: aspect > height/width > default 1:1."""
    if a.aspect:
        return ASPECT_RATIOS[a.aspect]
    # B1: height/width must be provided together; single parameter silently falls back to 1:1 (portrait becomes square, intent lost)
    if (a.height is None) != (a.width is None):
        sys.exit("[ERROR] --height and --width must be provided together; use --aspect presets for single dimension")
    if a.height and a.width:
        h, w = align16(a.height), align16(a.width)
        if max(h, w) > 2048:
            sys.exit(f"[ERROR] Longest side {max(h, w)} exceeds model limit 2048")
        return h, w
    return ASPECT_RATIOS["1:1"]


def resolve_output(a: argparse.Namespace, height: int, width: int) -> Path:
    out_dir = (
        Path(a.output_dir).resolve() if a.output_dir else Path.cwd() / "boogu-output"
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = int(time.time())
    suffix = uuid.uuid4().hex[:8]  # B8: Prevent same-second concurrent/batch output filename conflicts
    variant = ("turbo" if a.turbo else "base") + ("_fp8" if a.quantized else "_bf16")
    fname = f"boogu_{a.mode}_{variant}_{a.seed}_{width}x{height}_{ts}_{suffix}.png"
    return out_dir / fname


# ============================================================================
# Parameter Semantic Validation
# ============================================================================
def validate_args(a: argparse.Namespace) -> None:
    """Validate parameter semantic hard constraints (turbo DMD inference rules, etc.), exit on violation."""
    if a.mode == "ti2i" and not a.input:
        sys.exit("[ERROR] Image-to-image (ti2i) requires --input reference image path")
    if not (30 <= len(a.instruction) <= 400):
        print(
            f"[WARN] instruction length {len(a.instruction)} not in recommended 30-400 character range",
            file=sys.stderr,
        )
    if a.turbo:
        # B12: turbo is DMD student inference, text_guidance must = 1.0 (official hard constraint)
        if a.text_guidance is not None and abs(a.text_guidance - 1.0) > 1e-3:
            sys.exit(
                "[ERROR] turbo mode text_guidance must = 1.0 (DMD student inference hard constraint)"
            )
        # B11: turbo is 4-step DMD distillation, changing steps may cause divergence
        if a.steps is not None and a.steps != 4:
            print(
                f"[WARN] turbo is 4-step DMD distillation, current steps={a.steps} may diverge",
                file=sys.stderr,
            )


# ============================================================================
# CLI
# ============================================================================
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="boogu.py",
        description="wudaozi — Boogu-Image text-to-image/image-to-image wrapper (model matrix + defaults + seed + output path)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  # Text-to-image, 1:1, base, auto random seed
  python boogu.py t2i --instruction "an orange cat under moonlight, cinematic"

  # Text-to-image, turbo + portrait 9:16, specified seed for reproducibility
  python boogu.py t2i --instruction "..." --turbo --aspect 9:16 --seed 42

  # Image-to-image (editing), fp8 quantization to save VRAM
  python boogu.py ti2i --instruction "change background to beach" --input photo.jpg --quantized

  # Only view what command would run, don't actually run (for debugging without GPU)
  python boogu.py t2i --instruction "..." --dry-run

Aspect ratio presets: """
        + ", ".join(f"{k}={v[0]}x{v[1]}" for k, v in ASPECT_RATIOS.items()),
    )
    p.add_argument(
        "mode", choices=["t2i", "ti2i"], help="t2i=text-to-image, ti2i=image-to-image (editing)"
    )
    p.add_argument(
        "--instruction",
        "-i",
        required=True,
        help="Generation instruction (recommended to structure via SKILL.md first)",
    )
    p.add_argument(
        "--negative-instruction",
        default=None,
        help="Negative prompt; not passed uses built-in general template, empty string disables",
    )
    p.add_argument("--input", help="ti2i reference image path (required for ti2i)")

    # ponytail: aspect vs H/W mutual exclusion unified by resolve_size (aspect takes priority);
    # height/width must be paired; single parameter rejected by resolve_size. Not using argparse mutual exclusion group to maintain symmetry.
    p.add_argument(
        "--aspect",
        choices=list(ASPECT_RATIOS),
        help="Aspect ratio preset (takes priority over --height/--width)",
    )
    p.add_argument(
        "--height",
        type=int,
        help="Output height (must be provided with --width, 16-aligned, model limit 2048)",
    )
    p.add_argument("--width", type=int, help="Output width (must be provided with --height, 16-aligned)")

    p.add_argument(
        "--turbo",
        action="store_true",
        help="Use turbo model (4-step DMD, ~10× faster, no CFG)",
    )
    p.add_argument(
        "--quantized",
        action="store_true",
        help="Use fp8 quantized model (saves ~50%% VRAM, slight quality loss)",
    )
    p.add_argument(
        "--seed", type=int, default=None, help="Random seed; if not provided, auto-generated and echoed"
    )
    p.add_argument(
        "--steps", type=int, default=None, help="Override default steps (base=50, turbo=4)"
    )
    p.add_argument(
        "--text-guidance",
        type=float,
        default=None,
        help="Override default text CFG (base=4.0, turbo=1.0)",
    )
    p.add_argument(
        "--dmd-sigma",
        type=float,
        default=None,
        help="Override turbo default dmd_conditioning_sigma",
    )
    p.add_argument(
        "--device", default="cuda:0", help="Device (default cuda:0; try cpu if no GPU)"
    )
    p.add_argument(
        "--output-dir", "-o", default=None, help="Output directory (default $PWD/boogu-output/)"
    )
    p.add_argument("--dry-run", action="store_true", help="Only print command, don't execute")
    return p.parse_args()


def main() -> int:
    a = parse_args()
    validate_args(a)  # ti2i required + turbo hard constraints (B11/B12)

    if a.seed is None:
        a.seed = gen_seed()
        print(
            f"[INFO] --seed not specified, generated seed={a.seed} (add --seed {a.seed} to reproduce)",
            file=sys.stderr,
        )

    height, width = resolve_size(a)
    out_path = resolve_output(a, height, width)

    # B3: dry-run skips resource check, allowing machines without GPU/model to construct commands
    if not a.dry_run:
        check_resources(
            a.mode,
            a.turbo,
            a.quantized,
            need_gpu=a.device.startswith("cuda"),
        )

    cli_args = build_args(a, height, width, out_path)
    script = BOOGU_DIR / SCRIPT_FOR_TURBO[a.turbo]
    cmd = [str(VENV_PYTHON), str(script)] + cli_args

    env = os.environ.copy()
    env["PYTHONPATH"] = f"{BOOGU_DIR}:{env.get('PYTHONPATH', '')}"
    # ponytail: env["device"] compatible with official test_*.sh shell alias reading; argparse --device is the primary channel (B15 placeholder).
    env["device"] = a.device

    print(f"[INFO] mode={a.mode} turbo={a.turbo} quantized={a.quantized}", file=sys.stderr)
    print(
        f"[INFO] model={MATRIX[(a.mode, a.turbo, a.quantized)]} size={width}x{height}",
        file=sys.stderr,
    )
    print(f"[INFO] output={out_path}", file=sys.stderr)
    print(f"[CMD] {' '.join(cmd)}", file=sys.stderr)

    if a.dry_run:
        print("[DRY-RUN] Not executed (no GPU / for debugging)", file=sys.stderr)
        return 0

    try:
        result = subprocess.run(cmd, cwd=str(BOOGU_DIR), env=env)
    except KeyboardInterrupt:
        out_path.unlink(missing_ok=True)
        print("[CANCEL] User interrupted, cleaned up partial output", file=sys.stderr)
        return 130

    # B18/B20: Clean up partial output on failure + validate file size on success, prevent silent success/data loss
    if (
        result.returncode != 0
        or not out_path.exists()
        or out_path.stat().st_size < 1024
    ):
        out_path.unlink(missing_ok=True)
        print(
            f"[FAIL] exit_code={result.returncode} seed={a.seed} "
            f"model={MATRIX[(a.mode, a.turbo, a.quantized)]}",
            file=sys.stderr,
        )
        return result.returncode or 1
    print(
        f"[OK] Generated: {out_path} ({out_path.stat().st_size // 1024} KB)",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] != "__selfcheck__":
        sys.exit(main())
    # ponytail: Self-check — validates matrix lookup and 16-alignment, no GPU/model dependency.
    print("== wudaozi self-check ==")
    for key, name in MATRIX.items():
        assert name.startswith("Boogu-Image-0.1-"), key
    for h, w in ASPECT_RATIOS.values():
        assert h % 16 == 0 and w % 16 == 0
    assert align16(1365) == 1360
    assert align16(17) == 16
    print(f"  Matrix combinations: {len(MATRIX)}")
    print(f"  Aspect ratio presets: {len(ASPECT_RATIOS)}, all 16-aligned")
    print(
        f"  Boogu-Image directory: {BOOGU_DIR} ({'exists' if BOOGU_DIR.exists() else 'missing'})"
    )
    print(
        f"  venv python: {VENV_PYTHON} ({'exists' if VENV_PYTHON.exists() else 'missing'})"
    )
    local = (
        sorted(p.name for p in MODELS_DIR.glob("Boogu-Image-0.1-*"))
        if MODELS_DIR.exists()
        else []
    )
    print(f"  Local models: {local or '(none)'}")
    print("  self-check PASS")
