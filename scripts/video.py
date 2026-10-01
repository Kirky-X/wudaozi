#!/usr/bin/env python3
"""wudaozi —— agnes-video-v2.0 视频生成包装脚本（异步任务 + 轮询）。

支持四种模式：
- t2vid（文生视频）：prompt → 视频
- ti2vid（图生视频）：prompt + 公网图 URL（首帧）→ 视频
- multi（多图视频）：prompt + 多张公网图 URL → 多图融合视频
- keyframes（关键帧动画）：prompt + 多张公网图 URL（关键帧）→ 帧间过渡视频

核心职责（纯 stdlib）：
1. 构造视频任务请求（model/prompt/分辨率/帧数/帧率 + 可选 image）
2. POST /v1/videos 创建异步任务，拿 video_id
3. 轮询 GET /agnesapi?video_id=X 直到 completed/failed（或超时）
4. 下载返回的 mp4 到本地
5. 错误显式报错，不 fallback

⚠️ num_frames 须满足 8n+1 规则（如 81/121/241/441），≤441；frame_rate 1-60。
   ti2vid 的 image 参数只接受公网 URL（文档明确，不支持 base64）。

使用：
    AGNES_API_KEY=agn-xxx python3 video.py t2vid -i "猫在沙滩走，电影感"
    AGNES_API_KEY=agn-xxx python3 video.py t2vid -i "..." --duration 10s --aspect 16:9
    AGNES_API_KEY=agn-xxx python3 video.py ti2vid -i "镜头推进" --image https://x/a.png
    AGNES_API_KEY=agn-xxx python3 video.py t2vid -i "..." --dry-run
"""
# ponytail: 异步轮询是确定性逻辑（固定 interval + deadline），不交给模型决策（规则5）。
# num_frames 8n+1 是模型硬约束，入口校验拒绝，避免服务端 400。

import argparse
import json
import os
import random
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

import _cloud_common as _cc

# SSRF 防护自 2026-10 上移 _cloud_common（vision.py 同享）；保留原名，调用点与 tests 不动
from _cloud_common import assert_public_url as _assert_public_url  # noqa: F401

# ── 创建任务重试策略（调研建议#2，吸收自 comfy-python-sdk retry.py 的显式谓词表）──
# 仅 connect 阶段错误可安全自动重试：请求未送达，不会重复建任务。
CONNECT_ERRORS = (ConnectionRefusedError, ConnectionResetError, ConnectionAbortedError, socket.gaierror)
RETRY_BUDGET_S = 60.0  # 创建任务重试总预算
BACKOFF_BASE_S = 0.5   # full-jitter 退避起点
BACKOFF_CAP_S = 15.0   # full-jitter 退避封顶
# 终态显式常量：completed/failed 之外的 status 都按未知处理（连续 3 次告警）
TERMINAL = {"completed", "failed"}
KNOWN_STATES = TERMINAL | {"queued", "in_progress"}


def _is_connect_error(e: urllib.error.URLError) -> bool:
    """URLError 的 cause 是否 connect 阶段错误（拒绝/重置/DNS）。

    读超时/裸 TimeoutError 无法区分连接与读阶段——读超时意味着请求可能已送达、
    任务可能已创建，自动重试会双倍计费（agnes 无幂等键），绝不自动重试。
    """
    return isinstance(getattr(e, "reason", None), CONNECT_ERRORS)


def _full_jitter(attempt: int) -> float:
    """full-jitter 指数退避：0.5s 起 ×2、15s 封顶，随机抖动防惊群。"""
    return random.uniform(0, min(BACKOFF_CAP_S, BACKOFF_BASE_S * 2 ** attempt))

CREATE_ENDPOINT = "https://apihub.agnes-ai.com/v1/videos"
POLL_ENDPOINT = "https://apihub.agnes-ai.com/agnesapi"
MODEL = "agnes-video-v2.0"
TIMEOUT = 60           # 创建任务用（POST 秒级返回，60s 充分）
POLL_TIMEOUT = 30      # 单次轮询用（poll 接口秒级，30s 给 max_wait 留足轮询次数）
DOWNLOAD_TIMEOUT = 300  # mp4 下载（大视频给足余量）

