"""star-word 评分引擎（v0.4.1+）.

把违规列表压成 0-100 的复合分数。规则单分、组分、文档分都给。

设计原则：
- 文档分对长度归一化：1 处违规在 100 字 vs 10000 字本质不同
- 每条规则有权重；权重 reflect "this rule's importance to overall quality"
- 组内规则按权重加权平均（v0.4.1 修复：v0.4.0 是算术平均，与 docstring 不符）
- 组与组之间按 GROUP_WEIGHTS 加权平均
- 严格度（mode）只调单规则权重，不调阈值——避免「主动调宽就 10 分」的误导

评分公式（v0.4.1）：
    rule_score = max(0, 10 - violations_per_kchar * weight)
    group_score = sum(rule.score * rule.weight) / sum(rule.weight)   ← 加权
    doc_score   = sum(group_score * GROUP_WEIGHTS[g]) / sum(GROUP_WEIGHTS[active]) * 10
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

# -------- 权重表 --------

# 每规则违规对分数的扣减（per 1k chars）
RULE_WEIGHTS = {
    "词-01": 4.0,
    "词-02": 4.0,
    "词-03": 5.0,
    "词-04": 5.0,
    "词-05": 2.5,
    "词-06": 3.0,
    "词-07": 2.0,
    "词-08": 5.0,
    "式-01": 4.0,
    "式-02": 2.5,
    "式-03": 2.5,
    "式-04": 3.0,
    "式-05": 3.0,
    "式-06": 2.0,
    "式-07": 2.0,
    "式-08": 2.5,
    "气-01": 3.0,
    "气-02": 3.0,
    "气-03": 3.0,
    "气-04": 3.0,
    "气-05": 3.0,
    "气-06": 2.0,
}

# 组对最终文档分的贡献
GROUP_WEIGHTS = {
    "词": 0.40,
    "式": 0.30,
    "气": 0.30,
}

# 严格度调整：每个 mode 对所有规则权重做统一缩放
MODE_MULTIPLIERS = {
    "strict": 1.5,
    "normal": 1.0,
    "relaxed": 0.6,
}

# 极短文档保护：少于 N 字符直接标记 N/A，不假装能评估
MIN_DOC_CHARS = 20

# judge 评分中"算违规"的阈值（< 8 → violation_count = 1）
JUDGE_VIOLATION_THRESHOLD = 8.0


# -------- 数据类 --------


@dataclass
class RuleScore:
    rule_id: str
    score: float
    weight: float
    violation_count: int
    status: str  # "ok" / "violations" / "sense-pending" / "judged"
    judge_reasoning: str = ""


@dataclass
class GroupScore:
    group: str
    score: float
    has_active: bool = False  # v0.4.1: 替代之前的 setattr hack
    rules: List[RuleScore] = field(default_factory=list)


@dataclass
class DocumentScore:
    score: float
    char_count: int
    mode: str
    groups: List[GroupScore] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "score": round(self.score, 1) if self.score >= 0 else None,
            "char_count": self.char_count,
            "mode": self.mode,
            "groups": [
                {
                    "group": g.group,
                    "score": round(g.score, 2) if g.has_active else None,
                    "rules": [
                        {
                            "rule_id": r.rule_id,
                            "score": round(r.score, 2),
                            "weight": r.weight,
                            "violation_count": r.violation_count,
                            "status": r.status,
                            **({"judge_reasoning": r.judge_reasoning} if r.judge_reasoning else {}),
                        }
                        for r in g.rules
                    ],
                }
                for g in self.groups
            ],
            "notes": self.notes,
        }


# -------- 计算 --------


def _normalize_kchar(char_count: int) -> float:
    """字符数换千字单位，最少 0.5 防止极短文档分母过小。"""
    return max(0.5, char_count / 1000.0)


def score_rule(
    rule_id: str,
    violation_count: int,
    char_count: int,
    mode: str = "normal",
) -> RuleScore:
    base_weight = RULE_WEIGHTS.get(rule_id, 3.0)
    multiplier = MODE_MULTIPLIERS.get(mode, 1.0)
    weight = base_weight * multiplier
    kchar = _normalize_kchar(char_count)
    deduction = (violation_count / kchar) * weight
    score = max(0.0, 10.0 - deduction)
    status = "ok" if violation_count == 0 else "violations"
    return RuleScore(
        rule_id=rule_id,
        score=score,
        weight=weight,
        violation_count=violation_count,
        status=status,
    )


def score_document(
    results,  # List[RuleResult] from detectors
    text: str,
    mode: str = "normal",
    judge_results: Optional[List[RuleScore]] = None,
) -> DocumentScore:
    """从 detectors.review() 输出 + 可选 judge 输出，计算文档分。

    v0.4.1 修复：
    - 组内分数现在是按 weight 加权平均，与 docstring 一致
    - 极短文档（< MIN_DOC_CHARS）返回 score=-1 + note，不再假装满分
    - GroupScore.has_active 不再用 setattr hack
    """
    char_count = len(text)
    judge_by_id = {r.rule_id: r for r in (judge_results or [])}

    notes: List[str] = []

    # 极短文档保护
    if char_count < MIN_DOC_CHARS:
        notes.append(
            f"文档太短（{char_count} 字符 < {MIN_DOC_CHARS}），无法可靠评估。"
        )
        return DocumentScore(
            score=-1.0,
            char_count=char_count,
            mode=mode,
            groups=[],
            notes=notes,
        )

    # 按规则计分
    rule_scores: List[RuleScore] = []
    for r in results:
        # 跳过非真规则（doc:notes 等）
        if not (r.rule_id.startswith(("词-", "式-", "气-"))):
            continue
        # judge 已评 → 用 judge 的，但 weight 用 mode 调整后的
        if r.rule_id in judge_by_id:
            jr = judge_by_id[r.rule_id]
            base_weight = RULE_WEIGHTS.get(r.rule_id, 3.0)
            adjusted_weight = base_weight * MODE_MULTIPLIERS.get(mode, 1.0)
            rule_scores.append(RuleScore(
                rule_id=jr.rule_id,
                score=jr.score,
                weight=adjusted_weight,
                violation_count=0 if jr.score >= JUDGE_VIOLATION_THRESHOLD else 1,
                status="judged",
                judge_reasoning=jr.judge_reasoning,
            ))
            continue
        # sense-pending 但没 judge：标记不参与
        if r.status == "sense-pending":
            rule_scores.append(RuleScore(
                rule_id=r.rule_id,
                score=10.0,
                weight=0.0,
                violation_count=0,
                status="sense-pending",
            ))
            continue
        rule_scores.append(score_rule(r.rule_id, len(r.violations), char_count, mode))

    # 按组聚合（加权平均）
    groups: List[GroupScore] = []
    for group_id in ("词", "式", "气"):
        group_rules = [rs for rs in rule_scores if rs.rule_id.startswith(group_id)]
        active_rules = [r for r in group_rules if r.weight > 0]
        if active_rules:
            total_weight = sum(r.weight for r in active_rules)
            avg = sum(r.score * r.weight for r in active_rules) / total_weight
            groups.append(GroupScore(
                group=group_id, score=avg, has_active=True, rules=group_rules,
            ))
        else:
            groups.append(GroupScore(
                group=group_id, score=-1.0, has_active=False, rules=group_rules,
            ))

    # 文档分 = 仅在有活跃规则的组上做加权平均
    active_groups = [g for g in groups if g.has_active]
    if active_groups:
        total_weight = sum(GROUP_WEIGHTS[g.group] for g in active_groups)
        weighted_sum = sum(g.score * GROUP_WEIGHTS[g.group] for g in active_groups)
        doc_score = (weighted_sum / total_weight) * 10
    else:
        doc_score = -1.0
        notes.append("无活跃规则——无法评分。")

    pending_count = sum(1 for rs in rule_scores if rs.status == "sense-pending")
    if pending_count > 0:
        notes.append(
            f"{pending_count} 条语义规则未评估（需 LLM-as-judge）。"
            "运行 `star-word judge <file>` 获得完整文档分。"
        )

    return DocumentScore(
        score=doc_score,
        char_count=char_count,
        mode=mode,
        groups=groups,
        notes=notes,
    )


# -------- 输出辅助 --------


def grade(score: float) -> str:
    """0-100 → 等级标签。<0 → N/A。"""
    if score < 0:
        return "N/A"
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 70:
        return "C"
    if score >= 60:
        return "D"
    return "F"
