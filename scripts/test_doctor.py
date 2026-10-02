#!/usr/bin/env python3
"""wudaozi doctor.py 单元测试 —— 就绪自检的判定与报告（只读，不打 API）。

覆盖：key 探测 / boogu 栈检测（monkeypatch 路径）/ 矩阵构建 / 路由结论 / 退出码语义。
跑法：python3 -m pytest scripts/test_doctor.py -v
"""
# ponytail: GPU 探测真实调用 nvidia-smi（缺失/被屏蔽都只是报告项，不影响断言）。

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import boogu  # noqa: E402
import doctor  # noqa: E402


def _no_keys(monkeypatch):
    monkeypatch.delenv("AGNES_API_KEY", raising=False)
    monkeypatch.delenv("AIPING_API_KEY", raising=False)


def _boogu_ready(tmp_path, monkeypatch, models=("Boogu-Image-0.1-Base",)):
    """把 boogu 栈指向 tmp 伪环境：目录/venv/模型全就绪。"""
    root = tmp_path / "Boogu-Image"
    (root / ".venv" / "bin").mkdir(parents=True)
    (root / ".venv" / "bin" / "python").write_text("")
    for m in models:
        (root / "models" / m).mkdir(parents=True)
    monkeypatch.setattr(boogu, "BOOGU_DIR", root)
    monkeypatch.setattr(boogu, "VENV_PYTHON", root / ".venv" / "bin" / "python")
    monkeypatch.setattr(boogu, "MODELS_DIR", root / "models")


# ---------- key 探测 ----------
class TestCheckKeys:
    def test_both_set(self, monkeypatch):
        monkeypatch.setenv("AGNES_API_KEY", "agn-x")
        monkeypatch.setenv("AIPING_API_KEY", "QC-x")
        assert doctor.check_keys() == {"AGNES_API_KEY": True, "AIPING_API_KEY": True}

    def test_empty_value_counts_as_missing(self, monkeypatch):
        _no_keys(monkeypatch)
        monkeypatch.setenv("AGNES_API_KEY", "")
        keys = doctor.check_keys()
        assert keys["AGNES_API_KEY"] is False


# ---------- boogu 栈检测 ----------
class TestCheckBoogu:
    def test_missing_everything(self, tmp_path, monkeypatch):
        monkeypatch.setattr(boogu, "BOOGU_DIR", tmp_path / "nope")
        monkeypatch.setattr(boogu, "VENV_PYTHON", tmp_path / "nope" / "python")
        monkeypatch.setattr(boogu, "MODELS_DIR", tmp_path / "nope" / "models")
        bg = doctor.check_boogu()
        assert bg["ok"] is False and bg["models"] == []

    def test_ready_stack(self, tmp_path, monkeypatch):
        _boogu_ready(tmp_path, monkeypatch)
        bg = doctor.check_boogu()
        assert bg["ok"] is True
        assert bg["dir"] and bg["venv"]
        assert "Boogu-Image-0.1-Base" in bg["models"]


# ---------- 矩阵与路由 ----------
class TestMatrixAndRoute:
    def test_agnes_key_only(self, monkeypatch):
        _no_keys(monkeypatch)
        monkeypatch.setenv("AGNES_API_KEY", "agn-x")
        bg = {"ok": False, "gpu": False, "gpu_desc": "", "models": []}
        matrix = doctor.build_matrix(doctor.check_keys(), bg)
        by_cap = dict(matrix)
        assert by_cap["t2i"][0][:2] == ("agnes", True)
        assert by_cap["t2i"][1][:2] == ("kolors", False)
        assert by_cap["ti2i"][1][1] is False  # boogu 不可用
        assert by_cap["video"][0][1] is True

    def test_boogu_ready_gives_local_path(self, tmp_path, monkeypatch):
        _no_keys(monkeypatch)
        _boogu_ready(tmp_path, monkeypatch)
        bg = doctor.check_boogu()
        matrix = doctor.build_matrix(doctor.check_keys(), bg)
        by_cap = dict(matrix)
        t2i = dict((p[0], p[1]) for p in by_cap["t2i"])
        ti2i = dict((p[0], p[1]) for p in by_cap["ti2i"])
        assert t2i["boogu"] is True
        assert ti2i["boogu"] is False, "只装了 Base/Turbo 时 ti2i(Edit 系)应不可用"

    def test_route_with_agnes(self, monkeypatch):
        _no_keys(monkeypatch)
        monkeypatch.setenv("AGNES_API_KEY", "agn-x")
        s = doctor.route_conclusion(doctor.check_keys(), {"ok": False, "gpu": False, "gpu_desc": "", "models": []})
        assert "默认 agnes" in s

    def test_route_nothing(self, monkeypatch):
        _no_keys(monkeypatch)
        s = doctor.route_conclusion(doctor.check_keys(), {"ok": False, "gpu": False, "gpu_desc": "", "models": []})
        assert "AGNES_API_KEY" in s and "先配置" in s

    def test_route_aiping_plus_boogu(self, tmp_path, monkeypatch):
        _no_keys(monkeypatch)
        monkeypatch.setenv("AIPING_API_KEY", "QC-x")
        _boogu_ready(tmp_path, monkeypatch)
        s = doctor.route_conclusion(doctor.check_keys(), doctor.check_boogu())
        assert "kolors" in s and "boogu" in s


# ---------- 退出码语义 ----------
class TestMainExitCodes:
    def test_nothing_usable_exits_1(self, tmp_path, monkeypatch, capsys):
        _no_keys(monkeypatch)
        monkeypatch.setattr(boogu, "BOOGU_DIR", tmp_path / "nope")
        monkeypatch.setattr(boogu, "VENV_PYTHON", tmp_path / "nope" / "python")
        monkeypatch.setattr(boogu, "MODELS_DIR", tmp_path / "nope" / "models")
        assert doctor.main() == 1
        assert "matrix" in capsys.readouterr().out

    def test_agnes_key_exits_0(self, monkeypatch):
        _no_keys(monkeypatch)
        monkeypatch.setenv("AGNES_API_KEY", "agn-x")
        assert doctor.main() == 0

    def test_report_lists_all_capabilities(self, monkeypatch, capsys):
        _no_keys(monkeypatch)
        monkeypatch.setenv("AGNES_API_KEY", "agn-x")
        doctor.main()
        out = capsys.readouterr().out
        for cap in ("t2i", "ti2i", "vision", "video"):
            assert cap in out, f"矩阵必须覆盖 {cap}"
        assert "[route]" in out
