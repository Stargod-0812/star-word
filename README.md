# star-word

**22 条中文技术写作规则 + LLM-as-judge + MCP server。治 LLM 中文输出的 AI 味，量化打分到 0-100。**

四件事：

1. **生成时约束** — 规则注入 agent 系统提示，让 Claude / GPT / Gemini 起草时就避开 AI 味
2. **审阅时检测** — `star-word review` 给文档打 0-100 分，11 条机械/结构规则零 API 成本
3. **LLM-as-judge** — `star-word judge` 让模型评 10 条语义规则（气组 + 部分式组），返回 0-10 分 + reasoning
4. **MCP server** — `star-word mcp` 一键接入 Claude Desktop / Cursor / Cline，把 review/judge/rewrite 变成 tool

```
before.md  →  评分 39.8/100  F 级  机械违规 20+ 处
after.md   →  评分 100.0/100  A 级  零违规
corpus/*   →  评分 100.0/100  A 级（5 篇正向语料，strict 模式过）
```

---

## 60 秒安装

```bash
pip install "git+https://github.com/Stargod-0812/star-word.git@v0.4.0#subdirectory=packages/python"

# 接入 Claude Code（写到全局 CLAUDE.md）
star-word enable claude-code --global

# 审阅一份文档
star-word review path/to/doc.md --mode strict

# 让 LLM 评估语义规则（需 ANTHROPIC_API_KEY）
star-word judge path/to/doc.md

# 启动 MCP server（接入 Claude Desktop / Cursor）
star-word mcp
```

---

## 为什么不只是个词表

LLM 中文 AI 味的 tell：空洞套话（赋能/闭环/全面提升）、AI 过渡词（值得注意的是/综上所述）、讨好开场收尾（好问题/希望对你有帮助）、铺垫第一句（在当今/随着）、拟人装饰（稳稳接住/保驾护航/丝滑）、段尾复述。这些在预训练语料里高频，模型本能复用。

但禁词只是表层。真正区分人写和 AI 写的是：信息选择、节奏变化、具体性、判断力。

star-word v0.4 的三层防线：

| 层 | 机制 | 覆盖 |
| --- | --- | --- |
| **生成时**（adapter 注入） | 词表 + 6 条 forcing function 自检 | 所有 22 条规则 |
| **审阅时机械层** | 11 条规则的子串/正则/统计检测 | 词组 7 + 式组 4 |
| **审阅时语义层** | LLM-as-judge 打 0-10 分 | 气组 6 + 式组 3 + 词-05 |

不依赖 LLM 也能跑机械层；想要语义评分给个 API key 就行。

---

## 22 条规则

完整规则体见 [`RULES.md`](./RULES.md)。

### 词 —— 禁用词典（机械检测）

| 规则 | 概要 |
| --- | --- |
| 词-01 | 空洞价值词：`赋能`、`闭环`、`抓手`、`顶层设计`、`多维度`、`全面提升`（+ grey_zone 上下文感知词如 `打通`、`链路`） |
| 词-02 | AI 过渡套话：`值得注意的是`、`综上所述`、`毋庸置疑`、`众所周知` |
| 词-03 | 铺垫式开场（仅段首）：`在当今`、`随着...的发展`、`首先让我们` |
| 词-04 | 讨好式表达：`好问题`、`让我来为您解释`、`希望对你有帮助` |
| 词-05 | 模糊缓冲（非概率语境）：`可能`、`某种程度上` — judge |
| 词-06 | 滥用「进行」：`进行分析` → `分析` |
| 词-07 | 单句内 ≥ 3 个「的」 |
| 词-08 | 拟人化装饰：`稳稳接住`、`保驾护航`、`丝滑`、`一键搞定` |

### 式 —— 结构 tell

| 规则 | 概要 | 检测 |
| --- | --- | --- |
| 式-01 | 段尾总结句：`综上所述`、`总的来说` 收尾 | 机械 |
| 式-02 | 机械并列：强套 `首先/其次/最后` | judge |
| 式-03 | 长定语前置：主语前定语 > 20 字 | judge |
| 式-04 | 四字词堆砌：连续 4 个及以上四字结构 | 机械 |
| **式-05** | **术语前后不一致**（v0.4 机械化）：`Model / model` 同文档混用 | 机械 |
| 式-06 | 中英文标点混用：中文段落混半角 `, . ? !` | 机械 |
| 式-07 | 列表滥用：能一句话说完的拆 2 项列表 | judge |
| 式-08 | 句长方差过低：段落内句长 std < 5 且 ≥ 4 句 | 机械 |

### 气 —— 语感原则（LLM-as-judge）

