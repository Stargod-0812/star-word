"""安全测试——v0.4.1 安全加固的 regression test。

每条对应 reviewer agent 报的一个 vuln，确保不再回归。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import patch

import pytest

from star_word import _llm, detectors, installer, judge, mcp_server

# -------- V1: Prompt injection via """ boundary escape --------


def test_judge_prompt_uses_nonce_sentinel():
    """v0.4.1: 用 nonce sentinel 而不是固定 \"\"\" 边界。"""
    p = judge._build_prompt("正常文档", ["气-01"])
    # 不能再用裸的 """
    assert '"""' not in p
    # 必须用 nonce 包装
    assert re.search(r"<DOC_[a-f0-9]{16}_BEGIN>", p)
    assert re.search(r"<DOC_[a-f0-9]{16}_END>", p)


def test_judge_prompt_injection_defense_instruction():
    """prompt 必须包含「忽略数据里的指令」一类的对抗性提示。"""
    p = judge._build_prompt("文档", ["气-01"])
    # 至少要有"数据/data" + "忽略/不"一类的语义
    assert ("数据" in p or "data" in p.lower())
    assert ("忽略" in p or "ignore" in p.lower())


# -------- V2: Symlink follow vulnerability --------


def test_install_refuses_symlink_target(tmp_path, monkeypatch):
    """v0.4.1: enable 不应通过 symlink 写到任意路径。"""
    monkeypatch.chdir(tmp_path)
    victim = tmp_path / "victim.txt"
    victim.write_text("ORIGINAL CONTENT")
    sw_dir = tmp_path / ".sw"
    sw_dir.mkdir()
    # 攻击者预置 symlink: .sw/rules.md -> /tmp/victim.txt
    symlink_target = sw_dir / "rules.md"
    symlink_target.symlink_to(victim)
    # 跑 enable - _safe_copy 应拒绝跟随 symlink 写
    installer.enable_claude_code(global_scope=False)
    # 受害文件内容必须保持原样
    assert victim.read_text() == "ORIGINAL CONTENT", "symlink 被跟随了，受害文件被覆写"


def test_install_refuses_symlinked_sw_dir(tmp_path, monkeypatch):
    """如果 .sw/ 整体是 symlink，应拒绝写入。"""
    monkeypatch.chdir(tmp_path)
    other = tmp_path / "elsewhere"
    other.mkdir()
    sw_link = tmp_path / ".sw"
    sw_link.symlink_to(other)
    with pytest.raises(ValueError, match="symlink"):
        installer.enable_claude_code(global_scope=False)


# -------- V3: JSON output schema validation --------


def test_judge_rejects_unknown_rule_id():
    """LLM 返回不在白名单的 rule_id 应被丢弃。"""
    fake_resp = {
        "content": [{
            "type": "text",
            "text": json.dumps({
                "scores": [
                    {"rule_id": "../../etc/passwd", "score": 10, "reasoning": "evil"},
                    {"rule_id": "<script>alert(1)</script>", "score": 10, "reasoning": "xss"},
                    {"rule_id": "气-01", "score": 7, "reasoning": "正常"},
                ]
            })
        }]
    }
    with patch.object(_llm, "call_anthropic", return_value=fake_resp):
        scores = judge.judge_text("文本", api_key="fake-key")
    rule_ids = [s.rule_id for s in scores]
    assert "../../etc/passwd" not in rule_ids
    assert "<script>alert(1)</script>" not in rule_ids
    assert "气-01" in rule_ids


def test_judge_strips_control_chars_from_reasoning():
    """ANSI/控制字符应从 reasoning 字段去掉。"""
    fake_resp = {
        "content": [{
            "type": "text",
            "text": json.dumps({
                "scores": [{
                    "rule_id": "气-01",
                    "score": 5,
                    "reasoning": "\x1b[31m\x07RED ALERT\x1b[0m",
                }]
            })
        }]
    }
    with patch.object(_llm, "call_anthropic", return_value=fake_resp):
        scores = judge.judge_text("文本", api_key="fake-key")
    r = scores[0].judge_reasoning
    assert "\x1b" not in r
    assert "\x07" not in r


