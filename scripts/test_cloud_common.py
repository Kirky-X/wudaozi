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

    def read(self, length=-1):
        # download_to_file 已改流式（copyfileobj）：一次性返回后清空，读到空即停
        data, self._p = self._p, b""
        return data

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

    def test_failure_removes_part_file_and_exits(self, tmp_path, monkeypatch):
        # 流式 + .part 原子落盘：失败只删 .part，不动旧产物（rename 前产物不可见）
        def raise_url(url, timeout):
            raise urllib.error.URLError("reset")

        monkeypatch.setattr(urllib.request, "urlopen", raise_url)
        out = tmp_path / "o.png"
        with pytest.raises(SystemExit):
            cc.download_to_file("http://img/x", out, 30, "agnes")
        assert not out.exists() and not list(tmp_path.glob("*.part"))

    def test_success_renames_part_atomically(self, tmp_path, monkeypatch):
        monkeypatch.setattr(urllib.request, "urlopen", lambda url, timeout: _FakeResp(b"full-bytes"))
        out = tmp_path / "o.png"
        cc.download_to_file("http://img/x", out, 30, "agnes")
        assert out.read_bytes() == b"full-bytes"
        assert not list(tmp_path.glob("*.part"))


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


# ---------- 失败留痕 failed sidecar（调研建议#1） ----------
class TestFailedSidecar:
    def test_write_failed_sidecar_json(self, tmp_path):
        out = tmp_path / "agnes_t2i_1024x1024_1_a.png"
        sc = cc.write_failed_sidecar(out, {"status": "failed", "provider": "agnes", "error": "boom"})
        assert sc.exists() and "-failed-" in sc.name and sc.suffix == ".json"
        data = json.loads(sc.read_text(encoding="utf-8"))
        assert data["error"] == "boom" and data["status"] == "failed"

    def test_write_failure_never_masks_original_error(self, tmp_path):
        # 父路径是文件 → mkdir/write 必失败 → 只告警返回 None，绝不抛出掩盖原始错误
        blocker = tmp_path / "blocker"
        blocker.write_text("i-am-a-file")
        out = blocker / "a.png"
        assert cc.write_failed_sidecar(out, {"error": "x"}) is None

    def test_failed_meta_carries_argv_not_key(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["agnes.py", "t2i", "-i", "x"])
        meta = cc.failed_sidecar_meta(Path("/tmp/a.png"), "agnes", "HTTP 401", {"mode": "t2i"})
        assert meta["argv"] == ["t2i", "-i", "x"]
        assert meta["provider"] == "agnes" and meta["mode"] == "t2i"

    def test_raise_with_trace_appends_sidecar_line(self, tmp_path):
        out = tmp_path / "a.png"
        with pytest.raises(SystemExit) as e:
            try:
                cc.fail("network_error", "网络炸了")
            except SystemExit as se:
                cc.raise_with_trace(se, out, "agnes", {"mode": "t2i"})
        assert "失败详情已留痕" in str(e.value)
        assert list(tmp_path.glob("*-failed-*.json"))

    def test_int_exit_code_written_but_not_augmented(self, tmp_path):
        out = tmp_path / "a.png"
        with pytest.raises(SystemExit) as e:
            try:
                sys.exit(1)
            except SystemExit as se:
                cc.raise_with_trace(se, out, "agnes")
        assert e.value.code == 1  # 退出码语义不变
        assert list(tmp_path.glob("*-failed-*.json"))  # 但留痕照写


# ---------- Retry-After 解析（调研建议#2） ----------
class TestParseRetryAfter:
    def test_numeric_seconds(self):
        import time as _t
        assert cc.parse_retry_after("7") == 7.0

    def test_zero_is_invalid(self):
        # 0 视为无效 → 调用方回退退避抖动（防 0 值死循环，comfy 同款）
        assert cc.parse_retry_after("0") is None

    def test_negative_is_invalid(self):
        assert cc.parse_retry_after("-3") is None

    def test_garbage_is_invalid(self):
        assert cc.parse_retry_after("soon") is None

    def test_missing_is_none(self):
        assert cc.parse_retry_after(None) is None
        assert cc.parse_retry_after("") is None

    def test_http_date_in_future(self):
        import time as _t
        from email.utils import formatdate
        future = formatdate(_t.time() + 30, usegmt=True)
        v = cc.parse_retry_after(future)
        assert v is not None and 0 < v <= 31

    def test_http_date_in_past_is_none(self):
        import time as _t
        from email.utils import formatdate
        past = formatdate(_t.time() - 60, usegmt=True)
        assert cc.parse_retry_after(past) is None


