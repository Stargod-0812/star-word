<!-- SPDX-License-Identifier: CC-BY-4.0 -->

# star-word

**21 条中文技术写作规则，治 AI 中文输出的 AI 味。**

把规则注入到 Claude Code / Codex / Cursor / 任何支持 `AGENTS.md` 的 agent，让它生成的中文不再出现“稳稳接住”、“赋能闭环”、“综上所述”、“希望对你有帮助”这类套话。

```
before.md  →  机械规则违规 20 处（AI 味满格）
after.md   →  机械规则违规 0  处
```

试跑一下 `examples/before.md` 和 `examples/after.md`，差异一眼看清。

---

## 为什么做这个

LLM 写中文技术文字有一套可识别的 tell pattern：

- **空洞套话**：`赋能`、`闭环`、`顶层设计`、`多维度`、`全面提升`。
- **AI 过渡词**：`值得注意的是`、`综上所述`、`不难发现`、`毋庸置疑`。
- **讨好式开场/收尾**：`好问题`、`让我来为您解释`、`希望对你有帮助`。
- **铺垫式第一句**：`在当今XX领域中`、`随着XX的发展`、`众所周知`。
- **拟人化装饰**：`稳稳接住`、`默默守护`、`保驾护航`、`丝滑`。
- **无意义缓冲**：`可能`、`在某种程度上`、`一定程度上`。
- **段尾复述**：每段最后都要“综上所述”一下。

这些词句在预训练语料里高频出现，所以模型本能地复用。但技术读者看到就翻白眼。

star-word 做两件事：

1. **生成时约束**：把规则注入到 agent 的系统提示里，让模型起草时就不写这些。
2. **审阅时检测**：提供 `star-word review` 命令，对已有的 markdown / 文档做机械检测，指出违规位置。

---

## 快速开始（30 秒）

```bash
# 1. 从源码安装（v0.1.0 暂未发布到 PyPI，v0.2 会发）
pip install “git+https://github.com/Stargod-0812/star-word.git@v0.1.0#subdirectory=packages/python”

# 2. 全局启用 Claude Code（所有项目生效）
star-word enable claude-code --global

# 3. 验证（新开 Claude Code 会话）
#    问 “star-word 在生效吗？”
#    应答：”star-word v0.1.0 active: 21 条中文技术写作规则...”

# 4. 审阅一份文档
star-word review examples/before.md
```

若没装 Python，也可用 curl 方式（见下文”免安装路径”）。

---

## 21 条规则

分三组。机械规则和结构规则由 `star-word review` 自动检测；语义规则由宿主模型或人工判断。完整规则体（含每条的 BAD / GOOD 对照）见 [`RULES.md`](./RULES.md)。

### 一、禁用词典（机械检测）

| 规则 | 概要 |
| --- | --- |
| STAR-01 | 空洞价值词：`赋能`、`闭环`、`抓手`、`顶层设计`、`多维度`、`全面提升`、`打通`、`拉通`、`全链路` |
| STAR-02 | AI 过渡套话：`值得注意的是`、`综上所述`、`毋庸置疑`、`不难发现`、`众所周知`、`某种程度上` |
| STAR-03 | 铺垫式开场：`在当今`、`随着...的发展`、`首先让我们`、`在本文中` |
| STAR-04 | 讨好式表达：`好问题`、`让我来为您解释`、`希望对你有帮助`、`如有疑问请` |
| STAR-05 | 模糊缓冲（非概率语境）：`可能`、`大概`、`也许`、`某种意义上`（需语义判断） |
| STAR-06 | 滥用“进行”：`进行分析` → `分析` |
| STAR-07 | 单句内 ≥ 3 个“的” |
| STAR-08 | 拟人化装饰：`稳稳接住`、`默默守护`、`保驾护航`、`丝滑`、`一键搞定` |

### 二、结构 tell（结构检测）

| 规则 | 概要 |
| --- | --- |
| STAR-09 | 段尾总结句：`综上所述`、`总的来说` 式段落收尾 |
| STAR-10 | 机械并列：强套 `首先/其次/最后` 模板 |
| STAR-11 | 长定语前置：主语前的定语超过 20 字 |
| STAR-12 | 四字词堆砌：连续 3 个及以上四字结构并列 |
| STAR-13 | 术语前后不一致：`Model / 模型 / model` 混用 |
| STAR-14 | 中英文标点混用：中文段落里混半角 `, . ? !` |
| STAR-15 | 列表滥用：能一句话说完的拆成 2 项列表 |

### 三、语感原则（语义判断）

| 规则 | 概要 |
| --- | --- |
| STAR-16 | 第一句直接入题（删掉第一句第二句仍能独立成文？→ 首句是铺垫） |
| STAR-17 | 不说正确但无用的话 |
| STAR-18 | 有判断、有立场，不做“各有优劣”式中立综述 |
| STAR-19 | 看本质，不停在现象 |
| STAR-20 | 三句能说完的别用五句（信息密度要到） |
| STAR-21 | 用人话，不文绉绉 |

---

## 支持的工具

