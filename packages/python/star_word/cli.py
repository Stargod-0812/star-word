"""star-word CLI."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List

from . import __version__
from . import detectors, installer


def _print_result_human(result: installer.InstallResult) -> None:
    status = "已启用" if result.enabled else "已禁用 / 未启用"
    print(f"[star-word] {result.tool} ({result.mode}): {status}")
    if result.target:
        print(f"  target: {result.target}")
    if result.notes:
        print(f"  notes:  {result.notes}")


def cmd_enable(args: argparse.Namespace) -> int:
    try:
        r = installer.enable(args.tool, global_scope=args.global_)
    except ValueError as e:
        print(f"错误: {e}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(r.__dict__, ensure_ascii=False, indent=2))
    else:
        _print_result_human(r)
    return 0


def cmd_disable(args: argparse.Namespace) -> int:
    try:
        r = installer.disable(args.tool, global_scope=args.global_)
    except ValueError as e:
        print(f"错误: {e}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(r.__dict__, ensure_ascii=False, indent=2))
    else:
        _print_result_human(r)
    return 0


def cmd_list_tools(args: argparse.Namespace) -> int:
    tools = installer.list_tools()
    if args.json:
        print(json.dumps(tools, ensure_ascii=False, indent=2))
        return 0
    print("支持的工具:")
    for t in tools:
        print(f"  - {t['name']:<12} mode={t['mode']:<16} target={t['target']}")
    return 0


def cmd_review(args: argparse.Namespace) -> int:
    path = Path(args.file)
    if not path.exists():
        print(f"错误: 文件不存在 {path}", file=sys.stderr)
        return 2
    text = path.read_text(encoding="utf-8")
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

    # 人类可读输出
    total_violations = 0
    by_rule: dict[str, int] = {}
    print(f"star-word v{__version__} review: {path}")
    print("-" * 60)
    for r in results:
        if r.status == "semantic_pending":
            continue
        count = len(r.violations)
        by_rule[r.rule_id] = count
        if count:
            total_violations += count
            print(f"\n{r.rule_id}: {count} 处")
            for v in r.violations[:5]:
                print(f"  L{v.line}:C{v.col}  {v.message}")
                print(f"    > {v.excerpt}")
            if count > 5:
                print(f"  ... (还有 {count - 5} 处省略；用 --json 查看全部)")
    print("\n" + "-" * 60)
    print(f"机械 + 结构规则违规总数: {total_violations}")
    pending = [r.rule_id for r in results if r.status == "semantic_pending"]
    if pending:
        print(f"语义规则（需宿主模型或人工判断）: {', '.join(pending)}")
    return 1 if total_violations > 0 else 0


def cmd_verify(args: argparse.Namespace) -> int:
    """回答 "star-word 在生效吗？"."""
    print(
        f"star-word v{__version__} active: 21 条中文技术写作规则"
        "（STAR-01..08 禁用词典 + STAR-09..15 结构 tell + STAR-16..21 语感原则）；"
        "完整规则体见 .star-word/RULES.md。"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="star-word",
        description="star-word: 中文技术写作规则集（21 条）.",
    )
    p.add_argument("--version", action="version", version=f"star-word {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    # enable
    pe = sub.add_parser("enable", help="为某工具启用 star-word 规则")
    pe.add_argument("tool", help="工具名称，见 list-tools")
    pe.add_argument(
        "--global",
        dest="global_",
        action="store_true",
        help="全局安装（写到 ~/.claude/），而非当前目录",
    )
    pe.add_argument("--json", action="store_true", help="机器可读输出")
    pe.set_defaults(func=cmd_enable)

    # disable
    pd = sub.add_parser("disable", help="禁用某工具的 star-word 规则")
    pd.add_argument("tool")
    pd.add_argument("--global", dest="global_", action="store_true")
    pd.add_argument("--json", action="store_true")
    pd.set_defaults(func=cmd_disable)

    # list-tools
    pl = sub.add_parser("list-tools", help="列出支持的工具")
    pl.add_argument("--json", action="store_true")
    pl.set_defaults(func=cmd_list_tools)

    # review
    pr = sub.add_parser("review", help="审查一份 markdown/文本文件")
    pr.add_argument("file", help="待审查的文件路径")
    pr.add_argument("--json", action="store_true", help="JSON 输出")
    pr.add_argument("--audit-only", action="store_true", help="仅检测，不给修改建议（与 --json 等价）")
    pr.set_defaults(func=cmd_review)

    # verify
    pv = sub.add_parser("verify", help="打印自检握手字符串")
    pv.set_defaults(func=cmd_verify)

    return p


def main(argv: List[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
