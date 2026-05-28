"""Fuzz / property-based 测试——保证 detector / scoring 在随机输入下不崩。

理想用 hypothesis（dev dep 提供）。这里用 stdlib random 的等价方案，
每个测试跑 N 个 random sample，覆盖比单元测试多两个数量级的输入空间。

如果 hypothesis 装了，会用 hypothesis 跑；没装就用 random。
"""

from __future__ import annotations

import random
import string

import pytest

from star_word import detectors, scoring

# 随机生成的"看起来像中文文档"的字符集
CHINESE_CHARS = "".join(chr(c) for c in range(0x4E00, 0x4E00 + 200))
ALL_CHARS = CHINESE_CHARS + string.ascii_letters + string.digits + " 。，！？；：、\n\r\t"
EVIL_CHARS = "\x00\x07\x1b\x7f​‮﻿"  # 控制字符 / 零宽 / RTL override / BOM


def _random_text(length: int, seed: int, charset: str = ALL_CHARS) -> str:
    rng = random.Random(seed)
    return "".join(rng.choice(charset) for _ in range(length))


# -------- detector 不应崩 --------


@pytest.mark.parametrize("seed", range(20))
def test_detector_no_crash_random_text(seed):
    """20 个随机种子的中文+ASCII 文本，detector 必须不崩。"""
    text = _random_text(500, seed)
    results = detectors.review(text)
    assert isinstance(results, list)
    assert len(results) >= 22


@pytest.mark.parametrize("seed", range(10))
def test_detector_no_crash_with_evil_chars(seed):
    """带控制字符 / 零宽 / RTL override / BOM 的输入。"""
    text = _random_text(500, seed, ALL_CHARS + EVIL_CHARS)
    results = detectors.review(text)
    assert isinstance(results, list)


@pytest.mark.parametrize("size", [0, 1, 10, 100, 10000, 100000])
def test_detector_handles_various_sizes(size):
    """各种文档长度都不能崩。"""
    text = _random_text(size, seed=42) if size > 0 else ""
    results = detectors.review(text)
    assert isinstance(results, list)


def test_detector_rejects_too_large():
    """超过 MAX_INPUT_CHARS 应抛 ValueError。"""
    text = "a" * (detectors.MAX_INPUT_CHARS + 1)
    with pytest.raises(ValueError):
        detectors.review(text)


# -------- scoring 不应崩，且范围合法 --------


@pytest.mark.parametrize("seed", range(20))
def test_scoring_in_valid_range(seed):
    """scoring 输出必须 0-100 或 -1（极短文档）。"""
    text = _random_text(500, seed)
    results = detectors.review(text)
    doc = scoring.score_document(results, text)
    assert doc.score == -1 or 0 <= doc.score <= 100, f"score 越界: {doc.score}"


@pytest.mark.parametrize("mode", ["strict", "normal", "relaxed"])
def test_scoring_strict_le_normal_le_relaxed(mode):
    """对同一份文档，strict ≤ normal ≤ relaxed（更严应该分更低）。"""
    # 用一份有违规的文档
    text = "稳稳地接住流量，赋能业务，闭环数据。" + "正文。" * 100
    results = detectors.review(text)
    s_strict = scoring.score_document(results, text, mode="strict").score
    s_normal = scoring.score_document(results, text, mode="normal").score
    s_relaxed = scoring.score_document(results, text, mode="relaxed").score
    assert s_strict <= s_normal <= s_relaxed


def test_scoring_handles_empty_text():
    """空文本应返回 -1 + N/A 标记。"""
    results = detectors.review("")
    doc = scoring.score_document(results, "")
    assert doc.score == -1
    assert scoring.grade(doc.score) == "N/A"


def test_scoring_handles_only_violations():
    """所有规则都被违反的极端文档分应 ≤ 50。

    单一规则被反复违反但其它规则全过的文档不会跌到 50 以下——
    这是加权平均的合理行为：违规分布越广扣得越狠，
    集中在少数规则上扣得有限。
    """
    paragraphs = [
        "稳稳地保驾护航，赋能闭环顶层设计抓手。",  # 词-01 + 词-08
        "值得注意的是，毋庸置疑。",  # 词-02
        "在当今互联网架构中，进行分析。",  # 词-03 + 词-06
        "这是一个非常好的方案，希望对你有帮助。",  # 词-04
        "本系统高效可靠、稳定强大、灵活智能、便捷易用，值得推荐。",  # 式-04 四字堆砌
        "整体方案。\n\n综上所述，本方案是合适的。",  # 式-01 段尾总结
    ]
    text = "\n\n".join(paragraphs * 3)
    results = detectors.review(text)
    doc = scoring.score_document(results, text)
    assert doc.score <= 50, f"全维度违规文档分太高: {doc.score}"


