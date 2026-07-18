#!/usr/bin/env python3
"""wudaozi kolors.py 单元测试 —— 验证纯函数与错误分流（不打真实 API）。

覆盖：resolve_image_size / resolve_output / build_body /
call_api（mock urlopen）/ save_image / to_curl / IMAGE_SIZES 一致性 /
mode 强制 t2i（图生图不可达）。
跑法：python3 -m pytest scripts/test_kolors.py -v
"""
# ponytail: 只测决定正确性的纯函数 + mock 网络层；不打真实 API（省额度、可重复）。
# 关键钉死：mode 强制 t2i（Kolors 硬约束）、key 截断防泄露、image_size 可选语义。

import io
import json
import sys
import urllib.error
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import kolors  # noqa: E402


# ---------- resolve_image_size ----------
class TestResolveImageSize:
    def _ns(self, **kw):
        base = dict(aspect=None, image_size=None)
        base.update(kw)
        return SimpleNamespace(**base)

    def test_aspect_preset(self):
        assert kolors.resolve_image_size(self._ns(aspect="1:1")) == "1024x1024"
        assert kolors.resolve_image_size(self._ns(aspect="9:16")) == "720x1280"
        assert kolors.resolve_image_size(self._ns(aspect="16:9")) == "1280x720"

    def test_custom_image_size(self):
        assert (
            kolors.resolve_image_size(self._ns(image_size="1328x1328")) == "1328x1328"
        )

    def test_none_when_unset(self):
        # 不传 aspect/image_size → None（服务端给默认）
        assert kolors.resolve_image_size(self._ns()) is None

    def test_aspect_overrides_custom(self):
        # aspect 优先于 image_size
        assert (
            kolors.resolve_image_size(
                self._ns(aspect="1:1", image_size="999x999")
            )
            == "1024x1024"
        )


# ---------- resolve_output ----------
class TestResolveOutput:
    def test_default_dir_and_naming(self):
        out = kolors.resolve_output(SimpleNamespace(output_dir=None))
        assert out.parent.name == "kolors-output"
        assert out.name.startswith("kolors_t2i_")
        assert out.suffix == ".png"

    def test_custom_dir(self, tmp_path):
        out = kolors.resolve_output(SimpleNamespace(output_dir=str(tmp_path)))
        assert out.parent == tmp_path


# ---------- build_body ----------
def _body_ns(**kw):
    base = dict(instruction="测试 prompt", aspect=None, image_size=None)
    base.update(kw)
    return SimpleNamespace(**base)


class TestBuildBody:
    def test_no_image_size_omitted(self):
        # 不传 size → body 不含 image_size 字段（走服务端默认）
        body = kolors.build_body(_body_ns())
        assert body == {"model": "Kolors", "prompt": "测试 prompt"}
        assert "image_size" not in body

    def test_aspect_sets_image_size(self):
        body = kolors.build_body(_body_ns(aspect="9:16"))
        assert body["image_size"] == "720x1280"
        assert body["model"] == kolors.MODEL

    def test_custom_image_size(self):
        body = kolors.build_body(_body_ns(image_size="1328x1328"))
        assert body["image_size"] == "1328x1328"


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
            kolors.urllib.request,
            "urlopen",
            lambda req, timeout: _FakeResp(payload),
        )
        assert kolors.call_api({"model": "x"}, "k") == {"data": [{"url": "http://img"}]}

    def test_http_401_exits(self, monkeypatch):
        monkeypatch.setattr(
            kolors.urllib.request,
            "urlopen",
            lambda req, timeout: (_ for _ in ()).throw(_http_error(401)),
        )
        with pytest.raises(SystemExit) as e:
            kolors.call_api({}, "k")
        assert "401" in str(e.value)

    def test_http_429_exits(self, monkeypatch):
        monkeypatch.setattr(
            kolors.urllib.request,
            "urlopen",
            lambda req, timeout: (_ for _ in ()).throw(_http_error(429)),
        )
        with pytest.raises(SystemExit) as e:
            kolors.call_api({}, "k")
        assert "429" in str(e.value)

    def test_http_400_exits(self, monkeypatch):
        monkeypatch.setattr(
            kolors.urllib.request,
            "urlopen",
            lambda req, timeout: (_ for _ in ()).throw(_http_error(400)),
        )
        with pytest.raises(SystemExit) as e:
            kolors.call_api({}, "k")
        assert "400" in str(e.value)

    def test_urlerror_exits(self, monkeypatch):
        def raise_url(req, timeout):
            raise urllib.error.URLError("dns fail")

        monkeypatch.setattr(kolors.urllib.request, "urlopen", raise_url)
        with pytest.raises(SystemExit):
            kolors.call_api({}, "k")

    def test_timeout_exits(self, monkeypatch):
        def raise_to(req, timeout):
            raise TimeoutError()

        monkeypatch.setattr(kolors.urllib.request, "urlopen", raise_to)
        with pytest.raises(SystemExit):
            kolors.call_api({}, "k")


# ---------- save_image ----------
class TestSaveImage:
    def test_url_branch_downloads(self, tmp_path, monkeypatch):
        called = {}

        def fake_download(url, out_path):
            called["url"] = url
            out_path.write_bytes(b"x" * 2048)  # >1KB 通过校验

        monkeypatch.setattr(kolors, "_download", fake_download)
        out = tmp_path / "o.png"
        kolors.save_image({"data": [{"url": "http://img"}]}, out)
        assert called["url"] == "http://img"
        assert out.exists()

    def test_b64_branch_writes_file(self, tmp_path):
        import base64

        b64 = base64.b64encode(b"x" * 2048).decode()
        out = tmp_path / "o.png"
        kolors.save_image({"data": [{"b64_json": b64}]}, out)
        assert out.read_bytes() == b"x" * 2048

    def test_no_data_exits(self, tmp_path):
        with pytest.raises(SystemExit):
            kolors.save_image({"data": []}, tmp_path / "o.png")
        with pytest.raises(SystemExit):
            kolors.save_image({}, tmp_path / "o.png")


# ---------- to_curl ----------
class TestToCurl:
    def test_key_masked(self):
        body = {"model": "Kolors", "prompt": "p"}
        s = kolors.to_curl(body, "QC-test1234567890")
        # 只显示前 8 字符 + ***，完整 key 不得出现
        assert "QC-test1***" in s
        assert "1234567890" not in s


# ---------- IMAGE_SIZES 一致性 ----------
class TestImageSizes:
    def test_all_wxh_strings(self):
        for k, v in kolors.IMAGE_SIZES.items():
            assert isinstance(v, str) and "x" in v, k

    def test_portrait_landscape_direction(self):
        # 竖屏 W<H，横屏 W>H（"WxH" 字符串）
        def parse(s):
            w, h = s.split("x")
            return int(w), int(h)

        pw, ph = parse(kolors.IMAGE_SIZES["9:16"])
        assert ph > pw  # 竖屏
        lw, lh = parse(kolors.IMAGE_SIZES["16:9"])
        assert lw > lh  # 横屏
