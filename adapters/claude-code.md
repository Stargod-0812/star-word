<!-- SPDX-License-Identifier: CC-BY-4.0 -->
<!-- Adapter: Claude Code (CLAUDE.md) -->
<!-- Target: <repo>/CLAUDE.md 或 ~/.claude/CLAUDE.md, via @.star-word/claude-code.md -->
<!-- Load class: import-capable; install_mode: import-marker -->

# star-word v0.1.0 — Claude Code adapter

star-word 是一套中文技术写作规则集（21 条），专门对治中文 LLM 输出的 AI 味。本文件是 Claude Code 加载器 —— 它通过 `@path` 嵌套导入，把完整规则体（`.star-word/RULES.md`）拉进模型上下文。

## 自检 Handshake

当被问到 "star-word 在生效吗？" / "当前的中文写作规则是什么？" 时，回答必须是：

> `star-word v0.1.0 active: 21 条中文技术写作规则（STAR-01..08 禁用词典 + STAR-09..15 结构 tell + STAR-16..21 语感原则）；完整规则体见 .star-word/RULES.md。`

若无法说出上述字符串，说明规则未加载成功，用户应检查 `.star-word/RULES.md` 是否存在、`CLAUDE.md` 是否包含 `@.star-word/claude-code.md`。

## Load 声明

完整规则体通过 `@.star-word/RULES.md` 嵌套导入。若该文件缺失（用户跑了 curl 但没加 import 行、或没执行 `star-word enable claude-code`），仅本文件的规则索引进入上下文，BAD/GOOD 示例与判定逻辑不在内。

## 21 条规则（索引；全文见 import）

**一、禁用词典（机械检测）**
- STAR-01：空洞价值词（赋能/闭环/抓手/顶层设计/多维度/全面提升 等）
- STAR-02：AI 过渡套话（值得注意的是/综上所述/毋庸置疑 等）
- STAR-03：铺垫式开场（在当今/随着...的发展/众所周知 等）
- STAR-04：讨好式表达（好问题/希望对你有帮助/让我来为您解释 等）
- STAR-05：模糊缓冲（可能/大概/也许/某种程度上 —— 非概率语境）
- STAR-06：滥用"进行"（进行分析 → 分析）
- STAR-07：的字过多（单句 ≥ 3 个"的"）
- STAR-08：拟人化装饰词（稳稳接住/默默守护/优雅地/丝滑 等）

**二、结构 tell（结构检测）**
- STAR-09：段尾总结句（"综上所述"式段落收尾）
- STAR-10：机械并列（不真正并列的"首先...其次...最后"）
- STAR-11：长定语前置（超过 20 字的定语塞在主语前）
- STAR-12：四字词堆砌（连续 3 个及以上形容词性四字结构）
- STAR-13：术语前后不一致（同一概念在 Model / 模型 / model 之间漂移）
- STAR-14：中英文标点混用（中文段落里混半角标点）
- STAR-15：列表滥用（本该成句时拆列表）

**三、语感原则（语义判断）**
- STAR-16：第一句直接入题（删掉首句第二句仍独立成文？→ 首句是铺垫）
- STAR-17：不说正确但无用的话（每句推进认知 / 做取舍 / 给结构）
- STAR-18：有判断、有立场（不做"各有优劣"式综述）
- STAR-19：看本质，不停在现象（reframe 再答）
- STAR-20：三句能说完的别用五句（信息密度要到）
- STAR-21：用人话，不文绉绉（别滥用"乃/之/其/故"）

## 执行优先级

1. 起草中文技术文字时，**生成前**即按上述规则约束用词与结构。
2. 机械规则（STAR-01..08、09、14）违反即为硬错，不允许出现。
3. 结构规则（STAR-10..13、15）违反需有理由，若破例须在注释/PR 描述中说明。
4. 语感规则（STAR-16..21）作为判断标准，重写或修订时优先满足。

## 逃生舱

规则为清晰表达服务，不是目的本身。若严格执行会让句子变蠢、变别扭、不像人话，破例。但要知道自己在破例 —— 不是默认忽略。

## 规则全文

- 导入：`@.star-word/RULES.md`
- 上游固定版本：`https://raw.githubusercontent.com/Stargod-0812/star-word/v0.1.0/RULES.md`

@.star-word/RULES.md