# 分辨率预设（W, H）；文档推荐 1152x768（16:9 标准）
RESOLUTIONS = {
    "16:9": (1152, 768),  # 横版标准
    "9:16": (768, 1152),  # 竖版短视频
    "1:1": (960, 960),    # 方形
    "4:3": (1024, 768),   # 传统横版
    "3:4": (768, 1024),   # 竖版
}

# 时长预设（num_frames, frame_rate），均满足 8n+1
DURATIONS = {
    "3s": (81, 24),
    "5s": (121, 24),
    "10s": (241, 24),
    "18s": (441, 24),
}


def validate_num_frames(n: int) -> None:
    """num_frames 硬约束：≤441 且 8n+1。违反即 sys.exit。"""
    if n > 441:
        sys.exit(f"[ERROR] num_frames {n} > 441 上限")
    if (n - 1) % 8 != 0:
        sys.exit(
            f"[ERROR] num_frames {n} 不符合 8n+1 规则（可选 {list(DURATIONS.values())}）"
        )


def validate_frame_rate(fr: int) -> None:
    if not (1 <= fr <= 60):
        sys.exit(f"[ERROR] frame_rate {fr} 不在 1-60 范围")


def resolve_resolution(a: argparse.Namespace) -> tuple:
    """aspect > width/height（须同传）> 默认 16:9 (1152x768)。"""
    if a.aspect:
        return RESOLUTIONS[a.aspect]
    if (a.width is None) != (a.height is None):
        sys.exit("[ERROR] --width 与 --height 必须同时提供；单传请改用 --aspect 预设")
    if a.width and a.height:
        return a.width, a.height
    return RESOLUTIONS["16:9"]


def resolve_frames(a: argparse.Namespace) -> tuple:
    """num_frames/frame_rate（自定义，校验 8n+1）> duration 预设 > 默认 5s。"""
    if a.num_frames is not None:
        validate_num_frames(a.num_frames)
        fr = a.frame_rate if a.frame_rate is not None else 24
        validate_frame_rate(fr)
        return a.num_frames, fr
    if a.duration:
        return DURATIONS[a.duration]
    return DURATIONS["5s"]


