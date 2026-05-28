"""scoring 模块测试."""

from __future__ import annotations

from star_word import detectors, scoring


def test_clean_doc_gets_high_score():
    """无违规的文档应得高分。"""
    text = "训练 model 需要数据。导出权重到 S3。" * 10
    results = detectors.review(text)
    doc = scoring.score_document(results, text)
    assert doc.score >= 80, f"clean doc only got {doc.score}"


def test_dirty_doc_gets_low_score():
    """高违规密度应给 F 等级。"""
    text = (
        "在当今互联网架构中，我们要赋能业务，打通数据闭环。"
        "值得注意的是，这是一个非常好的方案。"
        "稳稳地保驾护航，希望对你有帮助。"
        "综上所述，整体来看，这种方案能够全面提升能力。"
    )
    results = detectors.review(text)
    doc = scoring.score_document(results, text)
    assert scoring.grade(doc.score) == "F", f"dirty doc graded {scoring.grade(doc.score)} ({doc.score})"
    # 词组应被严重扣分
    word_group = next(g for g in doc.groups if g.group == "词")
    assert word_group.score < 4.0, f"词 group score {word_group.score} too high"


def test_score_normalizes_for_length():
    """同样 1 处违规，长文档分数高于短文档。"""
    short = "稳稳地接住。" + "x" * 50
    long_text = "稳稳地接住。" + "x" * 5000

    short_results = detectors.review(short)
    long_results = detectors.review(long_text)

    short_score = scoring.score_document(short_results, short).score
    long_score = scoring.score_document(long_results, long_text).score

    assert long_score > short_score, "长文档应因归一化获得更高分"


def test_mode_changes_strictness():
    """strict 模式应比 relaxed 更严。"""
    text = "稳稳地。值得注意的是，这是一个很好的方案。" + "正文。" * 100

    results = detectors.review(text)
    strict = scoring.score_document(results, text, mode="strict").score
    normal = scoring.score_document(results, text, mode="normal").score
    relaxed = scoring.score_document(results, text, mode="relaxed").score

    assert strict < normal < relaxed


def test_grade_thresholds():
    assert scoring.grade(95) == "A"
    assert scoring.grade(85) == "B"
    assert scoring.grade(75) == "C"
    assert scoring.grade(65) == "D"
    assert scoring.grade(50) == "F"


def test_pending_rules_dont_drag_score():
    """sense-pending 规则在没 judge 时不应拉低文档分。"""
    text = "训练 model 需要数据。导出权重。" * 5
    results = detectors.review(text)
    doc = scoring.score_document(results, text)
    # 应有提示：N 条规则未评估
    assert any("未评估" in n for n in doc.notes)


def test_as_dict_serializable():
    """输出能 dump JSON。"""
    import json
    text = "短文。"
    results = detectors.review(text)
    doc = scoring.score_document(results, text)
    payload = doc.as_dict()
    s = json.dumps(payload, ensure_ascii=False)
    assert "score" in s
    assert "groups" in s
