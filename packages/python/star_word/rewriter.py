"""LLM-based rewriter（v0.4）.

把违规位置 + 上下文丢给模型，要求改写成符合 star-word 规则的版本。
和 judge 共用 anthropic HTTP 调用，零依赖。

输出 unified diff 风格——便于审阅和应用。
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import List, Optional

from .detectors import RuleResult, Violation


@dataclass
class RewriteSuggestion:
    line: int
    original: str
    suggested: str
    reason: str


REWRITE_SYSTEM_PROMPT = """你是中文技术写作改写器。给定违反 star-word 规则的句子，输出符合规则的改写版本。

改写原则：
1. 保留原意 100%——不增不减信息
2. 第一句直接入题，不铺垫
3. 用人话，不文绉绉
4. 删除空洞价值词、AI 过渡套话、讨好式表达、拟人装饰词
5. 句子长度有变化——长句铺逻辑，短句下结论

只输出 JSON：
{"rewrites": [{"original": "原句", "suggested": "改写", "reason": "为什么这么改"}]}"""


def _call_anthropic(prompt: str, api_key: str, model: str, timeout: int = 60) -> dict:
    body = json.dumps({
        "model": model,
        "max_tokens": 4000,
        "system": REWRITE_SYSTEM_PROMPT,
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
    if "```" in text:
        for fence in ("```json", "```JSON", "```"):
            if fence in text:
                start = text.find(fence) + len(fence)
                end = text.rfind("```")
                if end > start:
                    text = text[start:end].strip()
                    break
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < 0:
        raise ValueError(f"No JSON found: {text[:200]}")
    return json.loads(text[start : end + 1])


class RewriteError(Exception):
    pass


def suggest_rewrites(
    text: str,
    results: List[RuleResult],
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    max_violations: int = 20,
) -> List[RewriteSuggestion]:
    """对 review 出来的违规处生成改写建议。

    只取前 N 处违规——避免长文档把 prompt 撑爆。
    """
    api_key = api_key or os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("STAR_WORD_API_KEY")
    if not api_key:
        raise RewriteError("未找到 API key。设置 ANTHROPIC_API_KEY。")
    model = model or os.environ.get("STAR_WORD_REWRITER_MODEL") or "claude-sonnet-4-5-20250929"

    # 收集所有违规，附带原句
    lines = text.splitlines()
    violations: List[tuple[Violation, str]] = []
    for r in results:
        if r.status != "violations":
            continue
        for v in r.violations:
            if v.line - 1 < len(lines):
                violations.append((v, lines[v.line - 1]))
    if not violations:
        return []
    violations = violations[:max_violations]

    # 构造 prompt
    sentences = []
    for v, line in violations:
        sentences.append(f"- 违反 {v.rule_id}（{v.message}）: {line}")
    prompt = "改写以下违规句子：\n\n" + "\n".join(sentences)

    try:
        resp = _call_anthropic(prompt, api_key, model)
    except urllib.error.HTTPError as e:
        raise RewriteError(f"API HTTP {e.code}")
    except urllib.error.URLError as e:
        raise RewriteError(f"网络错误：{e.reason}")

    content = resp.get("content", [])
    if not content:
        raise RewriteError("API 无 content")
    raw = content[0].get("text", "")
    try:
        parsed = _extract_json(raw)
    except ValueError as e:
        raise RewriteError(f"JSON 解析失败：{e}")

    rewrites_data = parsed.get("rewrites", [])
    out: List[RewriteSuggestion] = []
    for entry, (v, line) in zip(rewrites_data, violations):
        original = entry.get("original", line)
        suggested = entry.get("suggested", "")
        reason = entry.get("reason", "")
        if suggested:
            out.append(RewriteSuggestion(
                line=v.line,
                original=original,
                suggested=suggested,
                reason=reason,
            ))
    return out
