#!/usr/bin/env python3
"""wudaozi boogu.py 单元测试 —— 验证纯函数（不依赖 GPU/模型/官方脚本）。

覆盖：align16 / gen_seed / resolve_size / build_args / validate_args / 矩阵一致性。
跑法：python3 -m pytest scripts/test_boogu.py -v
"""
# ponytail: 只测决定正确性的纯函数（查找表/校验）；main/subprocess/check_resources
# 是副作用函数，无 GPU 无法跑，YAGNI。核心纯函数覆盖率 100%。

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import boogu  # noqa: E402


# ---------- align16 ----------
class TestAlign16:
    def test_exact_multiple(self):
        assert boogu.align16(1024) == 1024
        assert boogu.align16(16) == 16

    def test_round_down(self):
        assert boogu.align16(1365) == 1360
        assert boogu.align16(17) == 16
        assert boogu.align16(31) == 16

    def test_below_floor(self):
        # B10 边界：负数/0 被 max(16,...) 兜底
        assert boogu.align16(0) == 16
        assert boogu.align16(-100) == 16

    def test_large(self):
        assert boogu.align16(2048) == 2048
        assert boogu.align16(2049) == 2048


# ---------- gen_seed ----------
class TestGenSeed:
    def test_range(self):
        for _ in range(100):
            s = boogu.gen_seed()
            assert 0 <= s <= 2**31 - 1


# ---------- resolve_size ----------
class TestResolveSize:
    def _ns(self, **kw):
        base = dict(aspect=None, height=None, width=None)
        base.update(kw)
        return SimpleNamespace(**base)

    def test_aspect_preset(self):
        assert boogu.resolve_size(self._ns(aspect="1:1")) == (1024, 1024)
        # 9:16 竖屏：H=1824 W=1024（修正横竖标反后）
        assert boogu.resolve_size(self._ns(aspect="9:16")) == (1824, 1024)
        # 16:9 横屏：H=1024 W=1824
        assert boogu.resolve_size(self._ns(aspect="16:9")) == (1024, 1824)
        assert boogu.resolve_size(self._ns(aspect="3:4")) == (1360, 1024)  # 竖

    def test_both_hw(self):
        assert boogu.resolve_size(self._ns(height=1360, width=1024)) == (1360, 1024)

    def test_both_hw_align_down(self):
        assert boogu.resolve_size(self._ns(height=1365, width=1024)) == (1360, 1024)

    def test_default_1_1(self):
        assert boogu.resolve_size(self._ns()) == (1024, 1024)

    def test_single_height_exits(self):
        # B1：单传 height 必须 sys.exit（不再静默退回 1:1）
        with pytest.raises(SystemExit):
            boogu.resolve_size(self._ns(height=1360))

    def test_single_width_exits(self):
        with pytest.raises(SystemExit):
            boogu.resolve_size(self._ns(width=1024))

    def test_over_2048_exits(self):
        with pytest.raises(SystemExit):
            boogu.resolve_size(self._ns(height=4096, width=4096))

    def test_aspect_priority_over_hw(self):
        # aspect 优先于 height/width（删 argparse 互斥组后由 resolve_size 统一处理）
        assert boogu.resolve_size(self._ns(aspect="1:1", height=999, width=999)) == (
            1024,
            1024,
        )


# ---------- build_args ----------
def _build_ns(**kw):
    base = dict(
        mode="t2i",
        turbo=False,
        quantized=False,
        instruction="测试 instruction",
        negative_instruction=None,
        input=None,
        seed=42,
        steps=None,
        text_guidance=None,
        dmd_sigma=None,
        device="cuda:0",
    )
    base.update(kw)
    return SimpleNamespace(**base)


