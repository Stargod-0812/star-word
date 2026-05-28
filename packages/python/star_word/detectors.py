"""star-word 检测器（v0.4.1+）.

规则 ID 用中文分组前缀：词-01..08 / 式-01..08 / 气-01..06。
机械 / 结构规则由 review() 直接检测；语义规则交给 LLM-as-judge 或人工。

v0.4.1 重大改进：
- 词表从 packaged rules.yaml 运行时加载，禁止 detectors 与 yaml 漂移
- 修复 ~~~ tilde fence 不识别、未配对 fence 静默屏蔽
- _mask_line 增加裸 URL、Markdown 链接、中文括号 mask
- 词-04 / 词-08 加入"中文字符续接"边界检测
- 式-05 加 tech acronym 白名单 + 主导≥2 + 严格多于变体阈值，URL 裸路径不报
- 词-03 / 式-08 识别 `*` `+` `1.` 列表前缀
- 词-01 grey_zone bypass 修复：ban 上下文出现就报，allow 不能反向豁免
- CRLF 标准化
- 输入大小护栏
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, List, Optional

# 输入字符上限——超过抛错（CLI 在 review() 入口校验）
MAX_INPUT_CHARS = 2_000_000  # ~2MB markdown，远超合理文档


@dataclass(frozen=True)
class Violation:
    rule_id: str
    message: str
    line: int
    col: int
    excerpt: str

    def as_dict(self) -> dict[str, Any]:
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
    fence_map: List[bool]
    masked_lines: List[str]
    notes: List[str] = field(default_factory=list)  # 文档级警告，例如未配对 fence


# -------- 词典：从 rules.yaml 运行时加载，避免与 yaml 漂移 --------


def _load_rule_data() -> dict[str, Any]:
    """加载 packaged rules.yaml。优先 PyYAML，fallback 自带极简 parser。

    v0.4.3: 解析逻辑统一移到 ._yaml.parse_yaml。之前 fallback 是
    `from scripts.build import _parse_yaml`——但 scripts/ 不在 wheel 内，
    pip 装的用户 fallback 失败 → 上层 except Exception 退到 _DEFAULT_WORD_LISTS（仅 6 条）。
    现在 _yaml 模块随包一起，single-source 真正成立。
    """
    yaml_path = Path(__file__).resolve().parent / "data" / "rules.yaml"
    text = yaml_path.read_text(encoding="utf-8")
    from ._yaml import parse_yaml
    return parse_yaml(text)


def _build_word_lists() -> dict[str, List[str]]:
    """从 rules.yaml 抽出每条规则的禁词列表。

    v0.4.3 改：之前 `except Exception → _DEFAULT_WORD_LISTS` 静默掩盖任何错误（含
    architect 发现的 scripts.build import failure）。现在仅 FileNotFoundError
    才走 fallback；解析失败 raise，让用户看到包损坏。
    """
    try:
        data = _load_rule_data()
    except FileNotFoundError:
        # data 文件缺失（极少：包损坏）才走代码内 fallback；其他错误抛出去
        return _DEFAULT_WORD_LISTS
    out: dict[str, List[str]] = {}
    for rule in data.get("rules", []):
        rid = rule.get("id", "")
        if "banned_words" in rule:
            out[rid] = list(rule["banned_words"])
        if "banned_patterns" in rule:
            out[rid] = [
                p.get("word", "") if isinstance(p, dict) else str(p)
                for p in rule["banned_patterns"]
            ]
        if "trigger_starters" in rule:
            out[rid] = list(rule["trigger_starters"])
    return out


def _build_grey_zones() -> dict[str, dict[str, Any]]:
    """从 rules.yaml 加载 grey_zone 上下文。

    yaml 里的 grey_zone 是对 word + note 的描述，但 ban/allow contexts 仍由代码维护
    （从 note 解析复杂、易脆弱）。所以保留代码内 CONTEXT_词_01。
    """
    return CONTEXT_词_01


# 代码内的默认词表（fallback / 兼容旧版直接 import 到的 const）
# v0.4.1 起，正常路径走 _build_word_lists() 从 yaml 读
_DEFAULT_WORD_LISTS = {
    "词-01": [
        "赋能", "闭环", "抓手", "顶层设计", "多维度", "全面提升", "深度赋能",
        "拉通", "加持", "一体化", "场景化",
    ],
    "词-02": [
        "值得注意的是", "值得一提的是", "需要指出的是", "不难发现", "不难看出",
        "毋庸置疑", "众所周知", "综上所述", "总的来说", "总而言之", "一言以蔽之",
        "可以说", "可以这么说", "某种程度上", "在一定程度上", "与此同时",
    ],
    "词-03": [
        "在当今", "随着", "首先让我们", "接下来我将", "接下来，我将", "在本文中",
        "让我们一起来", "让我们先来", "我们先来了解", "在开始之前", "为了更好地",
    ],
    "词-04": [
        "好问题", "这是一个非常好的问题", "这是一个很好的",
        "让我来为您解释", "让我为您解释", "让我来为你解释",
        "希望对你有帮助", "希望能帮到你", "希望这能帮",
        "如有疑问请", "如有疑问，请", "期待您的反馈", "感谢您的阅读",
        "抛砖引玉", "不当之处", "以上就是", "以上便是",
    ],
    "词-08": [
        "稳稳接住", "稳稳地", "默默守护", "悄然绽放", "温柔地", "从容应对",
        "有温度地", "贴心地", "智能地", "聪明地", "巧妙地", "轻松搞定", "一键搞定",
        "丝滑", "丝般顺滑", "如丝般", "保驾护航", "助力腾飞", "赋能前行",
    ],
    "式-01": [
        "综上所述", "总的来说", "总而言之", "一言以蔽之",
        "由此可见", "因此可以看出", "综上",
    ],
}

# 模块加载时一次性构建
_LOADED = _build_word_lists() if Path(__file__).resolve().parent.joinpath("data", "rules.yaml").exists() else {}

BANNED_词_01 = _LOADED.get("词-01") or _DEFAULT_WORD_LISTS["词-01"]
BANNED_词_02 = _LOADED.get("词-02") or _DEFAULT_WORD_LISTS["词-02"]
BANNED_词_03 = _LOADED.get("词-03") or _DEFAULT_WORD_LISTS["词-03"]
BANNED_词_04 = _LOADED.get("词-04") or _DEFAULT_WORD_LISTS["词-04"]
BANNED_词_08 = _LOADED.get("词-08") or _DEFAULT_WORD_LISTS["词-08"]
SUMMARY_CLOSERS = _LOADED.get("式-01") or _DEFAULT_WORD_LISTS["式-01"]


# 上下文感知 grey_zone（保留在代码内：ban/allow contexts 太结构化，从 yaml note 解析不划算）
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


# 式-05 用：常见技术缩写允许大小写变体（URL/url 等不告警）
TECH_ACRONYM_WHITELIST = frozenset({
    "url", "uri", "json", "yaml", "html", "css", "http", "https",
    "api", "sql", "tcp", "udp", "ssh", "ftp", "dns", "rpc", "rest", "grpc",
    "jwt", "oauth", "saml", "csrf", "xss", "cors",
    "id", "uuid", "guid", "md5", "sha", "rsa", "aes",
    "sdk", "ide", "cli", "gui", "ui", "ux",
    "io", "cpu", "gpu", "ram", "ssd", "hdd",
    "tdd", "bdd", "ci", "cd", "ml", "ai", "llm",
    "toml", "csv", "tsv", "xml", "pdf",
})


# 列表 / 引用 / 标题 行前缀正则——不算叙述句
NON_PROSE_LINE_PATTERN = re.compile(r"^\s*([\-\*\+>\|#]\s|\d+[.)、]\s)")


# -------- 预处理 --------


def _precompute_fence_map(lines: List[str]) -> tuple[List[bool], List[str]]:
    """识别 ``` 与 ~~~ fence。

    返回 (fence_map, notes)。fence_map[i]=True 表示该行在围栏内。
    若文档结束时仍 in_fence，notes 加一条警告，并把所有未配对部分回滚到非 fence。
    """
    fence_map = [False] * len(lines)
    notes: List[str] = []
    fence_open_at: Optional[int] = None
    fence_char: Optional[str] = None  # 当前围栏的字符（` 或 ~），开/关必须同字符
    fence_indent: int = 0  # 开 fence 时的缩进，关 fence 必须 ≤ 同缩进
    fence_min_len: int = 0  # 开 fence 的字符数，关必须 ≥ 同长

    fence_pattern = re.compile(r"^(\s*)(`{3,}|~{3,})(.*)$")

    for i, line in enumerate(lines):
        m = fence_pattern.match(line)
        if not m:
            if fence_open_at is not None:
                fence_map[i] = True
            continue

        leading_ws = m.group(1)
        fence_str = m.group(2)
        rest = m.group(3).strip()
        char = fence_str[0]
        length = len(fence_str)
        indent = len(leading_ws.expandtabs(4))

        if fence_open_at is None:
            # 开 fence
            fence_open_at = i
            fence_char = char
            fence_indent = indent
            fence_min_len = length
            fence_map[i] = True
        else:
            # 在 fence 内：检查这行是不是合法关 fence
            same_char = (char == fence_char)
            same_or_shorter_indent = indent <= fence_indent
            long_enough = length >= fence_min_len
            no_info_string = (rest == "")  # 关 fence 不能带 info string
            if same_char and same_or_shorter_indent and long_enough and no_info_string:
                fence_map[i] = True
                fence_open_at = None
                fence_char = None
            else:
                # 不是合法关 fence，仍在 fence 内
                fence_map[i] = True

    if fence_open_at is not None:
        notes.append(
            f"未配对的代码围栏（第 {fence_open_at + 1} 行开），"
            "后续内容被当作普通文本扫描。"
        )
        # 回滚未配对：从开 fence 到末尾全部置 False，让规则正常扫描
        for j in range(fence_open_at, len(lines)):
            fence_map[j] = False

    return fence_map, notes