| 工具 | 安装模式 | 目标路径 |
| --- | --- | --- |
| Claude Code | `import-marker` | `CLAUDE.md`（项目级或 `~/.claude/CLAUDE.md` 全局级）|
| AGENTS.md 兼容（Codex CLI / Zed / Jules / Warp / Gemini CLI / VS Code） | `append-block` | `AGENTS.md` |
| Codex API | `print-only` | `.star-word/codex-system-prompt.md`（用户手动粘贴到 `system_prompt`）|

Cursor、GitHub Copilot、Aider 等待 v0.2 适配。

---

## CLI 参考

```bash
star-word --version                      # 版本
star-word list-tools                     # 支持的工具
star-word verify                         # 打印自检握手字符串

# 启用 / 禁用
star-word enable claude-code             # 当前目录
star-word enable claude-code --global    # 全局（写到 ~/.claude/CLAUDE.md）
star-word disable claude-code [--global]

# 审阅
star-word review path/to/doc.md          # 人类可读输出
star-word review path/to/doc.md --json   # 机器可读 JSON

# 所有子命令都支持 --json 供脚本调用
```

**退出码**：
- `0`：成功，零违规
- `1`：有机械/结构规则违规
- `2`：参数错误或文件不存在

---

## 免安装路径（curl 一行）

不想装 pip 包，也能用：

```bash
VER=v0.1.0
mkdir -p .star-word
curl -fsSLo .star-word/RULES.md        "https://raw.githubusercontent.com/Stargod-0812/star-word/${VER}/RULES.md"
curl -fsSLo .star-word/claude-code.md  "https://raw.githubusercontent.com/Stargod-0812/star-word/${VER}/adapters/claude-code.md"

# 然后在 CLAUDE.md（或 ~/.claude/CLAUDE.md 做全局）里加一行：
echo '@.star-word/claude-code.md' >> CLAUDE.md
```

这种路径只走规则注入，不带 `review` 检测能力。想要检测能力必须装 Python 包。

---

## 例子：before / after

`examples/before.md` 是一份典型的 AI 味满格的设计文档：铺垫式开场、`综上所述` 段尾、`稳稳接住`、`保驾护航`、`希望对你有帮助` 收尾。

跑一下：

```bash
$ star-word review examples/before.md
...
机械 + 结构规则违规总数: 20
```

`examples/after.md` 是同一主题的改写，把它们全部拿掉、改成有信息密度的工程文字。跑一下：

```bash
$ star-word review examples/after.md
...
机械 + 结构规则违规总数: 0
```

两份对读，就知道“AI 味”具体是什么、干掉之后文字会变成什么样。

---

## 卸载

```bash
# 先禁用每一个你启用过的工具
star-word disable claude-code [--global]
star-word disable agents-md
# ...

# 再卸载 pip 包
pip uninstall star-word
```

`disable` 会清理掉 `.star-word/` 目录和 `CLAUDE.md` / `AGENTS.md` 里的 marker 块（marker 之外的用户内容不动）。

---

## 开发

```bash
git clone https://github.com/Stargod-0812/star-word.git
cd star-word/packages/python
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest                     # 37 个测试，应全部通过
```

代码结构：

```
star-word/
├── RULES.md                        # 规则全文（21 条，核心 IP）
├── adapters/                       # 各工具的 adapter 文件
│   ├── claude-code.md              # Claude Code（import-marker）
│   ├── AGENTS.md                   # AGENTS.md 兼容工具（append-block）
│   └── codex.md                    # Codex API system prompt
├── packages/python/
│   ├── pyproject.toml
│   ├── star_word/
│   │   ├── cli.py                  # CLI 入口
│   │   ├── installer.py            # enable / disable 逻辑
│   │   ├── detectors.py            # 检测器（机械 + 结构）
│   │   └── data/                   # 随包分发的 RULES.md 与 adapters/
│   └── tests/                      # pytest 套件
└── examples/
    ├── before.md                   # AI 味满格的文档
    └── after.md                    # 改写后
```

---

## 局限

- **检测器 precision 高，recall 中等**：为了不误报，默认禁用词列表偏保守。比如 `链路`、`生态`、`布局` 有合法技术用法，不纳入默认检测。RULES.md 列出了完整的“可疑词”清单供人审参考。
- **语义规则不做机械检测**：STAR-16 到 STAR-21 需要模型或人工判断。`review` 会把它们标记为 `semantic_pending`。
- **只支持简体中文**：繁体中文的规则差异未处理。
- **v0.1 只支持 Python 包**：npm 包在 v0.2 计划中。

---

## 许可证

- 代码（`packages/`）：MIT
- 规则文本（`RULES.md`、`adapters/*.md`）：CC-BY-4.0

转载、改编、再分发均欢迎，保留归属即可。

---

## Roadmap

- v0.2：npm 包、Cursor / Copilot adapter、列表滥用（STAR-15）的结构检测、GitHub Action 集成
- v0.3：LLM 驱动的 second-pass review（类似 agent-style 的 `style-review`）、自动改写建议
- v1.0：完整的 21 条检测器（含语义规则基于 LLM 的判定）、跨模型 benchmark

有建议 / bug 报告：[issues](https://github.com/Stargod-0812/star-word/issues)。
