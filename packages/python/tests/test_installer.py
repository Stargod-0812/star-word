"""installer 幂等性与文件写入测试."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from star_word import installer


@pytest.fixture
def tmp_project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_enable_claude_code_creates_files(tmp_project):
    r = installer.enable("claude-code")
    assert r.enabled is True
    assert (tmp_project / ".star-word" / "RULES.md").exists()
    assert (tmp_project / ".star-word" / "claude-code.md").exists()
    assert (tmp_project / "CLAUDE.md").exists()
    content = (tmp_project / "CLAUDE.md").read_text(encoding="utf-8")
    assert "star-word:begin" in content
    assert "@.star-word/claude-code.md" in content


def test_enable_claude_code_idempotent(tmp_project):
    installer.enable("claude-code")
    installer.enable("claude-code")  # 再来一次
    content = (tmp_project / "CLAUDE.md").read_text(encoding="utf-8")
    # marker 只有一对
    assert content.count("star-word:begin") == 1
    assert content.count("star-word:end") == 1


def test_enable_then_disable(tmp_project):
    installer.enable("claude-code")
    assert (tmp_project / "CLAUDE.md").exists()
    installer.disable("claude-code")
    # CLAUDE.md 若仅有 marker 块被移除后应被删除（干净状态）
    # 或内容不再包含 marker
    if (tmp_project / "CLAUDE.md").exists():
        content = (tmp_project / "CLAUDE.md").read_text(encoding="utf-8")
        assert "star-word:begin" not in content
    assert not (tmp_project / ".star-word").exists()


def test_enable_preserves_existing_claude_md_content(tmp_project):
    existing = "# 我的全局规则\n\n原有内容。\n"
    (tmp_project / "CLAUDE.md").write_text(existing, encoding="utf-8")
    installer.enable("claude-code")
    content = (tmp_project / "CLAUDE.md").read_text(encoding="utf-8")
    assert "原有内容。" in content
    assert "star-word:begin" in content


def test_disable_preserves_user_content(tmp_project):
    existing = "# 我的全局规则\n\n原有内容。\n"
    (tmp_project / "CLAUDE.md").write_text(existing, encoding="utf-8")
    installer.enable("claude-code")
    installer.disable("claude-code")
    content = (tmp_project / "CLAUDE.md").read_text(encoding="utf-8")
    assert "原有内容。" in content
    assert "star-word:begin" not in content


def test_enable_agents_md(tmp_project):
    r = installer.enable("agents-md")
    assert r.enabled is True
    assert (tmp_project / "AGENTS.md").exists()
    content = (tmp_project / "AGENTS.md").read_text(encoding="utf-8")
    assert "star-word v0.1.0" in content
    assert "禁止词汇" in content


def test_unknown_tool_raises():
    with pytest.raises(ValueError):
        installer.enable("not-a-real-tool")


def test_list_tools():
    tools = installer.list_tools()
    names = {t["name"] for t in tools}
    assert "claude-code" in names
    assert "agents-md" in names
    assert "codex" in names
