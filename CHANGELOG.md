# CHANGELOG

## v0.1.0 — 2026-04-20

初始版本。

### 规则
- 21 条中文技术写作规则（STAR-01 至 STAR-21），分三组：
  - STAR-01..08：禁用词典（机械检测）
  - STAR-09..15：结构 tell（结构检测）
  - STAR-16..21：语感原则（语义判断）
- 默认禁用词清单收敛到高 precision：`赋能`、`闭环`、`抓手`、`顶层设计`、`多维度`、`全面提升`、`深度赋能`、`打通`、`拉通`、`加持`、`一体化`、`全链路`、`场景化`。歧义词（`链路`、`生态`、`布局`）列在 RULES.md 可疑清单但不纳入机械检测。

### 工具适配
- Claude Code（`import-marker` 模式，支持项目级与 `--global` 全局级）
- AGENTS.md 兼容（`append-block`，覆盖 Codex CLI / Zed / Jules / Warp / Gemini CLI / VS Code）
- Codex API（`print-only`，手动粘贴到 `system_prompt`）

### CLI
- `star-word enable <tool> [--global]`
- `star-word disable <tool> [--global]`
- `star-word list-tools`
- `star-word review <file> [--json]`：检测 STAR-01..04、06、07、08、09、12、14（共 10 条机械/结构规则）
- `star-word verify`：打印自检握手字符串

### 检测器
- 反引号内联代码、中文/英文引号、markdown code fence 内容自动跳过（避免 meta 引用误报）
- 37 个 pytest 单元测试覆盖：规则正确性、installer 幂等、CLI 端到端

### 已知局限
- 语义规则（STAR-05、10、11、13、15、16-21）不做机械检测，由宿主模型或人工判断
- 只支持简体中文
- 只有 pip 包，npm 包在 v0.2 计划中

### 归属
- 工程结构与 adapter 分发机制参考 [yzhao062/agent-style](https://github.com/yzhao062/agent-style)
- 规则内容、禁用词清单、检测器实现为 star-word 独立设计
