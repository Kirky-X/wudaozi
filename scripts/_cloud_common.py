#!/usr/bin/env python3
"""wudaozi —— 云端 provider 共享传输骨架(纯 stdlib)。

收敛 agnes.py / kolors.py / vision.py / video.py 四份重复的 HTTP 样板:
- post_json / post_json_raw:带鉴权 JSON POST + 统一错误分流
- download_to_file:URL → 本地文件(失败删半成品)
- extract_media:生成类响应 → url/b64_json 落盘 + 产物 sanity 校验
- assert_public_url / parse_host_ip:SSRF 防护(自 video.py 上移共享)
- ERROR_HINTS:按 (hint_key, HTTP status) 查可执行提示

2026-10 吸收自 luminarylane/fal-mcp-server 的 handlers/ 分层模式:provider
脚本只留 build_body + 常量 + CLI,新增 provider 的边际成本 ≈ build_body + 常量。

历史说明:kolors.py 与 agnes.py 曾自declare「与对方解耦、intentionally not
imported to avoid cross-provider coupling」。本模块是对该决定的显式推翻
(2026-10-02 作者批准:按调研建议全面优化):收敛的只有 HTTP 传输骨架,不含
任何 provider 语义;provider 差异(端点/请求体/提示文案/自检)全部留在各自脚本。
"""
# ponytail: 本模块不做任何路由/重试决策,只做传输与落盘——决策归各脚本(规则5)。
# 提示文案统一中文,与 kolors/vision/video 现状一致(agnes 原为英文,随收敛统一)。

import base64
import ipaddress
import json
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# (hint_key, HTTP status) → 可执行提示。hint_key 与消息里的 label 解耦:
# vision.py 的 label 是 provider 名(agnes/aiping),用 <provider>-vlm 作 hint_key,
# 避免与图像生成的同名 provider 提示冲突。
ERROR_HINTS = {
    ("agnes", 401): "  → AGNES_API_KEY 失效，检查环境变量，或改用 boogu 本地",
    ("agnes", 429): "  → 限流，稍后重试，或改用 kolors（需 AIPING_API_KEY）",
    ("agnes", 400): "  → size/prompt 不被接受，试 --aspect 预设或精简 prompt",
    ("kolors", 401): "  → AIPING_API_KEY 失效，检查环境变量",
    ("kolors", 429): "  → 限流，稍后重试",
    ("kolors", 400): "  → prompt/image_size 不被接受，换 --aspect 或 --image-size",
    ("video", 401): "  → AGNES_API_KEY 失效",
    ("video", 429): "  → 限流，稍后重试",
    ("video", 400): "  → 参数不被接受，检查 num_frames(8n+1)/frame_rate(1-60)/分辨率",
    ("agnes-vlm", 401): "  → AGNES_API_KEY 失效，检查环境变量",
    ("agnes-vlm", 429): "  → 限流，稍后重试",
    ("agnes-vlm", 400): "  → 图片/question 格式不被接受，换图或精简 question",
    ("aiping-vlm", 401): "  → AIPING_API_KEY 失效，检查环境变量",
    ("aiping-vlm", 429): "  → 限流，稍后重试",
    ("aiping-vlm", 400): "  → 图片/question 格式不被接受，换图或精简 question",
}


# 稳定错误码全集（调研建议#9：SKILL.md 声明消费者是 agent，错误必须机器可读）。
# 错误首行统一 `[ERROR] code=<code> ...`，测试钉死全集防漂移（comfy 同款做法）。
CODES = frozenset({
    "auth_error",         # 401
    "rate_limited",       # 429
    "invalid_param",      # 400 / 参数不被接受
    "no_task",            # 404（video 轮询任务不存在）
    "empty_result",       # HTTP 200 但无产物（常为内容过滤）
    "abnormal_artifact",  # 产物过小，疑似异常
    "network_error",      # URLError / 下载失败
    "timeout",            # 请求或轮询超时
    "malformed_response", # 响应结构异常（缺字段/类型错/解码失败）
    "server_error",       # 5xx
    "generation_failed",  # 任务终态 failed（video）
})


def fail(code: str, msg: str, hint: str = "") -> None:
    """统一错误出口：首行稳定错误码（agent 可解析），后续人读详情 + 可执行提示。"""
    if code not in CODES:
        raise ValueError(f"未知错误码 {code}，必须登记进 CODES（规则11：显性化）")
    sys.exit(f"[ERROR] code={code} {msg}" + (f"\n{hint}" if hint else ""))


def code_for_status(status: int) -> str:
    """HTTP 状态 → 稳定错误码。"""
    if status == 401:
        return "auth_error"
    if status == 429:
        return "rate_limited"
    if status >= 500:
        return "server_error"
    return "invalid_param"


