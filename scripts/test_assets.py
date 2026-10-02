#!/usr/bin/env python3
"""wudaozi assets.py 单元测试 —— 资产库 CRUD 与消费端解析（不打网络）。

覆盖：add（--ref / --from-last）/ list / show / remove / 名称校验 / 引用解析上限。
跑法：python3 -m pytest scripts/test_assets.py -v
"""
# ponytail: 存储隔离靠 WUDAOZI_ASSETS_DIR——测试永不碰真实 ~/.config。

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import assets  # noqa: E402


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("WUDAOZI_ASSETS_DIR", str(tmp_path / "assets"))
    return tmp_path


def _run(argv, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["assets.py"] + argv)
    return assets.main()


# ---------- add ----------
class TestAdd:
    def test_add_copies_refs_into_store(self, store, monkeypatch, capsys):
        ref = store / "shot1.png"
        ref.write_bytes(b"png-bytes-1")
        _run(["add", "hero", "--kind", "character", "--ref", str(ref)], monkeypatch)
        meta = assets.load_asset("hero")
        assert meta["kind"] == "character"
        assert len(meta["refs"]) == 1
        assert meta["refs"][0].read_bytes() == b"png-bytes-1", "参考图必须拷贝入库"
        assert meta["refs"][0] != ref, "入库后与原文件解耦（原文件可删）"

    def test_add_multi_refs(self, store, monkeypatch):
        a = store / "a.png"
        b = store / "b.png"
        a.write_bytes(b"1")
        b.write_bytes(b"2")
        _run(["add", "hero", "--kind", "character", "--ref", str(a), str(b)], monkeypatch)
        assert len(assets.load_asset("hero")["refs"]) == 2

    def test_add_existing_without_force_exits(self, store, monkeypatch):
        ref = store / "x.png"
        ref.write_bytes(b"x")
        _run(["add", "hero", "--kind", "style", "--ref", str(ref)], monkeypatch)
        with pytest.raises(SystemExit):
            _run(["add", "hero", "--kind", "style", "--ref", str(ref)], monkeypatch)

    def test_add_force_overwrites(self, store, monkeypatch):
        ref = store / "x.png"
        ref.write_bytes(b"x")
        _run(["add", "hero", "--kind", "style", "--ref", str(ref)], monkeypatch)
        ref.write_bytes(b"y")
        _run(["add", "hero", "--kind", "style", "--ref", str(ref), "--force"], monkeypatch)
        assert assets.load_asset("hero")["refs"][0].read_bytes() == b"y"

    def test_add_missing_ref_exits(self, store, monkeypatch):
        with pytest.raises(SystemExit):
            _run(["add", "hero", "--kind", "character", "--ref", "/no/such.png"], monkeypatch)

    def test_invalid_name_exits(self, store, monkeypatch, tmp_path):
        ref = tmp_path / "x.png"
        ref.write_bytes(b"x")
        for bad in ("../evil", "a/b", "", "中文名"):
            with pytest.raises(SystemExit):
                _run(["add", bad, "--kind", "character", "--ref", str(ref)], monkeypatch)

    def test_invalid_kind_rejected_by_cli(self, store, monkeypatch):
        with pytest.raises(SystemExit):
            _run(["add", "hero", "--kind", "bogus", "--from-last"], monkeypatch)


# ---------- from-last ----------
class TestFromLast:
    def test_picks_newest_generated(self, store, monkeypatch):
        out = store / "agnes-output"
        out.mkdir()
        (out / "old.png").write_bytes(b"old")
        import os

        newest = out / "new.png"
        newest.write_bytes(b"new")
        stat = newest.stat()
        os.utime((out / "old.png"), (stat.st_atime - 100, stat.st_mtime - 100))
        monkeypatch.chdir(store)  # --from-last 扫描 cwd 的产物目录，必须隔离
        _run(["add", "hero", "--kind", "character", "--from-last"], monkeypatch)
        assert assets.load_asset("hero")["refs"][0].read_bytes() == b"new"

    def test_no_outputs_exits(self, store, monkeypatch, capsys):
        monkeypatch.chdir(store)  # 空 cwd：无任何输出目录
        with pytest.raises(SystemExit) as e:
            _run(["add", "hero", "--kind", "character", "--from-last"], monkeypatch)
        assert "未找到任何生成产物" in str(e.value)


