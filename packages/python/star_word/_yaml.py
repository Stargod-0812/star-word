"""极简 YAML 解析器，支持 rules.yaml 用到的全部语法。

v0.4.3 起从 scripts/build.py 抽到这里，让 detectors / scripts/build / mcp_server
共用同一份解析逻辑——避免 architect 反馈的「scripts/ 不在 wheel 里 → pip
安装的用户 fallback 失败 → 静默退到 6 条 hardcoded 词表」问题。

只支持 rules.yaml 用到的语法：
- 嵌套 dict / list / scalar
- inline dict: { key: value, key: value }
- literal block (`|`)
- 引号字符串、布尔、null、整数、浮点
- 注释 (# 起的行)

不支持完整 YAML（anchors、tags、flow-style sequence、multi-doc 等）——若有
PyYAML 可用则优先用 yaml.safe_load。
"""

from __future__ import annotations

import re
from typing import Any


def parse_yaml(text: str) -> dict[str, Any]:
    """解析 YAML 文本为 Python 对象。

    优先用 PyYAML（更鲁棒），无则降级到自带极简 parser。
    单一来源：detectors / scripts/build 都用此函数，不再有 silent fallback 路径。
    """
    try:
        import yaml

        result = yaml.safe_load(text)
        if result is None:
            return {}
        if not isinstance(result, dict):
            raise ValueError(f"rules.yaml 顶层不是 mapping: {type(result).__name__}")
        return result
    except ImportError:
        pass

    lines = text.splitlines()
    parsed, _ = _yaml_parse_block(lines, 0, 0)
    if not isinstance(parsed, dict):
        raise ValueError(f"rules.yaml 顶层不是 mapping: {type(parsed).__name__}")
    return parsed


def _parse_inline_dict(s: str) -> dict[str, Any]:
    """解析 YAML inline dict: { key: value, key: value }."""
    s = s.strip()
    if s.startswith("{"):
        s = s[1:]
    if s.endswith("}"):
        s = s[:-1]
    result: dict[str, Any] = {}
    parts = re.split(r",\s*(?=\w+\s*:)", s)
    for part in parts:
        part = part.strip()
        if not part:
            continue
        key, _, val = part.partition(":")
        key = key.strip()
        val = val.strip()
        if key and val:
            result[key] = _yaml_scalar(val)
        elif key:
            result[key] = ""
    return result


def _yaml_parse_block(
    lines: list[str], start: int, indent: int, depth: int = 0
) -> tuple[Any, int]:
    """解析一个 YAML 块，返回 (value, next_line_index)。深度上限 64 防恶意 yaml。"""
    if depth > 64:
        raise ValueError("YAML 嵌套过深（>64 层）；可能是攻击或文件损坏。")
    result: dict[str, Any] | list[Any] | None = None
    i = start
    while i < len(lines):
        raw = lines[i]
        if not raw.strip() or raw.lstrip().startswith("#"):
            i += 1
            continue
        line_indent = len(raw) - len(raw.lstrip())
        if line_indent < indent:
            break
        if line_indent > indent:
            i += 1
            continue
        stripped = raw.strip()
        # List item
        if stripped.startswith("- "):
            if result is None:
                result = []
            assert isinstance(result, list)  # mypy narrow
            item_text = stripped[2:]
            if ":" in item_text and not item_text.startswith("{"):
                key, _, val = item_text.partition(":")
                obj: dict[str, Any] = {}
                if val.strip():
                    obj[key.strip()] = _yaml_scalar(val.strip())
                elif i + 1 < len(lines):
                    sub, next_i = _yaml_parse_block(lines, i + 1, line_indent + 2, depth + 1)
                    if isinstance(sub, dict):
                        obj.update(sub)
                    i = next_i - 1
                # Continuation fields at indent + 2
                next_line = i + 1
                while next_line < len(lines):
                    nraw = lines[next_line]
                    if not nraw.strip() or nraw.lstrip().startswith("#"):
                        next_line += 1
                        continue
                    nindent = len(nraw) - len(nraw.lstrip())
                    if nindent == line_indent + 2 and not nraw.strip().startswith("- "):
                        sub, end = _yaml_parse_block(lines, next_line, line_indent + 2, depth + 1)
                        if isinstance(sub, dict):
                            obj.update(sub)
                        i = end - 1
                        next_line = end
                    else:
                        break
                result.append(obj)
            elif item_text.startswith("{"):
                result.append(_parse_inline_dict(item_text))
            else:
                result.append(_yaml_scalar(item_text))
            i += 1
        elif ":" in stripped:
            key, _, val = stripped.partition(":")
            key = key.strip()
            val = val.strip()
            if result is None:
                result = {}
            if val == "":
                sub, end = _yaml_parse_block(lines, i + 1, indent + 2, depth + 1)
                result[key] = sub  # type: ignore
                i = end
            elif val == "|":
                block_lines: list[str] = []
                i += 1
                block_indent: int | None = None
                while i < len(lines):
                    bline = lines[i]
                    if not bline.strip():
                        block_lines.append("")
                        i += 1
                        continue
                    bindent = len(bline) - len(bline.lstrip())
                    if block_indent is None:
                        block_indent = bindent
                    if bindent < block_indent and bline.strip():
                        break
                    block_lines.append(bline[block_indent:] if len(bline) >= block_indent else "")
                    i += 1
                result[key] = "\n".join(block_lines).rstrip() + "\n"  # type: ignore
            else:
                result[key] = _yaml_scalar(val)  # type: ignore
                i += 1
        else:
            i += 1
    return result if result is not None else {}, i


def _yaml_scalar(s: str) -> Any:
    s = s.strip()
    if not s:
        return ""
    if s.startswith('"') and s.endswith('"'):
        return s[1:-1]
    if s.startswith("'") and s.endswith("'"):
        return s[1:-1]
    if s == "true":
        return True
    if s == "false":
        return False
    if s == "null" or s == "~":
        return None
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return s
