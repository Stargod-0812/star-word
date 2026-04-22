#!/usr/bin/env python3
"""从 rules.yaml 生成 RULES.md 与各 adapter body。

这是 v0.2 架构的核心：rules.yaml 是唯一来源，所有分发产物由此脚本生成。
避免 RULES.md / adapter / detector 在多处漂移的老问题。

用法：
    python3 scripts/build.py            # 生成所有产物
    python3 scripts/build.py --check    # 只检查是否同步，不写入

生成目标：
    - RULES.md                                              （仓库根）
    - adapters/claude-code.md                               （Claude Code adapter）
    - adapters/AGENTS.md                                    （AGENTS.md 兼容）
    - adapters/codex.md                                     （Codex API system prompt）
    - packages/python/star_word/data/rules.yaml             （随包分发的 yaml）
    - packages/python/star_word/data/RULES.md               （复制）
    - packages/python/star_word/data/adapters/*.md          （复制）
    - packages/python/star_word/generated_rules.py          （运行时规则配置）
    - packages/python/README.md                             （从根 README 同步）
"""

from __future__ import annotations

import argparse
import pprint
import re
import sys
from pathlib import Path
from typing import Any


def _parse_yaml(text: str) -> dict[str, Any]:
    try:
        import yaml  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "scripts/build.py 依赖 PyYAML。先在 packages/python 下运行 `pip install -e \".[dev]\"`，"
            "或手动安装 `PyYAML>=6.0`。"
        ) from exc
    return yaml.safe_load(text)


def _py_repr(value: Any) -> str:
    return pprint.pformat(value, width=100, sort_dicts=False)


# -------- 生成器 --------


def gen_rules_md(data: dict) -> str:
    """生成 RULES.md 全文."""
    meta = data["meta"]
    rules = data["rules"]
    groups = {g["id"]: g for g in meta["groups"]}

    out: list[str] = []
    out.append("<!-- GENERATED — 不要手改，改 rules.yaml 后跑 scripts/build.py -->\n")
    out.append("")
    out.append("# star-word 中文技术写作规则")
    out.append("")
    out.append(f"**v{meta['version']}**  |  21 条规则分三组  |  语言：简体中文")
    out.append("")
    out.append("适用于 PR 描述、设计文档、RFC、commit message、技术博客、事故复盘、error message、文档、issue 回复、代码注释。")
    out.append("不适用于小说、诗歌、营销文案、情感色彩强的长篇叙事。")
    out.append("")
    out.append("---")
    out.append("")
    out.append("## 总纲")
    out.append("")
    out.append("写中文技术文字，像一个判断力极强的工程师在聊天：**直接、有推进感、每句都不可替代**。")
    out.append("不铺垫、不寒暄、不缓冲。看到 LLM 写的「值得注意的是」，你知道那一段可以删掉大半都不影响信息量 —— 这份规则就是让 LLM 不再写出那种东西。")
    out.append("")
    out.append("三条底线：")
    out.append("")
    out.append("1. **每句要么推进认知、要么做取舍、要么给结构**。不说正确但无用的话。")
    out.append("2. **第一句话就是有信息量的内容**。铺垫、寒暄、自我介绍式开场，全部砍掉。")
    out.append("3. **有判断、有立场**。罗列不是写作，是目录。")
    out.append("")
    out.append("规则分三组：")
    out.append("")
    for g in meta["groups"]:
        detect_zh = {"mechanical": "机械检测", "structural": "结构检测", "semantic": "语义判断"}[g["detect"]]
        out.append(f"- **{g['id']}-01..NN {g['name']}**（{detect_zh}）：{g['description']}")
    out.append("")
    out.append("**例外原则**：规则是为了说清楚，不是目的本身。若严格遵守会让句子变蠢、变别扭，破例 —— 但要知道自己在破例。")
    out.append("")
    out.append("---")
    out.append("")

    # 按组输出规则
    for group in meta["groups"]:
        gid = group["id"]
        gname = group["name"]
        detect_zh = {"mechanical": "机械检测", "structural": "结构检测", "semantic": "语义判断"}[group["detect"]]
        out.append(f"## {gid} —— {gname}（{detect_zh}）")
        out.append("")
        for rule in rules:
            if rule.get("group") != gid:
                continue
            out.append(f"### {rule['id']} — {rule['title']}")
            out.append("")
            if "why" in rule:
                out.append(rule["why"].strip())
                out.append("")
            if "banned_words" in rule:
                wlist = "、".join(f"`{w}`" for w in rule["banned_words"])
                out.append(f"**默认机械检测**：{wlist}")
                out.append("")
            if "grey_zone" in rule:
                out.append("**高风险但有合法用法（不纳入默认检测）**：")
                out.append("")
                for gz in rule["grey_zone"]:
                    out.append(f"- `{gz['word']}` —— {gz['note']}")
                out.append("")
            if "banned_patterns" in rule:
                patterns = "、".join(f"`{p['word']}`" for p in rule["banned_patterns"])
                out.append(f"**段首禁用**：{patterns}")
                out.append("")
            if "grey_words" in rule:
                glist = "、".join(f"`{w}`" for w in rule["grey_words"])
                out.append(f"**歧义词（非概率语境下告警）**：{glist}")
                out.append("")
            if "pattern" in rule:
                out.append(f"**检测正则**：`{rule['pattern']}`")
                out.append("")
            if "threshold" in rule:
                out.append(f"**阈值**：{rule['threshold']}")
                out.append("")
            if "trigger_starters" in rule:
                slist = "、".join(f"`{s}`" for s in rule["trigger_starters"])
                out.append(f"**触发词（段尾出现）**：{slist}")
                out.append("")
            if "bad" in rule:
                out.append("**BAD**")
                out.append("")
                for line in rule["bad"].strip().splitlines():
                    out.append(f"> {line}")
                out.append("")
            if "good" in rule:
                out.append("**GOOD**")
                out.append("")
                for line in rule["good"].strip().splitlines():
                    out.append(f"> {line}")
                out.append("")
            out.append("---")
            out.append("")

    out.append("## 例外原则")
    out.append("")
    out.append(data["escape_hatch"].strip())
    out.append("")
    return "\n".join(out)


