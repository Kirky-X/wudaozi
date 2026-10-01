#!/usr/bin/env python3
"""wudaozi _cloud_common.py 单元测试 —— 共享传输骨架的行为契约（不打真实 API）。

覆盖：post_json_raw（CloudHTTPError 分流）/ post_json（错误出口+提示表）/
download_to_file / extract_media / assert_public_url / parse_host_ip / ERROR_HINTS 完整性。
跑法：python3 -m pytest scripts/test_cloud_common.py -v
"""
# ponytail: 骨架是四个云脚本共用地基，契约必须钉死——这里坏了四处一起坏。

import io
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import _cloud_common as cc  # noqa: E402


class _FakeResp:
    def __init__(self, payload: bytes):
        self._p = payload

    def read(self):
        return self._p

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _http_error(code: int, body: bytes = b'{"error":"x"}', headers=None):
    return urllib.error.HTTPError("http://x", code, "err", headers or {}, io.BytesIO(body))


# ---------- post_json_raw ----------
class TestPostJsonRaw:
    def test_ok_returns_dict(self, monkeypatch):
        payload = json.dumps({"data": [{"url": "http://img"}]}).encode()
        monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout: _FakeResp(payload))
        r = cc.post_json_raw("https://x", {"a": 1}, "k", 30)
        assert r == {"data": [{"url": "http://img"}]}

    def test_http_error_raises_cloud_http_error(self, monkeypatch):
        def raise_401(req, timeout):
            raise _http_error(401, b'{"message":"bad key"}')

        monkeypatch.setattr(urllib.request, "urlopen", raise_401)
        with pytest.raises(cc.CloudHTTPError) as e:
            cc.post_json_raw("https://x", {}, "k", 30)
        assert e.value.status == 401
        assert "bad key" in e.value.raw

    def test_urlerror_propagates(self, monkeypatch):
        def raise_url(req, timeout):
            raise urllib.error.URLError("dns fail")

        monkeypatch.setattr(urllib.request, "urlopen", raise_url)
        with pytest.raises(urllib.error.URLError):
            cc.post_json_raw("https://x", {}, "k", 30)

    def test_timeout_propagates(self, monkeypatch):
        def raise_to(req, timeout):
            raise TimeoutError()

        monkeypatch.setattr(urllib.request, "urlopen", raise_to)
        with pytest.raises(TimeoutError):
            cc.post_json_raw("https://x", {}, "k", 30)

    def test_request_carries_auth_header(self, monkeypatch):
        seen = {}

        def fake_urlopen(req, timeout):
            seen["headers"] = dict(req.header_items())
            seen["url"] = req.full_url
            return _FakeResp(b"{}")

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        cc.post_json_raw("https://x/v1", {}, "agn-secret", 30)
        auth = seen["headers"].get("Authorization") or seen["headers"].get("authorization")
        assert auth == "Bearer agn-secret"
        assert seen["url"] == "https://x/v1"


# ---------- post_json 错误出口 ----------
class TestPostJson:
    def test_http_error_exits_with_hint(self, monkeypatch):
        def raise_401(req, timeout):
            raise _http_error(401)

        monkeypatch.setattr(urllib.request, "urlopen", raise_401)
        with pytest.raises(SystemExit) as e:
            cc.post_json("https://x", {}, "k", 30, label="agnes")
        assert "401" in str(e.value)
        assert "AGNES_API_KEY" in str(e.value)

    def test_hint_key_overrides_label_for_hints(self, monkeypatch):
        def raise_401(req, timeout):
            raise _http_error(401)

        monkeypatch.setattr(urllib.request, "urlopen", raise_401)
        with pytest.raises(SystemExit) as e:
            cc.post_json("https://x", {}, "k", 30, label="agnes", hint_key="aiping-vlm")
        # 消息首行是稳定错误码 + label 前缀，提示按 hint_key 查表
        assert "code=auth_error agnes HTTP 401" in str(e.value)
        assert "AIPING_API_KEY" in str(e.value)

    def test_unknown_status_gets_empty_hint(self, monkeypatch):
        def raise_503(req, timeout):
            raise _http_error(503)

        monkeypatch.setattr(urllib.request, "urlopen", raise_503)
        with pytest.raises(SystemExit) as e:
            cc.post_json("https://x", {}, "k", 30, label="agnes")
        assert "503" in str(e.value)


