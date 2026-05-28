"""CLI 端到端测试."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from contextlib import redirect_stderr, redirect_stdout

from star_word.cli import main as cli_main


def _run(args, cwd=None, extra_env=None):
    env = os.environ.copy()
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
    allowed_modes = {"anchor-import", "guarded-block", "manual-paste", "rule-file", "skill-file", "stdio-server"}
    for s in data:
        assert s["mode"] in allowed_modes


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


# ============================================================================
# v0.4.2: In-process CLI tests (覆盖 cli.py，不靠 subprocess)
#
# subprocess 跑的 _run() 不计入 coverage——cli.py 0% 是这个原因。
# 用 main(argv) 直接调，让 coverage 看见。
# ============================================================================


def _run_inproc(args):
    """直接调 main(argv) 而不 subprocess，让 coverage 计入。"""
    out = io.StringIO()
    err = io.StringIO()
    try:
        with redirect_stdout(out), redirect_stderr(err):
            rc = cli_main(args)
    except SystemExit as e:
        rc = e.code or 0
    return rc, out.getvalue(), err.getvalue()


def test_cli_inproc_surfaces():
    rc, out, _ = _run_inproc(["surfaces"])
    assert rc == 0
    assert "claude-code" in out
    assert "stdio-server" in out  # mcp 接入面


def test_cli_inproc_handshake():
    rc, out, _ = _run_inproc(["handshake"])
    assert rc == 0
    assert "已加载" in out


def test_cli_inproc_review_clean(tmp_path):
    f = tmp_path / "clean.md"
    f.write_text("订单服务延迟 3ms，用 Redis 做缓存。\n" * 3, encoding="utf-8")
    rc, _, _ = _run_inproc(["review", str(f)])
    assert rc == 0


def test_cli_inproc_review_dirty_text_format(tmp_path):
    f = tmp_path / "dirty.md"
    f.write_text("综上所述，这是赋能业务的抓手。\n" * 3, encoding="utf-8")
    rc, out, _ = _run_inproc(["review", str(f)])
    assert rc == 1
    assert "词-01" in out or "词-02" in out


def test_cli_inproc_review_json(tmp_path):
    f = tmp_path / "dirty.md"
    f.write_text("综上所述，这是抓手。\n" * 3, encoding="utf-8")
    rc, out, _ = _run_inproc(["review", str(f), "--json"])
    assert rc == 1
    import json as _json
    data = _json.loads(out)
    assert "score" in data
    assert "results" in data


def test_cli_inproc_review_audit_only(tmp_path):
    f = tmp_path / "dirty.md"
    f.write_text("综上所述，这是抓手。\n" * 3, encoding="utf-8")
    rc, out, _ = _run_inproc(["review", str(f), "--audit-only"])
    assert rc == 1
    import json as _json
    _json.loads(out)  # audit-only 必输 JSON


def test_cli_inproc_review_fail_under(tmp_path):
    """--fail-under 触发非零退出码即使无违规（仅当分数低于阈值）。"""
    f = tmp_path / "dirty.md"
    f.write_text("综上所述，这是赋能。" * 30, encoding="utf-8")
    rc, _, _ = _run_inproc(["review", str(f), "--fail-under", "99"])
    assert rc == 1


def test_cli_inproc_review_modes(tmp_path):
    """三个 mode 都不 crash（rc 0 或 1 都行，关键是不 raise）。"""
    f = tmp_path / "doc.md"
    f.write_text("订单服务延迟 3ms。\n" * 5, encoding="utf-8")
    for mode in ["strict", "normal", "relaxed"]:
        rc, _, _ = _run_inproc(["review", str(f), "--mode", mode])
        assert rc in (0, 1), f"mode={mode} 异常退出码 {rc}"


def test_cli_inproc_review_missing_file():
    rc, _, err = _run_inproc(["review", "/nonexistent/file.md"])
    assert rc == 2
    assert "不存在" in err


def test_cli_inproc_review_invalid_utf8(tmp_path):
    f = tmp_path / "bad.md"
    f.write_bytes(b"\xff\xfe\xfd")
    rc, _, err = _run_inproc(["review", str(f)])
    assert rc == 2
    assert "UTF-8" in err or "decode" in err.lower()


def test_cli_inproc_enable_disable(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rc, out, _ = _run_inproc(["enable", "claude-code"])
    assert rc == 0
    assert (tmp_path / "CLAUDE.md").exists()
    rc, _, _ = _run_inproc(["disable", "claude-code"])
    assert rc == 0


def test_cli_inproc_enable_unknown():
    rc, _, err = _run_inproc(["enable", "no-such"])
    assert rc == 2
    assert "未知接入面" in err


def test_cli_inproc_enable_json(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rc, out, _ = _run_inproc(["enable", "claude-code", "--json"])
    assert rc == 0
    import json as _json
    data = _json.loads(out)
    assert data["surface"] == "claude-code"
    assert data["wired"] is True


def test_cli_inproc_judge_no_api_key(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    f = tmp_path / "doc.md"
    f.write_text("订单服务延迟。" * 10, encoding="utf-8")
    rc, _, err = _run_inproc(["judge", str(f)])
    assert rc == 2
    assert "API key" in err or "ANTHROPIC_API_KEY" in err


def test_cli_inproc_judge_missing_file():
    rc, _, err = _run_inproc(["judge", "/nonexistent.md"])
    assert rc == 2
    assert "不存在" in err


def test_cli_inproc_fix_missing_file():
    rc, _, err = _run_inproc(["fix", "/nonexistent.md"])
    assert rc == 2
    assert "不存在" in err


def test_cli_inproc_fix_no_api_key(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    f = tmp_path / "doc.md"
    f.write_text("综上所述，这是赋能业务的抓手。" * 5, encoding="utf-8")
    rc, _, err = _run_inproc(["fix", str(f)])
    assert rc == 2
    assert "API key" in err or "ANTHROPIC_API_KEY" in err


def test_cli_inproc_disable_unknown():
    rc, _, err = _run_inproc(["disable", "no-such"])
    assert rc == 2
    assert "未知接入面" in err
