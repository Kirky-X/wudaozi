#!/usr/bin/env python3
"""wudaozi agnes.py 单元测试 —— 验证纯函数与错误分流（不打真实 API）。

覆盖：resolve_size / resolve_output / image_to_data_uri / build_body /
call_api（mock urlopen）/ save_image / to_curl / ASPECT_RATIOS 一致性。
跑法：python3 -m pytest scripts/test_agnes.py -v
"""
# ponytail: 只测决定正确性的纯函数 + mock 网络层；不打真实 API（省额度、可重复）。
# 关键钉死：size 的 WxH 方向（易写反）、key 截断防泄露、ti2i base64 转换。

import io
import json
import sys
import urllib.error
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import agnes  # noqa: E402


# ---------- resolve_size ----------
class TestResolveSize:
    def _ns(self, **kw):
        base = dict(aspect=None, height=None, width=None)
        base.update(kw)
        return SimpleNamespace(**base)

    def test_aspect_preset(self):
        assert agnes.resolve_size(self._ns(aspect="1:1")) == (1024, 1024)
        # 9:16 竖屏：H=1824 W=1024（元组 (H,W)）
        assert agnes.resolve_size(self._ns(aspect="9:16")) == (1824, 1024)
        assert agnes.resolve_size(self._ns(aspect="16:9")) == (1024, 1824)

    def test_both_hw_custom(self):
        # agnes 不做 16 对齐，原样返回
        assert agnes.resolve_size(self._ns(height=800, width=600)) == (800, 600)

    def test_default_1_1(self):
        assert agnes.resolve_size(self._ns()) == (1024, 1024)

    def test_single_height_exits(self):
        with pytest.raises(SystemExit):
            agnes.resolve_size(self._ns(height=800))


# ---------- resolve_output ----------
class TestResolveOutput:
    def test_default_dir_and_naming(self):
        out = agnes.resolve_output(
            SimpleNamespace(mode="t2i", output_dir=None), 1024, 1824
        )
        assert out.parent.name == "agnes-output"
        # 文件名含 mode + WxH（注意是 WxH 不是 HxW）
        assert out.name.startswith("agnes_t2i_1824x1024_")

    def test_custom_dir(self, tmp_path):
        out = agnes.resolve_output(
            SimpleNamespace(mode="ti2i", output_dir=str(tmp_path)), 1360, 1024
        )
        assert out.parent == tmp_path
        assert out.name.startswith("agnes_ti2i_1024x1360_")


# ---------- image_to_data_uri ----------
class TestImageToDataUri:
    def test_png(self, tmp_path):
        p = tmp_path / "x.png"
        p.write_bytes(b"\x89PNG\r\n\x1a\n")
        uri = agnes.image_to_data_uri(str(p))
        assert uri.startswith("data:image/png;base64,")

    def test_unsupported_ext_exits(self, tmp_path):
        p = tmp_path / "x.bmp"
        p.write_bytes(b"BM")
        with pytest.raises(SystemExit):
            agnes.image_to_data_uri(str(p))

    def test_missing_file_exits(self):
        with pytest.raises(SystemExit):
            agnes.image_to_data_uri("/no/such/file.png")


# ---------- build_body ----------
def _body_ns(**kw):
    base = dict(mode="t2i", instruction="测试 prompt", input=None, base64=False)
    base.update(kw)
    return SimpleNamespace(**base)


class TestBuildBody:
    def test_t2i_url_format(self):
        # ⚠️ 钉死 size 是 WxH 字符串方向：aspect 9:16 → (H=1824,W=1024) → size="1024x1824"
        body = agnes.build_body(_body_ns(), 1824, 1024)
        assert body["size"] == "1024x1824"
        assert body["model"] == agnes.MODEL
        assert body["prompt"] == "测试 prompt"
        assert body["extra_body"] == {"response_format": "url"}
        assert "return_base64" not in body
        assert "image" not in body["extra_body"]

    def test_t2i_base64_flag(self):
        body = agnes.build_body(_body_ns(base64=True), 1024, 1024)
        assert body["return_base64"] is True
        assert body["extra_body"] == {}

    def test_ti2i_with_local_input(self, tmp_path):
        p = tmp_path / "ref.png"
        p.write_bytes(b"\x89PNG")
        body = agnes.build_body(
            _body_ns(mode="ti2i", input=str(p)), 1024, 1024
        )
        ref = body["extra_body"]["image"][0]
        assert ref.startswith("data:image/png;base64,")

    def test_ti2i_with_remote_url(self):
        body = agnes.build_body(
            _body_ns(mode="ti2i", input="https://example.com/a.jpg"), 1024, 1024
        )
        # 远程 URL 直接透传，不转 base64
        assert body["extra_body"]["image"] == ["https://example.com/a.jpg"]

    def test_ti2i_missing_input_exits(self):
        with pytest.raises(SystemExit):
            agnes.build_body(_body_ns(mode="ti2i", input=None), 1024, 1024)


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
    return urllib.error.HTTPError(
        "http://x", code, "err", {}, io.BytesIO(body)
    )