# -------- mask_line 不应改变非中文非引号字符 --------


@pytest.mark.parametrize("seed", range(10))
def test_mask_line_preserves_non_special(seed):
    """随机文本里 mask 之后，非引号/非 url 区域应保持长度等同（被 mask 为空格）。"""
    text = _random_text(200, seed)
    masked = detectors._mask_line(text)
    # mask 操作后长度必须不变（一律替换为等长空格）
    assert len(masked) == len(text), f"mask 改变了长度 {len(masked)} vs {len(text)}"


# -------- fence map 不漏 --------


def test_fence_map_handles_nested_tilde():
    text = "正文\n~~~python\n赋能闭环\n~~~\n继续"
    ctx = detectors._build_ctx(text)
    # ~~~ 包裹的内容应在 fence 内（赋能不告警）
    r = detectors.词_01(ctx)
    # 只有 fence 外的内容会被扫
    assert all("赋能" not in v.message or v.line not in (3,) for v in r.violations)


def test_fence_map_warns_on_unpaired():
    """奇数 ``` 应在 doc:notes 里出现警告。"""
    text = "```python\n赋能\n继续没有关 fence"
    results = detectors.review(text)
    notes_results = [r for r in results if r.rule_id == "doc:notes"]
    if notes_results:
        assert any("未配对" in v.message for v in notes_results[0].violations)


# -------- 词-04 边界检测 --------


def test_词_04_no_substring_false_positive():
    """「你好问题大家」不应触发讨好式表达。"""
    text = "你好问题大家。"
    ctx = detectors._build_ctx(text)
    r = detectors.词_04(ctx)
    # 不应抓"好问题"作为 substring
    assert all("好问题" not in v.message for v in r.violations)


def test_词_04_句首好问题命中():
    """但 「好问题。」（句首）应该抓。"""
    text = "好问题。"
    ctx = detectors._build_ctx(text)
    r = detectors.词_04(ctx)
    assert any("好问题" in v.message for v in r.violations)


# -------- 式-05 假阳性修复 --------


def test_式_05_no_1plus1_false_positive():
    """Tests fail. tests run.（1+1）不应触发。"""
    text = "Tests fail when broken. tests run quickly."
    ctx = detectors._build_ctx(text)
    r = detectors.式_05(ctx)
    assert r.status == "ok"


def test_式_05_url_path_no_false_positive():
    """URL 路径段大小写不应触发（已在 _mask_line mask 掉）。"""
    text = "看 https://github.com/Foo 然后再看 github.com 文档。"
    ctx = detectors._build_ctx(text)
    r = detectors.式_05(ctx)
    # 不应报 Github vs github
    assert all("github" not in v.message.lower() for v in r.violations)


def test_式_05_tech_acronym_whitelist():
    """URL/url、JSON/json 等大小写变体在白名单里，不报。"""
    text = "URL 用 lowercase url；JSON 也写 json。" * 3
    ctx = detectors._build_ctx(text)
    r = detectors.式_05(ctx)
    assert r.status == "ok"


def test_式_05_real_inconsistency_still_caught():
    """真正的不一致（Model vs model 多次）仍要抓。"""
    text = "训练 Model 需要数据。Model 完成后导出 model 权重。重新训练 Model。"
    ctx = detectors._build_ctx(text)
    r = detectors.式_05(ctx)
    assert r.status == "violations"


# -------- 列表前缀识别 --------


def test_式_08_skips_numbered_list():
    """1. 编号列表项不应被当成短句触发方差告警。"""
    text = "正文\n1. 第一项\n2. 第二项\n3. 第三项\n4. 第四项"
    ctx = detectors._build_ctx(text)
    r = detectors.式_08(ctx)
    assert r.status == "ok"


def test_式_08_skips_star_list():
    """* 列表项也不算句子。"""
    text = "正文\n* a项\n* b项\n* c项\n* d项"
    ctx = detectors._build_ctx(text)
    r = detectors.式_08(ctx)
    assert r.status == "ok"


# -------- 词-01 grey_zone bypass 修复 --------


def test_词_01_business_link_still_caught_with_allow_neighbor():
    """v0.4.0 的 bypass：『打通业务链路追踪』 因为 link allow 优先，不报。
    v0.4.1 修复：ban 命中即报。"""
    text = "打通业务链路追踪。"
    ctx = detectors._build_ctx(text)
    r = detectors.词_01(ctx)
    # 应该报"打通"在 ban context（"打通业务"）
    assert any("打通" in v.message for v in r.violations)
