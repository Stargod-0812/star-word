# star-word v0.4 示例对比 + adapter 负担测量

> ⚠ **这不是 evidence-grade bench**。
>
> 本页两件事：
> 1. **示例对比**（§1）——作者手工构造的"含 AI 味原文 vs 改写示例"，用来演示规则的检测/改写覆盖面，**不是真实 LLM 输出抽样**。
> 2. **adapter 负担测量**（§2）——adapter 在 200k 上下文中的 token 占比，可独立验证，是真数据。
>
> 真实 LLM × 多模型 × 多任务的 evidence-grade bench 还没跑（[methodology.md](methodology.md) 已定门槛 = 12 任务 × 2 模型 × 3 次）。计划见 [v0.5 roadmap](../README.md#roadmap)。
>
> **数字诚实声明**：以下分数是用 v0.4.5 detectors 实测得出，不是从老版本搬过来的。但样本本身是作者写的，存在"作者自己写一段命中规则的烂文 vs 一段不命中的好文"的循环验证嫌疑——只能证明检测器能识别作者写的样本，不能证明能识别真实 LLM 输出。

---

## 1. 示例对比（作者手工构造样本）

**3 个示例段落**（涵盖技术解释、问题排查、最佳实践三类场景）：

| 样本 | 主题 | 含 AI 味原文 | 改写示例 |
|---|---|---|---|
| `sample-01-redis-migration` | Redis 集群迁移 | 55.3 / 100 | **100.0 / 100** |
| `sample-02-api-timeout` | 接口超时排查 | 35.7 / 100 | **100.0 / 100** |
| `sample-03-db-index` | 数据库索引优化 | 39.2 / 100 | **100.0 / 100** |
| **平均** |  | **43.4** | **100.0** |

每个含 AI 味原文都触发了全部 22 条规则（每条规则一次去重计数），改写示例 0 触发。

### 复现方法

```bash
# 实测分数（v0.4.5+）
for f in bench/effectiveness/sample-0{1,2,3}-*.md; do
  echo "=== $(basename $f) ==="
  star-word review "$f" --mode strict --json | jq '.score.score'
done
```

### 样本来源（重要）

- **含 AI 味原文**：作者手工构造，每段密集塞入"赋能/闭环/综上所述/希望对你有帮助/保驾护航"等 ban list 词汇，模拟 2023 年初 ChatGPT 3.5 时期的中文输出风格。**这不是从真实 GPT-4 / Claude 4.5 / Gemini 2.5 抽样的**——真实 frontier LLM 不会单段塞 15 个 ban 词。
- **改写示例**：作者手工撰写，模拟"agent 接入 star-word 后会怎么写"，未经 LLM 自动改写。
- **v0.5 计划**：用 GPT-4o / Claude Sonnet 4.5 / Gemini 2.5 Pro 各跑 5 个真实主题 × 3 次 = 45 篇真实输出，盲评 3 个评审。methodology 见 [`bench/methodology.md`](methodology.md)。

---

## 2. Adapter 负担测量（可独立验证）

**接入 Claude Code 时的 token 开销**：

| 资源 | 字符数 | 约 token 数（中英混排估算） |
|---|---|---|
| `.sw/claude.md` (adapter) | 1,370 | ~700 |
| `.sw/rules.md` (规则正文，via @import) | 6,182 | ~3,000 |
| **合计** | **7,552** | **~3,700** |

**占 Claude Sonnet 4.5 上下文（200,000 token）的比例：1.85%**

各 surface 的 adapter 大小：

| Surface | adapter 字符 | mode | 备注 |
|---|---|---|---|
| `claude-code` | 1,370 | anchor-import | CLAUDE.md 加 1 行 `@.sw/claude.md` |
| `agents-md` | 1,147 | guarded-block | AGENTS.md 嵌入 marker 块 |
| `codex` | 1,657 | manual-paste | system_prompt 完整内容 |
| `codebuddy` | 1,281 | rule-file | `.codebuddy/rules/star-word/RULE.mdc` |
| `workbuddy` | 1,183 | skill-file | `~/.workbuddy/skills/star-word/SKILL.md` |

**结论**：adapter 设计是「索引 + handshake + 规则名 + escape hatch」，规则正文 RULES.md 只在 import 时按需加载。即使全量加载（claude-code 模式），也只占 200k 上下文 1.85%——**负担够小**。

### 设计权衡

为什么规则正文 6182 字符还要 import？因为我们要让 agent 在生成时就避开 AI 味（**生成时约束**），而不仅是审阅时检测（**审阅时检测**）。如果只走审阅模式，adapter 可以缩到 ~500 字。完整 import 是为了让模型在每次回复前都能 reference rule 正文做自我检查（forcing function）。

### 跨厂商成本

| 模型 | $/M input token | adapter 月度成本估算（每天 100 次 review） |
|---|---|---|
| Claude Sonnet 4.5 | $3 | ~$0.33/月 |
| Claude Haiku 4.5 | $0.80 | ~$0.09/月 |
| GPT-4o | $2.50 | ~$0.28/月 |
| Gemini 2.5 Pro | $1.25 | ~$0.14/月 |

按每天 100 次 review、每次 ~3,700 token：月度 token 消耗 ~111M tokens。这是「规则注入」的边际成本，远低于实际业务 prompt 的 token 量。

---

## 3. 已知缺口

- **示例样本是循环验证**。§1 的 +56.6 分提升只能说明"作者能识别自己写的样本"，不能说明"工具能识别真实 LLM 输出"。真实 evidence 见 v0.5 roadmap。
- **judge 单厂商**。`_llm.py` 硬编码 `api.anthropic.com`，跨厂商 judge 在 v0.5。家族内换 tier（被测 sonnet → judge opus）能部分缓解 self-preference，不能完全消除。
- **rewriter 没 fixture-based test**。当前改写质量靠 model 直觉，没"改写后必须能过 review"的强制循环。
- **§2 的 token 估算是中英混排经验值**，不是 tokenizer 实测。真实 token 数因 prompt 内容浮动 ±15%。
