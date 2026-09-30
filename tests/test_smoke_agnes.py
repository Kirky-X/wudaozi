#!/usr/bin/env python3
"""agnes.py 冒烟测试（离线）——钉死最容易反的约定。

与 scripts/test_agnes.py（深层 166 测）互补：本文件只做冒烟级——
size 的 WxH 方向、prompt 组装、错误分流、key 截断、CLI dry-run。
跑法：python3 -m pytest tests -q
"""
import base64
import os
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import agnes  # noqa: E402

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "agnes.py"


def _ns(**kw):
    base = dict(mode="t2i", instruction="cat", input=None, base64=False,
                strict_prompt=False, transparent="off", mask=None)
    base.update(kw)
    return SimpleNamespace(**base)


class TestSizeSemantics(unittest.TestCase):
    """agnes size 是 WxH 字符串，方向极易写反——必须钉死。"""

    def test_size_is_wxh(self):
        # aspect 9:16 → (H=1824, W=1024) → API size="1024x1824"
        body = agnes.build_body(_ns(), 1824, 1024)
        self.assertEqual(body["size"], "1024x1824")

    def test_aspect_tuple_is_h_w(self):
        self.assertEqual(agnes.ASPECT_RATIOS["9:16"], (1824, 1024))
        self.assertEqual(agnes.ASPECT_RATIOS["16:9"], (1024, 1824))

    def test_snap_aligns_16(self):
        h, w, adj = agnes.snap_size(800, 600)
        self.assertEqual((h, w), (800, 608))
        self.assertTrue(adj)

    def test_single_dimension_exits(self):
        with self.assertRaises(SystemExit):
            agnes.resolve_size(SimpleNamespace(aspect=None, height=800, width=None))


class TestPromptAssembly(unittest.TestCase):
    def test_default_url_format(self):
        body = agnes.build_body(_ns(), 1024, 1024)
        self.assertEqual(body["extra_body"], {"response_format": "url"})
        self.assertNotIn("return_base64", body)
        self.assertEqual(body["model"], agnes.MODEL)

    def test_base64_t2i_uses_return_base64(self):
        body = agnes.build_body(_ns(base64=True), 1024, 1024)
        self.assertTrue(body["return_base64"])
        self.assertEqual(body["extra_body"], {})

    def test_strict_prompt_prefixes_guard(self):
        body = agnes.build_body(_ns(strict_prompt=True), 1024, 1024)
        self.assertTrue(body["prompt"].startswith(agnes.PROMPT_GUARD))

    def test_transparent_native_sets_background(self):
        body = agnes.build_body(_ns(transparent="native"), 1024, 1024)
        self.assertEqual(body["extra_body"]["background"], "transparent")


class TestTi2iInput(unittest.TestCase):
    def test_local_ref_becomes_data_uri(self, ):
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(b"\x89PNG")
            p = f.name
        try:
            body = agnes.build_body(_ns(mode="ti2i", input=p), 1024, 1024)
            self.assertTrue(body["extra_body"]["image"][0].startswith(
                "data:image/png;base64,"))
        finally:
            Path(p).unlink(missing_ok=True)

    def test_remote_url_passthrough(self):
        body = agnes.build_body(_ns(mode="ti2i", input="https://e.com/a.jpg"), 1024, 1024)
        self.assertEqual(body["extra_body"]["image"], ["https://e.com/a.jpg"])

    def test_missing_input_exits(self):
        with self.assertRaises(SystemExit):
            agnes.build_body(_ns(mode="ti2i", input=None), 1024, 1024)

    def test_missing_file_exits(self):
        with self.assertRaises(SystemExit):
            agnes.image_to_data_uri("/no/such/file.png")

    def test_unsupported_format_exits(self):
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".bmp", delete=False) as f:
            f.write(b"BM")
            p = f.name
        try:
            with self.assertRaises(SystemExit):
                agnes.image_to_data_uri(p)
        finally:
            Path(p).unlink(missing_ok=True)

    def test_mask_requires_png(self):
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(b"jpeg")
            p = f.name
        try:
            with self.assertRaises(SystemExit):
                agnes.build_body(_ns(mode="ti2i", input="https://e.com/a.png", mask=p),
                                 1024, 1024)
        finally:
            Path(p).unlink(missing_ok=True)


