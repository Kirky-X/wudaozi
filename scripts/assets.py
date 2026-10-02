#!/usr/bin/env python3
"""wudaozi —— 角色/画风命名资产库（纯 stdlib）。

IP 角色与固定画风的复用痛点：每次都要靠 prompt 重新文字描述，且参考图散落在
输出目录里。本模块把"满意的图"钉成命名资产，之后 agnes/boogu ti2i 用 --ref
直接引用，免重描述、防原文件被清理：

    python3 assets.py add hero --kind character --ref shot1.png shot2.png --note "主角定妆"
    python3 assets.py add ink --kind style --ref ref.png       # 画风：只借美学勿抄主体
    python3 assets.py add hero --kind character --from-last    # 刚生成且满意的一张直接钉
    python3 assets.py list / show hero / remove hero

存储：~/.config/wudaozi/assets/<name>/（WUDAOZI_ASSETS_DIR 覆盖，测试用），
参考图**拷贝入库**——引用原路径会在原文件删除/移动后静默失效，拷贝消灭这一类。

kind 语义（与 --ref-role 对齐）：
- character：参考图即主体本身（复现同一角色）→ 默认 ref-role=subject
- style：参考图只是画风/美学参照（勿抄其内容）→ 默认 ref-role=style

单一参考图上限 4 张（过多参考图稀释模型对每张的权重）；超限在消费端显式告警。
"""
# ponytail: 资产存取是确定性 CRUD（规则5）；路径拼接拒绝 ../ 穿越与任意字符名。

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
REF_CAP = 4
KINDS = ("character", "style")
# --from-last 扫描的产物目录（生成→喜欢→钉住→复用 闭环的"生成"端）
OUTPUT_DIRS = ("agnes-output", "kolors-output", "boogu-output")
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")


def store_root() -> Path:
    """资产库根目录；WUDAOZI_ASSETS_DIR 覆盖（测试/多库隔离）。
    默认 POSIX ~/.config、Windows %APPDATA%（规则25：平台惯例）。"""
    if os.environ.get("WUDAOZI_ASSETS_DIR"):
        return Path(os.environ["WUDAOZI_ASSETS_DIR"])
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
        return base / "wudaozi" / "assets"
    return Path.home() / ".config" / "wudaozi" / "assets"


def check_name(name: str) -> str:
    if not NAME_RE.match(name):
        sys.exit(f"[ERROR] 资产名只允许字母/数字/-/_（1-64 位）: {name!r}")
    return name


def asset_dir(name: str) -> Path:
    return store_root() / check_name(name)


def load_asset(name: str) -> dict:
    """读资产元数据。不存在 → 显性报错并列出可用资产（引用拼错是参数错误）。
    meta.json 中被篡改的 refs 路径（../ 穿越等）显性拒绝，不读库外文件。"""
    d = asset_dir(name)
    meta_path = d / "meta.json"
    if not meta_path.is_file():
        available = sorted(p.name for p in store_root().iterdir() if p.is_dir()) if store_root().is_dir() else []
        sys.exit(
            f"[ERROR] 资产不存在: {name}\n"
            f"  → 可用资产: {available or '(空，先 asset add)'}"
        )
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    refs_dir = d / "refs"
    for r in meta.get("refs", []):
        if (refs_dir / r).parent != refs_dir:
            sys.exit(
                f"[ERROR] meta.json refs 含非法路径（库可能被篡改）: {r!r}\n"
                f"  → 删除该资产后重新 asset add"
            )
    meta["refs"] = [refs_dir / r for r in meta.get("refs", [])]
    return meta


def resolve_refs(names: list, cap: int = REF_CAP) -> list:
    """多个资产名 → 扁平参考图路径列表（上限 cap，超限告警截断，显性化不静默）。"""
    refs = []
    for n in names:
        refs.extend(load_asset(n)["refs"])
    if len(refs) > cap:
        print(
            f"[WARN] 参考图 {len(refs)} 张 > 上限 {cap}，仅取前 {cap} 张（过多会稀释每张权重）",
            file=sys.stderr,
        )
        refs = refs[:cap]
    missing = [str(p) for p in refs if not p.is_file()]
    if missing:
        sys.exit(
            f"[ERROR] 资产参考图文件缺失（库曾被手动清理？）: {missing}\n"
            f"  → 重新 asset add 该资产，或 asset remove 后重建"
        )
    return refs