# 字符类常量
_CHINESE_CHAR = r"[一-鿿㐀-䶿]"


def _mask_line(line: str) -> str:
    """把 inline code / 引号 / HTML 标签 / URL / Markdown 链接 / 中文括号 mask 为等长空格。"""
    out = re.sub(r"`[^`]*`", lambda m: " " * len(m.group(0)), line)
    out = re.sub(r"“[^”]*”", lambda m: " " * len(m.group(0)), out)
    out = re.sub(r"‘[^’]*’", lambda m: " " * len(m.group(0)), out)
    out = re.sub(r"「[^」]*」", lambda m: " " * len(m.group(0)), out)
    out = re.sub(r'"[^"]*"', lambda m: " " * len(m.group(0)), out)
    out = re.sub(r"'[^']*'", lambda m: " " * len(m.group(0)), out)
    out = re.sub(r"<[^>]+>", lambda m: " " * len(m.group(0)), out)
    # Markdown 链接：[text](url) — 保留 text，mask URL 部分
    # v0.4.3 (security N3): 用 [^\[\]] 禁止嵌套 [ 防 quadratic backtracking
    # 老 pattern (\[[^\]]*\])\(([^)]*)\) 在 100KB `[[[...]]]` 上跑 2.7s（pattern 1KB → 64s）
    out = re.sub(
        r"(\[[^\[\]]*\])\(([^)]*)\)",
        lambda m: m.group(1) + "(" + " " * (len(m.group(2))) + ")",
        out,
    )
    # 裸 URL
    out = re.sub(r"https?://\S+", lambda m: " " * len(m.group(0)), out)
    # 中文括号——meta 引用规则名时常用 `（赋能/闭环）` 这种
    out = re.sub(r"（[^）]*）", lambda m: " " * len(m.group(0)), out)
    return out