# -------- V4: MCP input validation --------


def test_mcp_invalid_text_type_returns_invalid_params():
    """text=12345 不是字符串，应返回 -32602 而非 -32603。"""
    req = {
        "jsonrpc": "2.0", "id": 1,
        "method": "tools/call",
        "params": {"name": "review_text", "arguments": {"text": 12345}},
    }
    resp = mcp_server.handle_request(req)
    assert "error" in resp
    assert resp["error"]["code"] == -32602


def test_mcp_invalid_mode_returns_invalid_params():
    """mode='INVALID' 应返回 -32602。"""
    req = {
        "jsonrpc": "2.0", "id": 2,
        "method": "tools/call",
        "params": {"name": "review_text", "arguments": {"text": "hi", "mode": "INVALID"}},
    }
    resp = mcp_server.handle_request(req)
    assert "error" in resp
    assert resp["error"]["code"] == -32602


def test_mcp_oversized_text_rejected():
    """text 超过 MAX_TEXT_CHARS 应返回 -32602。"""
    huge = "x" * (mcp_server.MAX_TEXT_CHARS + 1)
    req = {
        "jsonrpc": "2.0", "id": 3,
        "method": "tools/call",
        "params": {"name": "review_text", "arguments": {"text": huge}},
    }
    resp = mcp_server.handle_request(req)
    assert "error" in resp
    assert resp["error"]["code"] == -32602


