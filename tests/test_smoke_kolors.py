#!/usr/bin/env python3
"""kolors.py 冒烟测试（离线）——Kolors 仅 t2i 的硬约束 + 请求组装。

与 scripts/test_kolors.py 互补：冒烟级钉死 mode 强制 t2i（图生图入口必须不可达）、
image_size 可选语义、key 截断、CLI dry-run。
跑法：python3 -m pytest tests -q
"""
import base64
import os
import subprocess
import sys
import unittest
import unittest.mock
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import kolors  # noqa: E402

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "kolors.py"


def _ns(**kw):
    base = dict(instruction="一只宇航员", aspect=None, image_size=None,
                output_dir=None, count=1, dry_run=False)
    base.update(kw)
    return SimpleNamespace(**base)


class TestT2iOnly(unittest.TestCase):
    """Kolors 模型不支持图生图——mode choices=["t2i"]，入口直接拒绝。"""

    def test_mode_choices_locked(self):
        with mock_argv(["kolors.py", "ti2i", "-i", "x"]):
            with self.assertRaises(SystemExit):
                kolors.parse_args()

    def test_image_size_not_in_body_semantics(self):
        body = kolors.build_body(_ns())
        self.assertEqual(body, {"model": kolors.MODEL, "prompt": "一只宇航员"})
        self.assertNotIn("image_size", body)


class TestRequestAssembly(unittest.TestCase):
    def test_aspect_preset(self):
        self.assertEqual(kolors.resolve_image_size(_ns(aspect="9:16")), "720x1280")
        self.assertEqual(kolors.resolve_image_size(_ns(aspect="16:9")), "1280x720")

    def test_aspect_overrides_custom(self):
        body = kolors.build_body(_ns(aspect="1:1", image_size="999x999"))
        self.assertEqual(body["image_size"], "1024x1024")

    def test_custom_image_size_passthrough(self):
        body = kolors.build_body(_ns(image_size="1328x1328"))
        self.assertEqual(body["image_size"], "1328x1328")

    def test_all_presets_are_wxh_strings(self):
        for k, v in kolors.IMAGE_SIZES.items():
            self.assertRegex(v, r"^\d+x\d+$", k)


class TestResponseHandling(unittest.TestCase):
    def test_no_data_exits(self):
        with self.assertRaises(SystemExit):
            kolors.save_image({"data": []}, Path("/tmp/never.png"))

    def test_no_url_and_no_b64_exits(self):
        with self.assertRaises(SystemExit):
            kolors.save_image({"data": [{}]}, Path("/tmp/never.png"))

    def test_b64_branch_writes(self):
        import tempfile
        out = Path(tempfile.mkdtemp()) / "o.png"
        b64 = base64.b64encode(b"x" * 2048).decode()
        kolors.save_image({"data": [{"b64_json": b64}]}, out)
        self.assertEqual(out.read_bytes(), b"x" * 2048)

    def test_small_image_exits_and_cleans(self):
        import tempfile
        out = Path(tempfile.mkdtemp()) / "o.png"
        b64 = base64.b64encode(b"tiny").decode()
        with self.assertRaises(SystemExit):
            kolors.save_image({"data": [{"b64_json": b64}]}, out)
        self.assertFalse(out.exists())

    def test_url_branch_downloads(self):
        import tempfile
        out = Path(tempfile.mkdtemp()) / "o.png"
        with unittest.mock.patch.object(kolors, "_download",
                                        lambda url, p: p.write_bytes(b"x" * 2048)):
            kolors.save_image({"data": [{"url": "http://cdn/x"}]}, out)
        self.assertTrue(out.exists())


class TestKeyHygiene(unittest.TestCase):
    def test_curl_masks_key(self):
        s = kolors.to_curl({"model": "Kolors"}, "QC-secret-123456")
        self.assertIn("QC-secre***", s)
        self.assertNotIn("t-123456", s)


class TestCliSmoke(unittest.TestCase):
    def _run(self, *args, env_extra=None):
        env = dict(os.environ)
        env.pop("AIPING_API_KEY", None)
        env.update(env_extra or {})
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            capture_output=True, text=True, timeout=60, env=env,
        )

    def test_help(self):
        r = self._run("--help")
        self.assertEqual(r.returncode, 0)
        self.assertIn("t2i", r.stdout)
        self.assertIn("Kolors 不支持图生图", r.stdout)

    def test_dry_run_without_key_exits(self):
        r = self._run("t2i", "-i", "x", "--dry-run")
        self.assertEqual(r.returncode, 1)
        self.assertIn("AIPING_API_KEY", r.stderr)

    def test_dry_run_with_key_ok(self):
        r = self._run("t2i", "-i", "x", "--dry-run",
                      env_extra={"AIPING_API_KEY": "QC-test-key-12345"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("[CMD]", r.stderr)

    def test_count_out_of_range_rejected(self):
        r = self._run("t2i", "-i", "x", "--count", "0",
                      env_extra={"AIPING_API_KEY": "QC-test-key-12345"})
        self.assertNotEqual(r.returncode, 0)


class mock_argv:
    """临时替换 sys.argv 的上下文（unittest 无 pytest monkeypatch）。"""

    def __init__(self, argv):
        self.argv = argv

    def __enter__(self):
        self._old = sys.argv
        sys.argv = self.argv
        return self

    def __exit__(self, *a):
        sys.argv = self._old
        return False


if __name__ == "__main__":
    unittest.main()
