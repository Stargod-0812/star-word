"""star-word 检测器.

机械规则 + 结构规则. 语义规则（STAR-16..21）交由宿主模型（Claude / Codex / 人工）判断。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, List, Optional


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
    status: str
    violations: List[Violation] = field(default_factory=list)


# -------- 词典 --------

BANNED_WORDS_STAR_01 = [
    "赋能",
    "闭环",
    "抓手",
    "顶层设计",
    "多维度",
    "全面提升",
    "深度赋能",
    "打通",
    "拉通",
    "加持",
    "一体化",
    "全链路",
    "场景化",
]
# 歧义重的词（链路/生态/布局）未进默认列表：
#   - "链路"：有合法技术用法（调用链路/补偿链路）
#   - "生态"：有合法用法（生态系统/开发者生态）
#   - "布局"：有合法用法（页面布局/UI 布局）
# RULES.md 仍将这几个词标记为高风险；具体场景由人审判断。

BANNED_WORDS_STAR_02 = [
    "值得注意的是",
    "值得一提的是",
    "需要指出的是",
    "不难发现",
    "不难看出",
    "毋庸置疑",
    "众所周知",
    "综上所述",
    "总的来说",
    "总而言之",
    "一言以蔽之",
    "可以说",
    "可以这么说",
    "某种程度上",
    "在一定程度上",
    "与此同时",
]

BANNED_WORDS_STAR_03 = [
    "在当今",
    "随着",
    "首先让我们",
    "接下来我将",
    "接下来，我将",
    "在本文中",
    "让我们一起来",
    "让我们先来",
    "我们先来了解",
    "在开始之前",
    "为了更好地",
]

BANNED_WORDS_STAR_04 = [
    "好问题",
    "这是一个非常好的问题",
    "这是一个很好的",
    "让我来为您解释",
    "让我为您解释",
    "让我来为你解释",
    "希望对你有帮助",
    "希望能帮到你",
    "希望这能帮",
    "如有疑问请",
    "如有疑问，请",
    "期待您的反馈",
    "感谢您的阅读",
    "抛砖引玉",
    "不当之处",
    "以上就是",
    "以上便是",
]

BANNED_WORDS_STAR_08 = [
    "稳稳接住",
    "稳稳地",
    "默默守护",
    "悄然绽放",
    "温柔地",
    "从容应对",
    "有温度地",
    "贴心地",
    "智能地",
    "聪明地",
    "巧妙地",
    "轻松搞定",
    "一键搞定",
    "丝滑",
    "丝般顺滑",
    "如丝般",
    "保驾护航",
    "助力腾飞",
    "赋能前行",
]

# 段尾总结句触发词
PARA_SUMMARY_OPENERS = [
    "综上所述",
    "总的来说",
    "总而言之",
    "一言以蔽之",
    "由此可见",
    "因此可以看出",
    "综上",
]

# -------- 工具 --------

CHINESE_CHAR = r"[\u4e00-\u9fff]"


def _iter_lines(text: str):
    for idx, line in enumerate(text.splitlines(), start=1):
        yield idx, line


def _is_in_code_fence(lines: List[str], target_idx: int) -> bool:
    """检测第 target_idx 行是否位于 ``` code fence 内（1-indexed）."""
    in_fence = False
    for i, line in enumerate(lines, start=1):
        stripped = line.lstrip()
        if stripped.startswith("```"):
            in_fence = not in_fence
        if i == target_idx:
            return in_fence
    return False


