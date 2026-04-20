"""单元测试: star-word 检测器."""

from __future__ import annotations

import pytest

from star_word import detectors


# -------- STAR-01 空洞价值词 --------


def test_rule_01_flags_banned_words():
    text = "我们通过顶层设计打通数据，全面提升业务闭环能力，全链路赋能。"
    r = detectors.rule_01(text)
    assert r.status == "violations"
    rule_words = {v.message.split("：")[-1].strip("'") for v in r.violations}
    assert "顶层设计" in rule_words
    assert "打通" in rule_words
    assert "全面提升" in rule_words
    assert "闭环" in rule_words
    assert "全链路" in rule_words
    assert "赋能" in rule_words


def test_rule_01_does_not_flag_ambiguous_compounds():
    """链路/生态/布局 等有合法技术用法，不在默认禁用列表."""
    text = "补偿链路断开后，调用链路会被追踪。开发者生态很好。页面布局合理。"
    r = detectors.rule_01(text)
    assert r.status == "ok"


def test_rule_01_clean_pass():
    text = "我们把订单服务接到消息队列，延迟从 3 秒降到 200ms。"
    r = detectors.rule_01(text)
    assert r.status == "ok"
    assert r.violations == []


# -------- STAR-02 AI 过渡套话 --------


def test_rule_02_flags_transition_cliches():
    text = "值得注意的是，这个函数有 bug。综上所述，需要重写。"
    r = detectors.rule_02(text)
    assert r.status == "violations"
    assert any("值得注意的是" in v.message for v in r.violations)
    assert any("综上所述" in v.message for v in r.violations)


# -------- STAR-03 铺垫式开场 --------


def test_rule_03_flags_paragraph_start_only():
    text = "在本文中，我们将介绍 gRPC。第二句是正文。"
    r = detectors.rule_03(text)
    assert r.status == "violations"
    assert any("在本文中" in v.message for v in r.violations)


def test_rule_03_does_not_flag_midparagraph():
    text = "gRPC 是一个 RPC 框架。在本文中出现这几个字不应告警。"
    r = detectors.rule_03(text)
    for v in r.violations:
        assert "在本文中" not in v.message, "段中出现不应告警"


# -------- STAR-04 讨好式表达 --------


def test_rule_04_flags_flattery():
    text = "好问题！让我来为您解释。希望对你有帮助。"
    r = detectors.rule_04(text)
    assert r.status == "violations"
    assert len(r.violations) >= 3


# -------- STAR-06 滥用"进行" --------


def test_rule_06_flags_jinxing_plus_verb():
    text = "对数据进行分析，并进行处理。"
    r = detectors.rule_06(text)
    assert r.status == "violations"
    assert len(r.violations) == 2


def test_rule_06_spares_legitimate_jinxing():
    text = "任务进行中，不要中断。"
    r = detectors.rule_06(text)
    assert r.status == "ok"


# -------- STAR-07 的字过多 --------


def test_rule_07_flags_de_overload():
    text = "这是一个基于深度学习的用于处理大规模数据的高性能的推理服务。"
    r = detectors.rule_07(text)
    assert r.status == "violations"
    assert len(r.violations) >= 1


def test_rule_07_clean_pass():
    text = "推理服务基于深度学习，吞吐 1w QPS。"
    r = detectors.rule_07(text)
    assert r.status == "ok"


# -------- STAR-08 拟人化装饰词 --------


def test_rule_08_flags_decorative_personification():
    text = "我们的系统能稳稳接住流量洪峰，优雅地处理异常，为业务保驾护航。"
    r = detectors.rule_08(text)
    assert r.status == "violations"
    flagged = {v.message for v in r.violations}
    assert any("稳稳接住" in m for m in flagged)
    assert any("保驾护航" in m for m in flagged)


# -------- STAR-09 段尾总结句 --------


def test_rule_09_flags_summary_closer():
    text = "Raft 用任期保证唯一 leader。\n选举需要多数票。\n综上所述，Raft 保证了 leader 唯一性。"
    r = detectors.rule_09(text)
    assert r.status == "violations"


def test_rule_09_clean_pass():
    text = "Raft 用任期保证唯一 leader。\n选举需要多数票。"
    r = detectors.rule_09(text)
    assert r.status == "ok"


# -------- STAR-12 四字词堆砌 --------


def test_rule_12_flags_quadruple_stacking():
    text = "系统高效可靠、稳定强大、灵活智能、便捷易用。"
    r = detectors.rule_12(text)
    assert r.status == "violations"


def test_rule_12_allows_two_quadrupes():
    text = "系统高效可靠、稳定强大。"
    r = detectors.rule_12(text)
    assert r.status == "ok"


# -------- STAR-14 中英文标点混用 --------


def test_rule_14_flags_halfwidth_in_chinese():
    text = "使用Redis做缓存,可以提升性能.但要注意key的过期.策略好"
    r = detectors.rule_14(text)
    assert r.status == "violations"
    assert len(r.violations) >= 1


def test_rule_14_does_not_flag_code_punctuation():
    text = "函数签名是 `foo(a, b)` 这样的调用。"
    r = detectors.rule_14(text)
    # 反引号内的半角逗号应被忽略
    assert r.status == "ok"


# -------- 代码块免疫 --------


def test_detectors_skip_code_fences():
    text = """
正文段落第一句。

```python
# 代码内的"赋能"不应该告警
x = "赋能闭环抓手"
```

正文结束。
"""
    r = detectors.rule_01(text)
    assert r.status == "ok", f"代码块内的违规词被误报: {r.violations}"


# -------- review 编排 --------


def test_review_returns_all_rules():
    text = "你好世界。"
    results = detectors.review(text)
    rule_ids = {r.rule_id for r in results}
    expected = {
        "STAR-01",
        "STAR-02",
        "STAR-03",
        "STAR-04",
        "STAR-06",
        "STAR-07",
        "STAR-08",
        "STAR-09",
        "STAR-12",
        "STAR-14",
        "STAR-05",
        "STAR-10",
        "STAR-11",
        "STAR-13",
        "STAR-15",
        "STAR-16",
        "STAR-17",
        "STAR-18",
        "STAR-19",
        "STAR-20",
        "STAR-21",
    }
    assert rule_ids == expected


def test_review_marks_semantic_as_pending():
    text = "测试文本。"
    results = detectors.review(text)
    semantic_ids = {"STAR-05", "STAR-10", "STAR-11", "STAR-13", "STAR-15",
                    "STAR-16", "STAR-17", "STAR-18", "STAR-19", "STAR-20", "STAR-21"}
    for r in results:
        if r.rule_id in semantic_ids:
            assert r.status == "semantic_pending"
            assert r.violations == []
