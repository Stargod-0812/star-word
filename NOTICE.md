# NOTICE

## 项目归属

star-word 是独立的中文技术写作规则集与执行工具，代码使用 MIT 许可证，规则文本（`RULES.md`、`adapters/*.md`）使用 Creative Commons Attribution 4.0 International（CC-BY-4.0）。

## 致谢与引用

本项目的工程结构、adapter 分发机制（`import-marker` / `append-block` / `owned-file`）、以及"生成时规则注入"这一思路，参考了 [yzhao062/agent-style](https://github.com/yzhao062/agent-style)（CC-BY-4.0 + MIT）。

规则内容为 star-word 原创，针对中文技术写作场景与中文 LLM 输出的 AI 味问题。不包含 agent-style 的 21 条英文规则原文。

## 规则编号映射

star-word 的规则编号（STAR-01..21）是独立命名空间，与 agent-style 的 RULE-01..12 / RULE-A..I 不存在一一对应关系。部分规则精神相通（如"禁用空洞词"、"避免段尾总结句"），但中文语境下的表现形式、违规词汇、检测逻辑均由 star-word 独立定义。

## 许可证

- 代码（`packages/`、`scripts/`）：MIT
- 规则文本与 adapter（`RULES.md`、`adapters/`、`README.md` 中引用的规则条文）：CC-BY-4.0
- 完整许可证文本见 `LICENSE`

使用 star-word 的规则文本时，请保留对 star-word 的引用。