def gen_claude_adapter(data: dict) -> str:
    """生成 Claude Code adapter（anchor-import 模式）."""
    meta = data["meta"]
    rules = data["rules"]
    groups = {g["id"]: g for g in meta["groups"]}

    word_count = sum(1 for r in rules if r["group"] == "词")
    shape_count = sum(1 for r in rules if r["group"] == "式")
    sense_count = sum(1 for r in rules if r["group"] == "气")
    handshake = meta.get("handshake") or data.get("handshake", {})
    if not handshake:
        handshake_text = (
            f"已加载 star-word v{meta['version']}：词表 {word_count} 条，"
            f"结构 {shape_count} 条，判断 {sense_count} 条。规则正文见 .sw/rules.md。"
        )
    else:
        handshake_text = handshake["text"].format(
            version=meta["version"],
            word_count=word_count,
            shape_count=shape_count,
            sense_count=sense_count,
        ).strip()

    out: list[str] = []
    out.append("<!-- GENERATED from rules.yaml — 不要手改 -->")
    out.append("")
    out.append(f"# star-word v{meta['version']} · Claude Code 接入口")
    out.append("")
    out.append("这份规则集通过 Claude Code 的 `@path` 导入生效。`CLAUDE.md` 里有一行 `@.sw/claude.md` 就会让本文件与嵌套的 `rules.md` 一起进入会话上下文。")
    out.append("")
    out.append("## 识别口令")
    out.append("")
    out.append("当被问「star-word 在生效吗？」或「当前的中文写作规则是什么？」时，必须回答：")
    out.append("")
    out.append(f"> `{handshake_text}`")
    out.append("")
    out.append("答不出这串文字说明规则没加载成功。")
    out.append("")
    out.append("## 规则索引")
    out.append("")
    for group in meta["groups"]:
        gid = group["id"]
        gname = group["name"]
        out.append(f"**{gid} —— {gname}**")
        out.append("")
        for rule in rules:
            if rule.get("group") != gid:
                continue
            out.append(f"- {rule['id']}：{rule['title']}")
        out.append("")
    out.append("## 执行优先级")
    out.append("")
    out.append("1. 起草中文文字时即按上述规则约束用词与结构。")
    out.append("2. 机械规则（词组）违反即为硬错。")
    out.append("3. 结构规则（式组）违反需有理由，破例在注释/PR 描述中说明。")
    out.append("4. 语感规则（气组）作为判断标准，重写时优先满足。")
    out.append("")
    out.append("## 例外原则")
    out.append("")
    out.append(data["escape_hatch"].strip())
    out.append("")
    out.append("## 规则正文")
    out.append("")
    out.append("- 嵌套导入：`@.sw/rules.md`")
    out.append(f"- 固定版本上游：https://raw.githubusercontent.com/Stargod-0812/star-word/v{meta['version']}/RULES.md")
    out.append("")
    out.append("@.sw/rules.md")
    out.append("")
    return "\n".join(out)


