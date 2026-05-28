"""judge 模块测试——全部用 mock，不打真实 API."""

from __future__ import annotations

import io
import json
from unittest.mock import patch

import pytest

from star_word import judge


# -------- prompt 构造 --------


def test_build_prompt_includes_all_rules():
    p = judge._build_prompt("测试文本", ["气-01", "气-02"])
    assert "气-01" in p
    assert "气-02" in p
    assert "测试文本" in p


def test_build_prompt_skips_unknown_rules():
    p = judge._build_prompt("文本", ["气-99"])
    assert "气-99" not in p


# -------- JSON 提取 --------


def test_extract_json_clean():
    raw = '{"scores": [{"rule_id": "气-01", "score": 7, "reasoning": "ok"}]}'
    parsed = judge._extract_json(raw)
    assert parsed["scores"][0]["score"] == 7


def test_extract_json_with_fence():
    raw = """这是我的判断：

```json
{"scores": [{"rule_id": "气-01", "score": 5, "reasoning": "中"}]}
```

希望有用。"""
    parsed = judge._extract_json(raw)
    assert parsed["scores"][0]["rule_id"] == "气-01"


def test_extract_json_with_prose():
    raw = """好的，我评估了一下。\n{"scores": []}\n以上结果。"""
    parsed = judge._extract_json(raw)
    assert parsed["scores"] == []


def test_extract_json_no_json_raises():
    with pytest.raises(ValueError):
        judge._extract_json("纯文本，没有 JSON。")


# -------- judge_text 路径 --------


def _mock_anthropic_response(scores: list) -> dict:
    return {
        "content": [{"type": "text", "text": json.dumps({"scores": scores})}]
    }


def test_judge_text_success():
    fake_resp = _mock_anthropic_response([
        {"rule_id": "气-01", "score": 8, "reasoning": "首句直接入题"},
        {"rule_id": "气-02", "score": 6, "reasoning": "有一句正确但无用"},
    ])
    with patch.object(judge, "_call_anthropic", return_value=fake_resp):
        scores = judge.judge_text("测试文本", api_key="fake-key")
    assert len(scores) == 2
    assert scores[0].rule_id == "气-01"
    assert scores[0].score == 8.0
    assert scores[0].judge_reasoning == "首句直接入题"
    assert scores[0].status == "judged"


def test_judge_text_clamps_score():
    fake_resp = _mock_anthropic_response([
        {"rule_id": "气-01", "score": 15, "reasoning": "..."},  # > 10
        {"rule_id": "气-02", "score": -3, "reasoning": "..."},  # < 0
    ])
    with patch.object(judge, "_call_anthropic", return_value=fake_resp):
        scores = judge.judge_text("文本", api_key="fake-key")
    assert scores[0].score == 10.0
    assert scores[1].score == 0.0


def test_judge_text_skips_malformed_entries():
    fake_resp = _mock_anthropic_response([
        {"rule_id": "气-01", "score": 7, "reasoning": "ok"},
        {"rule_id": None, "score": 5},  # missing rule_id
        {"score": "not_a_number"},      # missing rule_id
    ])
    with patch.object(judge, "_call_anthropic", return_value=fake_resp):
        scores = judge.judge_text("文本", api_key="fake-key")
    assert len(scores) == 1
    assert scores[0].rule_id == "气-01"


def test_judge_text_no_api_key_raises():
    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(judge.JudgeError, match="API key"):
            judge.judge_text("文本")


def test_judge_text_safe_swallows_error():
    with patch.dict("os.environ", {}, clear=True):
        scores, err = judge.judge_text_safe("文本")
    assert scores == []
    assert err is not None
    assert "API key" in err


def test_judge_text_safe_returns_scores_on_success():
    fake_resp = _mock_anthropic_response([
        {"rule_id": "气-01", "score": 9, "reasoning": "..."}
    ])
    with patch.object(judge, "_call_anthropic", return_value=fake_resp):
        scores, err = judge.judge_text_safe("文本", api_key="fake-key")
    assert err is None
    assert len(scores) == 1


def test_judge_violation_count_reflects_score():
    """score >= 8 → violation_count = 0; score < 8 → 1."""
    fake_resp = _mock_anthropic_response([
        {"rule_id": "气-01", "score": 9, "reasoning": "ok"},
        {"rule_id": "气-02", "score": 5, "reasoning": "差"},
    ])
    with patch.object(judge, "_call_anthropic", return_value=fake_resp):
        scores = judge.judge_text("文本", api_key="fake-key")
    assert scores[0].violation_count == 0
    assert scores[1].violation_count == 1
