# star-word

**21 条中文技术写作规则，治 LLM 中文输出的 AI 味。**

把规则注入到 Claude Code / Codex / 任何支持 `AGENTS.md` 的 agent，让它生成的中文不再出现「稳稳接住」、「赋能闭环」、「综上所述」、「希望对你有帮助」这类套话。

```
before.md  →  机械规则违规 20 处（AI 味满格）
after.md   →  机械规则违规 0  处
```

---

## 架构一图

```
rules.yaml                          （唯一来源）
    │
    ▼ scripts/build.py
    │
    ├─► RULES.md                    （规则全文，21 条）
    ├─► adapters/claude-code.md     （Claude Code 接入口）
    ├─► adapters/AGENTS.md          （AGENTS.md 兼容）
    ├─► adapters/codex.md           （Codex API 系统提示）
    └─► packages/python/star_word/data/*  （pip 包内分发镜像）
```

改规则只需改 `rules.yaml`，跑一次 `scripts/build.py` 全部产物自动重生成；CI 用 `scripts/build.py --check` 拒绝漂移。

---

## 为什么做这个

LLM 写中文技术文字有一套可识别的 tell pattern：

- **空洞套话**：`赋能`、`闭环`、`顶层设计`、`多维度`、`全面提升`
- **AI 过渡词**：`值得注意的是`、`综上所述`、`不难发现`、`毋庸置疑`
- **讨好式开场/收尾**：`好问题`、`让我来为您解释`、`希望对你有帮助`
- **铺垫式第一句**：`在当今XX领域中`、`随着XX的发展`、`众所周知`
- **拟人化装饰**：`稳稳接住`、`默默守护`、`保驾护航`、`丝滑`
- **无意义缓冲**：`可能`、`在某种程度上`、`一定程度上`
- **段尾复述**：每段最后都要「综上所述」一下

这些词句在预训练语料里高频出现，模型本能复用。技术读者看到就翻白眼。

star-word 做两件事：

1. **生成时约束**：把规则注入 agent 系统提示，让模型起草时就不写这些。
2. **审阅时检测**：提供 `star-word review` 命令，对已有 markdown/文档做机械检测，指出违规位置。

---

## 快速开始

```bash
# 1. 从源码安装（暂未发布到 PyPI，v0.3 计划发）
pip install "git+https://github.com/Stargod-0812/star-word.git@v0.2.1#subdirectory=packages/python"

# 2. 全局接入 Claude Code（所有项目生效）
star-word enable claude-code --global

# 3. 验证（新开 Claude Code 会话）
#    问 "star-word 在生效吗？"
#    应答："已加载 star-word v0.2.1：词表 8 条，结构 7 条，判断 6 条..."

# 4. 审阅一份文档
star-word review examples/before.md
```

没装 Python 也能用（见下文「免安装路径」）。

---

## 21 条规则

分三组。机械规则和结构规则由 `star-word review` 自动检测；语义规则由宿主模型或人工判断。完整规则体见 [`RULES.md`](./RULES.md)。

### 词 —— 禁用词典（机械检测）

| 规则 | 概要 |
| --- | --- |
| 词-01 | 空洞价值词：`赋能`、`闭环`、`抓手`、`顶层设计`、`多维度`、`全面提升`、`打通`、`拉通`、`全链路` |
| 词-02 | AI 过渡套话：`值得注意的是`、`综上所述`、`毋庸置疑`、`不难发现`、`众所周知`、`某种程度上` |
| 词-03 | 铺垫式开场：`在当今`、`随着...的发展`、`首先让我们`、`在本文中` |
| 词-04 | 讨好式表达：`好问题`、`让我来为您解释`、`希望对你有帮助`、`如有疑问请` |
| 词-05 | 模糊缓冲（非概率语境）：`可能`、`大概`、`也许`、`某种意义上`（语义判断） |
| 词-06 | 滥用「进行」：`进行分析` → `分析` |
| 词-07 | 单句内 ≥ 3 个「的」 |
| 词-08 | 拟人化装饰：`稳稳接住`、`默默守护`、`保驾护航`、`丝滑`、`一键搞定` |

### 式 —— 结构 tell（结构检测）