def gen_agents_md_body(data: dict) -> str:
    """生成 AGENTS.md 的 body（将被嵌入 marker 块内）."""
    meta = data["meta"]
    rules = data["rules"]
    word_count = sum(1 for r in rules if r["group"] == "词")
    shape_count = sum(1 for r in rules if r["group"] == "式")
    sense_count = sum(1 for r in rules if r["group"] == "气")
    handshake_text = data["handshake"]["text"].format(
        version=meta["version"],
        word_count=word_count,
        shape_count=shape_count,
        sense_count=sense_count,
    ).strip()

    # 收集所有禁用词（扁平化）
    all_banned = []
    for r in rules:
        if "banned_words" in r:
            all_banned.extend(r["banned_words"])
        if "banned_patterns" in r:
            all_banned.extend(p["word"] for p in r["banned_patterns"])

    out: list[str] = []
    out.append(f"star-word v{meta['version']} —— 中文技术写作规则 21 条，本项目生效。")
    out.append("")
    out.append("## 禁用词（出现即违规）")
    out.append("")
    out.append("、".join(all_banned) + "。")
    out.append("")
    out.append("## 禁用结构")
    out.append("")
    out.append("- 「进行 + 双音节动词」（写「分析」而非「进行分析」）")
    out.append("- 单句内 3 个及以上「的」")
    out.append("- 段尾用「综上所述 / 总的来说 / 由此可见」收尾")
    out.append("- 把不真正并列的信息强套「首先/其次/最后」")
    out.append("- 主语前的定语超过 20 字")
    out.append("- 连续 3 个及以上形容词性四字结构并列")
    out.append("- 中文段落里混半角 `, . ? !`")
    out.append("- 同一文档内术语中英文反复切换")
    out.append("- 能一句话说完的拆成 2 项列表")
    out.append("")
    out.append("## 语感要求")
    out.append("")
    out.append("1. 第一句话直接入题 —— 不铺垫、不寒暄、不讲「我要讲什么」。")
    out.append("2. 每句要么推进认知、要么做取舍、要么给结构。")
    out.append("3. 有判断、有立场 —— 不做「各有优劣」式中立综述。")
    out.append("4. 看本质，不停在现象 —— 先判断问题本身对不对，再答。")
    out.append("5. 三句能说完的别用五句。")
    out.append("6. 用人话 —— 别滥用「乃/之/其/故」。")
    out.append("")
    out.append("## 识别口令")
    out.append("")
    out.append("被问「star-word 在生效吗？」时回答：")
    out.append("")
    out.append(f"> {handshake_text}")
    out.append("")
    out.append("规则正文：`.sw/rules.md`")
    return "\n".join(out)


def gen_codebuddy_adapter(data: dict) -> str:
    """生成 CodeBuddy 项目规则（rule-file 模式）.

    目标路径（安装时）：.codebuddy/rules/star-word/RULE.mdc
    格式：MDC frontmatter + 规则正文（直接复用 AGENTS.md body）.
    """
    meta = data["meta"]
    body = gen_agents_md_body(data)
    out: list[str] = []
    out.append("<!-- GENERATED from rules.yaml — 不要手改 -->")
    out.append("<!-- Target: .codebuddy/rules/star-word/RULE.mdc  (rule-file 模式) -->")
    out.append("")
    out.append("---")
    out.append("description: star-word 中文技术写作规则（21 条，治 LLM 中文 AI 味）")
    out.append("alwaysApply: true")
    out.append("enabled: true")
    out.append(f"updatedAt: 2026-04-21T00:00:00.000Z")
    out.append(f"version: {meta['version']}")
    out.append("---")
    out.append("")
    out.append(body)
    out.append("")
    return "\n".join(out)


