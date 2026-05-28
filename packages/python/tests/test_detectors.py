"""单元测试：star-word 检测器 v0.2."""

from __future__ import annotations

import pytest

from star_word import detectors


# -------- 词-01 空洞价值词 --------


def test_词_01_flags_banned():
    text = "我们通过顶层设计打通数据，全面提升业务闭环能力，全链路赋能。"
    ctx = detectors._build_ctx(text)
    r = detectors.词_01(ctx)
    assert r.status == "violations"
    words = {v.message.split("：")[-1].strip("'") for v in r.violations}
    assert {"顶层设计", "打通", "全面提升", "闭环", "全链路", "赋能"} <= words


def test_词_01_skips_ambiguous_compounds():
    """链路/生态/布局 有合法技术用法，不进默认列表."""
    text = "补偿链路断开后，调用链路会被追踪。开发者生态好。页面布局合理。"
    ctx = detectors._build_ctx(text)
    r = detectors.词_01(ctx)
    assert r.status == "ok"


# -------- 词-02 AI 过渡套话 --------


def test_词_02_flags_transitions():
    text = "值得注意的是，这个函数有 bug。综上所述，需要重写。"
    ctx = detectors._build_ctx(text)
    r = detectors.词_02(ctx)
    assert r.status == "violations"
    assert any("值得注意的是" in v.message for v in r.violations)
    assert any("综上所述" in v.message for v in r.violations)


# -------- 词-03 铺垫式开场 --------


def test_词_03_flags_paragraph_start():
    text = "在本文中，我们将介绍 gRPC。第二句是正文。"
    ctx = detectors._build_ctx(text)
    r = detectors.词_03(ctx)
    assert r.status == "violations"


def test_词_03_flags_numbered_list_start():
    text = "1. 在本文中，我们先看缓存一致性。"
    ctx = detectors._build_ctx(text)
    r = detectors.词_03(ctx)
    assert r.status == "violations"
    assert any("在本文中" in v.message for v in r.violations)


def test_词_03_ignores_midparagraph():
    text = "gRPC 是一个 RPC 框架。在本文中出现这几个字不应告警。"
    ctx = detectors._build_ctx(text)
    r = detectors.词_03(ctx)
    for v in r.violations:
        assert "在本文中" not in v.message


# -------- 词-04 讨好式表达 --------


def test_词_04_flags_flattery():
    text = "好问题！让我来为您解释。希望对你有帮助。"
    ctx = detectors._build_ctx(text)
    r = detectors.词_04(ctx)
    assert r.status == "violations"
    assert len(r.violations) >= 3


# -------- 词-06 滥用“进行” --------


def test_词_06_flags_jinxing_plus_verb():
    text = "对数据进行分析，并进行处理。"
    ctx = detectors._build_ctx(text)
    r = detectors.词_06(ctx)
    assert r.status == "violations"
    assert len(r.violations) == 2


def test_词_06_spares_legitimate_jinxing():
    text = "任务进行中，不要中断。"
    ctx = detectors._build_ctx(text)
    r = detectors.词_06(ctx)
    assert r.status == "ok"


# -------- 词-07 的字过多 --------


def test_词_07_flags_de_overload():
    text = "这是一个基于深度学习的用于处理大规模数据的高性能的推理服务。"
    ctx = detectors._build_ctx(text)
    r = detectors.词_07(ctx)
    assert r.status == "violations"


def test_词_07_clean_pass():
    text = "推理服务基于深度学习，吞吐 1w QPS。"
    ctx = detectors._build_ctx(text)
    r = detectors.词_07(ctx)
    assert r.status == "ok"


# -------- 词-08 拟人化装饰词 --------


def test_词_08_flags_personification():
    text = "我们的系统能稳稳接住流量洪峰，为业务保驾护航。"
    ctx = detectors._build_ctx(text)
    r = detectors.词_08(ctx)
    assert r.status == "violations"
    msgs = {v.message for v in r.violations}
    assert any("稳稳接住" in m for m in msgs)
    assert any("保驾护航" in m for m in msgs)