# ---------- download_to_file ----------
class TestDownloadToFile:
    def test_writes_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            urllib.request, "urlopen", lambda url, timeout: _FakeResp(b"image-bytes")
        )
        out = tmp_path / "o.png"
        cc.download_to_file("http://img/x", out, 30, "agnes")
        assert out.read_bytes() == b"image-bytes"

    def test_failure_removes_partial_and_exits(self, tmp_path, monkeypatch):
        def raise_url(url, timeout):
            raise urllib.error.URLError("reset")

        monkeypatch.setattr(urllib.request, "urlopen", raise_url)
        out = tmp_path / "o.png"
        out.write_bytes(b"partial")  # 模拟上次残留
        with pytest.raises(SystemExit):
            cc.download_to_file("http://img/x", out, 30, "agnes")
        assert not out.exists()


# ---------- extract_media ----------
class TestExtractMedia:
    def test_url_branch(self, tmp_path):
        out = tmp_path / "o.png"
        item = cc.extract_media(
            {"data": [{"url": "http://img"}]}, out, "agnes", 1024,
            download=lambda u, p: p.write_bytes(b"x" * 2048),
        )
        assert item == {"url": "http://img"}
        assert out.stat().st_size == 2048

    def test_b64_branch(self, tmp_path):
        import base64

        out = tmp_path / "o.png"
        b64 = base64.b64encode(b"y" * 2048).decode()
        cc.extract_media({"data": [{"b64_json": b64}]}, out, "kolors", 1024)
        assert out.read_bytes() == b"y" * 2048

    def test_no_data_exits(self, tmp_path):
        with pytest.raises(SystemExit):
            cc.extract_media({"data": []}, tmp_path / "o.png", "agnes", 1024)
        with pytest.raises(SystemExit):
            cc.extract_media("not-a-dict", tmp_path / "o.png", "agnes", 1024)

    def test_non_dict_item_exits(self, tmp_path):
        with pytest.raises(SystemExit):
            cc.extract_media({"data": ["str-item"]}, tmp_path / "o.png", "agnes", 1024)

    def test_missing_url_and_b64_exits(self, tmp_path):
        with pytest.raises(SystemExit):
            cc.extract_media({"data": [{}]}, tmp_path / "o.png", "kolors", 1024)

    def test_undersized_artifact_exits_and_cleans(self, tmp_path):
        out = tmp_path / "o.png"
        with pytest.raises(SystemExit):
            cc.extract_media(
                {"data": [{"url": "http://img"}]}, out, "agnes", 1024,
                download=lambda u, p: p.write_bytes(b"tiny"),
            )
        assert not out.exists()

    def test_revised_prompt_printed_to_stderr(self, tmp_path, capsys):
        cc.extract_media(
            {"data": [{"url": "http://img", "revised_prompt": "better"}]}, tmp_path / "o.png",
            "agnes", 1024, download=lambda u, p: p.write_bytes(b"x" * 2048),
        )
        assert "revised_prompt" in capsys.readouterr().err


# ---------- assert_public_url / parse_host_ip ----------
class TestAssertPublicUrl:
    def test_public_ok(self):
        cc.assert_public_url("https://example.com/a.png")  # 不抛
        cc.assert_public_url("http://cdn.agnes-ai.com/x.jpg")

    def test_non_http_exits(self):
        with pytest.raises(SystemExit):
            cc.assert_public_url("file:///etc/passwd")
        with pytest.raises(SystemExit):
            cc.assert_public_url("/local/a.png")

    def test_private_and_metadata_exits(self):
        for u in [
            "http://localhost/a.png",
            "http://127.0.0.1/a.png",
            "http://169.254.169.254/latest/meta-data/",
            "http://10.0.0.1/a.png",
            "http://192.168.1.1/a.png",
            "http://172.16.0.1/a.png",
            "http://2852039166/a.png",   # 十进制 = 169.254.169.254
            "http://0xA9FEA9FE/a.png",   # 十六进制
            "http://0251.0376.0251.0376/a.png",  # 八进制
        ]:
            with pytest.raises(SystemExit):
                cc.assert_public_url(u)