def gen_workbuddy_adapter(data: dict) -> str:
    """生成 WorkBuddy Skill 文件（skill-file 模式）.

    目标路径（安装时）：~/.workbuddy/skills/star-word/SKILL.md
    格式：YAML frontmatter + 角色 / 执行流程 / 参考资源.
    """
    meta = data["meta"]
    rules = data["rules"]
    word_count = sum(1 for r in rules if r["group"] == "词")
    shape_count = sum(1 for r in rules if r["group"] == "式")
    sense_count = sum(1 for r in rules if r["group"] == "气")

    # 收集所有禁用词供 skill body 引用
    all_banned: list[str] = []
    for r in rules:
        if "banned_words" in r:
            all_banned.extend(r["banned_words"])
        if "banned_patterns" in r:
            all_banned.extend(p["word"] for p in r["banned_patterns"])

    out: list[str] = []
    out.append("<!-- GENERATED from rules.yaml — 不要手改 -->")
    out.append("<!-- Target: ~/.workbuddy/skills/star-word/SKILL.md  (skill-file 模式) -->")
    out.append("")
    out.append("---")
    out.append("name: star-word")
    out.append("description: 中文技术写作规则检查与约束（禁用 AI 套话、结构 tell、讨好式表达）")
    out.append(f"version: {meta['version']}")
    out.append("tags: [writing, chinese, linter, anti-ai-slop, technical-docs]")
    out.append("---")
    out.append("")
    out.append("## 角色定义")
    out.append("")
    out.append("你是一位中文技术写作审稿人。你熟悉 LLM 中文输出的 tell pattern —— 看到「赋能」、「值得注意的是」、「稳稳接住」会立刻标红；")
    out.append("看到段尾「综上所述」会立刻标红；看到铺垫式开场会立刻标红。")
    out.append("你写中文技术文字时，像一位判断力极强的工程师在聊天：直接、有推进感、每句不可替代。")
    out.append("")
    out.append("## 执行流程")
    out.append("")
    out.append("起草中文技术文字时，按以下顺序自查：")
    out.append("")
    out.append(f"1. **扫描禁用词**（共 {len(all_banned)} 个）：任一出现即改写。")
    out.append("2. **扫描禁用结构**：进行+动词 / 单句 3 个以上「的」 / 段尾「综上所述」 / 强套「首先/其次/最后」 / 主语前定语 > 20 字 / 连续 3 个四字词 / 中文里混半角标点 / 术语中英文切换 / 少于 3 项列表。")
    out.append("3. **语感自检**（6 条判断）：")
    out.append("   - 第一句直接入题（删首句第二句仍独立成文？首句多余）")
    out.append("   - 每句推进认知 / 做取舍 / 给结构 —— 否则砍")
    out.append("   - 有判断、有立场（不做「各有优劣」式综述）")
    out.append("   - 看本质、不停在现象（先 reframe 问题再答）")
    out.append("   - 三句能说完的别用五句")
    out.append("   - 用人话（别滥用「乃/之/其/故」）")
    out.append("4. **输出前再审一遍**：把全文当作他人写的 LLM 草稿去挑刺。")
    out.append("")
    out.append("## 常见失误（避坑清单）")
    out.append("")
    out.append("- 把「进行分析」写成动词「进行分析」：直接写「分析」。")
    out.append("- 每段收尾加「综上所述 / 总的来说」：段落写完就停。")
    out.append("- 用「好问题，让我来为您解释」开头：直接给答案。")
    out.append("- 铺垫式第一句「在当今XX领域」：第一句说事本身。")
    out.append("- 用「稳稳接住 / 默默守护 / 保驾护航」形容技术：写具体触发条件和处理逻辑。")
    out.append("")
    out.append("## 参考资源")
    out.append("")
    out.append(f"- 规则全文 21 条：词-01..08 / 式-01..07 / 气-01..06")
    out.append("- 项目仓库：https://github.com/Stargod-0812/star-word")
    out.append(f"- 当前版本：v{meta['version']}")
    out.append("")
    out.append("## 自检口令")
    out.append("")
    out.append("被问「star-word 在生效吗？」时回答：")
    out.append("")
    out.append(f"> 已加载 star-word v{meta['version']}：词表 {word_count} 条，结构 {shape_count} 条，判断 {sense_count} 条。")
    out.append("")
    return "\n".join(out)


