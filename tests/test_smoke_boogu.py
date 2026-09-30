#!/usr/bin/env python3
"""boogu.py 冒烟测试（离线）——模型矩阵路由 + 参数默认值 + 硬约束校验。

与 scripts/test_boogu.py 互补：冒烟级钉死 (mode,turbo,quant) 路由、
turbo/base 默认 steps/CFG 分叉、turbo text_guidance=1.0 硬约束、CLI dry-run。
跑法：python3 -m pytest tests -q
"""
import os
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import boogu  # noqa: E402

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "boogu.py"


def _ns(**kw):
    base = dict(mode="t2i", instruction="an orange cat under moonlight, cinematic",
                negative_instruction=None, input=None, aspect=None, height=None,
                width=None, turbo=False, quantized=False, seed=42, steps=None,
                text_guidance=None, dmd_sigma=None, device="cuda:0",
                output_dir=None, dry_run=False)
    base.update(kw)
    return SimpleNamespace(**base)


class TestModelMatrix(unittest.TestCase):
    def test_eight_combinations(self):
        self.assertEqual(len(boogu.MATRIX), 8)

    def test_fp8_suffix_matches_flag(self):
        # B2：fp8 后缀必须与 quantized 标志一致，错位会加载错权重分支
        for (mode, turbo, quant), name in boogu.MATRIX.items():
            self.assertEqual(name.endswith("-fp8"), quant, name)

    def test_turbo_flag_matches_model_name(self):
        for (mode, turbo, quant), name in boogu.MATRIX.items():
            self.assertEqual("Turbo" in name, turbo, name)

    def test_turbo_script_selection(self):
        self.assertEqual(boogu.SCRIPT_FOR_TURBO[False], "inference.py")
        self.assertEqual(boogu.SCRIPT_FOR_TURBO[True], "inference_turbo.py")


class TestDefaults(unittest.TestCase):
    def test_align16_floor(self):
        self.assertEqual(boogu.align16(1365), 1360)
        self.assertEqual(boogu.align16(17), 16)
        self.assertEqual(boogu.align16(0), 16)

    def test_gen_seed_range(self):
        self.assertTrue(0 <= boogu.gen_seed() <= 2**31 - 1)

    def test_base_defaults_50_steps_cfg4(self):
        args = boogu.build_args(_ns(), 1024, 1024, Path("/tmp/o.png"))
        i = args.index("--num_inference_steps")
        self.assertEqual(args[i + 1], "50")
        self.assertEqual(args[args.index("--text_guidance_scale") + 1], "4.0")

    def test_turbo_defaults_4_steps_cfg1(self):
        args = boogu.build_args(_ns(turbo=True), 1024, 1024, Path("/tmp/o.png"))
        self.assertEqual(args[args.index("--num_inference_steps") + 1], "4")
        self.assertEqual(args[args.index("--text_guidance_scale") + 1], "1.0")
        # turbo t2i 的 DMD sigma 默认 0.001
        self.assertEqual(args[args.index("--dmd_conditioning_sigma") + 1], "0.001")

    def test_turbo_ti2i_sigma_zero(self):
        args = boogu.build_args(_ns(turbo=True, mode="ti2i", input="p.png"),
                                1024, 1024, Path("/tmp/o.png"))
        self.assertEqual(args[args.index("--dmd_conditioning_sigma") + 1], "0.0")

    def test_negative_default_passthrough(self):
        # 不传 → 透传内置模板（防 LLM 忘记）
        args = boogu.build_args(_ns(), 1024, 1024, Path("/tmp/o.png"))
        self.assertEqual(args[args.index("--negative_instruction") + 1], boogu.DEFAULT_NEGATIVE)

    def test_negative_empty_string_disables(self):
        # 空串 → 显式禁用，不透传
        args = boogu.build_args(_ns(negative_instruction=""), 1024, 1024, Path("/tmp/o.png"))
        self.assertNotIn("--negative_instruction", args)

    def test_quantized_flag(self):
        args = boogu.build_args(_ns(quantized=True), 1024, 1024, Path("/tmp/o.png"))
        self.assertEqual(args[args.index("--use_fp8_weights") + 1], "True")

    def test_max_input_pixels_matches_size(self):
        args = boogu.build_args(_ns(), 1360, 1024, Path("/tmp/o.png"))
        self.assertEqual(args[args.index("--max_input_image_pixels") + 1],
                         str(1360 * 1024))


class TestHardConstraints(unittest.TestCase):
    def test_ti2i_requires_input(self):
        with self.assertRaises(SystemExit):
            boogu.validate_args(_ns(mode="ti2i", input=None))

    def test_turbo_text_guidance_must_be_1(self):
        # B12：DMD 学生推理硬约束
        with self.assertRaises(SystemExit):
            boogu.validate_args(_ns(turbo=True, text_guidance=4.0))

    def test_resolve_size_aligns_and_limits(self):
        self.assertEqual(boogu.resolve_size(_ns(height=1365, width=1024)), (1360, 1024))
        with self.assertRaises(SystemExit):
            boogu.resolve_size(_ns(height=4096, width=4096))  # 超模型 2048 上限

    def test_single_dimension_exits(self):
        with self.assertRaises(SystemExit):
            boogu.resolve_size(_ns(height=800))


class TestOutputNaming(unittest.TestCase):
    def test_name_contains_variant_seed_size(self):
        out = boogu.resolve_output(_ns(turbo=True, quantized=True), 1360, 1024)
        self.assertEqual(out.parent.name, "boogu-output")
        self.assertTrue(out.name.startswith("boogu_t2i_turbo_fp8_42_1024x1360_"), out.name)


class TestCliSmoke(unittest.TestCase):
    """② CLI 冒烟：dry-run 跳过资源检测，无 GPU/模型也能走通参数组装。"""

    def _run(self, *args, cwd=None):
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            capture_output=True, text=True, timeout=60, cwd=cwd,
        )

    def test_help(self):
        r = self._run("--help")
        self.assertEqual(r.returncode, 0)
        self.assertIn("--turbo", r.stdout)
        self.assertIn("--quantized", r.stdout)

    def test_dry_run_ok(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            r = self._run("t2i", "-i", "an orange cat", "--seed", "42",
                          "--dry-run", cwd=td)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("[DRY-RUN]", r.stderr)
            self.assertIn("inference.py", r.stderr)  # base 走官方 inference.py

    def test_dry_run_turbo_uses_turbo_script(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            r = self._run("t2i", "-i", "an orange cat", "--turbo",
                          "--dry-run", cwd=td)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("inference_turbo.py", r.stderr)

    def test_missing_instruction_rejected(self):
        r = self._run("t2i")
        self.assertNotEqual(r.returncode, 0)

    def test_turbo_cfg_violation_exits(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            r = self._run("t2i", "-i", "an orange cat", "--turbo",
                          "--text-guidance", "4.0", "--dry-run", cwd=td)
            self.assertEqual(r.returncode, 1)
            self.assertIn("turbo", r.stderr)

    def test_dry_run_auto_seed_echoed(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            r = self._run("t2i", "-i", "an orange cat", "--dry-run", cwd=td)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("generated seed=", r.stderr)


if __name__ == "__main__":
    unittest.main()