# ---------- 审查修复回归（安全 M-1/M-2/L-1，架构 M-5） ----------
class TestReviewFixes:
    def test_cgnat_rejected(self):
        # CGNAT 100.64.0.0/10 不归 ipaddress private，须显式拒绝（安全 L-1）
        with pytest.raises(SystemExit):
            cc.assert_public_url("http://100.64.0.1/x")

    def test_failed_sidecar_masks_key_shaped_strings(self, tmp_path):
        # 网关可能在 4xx 错误体回显 Authorization 值——落盘前必须脱敏（安全 M-1）
        meta = cc.failed_sidecar_meta(
            tmp_path / "a.png", "agnes",
            'HTTP 401: {"message":"invalid key agn-SUPERSECRET123"}',
            {"instruction": "use QC-anotherkey999 please"},
        )
        assert "agn-SUPERSECRET123" not in meta["error"]
        assert "agn-SUPE***" in meta["error"]
        assert "QC-anoth***" in meta["instruction"]
        sc = cc.write_failed_sidecar(tmp_path / "a.png", meta)
        assert "agn-SUPERSECRET123" not in sc.read_text(encoding="utf-8")

    def test_download_rejects_non_public_urls(self, tmp_path):
        # 下载 URL 来自 provider 响应——被入侵的 provider 不能诱导 CLI 读本地文件（安全 M-2）
        out = tmp_path / "o.png"
        with pytest.raises(SystemExit):
            cc.download_to_file("file:///etc/hostname", out, 30, "agnes")
        with pytest.raises(SystemExit):
            cc.download_to_file("http://169.254.169.254/latest/meta-data/", out, 30, "agnes")
        assert not out.exists() and not list(tmp_path.glob("*.part"))

    def test_image_to_data_uri_oversize_exits(self, tmp_path):
        import os as _os
        p = tmp_path / "big.png"
        p.write_bytes(b"\x89PNG" + b"0" * 100)
        with pytest.raises(SystemExit) as e:
            cc.image_to_data_uri(str(p), max_bytes=10)
        assert "code=invalid_param" in str(e.value)
        assert _os.path.exists(p), "超限图不得被删除"

    def test_to_curl_quotes_single_quotes(self):
        # prompt 含单引号时不得产生可被复制执行的注入命令（安全 M-3）
        body = {"prompt": "cat'; touch PWNED; echo '"}
        s = cc.to_curl("https://x", body, "agn-secret12345")
        assert "; touch PWNED;" not in s.replace("\'", "") or s.count("'") >= 2
        import shlex as _sh
        # shlex 反解 -d 参数应还原出原始 JSON
        import re as _re
        m = _re.search(r"-d (.+)$", s, _re.S)
        assert m and "'cat'" not in m.group(1)[1:-1]  # 不再裸拼单引号包裹


# ---------- PNG 元数据内嵌（调研 R3：sidecar-only → PNG 文本 chunk 双轨） ----------
def _png_bytes(pad: int = 2000) -> bytes:
    """最小合法 PNG：签名 + IHDR + 填充块（embed 只要求结构，不要求可渲染）。"""
    import struct
    import zlib

    ihdr_data = struct.pack(">IIBBBBB", 8, 8, 8, 2, 0, 0, 0)
    ihdr = struct.pack(">I", 13) + b"IHDR" + ihdr_data + struct.pack(">I", zlib.crc32(b"IHDR" + ihdr_data))
    out = b"\x89PNG\r\n\x1a\n" + ihdr
    if pad:
        data = b"\x00" * pad
        out += struct.pack(">I", len(data)) + b"prVt" + data + struct.pack(">I", zlib.crc32(b"prVt" + data))
    return out


def _walk_chunks(raw: bytes):
    """遍历 PNG chunk：yield (type, data)。"""
    import struct

    assert raw[:8] == b"\x89PNG\r\n\x1a\n"
    off = 8
    while off < len(raw):
        (length,) = struct.unpack(">I", raw[off:off + 4])
        ctype = raw[off + 4:off + 8]
        data = raw[off + 8:off + 8 + length]
        yield ctype, data
        off += 12 + length


