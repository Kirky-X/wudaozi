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
import urllib.request
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

    def test_both_hw_custom_snapped(self):
        # 吸收 gpt_image_playground：自定义尺寸自动规整到 16 倍数
        assert agnes.resolve_size(self._ns(height=800, width=600)) == (800, 608)
        assert agnes.resolve_size(self._ns(height=1024, width=1024)) == (1024, 1024)

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
            urllib.request,
            "urlopen",
            lambda req, timeout: _FakeResp(payload),
        )
        assert agnes.call_api({"model": "x"}, "k") == {"data": [{"url": "http://img"}]}

    def test_http_401_exits(self, monkeypatch):
        def raise_401(req, timeout):
            raise _http_error(401)

        monkeypatch.setattr(urllib.request, "urlopen", raise_401)
        with pytest.raises(SystemExit) as e:
            agnes.call_api({}, "k")
        assert "401" in str(e.value)

    def test_http_429_exits(self, monkeypatch):
        def raise_429(req, timeout):
            raise _http_error(429)

        monkeypatch.setattr(urllib.request, "urlopen", raise_429)
        with pytest.raises(SystemExit) as e:
            agnes.call_api({}, "k")
        assert "429" in str(e.value)

    def test_urlerror_exits(self, monkeypatch):
        def raise_url(req, timeout):
            raise urllib.error.URLError("dns fail")

        monkeypatch.setattr(urllib.request, "urlopen", raise_url)
        with pytest.raises(SystemExit):
            agnes.call_api({}, "k")

    def test_timeout_exits(self, monkeypatch):
        def raise_to(req, timeout):
            raise TimeoutError()

        monkeypatch.setattr(urllib.request, "urlopen", raise_to)
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


# ---------- 吸收自 gpt_image_playground（2026-09-14） ----------
class TestSnapSize:
    def test_aligns_to_16_multiple(self):
        assert agnes.snap_size(800, 600) == (800, 608, ["width 600 -> 608 (snapped to 16-multiple, range 256-2048)"])

    def test_aligned_passes_through(self):
        assert agnes.snap_size(1024, 1024) == (1024, 1024, [])

    def test_clamps_to_bounds(self):
        h, w, _ = agnes.snap_size(9999, 100)
        assert h == 2048 and w == 256

    def test_resolve_size_applies_snap(self):
        ns = SimpleNamespace(aspect=None, height=800, width=600)
        assert agnes.resolve_size(ns) == (800, 608)


class TestStrictPrompt:
    def test_guard_prefixed(self):
        body = agnes.build_body(SimpleNamespace(
            mode="t2i", instruction="cat", input=None, base64=False,
            strict_prompt=True, transparent="off", mask=None,
        ), 1024, 1024)
        assert body["prompt"].startswith(agnes.PROMPT_GUARD)
        assert body["prompt"].endswith("cat")

    def test_guard_off_by_default(self):
        body = agnes.build_body(SimpleNamespace(
            mode="t2i", instruction="cat", input=None, base64=False,
            strict_prompt=False, transparent="off", mask=None,
        ), 1024, 1024)
        assert body["prompt"] == "cat"


class TestTransparentNative:
    def test_background_param(self):
        body = agnes.build_body(SimpleNamespace(
            mode="t2i", instruction="x", input=None, base64=False,
            strict_prompt=False, transparent="native", mask=None,
        ), 1024, 1024)
        assert body["extra_body"]["background"] == "transparent"

    def test_off_has_no_background(self):
        body = agnes.build_body(SimpleNamespace(
            mode="t2i", instruction="x", input=None, base64=False,
            strict_prompt=False, transparent="off", mask=None,
        ), 1024, 1024)
        assert "background" not in body["extra_body"]


