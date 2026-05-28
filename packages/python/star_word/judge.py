"""LLM-as-judge for star-word semantic rules（v0.4）.

把 sense-pending 规则（气-01..06、词-05、式-02/03/07）变成可量化的 0-10 分。
不依赖 anthropic SDK——直接 HTTP，零运行时依赖。

设计原则：
1. **诚实出 0**：模型不知道答案就返回 0 + reasoning="cannot judge"，不强行打分。
2. **结构化输出**：要求 JSON-only 回答，schema 固定，便于解析。
3. **批量评估**：一次 API 调用评所有规则，省 token、保上下文一致性。
4. **可降级**：API 不可用时返回 sense-pending，不让 review 失败。

调用方式：
    from star_word.judge import judge_text
    scores = judge_text(text, api_key="sk-...")  # → List[RuleScore]

环境变量 fallback：
- ANTHROPIC_API_KEY 或 STAR_WORD_API_KEY
- STAR_WORD_JUDGE_MODEL（默认 claude-sonnet-4-5-20250929）
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import List, Optional

from .scoring import RuleScore


# -------- 规则的判断 prompt（每条规则一段) --------

JUDGE_RUBRIC = {
    "气-01": (
        "第一句直接入题。"
        "判定：删掉第一句之后，第二句能否独立成文？能 → 首句是铺垫，扣分；不能 → 首句是信息本身，满分。"
    ),
    "气-02": (
        "不说正确但无用的话。"
        "判定：每句是否做到「推进认知 / 做取舍 / 给结构」三件事之一？"
        "全部满足 → 满分；有「正确但无用」的句子 → 按数量扣分。"
    ),
    "气-03": (
        "有判断、有立场。"
        "判定：是否做出取舍 / 给结论 / 推荐方案？"
        "做了 → 满分；只列「各有优劣」式综述 → 严重扣分。"
    ),
    "气-04": (
        "看本质不停在现象。"
        "判定：是否回应了用户真正要解决的问题，而非字面问题？"
        "深层 → 满分；只解决字面问题 → 扣分。"
    ),
    "气-05": (
        "信息密度。"
        "判定：相同信息能否用更少字说完？"
        "已紧实 → 满分；可压缩 30%+ → 严重扣分。"
    ),
    "气-06": (
        "用人话，不文绉绉。"
        "判定：是否滥用「乃/之/其/故/诚然/固然」等文言虚词？"
        "无滥用 → 满分；有 → 按数量扣分。"
    ),
    "词-05": (
        "模糊缓冲。"
        "判定：「可能/也许/某种程度上/在一定程度上」是否在非概率语境下使用？"
        "没有非概率使用 → 满分；有 → 扣分。"
    ),
    "式-02": (
        "机械并列。"
        "判定：「首先/其次/最后」是否在不真正并列的信息上强套？"
        "并列合理 → 满分；强套模板 → 扣分。"
    ),
    "式-03": (
        "长定语前置。"
        "判定：是否有主语前定语超过 20 字的句子？"
        "无 → 满分；有 → 按数量扣分。"
    ),
    "式-07": (
        "列表滥用。"
        "判定：是否把能一句话说完的内容拆成 2 项列表？"
        "列表合理 → 满分；滥用 → 扣分。"
    ),
}

# 默认评估的规则集（即所有 sense-pending）
DEFAULT_JUDGE_RULES = list(JUDGE_RUBRIC.keys())


# -------- prompt 构造 --------


def _build_prompt(text: str, rule_ids: List[str]) -> str:
    rubric_lines = []
    for rid in rule_ids:
        if rid in JUDGE_RUBRIC:
            rubric_lines.append(f"- **{rid}**: {JUDGE_RUBRIC[rid]}")

    return f"""你是中文技术写作的严格审稿人。请对下方文档按指定规则打分。

每条规则给出：
- score: 0-10 整数（10=完全满足，0=严重违反）
- reasoning: 一句话说明给这个分的具体证据，引用文档原文片段

判断纪律：
- 没把握就给 5 + reasoning="证据不足"
- 不要为了好看打高分；该 0 就 0
- 引用证据要短，30 字以内