def gen_codex_adapter(data: dict) -> str:
    """生成 Codex API system prompt（manual-paste 模式）."""
    meta = data["meta"]
    agents_body = gen_agents_md_body(data)
    out: list[str] = []
    out.append("<!-- GENERATED from rules.yaml — 不要手改 -->")
    out.append("")
    out.append(f"# star-word v{meta['version']} · Codex API 系统提示")
    out.append("")
    out.append("把下方 SYSTEM PROMPT 小节的内容粘贴进你的 Codex API 调用的 `system_prompt` 字段。")
    out.append("")
    out.append("## SYSTEM PROMPT")
    out.append("")
    out.append("```")
    out.append(agents_body)
    out.append("")
    out.append("例外原则：若严格执行规则反而让句子变别扭，破例 —— 但在注释或 commit 说明中指出理由。")
    out.append("```")
    out.append("")
    out.append("## 用法（Python 示例）")
    out.append("")
    out.append("```python")
    out.append("from openai import OpenAI")
    out.append("")
    out.append("client = OpenAI(api_key='...')")
    out.append("")
    out.append('with open(".sw/codex-system-prompt.md") as f:')
    out.append("    system_prompt = f.read()")
    out.append("")
    out.append("resp = client.chat.completions.create(")
    out.append("    model='gpt-5',")
    out.append("    messages=[")
    out.append("        {'role': 'system', 'content': system_prompt},")
    out.append("        {'role': 'user', 'content': '帮我写一份分布式锁的 RFC。'},")
    out.append("    ],")
    out.append(")")
    out.append("```")
    out.append("")
    out.append(f"SYSTEM PROMPT 约 {len(agents_body)} 字符。若成本敏感，只粘「禁用词」加「语感要求」前三条即可。")
    out.append("")
    return "\n".join(out)


def gen_agents_md_full(data: dict) -> str:
    """生成 AGENTS.md adapter 全文（含 marker wrap）."""
    body = gen_agents_md_body(data)
    out: list[str] = []
    out.append("<!-- GENERATED from rules.yaml — 不要手改 -->")
    out.append("")
    out.append("# star-word · AGENTS.md 注入块")
    out.append("")
    out.append("<!-- sw-managed-begin -->")
    out.append(body)
    out.append("<!-- sw-managed-end -->")
    out.append("")
    return "\n".join(out)


def gen_python_rules_module(data: dict) -> str:
    """生成运行时使用的 Python 规则配置模块."""
    meta = data["meta"]
    rules = data["rules"]
    group_counts = {
        group["id"]: sum(1 for rule in rules if rule["group"] == group["id"])
        for group in meta["groups"]
    }
    all_rule_ids = [rule["id"] for rule in rules]
    rule_titles = {rule["id"]: rule["title"] for rule in rules}
    semantic_rules = [
        (rule["id"], rule["title"])
        for rule in rules
        if rule.get("detect_status") == "semantic"
    ]
    banned_words = {
        rule["id"]: rule["banned_words"]
        for rule in rules
        if "banned_words" in rule
    }
    banned_patterns = {
        rule["id"]: [item["word"] for item in rule["banned_patterns"]]
        for rule in rules
        if "banned_patterns" in rule
    }
    regex_patterns = {
        rule["id"]: rule["pattern"]
        for rule in rules
        if "pattern" in rule
    }
    thresholds = {
        rule["id"]: rule["threshold"]
        for rule in rules
        if "threshold" in rule
    }
    trigger_starters = {
        rule["id"]: rule["trigger_starters"]
        for rule in rules
        if "trigger_starters" in rule
    }

    out: list[str] = []
    out.append('"""GENERATED from rules.yaml — 不要手改。"""')
    out.append("")
    out.append("from __future__ import annotations")
    out.append("")
    out.append(f"VERSION = {_py_repr(meta['version'])}")
    out.append(f"RULE_GROUP_COUNTS = {_py_repr(group_counts)}")
    out.append(f"ALL_RULE_IDS = {_py_repr(all_rule_ids)}")
    out.append(f"RULE_TITLES = {_py_repr(rule_titles)}")
    out.append(f"SEMANTIC_RULES = {_py_repr(semantic_rules)}")
    out.append(f"BANNED_WORDS = {_py_repr(banned_words)}")
    out.append(f"BANNED_PATTERNS = {_py_repr(banned_patterns)}")
    out.append(f"REGEX_PATTERNS = {_py_repr(regex_patterns)}")
    out.append(f"THRESHOLDS = {_py_repr(thresholds)}")
    out.append(f"TRIGGER_STARTERS = {_py_repr(trigger_starters)}")
    out.append("")
    return "\n".join(out)