class TestMask:
    def test_mask_requires_png(self, tmp_path):
        mask = tmp_path / "m.jpg"
        mask.write_bytes(b"fake-jpeg")
        with pytest.raises(SystemExit):
            agnes.build_body(SimpleNamespace(
                mode="ti2i", instruction="x", input="https://e.com/a.png", base64=False,
                strict_prompt=False, transparent="off", mask=str(mask),
            ), 1024, 1024)

    def test_mask_rejected_for_t2i(self, tmp_path):
        mask = tmp_path / "m.png"
        mask.write_bytes(b"\x89PNG")
        with pytest.raises(SystemExit):
            agnes.build_body(SimpleNamespace(
                mode="t2i", instruction="x", input=None, base64=False,
                strict_prompt=False, transparent="off", mask=str(mask),
            ), 1024, 1024)

    def test_mask_png_injected_as_data_uri(self, tmp_path):
        import base64 as b64mod
        mask = tmp_path / "m.png"
        raw = b"\x89PNG real-bytes"
        mask.write_bytes(raw)
        body = agnes.build_body(SimpleNamespace(
            mode="ti2i", instruction="x", input="https://e.com/a.png", base64=False,
            strict_prompt=False, transparent="off", mask=str(mask),
        ), 1024, 1024)
        expected = "data:image/png;base64," + b64mod.b64encode(raw).decode()
        assert body["extra_body"]["mask"] == expected

    def test_mask_rejected_for_t2i_duplicate_guard(self, tmp_path):
        pass


class TestRemoveChroma:
    def test_magenta_removed_with_pillow(self):
        PIL = pytest.importorskip("PIL")
        from PIL import Image
        import io as _io
        img = Image.new("RGBA", (4, 4), (255, 0, 255, 255))
        img.putpixel((0, 0), (10, 20, 30, 255))  # 一个非洋红主体像素
        buf = _io.BytesIO()
        img.save(buf, "PNG")
        p = Path("dummy.png")
        p.write_bytes(buf.getvalue())
        try:
            agnes.remove_chroma(p, "magenta")
            out = Image.open(p).convert("RGBA")
            assert out.getpixel((0, 0))[3] == 255, "主体像素保留"
            assert out.getpixel((3, 3))[3] == 0, "洋红背景转透明"
        finally:
            p.unlink(missing_ok=True)


class TestSidecar:
    def test_write_sidecar_json(self, tmp_path):
        out = tmp_path / "a.png"
        out.write_bytes(b"x")
        sc = agnes.write_sidecar(out, {"provider": "agnes", "actual": {"bytes": 1}})
        import json as _json
        assert _json.loads(sc.read_text(encoding="utf-8"))["provider"] == "agnes"


class TestCountValidation:
    def test_batch_constants(self):
        assert agnes.BATCH_MAX == 8
        assert agnes.BATCH_CONCURRENCY == 4

    def test_count_rejected_via_cli(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["agnes.py", "t2i", "-i", "x", "--count", "9"])
        with pytest.raises(SystemExit):
            agnes.parse_args()

    def test_count_default_one(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["agnes.py", "t2i", "-i", "x"])
        a = agnes.parse_args()
        assert a.count == 1


# ---------- 失败留痕（调研建议#1） ----------
class TestFailedSidecarIntegration:
    def _ns(self, tmp_path, **kw):
        base = dict(
            mode="t2i", instruction="x", input=None, aspect="1:1", height=None, width=None,
            output_dir=str(tmp_path), base64=False, dry_run=False, count=1,
            transparent="off", chroma="magenta", strict_prompt=False, mask=None,
        )
        base.update(kw)
        return SimpleNamespace(**base)

    def test_401_writes_failed_sidecar_without_key(self, tmp_path, monkeypatch):
        monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout: (_ for _ in ()).throw(_http_error(401)))
        with pytest.raises(SystemExit) as e:
            agnes._generate_once(self._ns(tmp_path), "agn-secret-key-123", 1)
        scs = list(tmp_path.glob("*-failed-*.json"))
        assert len(scs) == 1, "错误路径必须留痕 failed sidecar"
        content = scs[0].read_text(encoding="utf-8")
        assert "agn-secret-key-123" not in content, "key 不得进 sidecar"
        meta = json.loads(content)
        assert meta["provider"] == "agnes" and meta["status"] == "failed"
        assert "留痕" in str(e.value)

    def test_undersized_image_leaves_failed_sidecar(self, tmp_path, monkeypatch):
        # save_image 产物过小路径：半成品被删，但失败原因必须留痕
        payload = json.dumps({"data": [{"b64_json": __import__("base64").b64encode(b"tiny").decode()}]}).encode()
        monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout: _FakeResp(payload))
        with pytest.raises(SystemExit):
            agnes._generate_once(self._ns(tmp_path), "k", 1)
        scs = list(tmp_path.glob("*-failed-*.json"))
        assert len(scs) == 1
        assert "abnormal_artifact" in scs[0].read_text(encoding="utf-8")

    def test_success_has_no_failed_sidecar(self, tmp_path, monkeypatch):
        payload = json.dumps({"data": [{"b64_json": __import__("base64").b64encode(b"x" * 2048).decode()}]}).encode()
        monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout: _FakeResp(payload))
        agnes._generate_once(self._ns(tmp_path), "k", 1)
        assert not list(tmp_path.glob("*-failed-*.json"))


