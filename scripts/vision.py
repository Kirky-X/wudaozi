#!/usr/bin/env python3
"""wudaozi —— 图像理解（VLM）双 provider 包装脚本。

支持两个视觉语言模型，用同一种 OpenAI 兼容 chat/completions 接口：
- agnes（agnes-2.0-flash）：文档称只支持 image_url 公网 URL，实测 base64 data URI 也能用
- aiping（DeepSeek-OCR-2）：image_url（URL 或 base64 data URI）

核心职责（纯 stdlib）：
1. 解析图片输入：本地路径 → base64 data URI；http(s) URL → 透传
2. 构造 chat/completions 请求（messages content array：image_url + text）
3. 调对应 provider，提取 content 打印到 stdout（可选 --output 存 txt）
4. 错误显式报错，不 fallback

使用：
    AGNES_API_KEY=agn-xxx python3 vision.py agnes --image photo.jpg -q "这张图里有什么"
    AGNES_API_KEY=agn-xxx python3 vision.py agnes --image https://... -q "..."
    AIPING_API_KEY=QC-xxx python3 vision.py aiping --image photo.jpg -q "这道题怎么解"
"""
# ponytail: 两 provider 都是 OpenAI 兼容 chat/completions，统一抽象为 PROVIDERS 查找表（规则5）。
# 默认非 stream——非 stream 实测两 provider 都能拿完整 content；stream 是 UX 优化，YAGNI。

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

TIMEOUT = 180  # VLM 推理比图像生成慢（复杂 OCR/解题可达 90s+），给足余量

# 确定性查找表：provider → endpoint/model/key 环境变量
PROVIDERS = {
    "agnes": {
        "endpoint": "https://apihub.agnes-ai.com/v1/chat/completions",
        "model": "agnes-2.0-flash",
        "key_env": "AGNES_API_KEY",
        "hint": "agnes-image-2.1-flash 是文生图，图像理解用 agnes-2.0-flash（本脚本）",
    },
    "aiping": {
        "endpoint": "https://www.aiping.cn/api/v1/chat/completions",
        "model": "DeepSeek-OCR-2",
        "key_env": "AIPING_API_KEY",
        "hint": "aiping DeepSeek-OCR-2，OCR/图文理解强项",
    },
}

# 图片支持的格式（base64 data URI）
SUPPORTED_MIME = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "gif": "image/gif",
}


def image_to_data_uri(path: str) -> str:
    """本地文件 → data:<mime>;base64,<...>。"""
    p = Path(path)
    if not p.exists():
        sys.exit(f"[ERROR] 图片不存在: {path}")
    # VLM 输入约束：>20MB 的图转 base64 会撑爆请求体（base64 膨胀 ~33%）
    size = p.stat().st_size
    if size > 20 * 1024 * 1024:
        sys.exit(
            f"[ERROR] 图片 {size // 1024 // 1024}MB > 20MB 上限\n"
            "  → 先压缩或降分辨率，或改用公网 URL 输入"
        )
    ext = p.suffix.lower().lstrip(".")
    mime = SUPPORTED_MIME.get(ext)
    if not mime:
        sys.exit(
            f"[ERROR] 不支持的图片格式: .{ext}（支持 {'/'.join(SUPPORTED_MIME)}）"
        )
    b64 = base64.b64encode(p.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def resolve_image_input(path: str) -> str:
    """远程 http(s) URL 直接透传；本地路径转 data URI。"""
    if path.startswith(("http://", "https://")):
        return path
    return image_to_data_uri(path)


def build_body(provider: str, image_input: str, question: str, max_tokens: int) -> dict:
    """组装 chat/completions 请求体（OpenAI 兼容 content array）。"""
    return {
        "model": PROVIDERS[provider]["model"],
        "max_tokens": max_tokens,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": image_input}},
                    {"type": "text", "text": question},
                ],
            }
        ],
    }


def call_api(provider: str, body: dict, api_key: str) -> dict:
    """POST 到 provider endpoint。失败 sys.exit 并给可执行提示。"""
    cfg = PROVIDERS[provider]
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        cfg["endpoint"],
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
            401: f"  → {cfg['key_env']} 失效，检查环境变量",
            429: "  → 限流，稍后重试",
            400: "  → 图片/question 格式不被接受，换图或精简 question",
        }.get(e.code, "")
        sys.exit(f"[ERROR] {provider} HTTP {e.code}: {raw}\n{hint}".rstrip())
    except urllib.error.URLError as e:
        sys.exit(f"[ERROR] {provider} 网络不可达: {e.reason}\n  → 检查网络/代理/DNS")
    except TimeoutError:
        sys.exit(f"[ERROR] {provider} {TIMEOUT}s 超时，重试或换 provider")


def extract_content(resp: dict) -> str:
    """从 chat/completions 响应提取 content。缺失即报错。"""
    choices = resp.get("choices")
    if not choices:
        sys.exit(f"[ERROR] 响应无 choices: {resp}")
    msg = choices[0].get("message", {}) or {}
    content = msg.get("content")
    if not content:
        sys.exit(f"[ERROR] 响应无 content: {resp}")
    return content


