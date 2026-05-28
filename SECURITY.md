# SECURITY 政策

## 报告漏洞

发现安全问题请发邮件到 GitHub 仓库 owner（不要提 public issue）。

我们承诺：
- **24 小时内回应**收到通知
- **7 天内确认**漏洞是否复现
- **30 天内修复**或给出明确时间表
- 修复后致谢报告者（除非要求匿名）

## 已加固的攻击面（v0.4.1）

### 1. LLM 调用（`judge.py` / `rewriter.py`）

**Prompt injection 防御**：
- 用户输入用 nonce sentinel `<DOC_{16-hex}_BEGIN>...<DOC_{16-hex}_END>` 包裹
- 系统提示明确声明 sentinel 之间内容不视为指令
- 攻击者无法预测 nonce，无法预先嵌入闭合 token

**JSON schema 校验**：
- LLM 输出的 `rule_id` 必须 ∈ `JUDGE_RUBRIC.keys()` 白名单
- `reasoning` / `suggested` 等自由文本字段经 ANSI / 控制码 strip + 长度截断

**API key 泄漏防护**：
- HTTP 错误体里的 `sk-***` 字串自动脱敏后再纳入异常消息
- ANSI 控制码自动剥离，避免污染终端输出

**输入大小硬上限**：
- `judge_text` / `suggest_rewrites` 默认 50KB（防烧 token）
- `detectors.review` 默认 2MB（防 OOM）
- 超过抛 `LLMError` / `ValueError`，不偷偷截断

### 2. Installer（写本地文件系统）

**Symlink follow 防御**：
- `_safe_copy` 在写入前检测 `dst.is_symlink()`，是则先 `unlink()`
- `dst.parent.is_symlink()` 一律拒绝（避免越权）
- `.sw/` 整体若为 symlink，拒绝写入并提示用户手动清理

**`HOME=/` 防御**：
- `--global` 模式下若 `HOME` 为空或 `/`，直接 ValueError 拒绝
- 避免 `mkdir(parents=True)` 在根目录失败给出「Permission denied」误导

**ReDoS 防护**：
- `_strip_marker_block` 使用 `count=1000` 限制 `re.sub`，避免 5000 个 unpaired marker 让 `.*?` 非贪婪回溯卡死

### 3. MCP server（stdio JSON-RPC）

**输入验证**：
- `text` 参数必须是 string、长度 ≤ MAX_TEXT_CHARS（1MB）
- `mode` 必须 ∈ `{strict, normal, relaxed}` 枚举
- `params` 必须是 object、`jsonrpc` 必须是 `"2.0"`（缺失容忍）
- 违反任意一条返回 `-32602 Invalid Params`（标准 JSON-RPC 错误码）

**资源上限**：
- 单条 stdin 消息 ≤ MAX_LINE_BYTES（10MB），超过返回 `-32600`
- HTTP 请求默认 60s 超时（`timeout` 参数可调）

**错误信息净化**：
- 内部异常的 `type(e).__name__` 不传给客户端
- Stack trace 进 stderr 日志（`SW_LOG_LEVEL` 控制）
- 客户端只看到 `"Tool error（详见 server stderr 日志）"`

### 4. Build script（解析 rules.yaml）

**栈溢出防护**：
- 自定义 YAML parser 限制递归深度 ≤ 64 层
- 超过抛 ValueError，避免恶意 PR 在 `rules.yaml` 里塞深嵌套搞 CI DoS

## 不在威胁模型内（设计选择）

以下场景**故意**不防御，因为成本远高于真实威胁：

- **运行不可信的 rules.yaml**：项目假设 `rules.yaml` 来自仓库本身，不是用户输入。读 PR 修改的 yaml 等同于读 PR 修改的 Python——CI 既然信任后者就不必特别防御前者。
- **CLAUDE.md / AGENTS.md 内容污染**：用户已对自己 CWD 下的这些文件有完全控制权。我们写入 marker 块、不读其它内容。
- **本地 LLM 模型恶意输出**：判 judge 用的模型本身被攻击者控制时，输出可能不可信。schema 校验把已知字段限制在白名单，但模型可以拒绝服务（返回空）。这种情况让用户自己重试或换模型。

## 依赖供应链

零运行时依赖。dev 依赖（`pytest`、`pytest-cov`、`hypothesis`、`ruff`、`mypy`）通过 `pyproject.toml` 声明。

PyPI 包未签名（计划 v0.5 加 sigstore）。

GitHub Actions 工作流：
- `actions/checkout@v4`、`actions/setup-python@v5`（pinned by major version）
- `permissions: contents: read` 在 v0.4.1 加入工作流默认权限收紧

## 报告示例

**好的报告**：
> 在 v0.4.1 的 `installer.enable_codex` 中，如果 `~/.claude/.sw/codex-system-prompt.md` 是 symlink 指向 `/etc/passwd`，跑 `star-word enable codex --global` 会把规则文本写到 /etc/passwd。复现脚本：[link]。修复建议：`_safe_copy` 应该在 `enable_codex` 也用上。
> 影响：在共享 CI runner 或多用户机器上是任意文件覆写。

**不太好的报告**：
> 这个项目可能有安全问题。