| 规则 | 概要 |
| --- | --- |
| 气-01 | 第一句直接入题（删首句第二句仍能独立成文？→ 首句是铺垫） |
| 气-02 | 不说正确但无用的话 |
| 气-03 | 有判断、有立场，不做「各有优劣」式综述 |
| 气-04 | 看本质，不停在现象 |
| 气-05 | 信息密度（三句能说完的别用五句） |
| 气-06 | 用人话，不文绉绉 |

---

## v0.4 新增能力

### 1. 文档评分（0-100，A-F 等级）

```bash
$ star-word review docs/RFC.md --mode strict
...
文档分: 87.3/100  等级: B  (字数 1240)
机械 + 结构规则违规总数: 4
  · 4 条语义规则未评估（需 LLM-as-judge）
```

三种 mode（`strict` / `normal` / `relaxed`）调权重不调阈值——避免「主动调宽就 10 分」的误导。

### 2. CI gate

```yaml
# .github/workflows/star-word.yml
- run: |
    pip install star-word
    star-word review docs/RFC.md --mode strict --fail-under 80
```

`--fail-under` 让退出码反映文档分阈值。文档分 < 80 → 退出码 1，CI 失败。

### 3. LLM-as-judge

`sense-pending` 规则不再是占位符。`star-word judge` 调 Claude API 给气组 6 条 + 部分式组打分：

```bash
$ ANTHROPIC_API_KEY=sk-... star-word judge docs/RFC.md
...
语义规则评分（LLM-as-judge）：
  气-01: 8.0/10  > 首句「订单服务每日 500w 读」直接入题，无铺垫
  气-02: 6.0/10  > 第三段有一句「整体架构清晰可靠」属于正确但无用
  气-03: 9.0/10  > 明确选 Cache-Aside，给了三个原因
  气-04: 7.0/10  > 部分回答了字面问题但深层未触
  气-05: 8.0/10  > 信息密度较高
  气-06: 10.0/10  > 用语自然
...
文档分: 84.2/100  等级: B
```

判 judge 用什么模型不重要——重要的是**严禁让被测模型 judge 自己**（self-preference）。详见 [`bench/methodology.md`](bench/methodology.md)。

### 4. MCP server（一键接入 Claude Desktop / Cursor）

```json
// ~/Library/Application Support/Claude/claude_desktop_config.json
{
  "mcpServers": {
    "star-word": {
      "command": "python",
      "args": ["-m", "star_word.mcp_server"]
    }
  }
}
```

四个 tool：`review_text`、`judge_text`、`get_rules`、`suggest_rewrite`。零依赖（不用装 mcp SDK），裸 stdio JSON-RPC 实现。

### 5. 改写建议

```bash
$ ANTHROPIC_API_KEY=sk-... star-word fix docs/RFC.md
改写建议（4 处）：

L42：
  - 我们通过顶层设计打通数据，全面提升业务闭环能力。
  + 我们把订单服务接到消息队列，延迟从 3 秒降到 200ms。
    理由：删除空词，给具体动作 + 量化结果

L78：
  - 综上所述，这是一个非常好的方案，希望对你有帮助。
  + 选 Cache-Aside 不选 Write-Through——读多写少的场景不需要同步写穿。
    理由：删段尾总结、删讨好式收尾，给立场
```

### 6. 上下文感知 grey_zone

`打通`、`链路`、`生态`、`布局` 这类词有合法技术用法。v0.4 检测器在 ±3 字窗口内判定：

- `调用链路追踪` → 合法，不报
- `打通业务链路` → 套话，告警
- `打通管道连接两个网络` → 合法，不报

---

## 输出 schema 与 CI 集成

完整 JSON schema 见 [`docs/JSON_SCHEMA.md`](docs/JSON_SCHEMA.md)。

```bash
# 程序化访问
star-word review doc.md --json | jq '.score.score'
# 87.3
```

或 Python API：

```python
from star_word import detectors, scoring
text = open("doc.md").read()
results = detectors.review(text)
doc = scoring.score_document(results, text, mode="strict")
print(doc.score, scoring.grade(doc.score))
```

---

## 支持的接入面

| 接入面 | 模式 | 目标文件 |
| --- | --- | --- |
| Claude Code | `anchor-import` | `CLAUDE.md`（项目级或全局级）|
| AGENTS.md 兼容（Codex CLI / Zed / Jules / Warp / Gemini CLI / VS Code） | `guarded-block` | `AGENTS.md` |
| Codex API | `manual-paste` | `.sw/codex-system-prompt.md`（手动粘贴）|
| CodeBuddy | `rule-file` | `.codebuddy/rules/star-word/RULE.mdc` |
| WorkBuddy | `skill-file` | `~/.workbuddy/skills/star-word/SKILL.md` |
| **MCP（v0.4 新）** | **stdio** | **任何 MCP client（Claude Desktop / Cursor / Cline）** |

