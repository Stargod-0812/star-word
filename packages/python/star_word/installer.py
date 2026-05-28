"""star-word installer: 把规则文件写到目标项目/全局，并在 CLAUDE.md / AGENTS.md 追加 import/marker。"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

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
        home = Path.home()
        # 防御：HOME=/ 或 HOME 为空会让 mkdir(parents=True) 试图建 / 失败
        if home == Path("/") or str(home) == "":
            raise ValueError(
                "HOME 环境变量不可用或指向 /。请设置正确的 HOME 再使用 --global。"
            )
        root = home / ".claude"
        root.mkdir(parents=True, exist_ok=True)
        return root
    return Path.cwd()


def _safe_copy(src: Path, dst: Path) -> None:
    """安全复制：拒绝跟随 symlink，避免 dst 是 symlink 时改写到任意位置。

    流程：
    1. 如果 dst 是 symlink，先 unlink 它（不沿 symlink 写）
    2. 用 shutil.copy2 写入新文件（dst 现在是 regular file 或不存在）
    """
    # dst.is_symlink() 不沿 symlink 解析，安全
    if dst.is_symlink():
        dst.unlink()
    # parent 也校验：如果 parent 是 symlink 指向其他位置，提示用户
    if dst.parent.is_symlink():
        raise ValueError(
            f"目标父目录 {dst.parent} 是 symlink，拒绝写入避免越权。"
            "若确认安全，请手动移除 symlink。"
        )
    shutil.copy2(src, dst)


def _assert_path_within(target: Path, root: Path) -> None:
    """v0.4.3 安全：确保 target 实际解析后仍在 root 内，防中间组件 symlink 攻击。

    场景：受害者 git clone 含恶意 `.codebuddy → ~/.ssh/` symlink 的 repo，跑
    `star-word enable codebuddy` 时 `mkdir(parents=True)` 静默穿过 symlink，把
    RULE.mdc 写到 ~/.ssh/。_safe_copy 只检查 leaf parent（mkdir 新建的真目录），
    中间 `.codebuddy` symlink 不在防御范围。

    解法：resolve(strict=False) 后 is_relative_to(root.resolve()) 校验。
    """
    try:
        target_resolved = target.resolve(strict=False)
        root_resolved = root.resolve(strict=False)
    except (OSError, RuntimeError) as e:
        raise ValueError(f"无法解析路径 {target}: {e}")
    # 兼容 Python 3.9（is_relative_to 是 3.9+，但 fallback 到字符串前缀对比）
    try:
        if not target_resolved.is_relative_to(root_resolved):
            raise ValueError(
                f"路径 {target} 实际解析到 {target_resolved}，超出预期根 {root_resolved}。"
                "中间组件可能是 symlink 指向其他位置；拒绝操作。"
            )
    except AttributeError:
        # Python 3.9 fallback
        if not str(target_resolved).startswith(str(root_resolved) + "/") and target_resolved != root_resolved:
            raise ValueError(
                f"路径 {target} 实际解析到 {target_resolved}，超出预期根 {root_resolved}。"
            )


def _write_shared_rules(root: Path) -> None:
    """把 rules.md 与 adapter 写到 <root>/.sw/。

    v0.4.3 (security R2 N2): 校验 store 实际解析后仍在 root 内——防 root 本身或其
    祖先组件是 symlink 指向 attacker dir，让 .sw/* 落地越权。
    """
    store = root / STORE_DIR_NAME
    if store.is_symlink():
        # 如果 .sw/ 本身是 symlink 指向其他目录，拒绝
        raise ValueError(
            f"{store} 是 symlink；拒绝写入。"
            "请删除 symlink 后再试。"
        )
    store.mkdir(parents=True, exist_ok=True)
    # mkdir 后才能 resolve；防 root 是 symlink 指向 attacker dir
    _assert_path_within(store, root)
    _safe_copy(_data_path("RULES.md"), store / "rules.md")
    _safe_copy(_data_path("adapters", "claude-code.md"), store / "claude.md")
    yaml_src = DATA_DIR / "rules.yaml"
    if yaml_src.exists():
        _safe_copy(yaml_src, store / "rules.yaml")


def _merge_marker_block(target_file: Path, body: str) -> bool:
    """幂等写入 marker 块。返回 True 表示有改动。

    v0.4.2 安全加固：拒绝跟随 symlink。如果 target_file 是 symlink（哪怕指向合法位置），
    一律 unlink 后重建。这防御 CLAUDE.md / AGENTS.md 被预先创建为 symlink 指向
    /etc/passwd 之类的攻击。
    """
    if target_file.is_symlink():
        # 不跟随 symlink，直接 unlink；下方走「文件不存在」分支重建
        target_file.unlink()
    if target_file.parent.is_symlink():
        raise ValueError(
            f"目标父目录 {target_file.parent} 是 symlink，拒绝写入避免越权。"
            "若确认安全，请手动移除 symlink。"
        )
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
    """删除 marker 块。用 string find 而非 regex 避免 ReDoS。

    v0.4.2 修复：达到 max_iter 上限时 raise 而非静默截断。
    之前 max_iter 上限会让大文件后半段被默默丢掉，用户毫无察觉。
    """
    if not target_file.exists():
        return False
    if target_file.is_symlink():
        # symlink target 不应该被我们处理；跟随会写到任意位置
        raise ValueError(
            f"{target_file} 是 symlink，拒绝处理。请手动检查 symlink target。"
        )
    current = target_file.read_text(encoding="utf-8")
    if MARKER_BEGIN not in current:
        return False
    # 用 find 迭代查找配对 marker，O(n) 不回溯
    out_parts: list[str] = []
    pos = 0
    max_iter = 10000  # 安全上限
    iters = 0
    while iters < max_iter:
        iters += 1
        begin_idx = current.find(MARKER_BEGIN, pos)
        if begin_idx < 0:
            out_parts.append(current[pos:])
            break
        end_idx = current.find(MARKER_END, begin_idx + len(MARKER_BEGIN))
        if end_idx < 0:
            # unpaired begin: 保留剩余原样（包括这个 unpaired begin）
            out_parts.append(current[pos:])
            break
        # 写入 begin 前的内容，跳过 begin..end 块（含可能的尾部 \n）
        out_parts.append(current[pos:begin_idx])
        next_pos = end_idx + len(MARKER_END)
        if next_pos < len(current) and current[next_pos] == "\n":
            next_pos += 1
        pos = next_pos
    else:
        # 触发 max_iter — 文件里有上万对 marker，不正常
        raise ValueError(
            f"{target_file} 中 marker 配对数超过 {max_iter}；拒绝处理避免静默丢数据。"
            "请手动清理后再试。"
        )
    updated = "".join(out_parts).rstrip() + "\n"
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
    sw_dir = root / STORE_DIR_NAME
    # v0.4.3: 即使 _strip_marker_block raise（symlink/max_iter），仍尽量清理 .sw/
    # 否则用户看到 ValueError → 退出 2 → .sw/ 残留无人清理
    strip_error: Optional[str] = None
    changed = False
    try:
        changed = _strip_marker_block(claude_md)
    except ValueError as e:
        strip_error = str(e)
    if sw_dir.exists():
        shutil.rmtree(sw_dir, ignore_errors=True)
    if strip_error:
        # 已清理 .sw/，但 marker 处理失败——重抛让用户知道要手动检查 CLAUDE.md
        raise ValueError(f"{strip_error}（已清理 .sw/，请手动检查 {claude_md}）")
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
    sw_dir = root / STORE_DIR_NAME
    strip_error: Optional[str] = None
    changed = False
    try:
        changed = _strip_marker_block(agents_md)
    except ValueError as e:
        strip_error = str(e)
    if sw_dir.exists():
        shutil.rmtree(sw_dir, ignore_errors=True)
    if strip_error:
        raise ValueError(f"{strip_error}（已清理 .sw/，请手动检查 {agents_md}）")
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
    _safe_copy(_data_path("adapters", "codex.md"), prompt_path)
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
    root = _resolve_target_root(global_scope)
    sw_dir = root / STORE_DIR_NAME
    existed = sw_dir.exists()
    if existed:
        shutil.rmtree(sw_dir)
    return InstallResult(
        surface="codex",
        mode="manual-paste",
        wired=False,
        target="",
        notes=(
            f"已清理 {STORE_DIR_NAME}/。"
            "手动步骤：从 API 的 system_prompt 里删掉粘贴内容。"
            if existed else
            "未发现 .sw/ 目录。请手动从 API 的 system_prompt 里删掉粘贴内容。"
        ),
    )


# rule-file: CodeBuddy 原生规则文件
def enable_codebuddy(global_scope: bool = False) -> InstallResult:
    """接入 CodeBuddy: 写 .codebuddy/rules/star-word/RULE.mdc.

    --global 时写到 ~/.codebuddy/rules/star-word/RULE.mdc（CodeBuddy 用户级规则路径）。
    v0.4.3 安全加固：mkdir 后校验中间组件无 symlink 越权。
    """
    if global_scope:
        intended_root = Path.home() / ".codebuddy"
    else:
        intended_root = Path.cwd() / ".codebuddy"
    rule_dir = intended_root / "rules" / "star-word"
    rule_dir.mkdir(parents=True, exist_ok=True)
    _assert_path_within(rule_dir, intended_root)
    target = rule_dir / "RULE.mdc"
    _safe_copy(_data_path("adapters", "codebuddy.md"), target)
    return InstallResult(
        surface="codebuddy",
        mode="rule-file",
        wired=True,
        target=str(target),
        notes=(
            f"CodeBuddy 规则文件已写入 {target}。\n"
            "注意：新建对话会话后规则才生效（CodeBuddy 仅在会话开始时加载规则）。"
        ),
    )


def disable_codebuddy(global_scope: bool = False) -> InstallResult:
    if global_scope:
        intended_root = Path.home() / ".codebuddy"
    else:
        intended_root = Path.cwd() / ".codebuddy"
    rule_dir = intended_root / "rules" / "star-word"
    existed = rule_dir.exists()
    if existed:
        # v0.4.3: rmtree 前校验 — 防中间组件 symlink 让 rmtree 删任意目录
        _assert_path_within(rule_dir, intended_root)
        shutil.rmtree(rule_dir)
    return InstallResult(
        surface="codebuddy",
        mode="rule-file",
        wired=False,
        target=str(rule_dir),
        notes=("已删除 star-word 规则目录。" if existed else "未发现 star-word 规则目录。"),
    )


# skill-file: WorkBuddy Skills 文件
def enable_workbuddy(global_scope: bool = False) -> InstallResult:
    """接入 WorkBuddy: 写 ~/.workbuddy/skills/star-word/SKILL.md.

    WorkBuddy 的 skills 只支持用户级，忽略 --global 参数（无项目级概念）。
    v0.4.3 安全加固：同 codebuddy，mkdir 后校验中间组件无 symlink 越权。
    """
    intended_root = Path.home() / ".workbuddy"
    skill_dir = intended_root / "skills" / "star-word"
    skill_dir.mkdir(parents=True, exist_ok=True)
    _assert_path_within(skill_dir, intended_root)
    target = skill_dir / "SKILL.md"
    _safe_copy(_data_path("adapters", "workbuddy.md"), target)
    return InstallResult(
        surface="workbuddy",
        mode="skill-file",
        wired=True,
        target=str(target),
        notes=(
            f"WorkBuddy skill 已写入 {target}。\n"
            "注意：需重启 WorkBuddy 让 skill 被识别（手动放入机制）。"
        ),
    )


def disable_workbuddy(global_scope: bool = False) -> InstallResult:
    intended_root = Path.home() / ".workbuddy"
    skill_dir = intended_root / "skills" / "star-word"
    existed = skill_dir.exists()
    if existed:
        _assert_path_within(skill_dir, intended_root)
        shutil.rmtree(skill_dir)
    return InstallResult(
        surface="workbuddy",
        mode="skill-file",
        wired=False,
        target=str(skill_dir),
        notes=("已删除 star-word skill 目录。" if existed else "未发现 star-word skill 目录。"),
    )


# mcp: stdio server, no install action needed (just run the binary)
def enable_mcp(global_scope: bool = False) -> InstallResult:
    """MCP 接入面：不需要 enable，启动 server 即可。

    v0.4.3 (architect HIGH 2): list_surfaces 列了 mcp 但 SUPPORTED_SURFACES 没有
    `enable mcp` → ValueError，文档跟 CLI 矛盾。现在返回 InstallResult 描述如何手动接。
    """
    return InstallResult(
        surface="mcp",
        mode="stdio-server",
        wired=False,  # 不写文件——MCP 客户端配置由用户自己加
        target="python -m star_word.mcp_server",
        notes=(
            "MCP 是 stdio server，不需要 enable。手动配置 client：\n"
            "Claude Desktop: ~/Library/Application Support/Claude/claude_desktop_config.json\n"
            '  "mcpServers": {"star-word": {"command": "python", "args": ["-m", "star_word.mcp_server"]}}\n'
            "Cursor / Cline 类似配置。详见 README.md MCP 段。"
        ),
    )


def disable_mcp(global_scope: bool = False) -> InstallResult:
    return InstallResult(
        surface="mcp",
        mode="stdio-server",
        wired=False,
        target="",
        notes="MCP 没有持久 enable 状态。请手动从 client 配置删除 star-word 条目。",
    )


SUPPORTED_SURFACES = {
    "claude-code": (enable_claude_code, disable_claude_code),
    "agents-md": (enable_agents_md, disable_agents_md),
    "codex": (enable_codex, disable_codex),
    "codebuddy": (enable_codebuddy, disable_codebuddy),
    "workbuddy": (enable_workbuddy, disable_workbuddy),
    "mcp": (enable_mcp, disable_mcp),
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
        {"surface": "codebuddy", "mode": "rule-file", "target": ".codebuddy/rules/star-word/RULE.mdc"},
        {"surface": "workbuddy", "mode": "skill-file", "target": "~/.workbuddy/skills/star-word/SKILL.md"},
        {"surface": "mcp", "mode": "stdio-server", "target": "python -m star_word.mcp_server"},
    ]
