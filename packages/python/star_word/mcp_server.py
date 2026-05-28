"""star-word MCP server（v0.4.1+）.

零依赖的 stdio MCP server。实现 4 个工具 + 必要的协议机制。

v0.4.1 安全加固：
- 严格输入验证（type / size / enum），违反返回 -32602 而非 -32603
- 错误消息净化（不泄漏内部 stack trace 或 exception type）
- 最大单行 payload 上限（10MB），防 OOM
- stderr 结构化日志（method / duration / error）
- 错误响应统一 ensure_ascii=False
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from typing import Any, Optional

from . import __version__, detectors, scoring

# -------- 配置 --------

# 单条 stdin 消息最大字节数。超过这个就关闭连接，防 OOM。
MAX_LINE_BYTES = 10 * 1024 * 1024  # 10MB

# 单个工具调用文档输入字符上限——防止误用 OOM
MAX_TEXT_CHARS = 1_000_000  # ~1MB

# Logger
_logger = logging.getLogger("star_word.mcp")
if not _logger.handlers:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("[%(asctime)s] %(name)s %(levelname)s: %(message)s"))
    _logger.addHandler(handler)
    _logger.setLevel(os.environ.get("SW_LOG_LEVEL", "WARNING").upper())


# -------- 工具定义 --------

TOOLS = [
    {
        "name": "review_text",
        "description": "机械 + 结构检测中文文本（star-word 词组/式组规则）。返回违规列表 + 文档评分。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "待检测的中文文本"},
                "mode": {
                    "type": "string",
                    "enum": ["strict", "normal", "relaxed"],
                    "default": "normal",
                    "description": "严格度模式",
                },
            },
            "required": ["text"],
        },
    },
    {
        "name": "judge_text",
        "description": "LLM-as-judge 评估语义规则（气组 + 部分式组）。需要 ANTHROPIC_API_KEY。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "待评估文本"},
                "rules": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "评估哪些规则；默认所有 sense-pending 规则",
                },
            },
            "required": ["text"],
        },
    },
    {
        "name": "get_rules",
        "description": "列出 star-word 全部规则（id、标题、组）。",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "suggest_rewrite",
        "description": "对违规处生成改写建议。需要 ANTHROPIC_API_KEY。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "max_violations": {"type": "integer", "default": 20, "minimum": 1, "maximum": 100},
            },
            "required": ["text"],
        },
    },
]


# -------- 输入验证 --------


class InvalidParams(Exception):
    """JSON-RPC -32602 类错误。"""


def _validate_text_arg(args: Any, key: str = "text") -> str:
    if not isinstance(args, dict):
        raise InvalidParams("arguments 必须是 object")
    text = args.get(key)
    if not isinstance(text, str):
        raise InvalidParams(f"参数 {key!r} 必须是字符串")
    if len(text) > MAX_TEXT_CHARS:
        raise InvalidParams(f"参数 {key!r} 超过 {MAX_TEXT_CHARS} 字符")
    return text


def _validate_mode(args: dict, default: str = "normal") -> str:
    mode = args.get("mode", default)
    if mode not in ("strict", "normal", "relaxed"):
        raise InvalidParams(f"mode 必须是 strict/normal/relaxed，收到 {mode!r}")
    return mode


# -------- 工具实现 --------


def _tool_review_text(args: dict) -> dict:
    text = _validate_text_arg(args)
    mode = _validate_mode(args)
    results = detectors.review(text)
    doc = scoring.score_document(results, text, mode=mode)
    return {
        "score": round(doc.score, 1) if doc.score >= 0 else None,
        "grade": scoring.grade(doc.score),
        "char_count": doc.char_count,
        "violations_by_rule": [
            {
                "rule_id": r.rule_id,
                "status": r.status,
                "violations": [v.as_dict() for v in r.violations],
            }
            for r in results
            if r.status == "violations"
        ],
        "scores": doc.as_dict(),
    }


def _tool_judge_text(args: dict) -> dict:
    text = _validate_text_arg(args)
    rule_ids = args.get("rules")
    if rule_ids is not None:
        if not isinstance(rule_ids, list) or not all(isinstance(r, str) for r in rule_ids):
            raise InvalidParams("rules 必须是字符串列表")
    from . import judge
    scores, err = judge.judge_text_safe(text, rule_ids=rule_ids)
    if err:
        return {"error": err, "scores": []}
    return {
        "scores": [
            {
                "rule_id": s.rule_id,
                "score": s.score,
                "reasoning": s.judge_reasoning,
            }
            for s in scores
        ]
    }


def _tool_get_rules(args: dict) -> dict:
    rules = []
    for rid, title in [
        ("词-01", "空洞价值词"),
        ("词-02", "AI 过渡套话"),
        ("词-03", "铺垫式开场"),
        ("词-04", "讨好式表达"),
        ("词-05", "模糊缓冲"),
        ("词-06", "滥用「进行」"),
        ("词-07", "的字过多"),
        ("词-08", "拟人化装饰词"),
    ]:
        rules.append({"id": rid, "title": title, "group": "词", "detect": "mechanical"})
    for rid, title, mech in [
        ("式-01", "段尾总结句", "mechanical"),
        ("式-02", "机械并列", "semantic"),
        ("式-03", "长定语前置", "semantic"),
        ("式-04", "四字词堆砌", "mechanical"),
        ("式-05", "术语前后不一致", "mechanical"),
        ("式-06", "中英文标点混用", "mechanical"),
        ("式-07", "列表滥用", "semantic"),
        ("式-08", "句长方差过低", "mechanical"),
    ]:
        rules.append({"id": rid, "title": title, "group": "式", "detect": mech})
    for rid, title in [
        ("气-01", "第一句直接入题"),
        ("气-02", "不说正确但无用的话"),
        ("气-03", "有判断、有立场"),
        ("气-04", "看本质，不停在现象"),
        ("气-05", "信息密度"),
        ("气-06", "用人话，不文绉绉"),
    ]:
        rules.append({"id": rid, "title": title, "group": "气", "detect": "semantic"})
    return {"version": __version__, "rules": rules}


def _tool_suggest_rewrite(args: dict) -> dict:
    text = _validate_text_arg(args)
    max_v = args.get("max_violations", 20)
    if not isinstance(max_v, int) or max_v < 1 or max_v > 100:
        raise InvalidParams("max_violations 必须是 1-100 的整数")
    from . import rewriter
    results = detectors.review(text)
    suggestions, err = rewriter.suggest_rewrites_safe(text, results, max_violations=max_v)
    if err:
        return {"error": err, "suggestions": []}
    return {
        "suggestions": [
            {
                "line": s.line,
                "rule_id": s.rule_id,
                "original": s.original,
                "suggested": s.suggested,
                "reason": s.reason,
            }
            for s in suggestions
        ]
    }


TOOL_HANDLERS = {
    "review_text": _tool_review_text,
    "judge_text": _tool_judge_text,
    "get_rules": _tool_get_rules,
    "suggest_rewrite": _tool_suggest_rewrite,
}


# -------- JSON-RPC 协议 --------


def _make_response(req_id: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _make_error(req_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def handle_request(req: Any) -> Optional[dict]:
    """处理 JSON-RPC 请求。返回 None = notification（不需回复）。"""
    if not isinstance(req, dict):
        return _make_error(None, -32600, "Invalid Request: 必须是 JSON 对象")

    if req.get("jsonrpc") not in ("2.0", None):
        # 接受缺失的 jsonrpc 字段（容忍），但拒绝非 "2.0" 的明确版本
        return _make_error(req.get("id"), -32600, "Invalid Request: jsonrpc 必须是 '2.0'")

    method = req.get("method")
    req_id = req.get("id")
    params = req.get("params", {})

    start = time.time()
    try:
        if method == "initialize":
            resp = _make_response(req_id, {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "star-word", "version": __version__},
            })
        elif method == "notifications/initialized":
            return None
        elif method == "tools/list":
            resp = _make_response(req_id, {"tools": TOOLS})
        elif method == "tools/call":
            if not isinstance(params, dict):
                return _make_error(req_id, -32602, "params 必须是 object")
            name = params.get("name")
            arguments = params.get("arguments", {})
            handler = TOOL_HANDLERS.get(name)
            if not handler:
                return _make_error(req_id, -32601, f"未知 tool: {name}")
            try:
                result = handler(arguments)
                resp = _make_response(req_id, {
                    "content": [{
                        "type": "text",
                        "text": json.dumps(result, ensure_ascii=False, indent=2),
                    }]
                })
            except InvalidParams as e:
                return _make_error(req_id, -32602, str(e))
            except Exception:
                _logger.exception("tool error: %s", name)
                # 不暴露内部细节给客户端；详细 trace 进 stderr 日志
                return _make_error(req_id, -32603, "Tool error（详见 server stderr 日志）")
        elif method == "ping":
            resp = _make_response(req_id, {})
        else:
            if req_id is not None:
                return _make_error(req_id, -32601, f"未知方法: {method}")
            return None
    finally:
        duration = (time.time() - start) * 1000
        _logger.info("method=%s id=%s duration_ms=%.1f", method, req_id, duration)

    return resp


def serve():
    """主循环：从 stdin 读 JSON-RPC，写到 stdout。

    实现 ndjson 帧（每行一个 JSON）。MCP spec 0.1 要求 LSP-style Content-Length，
    但 Claude Desktop / Cursor 当前都接受 ndjson；如需严格 spec 兼容请扩展。
    """
    _logger.info("MCP server starting (version=%s)", __version__)
    while True:
        try:
            line = sys.stdin.readline()
        except KeyboardInterrupt:
            _logger.info("MCP server interrupted")
            break
        if not line:
            break
        if len(line) > MAX_LINE_BYTES:
            err = _make_error(None, -32600, f"消息超过 {MAX_LINE_BYTES} 字节上限")
            sys.stdout.write(json.dumps(err, ensure_ascii=False) + "\n")
            sys.stdout.flush()
            _logger.warning("payload too large: %d bytes", len(line))
            continue
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as e:
            err = _make_error(None, -32700, f"Parse error: {e}")
            sys.stdout.write(json.dumps(err, ensure_ascii=False) + "\n")
            sys.stdout.flush()
            continue
        try:
            resp = handle_request(req)
        except Exception:
            _logger.exception("unexpected error in handle_request")
            resp = _make_error(req.get("id") if isinstance(req, dict) else None,
                              -32603, "Internal error")
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()


def main():
    serve()


if __name__ == "__main__":
    main()