class TestErrorHandling(unittest.TestCase):
    def test_save_image_no_data_exits(self):
        with self.assertRaises(SystemExit):
            agnes.save_image({"data": []}, Path("/tmp/never-written.png"))

    def test_save_image_b64_branch(self):
        import tempfile
        out = Path(tempfile.mkdtemp()) / "o.png"
        b64 = base64.b64encode(b"x" * 2048).decode()
        item = agnes.save_image({"data": [{"b64_json": b64}]}, out)
        self.assertEqual(out.read_bytes(), b"x" * 2048)
        self.assertEqual(item["b64_json"], b64)

    def test_save_image_small_file_exits(self):
        import tempfile
        out = Path(tempfile.mkdtemp()) / "o.png"
        b64 = base64.b64encode(b"tiny").decode()
        with self.assertRaises(SystemExit):
            agnes.save_image({"data": [{"b64_json": b64}]}, out)
        self.assertFalse(out.exists())  # 异常小图必须清理，不留半成品

    def test_save_image_url_branch_downloads(self):
        import tempfile
        out = Path(tempfile.mkdtemp()) / "o.png"
        with mock.patch.object(agnes, "_download",
                               lambda url, p: p.write_bytes(b"x" * 2048)):
            agnes.save_image({"data": [{"url": "http://img/x"}]}, out)
        self.assertTrue(out.exists())


class TestKeyHygiene(unittest.TestCase):
    def test_curl_masks_key(self):
        s = agnes.to_curl({"extra_body": {}}, "agn-secret-123456")
        self.assertIn("agn-secr***", s)
        self.assertNotIn("et-123456", s)

    def test_curl_truncates_base64_ref(self):
        body = {"extra_body": {"image": ["data:image/png;base64," + "A" * 500]}}
        s = agnes.to_curl(body, "agn-secret-123456")
        self.assertIn("truncated", s)
        self.assertNotIn("A" * 100, s)


class TestCliSmoke(unittest.TestCase):
    """② CLI 冒烟：--help / dry-run（全程离线）。"""

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
        self.assertIn("t2i", r.stdout)
        self.assertIn("ti2i", r.stdout)

    def test_dry_run_without_key_exits(self):
        r = self._run("t2i", "-i", "x", "--dry-run")
        self.assertEqual(r.returncode, 1)
        self.assertIn("AGNES_API_KEY", r.stderr)

    def test_dry_run_with_key_ok(self):
        key = "agn-test-key-12345"
        r = self._run("t2i", "-i", "x", "--dry-run", env_extra={"AGNES_API_KEY": key})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("[CMD]", r.stderr)
        self.assertNotIn(key, r.stderr)  # key 不落日志

    def test_invalid_mode_rejected(self):
        r = self._run("t2v", "-i", "x")
        self.assertNotEqual(r.returncode, 0)

    def test_count_out_of_range_rejected(self):
        r = self._run("t2i", "-i", "x", "--count", "9",
                      env_extra={"AGNES_API_KEY": "agn-test"})
        self.assertNotEqual(r.returncode, 0)

    def test_ti2i_dry_run_missing_input_exits(self):
        # build_body 在 dry-run 判定之前执行，引用图缺失必须显性报错
        r = self._run("ti2i", "-i", "x", "--dry-run",
                      env_extra={"AGNES_API_KEY": "agn-test"})
        self.assertEqual(r.returncode, 1)
        self.assertIn("ti2i", r.stderr)


if __name__ == "__main__":
    unittest.main()
