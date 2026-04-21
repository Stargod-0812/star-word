"""star-word CLI."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List

from . import __version__
from . import detectors, installer


def _print_human(r: installer.InstallResult) -> None:
    state = "已接线" if r.wired else "未接线 / 已拆除"
    print(f"[star-word] {r.surface} ({r.mode}): {state}")
    if r.target:
        print(f"  目标: {r.target}")
    if r.notes:
        print(f"  备注: {r.notes}")


def _handshake_text() -> str:
    counts = {"词": 0, "式": 0, "气": 0}
    for result in detectors.review(""):
        prefix = result.rule_id.split("-", 1)[0]
        if prefix in counts:
            counts[prefix] += 1
    return (
        f"已加载 star-word v{__version__}：词表 {counts['词']} 条，"
        f"结构 {counts['式']} 条，判断 {counts['气']} 条。规则正文见 .sw/rules.md。"
    )


def cmd_enable(args: argparse.Namespace) -> int:
    try:
        r = installer.enable(args.surface, global_scope=args.global_)
    except ValueError as e:
        print(f"错误: {e}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(r.__dict__, ensure_ascii=False, indent=2))
    else:
        _print_human(r)
    return 0


def cmd_disable(args: argparse.Namespace) -> int:
    try:
        r = installer.disable(args.surface, global_scope=args.global_)
    except ValueError as e:
        print(f"错误: {e}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(r.__dict__, ensure_ascii=False, indent=2))
    else:
        _print_human(r)
    return 0


def cmd_surfaces(args: argparse.Namespace) -> int:
    surfaces = installer.list_surfaces()
    if args.json:
        print(json.dumps(surfaces, ensure_ascii=False, indent=2))
        return 0
    print("支持的接入面:")
    for s in surfaces:
        print(f"  - {s['surface']:<12} mode={s['mode']:<16} target={s['target']}")
    return 0


def cmd_review(args: argparse.Namespace) -> int:
    path = Path(args.file)
    if not path.exists():
        print(f"错误: 文件不存在 {path}", file=sys.stderr)
        return 2
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as e:
        print(f"错误: 无法以 UTF-8 解码 {path}: {e}", file=sys.stderr)
        return 2

    results = detectors.review(text)

    if args.json or args.audit_only:
        payload = {
            "version": __version__,
            "file": str(path),
            "results": [
                {
                    "rule_id": r.rule_id,
                    "status": r.status,
                    "violation_count": len(r.violations),
                    "violations": [v.as_dict() for v in r.violations],
                }
                for r in results
            ],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        total = sum(len(r.violations) for r in results)
        return 1 if total > 0 else 0

    total = 0
    print(f"star-word v{__version__} review: {path}")
    print("-" * 60)
    for r in results:
        if r.status == "sense-pending":
            continue
        count = len(r.violations)
        if count:
            total += count
            print(f"\n{r.rule_id}: {count} 处")
            for v in r.violations[:5]:
                print(f"  L{v.line}:C{v.col}  {v.message}")
                print(f"    > {v.excerpt}")
            if count > 5:
                print(f"  ... (还有 {count - 5} 处省略；用 --json 查看全部)")
    print("\n" + "-" * 60)
    print(f"机械 + 结构规则违规总数: {total}")
    pending = [r.rule_id for r in results if r.status == "sense-pending"]
    if pending:
        print(f"语义规则（需宿主模型或人工判断）: {', '.join(pending)}")
    return 1 if total > 0 else 0


def cmd_handshake(args: argparse.Namespace) -> int:
    """打印自检 handshake 字符串（与 adapter 里写的一致）."""
    print(_handshake_text())
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="star-word",
        description="star-word —— 中文技术写作规则集（21 条）",
    )
    p.add_argument("--version", action="version", version=f"star-word {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    pe = sub.add_parser("enable", help="接线某接入面")
    pe.add_argument("surface")
    pe.add_argument("--global", dest="global_", action="store_true",
                    help="全局接入（写到 ~/.claude/ 而非 CWD）")
    pe.add_argument("--json", action="store_true")
    pe.set_defaults(func=cmd_enable)

    pd = sub.add_parser("disable", help="拆掉某接入面")
    pd.add_argument("surface")
    pd.add_argument("--global", dest="global_", action="store_true")
    pd.add_argument("--json", action="store_true")
    pd.set_defaults(func=cmd_disable)

    ps = sub.add_parser("surfaces", help="列出支持的接入面")
    ps.add_argument("--json", action="store_true")
    ps.set_defaults(func=cmd_surfaces)

    pr = sub.add_parser("review", help="审阅一份文档")
    pr.add_argument("file")
    pr.add_argument("--json", action="store_true")
    pr.add_argument("--audit-only", action="store_true")
    pr.set_defaults(func=cmd_review)

    ph = sub.add_parser("handshake", help="打印自检口令")
    ph.set_defaults(func=cmd_handshake)

    return p


def main(argv: List[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