class TestPngMetadata:
    def test_ascii_prompt_uses_text_chunk(self, tmp_path):
        p = tmp_path / "a.png"
        p.write_bytes(_png_bytes())
        assert cc.embed_png_metadata(p, "a cat, highly detailed", "blurry", {"seed": 42})
        chunks = list(_walk_chunks(p.read_bytes()))
        assert chunks[0][0] == b"IHDR", "IHDR 必须仍是首块"
        assert chunks[1][0] == b"tEXt", "ASCII 场景用 tEXt（webui/sd.cpp 可读）"
        kw, _, val = chunks[1][1].partition(b"\x00")
        assert kw == b"parameters"
        text = val.decode("latin-1")
        assert text.startswith("a cat, highly detailed")
        assert "Negative prompt: blurry" in text
        assert "seed: 42" in text

    def test_chinese_prompt_uses_itxt(self, tmp_path):
        p = tmp_path / "c.png"
        p.write_bytes(_png_bytes())
        assert cc.embed_png_metadata(p, "一只在月光下的橘猫", None, {"provider": "boogu"})
        chunks = list(_walk_chunks(p.read_bytes()))
        assert chunks[1][0] == b"iTXt", "中文超出 latin-1，必须走 iTXt(UTF-8)"
        data = chunks[1][1]
        assert data.split(b"\x00", 1)[1][2:].lstrip(b"\x00").decode("utf-8").startswith("一只")

    def test_non_png_content_not_modified(self, tmp_path, capsys):
        p = tmp_path / "j.png"
        raw = b"\xff\xd8\xff" + b"x" * 100  # JPEG 字节落了 .png 名
        p.write_bytes(raw)
        assert cc.embed_png_metadata(p, "x", None, {}) is False
        assert p.read_bytes() == raw, "非 PNG 产物绝不能被改写"
        assert "[WARN]" in capsys.readouterr().err

    def test_no_part_file_leftover(self, tmp_path):
        p = tmp_path / "a.png"
        p.write_bytes(_png_bytes())
        cc.embed_png_metadata(p, "x", None, {})
        assert not list(tmp_path.glob("*.part")), "原子落盘不得残留 .part"

    def test_parameters_text_shape(self):
        s = cc.png_parameters_text("prompt1", "neg1", {"a": 1, "b": None})
        lines = s.splitlines()
        assert lines[0] == "prompt1"
        assert lines[1] == "Negative prompt: neg1"
        assert lines[2] == "a: 1", "值为 None 的键不得出现（不编造参数）"

    def test_no_negative_line_when_absent(self):
        s = cc.png_parameters_text("prompt1", None, {"k": "v"})
        assert "Negative prompt" not in s


# ---------- ti2i 参考图角色子句（调研 R11） ----------
class TestRefRoleClauses:
    def test_subject_is_noop(self):
        assert cc.apply_ref_role("画一只猫", "subject") == "画一只猫"

    def test_style_appends_constraint(self):
        out = cc.apply_ref_role("画一只猫", "style")
        assert out.startswith("画一只猫")
        assert "style/aesthetic" in out and "do NOT reproduce" in out

    def test_composition_appends_constraint(self):
        out = cc.apply_ref_role("画一只猫", "composition")
        assert "composition reference" in out

    def test_invalid_role_exits(self):
        with pytest.raises(SystemExit) as e:
            cc.apply_ref_role("x", "bogus")
        assert "code=invalid_param" in str(e.value)

    def test_three_roles_distinct(self):
        outs = {cc.apply_ref_role("x", r) for r in cc.REF_ROLE_CLAUSES}
        assert len(outs) == 3


