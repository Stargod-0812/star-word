# Benchmark 方法论 — 怎么诚实评估 star-word 的效果

v0.2 的 bench 是 4 任务 × 1 次运行 × 1 个模型。这套数字看起来好看（违规降 80%），但统计上等于零。

v0.4 我们没有跑更大的 bench（需要预算和时间），但定下了一套**可被社区复现和扩展**的方法论。这份文档是给将来跑 bench 的人看的——也是给读者看的诚实标准。

## 三个问题

一个有意义的 bench 必须能回答：

1. **star-word 注入是否显著降低 AI 味？** （主问题）
2. **这种降低在多大程度上是机械层 vs 写作质感层？** （区分变化的来源）
3. **效果在不同模型/任务上是否一致？** （泛化性）

## 实验设计

### 数据集

至少 **20 个任务**，分 5 类各 4 篇：

- **debug**：故障排查复盘（容易触发铺垫和 AI 过渡词）
- **rfc**：方案设计文档（容易触发空词和长定语）
- **postmortem**：事故复盘（结构化场景，baseline 已较干净）
- **vision**：宏观愿景（最容易触发 AI 味）
- **how-to**：技术教程（容易触发讨好式收尾）

每个任务包含：
- 用户提问
- 上下文约束（字数、结构要求）
- 预期覆盖的概念点

### 模型矩阵

至少 **3 个模型**：
- Claude Sonnet 4.5 / 4.6 / 4.7（同家族不同版本）
- GPT-5 / GPT-5-mini（OpenAI）
- Gemini 2.5 Pro / Flash（Google）

不要只跑一家。不同家族的中文 AI 味分布不同——只测一家的"降幅"不能推广到另一家。

### 配置矩阵

每个任务 × 每个模型至少跑：
- baseline（无 star-word 注入）
- treatment（star-word v0.4 完整注入）
- 可选：treatment-rules-only（只词表，无 forcing function）—— 用来分离词表 vs forcing function 的贡献

### 重复次数

每个 cell 至少 **3 次独立运行**，取中位数。LLM 输出有随机性，单次结果误导。

总样本量：20 任务 × 3 模型 × 2 配置 × 3 次 = 360 次生成。

## 评估指标

### 机械层（自动）

直接跑 `star-word review --mode normal --json`：
- 违规总数
- 文档分（0-100）
- 各组分（词/式）

### 语义层（LLM-as-judge）

跑 `star-word judge --json`，让独立的 judge 模型（不是被测模型）评 6 条气组规则。

**严禁让被测模型自己 judge 自己的输出**——会有 self-preference bias。

例如：测 GPT-5，judge 用 Claude；测 Claude，judge 用 GPT-5。

### 人工层（盲评）

每个任务的 baseline / treatment 输出做成对，给 5 名以上技术写作者**盲评**：
- 哪个更想读到？（pairwise preference）
- 给两份各自的 1-10 分（可比性弱但能量化分布）

注意：
- 盲评者必须是技术从业者，不是普通用户
- 不告诉评委哪份是 baseline
- 至少 5 人，算 inter-rater agreement（Krippendorff's alpha）

## 报告格式

每次 bench 必须报：

1. 实验配置（数据集 hash、模型版本、prompt、重复次数）
2. 机械层结果表（违规数 + 文档分，按模型 × 任务类型）
3. judge 层结果表（按规则维度）
4. 人工 pairwise 偏好率（带 95% 置信区间）
5. **失败案例**（treatment 比 baseline 更差的任务）—— 这是最有信息量的部分

不要只报 headline number。给原始数据 + Jupyter notebook 让别人能验证。

## 反模式

不要做的事：

- ❌ 单次运行就发布"提升 X%"
- ❌ 自己 judge 自己（self-preference）
- ❌ 选对自己有利的 cherry-picked 任务
- ❌ 不给原始 prompt / 输出 / 评估代码
- ❌ 把 directional signal 当作 statistical significance

诚实的 bench 是 star-word 项目的可信度基础。宁可不发数字，也别发误导的数字。

## 最低门槛 vs 理想门槛

| 项目 | 最低门槛（可发布） | 理想门槛（可被引用） |
| --- | --- | --- |
| 任务数 | 12 | 50+ |
| 模型数 | 2 | 5+ |
| 重复次数 | 3 | 10 |
| 人工评估 | 3 人 | 10+ 人 |
| 报告 | 数字表 + 失败案例 | 加 notebook + raw outputs |

v0.2 的 bench 不到最低门槛。v0.4 不再发布违规降幅数字——直到能跑到最低门槛。

## 复现路径

1. clone 项目
2. 准备 ANTHROPIC_API_KEY 等
3. 跑 `bench/run.py`（待实现）
4. 输出 `bench/outputs/<timestamp>/`
5. 把结果按本文档格式整理成 `bench/v0.X-effectiveness.md`

## 谁来跑

我们没钱跑 360 次大模型生成。但社区可以：
- 任何看到这份文档的人，跑一部分（哪怕只 1 个模型 × 5 任务）
- 在 issue 里贴结果
- v0.5 我们汇总成 community bench

这是当前能做到的诚实方式。
