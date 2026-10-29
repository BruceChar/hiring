#!/usr/bin/env python3
"""技能评分模型 v3 —— 依据「证据强度金字塔」与「账实相符」规则。

一条技能的得分只由**可核对的事实**决定：

    证据分 = 强度分(≤50) + 落点分(≤30) + 量化分(≤20)     满分 100

  * 强度分：取该技能最强证据的星级（5 量化结果 / 4 规模复杂度 / 3 角色职责 / 2 外部验证 / 1 时长频率 / 0 证书课程）
  * 落点分：projectRefs 的数量 —— 技能必须能落到具体项目上（账实相符），没有落点的技能不可信
  * 量化分：metrics 里的可量化结果条数 —— 金字塔顶端、最有说服力的证据

岗位侧同样不用主观「重要度」，改用**覆盖率**（提到该技能的岗位数 ÷ 有技能标签或 JD 的岗位数并分档）。
"""

# ---------------------------------------------------------------- 四大分类
GROUPS = {
    "professional": {"label": "专业技能", "desc": "可验证的方法与领域能力，技能区主体，按目标岗位匹配度排序"},
    "tools": {"label": "工具与技术栈", "desc": "语言 / 框架 / 数据库 / 中间件 / 云与 DevOps，按技能簇分组"},
    "soft": {"label": "通用能力", "desc": "通过经历 bullet 证明；确需列出时带场景，最多 5 条"},
    "credentials": {"label": "语言与资质", "desc": "外语等级、证书、执照，按含金量降序"},
}
TOOL_CLUSTERS = ["语言", "框架", "数据库", "中间件", "云与 DevOps", "平台"]
SOFT_LIMIT = 5

# ------------------------------------------------------- 证据强度金字塔 4.4
EVIDENCE_LEVELS = {
    5: {"stars": "★★★★★", "label": "可量化的项目结果", "base": 50, "example": "GC 停顿 800ms→120ms；挽回率 +12%"},
    4: {"stars": "★★★★", "label": "规模 / 复杂度上下文", "base": 40, "example": "日活 500 万、QPS 3 万、200 节点集群"},
    3: {"stars": "★★★", "label": "角色与职责", "base": 28, "example": "主导 / 独立负责 / 参与 3 个模块"},
    2: {"stars": "★★", "label": "外部验证", "base": 18, "example": "开源 PR 被合并、竞赛名次、专利"},
    1: {"stars": "★", "label": "时长与频率", "base": 8, "example": "主力语言 3 年"},
    0: {"stars": "☆", "label": "证书 / 课程", "base": 4, "example": "仅证明学过，不证明会用"},
}

TIERS = [
    (80, "强证据", "量化结果 + 多项目落点，可直接作为简历主打项"),
    (60, "较充分", "有明确落点与角色，补一条量化结果即可升级"),
    (40, "一般", "有落点但强度不足，建议补规模或结果"),
    (20, "薄弱", "证据单薄，宜降格表述或补证据"),
    (0,  "待补证据", "只有声明没有落点，按 R1 需要补证据或删除"),
]

# 岗位侧覆盖率分档（由数据推导，不手工指定）
COVERAGE_TIERS = [
    (0.40, "必备", "超过四成目标岗位要求"),
    (0.20, "常见", "两成以上目标岗位提到"),
    (0.08, "加分", "少量岗位提到，属于差异化能力"),
    (0.0,  "少见", "仅个别岗位提到"),
]

MAX_STRENGTH, MAX_REFS, MAX_METRICS = 50, 30, 20


def _level(v):
    try:
        n = int(v)
    except (TypeError, ValueError):
        n = 0
    return max(0, min(5, n))


def evidence_score(skill, now_year=None):
    """返回 {score, tier, tierDesc, breakdown, stars, facts}。

    breakdown 逐项列出得分来源，供 UI 展示——分数必须可解释、可复核。
    """
    lv = _level(skill.get("evidenceLevel"))
    refs = [r for r in (skill.get("projectRefs") or []) if str(r).strip()]
    metrics = [m for m in (skill.get("metrics") or []) if str(m).strip()]

    strength = EVIDENCE_LEVELS[lv]["base"]
    ref_score = min(len(refs) * 12, MAX_REFS)
    metric_score = min(len(metrics) * 10, MAX_METRICS)
    total = strength + ref_score + metric_score

    tier = next(t for t in TIERS if total >= t[0])
    return {
        "score": total,
        "tier": tier[1],
        "tierDesc": tier[2],
        "stars": EVIDENCE_LEVELS[lv]["stars"],
        "breakdown": {"证据强度": strength, "项目落点": ref_score, "量化结果": metric_score},
        "facts": {
            "evidenceLevel": lv,
            "evidenceLabel": EVIDENCE_LEVELS[lv]["label"],
            "refCount": len(refs),
            "metricCount": len(metrics),
            "refs": refs,
            "metrics": metrics,
        },
    }


def coverage_tier(coverage):
    t = next(x for x in COVERAGE_TIERS if coverage >= x[0])
    return {"tier": t[1], "tierDesc": t[2], "threshold": t[0]}


def gap_priority(coverage, my_score, max_scale=5.0):
    """缺口优先级：岗位要得多 + 我证据少 → 优先级高。全部来自可复算的量。"""
    c = max(0.0, min(1.0, float(coverage or 0)))
    s = max(0.0, min(100.0, float(my_score or 0)))
    return round(c * (1 - s / 100.0) * max_scale, 2)


def profile_health(profile):
    """技能区结构体检：四大分类占比、软技能是否超限、资质是否空缺。"""
    skills = profile.get("skills") or []
    from collections import Counter
    cnt = Counter(s.get("group", "professional") for s in skills)
    issues = []
    if cnt.get("soft", 0) > SOFT_LIMIT:
        issues.append(f"通用能力列了 {cnt['soft']} 条，规范要求 ≤{SOFT_LIMIT} 条且必须带场景")
    for s in skills:
        if s.get("group") == "soft" and not (s.get("scenario") or "").strip():
            issues.append(f"通用能力「{s.get('name')}」缺少场景说明")
    if not cnt.get("credentials"):
        issues.append("「语言与资质」为空——如有外语等级/证书/执照请补上，没有可忽略")
    if not cnt.get("professional"):
        issues.append("「专业技能」为空——技能区主体不应为空")
    return {"counts": dict(cnt), "issues": issues, "total": len(skills)}


if __name__ == "__main__":
    import json
    demo = {"name": "高并发与性能优化", "group": "professional", "cluster": "性能工程", "evidenceLevel": 5,
            "projectRefs": ["高性能 JSON-RPC 代理网关", "ParallelFinance"],
            "metrics": ["吞吐提升 5-10 倍", "单日流量高峰 2TB"]}
    print(json.dumps(evidence_score(demo), ensure_ascii=False, indent=1))