class TestBuildArgs:
    def test_t2i_base_defaults(self):
        args = boogu.build_args(_build_ns(), 1024, 1024, Path("/tmp/out.png"))
        assert args[args.index("--num_inference_steps") + 1] == "50"
        assert args[args.index("--text_guidance_scale") + 1] == "4.0"
        assert "--image_guidance_scale" not in args  # t2i 不需要 image_cfg

    def test_t2i_turbo_defaults(self):
        args = boogu.build_args(_build_ns(turbo=True), 1024, 1024, Path("/tmp/out.png"))
        assert args[args.index("--num_inference_steps") + 1] == "4"
        assert args[args.index("--text_guidance_scale") + 1] == "1.0"
        assert args[args.index("--image_guidance_scale") + 1] == "1.0"
        assert args[args.index("--dmd_conditioning_sigma") + 1] == str(
            boogu.TURBO_T2I_SIGMA
        )
        # A7：None → 默认 negative 透传
        assert args[args.index("--negative_instruction") + 1] == boogu.DEFAULT_NEGATIVE

    def test_ti2i_input_passed(self):
        args = boogu.build_args(
            _build_ns(mode="ti2i", input="photo.jpg"),
            1024,
            1024,
            Path("/tmp/out.png"),
        )
        assert args[args.index("--input_image_paths") + 1] == "photo.jpg"
        assert args[args.index("--image_guidance_scale") + 1] == "1.0"

    def test_negative_empty_not_passed(self):
        # B5：空字符串 → 明确禁用，不透传
        args = boogu.build_args(
            _build_ns(negative_instruction=""),
            1024,
            1024,
            Path("/tmp/out.png"),
        )
        assert "--negative_instruction" not in args

    def test_negative_custom_passed(self):
        args = boogu.build_args(
            _build_ns(negative_instruction="水印, 文字"),
            1024,
            1024,
            Path("/tmp/out.png"),
        )
        assert args[args.index("--negative_instruction") + 1] == "水印, 文字"

    def test_quantized_fp8_flag(self):
        args = boogu.build_args(
            _build_ns(quantized=True), 1024, 1024, Path("/tmp/o.png")
        )
        assert args[args.index("--use_fp8_weights") + 1] == "True"

    def test_user_steps_override(self):
        args = boogu.build_args(_build_ns(steps=30), 1024, 1024, Path("/tmp/o.png"))
        assert args[args.index("--num_inference_steps") + 1] == "30"

    def test_ti2i_turbo_empty_cfg(self):
        # ti2i turbo 应补 empty_instruction_guidance_scale 0.0
        args = boogu.build_args(
            _build_ns(mode="ti2i", turbo=True, input="x.jpg"),
            1024,
            1024,
            Path("/tmp/o.png"),
        )
        assert args[args.index("--empty_instruction_guidance_scale") + 1] == "0.0"


# ---------- validate_args ----------
class TestValidateArgs:
    def _ns(self, **kw):
        base = dict(
            mode="t2i",
            turbo=False,
            instruction="一只橘色英短猫蜷缩在月光下的窗台上眼神温柔电影感胶片颗粒高细节专业级",
            input=None,
            steps=None,
            text_guidance=None,
        )
        base.update(kw)
        return SimpleNamespace(**base)

    def test_t2i_ok(self):
        boogu.validate_args(self._ns())

    def test_ti2i_without_input_exits(self):
        with pytest.raises(SystemExit):
            boogu.validate_args(self._ns(mode="ti2i"))

    def test_ti2i_with_input_ok(self):
        boogu.validate_args(self._ns(mode="ti2i", input="x.png"))

    def test_turbo_wrong_cfg_exits(self):
        # B12：turbo 的 text_guidance 必须 = 1.0
        with pytest.raises(SystemExit):
            boogu.validate_args(self._ns(turbo=True, text_guidance=4.0))

    def test_turbo_correct_cfg_ok(self):
        boogu.validate_args(self._ns(turbo=True, text_guidance=1.0))


# ---------- 矩阵与常量一致性 ----------
class TestMatrix:
    def test_eight_combinations(self):
        assert len(boogu.MATRIX) == 8

    def test_fp8_models_endwith_fp8(self):
        # B2：fp8 标志与模型目录名必须一致
        for (mode, turbo, quantized), name in boogu.MATRIX.items():
            assert name.endswith("-fp8") == quantized, (mode, turbo, quantized)

    def test_all_presets_align16(self):
        for h, w in boogu.ASPECT_RATIOS.values():
            assert h % 16 == 0 and w % 16 == 0
