"""star-word installer: 把规则文件写到目标项目/全局，并在 CLAUDE.md / AGENTS.md 追加 import/marker。"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import __version__

MARKER_BEGIN = "<!-- star-word:begin (managed) -->"
MARKER_END = "<!-- star-word:end -->"

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"


@dataclass
class InstallResult:
    tool: str
    mode: str
    enabled: bool
    target: str
    notes: str = ""


def _data_path(*parts: str) -> Path:
    p = DATA_DIR.joinpath(*parts)
    if not p.exists():
        raise FileNotFoundError(f"star-word 数据文件缺失：{p}. 请重装: pip install --force-reinstall star-word")
    return p


def _resolve_target_root(global_scope: bool) -> Path:
    if global_scope:
        root = Path.home() / ".claude"
        root.mkdir(parents=True, exist_ok=True)
        return root
    return Path.cwd()


def _write_shared_rules(root: Path) -> None:
    """把 RULES.md 与 adapter 数据写到 <root>/.star-word/."""
    target_dir = root / ".star-word"
    target_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(_data_path("RULES.md"), target_dir / "RULES.md")
    adapter_dir = target_dir / "adapters"
    adapter_dir.mkdir(exist_ok=True)
    for fname in ("claude-code.md", "AGENTS.md", "codex.md"):
        shutil.copy2(_data_path("adapters", fname), adapter_dir / fname)
    # adapter-claude-code 放在 .star-word/ 顶层，供 @.star-word/claude-code.md 引用
    shutil.copy2(
        _data_path("adapters", "claude-code.md"), target_dir / "claude-code.md"
    )


def _append_marker_block(target_file: Path, body: str) -> bool:
    """幂等追加 marker 块. 若已存在同内容块则不重复. 返回 True 表示有改动。"""
    new_block = f"{MARKER_BEGIN}\n{body.rstrip()}\n{MARKER_END}\n"
    if target_file.exists():
        current = target_file.read_text(encoding="utf-8")
        if MARKER_BEGIN in current and MARKER_END in current:
            updated = re.sub(
                re.escape(MARKER_BEGIN) + r".*?" + re.escape(MARKER_END) + r"\n?",
                new_block,
                current,
                count=1,
                flags=re.DOTALL,
            )
            if updated == current:
                return False
            target_file.write_text(updated, encoding="utf-8")
            return True
        new_content = current.rstrip() + "\n\n" + new_block
        target_file.write_text(new_content, encoding="utf-8")
        return True
    target_file.write_text(new_block, encoding="utf-8")
    return True


def _remove_marker_block(target_file: Path) -> bool:
    if not target_file.exists():
        return False
    current = target_file.read_text(encoding="utf-8")
    if MARKER_BEGIN not in current:
        return False
    updated = re.sub(
        re.escape(MARKER_BEGIN) + r".*?" + re.escape(MARKER_END) + r"\n?",
        "",
        current,
        flags=re.DOTALL,
    )
    updated = updated.rstrip() + "\n"
    if updated.strip():
        target_file.write_text(updated, encoding="utf-8")
    else:
        target_file.unlink()
    return True


# -------- 各工具的 enable/disable --------


def enable_claude_code(global_scope: bool = False) -> InstallResult:
    root = _resolve_target_root(global_scope)
    _write_shared_rules(root)
    claude_md = root / "CLAUDE.md"
    _append_marker_block(claude_md, "@.star-word/claude-code.md")
    return InstallResult(
        tool="claude-code",
        mode="import-marker",
        enabled=True,
        target=str(claude_md),
        notes=f"规则文件写入 {root/'.star-word'}；在 {claude_md} 追加 @-import 块。",
    )


def disable_claude_code(global_scope: bool = False) -> InstallResult:
    root = _resolve_target_root(global_scope)
    claude_md = root / "CLAUDE.md"
    changed = _remove_marker_block(claude_md)
    sw_dir = root / ".star-word"
    if sw_dir.exists():
        shutil.rmtree(sw_dir)
    return InstallResult(
        tool="claude-code",
        mode="import-marker",
        enabled=False,
        target=str(claude_md),
        notes=("已移除 marker 块并清理 .star-word/" if changed else "未发现 marker 块；已清理 .star-word/（若存在）。"),
    )


def enable_agents_md(global_scope: bool = False) -> InstallResult:
    root = _resolve_target_root(global_scope)
    _write_shared_rules(root)
    agents_md = root / "AGENTS.md"
    body_path = _data_path("adapters", "AGENTS.md")
    body = body_path.read_text(encoding="utf-8")
    # 从 adapters/AGENTS.md 中提取 managed block 的 body（marker 之间的内容）
    m = re.search(
        r"<!-- star-word:begin \(managed\) -->\n(.*?)\n<!-- star-word:end -->",
        body,
        flags=re.DOTALL,
    )
    block_body = m.group(1).strip() if m else body
    _append_marker_block(agents_md, block_body)
    return InstallResult(
        tool="agents-md",
        mode="append-block",
        enabled=True,
        target=str(agents_md),
        notes=f"在 {agents_md} 追加 marker 块；规则体写到 {root/'.star-word'}。",
    )


def disable_agents_md(global_scope: bool = False) -> InstallResult:
    root = _resolve_target_root(global_scope)
    agents_md = root / "AGENTS.md"
    changed = _remove_marker_block(agents_md)
    sw_dir = root / ".star-word"
    if sw_dir.exists():
        shutil.rmtree(sw_dir)
    return InstallResult(
        tool="agents-md",
        mode="append-block",
        enabled=False,
        target=str(agents_md),
        notes=("已移除 marker 块并清理 .star-word/" if changed else "未发现 marker 块；已清理 .star-word/（若存在）。"),
    )


def enable_codex(global_scope: bool = False) -> InstallResult:
    """Codex 是 print-only：把 system prompt 写到磁盘，并返回待粘贴的内容。"""
    root = _resolve_target_root(global_scope)
    _write_shared_rules(root)
    prompt_path = root / ".star-word" / "codex-system-prompt.md"
    shutil.copy2(_data_path("adapters", "codex.md"), prompt_path)
    return InstallResult(
        tool="codex",
        mode="print-only",
        enabled=False,  # 真正生效要用户手动粘贴进 API
        target=str(prompt_path),
        notes=(
            f"规则 system prompt 已写入 {prompt_path}。\n"
            "手动步骤：把该文件 ## SYSTEM PROMPT 小节的 ``` 块内容粘贴到 Codex API 的 system_prompt 字段。"
        ),
    )


SUPPORTED_TOOLS = {
    "claude-code": (enable_claude_code, disable_claude_code),
    "agents-md": (enable_agents_md, disable_agents_md),
    "codex": (enable_codex, lambda global_scope=False: InstallResult(
        tool="codex", mode="print-only", enabled=False,
        target="", notes="Codex 是 print-only，直接删除你粘贴进 API 的 system_prompt 即可。",
    )),
}


def enable(tool: str, global_scope: bool = False) -> InstallResult:
    if tool not in SUPPORTED_TOOLS:
        raise ValueError(f"未知工具: {tool}. 支持列表: {', '.join(SUPPORTED_TOOLS)}")
    return SUPPORTED_TOOLS[tool][0](global_scope)


def disable(tool: str, global_scope: bool = False) -> InstallResult:
    if tool not in SUPPORTED_TOOLS:
        raise ValueError(f"未知工具: {tool}. 支持列表: {', '.join(SUPPORTED_TOOLS)}")
    return SUPPORTED_TOOLS[tool][1](global_scope)


def list_tools() -> list[dict]:
    return [
        {"name": "claude-code", "mode": "import-marker", "target": "CLAUDE.md"},
        {"name": "agents-md", "mode": "append-block", "target": "AGENTS.md"},
        {"name": "codex", "mode": "print-only", "target": ".star-word/codex-system-prompt.md"},
    ]
