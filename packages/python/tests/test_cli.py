"""CLI 端到端测试."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def _run(args, cwd=None, extra_env=None):
    env = os.environ.copy()
    package_root = Path(__file__).resolve().parent.parent
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(package_root) if not existing_pythonpath else os.pathsep.join([str(package_root), existing_pythonpath])
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-m", "star_word.cli", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env=env,
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
    assert any(s["surface"] == "codebuddy" for s in data)
    assert any(s["surface"] == "workbuddy" for s in data)
    # 确保 mode 命名已去 agent-style 化
    allowed_modes = {"anchor-import", "guarded-block", "manual-paste", "rule-file", "skill-file"}
    for s in data:
        assert s["mode"] in allowed_modes


def test_cli_handshake():
    r = _run(["handshake"])
    assert r.returncode == 0
    # 新的 handshake 文本不使用 agent-style 的 "active: ... " 格式
    assert "已加载 star-word" in r.stdout
    assert "词表" in r.stdout and "结构" in r.stdout and "判断" in r.stdout
    assert "active:" not in r.stdout


def test_cli_handshake_json():
    r = _run(["handshake", "--json"])
    assert r.returncode == 0
    data = json.loads(r.stdout)
    assert data["version"]
    assert data["counts"] == {"词": 8, "式": 7, "气": 6}
    assert "已加载 star-word" in data["text"]


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


def test_cli_review_directory_error(tmp_path):
    r = _run(["review", str(tmp_path)])
    assert r.returncode == 2
    assert "不是普通文件" in r.stderr
    assert "Traceback" not in r.stderr


def test_cli_enable_disable_cycle(tmp_path):
    r = _run(["enable", "claude-code"], cwd=tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (tmp_path / "CLAUDE.md").exists()
    assert (tmp_path / ".sw" / "rules.md").exists()

    r = _run(["disable", "claude-code"], cwd=tmp_path)
    assert r.returncode == 0
    assert not (tmp_path / ".sw").exists()


def test_cli_enable_codex_reports_pending_manual_step(tmp_path):
    r = _run(["enable", "codex"], cwd=tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "已写入，待手动接线" in r.stdout
    prompt = tmp_path / ".sw" / "codex-system-prompt.md"
    assert prompt.exists()
    assert "## SYSTEM PROMPT" not in prompt.read_text(encoding="utf-8")


def test_cli_enable_disable_codebuddy(tmp_path):
    r = _run(["enable", "codebuddy"], cwd=tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (tmp_path / ".codebuddy" / "rules" / "star-word" / "RULE.mdc").exists()

    r = _run(["disable", "codebuddy"], cwd=tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert not (tmp_path / ".codebuddy" / "rules" / "star-word").exists()


def test_cli_enable_disable_workbuddy(tmp_path):
    fake_home = tmp_path / "fake-home"
    fake_home.mkdir()
    env = {"HOME": str(fake_home)}

    r = _run(["enable", "workbuddy"], cwd=tmp_path, extra_env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (fake_home / ".workbuddy" / "skills" / "star-word" / "SKILL.md").exists()

    r = _run(["disable", "workbuddy"], cwd=tmp_path, extra_env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert not (fake_home / ".workbuddy" / "skills" / "star-word").exists()


def test_cli_unknown_surface_error():
    r = _run(["enable", "no-such-surface"])
    assert r.returncode == 2
    assert "未知接入面" in r.stderr
