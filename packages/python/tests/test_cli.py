"""CLI 端到端测试."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


def _run(args, cwd=None):
    return subprocess.run(
        [sys.executable, "-m", "star_word.cli", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def test_cli_version():
    r = _run(["--version"])
    assert r.returncode == 0
    assert "star-word" in r.stdout


def test_cli_list_tools_json():
    r = _run(["list-tools", "--json"])
    assert r.returncode == 0
    data = json.loads(r.stdout)
    assert any(t["name"] == "claude-code" for t in data)


def test_cli_verify():
    r = _run(["verify"])
    assert r.returncode == 0
    assert "star-word v" in r.stdout
    assert "21 条" in r.stdout


def test_cli_review_clean_text(tmp_path):
    f = tmp_path / "clean.md"
    f.write_text("这是一段干净的技术描述。订单服务延迟 3ms。\n", encoding="utf-8")
    r = _run(["review", str(f)])
    assert r.returncode == 0, r.stdout + r.stderr


def test_cli_review_detects_violations(tmp_path):
    f = tmp_path / "dirty.md"
    f.write_text(
        "值得注意的是，我们通过顶层设计赋能业务。好问题，让我来为您解释。\n",
        encoding="utf-8",
    )
    r = _run(["review", str(f)])
    assert r.returncode == 1  # 有违规应返回 1


def test_cli_review_json_output(tmp_path):
    f = tmp_path / "dirty.md"
    f.write_text("综上所述，这是一个抓手。\n", encoding="utf-8")
    r = _run(["review", str(f), "--json"])
    assert r.returncode == 1
    data = json.loads(r.stdout)
    assert data["file"].endswith("dirty.md")
    star02 = next(r for r in data["results"] if r["rule_id"] == "STAR-02")
    assert star02["violation_count"] >= 1


def test_cli_enable_disable_cycle(tmp_path):
    r = _run(["enable", "claude-code"], cwd=tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (tmp_path / "CLAUDE.md").exists()
    assert (tmp_path / ".star-word" / "RULES.md").exists()

    r = _run(["disable", "claude-code"], cwd=tmp_path)
    assert r.returncode == 0
    assert not (tmp_path / ".star-word").exists()


def test_cli_unknown_tool_error():
    r = _run(["enable", "no-such-tool"])
    assert r.returncode == 2
    assert "未知工具" in r.stderr
