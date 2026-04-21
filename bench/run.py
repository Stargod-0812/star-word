#!/usr/bin/env python3
"""star-word 有效性评测：同一个提示，让 codex 跑 baseline + treatment 两遍，对比违规数。

baseline = 无 star-word 系统提示
treatment = 把 star-word codex adapter 的 SYSTEM PROMPT 作为前缀注入

产出：bench/outputs/<slug>-baseline.md / <slug>-treatment.md + bench/v0.2-effectiveness.md

用法：
    bench/run.py               # 跑全部 prompts
    bench/run.py --quick       # 只跑 1 个 prompt
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = Path(__file__).resolve().parent / "outputs"
SUMMARY = Path(__file__).resolve().parent / "v0.2-effectiveness.md"


# 4 条代表性任务：3 条具体技术题（baseline 应已较干净）+ 1 条宣传题（易诱发 AI 味）
PROMPTS = {
    "rfc": "帮我起草一份 400 字左右的中文 RFC，题目：'Redis 集群升级到 7.x 的迁移方案'。要说明现状、目标、迁移步骤、回滚预案。",
    "debug": "线上 Java 服务内存持续上涨，Full GC 频繁。请用中文给出系统化的排查思路和关键命令。500 字内。",
    "postmortem": "写一份 300 字的中文事故复盘：2026-04-15 下午 2 点订单服务挂了 17 分钟，根因是 ThreadLocal 泄漏。结构：时间线、根因、修复、改进。",
    "vision": "为我们的新 AI 平台团队写一份 400 字的中文愿景陈述，要求展望未来、打动投资人、彰显野心。",
}


@dataclass
class RunResult:
    slug: str
    variant: str          # "baseline" 或 "treatment"
    output_path: Path
    violation_count: int
    violations_by_rule: dict[str, int]
    wall_seconds: float


def extract_codex_system_prompt() -> str:
    """从 adapters/codex.md 提取 ``` 块内的 SYSTEM PROMPT 正文."""
    adapter = ROOT / "adapters" / "codex.md"
    text = adapter.read_text(encoding="utf-8")
    m = re.search(r"## SYSTEM PROMPT\s*\n\s*```\n(.*?)\n```", text, flags=re.DOTALL)
    if not m:
        raise RuntimeError("无法从 adapters/codex.md 提取 SYSTEM PROMPT")
    return m.group(1).strip()


def run_codex(prompt: str, timeout_seconds: int = 180) -> tuple[str, float]:
    """跑一次 codex exec，返回 (纯文本输出, 墙钟秒数)."""
    t0 = time.time()
    proc = subprocess.run(
        [
            "codex", "exec",
            "-s", "read-only",
            "-c", 'model_reasoning_effort="medium"',
            "-c", 'features.web_search_cached=false',
            prompt,
        ],
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        stdin=subprocess.DEVNULL,
    )
    elapsed = time.time() - t0
    if proc.returncode != 0:
        raise RuntimeError(f"codex exec 失败（exit={proc.returncode}）:\n{proc.stderr}")
    # codex exec 输出包含 [codex thinking] + [codex ran] + 答案。提取答案：最后一个 "codex" 行之后的内容
    out = proc.stdout
    # 简化：用启发式去掉 [codex thinking] / [codex ran] 行与元信息
    cleaned_lines = []
    skip_block = False
    for line in out.splitlines():
        if re.match(r"^\[(codex|tokens)\]|\[codex thinking\]|\[codex ran\]", line):
            skip_block = True
            continue
        if line.startswith("tokens used") or line.startswith("hook:"):
            continue
        if line.strip() == "codex":
            skip_block = False
            continue
        cleaned_lines.append(line)
    return "\n".join(cleaned_lines).strip() + "\n", elapsed


def run_star_word_review(path: Path) -> tuple[int, dict[str, int]]:
    """对某文件跑 star-word review --json，返回 (总违规数, 按规则分组计数)."""
    proc = subprocess.run(
        ["star-word", "review", str(path), "--json"],
        capture_output=True,
        text=True,
    )
    # review 有违规时 exit 1，无违规时 exit 0；两种都要解析 stdout
    data = json.loads(proc.stdout)
    total = 0
    by_rule: dict[str, int] = {}
    for r in data["results"]:
        if r["violation_count"] > 0:
            by_rule[r["rule_id"]] = r["violation_count"]
            total += r["violation_count"]
    return total, by_rule


def run_one(slug: str, prompt: str, system_prompt: str, treatment: bool) -> RunResult:
    variant = "treatment" if treatment else "baseline"
    full_prompt = (
        f"你必须遵守以下规则生成中文：\n\n{system_prompt}\n\n---\n\n用户任务：{prompt}"
        if treatment
        else prompt
    )
    print(f"  [{slug}:{variant}] codex exec 中…", flush=True)
    text, secs = run_codex(full_prompt)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"{slug}-{variant}.md"
    out_path.write_text(text, encoding="utf-8")
    total, by_rule = run_star_word_review(out_path)
    print(f"    → {secs:.1f}s, {total} 处违规 ({dict(by_rule)})", flush=True)
    return RunResult(
        slug=slug,
        variant=variant,
        output_path=out_path,
        violation_count=total,
        violations_by_rule=by_rule,
        wall_seconds=secs,
    )


def write_summary(results: list[RunResult], system_prompt_chars: int) -> None:
    # 按 slug 分组，比较 baseline vs treatment
    by_slug: dict[str, dict[str, RunResult]] = {}
    for r in results:
        by_slug.setdefault(r.slug, {})[r.variant] = r

    lines: list[str] = []
    lines.append("# star-word v0.2 有效性评测")
    lines.append("")
    lines.append(f"- 评测时间：{time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("- 模型：codex CLI（调用 GPT-5 系列）")
    lines.append(f"- 注入 prompt 字符数：{system_prompt_chars}")
    lines.append(f"- 评测任务数：{len(by_slug)}")
    lines.append("")
    lines.append("## 对比表")
    lines.append("")
    lines.append("| 任务 | baseline 违规 | treatment 违规 | 下降 | treatment 加速/减速 |")
    lines.append("| --- | ---: | ---: | ---: | ---: |")

    total_baseline = 0
    total_treatment = 0
    for slug, variants in by_slug.items():
        b = variants.get("baseline")
        t = variants.get("treatment")
        if not b or not t:
            continue
        drop = b.violation_count - t.violation_count
        drop_pct = f"{(drop / b.violation_count * 100):.0f}%" if b.violation_count else "n/a"
        delta_time = f"{t.wall_seconds - b.wall_seconds:+.1f}s"
        lines.append(
            f"| {slug} | {b.violation_count} | {t.violation_count} "
            f"| {drop}（{drop_pct}） | {delta_time} |"
        )
        total_baseline += b.violation_count
        total_treatment += t.violation_count

    if total_baseline:
        total_drop = total_baseline - total_treatment
        total_pct = (total_drop / total_baseline * 100)
        lines.append(
            f"| **合计** | **{total_baseline}** | **{total_treatment}** "
            f"| **{total_drop}（{total_pct:.0f}%）** | — |"
        )

    lines.append("")
    lines.append("## 各任务明细")
    lines.append("")
    for slug, variants in by_slug.items():
        b = variants.get("baseline")
        t = variants.get("treatment")
        if not b or not t:
            continue
        lines.append(f"### {slug}")
        lines.append("")
        lines.append(f"- baseline 违规规则分布：{dict(b.violations_by_rule) or '无'}")
        lines.append(f"- treatment 违规规则分布：{dict(t.violations_by_rule) or '无'}")
        lines.append(f"- 输出文件：[`outputs/{slug}-baseline.md`](outputs/{slug}-baseline.md) vs [`outputs/{slug}-treatment.md`](outputs/{slug}-treatment.md)")
        lines.append("")

    lines.append("## 解读")
    lines.append("")
    if total_baseline:
        if total_drop > 0:
            lines.append(
                f"注入 star-word 规则后，总违规数从 {total_baseline} 降到 {total_treatment}（-{total_drop}，-{total_pct:.0f}%）。"
            )
        elif total_drop == 0:
            lines.append(
                f"注入规则后违规数持平（{total_baseline}），说明 baseline 本身已经较干净，或规则未触达该类问题。"
            )
        else:
            lines.append(
                f"注入规则后违规数反升（{total_baseline} → {total_treatment}），"
                "说明 prompt 注入可能引入了规则自身提到的禁用词（因为 prompt 里就列了这些词）。需检查输出是否在引用或复述规则文本。"
            )
    lines.append("")
    lines.append("仅看机械/结构检测。语感规则（气组）未被 review 计入。")
    lines.append("每任务只跑 1 次，非统计学意义上显著；展示的是 directional signal，不是严格 benchmark。")
    lines.append("")
    SUMMARY.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n✓ 总结写入 {SUMMARY}")


def main() -> int:
    ap = argparse.ArgumentParser(description="star-word effectiveness bench")
    ap.add_argument("--quick", action="store_true", help="只跑 1 个 prompt")
    args = ap.parse_args()

    system_prompt = extract_codex_system_prompt()
    print(f"加载 SYSTEM PROMPT（{len(system_prompt)} 字符）", flush=True)

    prompts = dict(list(PROMPTS.items())[:1]) if args.quick else PROMPTS
    results: list[RunResult] = []
    for slug, prompt in prompts.items():
        print(f"\n=== {slug} ===", flush=True)
        try:
            baseline = run_one(slug, prompt, system_prompt, treatment=False)
            treatment = run_one(slug, prompt, system_prompt, treatment=True)
            results.extend([baseline, treatment])
        except subprocess.TimeoutExpired:
            print(f"  ✗ {slug} 超时，跳过", flush=True)
        except Exception as e:
            print(f"  ✗ {slug} 失败：{e}", flush=True)

    write_summary(results, len(system_prompt))
    return 0


if __name__ == "__main__":
    sys.exit(main())
