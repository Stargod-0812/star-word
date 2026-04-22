"""star-word 检测器（v0.2）.

规则 ID 使用中文分组前缀：词-01..08 / 式-01..07 / 气-01..06。
机械 / 结构规则由 review() 直接检测；语义规则标记为 sense-pending 交给宿主模型或人工。

性能：_precompute_fence_map 在扫描文档时只计算一次，避免每条规则 O(N²) 重扫。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, List

from .generated_rules import (
    ALL_RULE_IDS,
    BANNED_PATTERNS,
    BANNED_WORDS,
    REGEX_PATTERNS,
    RULE_TITLES,
    SEMANTIC_RULES,
    THRESHOLDS,
    TRIGGER_STARTERS,
)


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


# -------- 由 rules.yaml 生成的规则配置 --------

BANNED_词_01 = BANNED_WORDS["词-01"]
BANNED_词_02 = BANNED_WORDS["词-02"]
BANNED_词_03 = BANNED_PATTERNS["词-03"]
BANNED_词_04 = BANNED_WORDS["词-04"]
BANNED_词_08 = BANNED_WORDS["词-08"]
JINXING_PATTERN = re.compile(REGEX_PATTERNS["词-06"])
THRESHOLD_词_07 = THRESHOLDS["词-07"]
THRESHOLD_式_04 = THRESHOLDS["式-04"]
SUMMARY_CLOSERS = TRIGGER_STARTERS["式-01"]
SEMANTIC_RULE_IDS = {rule_id for rule_id, _title in SEMANTIC_RULES}
SENTENCE_ENDERS = "。！？!?"


# -------- 预处理 --------


def _match_fence_delimiter(line: str) -> str | None:
    stripped = line.lstrip()
    match = re.match(r"(`{3,}|~{3,})", stripped)
    if not match:
        return None
    return match.group(1)[0]


def _precompute_fence_map(lines: List[str]) -> List[bool]:
    """一次遍历，算出每行是否在 fenced code block 之内。"""
    fence_map = [False] * len(lines)
    fence_char: str | None = None
    for i, line in enumerate(lines):
        delimiter = _match_fence_delimiter(line)
        if delimiter is not None:
            if fence_char is None:
                fence_char = delimiter
            elif fence_char == delimiter:
                fence_char = None
            fence_map[i] = True
            continue
        fence_map[i] = fence_char is not None
    return fence_map


def _mask_line(line: str) -> str:
    """把 inline code / 中英文引号 / 中文引号内的内容替换为等长空格，避免 meta 引用误报。"""
    out = re.sub(r"`[^`]*`", lambda m: " " * len(m.group(0)), line)
    out = re.sub(r"\u201c[^\u201d]*\u201d", lambda m: " " * len(m.group(0)), out)  # 中文 ""
    out = re.sub(r"\u2018[^\u2019]*\u2019", lambda m: " " * len(m.group(0)), out)  # 中文 ''
    out = re.sub(r"「[^」]*」", lambda m: " " * len(m.group(0)), out)             # 日式/中文 「」
    out = re.sub(r"『[^』]*』", lambda m: " " * len(m.group(0)), out)
    out = re.sub(r"《[^》]*》", lambda m: " " * len(m.group(0)), out)
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


def _is_han(char: str | None) -> bool:
    return bool(char) and bool(re.fullmatch(r"[\u4e00-\u9fff]", char))


def _is_ascii_word_char(char: str | None) -> bool:
    return bool(char) and char.isascii() and (char.isalnum() or char in {"_", "/"})


def _prev_non_space(text: str, idx: int) -> tuple[str | None, int | None]:
    pos = idx
    while pos >= 0:
        if not text[pos].isspace():
            return text[pos], pos
        pos -= 1
    return None, None


def _next_non_space(text: str, idx: int) -> tuple[str | None, int | None]:
    pos = idx
    while pos < len(text):
        if not text[pos].isspace():
            return text[pos], pos
        pos += 1
    return None, None


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
    for i, masked in enumerate(ctx.masked_lines):
        if ctx.fence_map[i]:
            continue
        for m in JINXING_PATTERN.finditer(masked):
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
    current_chars: List[str] = []
    start_line: int | None = None
    start_col: int | None = None

    def flush_sentence() -> None:
        nonlocal current_chars, start_line, start_col
        if start_line is None or start_col is None:
            current_chars = []
            return
        sentence = "".join(current_chars)
        count = sentence.count("的")
        if count >= THRESHOLD_词_07:
            out.append(Violation(
                rule_id="词-07",
                message=f"单句内出现 {count} 个『的』，前置定语过重",
                line=start_line,
                col=start_col,
                excerpt=_excerpt(ctx.lines[start_line - 1], start_col - 1),
            ))
        current_chars = []
        start_line = None
        start_col = None

    for line_index, masked in enumerate(ctx.masked_lines, start=1):
        if ctx.fence_map[line_index - 1] or not masked.strip():
            flush_sentence()
            continue
        for col, char in enumerate(masked, start=1):
            if start_line is None:
                if char.isspace():
                    continue
                start_line = line_index
                start_col = col
            current_chars.append(char)
            if char in SENTENCE_ENDERS:
                flush_sentence()
        if current_chars:
            current_chars.append("\n")
    flush_sentence()
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
    groups = [r"([\u4e00-\u9fff]{4})"]
    groups.extend(r"[，、,]\s*([\u4e00-\u9fff]{4})" for _ in range(THRESHOLD_式_04 - 1))
    pattern = re.compile("".join(groups))
    for i, masked in enumerate(ctx.masked_lines):
        if ctx.fence_map[i]:
            continue
        for m in pattern.finditer(masked):
            stacked = "、".join(m.groups())
            out.append(Violation(
                rule_id="式-04",
                message=f"四字词堆砌：{stacked}",
                line=i + 1,
                col=m.start() + 1,
                excerpt=_excerpt(ctx.lines[i], m.start()),
            ))
    return RuleResult("式-04", "ok" if not out else "violations", out)


def 式_06(ctx: ScanContext) -> RuleResult:
    """中文段落里混入半角标点."""
    out: List[Violation] = []
    for i, masked in enumerate(ctx.masked_lines):
        if ctx.fence_map[i]:
            continue
        if not re.search(r"[\u4e00-\u9fff]", masked):
            continue
        for col, punct in enumerate(masked):
            if punct not in ",.!?":
                continue
            left_char, left_pos = _prev_non_space(masked, col - 1)
            right_char, _right_pos = _next_non_space(masked, col + 1)
            if punct == "." and left_char and right_char and left_char.isdigit() and right_char.isdigit():
                continue
            if _is_ascii_word_char(left_char) and _is_ascii_word_char(right_char):
                continue
            if not any((_is_han(left_char), _is_han(right_char), right_char is None and left_pos is not None and re.search(r"[\u4e00-\u9fff]", masked[:left_pos + 1]))):
                continue
            out.append(Violation(
                rule_id="式-06",
                message=f"中文段落混用半角标点：{punct!r} 应为全角",
                line=i + 1,
                col=col + 1,
                excerpt=_excerpt(ctx.lines[i], col),
            ))
    return RuleResult("式-06", "ok" if not out else "violations", out)


IMPLEMENTED_DETECTORS: dict[str, Callable[[ScanContext], RuleResult]] = {
    "词-01": 词_01,
    "词-02": 词_02,
    "词-03": 词_03,
    "词-04": 词_04,
    "词-06": 词_06,
    "词-07": 词_07,
    "词-08": 词_08,
    "式-01": 式_01,
    "式-04": 式_04,
    "式-06": 式_06,
}


def review(text: str) -> List[RuleResult]:
    """按 rules.yaml 顺序返回所有规则的检测结果。"""
    ctx = _build_ctx(text)
    results: List[RuleResult] = []
    for rule_id in ALL_RULE_IDS:
        detector = IMPLEMENTED_DETECTORS.get(rule_id)
        if detector is not None:
            results.append(detector(ctx))
            continue
        if rule_id in SEMANTIC_RULE_IDS:
            results.append(RuleResult(rule_id=rule_id, status="sense-pending"))
            continue
        raise RuntimeError(
            f"规则 {rule_id}（{RULE_TITLES[rule_id]}）在 rules.yaml 中存在，但 detectors.py 没有实现"
        )
    return results