class CloudHTTPError(Exception):
    """带状态码与原始响应片段的 HTTP 错误。需要按状态分类决策的调用方
    （如 video.py 的重试）捕它；简单调用方走 post_json() 直接分流退出。"""

    def __init__(self, status: int, raw: str):
        super().__init__(f"HTTP {status}: {raw}")
        self.status = status
        self.raw = raw


def read_error_body(e: urllib.error.HTTPError) -> str:
    """读错误响应体前 500 字符；读不到退回 reason。"""
    try:
        return e.read().decode("utf-8", errors="replace")[:500]
    except Exception:
        return str(e.reason)


def post_json_raw(endpoint: str, body: dict, api_key: str, timeout: int) -> dict:
    """带鉴权 JSON POST。成功返回解析后的 dict；HTTPError → CloudHTTPError；
    URLError/TimeoutError 原样上抛，由调用方分类（重试或退出）。"""
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise CloudHTTPError(e.code, read_error_body(e)) from None


def exit_http_error(label: str, e: CloudHTTPError, hint_key: str | None = None) -> None:
    """按 label + 状态码退出（首行稳定错误码），附 (hint_key, status) 查到的可执行提示。"""
    hint = ERROR_HINTS.get((hint_key or label, e.status), "")
    fail(code_for_status(e.status), f"{label} HTTP {e.status}: {e.raw}", hint)


def post_json(
    endpoint: str,
    body: dict,
    api_key: str,
    timeout: int,
    label: str,
    hint_key: str | None = None,
) -> dict:
    """post_json_raw + 统一错误出口（不重试、显式报错不 fallback）。agnes/kolors/vision 用。"""
    try:
        return post_json_raw(endpoint, body, api_key, timeout)
    except CloudHTTPError as e:
        exit_http_error(label, e, hint_key)
    except urllib.error.URLError as e:
        fail("network_error", f"{label} 网络不可达: {e.reason}", "  → 检查网络/代理/DNS")
    except TimeoutError:
        fail("timeout", f"{label} {timeout}s 超时，重试或换 provider")


def download_to_file(url: str, out_path: Path, timeout: int, label: str) -> None:
    """下载 URL 到文件；失败删半成品再退出。urllib 自动跟随重定向（签名 CDN 链接可用）。"""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            out_path.write_bytes(r.read())
    except (urllib.error.URLError, TimeoutError) as e:
        out_path.unlink(missing_ok=True)
        fail("network_error", f"下载 {label} 返回 URL 失败: {e}")


def extract_media(resp_data, out_path: Path, label: str, min_bytes: int, download=download_to_file) -> dict:
    """生成类响应处理：data[0].url → 下载；data[0].b64_json → 解码；缺失即报错。

    返回 data[0] 供调用方构建 sidecar。download 参数保留注入点（各脚本保留可
    mock 的 _download 薄封装，tests/ 靠它断言下载行为）。
    空 data 单独归因「可能被内容过滤」——国内 provider 审核严，HTTP 200 空结果
    常见，盲目换 provider 无效（归因吸收自 fal-mcp-server image_handlers）。
    """
    if not isinstance(resp_data, dict) or not resp_data.get("data"):
        snippet = json.dumps(resp_data, ensure_ascii=False)[:300]
        fail(
            "empty_result",
            f"{label} 响应无 data（空结果）: {snippet}",
            "  → prompt 可能被内容过滤，改写敏感词/换措辞后重试；多次复现再换 provider",
        )
    item = resp_data["data"][0]
    if not isinstance(item, dict):
        fail("malformed_response", f"{label} 响应 data[0] 不是对象: {item}")
    if rp := item.get("revised_prompt"):
        print(f"[INFO] {label} revised_prompt: {rp}", file=sys.stderr)
    try:
        url, b64 = item.get("url"), item.get("b64_json")
    except AttributeError as e:
        fail("malformed_response", f"{label} 响应 data[0] 结构异常: {e}")
    if url:
        download(url, out_path)
    elif b64:
        try:
            out_path.write_bytes(base64.b64decode(b64))
        except Exception as e:
            fail("malformed_response", f"{label} b64_json 解码失败: {e}")
    else:
        fail("malformed_response", f"{label} 响应无 url/b64_json: {item}")
    size = out_path.stat().st_size
    if size < min_bytes:
        out_path.unlink(missing_ok=True)
        fail("abnormal_artifact", f"{label} 返回图片 {size}B < {min_bytes}B，疑似异常")
    return item