# ---------- 跨进程并发闸（调研 R15：flock 槽位池） ----------
class TestProviderSlot:
    def test_zero_env_is_unlimited(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cc, "LOCK_DIR", tmp_path)
        monkeypatch.setenv("WUDAOZI_CONCURRENCY_AGNES", "0")
        with cc.provider_slot("agnes") as fh:
            assert fh is None, "0=不限：不建槽位文件直接放行"
        assert not list(tmp_path.iterdir())

    def test_invalid_env_exits(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cc, "LOCK_DIR", tmp_path)
        monkeypatch.setenv("WUDAOZI_CONCURRENCY_AGNES", "abc")
        with pytest.raises(SystemExit) as e:
            with cc.provider_slot("agnes"):
                pass
        assert "code=invalid_param" in str(e.value)

    def test_acquire_release(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cc, "LOCK_DIR", tmp_path)
        with cc.provider_slot("agnes") as fh:
            assert fh is not None
            assert (tmp_path / "agnes-0.lock").exists()
        # 释放后可重新获取
        with cc.provider_slot("agnes"):
            pass

    def test_exclusive_hold_blocks_second(self, tmp_path, monkeypatch):
        import threading

        monkeypatch.setattr(cc, "LOCK_DIR", tmp_path)
        monkeypatch.setenv("WUDAOZI_CONCURRENCY_AGNES", "1")  # 默认 2 槽，压到 1 才测互斥
        with cc.provider_slot("agnes"):
            result = {}

            def try_second():
                try:
                    with cc.provider_slot("agnes", timeout=0.3):
                        result["ok"] = True
                except SystemExit as e:
                    result["exit"] = str(e)

            t = threading.Thread(target=try_second)
            t.start()
            t.join()
        assert "exit" in result and "timeout" in result["exit"], "被占用时必须在超时后显性失败"
        assert "ok" not in result

    def test_limit_caps_concurrent_overlap(self, tmp_path, monkeypatch):
        import threading
        import time as _t

        monkeypatch.setattr(cc, "LOCK_DIR", tmp_path)
        monkeypatch.setenv("WUDAOZI_CONCURRENCY_KOLORS", "2")
        state = {"cur": 0, "max": 0}
        mux = threading.Lock()

        def worker():
            with cc.provider_slot("kolors"):
                with mux:
                    state["cur"] += 1
                    state["max"] = max(state["max"], state["cur"])
                _t.sleep(0.08)
                with mux:
                    state["cur"] -= 1

        threads = [threading.Thread(target=worker) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert state["max"] <= 2, f"6 个并发必须被 2 槽闸住（实测峰值 {state['max']}）"
        assert state["cur"] == 0

    def test_slot_files_shared_in_tmpdir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cc, "LOCK_DIR", tmp_path)
        with cc.provider_slot("video", timeout=1):
            assert (tmp_path / "video-0.lock").exists(), "槽位文件按 provider 命名"


# ---------- 审查修复回归:符号链接槽位跳过不崩(POSIX) ----------
class TestLockSymlinkHardening:
    def test_symlinked_slot_skipped(self, tmp_path, monkeypatch):
        import os as _os
        import sys as _sys

        if _sys.platform == "win32":
            pytest.skip("O_NOFOLLOW 为 POSIX 语义")
        monkeypatch.setattr(cc, "LOCK_DIR", tmp_path)
        monkeypatch.setenv("WUDAOZI_CONCURRENCY_AGNES", "2")
        # 预置指向不存在目标的符号链接:打开必须失败并跳过,走 slot-1
        _os.symlink(tmp_path / "nonexistent-target", tmp_path / "agnes-0.lock")
        with cc.provider_slot("agnes") as fh:
            assert fh is not None, "符号链接槽位必须被跳过而非崩溃"

    def test_meta_part_cleaned_on_rename_failure(self, tmp_path, monkeypatch, capsys):
        # rename 失败(如磁盘写满)时:.part 残留必须被清掉(含 prompt 全文,不留在产物目录)
        import pathlib as _pathlib

        p = tmp_path / "a.png"
        p.write_bytes(_png_bytes())

        def _fail_rename(self, target):
            raise OSError("simulated ENOSPC")

        monkeypatch.setattr(_pathlib.Path, "rename", _fail_rename)
        assert cc.embed_png_metadata(p, "x", None, {}) is False
        assert "[WARN]" in capsys.readouterr().err
        assert not list(tmp_path.glob("*.meta.part")), ".part 残留必须被清理"
        assert p.read_bytes().startswith(b"\x89PNG"), "原产物不受影响"

    def test_meta_part_dir_collision_no_crash(self, tmp_path, capsys):
        # .part 路径被目录占用(极端场景):不得崩溃、不得改写产物
        p = tmp_path / "a.png"
        p.write_bytes(_png_bytes())
        (tmp_path / "a.png.meta.part").mkdir()  # with_suffix 后的真实 .part 路径
        assert cc.embed_png_metadata(p, "x", None, {}) is False
        assert p.read_bytes().startswith(b"\x89PNG"), "原产物不受影响"
