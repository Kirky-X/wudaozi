#!/usr/bin/env python3
"""video.py 冒烟测试（离线）——8n+1 硬约束 + 异步任务流 + SSRF 防护。

与 scripts/test_video.py 互补：冒烟级钉死 num_frames 8n+1、四模式请求体差异
（t2vid/ti2vid/multi/keyframes）、公网 URL 校验、轮询状态机、CLI dry-run。
跑法：python3 -m pytest tests -q
"""
import io
import json
import os
import subprocess
import sys
import unittest
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import video  # noqa: E402

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "video.py"


def _ns(**kw):
    base = dict(mode="t2vid", instruction="猫在沙滩走", image=None, images=None,
                seed=None, negative_instruction=None)
    base.update(kw)
    return SimpleNamespace(**base)


class TestFrameConstraints(unittest.TestCase):
    """num_frames 8n+1 且 ≤441 是模型硬约束，入口必须拒绝。"""

    def test_valid(self):
        for n in (81, 121, 241, 441):
            video.validate_num_frames(n)

    def test_not_8n_plus_1_exits(self):
        with self.assertRaises(SystemExit):
            video.validate_num_frames(100)

    def test_over_441_exits(self):
        with self.assertRaises(SystemExit):
            video.validate_num_frames(449)

    def test_frame_rate_range(self):
        for fr in (1, 24, 60):
            video.validate_frame_rate(fr)
        with self.assertRaises(SystemExit):
            video.validate_frame_rate(0)
        with self.assertRaises(SystemExit):
            video.validate_frame_rate(61)

    def test_all_duration_presets_legal(self):
        for dur, (nf, fr) in video.DURATIONS.items():
            self.assertEqual((nf - 1) % 8, 0, dur)
            self.assertLessEqual(nf, 441, dur)
            self.assertTrue(1 <= fr <= 60, dur)

    def test_resolve_frames_custom_overrides_duration(self):
        self.assertEqual(video.resolve_frames(
            SimpleNamespace(num_frames=161, frame_rate=30, duration="10s")), (161, 30))
        self.assertEqual(video.resolve_frames(
            SimpleNamespace(num_frames=None, frame_rate=None, duration="10s")), (241, 24))

    def test_resolve_resolution_rules(self):
        self.assertEqual(video.resolve_resolution(
            SimpleNamespace(aspect="9:16", width=None, height=None)), (768, 1152))
        self.assertEqual(video.resolve_resolution(
            SimpleNamespace(aspect=None, width=None, height=None)), (1152, 768))
        with self.assertRaises(SystemExit):
            video.resolve_resolution(SimpleNamespace(aspect=None, width=800, height=None))


class TestBodyAssembly(unittest.TestCase):
    def test_t2vid_minimal(self):
        body = video.build_body(_ns(), 1152, 768, 121, 24)
        self.assertEqual(body["model"], video.MODEL)
        self.assertNotIn("image", body)
        self.assertNotIn("extra_body", body)

    def test_seed_and_negative_optional(self):
        body = video.build_body(_ns(seed=7, negative_instruction="模糊"), 1152, 768, 121, 24)
        self.assertEqual(body["seed"], 7)
        self.assertEqual(body["negative_prompt"], "模糊")

    def test_ti2vid_requires_public_url(self):
        body = video.build_body(_ns(mode="ti2vid", image="https://x/a.png"),
                                768, 1152, 121, 24)
        self.assertEqual(body["image"], "https://x/a.png")
        with self.assertRaises(SystemExit):
            video.build_body(_ns(mode="ti2vid", image=None), 768, 1152, 121, 24)
        # 文档明确：视频首帧不接受本地/base64
        with self.assertRaises(SystemExit):
            video.build_body(_ns(mode="ti2vid", image="/local/a.png"), 768, 1152, 121, 24)

    def test_multi_needs_two_urls(self):
        urls = ["https://x/1.png", "https://x/2.png"]
        body = video.build_body(_ns(mode="multi", images=urls), 1152, 768, 121, 24)
        self.assertEqual(body["extra_body"], {"image": urls})  # multi 不带 mode 字段
        with self.assertRaises(SystemExit):  # 单张应走 ti2vid
            video.build_body(_ns(mode="multi", images=urls[:1]), 768, 1152, 121, 24)

    def test_keyframes_adds_mode_field(self):
        urls = ["https://x/1.png", "https://x/2.png"]
        body = video.build_body(_ns(mode="keyframes", images=urls), 1152, 768, 121, 24)
        self.assertEqual(body["extra_body"], {"image": urls, "mode": "keyframes"})

    def test_image_images_mutually_exclusive(self):
        with self.assertRaises(SystemExit):
            video.build_body(_ns(mode="ti2vid", image="https://x/a.png",
                                 images=["https://x/b.png", "https://x/c.png"]),
                             768, 1152, 121, 24)


class TestSsrfGuard(unittest.TestCase):
    """图 URL 会由服务端拉取，必须挡住内网/元数据地址。"""

    def test_public_ok(self):
        video._assert_public_url("https://example.com/a.png")

    def test_non_http_rejected(self):
        with self.assertRaises(SystemExit):
            video._assert_public_url("file:///etc/passwd")

    def test_localhost_rejected(self):
        with self.assertRaises(SystemExit):
            video._assert_public_url("http://localhost/a.png")

    def test_private_and_metadata_rejected(self):
        for u in ("http://127.0.0.1/a.png", "http://10.0.0.1/a.png",
                  "http://192.168.1.1/a.png", "http://169.254.169.254/latest/meta-data/"):
            with self.assertRaises(SystemExit, msg=u):
                video._assert_public_url(u)

    def test_nonstandard_ip_forms_rejected(self):
        # inet_aton 兜底：十进制/十六进制/八进制写法的 169.254.169.254
        for u in ("http://2852039166/a.png", "http://0xA9FEA9FE/a.png",
                  "http://0251.0376.0251.0376/a.png"):
            with self.assertRaises(SystemExit, msg=u):
                video._assert_public_url(u)


