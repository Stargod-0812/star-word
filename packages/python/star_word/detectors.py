"""star-word 检测器（v0.2）.

规则 ID 使用中文分组前缀：词-01..08 / 式-01..07 / 气-01..06。
机械 / 结构规则由 review() 直接检测；语义规则标记为 sense-pending 交给宿主模型或人工。

性能：_precompute_fence_map 在扫描文档时只计算一次，避免每条规则 O(N²) 重扫。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, List


@dataclass(frozen=True)
class Violation:
    rule_id: str
    message: str
    line: int
    col: int
    excerpt: str

    def as_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "message": self.message,
            "line": self.line,
            "col": self.col,
            "excerpt": self.excerpt,
        }


@dataclass
class RuleResult:
    rule_id: str
    status: str  # "ok" / "violations" / "sense-pending"
    violations: List[Violation] = field(default_factory=list)


@dataclass
class ScanContext:
    """预计算的扫描上下文 —— 每个文档算一次，各规则共享。"""
    lines: List[str]
    fence_map: List[bool]    # fence_map[i] = True 表示第 i 行（0-indexed）在代码块内
    masked_lines: List[str]  # 每行的 inline-code / 引号内容已替换为等长空格


# -------- 词典（直接在代码里维护，与 rules.yaml 由 scripts/build.py 校对） --------

BANNED_词_01 = [
    "赋能", "闭环", "抓手", "顶层设计", "多维度", "全面提升", "深度赋能",
    "打通", "拉通", "加持", "一体化", "全链路", "场景化",
]

BANNED_词_02 = [
    "值得注意的是", "值得一提的是", "需要指出的是", "不难发现", "不难看出",
    "毋庸置疑", "众所周知", "综上所述", "总的来说", "总而言之", "一言以蔽之",
    "可以说", "可以这么说", "某种程度上", "在一定程度上", "与此同时",
]

BANNED_词_03 = [
    "在当今", "随着", "首先让我们", "接下来我将", "接下来，我将", "在本文中",
    "让我们一起来", "让我们先来", "我们先来了解", "在开始之前", "为了更好地",
]

BANNED_词_04 = [
    "好问题", "这是一个非常好的问题", "这是一个很好的",
    "让我来为您解释", "让我为您解释", "让我来为你解释",
    "希望对你有帮助", "希望能帮到你", "希望这能帮",
    "如有疑问请", "如有疑问，请", "期待您的反馈", "感谢您的阅读",
    "抛砖引玉", "不当之处", "以上就是", "以上便是",
]

BANNED_词_08 = [
    "稳稳接住", "稳稳地", "默默守护", "悄然绽放", "温柔地", "从容应对",
    "有温度地", "贴心地", "智能地", "聪明地", "巧妙地", "轻松搞定", "一键搞定",
    "丝滑", "丝般顺滑", "如丝般", "保驾护航", "助力腾飞", "赋能前行",
]

SUMMARY_CLOSERS = [
    "综上所述", "总的来说", "总而言之", "一言以蔽之",
    "由此可见", "因此可以看出", "综上",
]

SEMANTIC_RULES = [
    ("词-05", "模糊缓冲（需判断是否在谈概率）"),
    ("式-02", "机械并列（需判断信息是否真并列）"),
    ("式-03", "长定语前置（需中文句法分析）"),
    ("式-05", "术语前后不一致（需语义聚合）"),
    ("式-07", "列表滥用（需判断信息是否真需并列）"),
    ("气-01", "第一句直接入题"),
    ("气-02", "不说正确但无用的话"),
    ("气-03", "有判断、有立场"),
    ("气-04", "看本质，不停在现象"),
    ("气-05", "信息密度"),
    ("气-06", "用人话，不文绉绉"),
]


# -------- 预处理 --------


def _precompute_fence_map(lines: List[str]) -> List[bool]:
    """一次遍历，算出每行是否在 ``` code fence 之内。"""
    fence_map = [False] * len(lines)
    in_fence = False
    for i, line in enumerate(lines):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            fence_map[i] = True  # 围栏本身也视为 fence（避免误扫```python 里的```）
        else:
            fence_map[i] = in_fence
    return fence_map


def _mask_line(line: str) -> str:
    """把 inline code / 中英文引号 / 中文引号内的内容替换为等长空格，避免 meta 引用误报。"""
    out = re.sub(r"`[^`]*`", lambda m: " " * len(m.group(0)), line)
    out = re.sub(r"\u201c[^\u201d]*\u201d", lambda m: " " * len(m.group(0)), out)  # 中文 ""
    out = re.sub(r"\u2018[^\u2019]*\u2019", lambda m: " " * len(m.group(0)), out)  # 中文 ''
    out = re.sub(r"「[^」]*」", lambda m: " " * len(m.group(0)), out)             # 日式/中文 「」
    out = re.sub(r'"[^"]*"', lambda m: " " * len(m.group(0)), out)
    out = re.sub(r"'[^']*'", lambda m: " " * len(m.group(0)), out)
    return out


def _build_ctx(text: str) -> ScanContext:
    lines = text.splitlines()
    return ScanContext(
        lines=lines,
        fence_map=_precompute_fence_map(lines),
        masked_lines=[_mask_line(line) for line in lines],
    )


def _excerpt(line: str, col: int, width: int = 80) -> str:
    start = max(0, col - width // 2)
    end = min(len(line), col + width // 2)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(line) else ""
    return f"{prefix}{line[start:end]}{suffix}"


def _scan_banned(
    ctx: ScanContext, rule_id: str, words: List[str], label: str
) -> List[Violation]:
    out: List[Violation] = []
    for i, masked in enumerate(ctx.masked_lines):
        if ctx.fence_map[i]:
            continue
        for w in words:
            start = 0
            while True:
                col = masked.find(w, start)
                if col < 0:
                    break
                out.append(Violation(
                    rule_id=rule_id,
                    message=f"{label}：{w!r}",
                    line=i + 1,
                    col=col + 1,
                    excerpt=_excerpt(ctx.lines[i], col),
                ))
                start = col + len(w)
    return out


# -------- 规则实现 --------


def 词_01(ctx: ScanContext) -> RuleResult:
    v = _scan_banned(ctx, "词-01", BANNED_词_01, "空洞价值词")
    return RuleResult("词-01", "ok" if not v else "violations", v)


def 词_02(ctx: ScanContext) -> RuleResult:
    v = _scan_banned(ctx, "词-02", BANNED_词_02, "AI 过渡套话")
    return RuleResult("词-02", "ok" if not v else "violations", v)


def 词_03(ctx: ScanContext) -> RuleResult:
    """铺垫式开场：只在段首或 markdown 列表首命中才告警。"""
    out: List[Violation] = []
    paragraph_start = True
    for i, line in enumerate(ctx.lines):
        if ctx.fence_map[i]:
            paragraph_start = False
            continue
        stripped = line.strip()
        if not stripped:
            paragraph_start = True
            continue
        if paragraph_start:
            leading = re.sub(r"^(?:(?:[#>\-*]+)\s*|\d+[.)、]\s*)+", "", line).lstrip()
            for w in BANNED_词_03:
                if leading.startswith(w):
                    col = line.find(w)
                    out.append(Violation(
                        rule_id="词-03",
                        message=f"铺垫式开场：段首出现 {w!r}",
                        line=i + 1,
                        col=col + 1,
                        excerpt=_excerpt(line, col),
                    ))
        paragraph_start = False
    return RuleResult("词-03", "ok" if not out else "violations", out)


def 词_04(ctx: ScanContext) -> RuleResult:
    v = _scan_banned(ctx, "词-04", BANNED_词_04, "讨好式表达")
    return RuleResult("词-04", "ok" if not v else "violations", v)


def 词_06(ctx: ScanContext) -> RuleResult:
    """滥用『进行』：匹配 '进行 + 双音节汉字动词'."""
    out: List[Violation] = []
    pattern = re.compile(r"进行(?!到|中|不下去|得)([\u4e00-\u9fff]{2})")
    for i, masked in enumerate(ctx.masked_lines):
        if ctx.fence_map[i]:
            continue
        for m in pattern.finditer(masked):
            verb = m.group(1)
            out.append(Violation(
                rule_id="词-06",
                message=f"滥用『进行』：进行{verb} → {verb}",
                line=i + 1,
                col=m.start() + 1,
                excerpt=_excerpt(ctx.lines[i], m.start()),
            ))
    return RuleResult("词-06", "ok" if not out else "violations", out)


def 词_07(ctx: ScanContext) -> RuleResult:
    """单句内 ≥ 3 个『的』."""
    out: List[Violation] = []
    sentence_splitter = re.compile(r"[^。！？!?]+[。！？!?]?")
    for i, line in enumerate(ctx.lines):
        if ctx.fence_map[i]:
            continue
        for m in sentence_splitter.finditer(line):
            sentence = m.group(0)
            count = sentence.count("的")
            if count >= 3:
                out.append(Violation(
                    rule_id="词-07",
                    message=f"单句内出现 {count} 个『的』，前置定语过重",
                    line=i + 1,
                    col=m.start() + 1,
                    excerpt=_excerpt(line, m.start()),
                ))
    return RuleResult("词-07", "ok" if not out else "violations", out)


def 词_08(ctx: ScanContext) -> RuleResult:
    v = _scan_banned(ctx, "词-08", BANNED_词_08, "拟人化装饰词")
    return RuleResult("词-08", "ok" if not v else "violations", v)


def 式_01(ctx: ScanContext) -> RuleResult:
    """段尾总结句."""
    out: List[Violation] = []
    paragraph: List[int] = []  # store line indices

    def flush(indices: List[int]) -> list[Violation]:
        if not indices:
            return []
        last = indices[-1]
        stripped = ctx.lines[last].strip()
        if not stripped:
            return []
        for opener in SUMMARY_CLOSERS:
            if stripped.startswith(opener):
                return [Violation(
                    rule_id="式-01",
                    message=f"段尾总结句：以 {opener!r} 收尾的段落通常可删最后一句",
                    line=last + 1,
                    col=stripped.find(opener) + 1,
                    excerpt=_excerpt(ctx.lines[last], 0),
                )]
        return []

    for i, line in enumerate(ctx.lines):
        if ctx.fence_map[i]:
            if paragraph:
                out.extend(flush(paragraph))
                paragraph = []
            continue
        if not line.strip():
            out.extend(flush(paragraph))
            paragraph = []
        else:
            paragraph.append(i)
    out.extend(flush(paragraph))
    return RuleResult("式-01", "ok" if not out else "violations", out)


def 式_04(ctx: ScanContext) -> RuleResult:
    """连续 4+ 四字结构（顿号/逗号分隔）.

    阈值定 4 不定 3：紧实技术中文常常连用 3 个四字名词（「命令语义、复制链路、故障处理」），
    不是 AI 堆砌。只有 4 个及以上连用才基本排除合法技术表述，接近装饰性堆砌。
    """
    out: List[Violation] = []
    pattern = re.compile(
        r"([\u4e00-\u9fff]{4})[，、,]\s*"
        r"([\u4e00-\u9fff]{4})[，、,]\s*"
        r"([\u4e00-\u9fff]{4})[，、,]\s*"
        r"([\u4e00-\u9fff]{4})"
    )
    for i, masked in enumerate(ctx.masked_lines):
        if ctx.fence_map[i]:
            continue
        for m in pattern.finditer(masked):
            out.append(Violation(
                rule_id="式-04",
                message=f"四字词堆砌：{m.group(1)}、{m.group(2)}、{m.group(3)}、{m.group(4)}",
                line=i + 1,
                col=m.start() + 1,
                excerpt=_excerpt(ctx.lines[i], m.start()),
            ))
    return RuleResult("式-04", "ok" if not out else "violations", out)


def 式_06(ctx: ScanContext) -> RuleResult:
    """中文段落里混入半角标点."""
    out: List[Violation] = []
    pattern = re.compile(r"([\u4e00-\u9fff])([,.!?])([\u4e00-\u9fff])")
    for i, masked in enumerate(ctx.masked_lines):
        if ctx.fence_map[i]:
            continue
        for m in pattern.finditer(masked):
            punct = m.group(2)
            out.append(Violation(
                rule_id="式-06",
                message=f"中文段落混用半角标点：{punct!r} 应为全角",
                line=i + 1,
                col=m.start(2) + 1,
                excerpt=_excerpt(ctx.lines[i], m.start(2)),
            ))
    return RuleResult("式-06", "ok" if not out else "violations", out)


DETECTORS: List[Callable[[ScanContext], RuleResult]] = [
    词_01, 词_02, 词_03, 词_04, 词_06, 词_07, 词_08,
    式_01, 式_04, 式_06,
]


def review(text: str) -> List[RuleResult]:
    """返回所有规则的检测结果。"""
    ctx = _build_ctx(text)
    results = [d(ctx) for d in DETECTORS]
    for rule_id, _desc in SEMANTIC_RULES:
        results.append(RuleResult(rule_id=rule_id, status="sense-pending"))
    return results
