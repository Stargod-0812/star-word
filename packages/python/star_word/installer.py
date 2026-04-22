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
    status_label: str = ""


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


def _reject_global(surface: str) -> None:
    raise ValueError(f"{surface} 只支持项目级接入，不支持 --global")


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


def _has_marker_block(target_file: Path) -> bool:
    if not target_file.is_file():
        return False
    current = target_file.read_text(encoding="utf-8")
    return MARKER_BEGIN in current and MARKER_END in current


def _extract_fenced_system_prompt(adapter_text: str) -> str:
    match = re.search(r"^## SYSTEM PROMPT\s+```(?:\w+)?\n(.*?)\n```", adapter_text, flags=re.DOTALL | re.MULTILINE)
    if not match:
        raise ValueError("codex adapter 缺少 SYSTEM PROMPT fenced block")
    return match.group(1).rstrip() + "\n"


def _shared_store_in_use(root: Path) -> bool:
    store = root / STORE_DIR_NAME
    if not store.exists():
        return False
    return any(
        (
            _has_marker_block(root / "CLAUDE.md"),
            _has_marker_block(root / "AGENTS.md"),
            (store / "codex-system-prompt.md").exists(),
        )
    )


def _cleanup_shared_store(root: Path) -> bool:
    store = root / STORE_DIR_NAME
    if not store.exists() or _shared_store_in_use(root):
        return False
    shutil.rmtree(store)
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
        status_label="已接线",
    )


def disable_claude_code(global_scope: bool = False) -> InstallResult:
    root = _resolve_target_root(global_scope)
    claude_md = root / "CLAUDE.md"
    changed = _strip_marker_block(claude_md)
    cleaned = _cleanup_shared_store(root)
    if changed and cleaned:
        notes = "清掉 marker 块并清理未再使用的 .sw/"
    elif changed:
        notes = "清掉 marker 块；保留 .sw/ 供其他接入面继续使用。"
    elif cleaned:
        notes = f"未见 marker 块；已清理未再使用的 {STORE_DIR_NAME}/"
    else:
        notes = "未见 marker 块；保留现有共享文件。"
    return InstallResult(
        surface="claude-code",
        mode="anchor-import",
        wired=False,
        target=str(claude_md),
        notes=notes,
        status_label="未接线 / 已拆除",
    )


# guarded-block: 在 AGENTS.md 中嵌入受保护的规则块
def enable_agents_md(global_scope: bool = False) -> InstallResult:
    if global_scope:
        _reject_global("agents-md")
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
        status_label="已接线",
    )


def disable_agents_md(global_scope: bool = False) -> InstallResult:
    if global_scope:
        _reject_global("agents-md")
    root = _resolve_target_root(global_scope)
    agents_md = root / "AGENTS.md"
    changed = _strip_marker_block(agents_md)
    cleaned = _cleanup_shared_store(root)
    if changed and cleaned:
        notes = "清掉 marker 块并清理未再使用的 .sw/"
    elif changed:
        notes = "清掉 marker 块；保留 .sw/ 供其他接入面继续使用。"
    elif cleaned:
        notes = f"未见 marker 块；已清理未再使用的 {STORE_DIR_NAME}/"
    else:
        notes = "未见 marker 块；保留现有共享文件。"
    return InstallResult(
        surface="agents-md",
        mode="guarded-block",
        wired=False,
        target=str(agents_md),
        notes=notes,
        status_label="未接线 / 已拆除",
    )


# manual-paste: 把 system prompt 写到磁盘，用户自己粘贴到 API
def enable_codex(global_scope: bool = False) -> InstallResult:
    if global_scope:
        _reject_global("codex")
    root = _resolve_target_root(global_scope)
    _write_shared_rules(root)
    prompt_path = root / STORE_DIR_NAME / "codex-system-prompt.md"
    adapter_text = _data_path("adapters", "codex.md").read_text(encoding="utf-8")
    prompt_path.write_text(_extract_fenced_system_prompt(adapter_text), encoding="utf-8")
    return InstallResult(
        surface="codex",
        mode="manual-paste",
        wired=False,  # 真正生效需要用户手动粘贴
        target=str(prompt_path),
        notes=(
            f"system prompt 正文已写入 {prompt_path}。\n"
            "手动步骤：把该文件内容粘贴到 Codex API 的 system_prompt 字段。"
        ),
        status_label="已写入，待手动接线",
    )


def disable_codex(global_scope: bool = False) -> InstallResult:
    if global_scope:
        _reject_global("codex")
    root = _resolve_target_root(global_scope)
    prompt_path = root / STORE_DIR_NAME / "codex-system-prompt.md"
    existed = prompt_path.exists()
    if existed:
        prompt_path.unlink()
    cleaned = _cleanup_shared_store(root)
    if existed and cleaned:
        notes = "已删除 codex system prompt，并清理未再使用的 .sw/。"
    elif existed:
        notes = "已删除 codex system prompt；保留 .sw/ 供其他接入面继续使用。"
    elif cleaned:
        notes = f"未发现 codex system prompt；已清理未再使用的 {STORE_DIR_NAME}/。"
    else:
        notes = "未发现 codex system prompt。"
    return InstallResult(
        surface="codex",
        mode="manual-paste",
        wired=False,
        target=str(prompt_path),
        notes=notes + " 请手动从 API 的 system_prompt 里删掉已粘贴内容。",
        status_label="未接线 / 已拆除",
    )