def to_curl(provider: str, body: dict, api_key: str) -> str:
    """dry-run 等价 curl。key 截断防泄露，base64 图片截断防日志爆炸。"""
    import copy

    cfg = PROVIDERS[provider]
    sample = copy.deepcopy(body)  # 深拷贝（不污染传给 call_api 的 body），比 json 往返省内存
    for part in sample["messages"][0]["content"]:
        if part.get("type") == "image_url":
            url = part["image_url"]["url"]
            if isinstance(url, str) and url.startswith("data:"):
                part["image_url"]["url"] = url[:40] + "...(truncated)"
    return (
        f"curl -X POST {cfg['endpoint']} \\\n"
        f"  -H 'Authorization: Bearer {api_key[:8]}***' \\\n"
        f"  -H 'Content-Type: application/json' \\\n"
        f"  -d '{json.dumps(sample, ensure_ascii=False)}'"
    )


# ============================================================================
# CLI
# ============================================================================
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="vision.py",
        description="wudaozi —— 图像理解双 provider（agnes-2.0-flash / aiping DeepSeek-OCR-2）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
示例：
  # agnes 理解本地图（自动转 base64；实测 agnes 接受 data URI）
  AGNES_API_KEY=agn-xxx python3 vision.py agnes --image photo.jpg -q "这张图里有什么"

  # agnes 理解公网 URL 图
  AGNES_API_KEY=agn-xxx python3 vision.py agnes --image https://example.com/a.jpg -q "描述这张图"

  # aiping DeepSeek-OCR-2 解题
  AIPING_API_KEY=QC-xxx python3 vision.py aiping --image math.png -q "这道题怎么解答？"

  # 结果存 txt
  AGNES_API_KEY=agn-xxx python3 vision.py agnes --image x.jpg -q "..." --output result.txt

provider 选择：
  agnes  → agnes-2.0-flash（AGNES_API_KEY）
  aiping → DeepSeek-OCR-2（AIPING_API_KEY，OCR/图文强）
""",
    )
    p.add_argument(
        "provider", choices=list(PROVIDERS), help="视觉模型 provider"
    )
    p.add_argument(
        "--image", required=True, help="图片本地路径或公网 http(s) URL"
    )
    p.add_argument(
        "--question", "-q", required=True, help="对图片的提问/指令"
    )
    p.add_argument(
        "--max-tokens",
        type=int,
        default=1024,
        help="响应最大 token 数（默认 1024）",
    )
    p.add_argument(
        "--output", "-o", default=None, help="结果存到 txt（默认只打印 stdout）"
    )
    p.add_argument("--dry-run", action="store_true", help="只打印 curl 不执行")
    return p.parse_args()


def main() -> int:
    a = parse_args()
    cfg = PROVIDERS[a.provider]

    api_key = os.environ.get(cfg["key_env"])
    if not api_key:
        sys.exit(
            f"[ERROR] 未设置 {cfg['key_env']} 环境变量\n"
            f"  → export {cfg['key_env']}=xxx 后重试，或换另一个 provider"
        )

    image_input = resolve_image_input(a.image)
    body = build_body(a.provider, image_input, a.question, a.max_tokens)

    print(f"[INFO] provider={a.provider} model={cfg['model']}", file=sys.stderr)
    print(f"[CMD] {to_curl(a.provider, body, api_key)}", file=sys.stderr)

    if a.dry_run:
        print("[DRY-RUN] 未执行（无 key / 调试时用）", file=sys.stderr)
        return 0

    resp = call_api(a.provider, body, api_key)
    content = extract_content(resp)

    print(f"[RESULT] {a.provider} 图像理解结果：", file=sys.stderr)
    print(content)  # 正文打 stdout，便于 agent 管道读取

    if a.output:
        out = Path(a.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(content, encoding="utf-8")
        print(f"[OK] 已存: {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] != "__selfcheck__":
        sys.exit(main())
    # ponytail: 自检 —— 验证纯函数 + 常量 + key 存在性，不打网络。
    from types import SimpleNamespace

    print("== wudaozi vision self-check ==")
    for name, cfg in PROVIDERS.items():
        assert cfg["endpoint"].startswith("https://"), name
        assert cfg["model"], name
        assert cfg["key_env"], name
    # 本地图转 data URI
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        tmp = f.name
    uri = image_to_data_uri(tmp)
    assert uri.startswith("data:image/png;base64,"), uri
    Path(tmp).unlink()
    # URL 透传
    assert resolve_image_input("https://x.com/a.jpg") == "https://x.com/a.jpg"
    # body 结构
    body = build_body("agnes", "data:image/png;base64,AAA", "看图", 512)
    assert body["model"] == "agnes-2.0-flash"
    assert body["max_tokens"] == 512
    parts = body["messages"][0]["content"]
    assert parts[0]["type"] == "image_url"
    assert parts[1]["text"] == "看图"
    # extract_content
    assert extract_content({"choices": [{"message": {"content": "hello"}}]}) == "hello"
    print(f"  provider 数: {len(PROVIDERS)}（agnes + aiping）")
    for name, cfg in PROVIDERS.items():
        print(f"  {name}: {cfg['model']}（{cfg['key_env']}）")
    print("  self-check PASS")