class TestParseHostIp:
    def test_standard_ip(self):
        import ipaddress

        assert cc.parse_host_ip("10.0.0.1") == ipaddress.ip_address("10.0.0.1")

    def test_decimal_ip_via_inet_aton(self):
        import ipaddress

        assert cc.parse_host_ip("2852039166") == ipaddress.ip_address("169.254.169.254")

    def test_domain_returns_none(self):
        assert cc.parse_host_ip("example.com") is None


# ---------- 稳定错误码（调研建议#9：消费者是 agent，错误必须机器可读） ----------
class TestStableErrorCodes:
    def test_code_set_pinned(self):
        # 钉死全集：新增 code 必须显式改这里（防止悄悄漂移，comfy 同款做法）
        assert set(cc.CODES) == {
            "auth_error", "rate_limited", "invalid_param", "no_task",
            "empty_result", "abnormal_artifact", "network_error", "timeout",
            "malformed_response", "server_error", "generation_failed",
        }

    def test_http_error_first_line_carries_code(self, monkeypatch):
        def raise_401(req, timeout):
            raise _http_error(401)

        monkeypatch.setattr(urllib.request, "urlopen", raise_401)
        with pytest.raises(SystemExit) as e:
            cc.post_json("https://x", {}, "k", 30, label="agnes")
        assert str(e.value).startswith("[ERROR] code=auth_error ")

    def test_http_5xx_code_server_error(self, monkeypatch):
        def raise_500(req, timeout):
            raise _http_error(500)

        monkeypatch.setattr(urllib.request, "urlopen", raise_500)
        with pytest.raises(SystemExit) as e:
            cc.post_json("https://x", {}, "k", 30, label="kolors")
        assert "code=server_error" in str(e.value)

    def test_urlerror_code_network_error(self, monkeypatch):
        def raise_url(req, timeout):
            raise urllib.error.URLError("dns fail")

        monkeypatch.setattr(urllib.request, "urlopen", raise_url)
        with pytest.raises(SystemExit) as e:
            cc.post_json("https://x", {}, "k", 30, label="agnes")
        assert "code=network_error" in str(e.value)

    def test_timeout_code(self, monkeypatch):
        def raise_to(req, timeout):
            raise TimeoutError()

        monkeypatch.setattr(urllib.request, "urlopen", raise_to)
        with pytest.raises(SystemExit) as e:
            cc.post_json("https://x", {}, "k", 30, label="agnes")
        assert "code=timeout" in str(e.value)

    def test_download_failure_code(self, tmp_path, monkeypatch):
        def raise_url(url, timeout):
            raise urllib.error.URLError("reset")

        monkeypatch.setattr(urllib.request, "urlopen", raise_url)
        with pytest.raises(SystemExit) as e:
            cc.download_to_file("http://img/x", tmp_path / "o.png", 30, "agnes")
        assert "code=network_error" in str(e.value)

    def test_empty_result_attributed_to_content_filter(self, tmp_path):
        # 空 data + HTTP 200：最可能是内容过滤（国内 provider 审核严），归因必须显式
        with pytest.raises(SystemExit) as e:
            cc.extract_media({"data": []}, tmp_path / "o.png", "agnes", 1024)
        assert "code=empty_result" in str(e.value)
        assert "内容过滤" in str(e.value)

    def test_malformed_structure_code(self, tmp_path):
        with pytest.raises(SystemExit) as e:
            cc.extract_media({"data": [{}]}, tmp_path / "o.png", "kolors", 1024)
        assert "code=malformed_response" in str(e.value)

    def test_undersized_artifact_code(self, tmp_path):
        with pytest.raises(SystemExit) as e:
            cc.extract_media(
                {"data": [{"url": "http://img"}]}, tmp_path / "o.png", "agnes", 1024,
                download=lambda u, p: p.write_bytes(b"tiny"),
            )
        assert "code=abnormal_artifact" in str(e.value)


# ---------- ERROR_HINTS 完整性 ----------
class TestErrorHints:
    def test_covers_all_label_status_combos(self):
        labels = ["agnes", "kolors", "video", "agnes-vlm", "aiping-vlm"]
        for label in labels:
            for status in (401, 429, 400):
                assert (label, status) in cc.ERROR_HINTS, (label, status)

    def test_all_hints_actionable(self):
        for key, hint in cc.ERROR_HINTS.items():
            assert hint.strip().startswith("→"), key
