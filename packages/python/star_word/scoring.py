"""star-word 评分引擎（v0.4）.

把违规列表压成 0-100 的复合分数。规则单分、组分、文档分都给。

设计原则：
- 文档分对长度归一化：1 处违规在 100 字 vs 10000 字本质不同
- 每条规则有权重；机械规则（明确错的）权重高于结构规则
- 语义规则（sense-pending / judge-only）默认不计入机械分，由 judge 模块加权重叠
- 严格度（mode）只调阈值，不调权重——避免「主动调宽就 10 分」的误导

评分公式：
    rule_score = max(0, 10 - violations_per_kchar * weight)
    group_score = weighted_avg(rule_scores, by group_weight)
    doc_score   = weighted_avg(group_scores) * 10  # → 0..100
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import List, Optional

from .detectors import RuleResult


# -------- 权重表（可由 mode 调整） --------

# 每规则违规对分数的扣减（per 1k chars）
# 数值越大，越敏感；想让规则更宽松降低数值。
RULE_WEIGHTS = {
    "词-01": 4.0,  # 空洞价值词——硬错
    "词-02": 4.0,  # AI 过渡套话——硬错
    "词-03": 5.0,  # 段首铺垫——硬错（位置敏感）
    "词-04": 5.0,  # 讨好式表达——硬错
    "词-05": 2.5,  # 模糊缓冲——judge
    "词-06": 3.0,  # 滥用「进行」——常见但易改
    "词-07": 2.0,  # 的字过多——较易误报
    "词-08": 5.0,  # 拟人化装饰——硬错
    "式-01": 4.0,  # 段尾总结句
    "式-02": 2.5,  # 机械并列——judge
    "式-03": 2.5,  # 长定语前置——judge
    "式-04": 3.0,  # 四字词堆砌
    "式-05": 3.0,  # 术语不一致
    "式-06": 2.0,  # 半角混用——格式问题
    "式-07": 2.0,  # 列表滥用——judge
    "式-08": 2.5,  # 句长方差过低
    "气-01": 3.0,  # judge
    "气-02": 3.0,
    "气-03": 3.0,
    "气-04": 3.0,
    "气-05": 3.0,
    "气-06": 2.0,
}

# 组权重——对最终文档分的贡献
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


# -------- 数据类 --------


@dataclass
class RuleScore:
    rule_id: str
    score: float           # 0-10
    weight: float          # 当前权重
    violation_count: int
    status: str            # "ok" / "violations" / "sense-pending" / "judged"
    judge_reasoning: str = ""  # judge 模块填的解释，机械检测留空


@dataclass
class GroupScore:
    group: str
    score: float           # 0-10
    rules: List[RuleScore] = field(default_factory=list)


@dataclass
class DocumentScore:
    score: float           # 0-100
    char_count: int
    mode: str              # strict / normal / relaxed
    groups: List[GroupScore] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "score": round(self.score, 1),
            "char_count": self.char_count,
            "mode": self.mode,
            "groups": [
                {
                    "group": g.group,
                    "score": round(g.score, 2) if g.score >= 0 else None,
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
    """把字符数换成「千字符单位」，最少 0.5 防止极短文档分母过小。"""
    return max(0.5, char_count / 1000.0)


def score_rule(
    rule_id: str,
    violation_count: int,
    char_count: int,
    mode: str = "normal",
) -> RuleScore:
    """单规则评分。"""
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
    results: List[RuleResult],
    text: str,
    mode: str = "normal",
    judge_results: Optional[List[RuleScore]] = None,
) -> DocumentScore:
    """从 detectors.review() 的输出 + 可选的 judge 输出，计算文档分。

    judge_results: 来自 judge 模块的 RuleScore 列表（含 reasoning）。
                   若提供，会覆盖同 rule_id 的机械检测分。
    """
    char_count = len(text)
    judge_by_id = {r.rule_id: r for r in (judge_results or [])}

    # 先按规则计分
    rule_scores: List[RuleScore] = []
    for r in results:
        # 如果 judge 已经给过分，用 judge 的
        if r.rule_id in judge_by_id:
            rule_scores.append(judge_by_id[r.rule_id])
            continue
        # sense-pending 但没 judge：跳过这条规则（不计入分数）
        if r.status == "sense-pending":
            rule_scores.append(RuleScore(
                rule_id=r.rule_id,
                score=10.0,  # 不计入扣分
                weight=0.0,  # 标记为不参与
                violation_count=0,
                status="sense-pending",
            ))
            continue
        rule_scores.append(score_rule(r.rule_id, len(r.violations), char_count, mode))

    # 按组聚合（只算实际有权重的规则）
    groups: List[GroupScore] = []
    for group_id in ("词", "式", "气"):
        group_rules = [rs for rs in rule_scores if rs.rule_id.startswith(group_id)]
        active_rules = [r for r in group_rules if r.weight > 0]
        if active_rules:
            avg = sum(r.score for r in active_rules) / len(active_rules)
            has_active = True
        else:
            # 全 pending：组分标记 None（用 -1 表示），不参与文档分计算
            avg = -1.0
            has_active = False
        gs = GroupScore(group=group_id, score=avg, rules=group_rules)
        # 把 has_active 临时挂在对象上供后续过滤
        setattr(gs, "_has_active", has_active)
        groups.append(gs)

    # 文档分 = 仅在有活跃规则的组上做加权平均，权重重归一化
    active_groups = [g for g in groups if getattr(g, "_has_active", False)]
    if active_groups:
        total_weight = sum(GROUP_WEIGHTS[g.group] for g in active_groups)
        weighted_sum = sum(g.score * GROUP_WEIGHTS[g.group] for g in active_groups)
        doc_score = (weighted_sum / total_weight) * 10  # 0..100
    else:
        doc_score = 0.0  # 全 pending：无法评估

    notes: List[str] = []
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
    """0-100 → 等级标签。便于 PR review 的 gate 判断。"""
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 70:
        return "C"
    if score >= 60:
        return "D"
    return "F"
