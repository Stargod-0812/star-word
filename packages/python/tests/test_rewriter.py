"""rewriter 测试——mock-based，不打真实 API."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from star_word import _llm, rewriter
from star_word.detectors import RuleResult, Violation


def _mock_resp(rewrites: list) -> dict:
    return {
        "content": [{"type": "text", "text": json.dumps({"rewrites": rewrites})}]
    }


def _make_results_with_violation(text: str, line: int, rule_id: str = "词-08", message: str = "test") -> list:
    """构造 RuleResult 列表，单条违规。"""
    v = Violation(rule_id=rule_id, message=message, line=line, col=1, excerpt="...")
    return [RuleResult(rule_id=rule_id, status="violations", violations=[v])]


def test_no_violations_returns_empty():
    """无违规直接返回空。"""
    text = "干净的文档。"
    results = []
    out = rewriter.suggest_rewrites(text, results, api_key="fake-key")
    assert out == []


def test_no_api_key_raises():
    """缺 API key 抛 RewriteError。"""
    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(rewriter.RewriteError, match="API key"):
            rewriter.suggest_rewrites("text", [], api_key=None)


def test_simple_rewrite_returns_suggestion():
    text = "稳稳地接住流量。"
    results = _make_results_with_violation(text, 1, "词-08", "拟人化")
    fake = _mock_resp([
        {"key": "L1:词-08", "suggested": "QPS 超阈值返回缓存版本。", "reason": "去拟人化"},
    ])
    with patch.object(_llm, "call_anthropic", return_value=fake):
        out = rewriter.suggest_rewrites(text, results, api_key="fake-key")
    assert len(out) == 1
    assert out[0].rule_id == "词-08"
    assert out[0].suggested == "QPS 超阈值返回缓存版本。"
    assert out[0].reason == "去拟人化"
    assert out[0].line == 1


def test_rewrite_uses_key_not_position_zip():
    """改写关联应靠 key，不靠 list 位置。模型乱序返回也能正确关联。"""
    text = "L1 violation\nL2 violation\nL3 violation"
    results = [
        RuleResult(rule_id="词-08", status="violations", violations=[
            Violation("词-08", "v1", 1, 1, "x"),
            Violation("词-08", "v2", 2, 1, "x"),
            Violation("词-08", "v3", 3, 1, "x"),
        ]),
    ]
    # 模型反序返回
    fake = _mock_resp([
        {"key": "L3:词-08", "suggested": "改写3", "reason": "r3"},
        {"key": "L1:词-08", "suggested": "改写1", "reason": "r1"},
        {"key": "L2:词-08", "suggested": "改写2", "reason": "r2"},
    ])
    with patch.object(_llm, "call_anthropic", return_value=fake):
        out = rewriter.suggest_rewrites(text, results, api_key="fake-key")
    # 关联应正确：line 1 → 改写1, line 2 → 改写2, line 3 → 改写3
    by_line = {s.line: s.suggested for s in out}
    assert by_line[1] == "改写1"
    assert by_line[2] == "改写2"
    assert by_line[3] == "改写3"


def test_rewrite_skips_unknown_keys():
    """模型瞎编 key 应被丢弃，不污染输出。"""
    text = "violation"
    results = _make_results_with_violation(text, 1)
    fake = _mock_resp([
        {"key": "L99:词-99", "suggested": "fake", "reason": "evil"},
        {"key": "L1:词-08", "suggested": "real", "reason": "ok"},
    ])
    with patch.object(_llm, "call_anthropic", return_value=fake):
        out = rewriter.suggest_rewrites(text, results, api_key="fake-key")
    assert len(out) == 1
    assert out[0].suggested == "real"


def test_rewrite_skips_empty_suggested():
    """suggested 为空应被跳过。"""
    text = "violation"
    results = _make_results_with_violation(text, 1)
    fake = _mock_resp([
        {"key": "L1:词-08", "suggested": "", "reason": "empty"},
    ])
    with patch.object(_llm, "call_anthropic", return_value=fake):
        out = rewriter.suggest_rewrites(text, results, api_key="fake-key")
    assert out == []


def test_rewrite_strips_control_chars():
    """suggested / reason 里的 ANSI 应被清理。"""
    text = "violation"
    results = _make_results_with_violation(text, 1)
    fake = _mock_resp([
        {"key": "L1:词-08", "suggested": "\x1b[31m改写\x1b[0m", "reason": "\x07alert"},
    ])
    with patch.object(_llm, "call_anthropic", return_value=fake):
        out = rewriter.suggest_rewrites(text, results, api_key="fake-key")
    assert "\x1b" not in out[0].suggested
    assert "\x07" not in out[0].reason


def test_rewrite_truncates_long():
    """超长 suggested 应被截到 max_len。"""
    text = "violation"
    results = _make_results_with_violation(text, 1)
    fake = _mock_resp([
        {"key": "L1:词-08", "suggested": "x" * 10000, "reason": "ok"},
    ])
    with patch.object(_llm, "call_anthropic", return_value=fake):
        out = rewriter.suggest_rewrites(text, results, api_key="fake-key")
    assert len(out[0].suggested) <= 500


def test_rewrite_max_violations_limit():
    """超过 max_violations 应只取前 N 条。"""
    text = "\n".join(f"line{i}" for i in range(50))
    results = [RuleResult(
        rule_id="词-08",
        status="violations",
        violations=[Violation("词-08", "v", i + 1, 1, "x") for i in range(50)],
    )]
    fake = _mock_resp([
        {"key": f"L{i+1}:词-08", "suggested": f"改{i+1}", "reason": "r"}
        for i in range(50)
    ])
    with patch.object(_llm, "call_anthropic", return_value=fake):
        out = rewriter.suggest_rewrites(text, results, api_key="fake-key", max_violations=5)
    # 只关联前 5 条 violation 的 key
    keys = {f"L{s.line}:词-08" for s in out}
    assert keys.issubset({f"L{i+1}:词-08" for i in range(5)})


def test_rewrite_dedupes_keys():
    """同一 key 的多次改写只取第一个。"""
    text = "violation"
    results = _make_results_with_violation(text, 1)
    fake = _mock_resp([
        {"key": "L1:词-08", "suggested": "first", "reason": "1"},
        {"key": "L1:词-08", "suggested": "second", "reason": "2"},
    ])
    with patch.object(_llm, "call_anthropic", return_value=fake):
        out = rewriter.suggest_rewrites(text, results, api_key="fake-key")
    assert len(out) == 1
    assert out[0].suggested == "first"


def test_rewrite_safe_swallows_error():
    """suggest_rewrites_safe 不应抛。"""
    with patch.dict("os.environ", {}, clear=True):
        out, err = rewriter.suggest_rewrites_safe("text", [], api_key=None)
    assert out == []
    assert err is not None
    assert "API key" in err


def test_rewrite_input_size_limit():
    """超大输入应被拒绝。"""
    text = "\n".join("line" for _ in range(1000))
    results = [RuleResult(
        rule_id="词-08", status="violations",
        violations=[Violation("词-08", "v", 1, 1, "x")],
    )]
    with pytest.raises(rewriter.RewriteError, match="超过上限"):
        rewriter.suggest_rewrites(text, results, api_key="fake-key", max_input_chars=10)


def test_rewrite_handles_malformed_response():
    """rewrites 不是 list 应抛 RewriteError。"""
    text = "v"
    results = _make_results_with_violation(text, 1)
    fake = {"content": [{"type": "text", "text": '{"rewrites": "not a list"}'}]}
    with patch.object(_llm, "call_anthropic", return_value=fake):
        with pytest.raises(rewriter.RewriteError, match="不是列表"):
            rewriter.suggest_rewrites(text, results, api_key="fake-key")


def test_rewrite_handles_no_text_block():
    """API 返回无 text 块应抛错。"""
    text = "v"
    results = _make_results_with_violation(text, 1)
    fake = {"content": []}
    with patch.object(_llm, "call_anthropic", return_value=fake):
        with pytest.raises(rewriter.RewriteError, match="无 text"):
            rewriter.suggest_rewrites(text, results, api_key="fake-key")