def _excerpt(line: str, col: int, width: int = 80) -> str:
    start = max(0, col - width // 2)
    end = min(len(line), col + width // 2)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(line) else ""
    return f"{prefix}{line[start:end]}{suffix}"


def _mask_inline_code(line: str) -> str:
    """把 inline code / 中英文引号内容替换为等长空格，避免 meta-引用误报."""
    # 反引号 inline code
    out = re.sub(r"`[^`]*`", lambda m: " " * len(m.group(0)), line)
    # 中文引号 ""
    out = re.sub(r"\u201c[^\u201d]*\u201d", lambda m: " " * len(m.group(0)), out)
    # 中文单引号 ''
    out = re.sub(r"\u2018[^\u2019]*\u2019", lambda m: " " * len(m.group(0)), out)
    return out


def _scan_banned_words(
    text: str, rule_id: str, words: List[str], message_prefix: str
) -> List[Violation]:
    out: List[Violation] = []
    lines = text.splitlines()
    for idx, line in _iter_lines(text):
        if _is_in_code_fence(lines, idx):
            continue
        masked = _mask_inline_code(line)
        for word in words:
            start = 0
            while True:
                col = masked.find(word, start)
                if col < 0:
                    break
                out.append(
                    Violation(
                        rule_id=rule_id,
                        message=f"{message_prefix}：{word!r}",
                        line=idx,
                        col=col + 1,
                        excerpt=_excerpt(line, col),
                    )
                )
                start = col + len(word)
    return out


# -------- 检测器 --------


def rule_01(text: str) -> RuleResult:
    v = _scan_banned_words(text, "STAR-01", BANNED_WORDS_STAR_01, "空洞价值词")
    return RuleResult("STAR-01", "ok" if not v else "violations", v)


def rule_02(text: str) -> RuleResult:
    v = _scan_banned_words(text, "STAR-02", BANNED_WORDS_STAR_02, "AI 过渡套话")
    return RuleResult("STAR-02", "ok" if not v else "violations", v)


def rule_03(text: str) -> RuleResult:
    """铺垫式开场：只在段首（或首行）命中才告警，避免误杀。"""
    out: List[Violation] = []
    lines = text.splitlines()
    paragraph_start = True
    for idx, line in _iter_lines(text):
        if _is_in_code_fence(lines, idx):
            paragraph_start = False
            continue
        stripped = line.strip()
        if not stripped:
            paragraph_start = True
            continue
        if paragraph_start:
            # 剥离 Markdown 标记（# / > / - / *）与前导空白
            stripped_for_match = re.sub(r"^[#>\-*\s]+", "", line)
            for word in BANNED_WORDS_STAR_03:
                if stripped_for_match.startswith(word):
                    col = line.find(word)
                    out.append(
                        Violation(
                            rule_id="STAR-03",
                            message=f"铺垫式开场：段首出现 {word!r}",
                            line=idx,
                            col=col + 1,
                            excerpt=_excerpt(line, col),
                        )
                    )
        paragraph_start = False
    return RuleResult("STAR-03", "ok" if not out else "violations", out)


def rule_04(text: str) -> RuleResult:
    v = _scan_banned_words(text, "STAR-04", BANNED_WORDS_STAR_04, "讨好式表达")
    return RuleResult("STAR-04", "ok" if not v else "violations", v)


def rule_06(text: str) -> RuleResult:
    """滥用"进行"：匹配 '进行 + 双音节汉字动词'."""
    out: List[Violation] = []
    pattern = re.compile(r"进行(?!到|中|不下去|得)([\u4e00-\u9fff]{2})")
    exempt = {"到一半"}  # 目前兜底
    lines = text.splitlines()
    for idx, line in _iter_lines(text):
        if _is_in_code_fence(lines, idx):
            continue
        line = _mask_inline_code(line)
        for m in pattern.finditer(line):
            verb = m.group(1)
            if verb in exempt:
                continue
            out.append(
                Violation(
                    rule_id="STAR-06",
                    message=f'滥用"进行"：进行{verb} → {verb}',
                    line=idx,
                    col=m.start() + 1,
                    excerpt=_excerpt(line, m.start()),
                )
            )
    return RuleResult("STAR-06", "ok" if not out else "violations", out)


def rule_07(text: str) -> RuleResult:
    """单句内 ≥ 3 个"的" → 违规。"""
    out: List[Violation] = []
    sentence_splitter = re.compile(r"[^。！？!?]+[。！？!?]?")
    lines = text.splitlines()
    for idx, line in _iter_lines(text):
        if _is_in_code_fence(lines, idx):
            continue
        for m in sentence_splitter.finditer(line):
            sentence = m.group(0)
            count = sentence.count("的")
            if count >= 3:
                out.append(
                    Violation(
                        rule_id="STAR-07",
                        message=f'单句内出现 {count} 个"的"，前置定语过重，考虑拆句或后置',
                        line=idx,
                        col=m.start() + 1,
                        excerpt=_excerpt(line, m.start()),
                    )
                )
    return RuleResult("STAR-07", "ok" if not out else "violations", out)


def rule_08(text: str) -> RuleResult:
    v = _scan_banned_words(text, "STAR-08", BANNED_WORDS_STAR_08, "拟人化装饰词")
    return RuleResult("STAR-08", "ok" if not v else "violations", v)


def rule_09(text: str) -> RuleResult:
    """段尾总结句：以段落为单位，检查最后一个非空句是否以总结词开头。"""
    out: List[Violation] = []
    lines = text.splitlines()
    paragraph: List[tuple[int, str]] = []

    def flush(para):
        if not para:
            return []
        last_idx, last_line = para[-1]
        stripped = last_line.strip()
        if not stripped:
            return []
        for opener in PARA_SUMMARY_OPENERS:
            if stripped.startswith(opener):
                return [
                    Violation(
                        rule_id="STAR-09",
                        message=f"段尾总结句：以 {opener!r} 收尾的段落通常可删除最后一句",
                        line=last_idx,
                        col=stripped.find(opener) + 1,
                        excerpt=_excerpt(last_line, 0),
                    )
                ]
        return []

    for idx, line in _iter_lines(text):
        if _is_in_code_fence(lines, idx):
            if paragraph:
                out.extend(flush(paragraph))
                paragraph = []
            continue
        if not line.strip():
            out.extend(flush(paragraph))
            paragraph = []
        else:
            paragraph.append((idx, line))
    out.extend(flush(paragraph))
    return RuleResult("STAR-09", "ok" if not out else "violations", out)


def rule_12(text: str) -> RuleResult:
    """连续 3+ 形容词性四字结构（顿号/逗号分隔）→ 违规。"""
    out: List[Violation] = []
    # 匹配：四字 + [，、] + 四字 + [，、] + 四字
    pattern = re.compile(
        r"([\u4e00-\u9fff]{4})[，、,]\s*([\u4e00-\u9fff]{4})[，、,]\s*([\u4e00-\u9fff]{4})"
    )
    lines = text.splitlines()
    for idx, line in _iter_lines(text):
        if _is_in_code_fence(lines, idx):
            continue
        line = _mask_inline_code(line)
        for m in pattern.finditer(line):
            out.append(
                Violation(
                    rule_id="STAR-12",
                    message=f"连续四字词堆砌：{m.group(1)}、{m.group(2)}、{m.group(3)}",
                    line=idx,
                    col=m.start() + 1,
                    excerpt=_excerpt(line, m.start()),
                )
            )
    return RuleResult("STAR-12", "ok" if not out else "violations", out)


def rule_14(text: str) -> RuleResult:
    """中文段落里混入半角标点。"""
    out: List[Violation] = []
    # 两个汉字之间夹着半角标点（除了代码场景）
    pattern = re.compile(r"([\u4e00-\u9fff])([,.!?])([\u4e00-\u9fff])")
    lines = text.splitlines()
    for idx, line in _iter_lines(text):
        if _is_in_code_fence(lines, idx):
            continue
        # 跳过 inline code 里的内容（简化：整行忽略反引号区间）
        cleaned = re.sub(r"`[^`]*`", lambda m: " " * len(m.group(0)), line)
        for m in pattern.finditer(cleaned):
            punct = m.group(2)
            out.append(
                Violation(
                    rule_id="STAR-14",
                    message=f"中文段落混用半角标点：{punct!r} 应为全角",
                    line=idx,
                    col=m.start(2) + 1,
                    excerpt=_excerpt(line, m.start(2)),
                )
            )
    return RuleResult("STAR-14", "ok" if not out else "violations", out)


# -------- 编排 --------

DETECTORS: List[Callable[[str], RuleResult]] = [
    rule_01,
    rule_02,
    rule_03,
    rule_04,
    rule_06,
    rule_07,
    rule_08,
    rule_09,
    rule_12,
    rule_14,
]

SEMANTIC_RULES = [
    ("STAR-05", "模糊缓冲（需判断是否在谈概率）"),
    ("STAR-10", "机械并列（需判断信息是否真并列）"),
    ("STAR-11", "长定语前置（需中文句法分析）"),
    ("STAR-13", "术语前后不一致（需语义聚合）"),
    ("STAR-15", "列表滥用（需判断信息是否真需并列）"),
    ("STAR-16", "第一句直接入题"),
    ("STAR-17", "不说正确但无用的话"),
    ("STAR-18", "有判断、有立场"),
    ("STAR-19", "看本质，不停在现象"),
    ("STAR-20", "信息密度"),
    ("STAR-21", "用人话，不文绉绉"),
]


def review(text: str) -> List[RuleResult]:
    """返回所有规则的检测结果。机械/结构规则有实际 violations；
    语义规则标记为 status='semantic_pending'."""
    results = [d(text) for d in DETECTORS]
    for rule_id, desc in SEMANTIC_RULES:
        results.append(
            RuleResult(
                rule_id=rule_id,
                status="semantic_pending",
                violations=[],
            )
        )
    return results