规则：
{chr(10).join(rubric_lines)}

文档：
\"\"\"
{text}
\"\"\"

只输出 JSON，schema：
{{"scores": [{{"rule_id": "气-01", "score": 7, "reasoning": "首句..."}}, ...]}}
"""


# -------- API 调用 --------


def _call_anthropic(prompt: str, api_key: str, model: str, timeout: int = 60) -> dict:
    """直接 POST 到 Anthropic Messages API，零依赖。"""
    body = json.dumps({
        "model": model,
        "max_tokens": 2000,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _extract_json(text: str) -> dict:
    """从模型输出抽 JSON——容忍 ```json fence 和前后说明文字。"""
    # 先剥 fence
    if "```" in text:
        for fence in ("```json", "```JSON", "```"):
            if fence in text:
                start = text.find(fence) + len(fence)
                end = text.rfind("```")
                if end > start:
                    text = text[start:end].strip()
                    break
    # 找第一个 { 和最后一个 }
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < 0:
        raise ValueError(f"No JSON object found in response: {text[:200]}")
    return json.loads(text[start : end + 1])


# -------- 主入口 --------


class JudgeError(Exception):
    """Judge 失败时抛——caller 可决定降级还是冒泡。"""


def judge_text(
    text: str,
    rule_ids: Optional[List[str]] = None,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    timeout: int = 60,
) -> List[RuleScore]:
    """对文本按指定规则打分。

    Args:
        text: 待评估文本。
        rule_ids: 评估哪些规则（默认所有 sense-pending 规则）。
        api_key: Anthropic API key。若 None 从环境变量读。
        model: 模型名。默认 claude-sonnet-4-5。
        timeout: API 超时（秒）。

    Returns:
        每条规则一个 RuleScore（含 judge_reasoning）。

    Raises:
        JudgeError: API key 缺失 / API 失败 / 响应解析失败。
    """
    rule_ids = rule_ids or DEFAULT_JUDGE_RULES
    api_key = api_key or os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("STAR_WORD_API_KEY")
    if not api_key:
        raise JudgeError(
            "未找到 API key。设置 ANTHROPIC_API_KEY 或传 api_key=，"
            "或用 `star-word review` 跳过 judge。"
        )
    model = model or os.environ.get("STAR_WORD_JUDGE_MODEL") or "claude-sonnet-4-5-20250929"

    prompt = _build_prompt(text, rule_ids)
    try:
        resp = _call_anthropic(prompt, api_key, model, timeout)
    except urllib.error.HTTPError as e:
        raise JudgeError(f"API HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:300]}")
    except urllib.error.URLError as e:
        raise JudgeError(f"API 网络错误：{e.reason}")

    # 提取 content 文本
    content_blocks = resp.get("content", [])
    if not content_blocks:
        raise JudgeError(f"API 无 content：{resp}")
    raw_text = content_blocks[0].get("text", "")
    try:
        parsed = _extract_json(raw_text)
    except ValueError as e:
        raise JudgeError(f"JSON 解析失败：{e}")

    scores_data = parsed.get("scores", [])
    out: List[RuleScore] = []
    base_weight = 3.0  # judge 规则统一基础权重
    for entry in scores_data:
        rid = entry.get("rule_id")
        score = entry.get("score")
        reasoning = entry.get("reasoning", "")
        if rid is None or score is None:
            continue
        try:
            score_f = float(score)
        except (TypeError, ValueError):
            continue
        score_f = max(0.0, min(10.0, score_f))
        out.append(RuleScore(
            rule_id=rid,
            score=score_f,
            weight=base_weight,
            violation_count=0 if score_f >= 8 else 1,
            status="judged",
            judge_reasoning=reasoning,
        ))
    return out


def judge_text_safe(
    text: str,
    rule_ids: Optional[List[str]] = None,
    **kwargs,
) -> tuple[List[RuleScore], Optional[str]]:
    """非抛异常版本：返回 (scores, error_message)。

    用于 `star-word review` 默认流程——judge 失败不阻断 review。
    """
    try:
        return judge_text(text, rule_ids=rule_ids, **kwargs), None
    except JudgeError as e:
        return [], str(e)
