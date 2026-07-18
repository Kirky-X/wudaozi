#!/usr/bin/env python3
"""wudaozi —— Boogu-Image 文生图/图生图包装脚本。

核心职责（确定性逻辑，纯查找表，不交给模型决策）：
1. 模型矩阵路由：根据 (mode, turbo, quantized) 选官方脚本 + 模型目录
2. 默认参数填充：turbo(4步/无CFG) vs base(50步/CFG) 的关键差异
3. 随机种子：未指定时生成并回显（可复现）
4. 输出路径：默认 $PWD/boogu-output/，文件名含 mode+seed+时间戳防覆盖
5. 资源探测：venv / 模型本地存在性 / GPU 可用性，缺失即明确报错
6. 透传官方 inference.py / inference_turbo.py，不重写推理逻辑

使用：
    python boogu.py t2i --instruction "..." --aspect 1:1
    python boogu.py ti2i --instruction "..." --input img.png --turbo
    python boogu.py t2i --instruction "..." --dry-run   # 只构造命令不执行
"""
# ponytail: 透传官方脚本而非重写推理；矩阵决策是确定性查找表，符合 CLAUDE.md「确定性逻辑禁止交给模型」。

import argparse
import os
import random
import subprocess
import sys
import time
import uuid
from pathlib import Path

# ============================================================================
# 资源定位
# ============================================================================
BOOGU_DIR = Path(__file__).resolve().parents[3] / "software" / "Boogu-Image"
if not BOOGU_DIR.exists():
    BOOGU_DIR = Path(os.path.expanduser("~/software/Boogu-Image"))

VENV_PYTHON = BOOGU_DIR / ".venv" / "bin" / "python"
MODELS_DIR = BOOGU_DIR / "models"