# ---------- 批量路径执行级测试（性能审查 F2） ----------
class TestBatchMain:
    def test_partial_failure_reports_and_exits_1(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("AGNES_API_KEY", "agn-test")
        monkeypatch.setattr(
            sys, "argv",
            ["agnes.py", "t2i", "-i", "x", "--count", "2", "--output-dir", str(tmp_path)],
        )

        def fake_once(a, api_key, index, instruction=None):
            if index == 2:
                raise SystemExit("[ERROR] code=auth_error batch-sim-401")
            out = tmp_path / f"ok_{index}.png"
            out.write_bytes(b"x" * 2048)
            return out

        monkeypatch.setattr(agnes, "_generate_once", fake_once)
        with pytest.raises(SystemExit) as e:
            agnes.main()
        assert e.value.code == 1
        err = capsys.readouterr().err
        assert "[BATCH] 1/2" in err, "部分失败必须显式上报数量"
        assert "batch-sim-401" in err

    def test_all_success_exits_0(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("AGNES_API_KEY", "agn-test")
        monkeypatch.setattr(
            sys, "argv",
            ["agnes.py", "t2i", "-i", "x", "--count", "2", "--output-dir", str(tmp_path)],
        )

        def fake_once(a, api_key, index, instruction=None):
            out = tmp_path / f"ok_{index}.png"
            out.write_bytes(b"x" * 2048)
            return out

        monkeypatch.setattr(agnes, "_generate_once", fake_once)
        assert agnes.main() == 0
        assert "[BATCH] 2/2" in capsys.readouterr().err


# ---------- --ref-role 参考图角色子句（调研 R11） ----------
class TestRefRole:
    def test_subject_default_no_clause(self):
        body = agnes.build_body(SimpleNamespace(
            mode="ti2i", instruction="换成沙滩背景", input="https://e.com/a.png", base64=False,
            ref_role="subject",
        ), 1024, 1024)
        assert body["prompt"] == "换成沙滩背景"

    def test_style_clause_appended(self):
        body = agnes.build_body(SimpleNamespace(
            mode="ti2i", instruction="画一只猫", input="https://e.com/a.png", base64=False,
            ref_role="style",
        ), 1024, 1024)
        assert body["prompt"].startswith("画一只猫")
        assert "style/aesthetic" in body["prompt"]
        assert "do NOT reproduce its subject" in body["prompt"]

    def test_composition_clause_appended(self):
        body = agnes.build_body(SimpleNamespace(
            mode="ti2i", instruction="画一只猫", input="https://e.com/a.png", base64=False,
            ref_role="composition",
        ), 1024, 1024)
        assert "composition reference" in body["prompt"]

    def test_invalid_role_exits(self):
        with pytest.raises(SystemExit):
            agnes.build_body(SimpleNamespace(
                mode="ti2i", instruction="x", input="https://e.com/a.png", base64=False,
                ref_role="bogus",
            ), 1024, 1024)

    def test_missing_attr_defaults_subject(self):
        # 旧调用方（无 ref_role 属性）行为不变
        body = agnes.build_body(_body_ns(mode="ti2i", input="https://e.com/a.png"), 1024, 1024)
        assert body["prompt"] == "测试 prompt"

    def test_cli_choices(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["agnes.py", "ti2i", "-i", "x", "--input", "u",
                                         "--ref-role", "style"])
        assert agnes.parse_args().ref_role == "style"

    def test_cli_default_none_normalized_in_main(self, monkeypatch):
        # CLI 默认 None:main() 归一化为 subject(--ref style 资产时派生 style)
        monkeypatch.setattr("sys.argv", ["agnes.py", "t2i", "-i", "x"])
        assert agnes.parse_args().ref_role is None


# ---------- 变体展开集成（调研 R12） ----------
class TestVariantsMain:
    def _run(self, tmp_path, monkeypatch, instruction, count):
        monkeypatch.setenv("AGNES_API_KEY", "agn-test")
        monkeypatch.setattr(
            sys, "argv",
            ["agnes.py", "t2i", "-i", instruction, "--count", str(count), "--output-dir", str(tmp_path)],
        )
        captured = []

        def fake_once(a, api_key, index, instruction=None):
            captured.append(instruction)
            out = tmp_path / f"ok_{index}.png"
            out.write_bytes(b"x" * 2048)
            return out

        monkeypatch.setattr(agnes, "_generate_once", fake_once)
        assert agnes.main() == 0
        return captured

    def test_plain_instruction_stays_identical(self, tmp_path, monkeypatch):
        got = self._run(tmp_path, monkeypatch, "一只猫", 3)
        assert got == ["一只猫"] * 3, "无变体语法 = 原样 N 份（历史行为）"

    def test_enum_expands_nondecreasing_variants(self, tmp_path, monkeypatch):
        got = self._run(tmp_path, monkeypatch, "一只{橘|黑|白}猫", 3)
        assert len(got) == 3
        assert len(set(got)) == 3, "组合空间足够时必须非重复"
        assert all(g in ("一只橘猫", "一只黑猫", "一只白猫") for g in got)

    def test_single_count_with_syntax_renders_one_variant(self, tmp_path, monkeypatch):
        got = self._run(tmp_path, monkeypatch, "一只{橘|黑}猫", 1)
        assert got == [got[0]]
        assert got[0] in ("一只橘猫", "一只黑猫")


# ---------- PNG 元数据 + stdout 契约（调研 R1/R3） ----------
class TestOutputContractAndMetadata:
    def _ns(self, tmp_path, **kw):
        base = dict(
            mode="t2i", instruction="x", input=None, aspect="1:1", height=None, width=None,
            output_dir=str(tmp_path), base64=False, dry_run=False, count=1,
            transparent="off", chroma="magenta", strict_prompt=False, mask=None,
            ref_role="subject",
        )
        base.update(kw)
        return SimpleNamespace(**base)

    def test_success_stdout_has_machine_line(self, tmp_path, monkeypatch, capsys):
        import base64
        payload = json.dumps({"data": [{"b64_json": base64.b64encode(b"x" * 2048).decode()}]}).encode()
        monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout: _FakeResp(payload))
        out = agnes._generate_once(self._ns(tmp_path), "k", 1)
        captured = capsys.readouterr()
        assert captured.out == f"WUDAOZI_OUTPUT={out}\n", "stdout 必须恰好一行机器可读路径"

    def test_png_gets_parameters_chunk(self, tmp_path, monkeypatch):
        # 真实 PNG 字节：签名 + 合法 IHDR（13B 数据）+ 填充块（过 1KB 产物校验）
        import base64
        import struct
        import zlib
        ihdr_data = struct.pack(">IIBBBBB", 8, 8, 8, 2, 0, 0, 0)
        ihdr = struct.pack(">I", 13) + b"IHDR" + ihdr_data + struct.pack(">I", zlib.crc32(b"IHDR" + ihdr_data))
        pad_data = b"\x00" * 2000
        pad = struct.pack(">I", len(pad_data)) + b"prVt" + pad_data + struct.pack(">I", zlib.crc32(b"prVt" + pad_data))
        png_bytes = b"\x89PNG\r\n\x1a\n" + ihdr + pad
        payload = json.dumps({"data": [{"b64_json": base64.b64encode(png_bytes).decode()}]}).encode()
        monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout: _FakeResp(payload))
        out = agnes._generate_once(self._ns(tmp_path), "k", 1)
        raw = out.read_bytes()
        assert raw.startswith(b"\x89PNG\r\n\x1a\n")
        assert b"tEXt" in raw[:200] and b"parameters" in raw[:200]
        # IHDR 原样保留在头部，tEXt 紧跟其后（33 起是 chunk 长度字段，37 起是类型）
        assert raw[12:16] == b"IHDR" and raw[37:41] == b"tEXt"

    def test_non_png_content_skips_metadata_loudly(self, tmp_path, monkeypatch, capsys):
        # 响应实际是 JPEG 但落了 .png 名：绝不损坏产物，告警显性化
        import base64
        payload = json.dumps({"data": [{"b64_json": base64.b64encode(b"\xff\xd8\xff" + b"x" * 2045).decode()}]}).encode()
        monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout: _FakeResp(payload))
        out = agnes._generate_once(self._ns(tmp_path), "k", 1)
        err = capsys.readouterr().err
        assert "[WARN]" in err and "PNG" in err
        assert out.read_bytes().startswith(b"\xff\xd8\xff"), "产物字节不得被改动"


