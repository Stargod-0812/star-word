"""star-word CLI."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List

from . import __version__, detectors, installer, scoring


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
    doc = scoring.score_document(results, text, mode=args.mode)

    if args.json or args.audit_only:
        payload = {
            "version": __version__,
            "file": str(path),
            "score": doc.as_dict(),
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
        if args.fail_under is not None and doc.score < args.fail_under:
            return 1
        return 1 if total > 0 else 0

    total = 0
    print(f"star-word v{__version__} review: {path}  [mode={args.mode}]")
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
    grade = scoring.grade(doc.score)
    print(f"文档分: {doc.score:.1f}/100  等级: {grade}  (字数 {doc.char_count})")
    print(f"机械 + 结构规则违规总数: {total}")
    for note in doc.notes:
        print(f"  · {note}")
    pending = [r.rule_id for r in results if r.status == "sense-pending"]
    if pending:
        print(f"语义规则（pending）: {', '.join(pending)}")
        print("  跑 `star-word judge <file>` 让 LLM 评估这些规则。")
    if args.fail_under is not None and doc.score < args.fail_under:
        print(f"\n✗ 文档分 {doc.score:.1f} 低于阈值 {args.fail_under}")
        return 1
    return 1 if total > 0 else 0


def cmd_judge(args: argparse.Namespace) -> int:
    path = Path(args.file)
    if not path.exists():
        print(f"错误: 文件不存在 {path}", file=sys.stderr)
        return 2
    text = path.read_text(encoding="utf-8")

    from . import judge
    rule_ids = args.rules.split(",") if args.rules else None
    try:
        judge_scores = judge.judge_text(text, rule_ids=rule_ids)
    except judge.JudgeError as e:
        print(f"错误: {e}", file=sys.stderr)
        return 2

    # 同时跑 review 拿机械分
    results = detectors.review(text)
    doc = scoring.score_document(results, text, mode=args.mode, judge_results=judge_scores)

    if args.json:
        print(json.dumps(doc.as_dict(), ensure_ascii=False, indent=2))
        return 0

    print(f"star-word v{__version__} judge: {path}  [mode={args.mode}]")
    print("-" * 60)
    print("\n语义规则评分（LLM-as-judge）：\n")
    for s in judge_scores:
        print(f"  {s.rule_id}: {s.score:.1f}/10")
        if s.judge_reasoning:
            print(f"    > {s.judge_reasoning}")
    print("\n" + "-" * 60)
    print(f"文档分: {doc.score:.1f}/100  等级: {scoring.grade(doc.score)}")
    return 0


def cmd_fix(args: argparse.Namespace) -> int:
    path = Path(args.file)
    if not path.exists():
        print(f"错误: 文件不存在 {path}", file=sys.stderr)
        return 2
    text = path.read_text(encoding="utf-8")

    from . import rewriter
    results = detectors.review(text)
    try:
        suggestions = rewriter.suggest_rewrites(text, results, max_violations=args.max)
    except rewriter.RewriteError as e:
        print(f"错误: {e}", file=sys.stderr)
        return 2

    if args.json:
        payload = {
            "file": str(path),
            "suggestions": [
                {
                    "line": s.line,
                    "original": s.original,
                    "suggested": s.suggested,
                    "reason": s.reason,
                }
                for s in suggestions
            ],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if not suggestions:
        print("无违规，无需改写。")
        return 0
    print(f"改写建议（{len(suggestions)} 处）：\n")
    for s in suggestions:
        print(f"L{s.line}：")
        print(f"  - {s.original}")
        print(f"  + {s.suggested}")
        print(f"    理由：{s.reason}\n")
    return 0


def cmd_mcp(args: argparse.Namespace) -> int:
    from . import mcp_server
    mcp_server.serve()
    return 0


def cmd_handshake(args: argparse.Namespace) -> int:
    """打印自检 handshake 字符串（与 adapter 里写的一致）."""
    print(_handshake_text())
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="star-word",
        description="star-word —— 中文技术写作规则集（22 条）",
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
    pr.add_argument("--mode", choices=["strict", "normal", "relaxed"], default="normal",
                    help="严格度模式（默认 normal）")
    pr.add_argument("--fail-under", type=float, default=None,
                    help="文档分低于此值时退出码 1（CI gate 用）")
    pr.set_defaults(func=cmd_review)

    pj = sub.add_parser("judge", help="LLM-as-judge 评估语义规则（需 ANTHROPIC_API_KEY）")
    pj.add_argument("file")
    pj.add_argument("--rules", help="只评估指定规则（逗号分隔，如 '气-01,气-02'）")
    pj.add_argument("--mode", choices=["strict", "normal", "relaxed"], default="normal")
    pj.add_argument("--json", action="store_true")
    pj.set_defaults(func=cmd_judge)

    pf = sub.add_parser("fix", help="对违规处生成改写建议（需 ANTHROPIC_API_KEY）")
    pf.add_argument("file")
    pf.add_argument("--max", type=int, default=20, help="最多改写多少处（默认 20）")
    pf.add_argument("--json", action="store_true")
    pf.set_defaults(func=cmd_fix)

    pm = sub.add_parser("mcp", help="启动 MCP server（stdio）")
    pm.set_defaults(func=cmd_mcp)

    ph = sub.add_parser("handshake", help="打印自检口令")
    ph.set_defaults(func=cmd_handshake)

    return p


def main(argv: List[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
