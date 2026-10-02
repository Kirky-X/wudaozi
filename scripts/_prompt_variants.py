#!/usr/bin/env python3
"""wudaozi —— prompt 变体展开引擎（纯 stdlib）。

批量出图不该是"同一 prompt 复制 N 张"（--count>1 的同质图问题）。本模块把含
变体语法的 instruction 展开成 N 份刻意差异的 prompt，配合 agnes/kolors 的
--count 使用，每个 index 渲染一份非重复变体：

- ``{a|b|c}``  花括号枚举：一个取值位置，候选用竖线分隔
- ``{_name_}`` 词库引用：展开为 references/wordbanks/<name>.txt 的每行一个词

展开空间 = 各取值位置的笛卡尔积；抽样用 random.sample 非重复抽取，组合数
不足 N 时有放回补齐并 stderr 告警——过采样必须显性化（规则11）。抽样结果由
调用方传入的 random.Random 决定（云端不可复现出图，变体抽样同哲学：不给 seed）。

语法示例::

    一只{橘色|黑色|白色}猫，{_lighting_}，电影感
    python3 agnes.py t2i -i "..." --count 4

无变体语法时返回 N 份原样（与历史行为一致）；count=1 且含语法时渲染 1 个随机变体。
"""
# ponytail: 枚举/抽样是确定性逻辑（给定 rng 可复现），不交给模型决策（规则5）。

import random
import re
import sys
from pathlib import Path

import _cloud_common as _cc

WORDBANKS_DIR = Path(__file__).resolve().parent.parent / "references" / "wordbanks"

_SLOT_RE = re.compile(r"\{([^{}]*)\}")
_VARIANT_MARK = re.compile(r"\{[^{}]*\|[^{}]*\}|\{_[^{}_]*_\}")


def load_wordbank(name: str, wordbanks_dir: Path = WORDBANKS_DIR) -> list:
    """词库 → 非空、非 # 注释行列表。词库缺失/为空显性报错（引用拼错词库名是参数错误）。"""
    p = Path(wordbanks_dir) / f"{name}.txt"
    if not p.is_file():
        _cc.fail(
            "invalid_param",
            f"词库不存在: {p}",
            f"  → 可用词库: {sorted(x.stem for x in Path(wordbanks_dir).glob('*.txt')) or '(无)'}",
        )
    words = [
        ln.strip()
        for ln in p.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.lstrip().startswith("#")
    ]
    if not words:
        _cc.fail("invalid_param", f"词库为空: {p}")
    return words


def parse_slots(instruction: str, wordbanks_dir: Path = WORDBANKS_DIR) -> list:
    """instruction → 段列表：("lit", 文本) 或 ("choice", [候选...])。

    - {a|b|c} → choice；{_name_} → choice（词库展开）
    - 不含 | 且非 _name_ 引用的 {...}（含 {}）是普通字面量（JSON 示例等），原样保留
    - 空候选（{a||b}）显性报错
    """
    segments = []
    pos = 0
    for m in _SLOT_RE.finditer(instruction):
        inner = m.group(1)
        name = re.fullmatch(r"_([A-Za-z0-9_-]+)_", inner)
        if not name and "|" not in inner:
            continue  # 普通花括号不是变体语法：不切段，留在字面量里
        if m.start() > pos:
            segments.append(("lit", instruction[pos:m.start()]))
        if name:
            segments.append(("choice", load_wordbank(name.group(1), wordbanks_dir)))
        else:
            options = [o.strip() for o in inner.split("|")]
            if any(not o for o in options):
                _cc.fail("invalid_param", f"变体枚举含空候选: {{{inner}}}")
            segments.append(("choice", options))
        pos = m.end()
    if pos < len(instruction):
        segments.append(("lit", instruction[pos:]))
    return segments


def combo_count(segments: list) -> int:
    """展开空间大小：各 choice 段候选数的乘积（无 choice 段 = 1）。"""
    count = 1
    for kind, value in segments:
        if kind == "choice":
            count *= len(value)
    return count


def has_variant_syntax(instruction: str) -> bool:
    """是否含变体语法（{a|b|c} 或 {_词库_}）——普通 {...} 不算。"""
    return bool(_VARIANT_MARK.search(instruction))


def sample_variants(instruction: str, n: int, rng: random.Random, wordbanks_dir: Path = WORDBANKS_DIR, segments: list | None = None) -> list:
    """展开并抽 n 份非重复变体；组合数不足 n 时有放回补齐 + stderr 告警。

    segments 可传调用方已解析的段列表（避免同 instruction 重复解析/重复读词库）。
    返回长度恒为 n 的列表；无变体语法时为 n 份原样 instruction。
    """
    segments = segments if segments is not None else parse_slots(instruction, wordbanks_dir)
    if not any(kind == "choice" for kind, _ in segments):
        return [instruction] * n
    # 钳制到 ssize_t 安全范围：rng.sample(range(space)) 在 space > sys.maxsize 时抛
    # OverflowError（裸 traceback 违反显性报错约定）。n ≤ 8，钳制对抽样无实际影响。
    space = min(combo_count(segments), 2 ** 62)
    if space >= n:
        picks = rng.sample(range(space), n)
    else:
        picks = rng.choices(range(space), k=n)
        print(
            f"[WARN] 变体组合空间 {space} < --count {n}，{n - space} 份为重复组合（有放回补齐）",
            file=sys.stderr,
        )

    def render(pick: int) -> str:
        out = []
        for kind, value in segments:
            if kind == "lit":
                out.append(value)
            else:
                out.append(value[pick % len(value)])
                pick //= len(value)
        return "".join(out)

    return [render(p) for p in picks]


if __name__ == "__main__":
    # 自检：纯函数验证，不打网络
    print("== wudaozi _prompt_variants self-check ==")
    assert has_variant_syntax("一只{橘|黑}猫")
    assert not has_variant_syntax("普通 {字面量}")
    assert combo_count(parse_slots("a{1|2|3}b{c}")) == 3, "字面量 {} 不进空间"
    segs = parse_slots("{a|b}")
    assert combo_count(segs) == 2
    got = sample_variants("{a|b}", 2, random.Random(42))
    assert sorted(got) == ["a", "b"], "空间足够时必须非重复"
    assert sample_variants("普通", 3, random.Random(1)) == ["普通"] * 3
    assert len(sample_variants("{a}", 3, random.Random(1))) == 3
    # 词库 # 注释行不入候选;空间超 ssize_t 钳制不崩
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        from pathlib import Path as _P

        wb = _P(td) / "cmt.txt"
        wb.write_text("# 注释行\nsun\n\n# 另一条注释\nrain\n", encoding="utf-8")
        assert load_wordbank("cmt", _P(td)) == ["sun", "rain"]
        big = _P(td) / "big.txt"
        big.write_text("\n".join(f"w{i}" for i in range(300)) + "\n", encoding="utf-8")
        got = sample_variants("{_big_}" * 8, 2, random.Random(1), _P(td))
        assert len(got) == 2, "组合空间 300^8 远超 ssize_t:必须钳制抽样而非 OverflowError"
    print("  self-check PASS")