_ZERO_WIDTH_PATTERN = re.compile(
    # v0.4.3 (security R2 N1): 不只 ZWSP/ZWJ/ZWNJ/WJ/MVS/BOM，再扩展：
    # U+00AD soft hyphen / U+034F CGJ / U+061C ALM / U+115F-1160 韩文 filler /
    # U+17B4-17B5 KH zero-width / U+2028-2029 LS/PS / U+202A-202E 双向控制 /
    # U+2066-2069 隔离符 / U+3164 韩文 filler / U+FE00-FE0F variation selectors /
    # U+FFA0 韩文 filler / U+E0020-E007F tag chars / U+E0100-E01EF variation supp.
    r"[­͏؜ᅟᅠ឴឵᠎​-‏  "
    r"‪-‮⁠-⁤⁦-⁯ㅤ︀-️﻿ﾠ]"
    r"|[\U000e0020-\U000e007f\U000e0100-\U000e01ef]"
)

# v0.4.3 (security N4): ANSI escape + 控制字符
# 攻击者 markdown 嵌 \x1b[2J\x1b[H... 导致 CLI 输出 excerpt 时屏幕清屏 / osc52 剪贴板劫持
_ANSI_AND_CTRL_PATTERN = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]|[\x00-\x08\x0b-\x1f\x7f]")