def write_failed_sidecar(out_path: Path, meta: dict) -> Path | None:
    """失败留痕（调研建议#1；思想吸收自 mcp-server-stability-ai generateImageCore：
    失败先落盘 request+error 再报错，便于事后审计）。

    与上游的 env 门控 opt-in 不同：wudaozi 无条件落盘——有意加强，消费者是 agent，
    失败现场比成功现场更需要机器可读详情（规则11）。文件名 <输出名>-failed-<时间戳>.json，
    与成功 sidecar（同名 .json）不冲突。落盘失败只告警，绝不掩盖原始错误。
    """
    sidecar = out_path.with_name(f"{out_path.stem}-failed-{int(time.time())}.json")
    try:
        sidecar.parent.mkdir(parents=True, exist_ok=True)
        sidecar.write_text(
            json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return sidecar
    except OSError as e:
        print(f"[WARN] 失败留痕写入失败（不掩盖原始错误）: {e}", file=sys.stderr)
        return None


def failed_sidecar_meta(out_path: Path, provider: str, error: str, extra: dict | None = None) -> dict:
    """失败 sidecar 元数据：argv（key 走环境变量，天然不进 argv）+ 错误消息 + 上下文。"""
    meta = {
        "status": "failed",
        "provider": provider,
        "output": str(out_path),
        "argv": sys.argv[1:],
        "error": error[:2000],
        "timestamp": int(time.time()),
    }
    if extra:
        meta.update(extra)
    return meta


def raise_with_trace(
    e: SystemExit, out_path: Path, provider: str, extra: dict | None = None, resume: str | None = None
) -> None:
    """在调用方 `except SystemExit` 里调用：失败留痕 +（可选）stdout 输出 resume
    句柄（供调用方解析），然后重抛追加了留痕信息的错误。

    e.code 为 int（裸 sys.exit(1)）或空时不加工消息，但留痕照写——退出码语义不变。
    """
    if resume is not None:
        print(f"WUDAOZI_RESUME={resume}", flush=True)
    sc = write_failed_sidecar(out_path, failed_sidecar_meta(out_path, provider, str(e.code), extra))
    notes = []
    if resume is not None:
        notes.append(f"续查: --resume {resume}")
    if sc is not None:
        notes.append(f"失败详情已留痕: {sc}")
    if not notes or not e.code or isinstance(e.code, int):
        raise
    raise SystemExit(f"{str(e.code).rstrip()}\n  → " + "；".join(notes)) from None


def parse_retry_after(value) -> float | None:
    """Retry-After 头 → 秒数。支持数字秒与 HTTP-date 双格式（replicate 同款）。

    缺失/非正数/非法 → None，调用方回退退避抖动——0 或过去时间视为无效，
    防止「0 秒后重试」死循环（comfy 同款语义）。
    """
    if not value:
        return None
    value = str(value).strip()
    try:
        secs = float(value)
        return secs if secs > 0 else None
    except ValueError:
        pass
    try:
        from email.utils import parsedate_to_datetime  # noqa: PLC0415 — 低频路径，延迟导入
        delta = parsedate_to_datetime(value).timestamp() - time.time()
        return delta if delta > 0 else None
    except Exception:
        return None


def parse_host_ip(host: str):
    """host → IPv4Address/IPv6Address 或 None（域名/无法解析）。

    ipaddress.ip_address 只认标准点分十进制/IPv6，漏十进制(2852039166)/十六进制(0xA9FEA9FE)/
    八进制 IP 这类 inet_aton 认的非标准写法（Linux 下 2852039166 → 169.254.169.254 云元数据）；
    fallback 到 socket.inet_aton 补检测，挡 ipaddress 的盲区，避免 SSRF 非标准 IP 绕过。
    解析失败视为公网域名放行（DNS rebinding 属服务端 fetch 责任，CLI 层不引入 DNS 查询）。
    """
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        pass
    try:
        # ponytail: inet_aton 接受十进制/十六进制/八进制 IP（ipaddress 盲区），转 packed 再用 ipaddress 校验属性
        return ipaddress.ip_address(socket.inet_aton(host))
    except (OSError, ValueError):
        return None


def assert_public_url(u: str, ctx: str = "URL") -> None:
    """校验公网 http(s) URL，拒绝内网/环回/链路本地/云元数据地址（防 SSRF）。"""
    p = urllib.parse.urlparse(u)
    if p.scheme not in ("http", "https"):
        sys.exit(
            f"[ERROR] {ctx} 只接受公网 http(s) URL: {u}\n"
            "  → 先把本地文件上传到图床/OSS"
        )
    host = (p.hostname or "").lower()
    if host == "localhost":
        sys.exit(f"[ERROR] {ctx} 禁止 localhost（SSRF 防护）: {u}")
    ip = parse_host_ip(host)
    if ip is None:
        return  # 公网域名，放行
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
        sys.exit(f"[ERROR] {ctx} 禁止内网/环回/链路本地/保留地址（SSRF 防护）: {u}")
