"""star-word installer: 把规则文件写到目标项目/全局，并在 CLAUDE.md / AGENTS.md 追加 import/marker。"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import __version__

# 不与常见 lint/linter marker 重合的 namespace（刻意避开 agent-style 的 :begin/:end 模式）
MARKER_BEGIN = "<!-- sw-managed-begin -->"
MARKER_END = "<!-- sw-managed-end -->"

STORE_DIR_NAME = ".sw"

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"


@dataclass
class InstallResult:
    surface: str           # Claude Code / AGENTS.md / Codex 等「接入面」
    mode: str              # anchor-import / guarded-block / manual-paste
    wired: bool            # 是否已接线
    target: str            # 操作的文件路径
    notes: str = ""


def _data_path(*parts: str) -> Path:
    p = DATA_DIR.joinpath(*parts)
    if not p.exists():
        raise FileNotFoundError(
            f"star-word 数据文件缺失：{p}. 请重装: pip install --force-reinstall star-word"
        )
    return p


def _resolve_target_root(global_scope: bool) -> Path:
    if global_scope:
        root = Path.home() / ".claude"
        root.mkdir(parents=True, exist_ok=True)
        return root
    return Path.cwd()


def _write_shared_rules(root: Path) -> None:
    """把 rules.md 与 adapter 写到 <root>/.sw/."""
    store = root / STORE_DIR_NAME
    store.mkdir(parents=True, exist_ok=True)
    # 主规则体用小写 rules.md（避免 CAPS LOCK 视觉上与 agent-style 的 RULES.md 雷同）
    shutil.copy2(_data_path("RULES.md"), store / "rules.md")
    # Claude Code adapter 叫 claude.md，对外 import 路径是 @.sw/claude.md
    shutil.copy2(_data_path("adapters", "claude-code.md"), store / "claude.md")
    # 同时放一份 yaml source（方便离线查阅）
    yaml_src = DATA_DIR / "rules.yaml"
    if yaml_src.exists():
        shutil.copy2(yaml_src, store / "rules.yaml")


def _merge_marker_block(target_file: Path, body: str) -> bool:
    """幂等写入 marker 块。返回 True 表示有改动。"""
    block = f"{MARKER_BEGIN}\n{body.rstrip()}\n{MARKER_END}\n"
    if target_file.exists():
        current = target_file.read_text(encoding="utf-8")
        if MARKER_BEGIN in current and MARKER_END in current:
            updated = re.sub(
                re.escape(MARKER_BEGIN) + r".*?" + re.escape(MARKER_END) + r"\n?",
                block,
                current,
                count=1,
                flags=re.DOTALL,
            )
            if updated == current:
                return False
            target_file.write_text(updated, encoding="utf-8")
            return True
        new_content = current.rstrip() + "\n\n" + block
        target_file.write_text(new_content, encoding="utf-8")
        return True
    target_file.write_text(block, encoding="utf-8")
    return True


def _strip_marker_block(target_file: Path) -> bool:
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


# -------- surfaces --------

# anchor-import: 在目标文件写入一个 @-anchor 指向项目内的规则文件
def enable_claude_code(global_scope: bool = False) -> InstallResult:
    root = _resolve_target_root(global_scope)
    _write_shared_rules(root)
    claude_md = root / "CLAUDE.md"
    _merge_marker_block(claude_md, f"@{STORE_DIR_NAME}/claude.md")
    return InstallResult(
        surface="claude-code",
        mode="anchor-import",
        wired=True,
        target=str(claude_md),
        notes=f"规则落到 {root/STORE_DIR_NAME}；{claude_md} 追加了 @-anchor 块。",
    )


def disable_claude_code(global_scope: bool = False) -> InstallResult:
    root = _resolve_target_root(global_scope)
    claude_md = root / "CLAUDE.md"
    changed = _strip_marker_block(claude_md)
    sw_dir = root / STORE_DIR_NAME
    if sw_dir.exists():
        shutil.rmtree(sw_dir)
    return InstallResult(
        surface="claude-code",
        mode="anchor-import",
        wired=False,
        target=str(claude_md),
        notes=("清掉 marker 块并删除 .sw/" if changed else f"未见 marker 块；已清理 {STORE_DIR_NAME}/（若存在）"),
    )


# guarded-block: 在 AGENTS.md 中嵌入受保护的规则块
def enable_agents_md(global_scope: bool = False) -> InstallResult:
    root = _resolve_target_root(global_scope)
    _write_shared_rules(root)
    agents_md = root / "AGENTS.md"
    adapter_text = _data_path("adapters", "AGENTS.md").read_text(encoding="utf-8")
    m = re.search(
        re.escape(MARKER_BEGIN) + r"\n(.*?)\n" + re.escape(MARKER_END),
        adapter_text,
        flags=re.DOTALL,
    )
    body = m.group(1).strip() if m else adapter_text
    _merge_marker_block(agents_md, body)
    return InstallResult(
        surface="agents-md",
        mode="guarded-block",
        wired=True,
        target=str(agents_md),
        notes=f"{agents_md} 加入 marker 块；规则落到 {root/STORE_DIR_NAME}。",
    )


def disable_agents_md(global_scope: bool = False) -> InstallResult:
    root = _resolve_target_root(global_scope)
    agents_md = root / "AGENTS.md"
    changed = _strip_marker_block(agents_md)
    sw_dir = root / STORE_DIR_NAME
    if sw_dir.exists():
        shutil.rmtree(sw_dir)
    return InstallResult(
        surface="agents-md",
        mode="guarded-block",
        wired=False,
        target=str(agents_md),
        notes=("清掉 marker 块并删除 .sw/" if changed else f"未见 marker 块；已清理 {STORE_DIR_NAME}/（若存在）"),
    )


# manual-paste: 把 system prompt 写到磁盘，用户自己粘贴到 API
def enable_codex(global_scope: bool = False) -> InstallResult:
    root = _resolve_target_root(global_scope)
    _write_shared_rules(root)
    prompt_path = root / STORE_DIR_NAME / "codex-system-prompt.md"
    shutil.copy2(_data_path("adapters", "codex.md"), prompt_path)
    return InstallResult(
        surface="codex",
        mode="manual-paste",
        wired=False,  # 真正生效需要用户手动粘贴
        target=str(prompt_path),
        notes=(
            f"system prompt 已写入 {prompt_path}。\n"
            "手动步骤：把该文件 ## SYSTEM PROMPT 小节 ``` 块中的内容粘贴到 Codex API 的 system_prompt 字段。"
        ),
    )


def disable_codex(global_scope: bool = False) -> InstallResult:
    return InstallResult(
        surface="codex",
        mode="manual-paste",
        wired=False,
        target="",
        notes="manual-paste 模式不写磁盘配置；请手动从 API 的 system_prompt 里删掉粘贴内容。",
    )


SUPPORTED_SURFACES = {
    "claude-code": (enable_claude_code, disable_claude_code),
    "agents-md": (enable_agents_md, disable_agents_md),
    "codex": (enable_codex, disable_codex),
}


def enable(surface: str, global_scope: bool = False) -> InstallResult:
    if surface not in SUPPORTED_SURFACES:
        raise ValueError(
            f"未知接入面: {surface}. 支持: {', '.join(SUPPORTED_SURFACES)}"
        )
    return SUPPORTED_SURFACES[surface][0](global_scope)


def disable(surface: str, global_scope: bool = False) -> InstallResult:
    if surface not in SUPPORTED_SURFACES:
        raise ValueError(
            f"未知接入面: {surface}. 支持: {', '.join(SUPPORTED_SURFACES)}"
        )
    return SUPPORTED_SURFACES[surface][1](global_scope)


def list_surfaces() -> list[dict]:
    return [
        {"surface": "claude-code", "mode": "anchor-import", "target": "CLAUDE.md"},
        {"surface": "agents-md", "mode": "guarded-block", "target": "AGENTS.md"},
        {"surface": "codex", "mode": "manual-paste", "target": f"{STORE_DIR_NAME}/codex-system-prompt.md"},
    ]