def newest_generated(directory: Path | None = None) -> Path:
    """最近一次生成的图片（mtime 最新）；没有 → 显性报错，不猜。"""
    candidates = []
    if directory is not None:
        roots = [directory]
    else:
        roots = [Path.cwd() / d for d in OUTPUT_DIRS]
    for root in roots:
        if not root.is_dir():
            continue
        for p in root.iterdir():
            if p.suffix.lower() in IMAGE_EXTS and p.is_file():
                candidates.append(p)
    if not candidates:
        sys.exit(
            "[ERROR] --from-last 未找到任何生成产物"
            f"（扫描: {', '.join(str(r) for r in (roots if directory is None else [directory]))}）\n"
            "  → 先出一张图，或用 --ref 指定文件"
        )
    return max(candidates, key=lambda p: p.stat().st_mtime)


def cmd_add(a: argparse.Namespace) -> int:
    srcs = [Path(p) for p in a.ref] if a.ref else [newest_generated()]
    for src in srcs:
        if not src.is_file():
            sys.exit(f"[ERROR] 参考图不存在: {src}")
    dupes = sorted({s.name for s in srcs if [x.name for x in srcs].count(s.name) > 1})
    if dupes:
        sys.exit(
            f"[ERROR] 一次 add 传入同名文件（入库互相覆盖）: {dupes}\n"
            "  → 先重命名源文件再 add"
        )
    target = asset_dir(a.name)
    if target.exists() and not a.force:
        sys.exit(
            f"[ERROR] 资产已存在: {a.name}（覆盖请加 --force）\n"
            f"  → 查看: python3 assets.py show {a.name}"
        )
    refs_dir = target / "refs"
    refs_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    for src in srcs:
        dest = refs_dir / src.name
        # 拷贝入库防原文件被清理；同名覆盖是 force 重钉的预期行为
        dest.write_bytes(src.read_bytes())
        saved.append(src.name)
    meta = {
        "name": a.name,
        "kind": a.kind,
        "refs": saved,
        "note": a.note or "",
        "created": int(time.time()),
    }
    (target / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"[OK] 资产已保存: {a.name} (kind={a.kind}, {len(saved)} 张参考图) → {target}", file=sys.stderr)
    return 0


def cmd_list(_a: argparse.Namespace) -> int:
    root = store_root()
    if not root.is_dir():
        print("(资产库为空)", file=sys.stderr)
        return 0
    metas = sorted(
        (load_asset(p.name) for p in root.iterdir() if p.is_dir()),
        key=lambda m: m["name"],
    )
    if not metas:
        print("(资产库为空)", file=sys.stderr)
        return 0
    for m in metas:
        note = f" — {m['note']}" if m.get("note") else ""
        print(f"{m['name']}\t{m['kind']}\t{len(m['refs'])} refs{note}")
    return 0


def cmd_show(a: argparse.Namespace) -> int:
    m = load_asset(a.name)
    print(json.dumps({**m, "refs": [str(p) for p in m["refs"]]}, ensure_ascii=False, indent=2))
    return 0


def cmd_remove(a: argparse.Namespace) -> int:
    target = asset_dir(a.name)
    if not target.is_dir():
        sys.exit(f"[ERROR] 资产不存在: {a.name}")
    import shutil

    shutil.rmtree(target)
    print(f"[OK] 资产已删除: {a.name}", file=sys.stderr)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(
        prog="assets.py",
        description="wudaozi —— 角色/画风命名资产库（钉住满意的图，ti2i 用 --ref 复用）",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    add = sub.add_parser("add", help="新增/覆盖资产")
    add.add_argument("name")
    add.add_argument("--kind", choices=list(KINDS), required=True,
                     help="character=参考图即主体(复现角色) / style=只借画风勿抄主体")
    src = add.add_mutually_exclusive_group(required=True)
    src.add_argument("--ref", nargs="+", help="参考图文件（可多张，拷贝入库）")
    src.add_argument("--from-last", action="store_true",
                     help="把最近一次生成的产物（输出目录 mtime 最新）钉为参考图")
    add.add_argument("--note", default="", help="备注（用途/外观要点）")
    add.add_argument("--force", action="store_true", help="覆盖已有资产")
    add.set_defaults(func=cmd_add)

    lst = sub.add_parser("list", help="列出全部资产")
    lst.set_defaults(func=cmd_list)
    show = sub.add_parser("show", help="查看资产详情")
    show.add_argument("name")
    show.set_defaults(func=cmd_show)
    rm = sub.add_parser("remove", help="删除资产")
    rm.add_argument("name")
    rm.set_defaults(func=cmd_remove)

    a = p.parse_args()
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
