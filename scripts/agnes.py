#!/usr/bin/env python3
"""wudaozi —— agnes-image 云端文生图/图生图包装脚本。

核心职责（确定性逻辑，纯 stdlib，无本地模型/GPU 依赖）：
1. 构造 agnes API 请求（model/prompt/size + 可选参考图）
2. 调 POST https://apihub.agnes-ai.com/v1/images/generations（Bearer 鉴权）
3. 下载 URL 或解码 base64 存本地 PNG
4. 错误显式报错给用户决定，不自动 fallback 到 boogu

使用：
    AGNES_API_KEY=agn-xxx python agnes.py t2i -i "..." --aspect 1:1
    AGNES_API_KEY=agn-xxx python agnes.py ti2i -i "改背景" --input photo.jpg
    AGNES_API_KEY=agn-xxx python agnes.py t2i -i "..." --dry-run
"""
# ponytail: 云端 API 透传；无本地模型/GPU 依赖；错误不 fallback（用户决策，符合规则12）。
# agnes 是云端黑盒，不支持 seed/steps/cfg，故 CLI 精简——不暴露无意义的旋钮。

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ENDPOINT = "https://apihub.agnes-ai.com/v1/images/generations"
MODEL = "agnes-image-2.1-flash"
TIMEOUT = 60  # ponytail: 单值够用；按 size 分级超时是过早优化

# 自带一份宽高比，解耦 boogu（两 provider 演化路径不同）。
# ponytail: 不做 16 对齐断言——agnes 是云端，是否要求 16 倍数未知，留作联调校准。
# 与 boogu.ASPECT_RATIOS 同值，但刻意不 import 以免跨 provider 耦合。
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

# ti2i 本地参考图支持的格式（agnes 接受 Data URI）
SUPPORTED_MIME = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "gif": "image/gif",
}


def resolve_size(a: argparse.Namespace) -> tuple:
    """解析最终 H×W：aspect > height/width（须同传）> 默认 1:1。

    ponytail: 不做 16 对齐/2048 上限——agnes 限制未知，交给服务端 400 时提示。
    """
    if a.aspect:
        return ASPECT_RATIOS[a.aspect]
    if (a.height is None) != (a.width is None):
        sys.exit("[ERROR] --height 与 --width 必须同时提供；单传请改用 --aspect 预设")
    if a.height and a.width:
        return a.height, a.width
    return ASPECT_RATIOS["1:1"]


