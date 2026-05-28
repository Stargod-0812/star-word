"""star-word 检测器（v0.3）.

规则 ID 使用中文分组前缀：词-01..08 / 式-01..08 / 气-01..06。
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
    "拉通", "加持", "一体化", "场景化",
]

# 上下文感知：grey_zone 词只在套话上下文里告警，合法技术用法不报
# 与 rules.yaml 的 grey_zone 字段对齐
CONTEXT_词_01 = {
    "打通": {
        "ban_contexts": ["打通数据", "打通链路", "打通壁垒", "打通业务", "打通生态"],
        "allow_contexts": ["打通隧道", "打通网络", "打通管道"],
    },
    "全链路": {
        "ban_contexts": ["全链路赋能", "全链路价值", "全链路服务"],
        "allow_contexts": ["全链路追踪", "全链路压测", "全链路监控"],
    },
    "链路": {
        "ban_contexts": ["业务链路", "价值链路", "增长链路"],
        "allow_contexts": ["调用链路", "补偿链路", "链路追踪", "数据链路", "链路层"],
    },
    "生态": {
        "ban_contexts": ["产业生态", "战略生态", "赋能生态"],
        "allow_contexts": ["开发者生态", "生态系统", "插件生态", "技术生态"],
    },
    "布局": {
        "ban_contexts": ["战略布局", "全国布局", "全球布局", "生态布局"],
        "allow_contexts": ["页面布局", "UI 布局", "布局组件", "栅格布局", "弹性布局"],
    },
}


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
    """把 inline code / 引号 / HTML 标签内容替换为等长空格，避免 meta 引用误报。"""
    out = re.sub(r"`[^`]*`", lambda m: " " * len(m.group(0)), line)
    out = re.sub(r"\u201c[^\u201d]*\u201d", lambda m: " " * len(m.group(0)), out)  # 中文 “”
    out = re.sub(r"\u2018[^\u2019]*\u2019", lambda m: " " * len(m.group(0)), out)  # 中文 ‘’
    out = re.sub(r"「[^」]*」", lambda m: " " * len(m.group(0)), out)             # 日式/中文 「」
    out = re.sub(r'"[^"]*"', lambda m: " " * len(m.group(0)), out)
    out = re.sub(r"'[^']*'", lambda m: " " * len(m.group(0)), out)
    out = re.sub(r"<[^>]+>", lambda m: " " * len(m.group(0)), out)  # HTML 标签
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


def _scan_context_aware(
    ctx: ScanContext, rule_id: str, context_map: dict, label: str
) -> List[Violation]:
    """上下文感知扫描：grey_zone 词只在 ban_contexts 出现时告警，allow_contexts 不报。

    若词在 allow_contexts 之一里出现，跳过；
    若词在 ban_contexts 之一里出现，告警；
    若都不在，保守不告警（避免误报）。
    """
    out: List[Violation] = []
    for i, masked in enumerate(ctx.masked_lines):
        if ctx.fence_map[i]:
            continue
        for word, contexts in context_map.items():
            ban_ctxs = contexts.get("ban_contexts", [])
            allow_ctxs = contexts.get("allow_contexts", [])
            start = 0
            while True:
                col = masked.find(word, start)
                if col < 0:
                    break
                # 检查 ±3 字窗口内是否落在 allow/ban 上下文里
                window_start = max(0, col - 3)
                window_end = min(len(masked), col + len(word) + 3)
                window = masked[window_start:window_end]
                # allow 优先级最高
                if any(ac in window for ac in allow_ctxs):
                    start = col + len(word)
                    continue
                if any(bc in window for bc in ban_ctxs):
                    out.append(Violation(
                        rule_id=rule_id,
                        message=f"{label}（套话语境）：{word!r}",
                        line=i + 1,
                        col=col + 1,
                        excerpt=_excerpt(ctx.lines[i], col),
                    ))
                start = col + len(word)
    return out


def 词_01(ctx: ScanContext) -> RuleResult:
    """空洞价值词：默认禁词列表 + grey_zone 词的上下文感知检测。"""
    v = _scan_banned(ctx, "词-01", BANNED_词_01, "空洞价值词")
    v.extend(_scan_context_aware(ctx, "词-01", CONTEXT_词_01, "空洞价值词"))
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
    """单句内 ≥ 3 个『的』. 用分号/冒号/句号/叹号/问号分句。"""
    out: List[Violation] = []
    # 分号和冒号也算句子边界——分号后是新子句，冒号后是新说明
    sentence_splitter = re.compile(r"[^。！？!?；;：:]+[。！？!?；;：:]?")
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


def 式_05(ctx: ScanContext) -> RuleResult:
    """术语前后不一致：同文档内同一概念用了大小写不同的写法。

    机制：
    1. 提取所有 ASCII 标识符（≥3 字符，含字母）；
    2. 按 lowercase 聚合，若同一 key 下出现 ≥2 种写法且每种写法 ≥1 次，告警；
    3. 已 mask 掉代码块/inline code，避免误报代码里的合法 case 差异。

    例：「训练 Model 需要数据。导出 model 权重」→ Model 与 model 同概念，告警。
    例：「URL 解析 vs url 编码」→ URL/url 两种写法，告警。

    保护：
    - 缩写（≤ 2 字符）跳过：避免 "id" 与 "ID" 这种合法变体误报。
    - 路径里的标识符已被 _mask_line 的 fence_map 覆盖。
    """
    # 收集所有 ASCII identifiers（含字母，≥3 字符）
    ident_pattern = re.compile(r"[A-Za-z][A-Za-z0-9_]{2,}")
    occurrences: dict[str, dict[str, list[tuple[int, int]]]] = {}
    # key: lowercase form, value: { actual_case: [(line_idx, col), ...] }

    for i, masked in enumerate(ctx.masked_lines):
        if ctx.fence_map[i]:
            continue
        for m in ident_pattern.finditer(masked):
            term = m.group(0)
            key = term.lower()
            occurrences.setdefault(key, {}).setdefault(term, []).append((i, m.start()))

    out: List[Violation] = []
    for key, variants in occurrences.items():
        if len(variants) < 2:
            continue
        # 按出现次数倒序，第一个是主导写法
        sorted_variants = sorted(variants.items(), key=lambda kv: -len(kv[1]))
        dominant = sorted_variants[0][0]
        for variant, locs in sorted_variants[1:]:
            # 每个非主导变体的第一处出现报一次
            line_idx, col = locs[0]
            out.append(Violation(
                rule_id="式-05",
                message=f"术语不一致：{variant!r} 与主导写法 {dominant!r}（出现 {len(sorted_variants[0][1])} 次）混用",
                line=line_idx + 1,
                col=col + 1,
                excerpt=_excerpt(ctx.lines[line_idx], col),
            ))
    return RuleResult("式-05", "ok" if not out else "violations", out)


def 式_08(ctx: ScanContext) -> RuleResult:
    """句长方差过低：段落内句子长度标准差 < 5 且句子数 ≥ 4。

    AI 生成的段落句长趋同（每句 22-28 字，std < 5）。
    人写的节奏有变化：长句铺逻辑，短句下结论，断句制造停顿。
    """
    out: List[Violation] = []
    # 按中文句号/叹号/问号切句
    sent_splitter = re.compile(r"[^。！？!?\n]+[。！？!?]?")
    paragraph: List[int] = []

    def _check_paragraph(line_indices: List[int]) -> None:
        if not line_indices:
            return
        # 收集段落所有句子长度
        lengths: List[int] = []
        for idx in line_indices:
            if ctx.fence_map[idx]:
                continue
            line = ctx.lines[idx].strip()
            if not line or line.startswith("#") or line.startswith("|") or line.startswith("-"):
                continue
            for m in sent_splitter.finditer(line):
                s = m.group(0).strip()
                if len(s) >= 4:  # 忽略极短片段
                    lengths.append(len(s))
        if len(lengths) < 4:
            return
        mean = sum(lengths) / len(lengths)
        variance = sum((x - mean) ** 2 for x in lengths) / len(lengths)
        std = variance ** 0.5
        if std < 5.0:
            first_line = line_indices[0]
            out.append(Violation(
                rule_id="式-08",
                message=f"句长方差过低（std={std:.1f}，{len(lengths)} 句，均长 {mean:.0f} 字）——节奏单一",
                line=first_line + 1,
                col=1,
                excerpt=_excerpt(ctx.lines[first_line], 0),
            ))

    for i, line in enumerate(ctx.lines):
        if ctx.fence_map[i]:
            if paragraph:
                _check_paragraph(paragraph)
                paragraph = []
            continue
        if not line.strip():
            _check_paragraph(paragraph)
            paragraph = []
        else:
            paragraph.append(i)
    _check_paragraph(paragraph)
    return RuleResult("式-08", "ok" if not out else "violations", out)


DETECTORS: List[Callable[[ScanContext], RuleResult]] = [
    词_01, 词_02, 词_03, 词_04, 词_06, 词_07, 词_08,
    式_01, 式_04, 式_05, 式_06, 式_08,
]


def review(text: str) -> List[RuleResult]:
    """返回所有规则的检测结果。"""
    ctx = _build_ctx(text)
    results = [d(ctx) for d in DETECTORS]
    for rule_id, _desc in SEMANTIC_RULES:
        results.append(RuleResult(rule_id=rule_id, status="sense-pending"))
    return results