# -------- 式-01 段尾总结句 --------


def test_式_01_flags_summary_closer():
    text = "Raft 保证唯一 leader。\n选举需要多数票。\n综上所述，Raft 保证了 leader 唯一性。"
    ctx = detectors._build_ctx(text)
    r = detectors.式_01(ctx)
    assert r.status == "violations"


def test_式_01_clean_pass():
    text = "Raft 保证唯一 leader。\n选举需要多数票。"
    ctx = detectors._build_ctx(text)
    r = detectors.式_01(ctx)
    assert r.status == "ok"


# -------- 式-04 四字词堆砌 --------


def test_式_04_flags_quad_stacking():
    """连续 4 个四字结构才触发."""
    text = "系统高效可靠、稳定强大、灵活智能、便捷易用。"
    ctx = detectors._build_ctx(text)
    r = detectors.式_04(ctx)
    assert r.status == "violations"


def test_式_04_allows_three_tech_nouns():
    """连续 3 个紧实技术名词（非装饰性）不应触发."""
    text = "但旧版本在命令语义、复制链路、故障处理上与 7.x 存在差距。"
    ctx = detectors._build_ctx(text)
    r = detectors.式_04(ctx)
    assert r.status == "ok"


def test_式_04_allows_two_quadrupes():
    text = "系统高效可靠、稳定强大。"
    ctx = detectors._build_ctx(text)
    r = detectors.式_04(ctx)
    assert r.status == "ok"


# -------- 式-06 中英文标点混用 --------


def test_式_06_flags_halfwidth_in_chinese():
    text = "使用Redis做缓存,可以提升性能.但要注意key的过期.策略好"
    ctx = detectors._build_ctx(text)
    r = detectors.式_06(ctx)
    assert r.status == "violations"


def test_式_06_skips_code_punctuation():
    text = "函数签名是 `foo(a, b)` 这样的调用。"
    ctx = detectors._build_ctx(text)
    r = detectors.式_06(ctx)
    assert r.status == "ok"


# -------- 代码块/引用免疫 --------


def test_detectors_skip_code_fences():
    text = """
正文段落第一句。

```python
# 代码内的“赋能”不应该告警
x = "赋能闭环抓手"
```

正文结束。
"""
    ctx = detectors._build_ctx(text)
    r = detectors.词_01(ctx)
    assert r.status == "ok"


def test_detectors_skip_ascii_quoted_phrases():
    text = '这里讨论 "综上所述" 这种套话本身，不是在真的用它收尾。'
    ctx = detectors._build_ctx(text)
    r = detectors.词_02(ctx)
    assert r.status == "ok"


# -------- 式-08 句长方差 --------


def test_式_08_uniform_length_triggers():
    """句长趋同的段落应触发告警。"""
    text = (
        "我们采用了微服务架构来构建这个系统。"
        "每个服务负责一个独立的业务领域模块。"
        "服务之间通过消息队列来异步通信交互。"
        "这种架构能够支撑大规模的并发请求。"
        "整体部署采用了容器化的方式来管理。"
    )
    ctx = detectors._build_ctx(text)
    r = detectors.式_08(ctx)
    assert r.status == "violations"
    assert len(r.violations) >= 1


def test_式_08_varied_length_ok():
    """句长有变化的段落不应触发。"""
    text = (
        "微服务架构。每个服务管一个领域，消息队列串起来。"
        "好处是扩缩容独立——订单服务扛不住了加 pod，不用动支付。"
        "代价是分布式事务，后面细说。"
    )
    ctx = detectors._build_ctx(text)
    r = detectors.式_08(ctx)
    assert r.status == "ok"


