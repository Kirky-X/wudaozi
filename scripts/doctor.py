#!/usr/bin/env python3
"""wudaozi —— provider 就绪自检（doctor）。只读检查：不调任何 API、不跑推理。

一条命令回答"我现在能用什么"：
- key 存在性（AGNES_API_KEY / AIPING_API_KEY）
- boogu 本地栈：目录 / venv / GPU（nvidia-smi）/ 本地模型清单
- 能力 × provider 可用矩阵 + 默认路由结论（SKILL.md 路由规则的机器可读版）

退出码：**没有任何可用能力**（无 key 且 boogu 不可用）→ 1；否则 0。
单项缺失不是失败（只有 agnes key 也是完全可用的合法状态），矩阵里逐项标 ✗ 与原因。

用法：
    python3 scripts/doctor.py            # 人读报告（stdout）
    AGNES_API_KEY=agn-xxx python3 scripts/doctor.py

boogu 的目录/venv/模型常量从 boogu.py 导入（单一来源）；GPU 检测独立实现——
boogu.check_resources 是"缺了就退出"的生成前置语义，doctor 是"收集报告"语义。
"""
# ponytail: 就绪判定是确定性查表（规则5），每个结论都必须可追溯到一次真实探测。

import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import boogu  # noqa: E402  # BOOGU_DIR / VENV_PYTHON / MODELS_DIR / MATRIX 单一来源

KEY_ENVS = ("AGNES_API_KEY", "AIPING_API_KEY")
# 按 mode 从 boogu.MATRIX 派生（单一来源，MATRIX 改名不漂移）
BOOGU_T2I_MODELS = frozenset(name for (mode, _, _), name in boogu.MATRIX.items() if mode == "t2i")
BOOGU_TI2I_MODELS = frozenset(name for (mode, _, _), name in boogu.MATRIX.items() if mode == "ti2i")


def check_keys() -> dict:
    return {env: bool(os.environ.get(env)) for env in KEY_ENVS}


def check_gpu() -> tuple:
    """(可用, 描述)。NVML 被系统屏蔽时只影响 boogu 实际生成（dry-run 仍可用）。"""
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=5, check=True,
        )
        return True, r.stdout.strip().splitlines()[0]
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False, "nvidia-smi 不可用（无 CUDA 或 NVML 被屏蔽，boogu 只能 --dry-run）"


def local_models() -> list:
    if not boogu.MODELS_DIR.is_dir():
        return []
    return sorted(p.name for p in boogu.MODELS_DIR.glob("Boogu-Image-0.1-*"))


def check_boogu() -> dict:
    models = local_models()
    ok = boogu.BOOGU_DIR.exists() and boogu.VENV_PYTHON.exists() and bool(models)
    gpu_ok, gpu_desc = check_gpu()
    return {
        "ok": ok,
        "dir": boogu.BOOGU_DIR.exists(),
        "venv": boogu.VENV_PYTHON.exists(),
        "gpu": gpu_ok,
        "gpu_desc": gpu_desc,
        "models": models,
    }


def build_matrix(keys: dict, bg: dict) -> list:
    """能力 × provider 可用矩阵：[(能力, [(provider, 可用, 原因), ...]), ...]"""
    agnes = keys["AGNES_API_KEY"]
    aiping = keys["AIPING_API_KEY"]
    boogu_ready = bg["ok"]

    def boogu_for(names: frozenset) -> tuple:
        if not boogu_ready:
            return False, "boogu 未就绪(dir/venv/模型缺一)"
        hit = sorted(m for m in names if m in bg["models"])
        return (bool(hit), f"本地模型 {hit}" if hit else f"需下载 {sorted(names)[:2]} 等")

    return [
        ("t2i", [
            ("agnes", agnes, "AGNES_API_KEY" if agnes else "未设 AGNES_API_KEY"),
            ("kolors", aiping, "AIPING_API_KEY" if aiping else "未设 AIPING_API_KEY"),
            ("boogu", *boogu_for(BOOGU_T2I_MODELS)),
        ]),
        ("ti2i", [
            ("agnes", agnes, "AGNES_API_KEY" if agnes else "未设 AGNES_API_KEY"),
            ("boogu", *boogu_for(BOOGU_TI2I_MODELS)),
        ]),
        ("vision", [
            ("agnes", agnes, "AGNES_API_KEY" if agnes else "未设 AGNES_API_KEY"),
            ("aiping", aiping, "AIPING_API_KEY" if aiping else "未设 AIPING_API_KEY"),
        ]),
        ("video", [
            ("agnes", agnes, "AGNES_API_KEY" if agnes else "未设 AGNES_API_KEY"),
        ]),
    ]


def route_conclusion(keys: dict, bg: dict) -> str:
    """默认路由结论（对齐 SKILL.md Default routing 一节）。"""
    agnes, aiping = keys["AGNES_API_KEY"], keys["AIPING_API_KEY"]
    if agnes:
        s = "AGNES_API_KEY 已设置 → 图像/理解/视频默认 agnes"
        if aiping:
            s += ";kolors 作为 t2i 限流备选"
        if bg["ok"]:
            s += f";boogu 本地可手动指定（GPU: {'可用' if bg['gpu'] else '不可用，仅 --dry-run'}）"
        return s
    parts = []
    if aiping:
        parts.append("t2i→kolors、OCR/看图→aiping")
    if bg["ok"]:
        parts.append("图像生成→boogu 本地" + ("（GPU 可用）" if bg["gpu"] else "（⚠️ GPU 不可用，只能 --dry-run）"))
    if not parts:
        return "无任何可用 provider → 先配置 AGNES_API_KEY（推荐）或 AIPING_API_KEY，或在 CUDA 机器部署 boogu"
    return "AGNES_API_KEY 未设置 → " + "；".join(parts) + "；视频与 agnes 系能力不可用（需 key）"


def main() -> int:
    print("== wudaozi doctor ==")
    keys = check_keys()
    for env, present in keys.items():
        print(f"[key] {env}: {'set' if present else 'not set'}")

    bg = check_boogu()
    print(
        f"[boogu] dir={'ok' if bg['dir'] else 'missing'} venv={'ok' if bg['venv'] else 'missing'} "
        f"GPU={'可用' if bg['gpu'] else '不可用'}（{bg['gpu_desc']}）"
    )
    print(f"[boogu] models: {bg['models'] or '(none)'}")

    matrix = build_matrix(keys, bg)
    print("[matrix]")
    any_usable = False
    for cap, providers in matrix:
        cells = []
        for name, ok, reason in providers:
            any_usable = ok or any_usable
            cells.append(f"{name} {'✓' if ok else '✗(' + reason + ')'}")
        print(f"  {cap:7s} " + "  ".join(cells))

    print(f"[route] {route_conclusion(keys, bg)}")
    if not any_usable:
        print("[RESULT] 没有任何可用能力（exit 1）", file=sys.stderr)
        return 1
    print("[RESULT] 至少一条可用链路（exit 0）", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