class TestCallApi:
    def test_ok_returns_dict(self, monkeypatch):
        payload = json.dumps({"data": [{"url": "http://img"}]}).encode()
        monkeypatch.setattr(
            agnes.urllib.request,
            "urlopen",
            lambda req, timeout: _FakeResp(payload),
        )
        assert agnes.call_api({"model": "x"}, "k") == {"data": [{"url": "http://img"}]}

    def test_http_401_exits(self, monkeypatch):
        def raise_401(req, timeout):
            raise _http_error(401)

        monkeypatch.setattr(agnes.urllib.request, "urlopen", raise_401)
        with pytest.raises(SystemExit) as e:
            agnes.call_api({}, "k")
        assert "401" in str(e.value)

    def test_http_429_exits(self, monkeypatch):
        def raise_429(req, timeout):
            raise _http_error(429)

        monkeypatch.setattr(agnes.urllib.request, "urlopen", raise_429)
        with pytest.raises(SystemExit) as e:
            agnes.call_api({}, "k")
        assert "429" in str(e.value)

    def test_urlerror_exits(self, monkeypatch):
        def raise_url(req, timeout):
            raise urllib.error.URLError("dns fail")

        monkeypatch.setattr(agnes.urllib.request, "urlopen", raise_url)
        with pytest.raises(SystemExit):
            agnes.call_api({}, "k")

    def test_timeout_exits(self, monkeypatch):
        def raise_to(req, timeout):
            raise TimeoutError()

        monkeypatch.setattr(agnes.urllib.request, "urlopen", raise_to)
        with pytest.raises(SystemExit):
            agnes.call_api({}, "k")


# ---------- save_image ----------
class TestSaveImage:
    def test_url_branch_downloads(self, tmp_path, monkeypatch):
        called = {}

        def fake_download(url, out_path):
            called["url"] = url
            out_path.write_bytes(b"x" * 2048)  # >1KB 通过校验

        monkeypatch.setattr(agnes, "_download", fake_download)
        out = tmp_path / "o.png"
        agnes.save_image({"data": [{"url": "http://img"}]}, out)
        assert called["url"] == "http://img"
        assert out.exists()

    def test_b64_branch_writes_file(self, tmp_path):
        import base64

        b64 = base64.b64encode(b"x" * 2048).decode()
        out = tmp_path / "o.png"
        agnes.save_image({"data": [{"b64_json": b64}]}, out)
        assert out.read_bytes() == b"x" * 2048

    def test_no_data_exits(self, tmp_path):
        with pytest.raises(SystemExit):
            agnes.save_image({"data": []}, tmp_path / "o.png")
        with pytest.raises(SystemExit):
            agnes.save_image({}, tmp_path / "o.png")


# ---------- to_curl ----------
class TestToCurl:
    def test_key_masked(self):
        body = {"model": "x", "prompt": "p", "size": "1024x1024", "extra_body": {}}
        s = agnes.to_curl(body, "agn-test1234567890")
        # 只显示前 8 字符 + ***，完整 key 不得出现
        assert "agn-test***" in s
        assert "1234567890" not in s

    def test_base64_truncated(self):
        body = {
            "extra_body": {"image": ["data:image/png;base64," + "A" * 500]},
        }
        s = agnes.to_curl(body, "agn-test1234567890")
        assert "truncated" in s
        # 500 个 A 不得完整出现
        assert "A" * 100 not in s


# ---------- ASPECT_RATIOS 一致性 ----------
class TestAspectRatios:
    def test_all_int_pairs(self):
        for k, (h, w) in agnes.ASPECT_RATIOS.items():
            assert isinstance(h, int) and isinstance(w, int), k

    def test_portrait_landscape_direction(self):
        # 竖屏 H>W，横屏 W>H（修正后必须成立）
        assert agnes.ASPECT_RATIOS["9:16"][0] > agnes.ASPECT_RATIOS["9:16"][1]
        assert agnes.ASPECT_RATIOS["16:9"][1] > agnes.ASPECT_RATIOS["16:9"][0]
        assert agnes.ASPECT_RATIOS["3:4"][0] > agnes.ASPECT_RATIOS["3:4"][1]
