#!/usr/bin/env python3
"""wudaozi video.py 单元测试 —— 验证纯函数与异步轮询逻辑（不打真实 API）。

覆盖：validate_num_frames / validate_frame_rate / resolve_resolution /
resolve_frames / build_body / create_task（mock）/ poll_task（mock 4 态）/
save_video（mock）/ to_curl / 常量一致性。
跑法：python3 -m pytest scripts/test_video.py -v
"""
# ponytail: 只测决定正确性的纯函数 + mock 网络层；不打真实 API（视频生成慢且费额度）。
# 关键钉死：num_frames 8n+1 硬约束、ti2vid image 必须 URL、轮询 completed/failed/timeout/404 四态。

import io
import json
import socket
import sys
import urllib.error
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import video  # noqa: E402


# ---------- validate_num_frames ----------
class TestValidateNumFrames:
    def test_valid_8n_plus_1(self):
        for n in [81, 121, 161, 241, 441]:
            video.validate_num_frames(n)  # 不抛异常

    def test_invalid_not_8n_plus_1(self):
        with pytest.raises(SystemExit):
            video.validate_num_frames(80)
        with pytest.raises(SystemExit):
            video.validate_num_frames(100)

    def test_over_441(self):
        with pytest.raises(SystemExit):
            video.validate_num_frames(449)  # 8n+1 但超上限


class TestValidateFrameRate:
    def test_valid_range(self):
        for fr in [1, 24, 30, 60]:
            video.validate_frame_rate(fr)

    def test_out_of_range(self):
        with pytest.raises(SystemExit):
            video.validate_frame_rate(0)
        with pytest.raises(SystemExit):
            video.validate_frame_rate(61)


# ---------- resolve_resolution ----------
def _res_ns(**kw):
    base = dict(aspect=None, width=None, height=None)
    base.update(kw)
    return SimpleNamespace(**base)


class TestResolveResolution:
    def test_aspect_preset(self):
        assert video.resolve_resolution(_res_ns(aspect="16:9")) == (1152, 768)
        assert video.resolve_resolution(_res_ns(aspect="9:16")) == (768, 1152)

    def test_custom_wh(self):
        assert video.resolve_resolution(_res_ns(width=800, height=600)) == (800, 600)

    def test_default_16_9(self):
        assert video.resolve_resolution(_res_ns()) == (1152, 768)

    def test_single_width_exits(self):
        with pytest.raises(SystemExit):
            video.resolve_resolution(_res_ns(width=800))


# ---------- resolve_frames ----------
def _fr_ns(**kw):
    base = dict(num_frames=None, frame_rate=None, duration=None)
    base.update(kw)
    return SimpleNamespace(**base)


class TestResolveFrames:
    def test_duration_preset(self):
        assert video.resolve_frames(_fr_ns(duration="10s")) == (241, 24)
        assert video.resolve_frames(_fr_ns(duration="3s")) == (81, 24)

    def test_custom_num_frames(self):
        # 161 = 8*20+1 ✓
        assert video.resolve_frames(_fr_ns(num_frames=161, frame_rate=30)) == (161, 30)

    def test_default_5s(self):
        assert video.resolve_frames(_fr_ns()) == (121, 24)

    def test_invalid_custom_frames_exits(self):
        # 100 不是 8n+1，resolve_frames 内部调 validate 会 sys.exit
        with pytest.raises(SystemExit):
            video.resolve_frames(_fr_ns(num_frames=100))


