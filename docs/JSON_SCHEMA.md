# JSON 输出 schema（v0.4）

`star-word review --json` 和 `star-word judge --json` 的输出格式。

## review --json

```json
{
  "version": "0.4.0",
  "file": "examples/before.md",
  "score": {
    "score": 65.4,
    "char_count": 820,
    "mode": "normal",
    "groups": [
      {
        "group": "词",
        "score": 4.21,
        "rules": [
          {
            "rule_id": "词-01",
            "score": 0.0,
            "weight": 4.0,
            "violation_count": 3,
            "status": "violations"
          },
          {
            "rule_id": "词-05",
            "score": 10.0,
            "weight": 0.0,
            "violation_count": 0,
            "status": "sense-pending"
          }
        ]
      },
      { "group": "式", "score": 8.5, "rules": [...] },
      { "group": "气", "score": null, "rules": [...] }
    ],
    "notes": [
      "10 条语义规则未评估（需 LLM-as-judge）。运行 `star-word judge <file>` 获得完整文档分。"
    ]
  },
  "results": [
    {
      "rule_id": "词-01",
      "status": "violations",
      "violation_count": 3,
      "violations": [
        {
          "rule_id": "词-01",
          "message": "空洞价值词：'赋能'",
          "line": 42,
          "col": 8,
          "excerpt": "...全方位赋能业务团队..."
        }
      ]
    }
  ]
}
```

### 字段说明

**顶层**
- `version`：star-word 版本
- `file`：被检测文件路径
- `score`：见下
- `results`：每条规则一个 entry，含违规列表

**score 对象**
- `score`：文档分（0-100），`null` 表示无法评估（全 pending）
- `char_count`：字符数（含中英文混排）
- `mode`：`"strict" | "normal" | "relaxed"`
- `groups`：按词/式/气分组的子分数
- `notes`：附加说明（pending 提示等）

**group 对象**
- `group`：`"词" | "式" | "气"`
- `score`：组分（0-10），`null` 表示该组无活跃规则
- `rules`：组内每条规则一个 entry

**rule 对象**
- `rule_id`：如 `"词-01"`
- `score`：规则分（0-10）
- `weight`：当前权重（受 mode 影响）；0 表示该规则未参与评分
- `violation_count`：违规次数
- `status`：
  - `"ok"`：无违规
  - `"violations"`：有机械检测到的违规
  - `"sense-pending"`：需 LLM-as-judge 评估
  - `"judged"`：已由 judge 评分（含 `judge_reasoning` 字段）
- `judge_reasoning`（可选）：judge 给的理由

### 退出码

- `0`：零违规
- `1`：有违规，或 `--fail-under` 阈值未达
- `2`：参数错误或文件不存在

## judge --json

```json
{
  "score": 78.2,
  "char_count": 820,
  "mode": "normal",
  "groups": [
    {
      "group": "气",
      "score": 7.5,
      "rules": [
        {
          "rule_id": "气-01",
          "score": 8,
          "weight": 3.0,
          "violation_count": 0,
          "status": "judged",
          "judge_reasoning": "首句『订单服务每日 500w 读』直接入题，无铺垫"
        }
      ]
    }
  ],
  "notes": []
}
```

`judge` 的输出 schema 与 `review` 一致，区别在 sense-pending 规则被替换为 `status: "judged"` 的实际评分。

## CI gate 用法

```yaml
# .github/workflows/star-word.yml
- run: |
    pip install star-word
    star-word review docs/RFC.md --mode strict --fail-under 80
```

`--fail-under` 让退出码反映文档分阈值。文档分 < 80 → 退出码 1，CI 失败。

## 程序化访问

```python
import subprocess, json
result = subprocess.run(
    ["star-word", "review", "doc.md", "--json"],
    capture_output=True, text=True,
)
payload = json.loads(result.stdout)
print(f"Score: {payload['score']['score']}, Grade: {payload['score']['mode']}")
```

或直接用 Python API（无 subprocess）：

```python
from star_word import detectors, scoring
text = open("doc.md").read()
results = detectors.review(text)
doc = scoring.score_document(results, text, mode="strict")
print(doc.as_dict())
```