class TestAsyncTaskFlow(unittest.TestCase):
    """创建→轮询→下载 状态机（网络层 mock）。"""

    class _FakeResp:
        def __init__(self, payload):
            self._p = payload

        def read(self):
            return self._p

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def _patch_urlopen(self, payloads):
        if isinstance(payloads, dict):
            payloads = [payloads]  # 单响应 dict 统一包装，避免遍历出 key
        it = iter([self._FakeResp(p if isinstance(p, bytes) else json.dumps(p).encode())
                   for p in payloads])
        return mock.patch.object(video.urllib.request, "urlopen",
                                 lambda req, timeout=None: next(it))

    def test_create_task_extracts_video_id(self):
        with self._patch_urlopen({"video_id": "vid_1", "status": "queued"}):
            vid, r = video.create_task({}, "k")
        self.assertEqual(vid, "vid_1")

    def test_create_task_id_fallbacks(self):
        for field in ("id", "task_id"):
            with self.subTest(field=field):
                with self._patch_urlopen({field: "t1"}):
                    vid, _ = video.create_task({}, "k")
                self.assertEqual(vid, "t1")

    def test_create_task_without_id_exits(self):
        with self._patch_urlopen({"status": "queued"}):
            with self.assertRaises(SystemExit):
                video.create_task({}, "k")

    def test_create_task_http_401_exits(self):
        err = urllib.error.HTTPError("http://x", 401, "err", {}, io.BytesIO(b"{}"))
        with mock.patch.object(video.urllib.request, "urlopen",
                               lambda req, timeout=None: (_ for _ in ()).throw(err)):
            with self.assertRaises(SystemExit) as cm:
                video.create_task({}, "k")
            self.assertIn("401", str(cm.exception))

    def test_poll_completed(self):
        with self._patch_urlopen([{"status": "queued", "progress": 0},
                                  {"status": "completed", "progress": 100,
                                   "url": "http://mp4"}]):
            with mock.patch.object(video.time, "sleep", lambda s: None):
                r = video.poll_task("vid", "k", interval=0, max_wait=60)
        self.assertEqual(r["status"], "completed")

    def test_poll_failed_exits(self):
        with self._patch_urlopen({"status": "failed", "error": "boom"}):
            with self.assertRaises(SystemExit) as cm:
                video.poll_task("vid", "k", interval=1, max_wait=60)
        self.assertIn("boom", str(cm.exception))

    def test_poll_timeout_exits(self):
        times = iter([0, 100_000])  # 第二次检查已过 deadline → 立即超时
        with mock.patch.object(video.time, "time", lambda: next(times)), \
                mock.patch.object(video.time, "sleep", lambda s: None):
            with self.assertRaises(SystemExit) as cm:
                video.poll_task("vid", "k", interval=1, max_wait=60)
        self.assertIn("video_id", str(cm.exception))  # 超时信息带可手动查询的 id

    def test_save_video_size_guard(self):
        import tempfile
        out = Path(tempfile.mkdtemp()) / "o.mp4"
        with mock.patch.object(video, "download_video",
                               lambda url, p: p.write_bytes(b"x" * 100)):
            with self.assertRaises(SystemExit):  # <10KB 疑似异常
                video.save_video({"url": "http://mp4"}, out)
        self.assertFalse(out.exists())


class TestCliSmoke(unittest.TestCase):
    def _run(self, *args, env_extra=None):
        env = dict(os.environ)
        env.pop("AGNES_API_KEY", None)
        env.update(env_extra or {})
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            capture_output=True, text=True, timeout=60, env=env,
        )

    def test_help(self):
        r = self._run("--help")
        self.assertEqual(r.returncode, 0)
        for mode in ("t2vid", "ti2vid", "multi", "keyframes"):
            self.assertIn(mode, r.stdout)

    def test_dry_run_without_key_exits(self):
        r = self._run("t2vid", "-i", "x", "--dry-run")
        self.assertEqual(r.returncode, 1)
        self.assertIn("AGNES_API_KEY", r.stderr)

    def test_dry_run_ok(self):
        r = self._run("t2vid", "-i", "x", "--duration", "10s", "--dry-run",
                      env_extra={"AGNES_API_KEY": "agn-test-key-12345"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("241@24fps", r.stderr)

    def test_illegal_frames_rejected_even_dry_run(self):
        r = self._run("t2vid", "-i", "x", "--num-frames", "100", "--dry-run",
                      env_extra={"AGNES_API_KEY": "agn-test-key-12345"})
        self.assertEqual(r.returncode, 1)
        self.assertIn("8n+1", r.stderr)

    def test_ti2vid_without_image_exits(self):
        r = self._run("ti2vid", "-i", "x", "--dry-run",
                      env_extra={"AGNES_API_KEY": "agn-test-key-12345"})
        self.assertEqual(r.returncode, 1)


if __name__ == "__main__":
    unittest.main()