def _normalize_text(text: str) -> str:
    """标准化换行符，剥 BOM，去 zero-width 字符与 ANSI/控制字符。

    v0.4.2: zero-width 字符（U+200B/200C/200D/2060/180E/FEFF）会绕过词典扫描——
    `赋​能` 在视觉上等价于「赋能」但 .find('赋能') 找不到。
    在最早归一化阶段全部剥掉，让后续规则只看到「真实」字符。
    BOM (FEFF) 也包含在内：在文档中间出现的 BOM 是攻击向量，不是合法编码标记。

    v0.4.3 (security N4): 同步剥 ANSI escape sequences 与 C0/DEL 控制字符。
    Violation.excerpt 直接打到 CLI 终端，攻击者能借此屏幕劫持 / osc52 剪贴板攻击。
    """
    if text.startswith("﻿"):
        text = text[1:]
    text = _ZERO_WIDTH_PATTERN.sub("", text)
    text = _ANSI_AND_CTRL_PATTERN.sub("", text)
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _build_ctx(text: str) -> ScanContext:
    if len(text) > MAX_INPUT_CHARS:
        raise ValueError(
            f"输入超过上限 {MAX_INPUT_CHARS} 字符（实际 {len(text)}）；"
            "拆分文档或调高 MAX_INPUT_CHARS。"
        )
    text = _normalize_text(text)
    lines = text.splitlines()
    fence_map, notes = _precompute_fence_map(lines)
    return ScanContext(
        lines=lines,
        fence_map=fence_map,
        masked_lines=[_mask_line(line) for line in lines],
        notes=notes,
    )


