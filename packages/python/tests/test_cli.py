"""CLI 端到端测试."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


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


def test_cli_surfaces_json():
    r = _run(["surfaces", "--json"])
    assert r.returncode == 0
    data = json.loads(r.stdout)
    assert any(s["surface"] == "claude-code" for s in data)
    # 确保 mode 命名已去 agent-style 化
    for s in data:
        assert s["mode"] in {"anchor-import", "guarded-block", "manual-paste"}


def test_cli_handshake():
    r = _run(["handshake"])
    assert r.returncode == 0
    # 新的 handshake 文本不使用 agent-style 的 "active: ... " 格式
    assert "已加载 star-word" in r.stdout
    assert "词表" in r.stdout and "结构" in r.stdout and "判断" in r.stdout
    assert "active:" not in r.stdout


def test_cli_review_clean(tmp_path):
    f = tmp_path / "clean.md"
    f.write_text("订单服务延迟 3ms，用 Redis 做缓存。\n", encoding="utf-8")
    r = _run(["review", str(f)])
    assert r.returncode == 0, r.stdout + r.stderr


def test_cli_review_detects(tmp_path):
    f = tmp_path / "dirty.md"
    f.write_text(
        "值得注意的是，我们通过顶层设计赋能业务。好问题，让我来为您解释。\n",
        encoding="utf-8",
    )
    r = _run(["review", str(f)])
    assert r.returncode == 1


def test_cli_review_json(tmp_path):
    f = tmp_path / "dirty.md"
    f.write_text("综上所述，这是一个抓手。\n", encoding="utf-8")
    r = _run(["review", str(f), "--json"])
    assert r.returncode == 1
    data = json.loads(r.stdout)
    assert data["file"].endswith("dirty.md")
    rule_02 = next(r for r in data["results"] if r["rule_id"] == "词-02")
    assert rule_02["violation_count"] >= 1


def test_cli_enable_disable_cycle(tmp_path):
    r = _run(["enable", "claude-code"], cwd=tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (tmp_path / "CLAUDE.md").exists()
    assert (tmp_path / ".sw" / "rules.md").exists()

    r = _run(["disable", "claude-code"], cwd=tmp_path)
    assert r.returncode == 0
    assert not (tmp_path / ".sw").exists()


def test_cli_unknown_surface_error():
    r = _run(["enable", "no-such-surface"])
    assert r.returncode == 2
    assert "未知接入面" in r.stderr
