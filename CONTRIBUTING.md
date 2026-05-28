# 贡献指南

## TL;DR

```bash
git clone https://github.com/Stargod-0812/star-word.git
cd star-word/packages/python
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest                                   # 全部应通过

# 改规则
cd ..
# 编辑 rules.yaml
python3 scripts/build.py                 # 重新生成所有产物
python3 scripts/build.py --check         # CI 用：检查同步

# 跑 lint
cd packages/python
ruff check star_word/
mypy star_word/ --ignore-missing-imports
```

## PR 检查清单

提交前自查：

- [ ] `pytest` 全绿（`cd packages/python && python -m pytest`）
- [ ] `python3 scripts/build.py --check` 不报漂移
- [ ] 修改了 `rules.yaml` → 跑了 `python3 scripts/build.py` 生成产物
- [ ] 加新 detector → 加了对应单元测试 + 至少一个边界用例
- [ ] 修改了安全相关代码（`_llm.py` / `installer.py` / `mcp_server.py`）→ 加了对应 `test_security.py` 测试
- [ ] `ruff check` 无新增 error
- [ ] CHANGELOG 加了条目（不需要每个 PR 一条，每个 release 之前补齐）

## 加新规则

1. 在 `rules.yaml` 的 `rules:` 列表加新条目，用现有规则做模板
2. 跑 `python3 scripts/build.py` 让 `RULES.md` / `adapters/` / `data/` 同步
3. 在 `packages/python/star_word/detectors.py` 加 detector 函数（或加到 `SEMANTIC_RULES` 留 judge 处理）
4. 在 `packages/python/tests/test_detectors.py` 加单元测试（正例 + 反例 + 边界）
5. 在 `scoring.RULE_WEIGHTS` 给权重；常见硬错给 4-5，结构问题给 2-3，judge 类给 3
6. `examples/before.md` 加触发用例，`examples/after.md` 加修复版本
7. 更新 README 的规则表格

## 加新接入面（surface）

1. 在 `packages/python/star_word/installer.py` 加 `enable_<name>` / `disable_<name>` 函数
2. 注册到 `SUPPORTED_SURFACES` 字典
3. 加到 `list_surfaces()` 返回列表
4. 在 `scripts/build.py` 加 `gen_<name>_adapter(data)` 生成函数
5. 注册到 `main()` 的 `generated` dict
6. 加 golden snapshot 测试到 `test_installer.py::test_golden_snapshot_<name>_*`
7. 更新 README 的「支持的接入面」表格

## 加新 LLM 后端（除 Anthropic 外）

当前 `_llm.py` 直接写死 Anthropic。要加 OpenAI / Gemini：

1. 抽 `_llm.LLMClient` 抽象基类（`call`, `extract_text`）
2. 加 `_llm.AnthropicClient` / `OpenAIClient` 实现
3. `judge_text` / `suggest_rewrites` 接受可选 `client` 参数，默认从 env 自动选
4. 加 `STAR_WORD_PROVIDER=anthropic|openai|gemini` 环境变量
5. 测试用 mock 覆盖每个 provider

## 测试纪律

- **单元测试**：`tests/test_*.py`，必须 mock 网络
- **属性测试**：`tests/test_fuzz.py`，参数化 + 随机种子
- **安全测试**：`tests/test_security.py`，每个 v0.4.1 修复的 vuln 都有对应 regression
- **集成测试**：CI 的 `smoke` job，对真实 stdin/stdout 跑 CLI

跑测试：
```bash
python -m pytest tests/                  # 全部
python -m pytest tests/test_detectors.py # 单文件
python -m pytest -k "式_05"              # 按名字过滤
python -m pytest --cov=star_word --cov-report=term-missing  # 覆盖率
```

## 写作风格（PR 描述、commit message）

PR 描述和 commit message 必须用项目自己的规则：

- 第一句直接说做了什么——不要「值得注意的是」、「在本次 PR 中」开场
- 给具体数字（行数、性能、违规变化），不给"显著提升"
- 不要 emoji 和「🚀 Co-Authored-By: Claude」之类的 ceremony

参考 commit `d2a43d0` 的格式。

## DCO

提交即表示你拥有该代码或有权按 LICENSE（MIT 代码 / CC-BY-4.0 规则文本）分发。无需单独签 CLA。

## 决策原则

不接受的 PR 类型：

- 加新词到 `BANNED_*` 但没给 false-positive 测试 → 容易误报
- 改阈值（如 `式-08` 的 `std < 5`）但没给数据支撑 → magic number 不允许
- 加运行时依赖（`pyproject.toml` 的 `dependencies` 必须保持空）→ 零依赖是项目核心承诺
- 加 `# noqa` 或 `# type: ignore` 但没注释解释为什么 → 这是 lint 失败的红色信号

## 决策（建议先开 issue 再写代码）

涉及以下变更请先开 issue 讨论：

- 新规则
- 新接入面
- 改 scoring 权重或公式
- 新 LLM provider
- 与 v0.4.1 不向下兼容的改动

简单 bugfix / 加测试 / 文档修订直接 PR 即可。

## 联系

- Issue：[github.com/Stargod-0812/star-word/issues](https://github.com/Stargod-0812/star-word/issues)
- Security：见 `SECURITY.md`