def _excerpt(line: str, col: int, width: int = 80) -> str:
    start = max(0, col - width // 2)
    end = min(len(line), col + width // 2)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(line) else ""
    return f"{prefix}{line[start:end]}{suffix}"


def _is_chinese_neighbor(line: str, idx: int) -> bool:
    """判断索引位置的字符是否是中文（用于词边界检测）。"""
    if idx < 0 or idx >= len(line):
        return False
    ch = line[idx]
    return bool(re.match(_CHINESE_CHAR, ch))


def _scan_banned(
    ctx: ScanContext,
    rule_id: str,
    words: List[str],
    label: str,
    *,
    word_boundary: bool = False,
) -> List[Violation]:
    """字符串扫描；word_boundary=True 时对短词要求严格边界。

    v0.4.3 hybrid 边界：
    - 长度 ≥ 6 的整句套话（让我来为您解释 / 希望对你有帮助 / 这是一个非常好的问题）
      走 substring 直接抓——这种长度不可能在合法中文里被「写好问题」式地误嵌入。
    - 长度 ≤ 5 的短词（好问题 / 抛砖引玉 / 不当之处）走 AND 边界——「写好问题」前后
      都是中文 → AND fail → 不抓；「好问题。」AND pass → 抓。

    word_boundary 适合「好问题」这种 — 防止「你好问题」误中。
    不适合「赋能」这种典型套话单元 — 它常出现在「全面赋能」中，需要被抓。
    """
    LONG_PHRASE_THRESHOLD = 6  # ≥ 此长度直接 substring 抓
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
                # 长套话直接抓；短词在 word_boundary 模式下走 AND
                if word_boundary and len(w) < LONG_PHRASE_THRESHOLD:
                    before_ok = not _is_chinese_neighbor(masked, col - 1)
                    after_ok = not _is_chinese_neighbor(masked, col + len(w))
                    if not (before_ok and after_ok):
                        start = col + len(w)
                        continue
                out.append(Violation(
                    rule_id=rule_id,
                    message=f"{label}：{w!r}",
                    line=i + 1,
                    col=col + 1,
                    excerpt=_excerpt(ctx.lines[i], col),
                ))
                start = col + len(w)
    return out


def _scan_context_aware(
    ctx: ScanContext, rule_id: str, context_map: dict[str, Any], label: str
) -> List[Violation]:
    """grey_zone 上下文感知扫描（修复版）.

    v0.4.1 修复：ban context 命中即报告，allow context 不能反向豁免。
    （v0.4.0 行为：allow 优先 → 套话作者 append "追踪/压测/监控" 即可绕过）
    新行为：句子里同时出现 ban 上下文 → 还是要报。
    """
    out: List[Violation] = []
    for i, masked in enumerate(ctx.masked_lines):
        if ctx.fence_map[i]:
            continue
        for word, contexts in context_map.items():
            ban_ctxs = contexts.get("ban_contexts", [])
            # allow_ctxs 留在 yaml 里作文档参考，不再参与判定（v0.4.0 的 bypass 漏洞）
            start = 0
            while True:
                col = masked.find(word, start)
                if col < 0:
                    break
                window_start = max(0, col - 4)
                window_end = min(len(masked), col + len(word) + 4)
                window = masked[window_start:window_end]

                hit_ban = any(bc in window for bc in ban_ctxs)
                # 注：v0.4.1 不再用 allow 反向豁免（之前的 bypass 漏洞）
                # 仅 ban 上下文出现就报，allow_ctxs 列在 yaml 里供文档参考

                if hit_ban:
                    # ban 命中即报，不被 allow 豁免
                    out.append(Violation(
                        rule_id=rule_id,
                        message=f"{label}（套话语境）：{word!r}",
                        line=i + 1,
                        col=col + 1,
                        excerpt=_excerpt(ctx.lines[i], col),
                    ))
                # 不在 allow 也不在 ban 的情况：保守不报
                start = col + len(word)
    return out


# -------- 规则实现 --------


def 词_01(ctx: ScanContext) -> RuleResult:
    """空洞价值词：默认禁词列表 + grey_zone 上下文感知。"""
    v = _scan_banned(ctx, "词-01", BANNED_词_01, "空洞价值词")
    v.extend(_scan_context_aware(ctx, "词-01", CONTEXT_词_01, "空洞价值词"))
    return RuleResult("词-01", "ok" if not v else "violations", v)


def 词_02(ctx: ScanContext) -> RuleResult:
    v = _scan_banned(ctx, "词-02", BANNED_词_02, "AI 过渡套话")
    return RuleResult("词-02", "ok" if not v else "violations", v)


def 词_03(ctx: ScanContext) -> RuleResult:
    """铺垫式开场：在段首或 markdown 列表/编号项首命中才告警。"""
    out: List[Violation] = []
    paragraph_start = True
    list_prefix_re = re.compile(r"^(?:[#>\-*+]+\s+|\d+[.)、]\s+)+")
    for i, line in enumerate(ctx.lines):
        if ctx.fence_map[i]:
            paragraph_start = False
            continue
        stripped = line.strip()
        if not stripped:
            paragraph_start = True
            continue
        if paragraph_start:
            leading = list_prefix_re.sub("", line).lstrip()
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
    """讨好式表达：用词边界检测避免「你好问题大家」之类的子串误报。"""
    v = _scan_banned(ctx, "词-04", BANNED_词_04, "讨好式表达", word_boundary=True)
    return RuleResult("词-04", "ok" if not v else "violations", v)


def 词_06(ctx: ScanContext) -> RuleResult:
    """滥用『进行』：'进行 + 双音节汉字动词'。"""
    out: List[Violation] = []
    pattern = re.compile(r"进行(?!到|中|不下去|得)([一-鿿]{2})")
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
    """单句内 ≥ 3 个『的』。分号/冒号/句号/叹号/问号都算句子边界。"""
    out: List[Violation] = []
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
    """拟人化装饰：词边界检测，但绝大多数本来就有边界（不是中文复合词），所以宽松。"""
    v = _scan_banned(ctx, "词-08", BANNED_词_08, "拟人化装饰词")
    return RuleResult("词-08", "ok" if not v else "violations", v)


def 式_01(ctx: ScanContext) -> RuleResult:
    """段尾总结句。"""
    out: List[Violation] = []
    paragraph: List[int] = []

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
    """连续 4+ 四字结构（顿号/逗号分隔）。"""
    out: List[Violation] = []
    pattern = re.compile(
        r"([一-鿿]{4})[，、,]\s*"
        r"([一-鿿]{4})[，、,]\s*"
        r"([一-鿿]{4})[，、,]\s*"
        r"([一-鿿]{4})"
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


def 式_05(ctx: ScanContext) -> RuleResult:
    """术语前后不一致（v0.4.1 修复版）.

    v0.4.0 的问题：1+1 假阳性、URL 路径段误报、tech acronym 误报。
    v0.4.1 修复：
    - tech acronym 白名单（URL/url、JSON/json 等）跳过
    - 主导写法必须 ≥ 2 次出现，且严格多于变体
    - URL 已在 _mask_line 阶段被 mask，URL 路径段的标识符不再扫到
    """
    ident_pattern = re.compile(r"[A-Za-z][A-Za-z0-9_]{2,}")
    occurrences: dict[str, dict[str, list[tuple[int, int]]]] = {}

    for i, masked in enumerate(ctx.masked_lines):
        if ctx.fence_map[i]:
            continue
        for m in ident_pattern.finditer(masked):
            term = m.group(0)
            key = term.lower()
            if key in TECH_ACRONYM_WHITELIST:
                continue
            occurrences.setdefault(key, {}).setdefault(term, []).append((i, m.start()))

    out: List[Violation] = []
    for _key, variants in occurrences.items():
        if len(variants) < 2:
            continue
        sorted_variants = sorted(variants.items(), key=lambda kv: -len(kv[1]))
        dominant_term, dominant_locs = sorted_variants[0]
        dominant_count = len(dominant_locs)

        # 主导必须 ≥ 2 次出现
        if dominant_count < 2:
            continue

        for variant, locs in sorted_variants[1:]:
            variant_count = len(locs)
            # 变体必须严格少于主导
            if variant_count >= dominant_count:
                continue
            line_idx, col = locs[0]
            out.append(Violation(
                rule_id="式-05",
                message=(
                    f"术语不一致：{variant!r}（{variant_count} 次）与主导写法 "
                    f"{dominant_term!r}（{dominant_count} 次）混用"
                ),
                line=line_idx + 1,
                col=col + 1,
                excerpt=_excerpt(ctx.lines[line_idx], col),
            ))
    return RuleResult("式-05", "ok" if not out else "violations", out)


def 式_06(ctx: ScanContext) -> RuleResult:
    """中文段落里混入半角标点。"""
    out: List[Violation] = []
    pattern = re.compile(r"([一-鿿])([,.!?])([一-鿿])")
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


def 式_08(ctx: ScanContext) -> RuleResult:
    """句长方差过低（v0.4.1：识别更多列表/标题/引用前缀）。"""
    out: List[Violation] = []
    sent_splitter = re.compile(r"[^。！？!?\n]+[。！？!?]?")
    paragraph: List[int] = []

    def _is_prose_line(idx: int) -> bool:
        if ctx.fence_map[idx]:
            return False
        line = ctx.lines[idx].strip()
        if not line:
            return False
        if NON_PROSE_LINE_PATTERN.match(line):
            return False
        return True

    def _check_paragraph(line_indices: List[int]) -> None:
        if not line_indices:
            return
        lengths: List[int] = []
        for idx in line_indices:
            if not _is_prose_line(idx):
                continue
            line = ctx.lines[idx].strip()
            for m in sent_splitter.finditer(line):
                s = m.group(0).strip()
                if len(s) >= 4:
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
    # 把文档级 notes 暴露在第一个 result 上（兼容性最小破坏）
    if ctx.notes and results:
        # 用一个特殊 rule_id "doc:notes" 暂存
        results.append(RuleResult(
            rule_id="doc:notes",
            status="notes",
            violations=[
                Violation(
                    rule_id="doc:notes",
                    message=note,
                    line=0,
                    col=0,
                    excerpt="",
                )
                for note in ctx.notes
            ],
        ))
    return results