# -------- 主入口 --------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="star-word 规则产物生成器")
    ap.add_argument("--check", action="store_true", help="检查是否同步，不写入")
    args = ap.parse_args(argv)

    repo_root = Path(__file__).resolve().parent.parent
    yaml_path = repo_root / "rules.yaml"
    if not yaml_path.exists():
        print(f"错误：缺 {yaml_path}", file=sys.stderr)
        return 2

    text = yaml_path.read_text(encoding="utf-8")
    try:
        data = _parse_yaml(text)
    except RuntimeError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2

    # 生成所有产物
    generated_rules = gen_python_rules_module(data)
    generated = {
        repo_root / "RULES.md": gen_rules_md(data),
        repo_root / "adapters" / "claude-code.md": gen_claude_adapter(data),
        repo_root / "adapters" / "AGENTS.md": gen_agents_md_full(data),
        repo_root / "adapters" / "codex.md": gen_codex_adapter(data),
        repo_root / "adapters" / "codebuddy.md": gen_codebuddy_adapter(data),
        repo_root / "adapters" / "workbuddy.md": gen_workbuddy_adapter(data),
        repo_root / "packages" / "python" / "star_word" / "generated_rules.py": generated_rules,
    }

    # 镜像到包数据目录
    data_dir = repo_root / "packages" / "python" / "star_word" / "data"
    pkg_mirror = {
        data_dir / "rules.yaml": text,
        data_dir / "RULES.md": gen_rules_md(data),
        data_dir / "adapters" / "claude-code.md": gen_claude_adapter(data),
        data_dir / "adapters" / "AGENTS.md": gen_agents_md_full(data),
        data_dir / "adapters" / "codex.md": gen_codex_adapter(data),
        data_dir / "adapters" / "codebuddy.md": gen_codebuddy_adapter(data),
        data_dir / "adapters" / "workbuddy.md": gen_workbuddy_adapter(data),
    }
    generated.update(pkg_mirror)

    # 同步 README（不走 codegen，仅镜像）
    root_readme = repo_root / "README.md"
    if root_readme.exists():
        generated[repo_root / "packages" / "python" / "README.md"] = root_readme.read_text(encoding="utf-8")

    drift = []
    for path, content in generated.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            current = path.read_text(encoding="utf-8")
            if current == content:
                continue
            drift.append(path)
        if not args.check:
            path.write_text(content, encoding="utf-8")

    if args.check:
        if drift:
            print("✗ 以下文件与 rules.yaml 不同步：", file=sys.stderr)
            for p in drift:
                print(f"  {p.relative_to(repo_root)}", file=sys.stderr)
            print("\n跑 `python3 scripts/build.py` 重新生成。", file=sys.stderr)
            return 1
        print("✓ 所有生成产物与 rules.yaml 同步")
        return 0

    print(f"✓ 生成 {len(generated)} 个文件（含镜像）")
    for path in generated:
        try:
            rel = path.relative_to(repo_root)
        except ValueError:
            rel = path
        print(f"  {rel}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