def test_mcp_non_object_params_rejected():
    """params 不是 object 应返回 -32602。"""
    req = {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": "not-a-dict"}
    resp = mcp_server.handle_request(req)
    assert "error" in resp
    assert resp["error"]["code"] == -32602


def test_mcp_internal_error_does_not_leak_stack():
    """内部异常的错误消息不应包含 type 名或 stack 内容。"""
    # 制造一个会让 detector 崩的输入：通过 patch
    with patch.object(mcp_server.detectors, "review", side_effect=RuntimeError("内部秘密 token=abc123")):
        req = {
            "jsonrpc": "2.0", "id": 5,
            "method": "tools/call",
            "params": {"name": "review_text", "arguments": {"text": "hi"}},
        }
        resp = mcp_server.handle_request(req)
    assert "error" in resp
    assert resp["error"]["code"] == -32603
    # 不能泄漏 RuntimeError 或秘密内容
    assert "RuntimeError" not in resp["error"]["message"]
    assert "abc123" not in resp["error"]["message"]


def test_mcp_capabilities_list_changed():
    """initialize 应声明 listChanged 能力（MCP spec）。"""
    req = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    resp = mcp_server.handle_request(req)
    caps = resp["result"]["capabilities"]
    assert "tools" in caps
    assert "listChanged" in caps["tools"]


def test_mcp_invalid_jsonrpc_version_rejected():
    """jsonrpc != '2.0' 应被拒绝。"""
    req = {"jsonrpc": "1.0", "id": 1, "method": "ping"}
    resp = mcp_server.handle_request(req)
    assert "error" in resp
    assert resp["error"]["code"] == -32600


# -------- V5: YAML parser stack overflow --------


def test_yaml_parser_rejects_deep_nesting():
    """build.py 的 fallback YAML parser 应拒绝过深嵌套。"""
    import importlib.util
    repo_root = Path(__file__).resolve().parent.parent.parent.parent
    build_path = repo_root / "scripts" / "build.py"
    if not build_path.exists():
        pytest.skip("scripts/build.py 不在测试环境中（pip install 后运行的环境）")
    spec = importlib.util.spec_from_file_location("scripts_build", build_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # 构造 100 层嵌套
    lines = []
    for i in range(100):
        lines.append("  " * i + f"level{i}:")
    with pytest.raises(ValueError, match="嵌套过深"):
        mod._yaml_parse_block(lines, 0, 0, depth=0)


# -------- V6: Sanitize API key from error messages --------


def test_sanitize_error_redacts_api_key():
    """错误消息里的 API key 应被脱敏。"""
    msg = "HTTP 401: invalid api_key sk-ant-LEAKED-LAST-1234567890ABCDEFGH"
    sanitized = _llm.sanitize_error(msg)
    assert "sk-ant-LEAKED" not in sanitized
    assert "REDACTED" in sanitized


def test_sanitize_error_strips_ansi():
    """错误消息里的 ANSI 控制码应被去掉。"""
    msg = "\x1b[31mError: something\x1b[0m"
    sanitized = _llm.sanitize_error(msg)
    assert "\x1b" not in sanitized


def test_sanitize_error_truncates_long():
    """过长错误消息应被截断。"""
    msg = "x" * 10000
    sanitized = _llm.sanitize_error(msg)
    assert len(sanitized) <= 500


# -------- V7: ReDoS in _strip_marker_block --------


def test_strip_marker_no_redos(tmp_path):
    """5000 个无配对的 MARKER_BEGIN 应快速返回，不卡死。"""
    import time
    f = tmp_path / "claude.md"
    pathological = (installer.MARKER_BEGIN + "\n") * 5000
    f.write_text(pathological)
    start = time.time()
    installer._strip_marker_block(f)
    elapsed = time.time() - start
    assert elapsed < 2.0, f"_strip_marker_block 卡了 {elapsed:.1f}s"


# -------- HOME=/ guard --------


def test_global_install_rejects_root_home(monkeypatch):
    """HOME=/ 应被拒绝（防止 mkdir / 失败的尴尬错误）。"""
    monkeypatch.setenv("HOME", "/")
    with pytest.raises(ValueError, match="HOME"):
        installer._resolve_target_root(global_scope=True)


# -------- Detector input size guard --------


def test_detectors_reject_oversized_input():
    """超过 MAX_INPUT_CHARS 应抛 ValueError。"""
    huge = "x" * (detectors.MAX_INPUT_CHARS + 1)
    with pytest.raises(ValueError, match="超过上限"):
        detectors.review(huge)


# ============================================================================
# Round 4 — v0.4.2 安全 regression
# ============================================================================


# -------- V8: Zero-width 字符 bypass --------


def test_zero_width_bypass_blocked():
    """U+200B/200C/200D 插入「赋能」中间不再绕过词典扫描。"""
    # 构造 4 种 zero-width 字符 + BOM 的 bypass 尝试
    zw_variants = [
        "赋​能",  # ZERO WIDTH SPACE
        "赋‌能",  # ZERO WIDTH NON-JOINER
        "赋‍能",  # ZERO WIDTH JOINER
        "赋⁠能",  # WORD JOINER
        "赋﻿能",  # ZERO WIDTH NO-BREAK SPACE (BOM)
    ]
    for variant in zw_variants:
        text = f"我们要全面{variant}业务发展\n"
        results = detectors.review(text)
        ci_violations = [
            v for r in results for v in r.violations
            if r.rule_id == "词-01"
        ]
        assert ci_violations, f"zero-width bypass 未被拦截: {variant!r}"


def test_zero_width_does_not_break_normal_text():
    """正常无 ZW 字符的文档行为不变。"""
    text = "正常文档没有空话\n"
    results = detectors.review(text)
    ci = [v for r in results for v in r.violations if r.rule_id == "词-01"]
    assert ci == []


# -------- V9: CLAUDE.md / AGENTS.md symlink hijacking --------


def test_enable_refuses_to_follow_claude_md_symlink(tmp_path, monkeypatch):
    """CLAUDE.md 是 symlink 时 enable 必须不跟随写入。

    攻击场景：恶意 git repo 预置 CLAUDE.md → ~/.ssh/authorized_keys
    """
    monkeypatch.chdir(tmp_path)
    victim = tmp_path / "victim.txt"
    victim.write_text("ORIGINAL")
    claude_md = tmp_path / "CLAUDE.md"
    claude_md.symlink_to(victim)
    # enable 必须先 unlink symlink 再写实文件
    installer.enable_claude_code(global_scope=False)
    # victim 不能被改
    assert victim.read_text() == "ORIGINAL"
    # CLAUDE.md 现在应是真实文件，不是 symlink
    assert not claude_md.is_symlink()
    assert claude_md.is_file()


def test_disable_refuses_claude_md_symlink(tmp_path, monkeypatch):
    """CLAUDE.md 是 symlink 时 disable 必须 raise，不静默跟随。"""
    monkeypatch.chdir(tmp_path)
    victim = tmp_path / "victim.txt"
    victim.write_text("ORIGINAL")
    claude_md = tmp_path / "CLAUDE.md"
    claude_md.symlink_to(victim)
    with pytest.raises(ValueError, match="symlink"):
        installer._strip_marker_block(claude_md)
    assert victim.read_text() == "ORIGINAL"


# -------- V10: _strip_marker_block max_iter raise --------


def test_strip_marker_block_raises_on_excessive_iterations(tmp_path):
    """marker 配对数超过 max_iter 必须 raise，不能静默丢数据。"""
    f = tmp_path / "claude.md"
    # 12000 对 marker 块（超过 max_iter=10000）
    pairs = (installer.MARKER_BEGIN + "\nbody\n" + installer.MARKER_END + "\n") * 12000
    f.write_text(pairs)
    with pytest.raises(ValueError, match="拒绝处理"):
        installer._strip_marker_block(f)


# -------- V11: judge NaN / Infinity 拒绝 --------


def test_judge_rejects_nan_score():
    """模型返回 score=NaN 应被丢弃，不静默退化。"""
    # 模拟 _llm.call_anthropic 返回 NaN
    fake_resp = {
        "content": [
            {
                "type": "text",
                "text": '{"scores":[{"rule_id":"气-01","score":NaN,"reasoning":"x"}]}',
            }
        ]
    }
    with patch.object(_llm, "call_anthropic", return_value=fake_resp):
        with patch.object(_llm, "get_api_key", return_value="sk-test"):
            # JSON.parse 不接受裸 NaN；模型实际返回 float("nan") 时走 dict 路径
            try:
                scores = judge.judge_text("这是文档" * 30, rule_ids=["气-01"])
                # 即使解析失败也只该 raise 或返回空，不该 silently mark satisfied
                assert all(s.score == s.score for s in scores), "NaN 入侵 score"
            except judge.JudgeError:
                pass  # JSON 解析失败也 OK


def test_judge_handles_infinity_in_dict():
    """直接 inject float('inf') 到响应 dict（绕开 JSON 解析），应被丢弃。"""
    import json as _json
    # 用 allow_nan=True 的 dumps + 自定义解析
    fake_resp = {
        "content": [
            {
                "type": "text",
                "text": _json.dumps(
                    {"scores": [{"rule_id": "气-01", "score": float("inf"), "reasoning": "x"}]},
                    allow_nan=True,  # Python json 默认就 allow_nan=True
                ),
            }
        ]
    }
    with patch.object(_llm, "call_anthropic", return_value=fake_resp):
        with patch.object(_llm, "get_api_key", return_value="sk-test"):
            scores = judge.judge_text("这是文档" * 30, rule_ids=["气-01"])
            # Infinity 应被 isfinite 拒绝，scores 为空
            assert scores == [], f"Infinity 未被拒绝: {scores}"


# -------- V12: 词-04 AND 边界 --------


def test_ci_04_and_boundary_rejects_compound_words():
    """v0.4.2: 词-04 改 AND 边界后，「写好问题」（动宾）不再误抓。"""
    text = "请你写好问题再来\n"  # "写"(中文) + "好问题" + "再"(中文): AND fail = 不抓
    results = detectors.review(text)
    ci_04 = [v for r in results for v in r.violations if r.rule_id == "词-04"]
    assert ci_04 == [], f"AND 边界应拒绝「写好问题」误抓: {ci_04}"


def test_ci_04_and_boundary_still_catches_real_violations():
    """词-04 AND 边界仍能抓真正的句首/独立 case。"""
    text = "好问题。这是一个套话开场\n"  # 行首+句号: 两边都非中文
    results = detectors.review(text)
    ci_04 = [v for r in results for v in r.violations if r.rule_id == "词-04"]
    assert ci_04, "AND 边界应抓行首讨好语"
