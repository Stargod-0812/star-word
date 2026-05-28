"""mcp_server 测试——直接调 handle_request，不起进程."""

from __future__ import annotations

import json

from star_word import mcp_server


def test_initialize_returns_capabilities():
    req = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    resp = mcp_server.handle_request(req)
    assert resp["id"] == 1
    assert "serverInfo" in resp["result"]
    assert resp["result"]["serverInfo"]["name"] == "star-word"


def test_tools_list_returns_four_tools():
    req = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
    resp = mcp_server.handle_request(req)
    tools = resp["result"]["tools"]
    names = {t["name"] for t in tools}
    assert names == {"review_text", "judge_text", "get_rules", "suggest_rewrite"}


def test_tools_call_review_text():
    req = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {
            "name": "review_text",
            "arguments": {"text": "稳稳地接住流量。" * 20},
        },
    }
    resp = mcp_server.handle_request(req)
    assert "result" in resp
    content_text = resp["result"]["content"][0]["text"]
    payload = json.loads(content_text)
    assert "score" in payload
    assert "grade" in payload
    # Should detect 词-08 violations
    assert any(v["rule_id"] == "词-08" for v in payload["violations_by_rule"])


def test_tools_call_get_rules():
    req = {
        "jsonrpc": "2.0",
        "id": 4,
        "method": "tools/call",
        "params": {"name": "get_rules", "arguments": {}},
    }
    resp = mcp_server.handle_request(req)
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert len(payload["rules"]) == 22


def test_unknown_method_returns_error():
    req = {"jsonrpc": "2.0", "id": 5, "method": "bogus/method"}
    resp = mcp_server.handle_request(req)
    assert "error" in resp
    assert resp["error"]["code"] == -32601


def test_unknown_tool_returns_error():
    req = {
        "jsonrpc": "2.0",
        "id": 6,
        "method": "tools/call",
        "params": {"name": "unknown_tool", "arguments": {}},
    }
    resp = mcp_server.handle_request(req)
    assert "error" in resp


def test_initialized_notification_no_response():
    req = {"jsonrpc": "2.0", "method": "notifications/initialized"}
    resp = mcp_server.handle_request(req)
    assert resp is None


def test_judge_without_api_key_returns_error_field():
    """没 API key 应返回 error 字段在 result 里，不抛异常。"""
    import os
    original = os.environ.copy()
    for k in ("ANTHROPIC_API_KEY", "STAR_WORD_API_KEY"):
        os.environ.pop(k, None)
    try:
        req = {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {"name": "judge_text", "arguments": {"text": "测试"}},
        }
        resp = mcp_server.handle_request(req)
        payload = json.loads(resp["result"]["content"][0]["text"])
        assert "error" in payload
        assert payload["scores"] == []
    finally:
        os.environ.update(original)
