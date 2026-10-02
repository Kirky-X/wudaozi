#!/usr/bin/env python3
"""wudaozi _prompt_variants.py 单元测试 —— 变体展开引擎的行为契约。

覆盖：语法识别 / 段解析 / 组合空间 / 非重复抽样 / 过采样告警 / 词库加载。
跑法：python3 -m pytest scripts/test_prompt_variants.py -v
"""
# ponytail: 抽样给定 rng 必须可复现——确定性是规则5，不是可选项。

import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import _cloud_common as cc  # noqa: E402
import _prompt_variants as pv  # noqa: E402


# ---------- 语法识别 ----------
class TestHasVariantSyntax:
    def test_enum_detected(self):
        assert pv.has_variant_syntax("一只{橘|黑}猫")
        assert pv.has_variant_syntax("{_lighting_}")

    def test_plain_brace_not_variant(self):
        assert not pv.has_variant_syntax("JSON {like} this")
        assert not pv.has_variant_syntax("无花括号")

    def test_wordbank_detected(self, tmp_path):
        (tmp_path / "demo.txt").write_text("a\nb\n", encoding="utf-8")
        assert pv.parse_slots("{_demo_}", tmp_path)[0] == ("choice", ["a", "b"])


# ---------- 段解析 ----------
class TestParseSlots:
    def test_enum_segments(self):
        segs = pv.parse_slots("a{1|2}b")
        assert segs == [("lit", "a"), ("choice", ["1", "2"]), ("lit", "b")]

    def test_plain_brace_is_literal(self):
        segs = pv.parse_slots("JSON {like}")
        assert segs == [("lit", "JSON {like}")]

    def test_empty_alternative_exits(self):
        with pytest.raises(SystemExit) as e:
            pv.parse_slots("{a||b}")
        assert "code=invalid_param" in str(e.value)

    def test_empty_brace_is_literal(self):
        # {} 无 | 且非词库引用：按字面量保留（JSON 示例等场景）
        assert pv.parse_slots("x{}y") == [("lit", "x{}y")]

    def test_wordbank_missing_exits(self, tmp_path):
        with pytest.raises(SystemExit) as e:
            pv.parse_slots("{_nope_}", tmp_path)
        assert "词库不存在" in str(e.value)

    def test_wordbank_skips_blank_lines(self, tmp_path):
        (tmp_path / "wb.txt").write_text("one\n\n  \ntwo\n", encoding="utf-8")
        assert pv.load_wordbank("wb", tmp_path) == ["one", "two"]

    def test_wordbank_empty_exits(self, tmp_path):
        (tmp_path / "empty.txt").write_text("\n\n", encoding="utf-8")
        with pytest.raises(SystemExit):
            pv.load_wordbank("empty", tmp_path)


# ---------- 组合空间 ----------
class TestComboCount:
    def test_product_of_choices(self):
        segs = pv.parse_slots("{a|b|c}{x|y}")
        assert pv.combo_count(segs) == 6

    def test_literal_only_is_one(self):
        assert pv.combo_count(pv.parse_slots("plain text")) == 1

    def test_wordbank_counts(self, tmp_path):
        (tmp_path / "w.txt").write_text("1\n2\n3\n", encoding="utf-8")
        assert pv.combo_count(pv.parse_slots("{_w_}{a|b}", tmp_path)) == 6


# ---------- 抽样 ----------
class TestSampleVariants:
    def test_no_syntax_returns_n_copies(self):
        assert pv.sample_variants("普通", 3, random.Random(1)) == ["普通"] * 3

    def test_space_ge_n_means_no_repeat(self):
        got = pv.sample_variants("{a|b|c|d}", 3, random.Random(42))
        assert len(got) == 3 and len(set(got)) == 3

    def test_deterministic_given_rng(self):
        a = pv.sample_variants("{a|b|c}", 2, random.Random(7))
        b = pv.sample_variants("{a|b|c}", 2, random.Random(7))
        assert a == b, "同 rng 同结果（可复现）"

    def test_multi_slot_combination_rendering(self):
        got = pv.sample_variants("{a|b}{1|2}", 4, random.Random(0))
        assert set(got) == {"a1", "a2", "b1", "b2"}, "4 次非重复抽样覆盖全部笛卡尔积"

    def test_oversample_warns_loudly(self, capsys):
        got = pv.sample_variants("{a|b}", 5, random.Random(1))
        assert len(got) == 5
        assert "重复组合" in capsys.readouterr().err, "过采样必须显性告警（规则11）"

    def test_two_choices_nondecreasing(self, tmp_path):
        (tmp_path / "m.txt").write_text("安静的\n热闹的\n", encoding="utf-8")
        got = pv.sample_variants("一只{橘|黑}猫，{_m_}", 4, random.Random(3), tmp_path)
        assert len(set(got)) == 4, "2×2 空间抽 4 份必须全不重复"


# ---------- 审查修复回归:词库注释过滤 + 空间溢出钳制 ----------
class TestReviewFixes:
    def test_wordbank_comment_lines_filtered(self, tmp_path):
        (tmp_path / "c.txt").write_text("# 头注释\nsun\n\n  # 缩进注释\nrain\n", encoding="utf-8")
        assert pv.load_wordbank("c", tmp_path) == ["sun", "rain"]

    def test_real_wordbanks_have_no_comment_candidates(self):
        # 真实词库快照断言:候选里不得出现 # 注释行(此前 # 整行被当词抽中)
        for name in ("lighting", "mood"):
            words = pv.load_wordbank(name, pv.WORDBANKS_DIR)
            assert len(words) >= 2, name
            assert all(not w.startswith("#") for w in words), name

    def test_oversized_combo_space_clamped_not_crash(self, tmp_path):
        # 300 行词库 × 8 槽 = 300^8 > sys.maxsize:rng.sample 曾抛 OverflowError 裸 traceback
        (tmp_path / "big.txt").write_text("\n".join(f"w{i}" for i in range(300)) + "\n", encoding="utf-8")
        got = pv.sample_variants("{_big_}" * 8, 2, random.Random(1), tmp_path)
        assert len(got) == 2 and all(g.startswith("w") for g in got)

    def test_segments_reuse_equivalence(self, tmp_path):
        (tmp_path / "w.txt").write_text("a\nb\n", encoding="utf-8")
        instr = "{_w_}{1|2}"
        segs = pv.parse_slots(instr, tmp_path)
        direct = pv.sample_variants(instr, 2, random.Random(9), tmp_path)
        reused = pv.sample_variants(instr, 2, random.Random(9), tmp_path, segments=segs)
        assert direct == reused, "段复用与直接调用结果一致"
