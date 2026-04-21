# CHANGELOG

## v0.2.0 — 2026-04-21

架构重构。rules.yaml 成为唯一来源。

### 架构
- `rules.yaml` 定义所有规则、禁用词、handshake；`scripts/build.py` 从此生成 `RULES.md` + 3 份 adapter + 包数据镜像。取代 v0.1 的多处手维护 + `scripts/sync.sh`。
- 规则 ID 重新编码：`STAR-01..21` → `词-01..08` / `式-01..07` / `气-01..06`。中文分组前缀，一眼就知道是哪类规则。
- 接入面（surface）三种模式重命名：`anchor-import`（Claude Code 的 @-import）、`guarded-block`（AGENTS.md 的 marker 块）、`manual-paste`（Codex API 的粘贴粘贴）。
- marker 语法改为 `<!-- sw-managed-begin/end -->`。
- 项目内存储目录：`.star-word/` → `.sw/`；规则文件：`RULES.md` → `rules.md`。
- Handshake 文本换成中文自然陈述句：「已加载 star-word v0.2.0：词表 8 条，结构 7 条，判断 6 条。规则正文见 .sw/rules.md。」

### CLI
- `list-tools` → `surfaces`（更准确：这些是接入面不是工具）。
- `verify` → `handshake`（语义更贴切）。
- `enable` / `disable` / `review` 保留。
- 新增 `--json` 支持在所有子命令上一致。

### 检测器
- `ScanContext`：每份文档预计算一次 fence map + inline code mask，所有规则共享。v0.1 是每条规则 O(N²) 重扫，v0.2 降到 O(N)。
- inline-code / 中文 「」 / 「""」 / 「''」 内容 masked，meta 文档（README / RULES）里的示例引用不再误报。
- 测试覆盖新 fence map 单次计算的不变式。

### 测试
- golden snapshot 测试：`.sw/rules.md`、`.sw/claude.md`、`AGENTS.md` 安装产物做 sha256 比对，installer 漏改一字节立刻挂。
- encoding 鲁棒性：CRLF + BOM 行尾的 `CLAUDE.md` 存在时 enable 不应炸。
- 防回归：测试强制 `surfaces` 返回的 mode 不再有 `import-marker` / `append-block` / `print-only`，marker 里不含 `:begin` / `:end`。
- 44 个测试全通过（v0.1 是 37 个）。

### CI
- macOS matrix 纳入 push/PR 测试。
- 弃用 `scripts/sync.sh`，改用 `python3 scripts/build.py --check` 在 CI 里验证 rules.yaml 与生成产物同步。
- 端到端 smoke test 改用新命令（`handshake` / `surfaces`）。

### 文件结构
- `adapters/codex.md` 的 SYSTEM PROMPT 从 yaml 的 handshake.text 字段派生，不再与 CLI handshake 有文本漂移风险。
- 清理 v0.1 里所有对其他项目的致谢 / 参考链接。

### 不兼容变更
- CLI 子命令 `list-tools` / `verify` 已删除，升级 v0.2 的用户改调 `surfaces` / `handshake`。
- `.star-word/` 目录不再存在，升级时先 `star-word disable` 再 `star-word enable` 让 v0.2 把存储目录落到 `.sw/`。
- `STAR-XX` 旧规则 ID 已删除。`review --json` 输出的 `rule_id` 字段用新编码。

## v0.1.0 — 2026-04-20

初始版本。21 条规则，3 个接入面（claude-code / agents-md / codex），10 条机械/结构检测，37 个测试。
