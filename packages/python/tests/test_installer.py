"""installer 幂等 + 隔离 + golden snapshot 测试."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from star_word import installer


@pytest.fixture
def tmp_project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


# -------- enable/disable 生命周期 --------


def test_enable_claude_code_creates_files(tmp_project):
    r = installer.enable("claude-code")
    assert r.wired is True
    assert (tmp_project / ".sw" / "rules.md").exists()
    assert (tmp_project / ".sw" / "claude.md").exists()
    assert (tmp_project / "CLAUDE.md").exists()
    content = (tmp_project / "CLAUDE.md").read_text(encoding="utf-8")
    assert "sw-managed-begin" in content
    assert "@.sw/claude.md" in content


def test_enable_claude_code_idempotent(tmp_project):
    installer.enable("claude-code")
    installer.enable("claude-code")
    content = (tmp_project / "CLAUDE.md").read_text(encoding="utf-8")
    assert content.count("sw-managed-begin") == 1
    assert content.count("sw-managed-end") == 1


def test_enable_then_disable(tmp_project):
    installer.enable("claude-code")
    installer.disable("claude-code")
    if (tmp_project / "CLAUDE.md").exists():
        content = (tmp_project / "CLAUDE.md").read_text(encoding="utf-8")
        assert "sw-managed-begin" not in content
    assert not (tmp_project / ".sw").exists()


def test_enable_preserves_existing_claude_md(tmp_project):
    existing = "# 我的全局规则\n\n原有内容。\n"
    (tmp_project / "CLAUDE.md").write_text(existing, encoding="utf-8")
    installer.enable("claude-code")
    content = (tmp_project / "CLAUDE.md").read_text(encoding="utf-8")
    assert "原有内容。" in content
    assert "sw-managed-begin" in content


def test_disable_preserves_user_content(tmp_project):
    existing = "# 我的全局规则\n\n原有内容。\n"
    (tmp_project / "CLAUDE.md").write_text(existing, encoding="utf-8")
    installer.enable("claude-code")
    installer.disable("claude-code")
    content = (tmp_project / "CLAUDE.md").read_text(encoding="utf-8")
    assert "原有内容。" in content
    assert "sw-managed-begin" not in content


def test_enable_agents_md(tmp_project):
    r = installer.enable("agents-md")
    assert r.wired is True
    assert (tmp_project / "AGENTS.md").exists()
    content = (tmp_project / "AGENTS.md").read_text(encoding="utf-8")
    assert "star-word v0.2.0" in content
    assert "禁用词" in content


def test_enable_codex_writes_prompt(tmp_project):
    r = installer.enable("codex")
    assert r.wired is False  # manual-paste 模式
    assert "codex-system-prompt.md" in r.target
    assert (tmp_project / ".sw" / "codex-system-prompt.md").exists()


def test_unknown_surface_raises():
    with pytest.raises(ValueError):
        installer.enable("not-a-real-surface")


def test_list_surfaces():
    surfaces = installer.list_surfaces()
    names = {s["surface"] for s in surfaces}
    assert {"claude-code", "agents-md", "codex"} <= names
    # 确认不再出现 agent-style 风格的 mode 命名
    modes = {s["mode"] for s in surfaces}
    for bad in {"import-marker", "append-block", "print-only"}:
        assert bad not in modes


# -------- golden snapshot：installed 文件字节级稳定性 --------


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_golden_snapshot_agents_md(tmp_project):
    """锁定 AGENTS.md 安装产物的 hash。内容变了说明规则/adapter 漂移。"""
    installer.enable("agents-md")
    installed = tmp_project / "AGENTS.md"
    # 正文位于 marker 之间，提取出来校验
    text = installed.read_text(encoding="utf-8")
    start = text.index("<!-- sw-managed-begin -->")
    end = text.index("<!-- sw-managed-end -->") + len("<!-- sw-managed-end -->")
    body = text[start:end]
    # 从 adapter 源文件的 body 也提取一次，应该 byte-exact 相同
    src = (
        Path(__file__).resolve().parent.parent
        / "star_word" / "data" / "adapters" / "AGENTS.md"
    ).read_text(encoding="utf-8")
    src_start = src.index("<!-- sw-managed-begin -->")
    src_end = src.index("<!-- sw-managed-end -->") + len("<!-- sw-managed-end -->")
    assert body == src[src_start:src_end], "AGENTS.md 安装产物与 adapter 源文件 body 不一致"


def test_golden_snapshot_claude_rules(tmp_project):
    """锁定 .sw/rules.md 的 hash —— 随包分发的规则体不能与源 RULES.md 漂移."""
    installer.enable("claude-code")
    installed = tmp_project / ".sw" / "rules.md"
    src = Path(__file__).resolve().parent.parent / "star_word" / "data" / "RULES.md"
    assert _sha256(installed) == _sha256(src), ".sw/rules.md 内容与 data/RULES.md 不一致"


def test_golden_snapshot_claude_adapter(tmp_project):
    """锁定 .sw/claude.md 的 hash."""
    installer.enable("claude-code")
    installed = tmp_project / ".sw" / "claude.md"
    src = (
        Path(__file__).resolve().parent.parent
        / "star_word" / "data" / "adapters" / "claude-code.md"
    )
    assert _sha256(installed) == _sha256(src), ".sw/claude.md 内容与 adapter 源不一致"


def test_marker_syntax_not_agent_style(tmp_project):
    """确保 marker 语法不与 agent-style 的 :begin/:end 约定相同."""
    installer.enable("claude-code")
    content = (tmp_project / "CLAUDE.md").read_text(encoding="utf-8")
    # star-word v0.2 marker = sw-managed-begin / sw-managed-end
    assert "sw-managed-begin" in content
    # agent-style 的旧 pattern 不应出现
    assert ":begin" not in content
    assert ":end" not in content


# -------- encoding 鲁棒性 --------


def test_enable_handles_crlf_in_existing(tmp_project):
    """如果用户的 CLAUDE.md 用 CRLF 行尾，enable 应不炸且保留用户内容."""
    existing = "# 我的规则\r\n\r\n原有内容。\r\n"
    (tmp_project / "CLAUDE.md").write_bytes(existing.encode("utf-8"))
    installer.enable("claude-code")
    content = (tmp_project / "CLAUDE.md").read_text(encoding="utf-8")
    assert "原有内容。" in content


def test_enable_handles_bom_in_existing(tmp_project):
    existing = "\ufeff# BOM 打头\n原有内容。\n"
    (tmp_project / "CLAUDE.md").write_text(existing, encoding="utf-8")
    installer.enable("claude-code")
    content = (tmp_project / "CLAUDE.md").read_text(encoding="utf-8")
    assert "原有内容。" in content
