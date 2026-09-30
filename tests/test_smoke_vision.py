#!/usr/bin/env python3
"""vision.py 冒烟测试（离线）——双 provider 路由 + 图片输入解析 + 响应提取。

与 scripts/test_vision.py 互补：冒烟级钉死 provider 查找表、URL 透传 vs 本地
base64、20MB 上限、content 提取、CLI dry-run。
跑法：python3 -m pytest tests -q
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import vision  # noqa: E402

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "vision.py"


class TestProviderRouting(unittest.TestCase):
    """规则5：provider 路由是确定性查找表，不是模型判断。"""

    def test_two_providers(self):
        self.assertEqual(set(vision.PROVIDERS), {"agnes", "aiping"})

    def test_each_provider_complete(self):
        for name, cfg in vision.PROVIDERS.items():
            self.assertTrue(cfg["endpoint"].startswith("https://"), name)
            self.assertTrue(cfg["model"], name)
            self.assertTrue(cfg["key_env"].endswith("_API_KEY"), name)

    def test_build_body_content_array(self):
        body = vision.build_body("aiping", "https://e.com/a.jpg", "这道题怎么解", 512)
        self.assertEqual(body["model"], vision.PROVIDERS["aiping"]["model"])
        self.assertEqual(body["max_tokens"], 512)
        parts = body["messages"][0]["content"]
        self.assertEqual(parts[0]["type"], "image_url")
        self.assertEqual(parts[0]["image_url"]["url"], "https://e.com/a.jpg")
        self.assertEqual(parts[1]["type"], "text")
        self.assertEqual(parts[1]["text"], "这道题怎么解")


class TestImageInput(unittest.TestCase):
    def test_url_passthrough(self):
        self.assertEqual(vision.resolve_image_input("https://x.com/a.jpg"),
                         "https://x.com/a.jpg")

    def test_local_png_becomes_data_uri(self):
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(b"\x89PNG\r\n\x1a\n")
            p = f.name
        try:
            uri = vision.image_to_data_uri(p)
            self.assertTrue(uri.startswith("data:image/png;base64,"))
            self.assertEqual(vision.resolve_image_input(p), uri)
        finally:
            Path(p).unlink()

    def test_missing_file_exits(self):
        with self.assertRaises(SystemExit):
            vision.image_to_data_uri("/no/such/file.png")

    def test_unsupported_format_exits(self):
        with tempfile.NamedTemporaryFile(suffix=".bmp", delete=False) as f:
            f.write(b"BM")
            p = f.name
        try:
            with self.assertRaises(SystemExit):
                vision.image_to_data_uri(p)
        finally:
            Path(p).unlink()

    def test_oversize_image_exits(self):
        # >20MB 请求体会撑爆 base64；稀疏文件即可触发 size 检查（先于 read）
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.truncate(21 * 1024 * 1024)
            p = f.name
        try:
            with self.assertRaises(SystemExit) as cm:
                vision.image_to_data_uri(p)
            self.assertIn("20MB", str(cm.exception))
        finally:
            Path(p).unlink()


class TestContentExtraction(unittest.TestCase):
    def test_ok(self):
        resp = {"choices": [{"message": {"content": "图里有一只猫"}}]}
        self.assertEqual(vision.extract_content(resp), "图里有一只猫")

    def test_no_choices_exits(self):
        with self.assertRaises(SystemExit):
            vision.extract_content({})

    def test_empty_content_exits(self):
        with self.assertRaises(SystemExit):
            vision.extract_content({"choices": [{"message": {"content": ""}}]})

    def test_null_message_exits(self):
        with self.assertRaises(SystemExit):
            vision.extract_content({"choices": [{}]})


class TestKeyHygiene(unittest.TestCase):
    def test_curl_masks_key_and_truncates_data_uri(self):
        body = vision.build_body("agnes", "data:image/png;base64," + "A" * 500, "q", 16)
        s = vision.to_curl("agnes", body, "agn-secret-123456")
        self.assertIn("agn-secr***", s)
        self.assertNotIn("et-123456", s)
        self.assertIn("truncated", s)
        # 深拷贝：入参 body 不得被截断污染
        self.assertIn("A" * 100, body["messages"][0]["content"][0]["image_url"]["url"])


class TestCliSmoke(unittest.TestCase):
    def _run(self, *args, env_extra=None):
        env = dict(os.environ)
        env.pop("AGNES_API_KEY", None)
        env.pop("AIPING_API_KEY", None)
        env.update(env_extra or {})
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            capture_output=True, text=True, timeout=60, env=env,
        )

    def test_help(self):
        r = self._run("--help")
        self.assertEqual(r.returncode, 0)
        self.assertIn("agnes", r.stdout)
        self.assertIn("aiping", r.stdout)

    def test_invalid_provider_rejected(self):
        r = self._run("gpt4v", "--image", "https://e.com/a.jpg", "-q", "x")
        self.assertNotEqual(r.returncode, 0)

    def test_dry_run_without_key_exits(self):
        r = self._run("agnes", "--image", "https://e.com/a.jpg", "-q", "x", "--dry-run")
        self.assertEqual(r.returncode, 1)
        self.assertIn("AGNES_API_KEY", r.stderr)

    def test_dry_run_with_key_ok(self):
        r = self._run("agnes", "--image", "https://e.com/a.jpg", "-q", "x", "--dry-run",
                      env_extra={"AGNES_API_KEY": "agn-test-key-12345"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("[CMD]", r.stderr)


if __name__ == "__main__":
    unittest.main()
