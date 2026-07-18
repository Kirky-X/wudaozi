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
        mode="t2vid", instruction="测", image=None, seed=None, negative_instruction=None
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


# ---------- create_task（mock urlopen）----------
class _FakeResp:
    def __init__(self, payload: bytes):
        self._p = payload

    def read(self):
        return self._p

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _http_error(code: int, body: bytes = b'{"error":"x"}'):
    return urllib.error.HTTPError("http://x", code, "err", {}, io.BytesIO(body))


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
        # 第一次 time.time() 算出小 deadline(0+60=60)，
        # 第二次循环检查返回越界值(100_000>60) → 循环不进 → 立即 timeout
        times = iter([0, 100_000])
        monkeypatch.setattr(video.time, "time", lambda: next(times))
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