---

## CLI 参考

```bash
star-word --version                       # 版本
star-word surfaces                        # 列出接入面
star-word handshake                       # 打印自检口令

# 接线 / 拆除
star-word enable claude-code --global     # 全局接入
star-word disable claude-code --global

# 审阅
star-word review doc.md                   # 默认 normal 模式
star-word review doc.md --mode strict     # 严格
star-word review doc.md --fail-under 80   # CI gate
star-word review doc.md --json            # 机器可读

# LLM 能力（需 ANTHROPIC_API_KEY）
star-word judge doc.md                    # 评估语义规则
star-word judge doc.md --rules 气-01,气-02
star-word fix doc.md --max 10             # 生成改写建议

# 服务模式
star-word mcp                             # 启动 MCP stdio server
```

---

## 正向语料库

[`examples/corpus/`](examples/corpus/) 5 篇原创技术写作示例，演示规则的 target state：

1. [JVM Full GC 排查复盘](examples/corpus/01-debugging-jvm-fullgc.md)
2. [Redis 集群迁移 RFC](examples/corpus/02-rfc-redis-migration.md)
3. [缓存击穿事故复盘](examples/corpus/03-postmortem-cache-stampede.md)
4. [限流器选型设计](examples/corpus/04-design-rate-limiter.md)
5. [数据库索引优化提效](examples/corpus/05-perf-database-index.md)

每篇 strict 模式过、文档分 100/100。ban list 告诉模型不要做什么；正向语料告诉模型要做什么。

---

## 局限

诚实说明 v0.4 还有的差距：

- **bench 不达最低门槛**。v0.2 那份 4 任务 × 1 次的数据被 v0.4 retired，新 bench 还没跑（[methodology](bench/methodology.md) 已定，欢迎社区贡献）。
- **judge 有 self-preference 风险**。当前默认 judge 用 Claude，被测如果也是 Claude，分数偏高。下一步加 cross-model judge 配置。
- **只支持简体中文**。架构里有 language 字段，但还没实现非中文规则。
- **rewriter 没做 fixture-based test**。当前 rewrite 质量靠 model 直觉，没有「改写后能过 review」的强制循环。
- **MCP server 实现的是 spec 子集**。够用 Claude Desktop / Cursor，复杂场景（resources / prompts）没实现。

---

## Roadmap

- **v0.5**：cross-model judge（让 judge 模型必须不同于被测模型）、rewrite-then-review 自动循环、Cursor / Copilot 原生 adapter、社区 bench 汇总
- **v0.6**：adaptive learning（记录用户接受/拒绝的改写，推导团队偏好）、npm 包
- **v1.0**：从词表升级为转换图谱——给出「X 应该变成 Y」的映射关系，规则从禁止型变为引导型

---

## 开发

```bash
git clone https://github.com/Stargod-0812/star-word.git
cd star-word/packages/python
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest                          # 95+ 个测试

# 改规则
cd ..
# 编辑 rules.yaml ...
python3 scripts/build.py        # 重新生成所有产物
python3 scripts/build.py --check   # CI 用：断言产物与 yaml 同步
```

### 代码结构

```
star-word/
├── rules.yaml                   # 唯一来源（22 条规则 + 权重）
├── scripts/build.py             # rules.yaml → 所有产物
├── RULES.md                     # 生成：规则全文
├── adapters/                    # 生成：各 surface 接入口
├── bench/methodology.md         # bench 方法论（v0.4 新）
├── docs/JSON_SCHEMA.md          # 输出 schema（v0.4 新）
├── examples/
│   ├── before.md / after.md     # 反面 / 正面对比
│   └── corpus/                  # 正向语料库（v0.4 新，5 篇）
└── packages/python/star_word/
    ├── cli.py                   # 6 个子命令
    ├── installer.py             # enable / disable
    ├── detectors.py             # 11 条机械/结构检测
    ├── scoring.py               # 0-100 评分（v0.4 新）
    ├── judge.py                 # LLM-as-judge（v0.4 新）
    ├── rewriter.py              # 改写建议（v0.4 新）
    └── mcp_server.py            # MCP stdio server（v0.4 新）
```

---

## 许可证

- 代码（`packages/`、`scripts/`）：MIT
- 规则文本（`RULES.md`、`adapters/*.md`、`rules.yaml`）：CC-BY-4.0
- 正向语料（`examples/corpus/*.md`）：CC-BY-4.0

转载、改编、再分发均欢迎，保留归属即可。见 [`NOTICE.md`](./NOTICE.md) 与 [`LICENSE`](./LICENSE)。

有建议 / bug：[issues](https://github.com/Stargod-0812/star-word/issues)。