# ============================================================================
# 模型矩阵 —— 8 种组合（2 模式 × 2 速度 × 2 量化）
# ============================================================================
MATRIX = {
    # (mode,    turbo,  quant) : 模型目录名
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

# turbo 的 DMD 默认 sigma（来自官方 inference_turbo_simple.py / test_ti2i_turbo.sh）
TURBO_T2I_SIGMA = 0.001
TURBO_TI2I_SIGMA = 0.0

# A7：通用负向提示模板。未指定 --negative-instruction 时透传，避免 LLM 忘记带。
DEFAULT_NEGATIVE = (
    "模糊, 低品质, 变形, 多余的手指, 透视错误, 水印, 文字, 签名, 过曝, JPEG 伪影"
)

# ============================================================================
# 宽高比预设 —— 全部对齐 16 倍数，长边 ≤ 2048（模型原生 2K 上限）
# ============================================================================
ASPECT_RATIOS = {
    # 元组语义 (H, W)；竖屏 H>W，横屏 W>H。aspect 表示 W:H。
    "1:1": (1024, 1024),
    "3:4": (1360, 1024),  # 竖
    "4:3": (1024, 1360),  # 横
    "2:3": (1536, 1024),  # 竖
    "3:2": (1024, 1536),  # 横
    "9:16": (1824, 1024),  # 手机竖屏
    "16:9": (1024, 1824),  # 横
}
assert all(h % 16 == 0 and w % 16 == 0 for h, w in ASPECT_RATIOS.values()), (
    "宽高比须 16 对齐"
)


def align16(n: int) -> int:
    """向下对齐到 16 的倍数（模型硬约束）。"""
    return max(16, (n // 16) * 16)


def gen_seed() -> int:
    """生成随机种子（未指定时用）。"""
    return random.randint(0, 2**31 - 1)


# ============================================================================
# 资源探测
# ============================================================================
def check_resources(mode: str, turbo: bool, quantized: bool, need_gpu: bool):
    """探测 venv / 模型 / GPU，缺失即 sys.exit 并给出可执行修复建议。"""
    errors, warnings = [], []

    if not BOOGU_DIR.exists():
        errors.append(f"Boogu-Image 目录不存在: {BOOGU_DIR}")
    if not VENV_PYTHON.exists():
        errors.append(
            f"venv python 不存在: {VENV_PYTHON}（在 {BOOGU_DIR} 下创建 .venv）"
        )

    model_name = MATRIX[(mode, turbo, quantized)]
    # B2：fp8 标志与模型目录名一致性（不匹配会让官方脚本加载错权重分支而崩溃）
    if model_name.endswith("-fp8") != quantized:
        errors.append(
            f"fp8 标志与模型不匹配：模型={model_name}，--quantized={quantized}"
        )
    model_path = MODELS_DIR / model_name
    if not model_path.exists():
        local = (
            sorted(p.name for p in MODELS_DIR.glob("Boogu-Image-0.1-*"))
            if MODELS_DIR.exists()
            else []
        )
        errors.append(
            f"模型未下载: models/{model_name}\n"
            f"  本地已有: {local or '（无）'}\n"
            f"  修复：下载该模型到 {MODELS_DIR}/，或换用本地已存在的模型组合"
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
                "GPU 探测失败（nvidia-smi 不可用 / NVML 被拦截）。"
                "如确认无 CUDA，加 --dry-run 仅构造命令；或换 --device cpu（极慢）。"
            )

    for w in warnings:
        print(f"[WARN] {w}", file=sys.stderr)
    if errors:
        print("[ERROR] 资源探测未通过：", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        sys.exit(2)


# ============================================================================
# 命令构造
# ============================================================================
def build_args(a: argparse.Namespace, height: int, width: int, out_path: Path) -> list:
    """组装透传给官方脚本的参数列表（含默认值差异化填充）。"""
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
        # max_input 系列：按官方推荐公式自动算（保证原生分辨率清晰度）
        "--max_input_image_pixels",
        str(height * width),
        "--max_input_image_side_length",
        str(2 * max(height, width)),
    ]

    # 16GB VRAM 环境下 10B 模型必须用 seq CPU offload
    args += ["--enable_sequential_cpu_offload_flag", "True"]

    # B5/A7：None→透传默认负向模板；非空→透传用户值；空字符串→明确禁用不透传
    if a.negative_instruction is None:
        args += ["--negative_instruction", DEFAULT_NEGATIVE]
    elif a.negative_instruction.strip():
        args += ["--negative_instruction", a.negative_instruction]

    if a.mode == "ti2i":
        args += ["--input_image_paths", str(a.input)]

    # 步数与 CFG：turbo vs base 关键差异
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
    """解析最终 H×W：aspect > height/width > 默认 1:1。"""
    if a.aspect:
        return ASPECT_RATIOS[a.aspect]
    # B1：height/width 必须同时提供，单传会静默退回 1:1（竖图变正方形，意图丢失）
    if (a.height is None) != (a.width is None):
        sys.exit("[ERROR] --height 与 --width 必须同时提供；单传请改用 --aspect 预设")
    if a.height and a.width:
        h, w = align16(a.height), align16(a.width)
        if max(h, w) > 2048:
            sys.exit(f"[ERROR] 长边 {max(h, w)} 超模型上限 2048")
        return h, w
    return ASPECT_RATIOS["1:1"]


def resolve_output(a: argparse.Namespace, height: int, width: int) -> Path:
    out_dir = (
        Path(a.output_dir).resolve() if a.output_dir else Path.cwd() / "boogu-output"
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = int(time.time())
    suffix = uuid.uuid4().hex[:8]  # B8：防同秒并发/批量出图文件名冲突
    variant = ("turbo" if a.turbo else "base") + ("_fp8" if a.quantized else "_bf16")
    fname = f"boogu_{a.mode}_{variant}_{a.seed}_{width}x{height}_{ts}_{suffix}.png"
    return out_dir / fname


# ============================================================================
# 参数语义校验
# ============================================================================
def validate_args(a: argparse.Namespace) -> None:
    """校验参数语义硬约束（turbo DMD 推理规则等），违反即 sys.exit。"""
    if a.mode == "ti2i" and not a.input:
        sys.exit("[ERROR] 图生图(ti2i)必须提供 --input 参考图路径")
    if not (30 <= len(a.instruction) <= 400):
        print(
            f"[WARN] instruction 长度 {len(a.instruction)} 不在推荐 30-400 字区间",
            file=sys.stderr,
        )
    if a.turbo:
        # B12：turbo 是 DMD 学生推理，text_guidance 必须 = 1.0（官方硬约束）
        if a.text_guidance is not None and abs(a.text_guidance - 1.0) > 1e-3:
            sys.exit(
                "[ERROR] turbo 模式 text_guidance 必须 = 1.0（DMD 学生推理硬约束）"
            )
        # B11：turbo 为 4 步 DMD 蒸馏调优，改 steps 易发散
        if a.steps is not None and a.steps != 4:
            print(
                f"[WARN] turbo 是 4 步 DMD 蒸馏，当前 steps={a.steps} 可能发散",
                file=sys.stderr,
            )


# ============================================================================
# CLI
# ============================================================================
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="boogu.py",
        description="wudaozi —— Boogu-Image 文生图/图生图包装（模型矩阵 + 默认值 + 种子 + 输出路径）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
示例：
  # 文生图，1:1，base，自动随机种子
  python boogu.py t2i --instruction "一只在月光下的橘猫，电影感"

  # 文生图，turbo + 竖屏 9:16，指定种子复现
  python boogu.py t2i --instruction "..." --turbo --aspect 9:16 --seed 42

  # 图生图（编辑），fp8 量化省显存
  python boogu.py ti2i --instruction "把背景换成沙滩" --input photo.jpg --quantized

  # 只看会跑什么命令，不真跑（无 GPU 时调试用）
  python boogu.py t2i --instruction "..." --dry-run

宽高比预设: """
        + ", ".join(f"{k}={v[0]}x{v[1]}" for k, v in ASPECT_RATIOS.items()),
    )
    p.add_argument(
        "mode", choices=["t2i", "ti2i"], help="t2i=文生图, ti2i=图生图(编辑)"
    )
    p.add_argument(
        "--instruction",
        "-i",
        required=True,
        help="生成指令（建议先经 SKILL.md 结构化）",
    )
    p.add_argument(
        "--negative-instruction",
        default=None,
        help="负向提示；不传则用内置通用模板，传空字符串禁用",
    )
    p.add_argument("--input", help="ti2i 参考图路径（ti2i 必填）")

    # ponytail: aspect 与 H/W 的互斥由 resolve_size 统一校验（aspect 优先）；
    # height/width 须配套同传，单传由 resolve_size 拒绝。不入 argparse 互斥组以保持对称。
    p.add_argument(
        "--aspect",
        choices=list(ASPECT_RATIOS),
        help="宽高比预设（优先于 --height/--width）",
    )
    p.add_argument(
        "--height",
        type=int,
        help="输出高度（须与 --width 同传，16 对齐，模型上限 2048）",
    )
    p.add_argument("--width", type=int, help="输出宽度（须与 --height 同传，16 对齐）")

    p.add_argument(
        "--turbo",
        action="store_true",
        help="用 turbo 模型（4 步 DMD，快约 10×，无 CFG）",
    )
    p.add_argument(
        "--quantized",
        action="store_true",
        help="用 fp8 量化模型（省约 50%% 显存，画质略降）",
    )
    p.add_argument(
        "--seed", type=int, default=None, help="随机种子；不传则自动生成并回显"
    )
    p.add_argument(
        "--steps", type=int, default=None, help="覆盖默认步数（base=50, turbo=4）"
    )
    p.add_argument(
        "--text-guidance",
        type=float,
        default=None,
        help="覆盖默认 text CFG（base=4.0, turbo=1.0）",
    )
    p.add_argument(
        "--dmd-sigma",
        type=float,
        default=None,
        help="覆盖 turbo 默认 dmd_conditioning_sigma",
    )
    p.add_argument(
        "--device", default="cuda:0", help="设备（默认 cuda:0；无 GPU 试 cpu）"
    )
    p.add_argument(
        "--output-dir", "-o", default=None, help="输出目录（默认 $PWD/boogu-output/）"
    )
    p.add_argument("--dry-run", action="store_true", help="只打印命令不执行")
    return p.parse_args()


def main() -> int:
    a = parse_args()
    validate_args(a)  # ti2i 必填 + turbo 硬约束（B11/B12）

    if a.seed is None:
        a.seed = gen_seed()
        print(
            f"[INFO] 未指定 --seed，已生成 seed={a.seed}（复现请加 --seed {a.seed}）",
            file=sys.stderr,
        )

    height, width = resolve_size(a)
    out_path = resolve_output(a, height, width)

    # B3：dry-run 跳过资源检查，让无 GPU/无模型的机器也能构造命令
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
    # ponytail: env["device"] 兼容官方 test_*.sh 的 shell 别名读取；argparse --device 是主通道（B15 暂留）。
    env["device"] = a.device

    print(f"[INFO] 模式={a.mode} turbo={a.turbo} 量化={a.quantized}", file=sys.stderr)
    print(
        f"[INFO] 模型={MATRIX[(a.mode, a.turbo, a.quantized)]} 尺寸={width}x{height}",
        file=sys.stderr,
    )
    print(f"[INFO] 输出={out_path}", file=sys.stderr)
    print(f"[CMD] {' '.join(cmd)}", file=sys.stderr)

    if a.dry_run:
        print("[DRY-RUN] 未执行（无 GPU / 调试时用）", file=sys.stderr)
        return 0

    try:
        result = subprocess.run(cmd, cwd=str(BOOGU_DIR), env=env)
    except KeyboardInterrupt:
        out_path.unlink(missing_ok=True)
        print("[CANCEL] 用户中断，已清理半成品", file=sys.stderr)
        return 130

    # B18/B20：失败清理半成品 + 成功校验文件大小，避免静默成功/数据丢失
    if (
        result.returncode != 0
        or not out_path.exists()
        or out_path.stat().st_size < 1024
    ):
        out_path.unlink(missing_ok=True)
        print(
            f"[FAIL] 退出码={result.returncode} seed={a.seed} "
            f"模型={MATRIX[(a.mode, a.turbo, a.quantized)]}",
            file=sys.stderr,
        )
        return result.returncode or 1
    print(
        f"[OK] 已生成: {out_path} ({out_path.stat().st_size // 1024} KB)",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] != "__selfcheck__":
        sys.exit(main())
    # ponytail: 自检 —— 验证矩阵查表与 16 对齐，不依赖 GPU/模型。
    print("== wudaozi self-check ==")
    for key, name in MATRIX.items():
        assert name.startswith("Boogu-Image-0.1-"), key
    for h, w in ASPECT_RATIOS.values():
        assert h % 16 == 0 and w % 16 == 0
    assert align16(1365) == 1360
    assert align16(17) == 16
    print(f"  矩阵组合: {len(MATRIX)} 种")
    print(f"  宽高比预设: {len(ASPECT_RATIOS)} 种，全部 16 对齐")
    print(
        f"  Boogu-Image 目录: {BOOGU_DIR} ({'存在' if BOOGU_DIR.exists() else '缺失'})"
    )
    print(
        f"  venv python: {VENV_PYTHON} ({'存在' if VENV_PYTHON.exists() else '缺失'})"
    )
    local = (
        sorted(p.name for p in MODELS_DIR.glob("Boogu-Image-0.1-*"))
        if MODELS_DIR.exists()
        else []
    )
    print(f"  本地模型: {local or '（无）'}")
    print("  self-check PASS")