# ---------- list / show / remove ----------
class TestCrud:
    def _seed(self, store, monkeypatch):
        ref = store / "x.png"
        ref.write_bytes(b"x")
        _run(["add", "ink", "--kind", "style", "--ref", str(ref), "--note", "水墨画风"], monkeypatch)

    def test_list_and_show(self, store, monkeypatch, capsys):
        self._seed(store, monkeypatch)
        _run(["list"], monkeypatch)
        assert "ink" in capsys.readouterr().out
        _run(["show", "ink"], monkeypatch)
        out = capsys.readouterr().out
        assert "style" in out and "水墨画风" in out

    def test_show_missing_exits_with_hint(self, store, monkeypatch):
        self._seed(store, monkeypatch)
        with pytest.raises(SystemExit) as e:
            _run(["show", "nope"], monkeypatch)
        assert "可用资产" in str(e.value), "缺失报错必须列出可用资产（拼错可自纠）"

    def test_remove(self, store, monkeypatch):
        self._seed(store, monkeypatch)
        _run(["remove", "ink"], monkeypatch)
        with pytest.raises(SystemExit):
            assets.load_asset("ink")

    def test_remove_missing_exits(self, store, monkeypatch):
        with pytest.raises(SystemExit):
            _run(["remove", "ghost"], monkeypatch)


# ---------- 消费端解析（agnes/boogu --ref 用） ----------
class TestResolveRefs:
    def test_flatten_multiple_assets(self, store, monkeypatch):
        a = store / "a.png"
        b = store / "b.png"
        a.write_bytes(b"1")
        b.write_bytes(b"2")
        _run(["add", "hero", "--kind", "character", "--ref", str(a)], monkeypatch)
        _run(["add", "ink", "--kind", "style", "--ref", str(b)], monkeypatch)
        refs = assets.resolve_refs(["hero", "ink"])
        assert [p.name for p in refs] == ["a.png", "b.png"]

    def test_cap_warns_and_truncates(self, store, monkeypatch, capsys):
        refs = []
        for i in range(6):
            p = store / f"r{i}.png"
            p.write_bytes(b"x")
            refs.append(str(p))
        _run(["add", "big", "--kind", "character", "--ref", *refs], monkeypatch)
        got = assets.resolve_refs(["big"])
        assert len(got) == 4, "上限 4：超限截断"
        assert "仅取前 4" in capsys.readouterr().err

    def test_missing_ref_file_exits(self, store, monkeypatch):
        a = store / "a.png"
        a.write_bytes(b"1")
        _run(["add", "hero", "--kind", "character", "--ref", str(a)], monkeypatch)
        # 模拟库被手动清理：删掉入库副本
        assets.load_asset("hero")["refs"][0].unlink()
        with pytest.raises(SystemExit) as e:
            assets.resolve_refs(["hero"])
        assert "缺失" in str(e.value)


# ---------- 审查修复回归:双资产排序/同名源/refs 穿越 ----------
class TestReviewFixes:
    def test_list_two_assets_sorted(self, store, monkeypatch, capsys):
        for name in ("zeta", "alpha"):
            ref = store / f"{name}.png"
            ref.write_bytes(b"x")
            _run(["add", name, "--kind", "character", "--ref", str(ref)], monkeypatch)
        _run(["list"], monkeypatch)
        out = capsys.readouterr().out
        assert out.index("alpha") < out.index("zeta"), "多资产必须按名字排序(dict 排序会 TypeError)"

    def test_add_duplicate_source_names_exits(self, store, monkeypatch):
        d1 = store / "d1"
        d2 = store / "d2"
        d1.mkdir()
        d2.mkdir()
        (d1 / "same.png").write_bytes(b"1")
        (d2 / "same.png").write_bytes(b"2")
        with pytest.raises(SystemExit) as e:
            _run(["add", "hero", "--kind", "character", "--ref", str(d1 / "same.png"), str(d2 / "same.png")], monkeypatch)
        assert "同名文件" in str(e.value)

    def test_tampered_meta_refs_rejected(self, store, monkeypatch):
        import json as _json

        ref = store / "x.png"
        ref.write_bytes(b"x")
        _run(["add", "hero", "--kind", "character", "--ref", str(ref)], monkeypatch)
        meta_path = assets.store_root() / "hero" / "meta.json"
        meta = _json.loads(meta_path.read_text(encoding="utf-8"))
        meta["refs"] = ["../../.ssh/id_rsa"]
        meta_path.write_text(_json.dumps(meta), encoding="utf-8")
        with pytest.raises(SystemExit) as e:
            assets.load_asset("hero")
        assert "非法路径" in str(e.value), "被篡改的 meta.json 不得读库外文件"
