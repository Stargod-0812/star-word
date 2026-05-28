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