| 规则 | 概要 |
| --- | --- |
| 式-01 | 段尾总结句：`综上所述`、`总的来说` 式段落收尾 |
| 式-02 | 机械并列：强套 `首先/其次/最后` 模板（语义判断） |
| 式-03 | 长定语前置：主语前的定语超过 20 字（语义判断） |
| 式-04 | 四字词堆砌：连续 4 个及以上四字结构并列 |
| 式-05 | 术语前后不一致：`Model / 模型 / model` 混用（语义判断） |
| 式-06 | 中英文标点混用：中文段落里混半角 `, . ? !` |
| 式-07 | 列表滥用：能一句话说完的拆成 2 项列表（语义判断） |

### 气 —— 语感原则（语义判断）

| 规则 | 概要 |
| --- | --- |
| 气-01 | 第一句直接入题（删掉第一句第二句仍能独立成文？→ 首句是铺垫） |
| 气-02 | 不说正确但无用的话 |
| 气-03 | 有判断、有立场，不做「各有优劣」式中立综述 |
| 气-04 | 看本质，不停在现象 |
| 气-05 | 三句能说完的别用五句（信息密度要到） |
| 气-06 | 用人话，不文绉绉 |

---

## 支持的接入面

| 接入面 | 模式 | 目标文件 |
| --- | --- | --- |
| Claude Code | `anchor-import` | `CLAUDE.md`（项目级或 `~/.claude/CLAUDE.md` 全局级）|
| AGENTS.md 兼容（Codex CLI / Zed / Jules / Warp / Gemini CLI / VS Code） | `guarded-block` | `AGENTS.md` |
| Codex API | `manual-paste` | `.sw/codex-system-prompt.md`（手动粘贴到 `system_prompt`）|
| CodeBuddy（腾讯云代码助手） | `rule-file` | `.codebuddy/rules/star-word/RULE.mdc`（项目级）或 `~/.codebuddy/rules/star-word/RULE.mdc`（`--global`） |
| WorkBuddy（腾讯 AI 桌面智能体） | `skill-file` | `~/.workbuddy/skills/star-word/SKILL.md`（始终用户级） |

Cursor、GitHub Copilot、Aider 等待 v0.3 适配。

### 针对不同 surface 的特化

- **Claude Code / AGENTS.md**：`@path` 嵌套导入 + marker 块，让规则在每次会话启动即进入上下文。
- **CodeBuddy**：用其原生 `.codebuddy/rules/` 机制 + `alwaysApply: true` + `enabled: true` frontmatter，与它的规则加载协议对齐。新建会话才生效（CodeBuddy 特性）。
- **WorkBuddy**：作为 `SKILL.md` 注入，带角色定义 / 执行流程 / 避坑清单结构，匹配 WorkBuddy 的 Skill 语义。重启 WorkBuddy 才被识别。

---

## CLI 参考

```bash
star-word --version                      # 版本
star-word surfaces                       # 列出接入面
star-word handshake                      # 打印自检口令
star-word handshake --json               # 机器可读自检信息

# 接线 / 拆除
star-word enable claude-code             # 当前目录
star-word enable claude-code --global    # 全局（写到 ~/.claude/CLAUDE.md）
star-word disable claude-code [--global]

# 审阅
star-word review path/to/doc.md          # 人类可读输出
star-word review path/to/doc.md --json   # 机器可读 JSON

# enable / disable / surfaces / review / handshake 都支持 --json
```

**退出码**：
- `0`：成功，零违规
- `1`：有机械/结构规则违规
- `2`：参数错误或文件不存在

---

## 免安装路径（curl 一行）

不想装 pip 包也行：

```bash
VER=v0.2.1
mkdir -p .sw
curl -fsSLo .sw/rules.md       "https://raw.githubusercontent.com/Stargod-0812/star-word/${VER}/RULES.md"
curl -fsSLo .sw/claude.md      "https://raw.githubusercontent.com/Stargod-0812/star-word/${VER}/adapters/claude-code.md"

# 然后在 CLAUDE.md（或 ~/.claude/CLAUDE.md 做全局）里加一行：
echo '@.sw/claude.md' >> CLAUDE.md
```

这种路径只走规则注入，不带 `review` 检测能力。要检测能力装 Python 包。

---

## 例子：before / after

`examples/before.md` 是典型 AI 味满格的设计文档：铺垫式开场、`综上所述` 段尾、`稳稳接住`、`保驾护航`、`希望对你有帮助` 收尾。

```bash
$ star-word review examples/before.md
...
机械 + 结构规则违规总数: 20
```

`examples/after.md` 是同一主题的改写：

```bash
$ star-word review examples/after.md
...
机械 + 结构规则违规总数: 0
```

两份对读，就知道「AI 味」具体是什么、干掉之后文字会变成什么样。