def resolve_output(a: argparse.Namespace, width: int, height: int) -> Path:
    """输出：默认 $PWD/video-output/，文件名含 mode+尺寸+时间戳+uuid8。"""
    out_dir = (
        Path(a.output_dir).resolve() if a.output_dir else Path.cwd() / "video-output"
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = int(time.time())
    suffix = uuid.uuid4().hex[:8]
    return out_dir / f"agnes_video_{a.mode}_{width}x{height}_{ts}_{suffix}.mp4"


def build_body(
    a: argparse.Namespace, width: int, height: int, num_frames: int, frame_rate: int
) -> dict:
    """组装创建任务请求体。"""
    body: dict = {
        "model": MODEL,
        "prompt": a.instruction,
        "width": width,
        "height": height,
        "num_frames": num_frames,
        "frame_rate": frame_rate,
    }
    if a.image and a.images:
        sys.exit(
            "[ERROR] --image 与 --images 互斥（ti2vid 用 --image，multi/keyframes 用 --images）"
        )
    if a.mode == "ti2vid":
        if not a.image:
            sys.exit("[ERROR] 图生视频(ti2vid)必须提供 --image 公网 URL")
        _assert_public_url(a.image, "ti2vid --image")
        body["image"] = a.image
    elif a.mode in ("multi", "keyframes"):
        # multi 多图融合 / keyframes 关键帧过渡 —— 官方走 extra_body.image 数组
        if not a.images or len(a.images) < 2:
            sys.exit(
                f"[ERROR] {a.mode} 至少需要 2 张公网图 URL（--images，空格分隔）\n"
                "  → 单张图请改用 ti2vid"
            )
        for u in a.images:
            _assert_public_url(u, f"{a.mode} --images")
        # multi：不带 mode 字段（agnes 靠 extra_body.image 数组 + 无 mode 区分）
        # keyframes：显式 mode=keyframes（帧间过渡）
        extra = {"image": list(a.images)}
        if a.mode == "keyframes":
            extra["mode"] = "keyframes"
        body["extra_body"] = extra
    if a.seed is not None:
        body["seed"] = a.seed
    if a.negative_instruction:
        body["negative_prompt"] = a.negative_instruction
    return body


def create_task(body: dict, api_key: str) -> tuple:
    """POST 创建任务（连接阶段失败按 full-jitter 退避重试，60s 预算）。返回 (video_id, 原始响应)。

    重试分类（调研建议#2，显式谓词表；与「显式报错不 fallback」不冲突——
    retry=同一请求再试，fallback=换 provider 假装成功）：
    - URLError 且 cause 为 connect 阶段错误 → 重试（请求未送达，安全）
    - 裸 TimeoutError → 绝不自动重试（任务可能已创建，重提交双倍计费），引导 --resume
    - HTTP 4xx/5xx → 一律不重试，显式报错
    """
    attempt = 0
    deadline = time.monotonic() + RETRY_BUDGET_S
    while True:
        try:
            r = _cc.post_json_raw(CREATE_ENDPOINT, body, api_key, TIMEOUT)
            break
        except _cc.CloudHTTPError as e:
            _cc.exit_http_error("video", e)
        except urllib.error.URLError as e:
            if not _is_connect_error(e) or time.monotonic() >= deadline:
                _cc.fail("network_error", f"创建任务网络不可达: {e.reason}", "  → 检查网络/代理/DNS")
            delay = _full_jitter(attempt)
            print(
                f"[WARN] 创建任务连接失败（{e.reason}），{delay:.1f}s 后重试（预算 {RETRY_BUDGET_S:.0f}s）",
                file=sys.stderr,
            )
            time.sleep(delay)
            attempt += 1
        except TimeoutError:
            _cc.fail(
                "timeout",
                f"创建任务 {TIMEOUT}s 超时（任务可能已创建，不自动重试以防重复计费）",
                "  → 稍后用 --resume <video_id> 续查；video_id 可在 provider 控制台查询",
            )
    vid = r.get("video_id") or r.get("id") or r.get("task_id")
    if not vid:
        _cc.fail("malformed_response", f"创建任务响应无 video_id/id/task_id: {r}")
    return vid, r


def poll_task(
    video_id: str, api_key: str, interval: int, max_wait: int
) -> dict:
    """轮询 GET /agnesapi?video_id=X 直到 completed/failed/超时。返回最终响应。

    重试策略（调研建议#2）：
    - 404 → no_task 立即退出；其余 4xx（除 429）→ 立即退出（重试无意义）
    - 429/503/504 → 读 Retry-After（数字秒或 HTTP-date；0/非法回退退避抖动）
    - 其余 5xx/网络抖动 → full-jitter 退避重试（替代原固定 interval，防惊群）
    - 连续 3 次未知状态 → 打印原始响应告警（provider 可能改了状态枚举）
    """
    url = f"{POLL_ENDPOINT}?video_id={urllib.parse.quote(video_id)}"
    deadline = time.time() + max_wait
    last_status = None
    last_progress = None
    unknown_streak = 0
    attempt = 0
    while time.time() < deadline:
        req = urllib.request.Request(
            url, headers={"Authorization": f"Bearer {api_key}"}
        )
        try:
            with urllib.request.urlopen(req, timeout=POLL_TIMEOUT) as r:
                resp = json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                _cc.fail("no_task", f"任务不存在（404）: video_id={video_id}")
            if e.code < 500 and e.code != 429:
                code = "auth_error" if e.code == 401 else "invalid_param"
                _cc.fail(code, f"轮询 HTTP {e.code}，重试无意义: video_id={video_id}")
            headers = e.headers or {}
            delay = _cc.parse_retry_after(headers.get("Retry-After"))
            source = f"遵循 Retry-After" if delay else "退避抖动"
            delay = delay if delay else _full_jitter(attempt)
            print(f"[WARN] 轮询 HTTP {e.code}（{source}），{delay:.1f}s 后重试", file=sys.stderr)
            time.sleep(delay)
            attempt += 1
            continue
        except (urllib.error.URLError, TimeoutError) as e:
            delay = _full_jitter(attempt)
            print(f"[WARN] 轮询网络异常 {e}，{delay:.1f}s 后重试", file=sys.stderr)
            time.sleep(delay)
            attempt += 1
            continue

        status = resp.get("status", "unknown")
        progress = resp.get("progress", 0)
        # 状态或进度变化才打印，避免刷屏；processing 阶段 progress 0→90% 也能被看到
        if status != last_status or progress != last_progress:
            print(f"[INFO] status={status} progress={progress}%", file=sys.stderr)
            last_status = status
            last_progress = progress
        if status == "completed":
            return resp
        if status == "failed":
            err = resp.get("error") or resp
            _cc.fail("generation_failed", f"视频生成失败: {err}")
        if status not in KNOWN_STATES:
            unknown_streak += 1
            if unknown_streak == 3:
                raw = json.dumps(resp, ensure_ascii=False)[:300]
                print(
                    f"[WARN] 连续 {unknown_streak} 次未知状态 status={status!r}，原始响应: {raw}",
                    file=sys.stderr,
                )
        else:
            unknown_streak = 0
        time.sleep(interval)

    _cc.fail(
        "timeout",
        f"轮询超时（{max_wait}s），最后状态={last_status}。",
        f"  → video_id={video_id} 稍后用 --resume {video_id} 续查"
        f"（任务可能仍在跑，勿重新提交以防双倍计费）",
    )


def download_video(url: str, out_path: Path) -> None:
    """流式下载 mp4 到 tmp 文件再 rename，避免大文件内存峰值 + 半成品残留。"""
    import shutil
    tmp = out_path.with_suffix(out_path.suffix + ".part")
    try:
        with urllib.request.urlopen(url, timeout=DOWNLOAD_TIMEOUT) as r, open(
            tmp, "wb"
        ) as f:
            shutil.copyfileobj(r, f, length=64 * 1024)
        tmp.rename(out_path)
    except (urllib.error.URLError, TimeoutError) as e:
        tmp.unlink(missing_ok=True)
        _cc.fail("network_error", f"下载视频失败: {e}")


def save_video(resp: dict, out_path: Path) -> None:
    """从 completed 响应取 url 下载。"""
    url = resp.get("url")
    if not url:
        _cc.fail("malformed_response", f"任务 completed 但无 url: {resp}")
    download_video(url, out_path)
    if out_path.stat().st_size < 10 * 1024:
        out_path.unlink(missing_ok=True)
        _cc.fail("abnormal_artifact", "视频文件 <10KB，疑似异常")


def to_curl(body: dict, api_key: str) -> str:
    """dry-run 等价 curl（创建任务）。key 截断。"""
    return (
        f"curl -X POST {CREATE_ENDPOINT} \\\n"
        f"  -H 'Authorization: Bearer {api_key[:8]}***' \\\n"
        f"  -H 'Content-Type: application/json' \\\n"
        f"  -d '{json.dumps(body, ensure_ascii=False)}'"
    )


# ============================================================================
# CLI
# ============================================================================
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="video.py",
        description="wudaozi —— agnes-video-v2.0 视频生成（文生视频/图生视频，异步轮询）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
示例：
  # 文生视频，5s，16:9（默认）
  AGNES_API_KEY=agn-xxx python3 video.py t2vid -i "猫在沙滩走，电影感，暖光"

  # 10s 横版 + 反向提示
  AGNES_API_KEY=agn-xxx python3 video.py t2vid -i "..." --duration 10s --aspect 16:9 \\
      --negative-instruction "模糊, 变形"

  # 图生视频（首帧图必须是公网 URL）
  AGNES_API_KEY=agn-xxx python3 video.py ti2vid -i "镜头缓慢推进" --image https://x/a.png

  # 多图融合（multi）/ 关键帧过渡（keyframes）：至少 2 张公网图
  AGNES_API_KEY=agn-xxx python3 video.py multi -i "从场景 A 平滑变到场景 B" \\
      --images https://x/a.png https://x/b.png
  AGNES_API_KEY=agn-xxx python3 video.py keyframes -i "保持人物一致，视角推近" \\
      --images https://x/a.png https://x/b.png

  # 只看 curl 不真调
  AGNES_API_KEY=agn-xxx python3 video.py t2vid -i "..." --dry-run

时长预设: """
        + ", ".join(f"{k}={v[0]}帧/{v[1]}fps" for k, v in DURATIONS.items())
        + "\n分辨率预设: "
        + ", ".join(f"{k}={v[0]}x{v[1]}" for k, v in RESOLUTIONS.items()),
    )
    p.add_argument(
        "mode",
        choices=["t2vid", "ti2vid", "multi", "keyframes"],
        help="t2vid=文生视频, ti2vid=图生视频(单图首帧), multi=多图融合, keyframes=关键帧过渡",
    )
    p.add_argument(
        "--instruction", "-i", default=None, help="视频内容描述（--resume 续查时可不填）"
    )
    p.add_argument(
        "--image", default=None, help="ti2vid 首帧图公网 URL（ti2vid 必填）"
    )
    p.add_argument(
        "--images",
        nargs="+",
        default=None,
        help="multi/keyframes 多张公网图 URL（至少 2 张，空格分隔）",
    )
    p.add_argument(
        "--aspect",
        choices=list(RESOLUTIONS),
        help="分辨率预设（优先于 --width/--height）",
    )
    p.add_argument(
        "--duration",
        choices=list(DURATIONS),
        help="时长预设（优先级低于 --num-frames）",
    )
    p.add_argument("--width", type=int, default=None, help="视频宽度（须与 --height 同传）")
    p.add_argument("--height", type=int, default=None, help="视频高度（须与 --width 同传）")
    p.add_argument(
        "--num-frames",
        type=int,
        default=None,
        help="自定义帧数（须 8n+1，≤441；优先于 --duration）",
    )
    p.add_argument(
        "--frame-rate", type=int, default=None, help="自定义帧率（1-60，默认 24）"
    )
    p.add_argument("--seed", type=int, default=None, help="随机种子（可复现）")
    p.add_argument(
        "--negative-instruction", default=None, help="反向提示（避免的内容）"
    )
    p.add_argument(
        "--poll-interval", type=int, default=10, help="轮询间隔秒（默认 10）"
    )
    p.add_argument(
        "--max-wait",
        type=int,
        default=1200,
        help="最大等待秒（默认 1200=20 分钟，覆盖最长 18s 视频的生成耗时）",
    )
    p.add_argument(
        "--output-dir", "-o", default=None, help="输出目录（默认 $PWD/video-output/）"
    )
    p.add_argument("--dry-run", action="store_true", help="只打印创建任务 curl")
    p.add_argument(
        "--resume",
        default=None,
        metavar="VIDEO_ID",
        help="续查已有任务：跳过创建，直接轮询该 video_id 并落盘（超时/中断后用，"
        "配合失败时 stdout 输出的 WUDAOZI_RESUME=<id> 行）",
    )
    a = p.parse_args()
    if not a.resume and not a.instruction:
        p.error("-i/--instruction 必填；续查已有任务请用 --resume <video_id>")
    if a.resume and (a.image or a.images):
        p.error("--resume 与 --image/--images 互斥（续查不重新提交素材）")
    if a.resume and a.dry_run:
        p.error("--resume 与 --dry-run 互斥")
    return a


def main() -> int:
    a = parse_args()

    api_key = os.environ.get("AGNES_API_KEY")
    if not api_key:
        sys.exit(
            "[ERROR] 未设置 AGNES_API_KEY 环境变量\n"
            "  → export AGNES_API_KEY=agn-xxx 后重试"
        )

    if a.resume:
        # 续查模式：不重新提交任务（避免重复计费），原始分辨率未知，文件名尺寸仅作标识
        out_path = resolve_output(a, *RESOLUTIONS["16:9"])
        video_id = a.resume
        print(f"[INFO] resume video_id={video_id}（跳过创建，直接轮询）", file=sys.stderr)
        print(f"[INFO] 输出={out_path}", file=sys.stderr)
    else:
        width, height = resolve_resolution(a)
        num_frames, frame_rate = resolve_frames(a)
        out_path = resolve_output(a, width, height)
        body = build_body(a, width, height, num_frames, frame_rate)

        secs = num_frames / frame_rate
        print(
            f"[INFO] mode={a.mode} size={width}x{height} frames={num_frames}@{frame_rate}fps (~{secs:.1f}s)",
            file=sys.stderr,
        )
        print(f"[INFO] 输出={out_path}", file=sys.stderr)
        print(f"[CMD] {to_curl(body, api_key)}", file=sys.stderr)

        if a.dry_run:
            print("[DRY-RUN] 未执行（无 key / 调试时用）", file=sys.stderr)
            return 0
        video_id = None

    try:
        if not a.resume:
            video_id, created = create_task(body, api_key)
            print(f"[INFO] 任务已创建: video_id={video_id} status={created.get('status')}", file=sys.stderr)
        final = poll_task(video_id, api_key, a.poll_interval, a.max_wait)
        save_video(final, out_path)
    except SystemExit as e:
        # 失败留痕 + 机器可读恢复句柄：stdout 单行 WUDAOZI_RESUME=<id> 供调用方解析
        #（video 日志全走 stderr，stdout 只这一行，互不污染）（调研建议#3）
        _cc.raise_with_trace(e, out_path, "agnes-video", {"video_id": video_id, "mode": a.mode}, resume=video_id)
    print(
        f"[OK] 已生成: {out_path} ({out_path.stat().st_size // (1024*1024)} MB)",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] != "__selfcheck__":
        sys.exit(main())
    # ponytail: 自检 —— 验证纯函数 + 常量 + 8n+1 规则，不打网络。
    from types import SimpleNamespace

    print("== wudaozi video self-check ==")
    # 8n+1 规则验证所有预设
    for dur, (nf, fr) in DURATIONS.items():
        assert (nf - 1) % 8 == 0 and nf <= 441, dur
        assert 1 <= fr <= 60, dur
    # num_frames 校验
    validate_num_frames(81)  # ok
    assert resolve_resolution(SimpleNamespace(aspect="16:9", width=None, height=None)) == (1152, 768)
    assert resolve_resolution(SimpleNamespace(aspect=None, width=800, height=600)) == (800, 600)
    assert resolve_resolution(SimpleNamespace(aspect=None, width=None, height=None)) == (1152, 768)
    nf, fr = resolve_frames(SimpleNamespace(num_frames=None, frame_rate=None, duration="10s"))
    assert (nf, fr) == (241, 24)
    nf2, fr2 = resolve_frames(SimpleNamespace(num_frames=161, frame_rate=30, duration=None))
    assert (nf2, fr2) == (161, 30)  # 161 = 8*20+1 ✓
    # body 结构
    body = build_body(
        SimpleNamespace(
            mode="t2vid", instruction="测", image=None, images=None,
            seed=42, negative_instruction="模糊",
        ),
        1152, 768, 121, 24,
    )
    assert body["model"] == MODEL
    assert body["width"] == 1152 and body["height"] == 768
    assert body["seed"] == 42 and body["negative_prompt"] == "模糊"
    assert "image" not in body
    # multi / keyframes —— extra_body.image 数组（keyframes 多 mode 字段）
    mbody = build_body(
        SimpleNamespace(
            mode="multi", instruction="过渡", image=None,
            images=["https://x/1.png", "https://x/2.png"], seed=None, negative_instruction=None,
        ),
        1152, 768, 121, 24,
    )
    assert mbody["extra_body"] == {"image": ["https://x/1.png", "https://x/2.png"]}
    kbody = build_body(
        SimpleNamespace(
            mode="keyframes", instruction="过渡", image=None,
            images=["https://x/1.png", "https://x/2.png"], seed=None, negative_instruction=None,
        ),
        1152, 768, 121, 24,
    )
    assert kbody["extra_body"] == {
        "image": ["https://x/1.png", "https://x/2.png"], "mode": "keyframes",
    }
    print(f"  分辨率预设: {len(RESOLUTIONS)} 种，时长预设: {len(DURATIONS)} 种")
    print(f"  CREATE: {CREATE_ENDPOINT}")
    print(f"  POLL: {POLL_ENDPOINT}?video_id=<ID>")
    print(f"  MODEL: {MODEL}")
    print(f"  AGNES_API_KEY: {'已设置' if os.environ.get('AGNES_API_KEY') else '未设置'}")
    print("  self-check PASS")
