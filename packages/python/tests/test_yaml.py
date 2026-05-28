"""_yaml.py fallback parser 测试 (v0.4.4).

强制走 fallback path（无 PyYAML），覆盖 nested dict / list / inline / literal block
+ 深度炸弹 / 极端输入。
"""

from __future__ import annotations

import sys

import pytest

from star_word._yaml import _yaml_parse_block, _yaml_scalar, parse_yaml

# -------- 强制走 fallback (no PyYAML) --------


@pytest.fixture
def no_pyyaml(monkeypatch):
    """让 import yaml 抛 ImportError，强制走 fallback parser。"""
    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

    def mock_import(name, *args, **kwargs):
        if name == "yaml":
            raise ImportError("no yaml for test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", mock_import)
    # 把 yaml 从 sys.modules 移除以防被缓存
    sys.modules.pop("yaml", None)


# -------- 基本语法 --------


def test_parse_simple_dict(no_pyyaml):
    text = "key: value\nfoo: bar\n"
    assert parse_yaml(text) == {"key": "value", "foo": "bar"}


def test_parse_simple_list(no_pyyaml):
    text = "items:\n  - one\n  - two\n  - three\n"
    assert parse_yaml(text) == {"items": ["one", "two", "three"]}


def test_parse_nested_dict(no_pyyaml):
    text = "outer:\n  inner:\n    leaf: 42\n"
    assert parse_yaml(text) == {"outer": {"inner": {"leaf": 42}}}


def test_parse_inline_dict(no_pyyaml):
    text = "items:\n  - { word: 赋能, match: contains }\n"
    out = parse_yaml(text)
    assert out["items"] == [{"word": "赋能", "match": "contains"}]


def test_parse_literal_block(no_pyyaml):
    text = "body: |\n  line one\n  line two\n  line three\n"
    out = parse_yaml(text)
    assert out["body"] == "line one\nline two\nline three\n"


def test_parse_list_of_dicts_with_continuation(no_pyyaml):
    text = (
        "rules:\n"
        "  - id: rule-01\n"
        "    title: First\n"
        "  - id: rule-02\n"
        "    title: Second\n"
    )
    out = parse_yaml(text)
    assert out["rules"] == [
        {"id": "rule-01", "title": "First"},
        {"id": "rule-02", "title": "Second"},
    ]


# -------- scalar 类型 --------


def test_yaml_scalar_types():
    assert _yaml_scalar('"quoted"') == "quoted"
    assert _yaml_scalar("'single'") == "single"
    assert _yaml_scalar("true") is True
    assert _yaml_scalar("false") is False
    assert _yaml_scalar("null") is None
    assert _yaml_scalar("~") is None
    assert _yaml_scalar("42") == 42
    assert _yaml_scalar("3.14") == 3.14
    assert _yaml_scalar("plain") == "plain"
    assert _yaml_scalar("") == ""


# -------- 安全：深度炸弹 --------


def test_yaml_parser_rejects_deep_nesting():
    """超过 64 层嵌套应 raise（防 stack overflow / billion laughs 类攻击）。"""
    lines = []
    for i in range(100):
        lines.append("  " * i + f"level{i}:")
    with pytest.raises(ValueError, match="嵌套过深"):
        _yaml_parse_block(lines, 0, 0, depth=0)


def test_yaml_parser_handles_empty_input(no_pyyaml):
    """空输入应返回空 dict，不崩。"""
    assert parse_yaml("") == {}
    assert parse_yaml("\n\n") == {}
    assert parse_yaml("# only comment\n") == {}


def test_yaml_parser_handles_comments(no_pyyaml):
    text = "# top comment\nkey: value  # not stripped from value yet\n# another\n"
    out = parse_yaml(text)
    assert "key" in out


# -------- 真实 rules.yaml 解析 --------


def test_parse_real_rules_yaml(no_pyyaml):
    """packaged rules.yaml 真能用 fallback parser 跑出 22 条规则。"""
    from pathlib import Path
    yaml_path = Path(__file__).parent.parent / "star_word" / "data" / "rules.yaml"
    assert yaml_path.exists(), f"data file missing: {yaml_path}"
    text = yaml_path.read_text(encoding="utf-8")
    data = parse_yaml(text)
    assert "meta" in data
    assert "rules" in data
    assert isinstance(data["rules"], list)
    assert len(data["rules"]) == data["meta"]["total_rules"]


# -------- PyYAML 路径 --------


def test_pyyaml_path_when_available():
    """有 PyYAML 时优先用 yaml.safe_load。"""
    text = "key: value\n"
    out = parse_yaml(text)
    assert out == {"key": "value"}