def resolve_output(a: argparse.Namespace, height: int, width: int) -> Path:
    """输出路径：默认 $PWD/agnes-output/，文件名含 mode+尺寸+时间戳+uuid8 防覆盖。"""
    out_dir = (
        Path(a.output_dir).resolve() if a.output_dir else Path.cwd() / "agnes-output"
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = int(time.time())
    suffix = uuid.uuid4().hex[:8]
    fname = f"agnes_{a.mode}_{width}x{height}_{ts}_{suffix}.png"
    return out_dir / fname


def image_to_data_uri(path: str) -> str:
    """本地文件 → data:<mime>;base64,<...>。"""
    p = Path(path)
    if not p.exists():
        sys.exit(f"[ERROR] 参考图不存在: {path}")
    ext = p.suffix.lower().lstrip(".")
    mime = SUPPORTED_MIME.get(ext)
    if not mime:
        sys.exit(
            f"[ERROR] 不支持的参考图格式: .{ext}（支持 {'/'.join(SUPPORTED_MIME)}）"
        )
    b64 = base64.b64encode(p.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def build_body(a: argparse.Namespace, height: int, width: int) -> dict:
    """组装 agnes 请求体。

    ⚠️ agnes size 是 WxH 字符串（文档示例 1024x768 为横图），易写反，须测试钉死。
    默认 response_format=url（下载）；--base64 时按文档：t2i 用顶层 return_base64，
    ti2i 用 extra_body.response_format=b64_json。
    """
    extra = {"response_format": "url"}
    if a.base64:
        extra = {} if a.mode == "t2i" else {"response_format": "b64_json"}

    body = {
        "model": MODEL,
        "prompt": a.instruction,
        "size": f"{width}x{height}",  # WxH
        "extra_body": extra,
    }
    if a.base64 and a.mode == "t2i":
        body["return_base64"] = True

    if a.mode == "ti2i":
        if not a.input:
            sys.exit("[ERROR] 图生图(ti2i)必须提供 --input 参考图路径或 URL")
        # 远程 http(s) URL 直接透传；本地路径转 Data URI
        ref = (
            a.input
            if a.input.startswith(("http://", "https://"))
            else image_to_data_uri(a.input)
        )
        extra["image"] = [ref]

    return body


def call_api(body: dict, api_key: str) -> dict:
    """POST 到 ENDPOINT。失败 sys.exit 并给可执行提示，不 fallback。"""
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        ENDPOINT,
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = ""
        try:
            raw = e.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            raw = str(e.reason)
        hint = {
            401: "  → AGNES_API_KEY 失效，检查环境变量",
            429: "  → 限流，稍后重试或联系 provider",
            400: "  → size/prompt 不被接受，换 --aspect 预设或精简 prompt",
        }.get(e.code, "")
        sys.exit(f"[ERROR] agnes HTTP {e.code}: {raw}\n{hint}".rstrip())
    except urllib.error.URLError as e:
        sys.exit(f"[ERROR] agnes 网络不可达: {e.reason}\n  → 检查网络/代理/DNS")
    except TimeoutError:
        sys.exit(f"[ERROR] agnes {TIMEOUT}s 超时，重试或换 provider")


def _download(url: str, out_path: Path) -> None:
    """下载 URL 到文件。urllib 自动跟随重定向（agnes 签名 URL 重定向到 OSS）。"""
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as r:
            out_path.write_bytes(r.read())
    except (urllib.error.URLError, TimeoutError) as e:
        out_path.unlink(missing_ok=True)
        sys.exit(f"[ERROR] 下载 agnes 返回 URL 失败: {e}")


def save_image(resp_data: dict, out_path: Path) -> None:
    """响应处理：data[0].url → 下载；data[0].b64_json → 解码；缺失即报错。"""
    if not resp_data.get("data"):
        sys.exit(f"[ERROR] agnes 响应无 data 字段: {resp_data}")
    item = resp_data["data"][0]
    if rp := item.get("revised_prompt"):
        print(f"[INFO] agnes revised_prompt: {rp}", file=sys.stderr)
    if url := item.get("url"):
        _download(url, out_path)
    elif b64 := item.get("b64_json"):
        out_path.write_bytes(base64.b64decode(b64))
    else:
        sys.exit(f"[ERROR] agnes 响应无 url/b64_json: {item}")
    if out_path.stat().st_size < 1024:
        out_path.unlink(missing_ok=True)
        sys.exit("[FAIL] agnes 返回图片 <1KB，疑似异常")


def to_curl(body: dict, api_key: str) -> str:
    """dry-run 等价 curl 命令。key 截断防泄露，base64 参考图截断防日志爆炸。"""
    sample = json.loads(json.dumps(body))  # 深拷贝避免污染
    extra = sample.get("extra_body", {})
    if "image" in extra:
        v = extra["image"][0]
        if isinstance(v, str) and v.startswith("data:"):
            extra["image"] = [v[:40] + "...(truncated)"]
    return (
        f"curl -X POST {ENDPOINT} \\\n"
        f"  -H 'Authorization: Bearer {api_key[:8]}***' \\\n"
        f"  -H 'Content-Type: application/json' \\\n"
        f"  -d '{json.dumps(sample, ensure_ascii=False)}'"
    )


# ============================================================================
# CLI
# ============================================================================
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="agnes.py",
        description="wudaozi —— agnes-image 云端文生图/图生图包装（构造请求 + 调 API + 存图）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
示例：
  # 文生图（默认 url 返回并下载，1:1）
  AGNES_API_KEY=agn-xxx python agnes.py t2i -i "一只在月光下的橘猫，电影感"

  # 图生图（本地参考图自动转 base64）
  AGNES_API_KEY=agn-xxx python agnes.py ti2i -i "把背景换成沙滩" --input photo.jpg

  # 只看 curl 等价命令，不真调（调试用）
  AGNES_API_KEY=agn-xxx python agnes.py t2i -i "..." --dry-run

宽高比预设: """
        + ", ".join(f"{k}={v[0]}x{v[1]}" for k, v in ASPECT_RATIOS.items()),
    )
    p.add_argument(
        "mode", choices=["t2i", "ti2i"], help="t2i=文生图, ti2i=图生图(编辑)"
    )
    p.add_argument(
        "--instruction", "-i", required=True, help="生成指令（建议先经 SKILL.md 结构化）"
    )
    p.add_argument("--input", help="ti2i 参考图本地路径或公网 URL（ti2i 必填）")
    p.add_argument(
        "--aspect",
        choices=list(ASPECT_RATIOS),
        help="宽高比预设（优先于 --height/--width）",
    )
    p.add_argument(
        "--height", type=int, help="输出高度（须与 --width 同传）"
    )
    p.add_argument("--width", type=int, help="输出宽度（须与 --height 同传）")
    p.add_argument(
        "--output-dir", "-o", default=None, help="输出目录（默认 $PWD/agnes-output/）"
    )
    p.add_argument(
        "--base64",
        action="store_true",
        help="强制 base64 返回（默认 url 下载）",
    )
    p.add_argument("--dry-run", action="store_true", help="只打印 curl 不执行")
    return p.parse_args()


def main() -> int:
    a = parse_args()

    api_key = os.environ.get("AGNES_API_KEY")
    if not api_key:
        sys.exit(
            "[ERROR] 未设置 AGNES_API_KEY 环境变量\n"
            "  → export AGNES_API_KEY=agn-xxx 后重试，或改用 boogu 本地 provider"
        )

    height, width = resolve_size(a)
    out_path = resolve_output(a, height, width)
    body = build_body(a, height, width)

    print(f"[INFO] provider=agnes mode={a.mode} size={width}x{height}", file=sys.stderr)
    print(f"[INFO] 输出={out_path}", file=sys.stderr)
    print(f"[CMD] {to_curl(body, api_key)}", file=sys.stderr)

    if a.dry_run:
        print("[DRY-RUN] 未执行（无 key / 调试时用）", file=sys.stderr)
        return 0

    resp = call_api(body, api_key)
    save_image(resp, out_path)
    print(
        f"[OK] 已生成: {out_path} ({out_path.stat().st_size // 1024} KB)",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] != "__selfcheck__":
        sys.exit(main())
    # ponytail: 自检 —— 验证纯函数 + 常量 + key 存在性，不打网络（不依赖外部资源）。
    from types import SimpleNamespace

    print("== wudaozi agnes self-check ==")
    for k, (h, w) in ASPECT_RATIOS.items():
        assert isinstance(h, int) and isinstance(w, int), k
    assert resolve_size(SimpleNamespace(aspect="9:16", height=None, width=None)) == (
        1824,
        1024,
    )
    assert resolve_size(SimpleNamespace(aspect=None, height=800, width=600)) == (
        800,
        600,
    )
    assert resolve_output(
        SimpleNamespace(mode="t2i", output_dir=None), 1024, 1024
    ).name.startswith("agnes_t2i_1024x1024_")
    body = build_body(SimpleNamespace(
        mode="t2i", instruction="x", input=None, base64=False
    ), 1024, 1024)
    assert body["size"] == "1024x1024"
    assert body["extra_body"]["response_format"] == "url"
    print(f"  宽高比预设: {len(ASPECT_RATIOS)} 种")
    print(f"  ENDPOINT: {ENDPOINT}")
    print(f"  MODEL: {MODEL}")
    print(
        f"  AGNES_API_KEY: {'已设置' if os.environ.get('AGNES_API_KEY') else '未设置'}"
    )
    print("  self-check PASS")