# ---------- build_body ----------
def _body_ns(**kw):
    base = dict(
        mode="t2vid", instruction="测", image=None, images=None,
        seed=None, negative_instruction=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


class TestBuildBody:
    def test_t2vid_minimal(self):
        body = video.build_body(_body_ns(), 1152, 768, 121, 24)
        assert body["model"] == video.MODEL
        assert body["width"] == 1152 and body["height"] == 768
        assert body["num_frames"] == 121 and body["frame_rate"] == 24
        assert "image" not in body
        assert "seed" not in body

    def test_seed_and_negative(self):
        body = video.build_body(
            _body_ns(seed=42, negative_instruction="模糊"), 1152, 768, 121, 24
        )
        assert body["seed"] == 42
        assert body["negative_prompt"] == "模糊"

    def test_ti2vid_with_url(self):
        body = video.build_body(
            _body_ns(mode="ti2vid", image="https://x.com/a.png"), 768, 1152, 121, 24
        )
        assert body["image"] == "https://x.com/a.png"

    def test_ti2vid_missing_image_exits(self):
        with pytest.raises(SystemExit):
            video.build_body(_body_ns(mode="ti2vid", image=None), 768, 1152, 121, 24)

    def test_ti2vid_local_path_exits(self):
        # 视频生成 image 不支持本地/base64
        with pytest.raises(SystemExit):
            video.build_body(
                _body_ns(mode="ti2vid", image="/local/a.png"), 768, 1152, 121, 24
            )

    def test_image_and_images_mutually_exclusive_exits(self):
        # --image（ti2vid）与 --images（multi/keyframes）互斥，不静默丢参数
        with pytest.raises(SystemExit):
            video.build_body(
                _body_ns(mode="ti2vid", image="https://x/a.png",
                         images=["https://x/b.png", "https://x/c.png"]),
                768, 1152, 121, 24,
            )


class TestBuildBodyMultiKeyframes:
    """multi 多图视频 / keyframes 关键帧动画 —— extra_body.image 数组（agnes 官方最佳实践）。"""

    def test_multi_with_images(self):
        body = video.build_body(
            _body_ns(mode="multi", images=["https://x.com/1.png", "https://x.com/2.png"]),
            1152, 768, 121, 24,
        )
        # multi：extra_body.image 数组，不带 mode 字段
        assert body["extra_body"] == {"image": ["https://x.com/1.png", "https://x.com/2.png"]}
        assert "mode" not in body["extra_body"]

    def test_keyframes_with_images(self):
        body = video.build_body(
            _body_ns(mode="keyframes", images=["https://x.com/1.png", "https://x.com/2.png"]),
            1152, 768, 121, 24,
        )
        # keyframes：extra_body.image 数组 + mode=keyframes
        assert body["extra_body"] == {
            "image": ["https://x.com/1.png", "https://x.com/2.png"],
            "mode": "keyframes",
        }

    def test_multi_missing_images_exits(self):
        with pytest.raises(SystemExit):
            video.build_body(_body_ns(mode="multi", images=None), 768, 1152, 121, 24)

    def test_multi_single_image_exits(self):
        # multi 至少 2 张（单张走 ti2vid）
        with pytest.raises(SystemExit):
            video.build_body(
                _body_ns(mode="multi", images=["https://x.com/1.png"]), 768, 1152, 121, 24
            )

    def test_multi_local_path_exits(self):
        # 视频生成 images 只接受公网 URL，不支持本地/base64
        with pytest.raises(SystemExit):
            video.build_body(
                _body_ns(mode="multi", images=["/local/1.png", "https://x.com/2.png"]),
                768, 1152, 121, 24,
            )

    def test_keyframes_local_path_exits(self):
        with pytest.raises(SystemExit):
            video.build_body(
                _body_ns(mode="keyframes", images=["https://x.com/1.png", "/local/2.png"]),
                768, 1152, 121, 24,
            )


class TestAssertPublicUrl:
    """SSRF 防护 —— 拒绝内网/环回/链路本地/云元数据地址。"""

    def test_public_domain_ok(self):
        # 公网域名放行（不抛异常）
        video._assert_public_url("https://example.com/a.png")
        video._assert_public_url("http://cdn.agnes-ai.com/x.jpg")

    def test_non_http_exits(self):
        with pytest.raises(SystemExit):
            video._assert_public_url("file:///etc/passwd")
        with pytest.raises(SystemExit):
            video._assert_public_url("/local/a.png")

    def test_localhost_exits(self):
        with pytest.raises(SystemExit):
            video._assert_public_url("http://localhost/a.png")

    def test_loopback_ip_exits(self):
        with pytest.raises(SystemExit):
            video._assert_public_url("http://127.0.0.1/a.png")

    def test_cloud_metadata_exits(self):
        # AWS/阿里云元数据端点（SSRF 主要目标）
        with pytest.raises(SystemExit):
            video._assert_public_url("http://169.254.169.254/latest/meta-data/")

    def test_private_10_exits(self):
        with pytest.raises(SystemExit):
            video._assert_public_url("http://10.0.0.1/a.png")

    def test_private_192168_exits(self):
        with pytest.raises(SystemExit):
            video._assert_public_url("http://192.168.1.1/a.png")

    def test_private_172_exits(self):
        with pytest.raises(SystemExit):
            video._assert_public_url("http://172.16.0.1/a.png")

    def test_decimal_ip_exits(self):
        # 十进制 IP 2852039166 = 169.254.169.254（云元数据），ipaddress 漏、inet_aton 认 → fallback 补
        with pytest.raises(SystemExit):
            video._assert_public_url("http://2852039166/a.png")

    def test_hex_ip_exits(self):
        # 十六进制 IP 0xA9FEA9FE = 169.254.169.254
        with pytest.raises(SystemExit):
            video._assert_public_url("http://0xA9FEA9FE/a.png")

    def test_octal_ip_exits(self):
        # 八进制 IP 0251.0376.0251.0376 = 169.254.169.254
        with pytest.raises(SystemExit):
            video._assert_public_url("http://0251.0376.0251.0376/a.png")


# ---------- create_task（mock urlopen）----------
class _FakeResp:
    def __init__(self, payload: bytes):
        self._p = payload

    def read(self, length=-1):
        # length 参数兼容 shutil.copyfileobj 的流式读取（视频下载走 copyfileobj）；
        # 一次性返回后清空，让 copyfileobj 下次读到空即停，不死循环
        data, self._p = self._p, b""
        return data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _http_error(code: int, body: bytes = b'{"error":"x"}', headers=None):
    return urllib.error.HTTPError("http://x", code, "err", headers or {}, io.BytesIO(body))


def _seq_urlopen(monkeypatch, responses):
    """按脚本依次返回响应/抛异常的 urlopen 桩。"""
    it = iter(responses)

    def urlopen(req, timeout):
        item = next(it)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(video.urllib.request, "urlopen", urlopen)


class TestCreateTask:
    def test_ok_returns_video_id(self, monkeypatch):
        payload = json.dumps({"video_id": "vid_123", "status": "queued"}).encode()
        monkeypatch.setattr(
            video.urllib.request,
            "urlopen",
            lambda req, timeout: _FakeResp(payload),
        )
        vid, r = video.create_task({"model": "x"}, "k")
        assert vid == "vid_123"
        assert r["status"] == "queued"

    def test_fallback_to_id_field(self, monkeypatch):
        # 无 video_id 时回退到 id
        payload = json.dumps({"id": "task_456"}).encode()
        monkeypatch.setattr(
            video.urllib.request,
            "urlopen",
            lambda req, timeout: _FakeResp(payload),
        )
        vid, _ = video.create_task({}, "k")
        assert vid == "task_456"

    def test_no_id_exits(self, monkeypatch):
        payload = b'{"status":"queued"}'
        monkeypatch.setattr(
            video.urllib.request,
            "urlopen",
            lambda req, timeout: _FakeResp(payload),
        )
        with pytest.raises(SystemExit):
            video.create_task({}, "k")

    def test_http_401_exits(self, monkeypatch):
        monkeypatch.setattr(
            video.urllib.request,
            "urlopen",
            lambda req, timeout: (_ for _ in ()).throw(_http_error(401)),
        )
        with pytest.raises(SystemExit) as e:
            video.create_task({}, "k")
        assert "401" in str(e.value)

    def test_http_400_exits(self, monkeypatch):
        monkeypatch.setattr(
            video.urllib.request,
            "urlopen",
            lambda req, timeout: (_ for _ in ()).throw(_http_error(400)),
        )
        with pytest.raises(SystemExit) as e:
            video.create_task({}, "k")
        assert "400" in str(e.value)


# ---------- poll_task（mock urlopen + time）----------
class TestPollTask:
    def test_completed_returns_resp(self, monkeypatch):
        payload = json.dumps(
            {"status": "completed", "url": "http://mp4"}
        ).encode()
        monkeypatch.setattr(
            video.urllib.request,
            "urlopen",
            lambda req, timeout: _FakeResp(payload),
        )
        r = video.poll_task("vid", "k", interval=1, max_wait=60)
        assert r["status"] == "completed"
        assert r["url"] == "http://mp4"

    def test_failed_exits(self, monkeypatch):
        payload = json.dumps({"status": "failed", "error": "boom"}).encode()
        monkeypatch.setattr(
            video.urllib.request,
            "urlopen",
            lambda req, timeout: _FakeResp(payload),
        )
        with pytest.raises(SystemExit) as e:
            video.poll_task("vid", "k", interval=1, max_wait=60)
        assert "boom" in str(e.value) or "failed" in str(e.value)

    def test_timeout_exits(self, monkeypatch):
        # 第一次 monotonic() 算出小 deadline(0+60=60)，
        # 第二次循环检查返回越界值(100_000>60) → 循环不进 → 立即 timeout
        times = iter([0, 100_000])
        monkeypatch.setattr(video.time, "monotonic", lambda: next(times))
        monkeypatch.setattr(video.time, "sleep", lambda s: None)
        with pytest.raises(SystemExit) as e:
            video.poll_task("vid", "k", interval=1, max_wait=60)
        assert "超时" in str(e.value) or "timeout" in str(e.value).lower() or "video_id" in str(e.value)

    def test_404_exits(self, monkeypatch):
        def raise_404(req, timeout):
            raise _http_error(404)

        monkeypatch.setattr(video.urllib.request, "urlopen", raise_404)
        monkeypatch.setattr(video.time, "sleep", lambda s: None)
        with pytest.raises(SystemExit) as e:
            video.poll_task("vid", "k", interval=1, max_wait=60)
        assert "404" in str(e.value) or "不存在" in str(e.value)

    def test_queued_then_completed(self, monkeypatch):
        # 第一次 queued，第二次 completed（验证循环继续）
        responses = iter([
            _FakeResp(json.dumps({"status": "queued", "progress": 0}).encode()),
            _FakeResp(json.dumps({"status": "in_progress", "progress": 50}).encode()),
            _FakeResp(json.dumps({"status": "completed", "progress": 100, "url": "http://mp4"}).encode()),
        ])
        monkeypatch.setattr(
            video.urllib.request, "urlopen", lambda req, timeout: next(responses)
        )
        monkeypatch.setattr(video.time, "sleep", lambda s: None)
        r = video.poll_task("vid", "k", interval=0, max_wait=60)
        assert r["status"] == "completed"


# ---------- 轮询错误码（调研建议#9） ----------
class TestPollTaskErrorCodes:
    def test_failed_code_generation_failed(self, monkeypatch):
        payload = json.dumps({"status": "failed", "error": "boom"}).encode()
        monkeypatch.setattr(
            video.urllib.request, "urlopen",
            lambda req, timeout: _FakeResp(payload),
        )
        with pytest.raises(SystemExit) as e:
            video.poll_task("vid", "k", interval=1, max_wait=60)
        assert "code=generation_failed" in str(e.value)

    def test_404_code_no_task(self, monkeypatch):
        def raise_404(req, timeout):
            raise _http_error(404)

        monkeypatch.setattr(video.urllib.request, "urlopen", raise_404)
        monkeypatch.setattr(video.time, "sleep", lambda s: None)
        with pytest.raises(SystemExit) as e:
            video.poll_task("vid", "k", interval=1, max_wait=60)
        assert "code=no_task" in str(e.value)

    def test_timeout_code(self, monkeypatch):
        times = iter([0, 100_000])
        monkeypatch.setattr(video.time, "monotonic", lambda: next(times))
        monkeypatch.setattr(video.time, "sleep", lambda s: None)
        with pytest.raises(SystemExit) as e:
            video.poll_task("vid", "k", interval=1, max_wait=60)
        assert "code=timeout" in str(e.value)

    def test_save_video_malformed_code(self, tmp_path):
        with pytest.raises(SystemExit) as e:
            video.save_video({"status": "completed"}, tmp_path / "o.mp4")
        assert "code=malformed_response" in str(e.value)

    def test_save_video_undersized_code(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            video, "download_video",
            lambda url, out_path: out_path.write_bytes(b"x" * 100),
        )
        with pytest.raises(SystemExit) as e:
            video.save_video({"url": "http://mp4"}, tmp_path / "o.mp4")
        assert "code=abnormal_artifact" in str(e.value)


# ---------- save_video ----------
class TestSaveVideo:
    def test_ok_downloads(self, tmp_path, monkeypatch):
        called = {}

        def fake_dl(url, out_path):
            called["url"] = url
            out_path.write_bytes(b"x" * (20 * 1024))  # >10KB

        monkeypatch.setattr(video, "download_video", fake_dl)
        out = tmp_path / "o.mp4"
        video.save_video({"url": "http://mp4"}, out)
        assert called["url"] == "http://mp4"
        assert out.exists()

    def test_no_url_exits(self, tmp_path):
        with pytest.raises(SystemExit):
            video.save_video({"status": "completed"}, tmp_path / "o.mp4")

    def test_small_file_exits(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            video,
            "download_video",
            lambda url, out_path: out_path.write_bytes(b"x" * 100),  # <10KB
        )
        with pytest.raises(SystemExit):
            video.save_video({"url": "http://mp4"}, tmp_path / "o.mp4")


# ---------- to_curl ----------
class TestToCurl:
    def test_key_masked(self):
        body = {"model": video.MODEL, "prompt": "p"}
        s = video.to_curl(body, "agn-test1234567890")
        assert "agn-test***" in s
        assert "1234567890" not in s


# ---------- 常量一致性 ----------
class TestConstants:
    def test_durations_all_8n_plus_1(self):
        for dur, (nf, fr) in video.DURATIONS.items():
            assert (nf - 1) % 8 == 0, dur
            assert nf <= 441, dur
            assert 1 <= fr <= 60, dur

    def test_resolutions_pairs(self):
        for k, (w, h) in video.RESOLUTIONS.items():
            assert isinstance(w, int) and isinstance(h, int), k


# ---------- 失败留痕（调研建议#1） ----------
class TestFailedSidecarIntegration:
    def test_poll_failed_writes_failed_sidecar(self, tmp_path, monkeypatch):
        # 走 main() 全流程：创建→轮询失败→main 的 except 留痕
        monkeypatch.setenv("AGNES_API_KEY", "agn-test")
        monkeypatch.setattr(
            sys, "argv",
            ["video.py", "t2vid", "-i", "测", "--output-dir", str(tmp_path),
             "--poll-interval", "1", "--max-wait", "60"],
        )
        responses = iter([
            _FakeResp(json.dumps({"video_id": "vid_1", "status": "queued"}).encode()),
            _FakeResp(json.dumps({"status": "failed", "error": "审核不通过"}).encode()),
        ])
        monkeypatch.setattr(video.urllib.request, "urlopen", lambda req, timeout: next(responses))
        monkeypatch.setattr(video.time, "sleep", lambda s: None)
        with pytest.raises(SystemExit):
            video.main()
        scs = list(tmp_path.glob("*-failed-*.json"))
        assert len(scs) == 1
        content = scs[0].read_text(encoding="utf-8")
        assert "审核不通过" in content
        assert json.loads(content)["video_id"] == "vid_1"


# ---------- --resume 恢复句柄（调研建议#3） ----------
class TestResumeMode:
    def _argv(self, tmp_path, vid, *extra):
        return ["video.py", "t2vid", "--resume", vid, "--output-dir", str(tmp_path),
                "--poll-interval", "1", "--max-wait", "60", *extra]

    def test_resume_without_instruction_ok(self, monkeypatch, tmp_path):
        monkeypatch.setenv("AGNES_API_KEY", "agn-test")
        monkeypatch.setattr(sys, "argv", self._argv(tmp_path, "vid_9"))
        a = video.parse_args()
        assert a.resume == "vid_9"
        assert a.instruction is None

    def test_no_instruction_no_resume_errors(self, monkeypatch, tmp_path):
        monkeypatch.setenv("AGNES_API_KEY", "agn-test")
        monkeypatch.setattr(sys, "argv", ["video.py", "t2vid", "--output-dir", str(tmp_path)])
        with pytest.raises(SystemExit):
            video.parse_args()

    def test_resume_with_image_errors(self, monkeypatch, tmp_path):
        monkeypatch.setenv("AGNES_API_KEY", "agn-test")
        monkeypatch.setattr(sys, "argv", self._argv(tmp_path, "v", "--image", "https://x/a.png"))
        with pytest.raises(SystemExit):
            video.parse_args()

    def test_resume_skips_create_and_downloads(self, monkeypatch, tmp_path, capsys):
        # 直接轮询 vid_9 → completed → 下载；创建接口不应被调用
        monkeypatch.setenv("AGNES_API_KEY", "agn-test")
        monkeypatch.setattr(sys, "argv", self._argv(tmp_path, "vid_9"))
        responses = iter([
            _FakeResp(json.dumps({"status": "completed", "progress": 100, "url": "http://mp4/x"}).encode()),
            _FakeResp(b"x" * (20 * 1024)),
        ])
        monkeypatch.setattr(video.urllib.request, "urlopen", lambda req, timeout: next(responses))
        assert video.main() == 0
        assert list(tmp_path.glob("*.mp4")), "resume 成功必须落盘 mp4"

    def test_resume_timeout_emits_machine_readable_handle(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setenv("AGNES_API_KEY", "agn-test")
        monkeypatch.setattr(sys, "argv", self._argv(tmp_path, "vid_9"))
        # 轮询 deadline 用单调钟（审查 L-5）：只需两个值，伪时钟末值重复对多出的消费者鲁棒
        class _SeqTime:
            def __init__(self, *vals):
                self._vals, self._i = list(vals), 0

            def __call__(self):
                v = self._vals[min(self._i, len(self._vals) - 1)]
                self._i += 1
                return v

        monkeypatch.setattr(video.time, "monotonic", _SeqTime(0, 100_000))
        monkeypatch.setattr(video.time, "sleep", lambda s: None)
        with pytest.raises(SystemExit) as e:
            video.main()
        out = capsys.readouterr()
        assert "WUDAOZI_RESUME=vid_9" in out.out, "stdout 必须有机器可读恢复句柄"
        assert "--resume vid_9" in str(e.value)
        assert "WUDAOZI_RESUME" not in out.err, "句柄只走 stdout（日志走 stderr，互不污染）"

    def test_normal_failure_also_emits_resume_handle(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setenv("AGNES_API_KEY", "agn-test")
        monkeypatch.setattr(
            sys, "argv",
            ["video.py", "t2vid", "-i", "测", "--output-dir", str(tmp_path),
             "--poll-interval", "1", "--max-wait", "60"],
        )
        responses = iter([
            _FakeResp(json.dumps({"video_id": "vid_1", "status": "queued"}).encode()),
            _FakeResp(json.dumps({"status": "failed", "error": "审核不通过"}).encode()),
        ])
        monkeypatch.setattr(video.urllib.request, "urlopen", lambda req, timeout: next(responses))
        monkeypatch.setattr(video.time, "sleep", lambda s: None)
        with pytest.raises(SystemExit):
            video.main()
        assert "WUDAOZI_RESUME=vid_1" in capsys.readouterr().out


# ---------- 创建任务失败分类重试（调研建议#2） ----------
class TestCreateTaskRetry:
    def test_connect_error_retries_then_succeeds(self, monkeypatch):
        payload = json.dumps({"video_id": "vid_1", "status": "queued"}).encode()
        _seq_urlopen(monkeypatch, [
            urllib.error.URLError(ConnectionRefusedError(111, "Connection refused")),
            _FakeResp(payload),
        ])
        monkeypatch.setattr(video.time, "sleep", lambda s: None)
        monkeypatch.setattr(video.random, "uniform", lambda a, b: 0.0)
        vid, _ = video.create_task({"model": "x"}, "k")
        assert vid == "vid_1"

    def test_dns_gaierror_is_connect_phase(self, monkeypatch):
        payload = json.dumps({"video_id": "vid_2"}).encode()
        _seq_urlopen(monkeypatch, [
            urllib.error.URLError(socket.gaierror(8, "nodename nor servname")),
            _FakeResp(payload),
        ])
        monkeypatch.setattr(video.time, "sleep", lambda s: None)
        monkeypatch.setattr(video.random, "uniform", lambda a, b: 0.0)
        assert video._is_connect_error(urllib.error.URLError(socket.gaierror())) is True
        assert video._is_connect_error(urllib.error.URLError("dns fail")) is False
        vid, _ = video.create_task({"model": "x"}, "k")
        assert vid == "vid_2"

    def test_budget_exhausted_exits_network_error(self, monkeypatch):
        _seq_urlopen(monkeypatch, [
            urllib.error.URLError(ConnectionRefusedError(111, "refused")),
            urllib.error.URLError(ConnectionRefusedError(111, "refused")),
        ])
        monotonic = iter([0, 61])
        monkeypatch.setattr(video.time, "monotonic", lambda: next(monotonic))
        monkeypatch.setattr(video.time, "sleep", lambda s: None)
        monkeypatch.setattr(video.random, "uniform", lambda a, b: 0.0)
        with pytest.raises(SystemExit) as e:
            video.create_task({"model": "x"}, "k")
        assert "code=network_error" in str(e.value)

    def test_bare_timeout_never_retried(self, monkeypatch):
        # 读超时 = 请求可能已送达、任务可能已创建，自动重试会双倍计费（agnes 无幂等键）
        calls = {"n": 0}

        def urlopen(req, timeout):
            calls["n"] += 1
            raise TimeoutError()

        monkeypatch.setattr(video.urllib.request, "urlopen", urlopen)
        with pytest.raises(SystemExit) as e:
            video.create_task({"model": "x"}, "k")
        assert calls["n"] == 1, "裸超时绝不自动重试"
        assert "code=timeout" in str(e.value)
        assert "可能已创建" in str(e.value)

    def test_http_4xx_never_retried(self, monkeypatch):
        calls = {"n": 0}

        def urlopen(req, timeout):
            calls["n"] += 1
            raise _http_error(401)

        monkeypatch.setattr(video.urllib.request, "urlopen", urlopen)
        with pytest.raises(SystemExit) as e:
            video.create_task({"model": "x"}, "k")
        assert calls["n"] == 1
        assert "code=auth_error" in str(e.value)


# ---------- 轮询重试策略：Retry-After 感知 + 终态常量（调研建议#2） ----------
class TestPollRetryPolicy:
    def _run(self, monkeypatch, responses, uniform_ret=3.25):
        sleeps = []
        _seq_urlopen(monkeypatch, responses)
        monkeypatch.setattr(video.time, "sleep", lambda s: sleeps.append(s))
        monkeypatch.setattr(video.random, "uniform", lambda a, b: uniform_ret)
        return sleeps

    def test_429_honors_retry_after(self, monkeypatch):
        sleeps = self._run(monkeypatch, [
            _http_error(429, headers={"Retry-After": "7"}),
            _FakeResp(json.dumps({"status": "completed", "url": "http://mp4"}).encode()),
        ])
        r = video.poll_task("vid", "k", interval=1, max_wait=60)
        assert r["status"] == "completed"
        assert sleeps == [7.0], "有合法 Retry-After 必须精确遵循"

    def test_429_zero_retry_after_falls_back_to_jitter(self, monkeypatch):
        # Retry-After: 0 视为无效 → 回退退避抖动（防 0 值死循环）
        sleeps = self._run(monkeypatch, [
            _http_error(429, headers={"Retry-After": "0"}),
            _FakeResp(json.dumps({"status": "completed", "url": "http://mp4"}).encode()),
        ])
        video.poll_task("vid", "k", interval=1, max_wait=60)
        assert sleeps == [3.25]

    def test_429_without_header_uses_jitter(self, monkeypatch):
        sleeps = self._run(monkeypatch, [
            _http_error(429),
            _FakeResp(json.dumps({"status": "completed", "url": "http://mp4"}).encode()),
        ])
        video.poll_task("vid", "k", interval=1, max_wait=60)
        assert sleeps == [3.25], "无 header 用 jitter 退避替代固定 interval"

    def test_503_504_same_as_429(self, monkeypatch):
        sleeps = self._run(monkeypatch, [
            _http_error(503, headers={"Retry-After": "12"}),
            _FakeResp(json.dumps({"status": "completed", "url": "http://mp4"}).encode()),
        ])
        video.poll_task("vid", "k", interval=1, max_wait=60)
        assert sleeps == [12.0]

    def test_401_poll_exits_immediately(self, monkeypatch):
        calls = {"n": 0}

        def urlopen(req, timeout):
            calls["n"] += 1
            raise _http_error(401)

        monkeypatch.setattr(video.urllib.request, "urlopen", urlopen)
        monkeypatch.setattr(video.time, "sleep", lambda s: None)
        with pytest.raises(SystemExit) as e:
            video.poll_task("vid", "k", interval=1, max_wait=60)
        assert calls["n"] == 1, "4xx 重试无意义，立即退出"
        assert "code=auth_error" in str(e.value)

    def test_unknown_status_warns_after_3(self, monkeypatch, capsys):
        responses = [
            _FakeResp(json.dumps({"status": "mystery", "progress": 0}).encode())
            for _ in range(3)
        ] + [_FakeResp(json.dumps({"status": "completed", "url": "http://mp4"}).encode())]
        self._run(monkeypatch, responses)
        video.poll_task("vid", "k", interval=1, max_wait=60)
        err = capsys.readouterr().err
        assert "未知状态" in err and "原始响应" in err, "连续 3 次未知状态必须告警并附原始响应"

    def test_known_status_resets_unknown_streak(self, monkeypatch, capsys):
        responses = [
            _FakeResp(json.dumps({"status": "mystery"}).encode()),
            _FakeResp(json.dumps({"status": "mystery"}).encode()),
            _FakeResp(json.dumps({"status": "queued"}).encode()),   # 已知状态 → 计数重置
            _FakeResp(json.dumps({"status": "mystery"}).encode()),
            _FakeResp(json.dumps({"status": "mystery"}).encode()),  # 重置后仅 2 连，不告警
            _FakeResp(json.dumps({"status": "completed", "url": "http://mp4"}).encode()),
        ]
        self._run(monkeypatch, responses)
        video.poll_task("vid", "k", interval=1, max_wait=60)
        err = capsys.readouterr().err
        assert "未知状态" not in err, "已知状态插入后连续计数必须重置（未达连续 3 次不告警）"


class TestTerminalConstant:
    def test_terminal_states(self):
        assert video.TERMINAL == {"completed", "failed"}
        assert "queued" in video.KNOWN_STATES and "in_progress" in video.KNOWN_STATES


# ---------- 审查修复回归（性能 F1，架构 M-4） ----------
class TestReviewFixes:
    def test_retry_after_clamped_to_remaining_budget(self, monkeypatch):
        # Retry-After: 3600 不得睡穿 max-wait=60（性能 F1：单次 sleep 无上界）
        sleeps = []
        responses = iter([
            _http_error(429, headers={"Retry-After": "3600"}),
        ])
        def urlopen(req, timeout):
            item = next(responses)
            if isinstance(item, Exception):
                raise item
            return item
        monkeypatch.setattr(video.urllib.request, "urlopen", urlopen)
        monotonic = iter([0, 0, 0, 100_000])  # deadline → while 检查 → 钳制计算 → 循环检查
        monkeypatch.setattr(video.time, "monotonic", lambda: next(monotonic))
        monkeypatch.setattr(video.time, "sleep", lambda s: sleeps.append(s))
        with pytest.raises(SystemExit) as e:
            video.poll_task("vid", "k", interval=1, max_wait=60)
        assert sleeps == [60.0], "sleep 必须被钳制到剩余预算"
        assert "code=timeout" in str(e.value)

    def test_keyboard_interrupt_emits_resume_handle(self, monkeypatch, tmp_path, capsys):
        # Ctrl-C 不是 SystemExit——中断也要拿到 WUDAOZI_RESUME + 留痕（架构 M-4）
        monkeypatch.setenv("AGNES_API_KEY", "agn-test")
        monkeypatch.setattr(
            sys, "argv",
            ["video.py", "t2vid", "--resume", "vid_7", "--output-dir", str(tmp_path),
             "--poll-interval", "1", "--max-wait", "60"],
        )
        def fake_poll(video_id, api_key, interval, max_wait):
            raise KeyboardInterrupt()
        monkeypatch.setattr(video, "poll_task", fake_poll)
        with pytest.raises(KeyboardInterrupt):
            video.main()
        assert "WUDAOZI_RESUME=vid_7" in capsys.readouterr().out
        scs = list(tmp_path.glob("*-failed-*.json"))
        assert len(scs) == 1