# ---------- 审查修复回归:agnes --ref 资产引用(此前文档承诺未实现) ----------
class TestRefAssets:
    def _seed_asset(self, store, monkeypatch, name="hero", kind="character"):
        import sys as _sys
        from pathlib import Path as _P

        _sys.path.insert(0, str(_P(__file__).parent))
        import assets as _assets

        monkeypatch.setenv("WUDAOZI_ASSETS_DIR", str(_P(store)))
        ref = _P(store) / f"{name}.png"
        ref.write_bytes(b"\x89PNG-fake")
        monkeypatch.setattr("sys.argv", ["assets.py", "add", name, "--kind", kind, "--ref", str(ref)])
        assert _assets.main() == 0
        return ref

    def test_build_body_uses_refs_list(self, tmp_path):
        for name in ("a.png", "b.png"):
            (tmp_path / name).write_bytes(b"\x89PNG-fake")
        body = agnes.build_body(SimpleNamespace(
            mode="ti2i", instruction="画一只猫", input=None, base64=False,
            ref_role="subject", _refs=[tmp_path / "a.png", tmp_path / "b.png"],
        ), 1024, 1024)
        imgs = body["extra_body"]["image"]
        assert len(imgs) == 2
        assert all(u.startswith("data:image/png;base64,") for u in imgs), "--ref 多张全部转 data URI"

    def test_main_ref_dry_run_subject(self, tmp_path, monkeypatch, capsys):
        self._seed_asset(tmp_path, monkeypatch, "hero", "character")
        monkeypatch.setenv("AGNES_API_KEY", "agn-test")
        monkeypatch.setattr(
            sys, "argv",
            ["agnes.py", "ti2i", "-i", "画一只猫", "--ref", "hero",
             "--output-dir", str(tmp_path), "--dry-run"],
        )
        assert agnes.main() == 0
        err = capsys.readouterr().err
        assert "[DRY-RUN]" in err
        assert "style/aesthetic" not in err, "character 资产默认 subject,无风格子句"

    def test_main_ref_style_asset_gets_style_clause(self, tmp_path, monkeypatch, capsys):
        self._seed_asset(tmp_path, monkeypatch, "ink", "style")
        monkeypatch.setenv("AGNES_API_KEY", "agn-test")
        monkeypatch.setattr(
            sys, "argv",
            ["agnes.py", "ti2i", "-i", "画一只猫", "--ref", "ink",
             "--output-dir", str(tmp_path), "--dry-run"],
        )
        assert agnes.main() == 0
        assert "style/aesthetic" in capsys.readouterr().err, "style 资产默认派生 --ref-role style"

    def test_main_ref_conflicts_with_input(self, tmp_path, monkeypatch):
        self._seed_asset(tmp_path, monkeypatch, "hero", "character")
        monkeypatch.setenv("AGNES_API_KEY", "agn-test")
        monkeypatch.setattr(
            sys, "argv",
            ["agnes.py", "ti2i", "-i", "x", "--ref", "hero", "--input", "a.png", "--dry-run"],
        )
        with pytest.raises(SystemExit) as e:
            agnes.main()
        assert "互斥" in str(e.value)

    def test_main_ref_rejected_for_t2i(self, tmp_path, monkeypatch):
        self._seed_asset(tmp_path, monkeypatch, "hero", "character")
        monkeypatch.setenv("AGNES_API_KEY", "agn-test")
        monkeypatch.setattr(
            sys, "argv",
            ["agnes.py", "t2i", "-i", "x", "--ref", "hero", "--dry-run"],
        )
        with pytest.raises(SystemExit) as e:
            agnes.main()
        assert "仅支持 ti2i" in str(e.value)

    def test_role_default_normalized_subject(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["agnes.py", "t2i", "-i", "x"])
        assert agnes.parse_args().ref_role is None, "CLI 默认 None(由 main 归一化/资产派生)"