---

## 卸载

```bash
# 拆掉每一个接入过的面
star-word disable claude-code [--global]
star-word disable agents-md
# ...

# 卸 pip 包
pip uninstall star-word
```

`disable` 会清理对应的 marker 块或规则文件。只有当没有其他接入面继续使用共享 `.sw/` 时，才会删除该目录。marker 之外的用户内容不动。

---

## 有效性评测

`bench/run.py` 对 codex CLI 驱动的 GPT-5 做 A/B：baseline（无 star-word）vs treatment（注入 star-word Codex 系统提示）。v0.2.1 结果：

| 任务 | baseline 违规 | treatment 违规 |
| --- | ---: | ---: |
| rfc（Redis 迁移方案） | 1 | 0 |
| debug（Full GC 排查） | 1 | 0 |
| postmortem（事故复盘） | 0 | 0 |
| vision（AI 平台愿景） | 3 | 1 |
| **合计** | **5** | **1**（**-80%**） |

`vision` 任务定性对比尤其值得看：baseline 写出「下一代智能生产力的基础设施」，treatment 改写成立场锋利、痛点具体的版本。完整对比见 [`bench/v0.2-effectiveness.md`](bench/v0.2-effectiveness.md)。

复现：`python3 bench/run.py`（需安装 codex CLI + 有 OpenAI 账号）。

诚实说明：违规数只是 directional signal —— 真正的写作质感改进（立场、密度、具体性）当前的机械规则捕捉不到，需要 v0.3 加上 LLM-as-judge 才能量化。

---

## 开发

```bash
git clone https://github.com/Stargod-0812/star-word.git
cd star-word/packages/python
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest                          # 测试应全通过

# 改规则：
cd ~/code/star-word
# 编辑 rules.yaml ...
python3 scripts/build.py        # 重新生成所有产物
python3 scripts/build.py --check   # CI 用：断言产物与 yaml 同步
```

### 代码结构

```
star-word/
├── rules.yaml                      # 唯一来源（21 条规则）
├── scripts/build.py                # rules.yaml → 所有产物
├── RULES.md                        # 生成：规则全文
├── adapters/                       # 生成：各 surface 的接入口
│   ├── claude-code.md              # Claude Code（anchor-import）
│   ├── AGENTS.md                   # AGENTS.md 兼容（guarded-block）
│   └── codex.md                    # Codex API（manual-paste）
├── packages/python/
│   ├── pyproject.toml
│   ├── star_word/
│   │   ├── cli.py                  # CLI 入口
│   │   ├── installer.py            # enable / disable 逻辑
│   │   ├── detectors.py            # 检测器（机械 + 结构）
│   │   └── data/                   # 随包分发的 rules.yaml + RULES.md + adapters/
│   └── tests/                      # pytest 套件（44 个）
└── examples/
    ├── before.md                   # AI 味满格的文档
    └── after.md                    # 改写后
```

---

## 局限

- **检测器 precision 高，recall 中等**：默认禁用词列表保守。`链路`、`生态`、`布局` 有合法技术用法，不纳入默认检测。rules.yaml 的 grey_zone 字段列了完整「可疑词」供人审。
- **语义规则不做机械检测**：气-01 到 气-06、式-02/03/05/07、词-05 需要模型或人工判断。`review` 会把它们标记为 `sense-pending`。
- **只支持简体中文**。
- **v0.2 只有 Python 包**。npm 包、MCP server、LLM-as-judge 在 v0.3 计划中。

---

## Roadmap

- **v0.3**：MCP server（`get_rules` / `review_text` 两个 tool，让任何 MCP 客户端直接接入）、LLM-as-judge runtime 为语义规则落地、Cursor / Copilot adapter、cross-model benchmark
- **v0.4**：adaptive learning（记录用户接受/拒绝的改写，推导团队偏好）、自动改写建议、npm 包
- **v1.0**：汉语技术写作句势图谱 —— 规则不是词表，是 typed edge graph，从「套话」到「人话」的分类转换关系

---

## 许可证

- 代码（`packages/`、`scripts/`）：MIT
- 规则文本（`RULES.md`、`adapters/*.md`、`rules.yaml`）：CC-BY-4.0

转载、改编、再分发均欢迎，保留归属即可。见 [`NOTICE.md`](./NOTICE.md) 与 [`LICENSE`](./LICENSE)。

有建议 / bug：[issues](https://github.com/Stargod-0812/star-word/issues)。