# rule-file: CodeBuddy 原生规则文件
def enable_codebuddy(global_scope: bool = False) -> InstallResult:
    """接入 CodeBuddy: 写 .codebuddy/rules/star-word/RULE.mdc.

    --global 时写到 ~/.codebuddy/rules/star-word/RULE.mdc（CodeBuddy 用户级规则路径）。
    """
    if global_scope:
        rule_dir = Path.home() / ".codebuddy" / "rules" / "star-word"
    else:
        rule_dir = Path.cwd() / ".codebuddy" / "rules" / "star-word"
    rule_dir.mkdir(parents=True, exist_ok=True)
    target = rule_dir / "RULE.mdc"
    shutil.copy2(_data_path("adapters", "codebuddy.md"), target)
    return InstallResult(
        surface="codebuddy",
        mode="rule-file",
        wired=True,
        target=str(target),
        notes=(
            f"CodeBuddy 规则文件已写入 {target}。\n"
            "注意：新建对话会话后规则才生效（CodeBuddy 仅在会话开始时加载规则）。"
        ),
        status_label="已接线",
    )


def disable_codebuddy(global_scope: bool = False) -> InstallResult:
    if global_scope:
        rule_dir = Path.home() / ".codebuddy" / "rules" / "star-word"
    else:
        rule_dir = Path.cwd() / ".codebuddy" / "rules" / "star-word"
    existed = rule_dir.exists()
    if existed:
        shutil.rmtree(rule_dir)
    return InstallResult(
        surface="codebuddy",
        mode="rule-file",
        wired=False,
        target=str(rule_dir),
        notes=("已删除 star-word 规则目录。" if existed else "未发现 star-word 规则目录。"),
        status_label="未接线 / 已拆除",
    )


# skill-file: WorkBuddy Skills 文件
def enable_workbuddy(global_scope: bool = False) -> InstallResult:
    """接入 WorkBuddy: 写 ~/.workbuddy/skills/star-word/SKILL.md.

    WorkBuddy 的 skills 只支持用户级，忽略 --global 参数（无项目级概念）。
    """
    skill_dir = Path.home() / ".workbuddy" / "skills" / "star-word"
    skill_dir.mkdir(parents=True, exist_ok=True)
    target = skill_dir / "SKILL.md"
    shutil.copy2(_data_path("adapters", "workbuddy.md"), target)
    return InstallResult(
        surface="workbuddy",
        mode="skill-file",
        wired=True,
        target=str(target),
        notes=(
            f"WorkBuddy skill 已写入 {target}。\n"
            "注意：需重启 WorkBuddy 让 skill 被识别（手动放入机制）。"
        ),
        status_label="已接线",
    )


def disable_workbuddy(global_scope: bool = False) -> InstallResult:
    skill_dir = Path.home() / ".workbuddy" / "skills" / "star-word"
    existed = skill_dir.exists()
    if existed:
        shutil.rmtree(skill_dir)
    return InstallResult(
        surface="workbuddy",
        mode="skill-file",
        wired=False,
        target=str(skill_dir),
        notes=("已删除 star-word skill 目录。" if existed else "未发现 star-word skill 目录。"),
        status_label="未接线 / 已拆除",
    )


SUPPORTED_SURFACES = {
    "claude-code": (enable_claude_code, disable_claude_code),
    "agents-md": (enable_agents_md, disable_agents_md),
    "codex": (enable_codex, disable_codex),
    "codebuddy": (enable_codebuddy, disable_codebuddy),
    "workbuddy": (enable_workbuddy, disable_workbuddy),
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
        {
            "surface": "claude-code",
            "mode": "anchor-import",
            "target": "CLAUDE.md 或 ~/.claude/CLAUDE.md",
            "scope": "project|global",
        },
        {
            "surface": "agents-md",
            "mode": "guarded-block",
            "target": "AGENTS.md",
            "scope": "project",
        },
        {
            "surface": "codex",
            "mode": "manual-paste",
            "target": f"{STORE_DIR_NAME}/codex-system-prompt.md",
            "scope": "project",
        },
        {
            "surface": "codebuddy",
            "mode": "rule-file",
            "target": ".codebuddy/rules/star-word/RULE.mdc 或 ~/.codebuddy/rules/star-word/RULE.mdc",
            "scope": "project|global",
        },
        {
            "surface": "workbuddy",
            "mode": "skill-file",
            "target": "~/.workbuddy/skills/star-word/SKILL.md",
            "scope": "user",
        },
    ]
