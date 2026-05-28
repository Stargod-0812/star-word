"""star-word MCP server（v0.4）.

零依赖的 stdio MCP server。实现 4 个工具：
- review_text: 机械检测
- judge_text: LLM-as-judge 语义评分
- get_rules: 列出所有规则
- suggest_rewrite: 改写建议

不依赖 `mcp` Python SDK——直接 JSON-RPC 2.0 over stdio。
设计目标：兼容 MCP 0.1 spec 的核心子集，足够 Claude Desktop / Cursor / Cline 接入。

启动：
    python -m star_word.mcp_server

或在 Claude Desktop 配置：
    {
      "mcpServers": {
        "star-word": {
          "command": "python",
          "args": ["-m", "star_word.mcp_server"]
        }
      }
    }
"""

from __future__ import annotations

import json
import sys
from typing import Any

from . import __version__
from . import detectors, scoring


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
        "description": "LLM-as-judge 评估语义规则（气组 + 部分式组）。返回每条规则 0-10 分 + reasoning。需要 ANTHROPIC_API_KEY。",
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
                "max_violations": {"type": "integer", "default": 20},
            },
            "required": ["text"],
        },
    },
]


# -------- 工具实现 --------


def _tool_review_text(args: dict) -> dict:
    text = args.get("text", "")
    mode = args.get("mode", "normal")
    results = detectors.review(text)
    doc = scoring.score_document(results, text, mode=mode)
    return {
        "score": round(doc.score, 1),
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
    text = args.get("text", "")
    rule_ids = args.get("rules")
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
    # 词组
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
    # 式组
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
    # 气组
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
    text = args.get("text", "")
    max_violations = args.get("max_violations", 20)
    from . import rewriter
    results = detectors.review(text)
    try:
        suggestions = rewriter.suggest_rewrites(text, results, max_violations=max_violations)
    except rewriter.RewriteError as e:
        return {"error": str(e), "suggestions": []}
    return {
        "suggestions": [
            {
                "line": s.line,
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


def handle_request(req: dict) -> dict | None:
    """处理一个 JSON-RPC 请求。返回 None 表示是 notification（不需回复）。"""
    method = req.get("method")
    req_id = req.get("id")
    params = req.get("params", {})

    if method == "initialize":
        return _make_response(req_id, {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "star-word", "version": __version__},
        })

    if method == "notifications/initialized":
        return None  # notification, no response

    if method == "tools/list":
        return _make_response(req_id, {"tools": TOOLS})

    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments", {})
        handler = TOOL_HANDLERS.get(name)
        if not handler:
            return _make_error(req_id, -32601, f"Unknown tool: {name}")
        try:
            result = handler(arguments)
            return _make_response(req_id, {
                "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}]
            })
        except Exception as e:
            return _make_error(req_id, -32603, f"Tool error: {type(e).__name__}: {e}")

    if method == "ping":
        return _make_response(req_id, {})

    if req_id is not None:
        return _make_error(req_id, -32601, f"Unknown method: {method}")
    return None


def serve():
    """主循环：从 stdin 读 JSON-RPC，写到 stdout。"""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as e:
            err = _make_error(None, -32700, f"Parse error: {e}")
            sys.stdout.write(json.dumps(err) + "\n")
            sys.stdout.flush()
            continue
        resp = handle_request(req)
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()


def main():
    serve()


if __name__ == "__main__":
    main()