def test_式_08_too_few_sentences_skip():
    """少于 4 句不检测。"""
    text = "句子一。句子二。句子三。"
    ctx = detectors._build_ctx(text)
    r = detectors.式_08(ctx)
    assert r.status == "ok"


# -------- 式-05 术语一致性（v0.4 机械化） --------


def test_式_05_flags_case_inconsistency():
    """同一概念混用不同大小写。"""
    text = "训练 Model 需要数据。Model 训练完成后导出 model 权重。再训练一次 Model。"
    ctx = detectors._build_ctx(text)
    r = detectors.式_05(ctx)
    assert r.status == "violations"
    assert any("model" in v.message.lower() for v in r.violations)


def test_式_05_clean_pass_when_consistent():
    """术语一致时不触发。"""
    text = "训练 model 需要数据。model 训练完成后导出权重到 S3。"
    ctx = detectors._build_ctx(text)
    r = detectors.式_05(ctx)
    assert r.status == "ok"


def test_式_05_skips_short_identifiers():
    """≤2 字符标识符不检测（如 id / ID 是合法变体）。"""
    text = "用 id 索引。ID 是主键。"
    ctx = detectors._build_ctx(text)
    r = detectors.式_05(ctx)
    assert r.status == "ok"


def test_式_05_skips_code_blocks():
    """代码块内的大小写差异不告警。"""
    text = """正文用 Redis。

```python
redis = Redis()
REDIS_URL = "..."
```

继续用 Redis 描述。"""
    ctx = detectors._build_ctx(text)
    r = detectors.式_05(ctx)
    assert r.status == "ok"


# -------- 词-01 上下文感知 grey_zone（v0.4 接通） --------


def test_词_01_grey_zone_triggers_in_business_context():
    """grey_zone 词在套话语境下应告警。"""
    text = "我们要打通业务链路，建立战略生态。"
    ctx = detectors._build_ctx(text)
    r = detectors.词_01(ctx)
    assert r.status == "violations"
    # 应至少抓到「打通」+「业务」的套话上下文
    assert any("打通" in v.message for v in r.violations)


def test_词_01_grey_zone_spares_legitimate_tech_use():
    """grey_zone 词在合法技术用法下不告警。"""
    text = "用 OpenTelemetry 做调用链路追踪。打通管道连接两个网络。"
    ctx = detectors._build_ctx(text)
    r = detectors.词_01(ctx)
    # 不应报「链路」或「打通」（在合法技术上下文里）
    assert all("链路" not in v.message and "打通" not in v.message for v in r.violations)


# -------- review() 编排 --------


def test_review_returns_all_rules():
    text = "你好世界。"
    results = detectors.review(text)
    rule_ids = {r.rule_id for r in results}
    expected = {
        "词-01", "词-02", "词-03", "词-04", "词-06", "词-07", "词-08",
        "式-01", "式-04", "式-05", "式-06", "式-08",
        "词-05", "式-02", "式-03", "式-07",
        "气-01", "气-02", "气-03", "气-04", "气-05", "气-06",
    }
    assert rule_ids == expected


def test_review_semantic_pending():
    results = detectors.review("测试文本。")
    sem_ids = {
        "词-05", "式-02", "式-03", "式-07",
        "气-01", "气-02", "气-03", "气-04", "气-05", "气-06",
    }
    for r in results:
        if r.rule_id in sem_ids:
            assert r.status == "sense-pending"
            assert r.violations == []


# -------- perf: fence map 只计算一次 --------


def test_fence_map_precomputed_once(monkeypatch):
    calls = {"count": 0}
    orig = detectors._precompute_fence_map

    def counting(lines):
        calls["count"] += 1
        return orig(lines)

    monkeypatch.setattr(detectors, "_precompute_fence_map", counting)
    text = "第一行。\n```\ncode\n```\n第二行。"
    detectors.review(text)
    assert calls["count"] == 1, f"fence map 重复计算了 {calls['count']} 次"
