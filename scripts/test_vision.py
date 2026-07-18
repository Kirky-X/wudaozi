#!/usr/bin/env python3
"""wudaozi vision.py 单元测试 —— 验证纯函数与错误分流（不打真实 API）。

覆盖：image_to_data_uri / resolve_image_input / build_body /
call_api（mock urlopen）/ extract_content / to_curl / PROVIDERS 一致性。
跑法：python3 -m pytest scripts/test_vision.py -v
"""
# ponytail: 只测决定正确性的纯函数 + mock 网络层；不打真实 API。
# 关键钉死：双 provider 路由、URL 透传 vs 本地 base64、key 截断、base64 图片截断。

import io
import json
import sys
import urllib.error
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import vision  # noqa: E402


# ---------- image_to_data_uri ----------
class TestImageToDataUri:
    def test_png(self, tmp_path):
        p = tmp_path / "x.png"
        p.write_bytes(b"\x89PNG\r\n\x1a\n")
        uri = vision.image_to_data_uri(str(p))
        assert uri.startswith("data:image/png;base64,")

    def test_jpeg(self, tmp_path):
        p = tmp_path / "x.jpg"
        p.write_bytes(b"\xff\xd8\xff")
        assert vision.image_to_data_uri(str(p)).startswith("data:image/jpeg;base64,")

    def test_unsupported_ext_exits(self, tmp_path):
        p = tmp_path / "x.bmp"
        p.write_bytes(b"BM")
        with pytest.raises(SystemExit):
            vision.image_to_data_uri(str(p))

    def test_missing_file_exits(self):
        with pytest.raises(SystemExit):
            vision.image_to_data_uri("/no/such/file.png")


# ---------- resolve_image_input ----------
class TestResolveImageInput:
    def test_http_url_passthrough(self):
        assert vision.resolve_image_input("http://x.com/a.jpg") == "http://x.com/a.jpg"
        assert (
            vision.resolve_image_input("https://x.com/a.jpg") == "https://x.com/a.jpg"
        )

    def test_local_to_data_uri(self, tmp_path):
        p = tmp_path / "x.png"
        p.write_bytes(b"\x89PNG")
        uri = vision.resolve_image_input(str(p))
        assert uri.startswith("data:image/png;base64,")


# ---------- build_body ----------
class TestBuildBody:
    def test_agnes_body(self):
        body = vision.build_body("agnes", "https://x/a.jpg", "看图", 1024)
        assert body["model"] == "agnes-2.0-flash"
        assert body["max_tokens"] == 1024
        parts = body["messages"][0]["content"]
        assert parts[0] == {"type": "image_url", "image_url": {"url": "https://x/a.jpg"}}
        assert parts[1] == {"type": "text", "text": "看图"}

    def test_aiping_body(self):
        body = vision.build_body("aiping", "data:image/png;base64,AAA", "解题", 512)
        assert body["model"] == "DeepSeek-OCR-2"
        assert body["max_tokens"] == 512
        assert (
            body["messages"][0]["content"][0]["image_url"]["url"]
            == "data:image/png;base64,AAA"
        )


# ---------- call_api（mock urlopen）----------
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


class TestCallApi:
    def test_ok_returns_dict(self, monkeypatch):
        payload = json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode()
        monkeypatch.setattr(
            vision.urllib.request,
            "urlopen",
            lambda req, timeout: _FakeResp(payload),
        )
        r = vision.call_api("agnes", {"model": "x"}, "k")
        assert r["choices"][0]["message"]["content"] == "ok"

    def test_http_401_exits(self, monkeypatch):
        monkeypatch.setattr(
            vision.urllib.request,
            "urlopen",
            lambda req, timeout: (_ for _ in ()).throw(_http_error(401)),
        )
        with pytest.raises(SystemExit) as e:
            vision.call_api("agnes", {}, "k")
        assert "401" in str(e.value)

    def test_http_400_exits(self, monkeypatch):
        monkeypatch.setattr(
            vision.urllib.request,
            "urlopen",
            lambda req, timeout: (_ for _ in ()).throw(_http_error(400)),
        )
        with pytest.raises(SystemExit) as e:
            vision.call_api("aiping", {}, "k")
        assert "400" in str(e.value)

    def test_urlerror_exits(self, monkeypatch):
        def raise_url(req, timeout):
            raise urllib.error.URLError("dns fail")

        monkeypatch.setattr(vision.urllib.request, "urlopen", raise_url)
        with pytest.raises(SystemExit):
            vision.call_api("agnes", {}, "k")

    def test_timeout_exits(self, monkeypatch):
        def raise_to(req, timeout):
            raise TimeoutError()

        monkeypatch.setattr(vision.urllib.request, "urlopen", raise_to)
        with pytest.raises(SystemExit):
            vision.call_api("aiping", {}, "k")


# ---------- extract_content ----------
class TestExtractContent:
    def test_normal(self):
        r = {"choices": [{"message": {"content": "这是一只猫"}}]}
        assert vision.extract_content(r) == "这是一只猫"

    def test_no_choices_exits(self):
        with pytest.raises(SystemExit):
            vision.extract_content({})

    def test_no_content_exits(self):
        with pytest.raises(SystemExit):
            vision.extract_content({"choices": [{"message": {}}]})


# ---------- to_curl ----------
class TestToCurl:
    def test_key_masked(self):
        body = vision.build_body("agnes", "https://x/a.jpg", "看图", 256)
        s = vision.to_curl("agnes", body, "agn-test1234567890")
        assert "agn-test***" in s
        assert "1234567890" not in s

    def test_base64_truncated(self):
        body = vision.build_body(
            "agnes", "data:image/png;base64," + "A" * 500, "看图", 256
        )
        s = vision.to_curl("agnes", body, "agn-test1234567890")
        assert "truncated" in s
        assert "A" * 100 not in s

    def test_url_not_truncated(self):
        # 公网 URL 不应被截断
        body = vision.build_body("agnes", "https://example.com/photo.jpg", "看图", 256)
        s = vision.to_curl("agnes", body, "agn-test1234567890")
        assert "https://example.com/photo.jpg" in s


# ---------- PROVIDERS 一致性 ----------
class TestProviders:
    def test_all_have_required_fields(self):
        for name, cfg in vision.PROVIDERS.items():
            assert cfg["endpoint"].startswith("https://"), name
            assert cfg["model"], name
            assert cfg["key_env"], name

    def test_two_providers(self):
        assert set(vision.PROVIDERS) == {"agnes", "aiping"}
        assert vision.PROVIDERS["agnes"]["model"] == "agnes-2.0-flash"
        assert vision.PROVIDERS["aiping"]["model"] == "DeepSeek-OCR-2"
