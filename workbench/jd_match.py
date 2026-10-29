#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""jd_match.py — 履历 × 目标岗位 层级语义匹配引擎（M1-M4，纯规则零依赖）。

设计依据：《履历 × 目标岗位匹配评估系统 — 设计方案 v1.0》
本实现是零依赖规则版（LLM 归纳维度的可选通道留空，词表命中 + 规则推断代替）。

四大模块：
    M1 目标岗位解析器  build_requirements : JD 语料 → 能力需求向量
        requirements[] = {dim, minLevel(L1-L4), weight, category(must/nice_to_have),
                          coverage, mentions, jdEvidence[], respVerb}
        + verbProfile 职责动词画像（参与/负责/主导/治理 四档）
    M2 履历能力画像器  build_capabilities : profile.skills → 层级画像
        capabilities[] = {skill, detectedLevel, confidence, evidenceRefs,
                          refVerified, quantQuality, userConfirmed}
        层级锚点：L1 用会 / L2 负责实现 / L3 主导设计 / L4 治理闭环
        引用校验闭环：evidenceRefs 在履历原文（projects/experiences）子串校验
        量化口径分级：business(业务指标) > tech(技术指标) > decorative(纯形容词)
    M3 差距诊断引擎    build_dims : 逐维度对照 → 六色差距分型 + 硬门槛 + 加权匹配率
        七型：✅达标 🌟超配 ✏️表述差距 🔁迁移差距 📚学习差距 🏗️结构差距 ⛔硬差距
        匹配率 = Σ(min(actual, required) × weight) / Σ(required × weight)，超配不加分
    M4 行动建议生成器  build_cards : 四张卡（简历定制 / 证据补全 / 学习计划 / 面试预演）

与 engine.py 的关系：engine 的 analyze() 已按增量基线算好每个词库技能点的
_mentions/_coverage/_demand/_myScore/_inProfile/_matchedProfile/_hitLabels/_domain。
本模块直接消费这些中间产物（增量逻辑自动继承），补充 JD 片段抽取、层级推断、
六色分型与四张卡，输出写入 gap_analysis.json 的新字段。
"""

import datetime
import json
import math
import re

# ================================================================ 常量：层级与动词
LEVELS = {"L1": 1, "L2": 2, "L3": 3, "L4": 4}
LEVEL_LABEL = {
    "L1": "用会", "L2": "负责实现", "L3": "主导设计", "L4": "治理闭环",
}
LEVEL_HINT = {
    "L1": "了解/熟悉/使用过",
    "L2": "负责实现：在既定方案下完成开发落地",
    "L3": "主导设计：能拍板方案、搭骨架、对结果负责",
    "L4": "治理闭环：建机制/标准/体系并持续运营",
}

# JD 侧：职责动词 → 层级档位（设计方案 §5.1 的映射规则）
_L4_KEYS = ("治理", "机制", "标准", "规范", "闭环", "门禁", "平台化", "基座", "中台",
            "规模化", "全链路", "可持续优化", "持久化")
_L3_KEYS = ("主导", "搭建", "架构", "构建", "设计", "规划", "建设", "从0到1", "从 0 到 1",
            "重构", "牵头", "定义")
_L3_BOOST = ("体系", "演进", "方向", "长期", "整体", "核心子系统")
_L2_KEYS = ("负责", "开发", "实现", "优化", "迭代", "维护", "接入", "落地", "交付",
            "集成", "支持", "调试", "修复", "排查")
_L1_KEYS = ("了解", "熟悉", "掌握", "使用", "接触", "阅读", "跟进")

# 履历侧：层级判定关键词（M2）
_L4_HARD = ("治理", "闭环", "门禁", "制定标准", "沉淀", "规模化", "全链路", "标准化体系")
_L4_SOFT = ("中台", "基座", "平台化", "机制建设")
_L4_VERB_NEAR = ("主导", "搭建", "建设", "架构", "设计", "规划", "构建", "治理", "推动")
_L3_SELF = ("主导", "架构", "搭建", "构建", "设计", "重构", "从0到1", "从 0 到 1",
            "方案", "规划", "牵头", "定义", "体系建设", "机制建设")
_L2_SELF = ("负责", "开发", "实现", "优化", "迭代", "维护", "接入", "落地", "交付",
            "集成", "支持", "完成")

# 量化口径分级（business > tech > decorative）
_BUSINESS_WORDS = ("成本", "收入", "人力", "效率", "时间", "提升", "下降", "节省", "挽回",
                   "转化", "增长", "降低", "提高", "减少", "倍", "%", "％", "个百分点", "人天", "人时")
_TECH_WORDS = ("qps", "延迟", "吞吐", "p99", "p95", "p50", "内存", "cpu", "带宽", "并发",
               "gb/s", "mb/s", "ms", "节点", "tps", "rps", "召回率", "准确率", "token", "tok")

# 邻接维度映射（M3 迁移差距的判定依据；词表按需生长，Phase 2 从本体自然长出）
ADJACENCY = {
    "工具调用 / Function Calling": ["MCP 协议与工具生态", "Agent Harness 与运行时架构"],
    "MCP 协议与工具生态": ["工具调用 / Function Calling", "Agent Harness 与运行时架构"],
    "评测体系与指标设计": ["LLM-as-Judge 自动评估", "Badcase 分析与迭代闭环", "Agent 轨迹与过程评估"],
    "LLM-as-Judge 自动评估": ["评测体系与指标设计", "Badcase 分析与迭代闭环", "Agent 轨迹与过程评估"],
    "Badcase 分析与迭代闭环": ["评测体系与指标设计", "LLM-as-Judge 自动评估", "用户反馈闭环"],
    "Agent 轨迹与过程评估": ["评测体系与指标设计", "可观测性建设"],
    "可观测性建设": ["Agent 轨迹与过程评估", "审计与可回放"],
    "上下文工程": ["记忆与状态管理", "RAG 全流程"],
    "记忆与状态管理": ["上下文工程", "缓存设计", "向量数据库与向量检索"],
    "RAG 全流程": ["向量数据库与向量检索", "文本嵌入与语义检索", "上下文工程"],
    "向量数据库与向量检索": ["RAG 全流程", "文本嵌入与语义检索", "缓存设计"],
    "长链路稳定性与容错": ["可靠性与故障安全", "Agent 轨迹与过程评估"],
    "可靠性与故障安全": ["长链路稳定性与容错", "权限与访问控制"],
    "结构化输出与约束生成": ["提示工程", "工具调用 / Function Calling"],
    "提示工程": ["结构化输出与约束生成", "幻觉抑制与事实性"],
    "幻觉抑制与事实性": ["提示工程", "RAG 全流程", "评测体系与指标设计"],
    "推理部署与加速（vLLM/TGI/Ollama）": ["高并发与性能优化", "容器化与镜像工程"],
    "权限与访问控制": ["审计与可回放", "可靠性与故障安全", "内容安全与合规"],
    "成本与预算治理": ["可观测性建设", "评测体系与指标设计"],
    "Agent 开发框架（LangChain/LlamaIndex）": ["Agent Harness 与运行时架构", "多 Agent 编排"],
    "多 Agent 编排": ["Agent Harness 与运行时架构", "任务规划与分解"],
    "任务规划与分解": ["多 Agent 编排", "推理范式与自省"],
    "人机协同与审批流": ["权限与访问控制", "可靠性与故障安全"],
    "Python": ["Web 服务框架（FastAPI/Flask/Django）", "Agent 开发框架（LangChain/LlamaIndex）"],
    "TypeScript / JavaScript": ["前端工程与全栈交付", "MCP 协议与工具生态"],
    "网关与流量治理": ["系统架构设计", "微服务架构", "高并发与性能优化"],
}

# 同义词根（M3 近义匹配的第二层：维度别名 ≠ 履历技能名，但描述文本里出现同义概念，
# 如词库「评测」↔ 履历技能「可观测与评估」的 statement 含「评估」。按需生长。）
SYNONYM_ROOTS = {
    "评测": ["评测", "评估", "评价", "benchmark", "eval", "质量度量"],
    "评估": ["评测", "评估", "评价", "eval"],
    "检索": ["检索", "召回", "搜索", "retrieval"],
    "编排": ["编排", "orchestration", "调度", "协调", "仲裁"],
    "工具调用": ["工具调用", "function calling", "tool use", "tool calling", "函数调用"],
    "幻觉": ["幻觉", "hallucin", "事实性", "事实一致", "胡编"],
    "向量": ["向量", "embedding", "vector", "faiss", "milvus", "pgvector"],
    "权限": ["权限", "rbac", "访问控制", "鉴权", "授权", "最小权限"],
    "评测集": ["评测集", "测试集", "benchmark", "评测数据", "数据集"],
    "落地": ["落地", "上线", "投产", "商用", "业务化", "场景", "端到端交付"],
    "方案": ["方案", "文档", "rfc", "技术写作", "设计文档", "架构方案"],
    "微调": ["微调", "sft", "fine-tune", "finetune", "lora", "qlora"],
    "记忆": ["记忆", "memory", "状态管理", "上下文管理", "持久化"],
    "对齐": ["对齐", "rlhf", "dpo", "grpo", "偏好优化"],
    "多模态": ["多模态", "multimodal", "图文", "vision", "语音识别"],
    "检索增强": ["rag", "检索增强", "知识库", "知识问答"],
}

# 同领域地基（结构差距判定：must 缺失但相邻能力达 L2+）
_YEARS_RE = re.compile(r"(\d+)\s*[-~至]\s*(\d+)\s*年")
_YEARS_PLUS_RE = re.compile(r"(\d+)\s*年\s*(以上|及以上|以上相关|以上经验|plus)")


# ================================================================ 基础工具
def as_text(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        return " ".join(as_text(v) for v in value)
    if isinstance(value, dict):
        return " ".join(as_text(v) for v in value.values())
    return str(value)


def _lower(s):
    return s.strip().lower()


def job_years(job):
    """从 JD 抽取年限区间：优先 'X-Y年'，退回 'X年以上'；无则 None。"""
    jd = as_text(job.get("jd")) or ""
    m = _YEARS_RE.search(jd)
    if m:
        return "%s-%s 年" % (m.group(1), m.group(2))
    m = _YEARS_PLUS_RE.search(jd)
    if m:
        return "%s 年以上" % m.group(1)
    return None


def _snippet(jd, alias, width=42):
    """在 JD 原文中定位 alias，返回包含它的短片段（居中截断，含上下文）。"""
    low_jd, low_alias = jd.lower(), _lower(alias)
    pos = low_jd.find(low_alias)
    if pos < 0:
        return ""
    start = max(0, pos - width)
    end = min(len(jd), pos + len(alias) + width)
    frag = jd[start:end].replace("\n", " ").strip()
    if start > 0:
        frag = "…" + frag
    if end < len(jd):
        frag = frag + "…"
    return frag


def _snippet_level(snippet):
    """职责动词档位判定：治理 > 主导 > 负责 > 熟悉（设计方案 §5.1 映射）。

    校准规则（对抗 JD 语言天然的高要求表述，对齐设计文档示例映射）：
    * 「主导/牵头 + 体系词」「治理/制定标准/平台化」→ L4（治理级）
    * 「主导/搭建/建设/架构设计/从0到1」「负责 + 架构/体系/演进」→ L3（主导建设）
    * 「负责实现」「参与 + 体系词」→ L2（负责实现）
    * 「熟悉/掌握/了解」→ L1（用会）
    """
    s = _lower(snippet)
    # 1) L4 治理级：强治理义独立词
    if any(k in s for k in ("治理", "制定标准", "沉淀机制", "沉淀体系", "平台化", "规模化",
                            "中台", "基座", "建机制", "机制建设", "标准体系")):
        return "L4"
    # 2) 主导/牵头 + 体系词 → L4（主导治理）
    if any(k in s for k in ("主导", "牵头")) and any(
            k in s for k in ("治理", "体系", "机制", "标准", "规范", "闭环", "中台", "基座")):
        return "L4"
    # 3) 参与/熟悉前缀 + 体系词 → 降级（「参与体系建设」≠ 治理）
    if any(k in s for k in ("参与", "配合", "协助")):
        if any(k in s for k in ("体系", "机制", "标准", "规范", "治理", "闭环")):
            return "L2"
    if any(k in s for k in ("了解", "熟悉", "学习", "阅读")):
        if any(k in s for k in ("体系", "机制", "标准", "规范", "治理", "闭环")):
            return "L1"
    # 4) L3 主导建设
    if any(k in s for k in ("主导", "搭建", "从0到1", "从 0 到 1", "牵头", "架构设计",
                            "体系设计", "系统设计", "方案设计", "建设", "构建")):
        return "L3"
    # 5) 负责：带体系/架构/演进词 → L3，否则 L2
    if "负责" in s:
        if any(k in s for k in ("架构", "演进", "整体", "方向", "长期", "体系", "机制", "闭环")):
            return "L3"
        return "L2"
    # 6) 设计/规划/重构/定义 → L3
    if any(k in s for k in ("设计", "规划", "重构", "定义")):
        return "L3"
    # 7) L2 实现类
    if any(k in s for k in ("开发", "实现", "优化", "迭代", "维护", "接入", "落地",
                            "交付", "集成", "部署", "调试")):
        return "L2"
    # 8) L1 熟悉掌握类
    if any(k in s for k in ("熟悉", "掌握", "熟练", "使用", "了解", "接触")):
        return "L1"
    return None


def _resp_verb(snippet):
    """返回片段中最强的职责动词（用于展示）。"""
    s = _lower(snippet)
    for key in ("治理", "主导", "搭建", "架构", "构建", "设计", "建立", "负责", "开发",
                "实现", "优化", "维护", "支持", "熟悉", "掌握", "使用"):
        if key in s:
            return key
    return None


# ================================================================ M1 目标岗位解析器
def build_verb_profile(corpus):
    """职责动词画像：统计全部 JD 语料中四档动词的命中岗位数。"""
    buckets = {"治理": _L4_KEYS, "主导": _L3_KEYS, "负责": _L2_KEYS, "参与": ("参与", "配合", "协助")}
    out = {k: 0 for k in buckets}
    seen = {k: set() for k in buckets}
    for item in corpus:
        jd = _lower(as_text(item.get("job") and item["job"].get("jd")) or "")
        if not jd:
            continue
        for bucket, keys in buckets.items():
            if any(k in jd for k in keys):
                seen[bucket].add(id(item))
    for bucket, ids in seen.items():
        out[bucket] = len(ids)
    return out


def build_requirements(lexicon, corpus, total, documented, top=28):
    """JD 语料 → 能力需求向量。

    只对「有 JD 原文」的命中岗位抽取片段；minLevel 由职责动词档位推断，
    权重 = importance × (0.4 + 2×coverage)，must = 覆盖率 ≥ 0.2 或 importance ≥ 5。
    """
    reqs = []
    for domain in lexicon.get("domains") or []:
        dname = domain.get("name") or "未分类"
        for skill in domain.get("skills") or []:
            name = (skill.get("name") or "").strip()
            if not name:
                continue
            mentions = skill.get("_mentions") or 0
            coverage = skill.get("_coverage") or 0.0
            if mentions <= 0:
                continue
            importance = int(skill.get("importance") or 3)
            aliases = [a for a in (skill.get("aliases") or []) if isinstance(a, str) and a.strip()]
            # 抽取命中岗位的 JD 片段（最多 3 条）
            snippets, jobs_seen = [], set()
            for item in corpus:
                job = item.get("job") or {}
                jid = str(job.get("id") or item.get("position") or "")
                if jid in jobs_seen:
                    continue
                jd = as_text(job.get("jd")) or ""
                if not jd.strip():
                    continue
                hit_alias = next((a for a in aliases if _lower(a) in jd.lower()), None)
                if not hit_alias:
                    continue
                frag = _snippet(jd, hit_alias)
                if frag:
                    snippets.append({"text": frag, "job": item.get("position") or job.get("company") or ""})
                    jobs_seen.add(jid)
                if len(snippets) >= 5:
                    break
            # minLevel：用「全量片段」的档位中位数（更稳健，不被个别激进 JD 拔高）
            levels = [_snippet_level(s["text"]) for s in snippets]
            levels = [lv for lv in levels if lv]
            if levels:
                ordered = sorted(levels, key=lambda x: LEVELS[x])
                min_level = ordered[len(ordered) // 2]
            else:
                min_level = "L2" if mentions else None
            if min_level is None:
                continue
            # 展示片段：含职责动词的优先（证据更可信），只留 3 条
            snippets.sort(key=lambda s: (0 if _snippet_level(s["text"]) else 1, -len(s["text"])))
            snippets = snippets[:3]
            weight = round(importance * (0.4 + 2 * coverage), 3)
            category = "must" if (coverage >= 0.2 or importance >= 5) else "nice_to_have"
            resp_verbs = [_resp_verb(s["text"]) for s in snippets]
            resp_verb = next((v for v in resp_verbs if v), None) or "（未识别）"
            reqs.append({
                "dim": name,
                "domain": dname,
                "minLevel": min_level,
                "minLevelLabel": LEVEL_LABEL[min_level],
                "weight": weight,
                "category": category,
                "importance": importance,
                "coverage": coverage,
                "mentions": mentions,
                "jdEvidence": snippets,
                "respVerb": resp_verb,
            })
    reqs.sort(key=lambda r: (-(LEVELS[r["minLevel"]]), -r["weight"], -r["coverage"], r["dim"]))
    return reqs[:top]


# ================================================================ M2 履历能力画像器
def detect_level(item):
    """L1-L4 判定（纯规则，可复算）。返回 (level, reason)。

    锚点：L4 治理闭环 / L3 主导设计 / L2 负责实现 / L1 用会。
    statement 关键词为主，evidenceLevel 与量化指标作强度确认。
    """
    text = _lower(as_text(item.get("statement")) + " " + as_text(item.get("note")) + " "
                  + as_text(item.get("scenario")))
    metrics = [str(m) for m in (item.get("metrics") or []) if str(m).strip()]
    refs = [str(r) for r in (item.get("projectRefs") or []) if str(r).strip()]
    try:
        ev = int(item.get("evidenceLevel") or 0)
    except (TypeError, ValueError):
        ev = 0
    if any(k in text for k in _L4_HARD) and (metrics or refs):
        return "L4", "statement 含治理/体系/闭环类动词，且有落点" + ("与量化" if metrics else "")
    if any(k in text for k in _L4_HARD):
        return "L4", "statement 含治理/体系/闭环类动词（无落点，置信度存疑）"
    # 软治理词（中台/基座/平台化）需近邻出现动词才算治理级，避免项目名误判
    for kw in _L4_SOFT:
        pos = text.find(kw)
        while pos >= 0:
            window = text[max(0, pos - 12):pos + len(kw) + 4]
            if any(v in window for v in _L4_VERB_NEAR):
                return "L4", "statement 含「%s」且近邻治理动词，视为治理级" % kw
            pos = text.find(kw, pos + 1)
    if any(k in text for k in _L3_SELF) or ev >= 4:
        return "L3", "statement 含主导/设计/架构类动词" + ("（evidenceLevel=%d）" % ev if ev >= 4 else "")
    if any(k in text for k in _L2_SELF) or ev >= 3:
        return "L2", "statement 含负责/开发/实现类动词" + ("（evidenceLevel=%d）" % ev if ev >= 3 else "")
    return "L1", "仅声明使用/学习过，无明确职责动词"


def confidence_of(item, level):
    """层级置信度：high（落点≥2 且有量化）/ mid（有落点或量化）/ low（只有声明）。"""
    metrics = [str(m) for m in (item.get("metrics") or []) if str(m).strip()]
    refs = [str(r) for r in (item.get("projectRefs") or []) if str(r).strip()]
    if len(refs) >= 2 and metrics:
        return "high"
    if refs or metrics:
        return "mid"
    return "low"


def quant_quality(item):
    """量化口径分级：business(业务指标) > tech(技术指标) > decorative(纯形容词)。"""
    metrics = [str(m) for m in (item.get("metrics") or []) if str(m).strip()]
    if not metrics:
        return "decorative"
    blob = _lower(" ".join(metrics))
    if any(k in blob for k in _BUSINESS_WORDS):
        return "business"
    if any(k in blob for k in _TECH_WORDS):
        return "tech"
    return "tech"  # 有量化但无法归类的兜底：技术口径


def _scan_resume_evidence(profile, dim, aliases):
    """扫描所有项目 bullet（projects + experiences.highlights + subProjects.highlights）
    里有没有提到 dim 或其 aliases。返回 [{source, text}] 列表。

    用于硬差距/结构差距判定：即使 skills[] 里没显式登记这个技能，
    只要项目 bullet 里写了相关内容，就不能判成"完全无痕迹"。
    """
    import engine
    needles = [_lower(dim)] + [_lower(a) for a in (aliases or []) if a]
    hits = []
    def _scan(items, src_label):
        for it in items or []:
            if not isinstance(it, dict):
                continue
            bullets = it.get("highlights") or []
            if isinstance(bullets, str):
                bullets = [bullets]
            name = it.get("name") or it.get("company") or ""
            for b in bullets:
                bt = _lower(str(b))
                for n in needles:
                    if len(n) >= 2 and n in bt:
                        hits.append({"source": src_label + "：" + str(name), "text": str(b)[:120]})
                        break
    _scan(profile.get("projects"), "项目")
    for e in profile.get("experiences") or []:
        if not isinstance(e, dict):
            continue
        _scan([e], "工作")
        _scan(e.get("subProjects"), "工作项目")
    return hits[:5]


def ref_verified(item, profile):
    """引用校验闭环：projectRefs 中的项目名必须在履历原文（projects/experiences）中出现。"""
    refs = [str(r) for r in (item.get("projectRefs") or []) if str(r).strip()]
    if not refs:
        return {"verified": "none", "detail": "无项目落点（R1 警告）"}
    body = " ".join([
        as_text(p.get("name")) + " " + as_text(p.get("highlights")) + " " + as_text(p.get("stack"))
        for p in (profile.get("projects") or []) if isinstance(p, dict)
    ]).lower() + " " + " ".join([
        as_text(e.get("company")) + " " + as_text(e.get("role")) + " " + as_text(e.get("highlights"))
        for e in (profile.get("experiences") or []) if isinstance(e, dict)
    ]).lower()
    ok, miss = [], []
    for r in refs:
        if _lower(r) and _lower(r) in body:
            ok.append(r)
        else:
            miss.append(r)
    if miss:
        return {"verified": "partial" if ok else "false",
                "detail": "未在履历原文中匹配：%s" % "、".join(miss[:3])}
    return {"verified": "true", "detail": "全部落点均可在履历原文核验"}


def build_capabilities(profile, only_names=None):
    """profile.skills → 层级画像（只对 requirements 涉及的维度做深度判定）。"""
    caps = []
    for s in (profile.get("skills") or []):
        if not isinstance(s, dict) or not s.get("name"):
            continue
        name = str(s["name"]).strip()
        if only_names is not None and name not in only_names:
            continue
        level, reason = detect_level(s)
        caps.append({
            "skill": name,
            "detectedLevel": level,
            "levelLabel": LEVEL_LABEL[level],
            "confidence": confidence_of(s, level),
            "evidenceRefs": [str(r) for r in (s.get("projectRefs") or []) if str(r).strip()],
            "refVerified": ref_verified(s, profile),
            "quantQuality": quant_quality(s),
            "quantQualityLabel": {"business": "业务量化", "tech": "技术量化", "decorative": "纯描述"}[quant_quality(s)],
            "metrics": [str(m) for m in (s.get("metrics") or []) if str(m).strip()],
            "statement": as_text(s.get("statement")),
            "userConfirmed": None,
        })
    return caps


# ================================================================ M3 差距诊断引擎
def _cap_map(caps):
    """技能名 → 画像（后者覆盖前者；取层级最高的一条）。"""
    out = {}
    for c in caps:
        old = out.get(c["skill"])
        if old is None or LEVELS[c["detectedLevel"]] > LEVELS[old["detectedLevel"]]:
            out[c["skill"]] = c
    return out


def _foundation_level(req, caps, all_skill_names_by_domain):
    """must 缺失时检查「同领域相邻能力」是否有 L2+ 地基。返回 (bool, [技能名])。"""
    base_names = []
    for nm in all_skill_names_by_domain.get(req["domain"], []):
        c = caps.get(nm)
        if c and c["skill"] != req["dim"] and LEVELS[c["detectedLevel"]] >= 2:
            base_names.append(nm)
    return (bool(base_names), base_names[:3])


def build_dims(reqs, caps, lexicon, profile=None):
    """逐维度对照 → 六色差距分型（判定逻辑纯规则，可复算）。"""
    cap_by_name = _cap_map(caps)
    domain_skill_names = {}
    for d in lexicon.get("domains") or []:
        domain_skill_names[d.get("name") or ""] = [s.get("name") for s in (d.get("skills") or [])]

    dims = []
    for req in reqs:
        dim = req["dim"]
        required_n = LEVELS[req["minLevel"]]
        cap = cap_by_name.get(dim)
        status, gap_type, actual, leverage = None, None, "L0", ""
        # 取该维度的 aliases 用于全文扫描
        dim_aliases = []
        for d in lexicon.get("domains") or []:
            for s in d.get("skills") or []:
                if s.get("name") == dim:
                    dim_aliases = [str(a) for a in (s.get("aliases") or []) if str(a).strip()]
                    break
        # 全文扫描项目 bullet（即使 skills[] 没登记，项目里写了也算有痕迹）
        my_evidence = _scan_resume_evidence(profile, dim, dim_aliases) if not cap else []
        if cap:
            actual = cap["detectedLevel"]
            actual_n = LEVELS[actual]
            if actual_n >= required_n + 1:
                status, gap_type = "超配", "over"
                leverage = "差异化武器：简历前置 + 面试主引导方向（比岗位要求高一级）"
            elif actual_n >= required_n:
                status, gap_type = "达标", "ok"
                leverage = "已满足要求，按岗位措辞对齐即可"
            else:
                status, gap_type = "表述差距", "wording"
                leverage = "有直接经验但层级证据不足（%s 但要求 %s）：改写措辞 + 补证据升级" % (
                    LEVEL_LABEL[actual], LEVEL_LABEL[req["minLevel"]])
        else:
            # 未命中 skills[] → 先看项目 bullet 全文扫描
            if my_evidence:
                status, gap_type = "迁移差距", "migrate"
                actual = "L1"   # 项目里提到了，至少"用会"
                leverage = "项目 bullet 里已有相关描述，但未在技能区显式登记为「%s」：把技能补进技能区 + 按 JD 措辞改写" % dim
            else:
                near = _find_near(req, caps, lexicon)
                if near:
                    status, gap_type = "表述差距", "wording"
                    actual = "L0"
                    near_cap = cap_by_name.get(near)
                    near_lv = "（%s）" % near_cap["detectedLevel"] if near_cap else ""
                    leverage = ("近义经验存在（%s%s）但未按 JD 措辞表达：改写简历，显式使用「%s」术语，"
                                "把已有能力写成 JD 认得的语言" % (near, near_lv, dim))
                else:
                    adj = ADJACENCY.get(dim, [])
                    adj_hit = [a for a in adj if a in cap_by_name and LEVELS[cap_by_name[a]["detectedLevel"]] >= 2]
                    if adj_hit:
                        status, gap_type = "迁移差距", "migrate"
                        actual = "L0"
                        leverage = "邻接维度（%s）已达 L2+：把该经验迁移表述到「%s」，并补一个该维度的落地案例" % (
                            "、".join(adj_hit), dim)
                    elif req["category"] == "nice_to_have":
                        status, gap_type = "学习差距", "learn"
                        actual = "L0"
                        leverage = "加分项且完全缺失：列入学习计划，按权重排序投入"
                    else:
                        foundation, fnames = _foundation_level(req, cap_by_name, domain_skill_names)
                        if foundation:
                            status, gap_type = "结构差距", "structure"
                            actual = "L0"
                            leverage = "must 缺失但有同领域地基（%s）：建议做一个能落地该维度的真实项目" % "、".join(fnames)
                        else:
                            status, gap_type = "硬差距", "hard"
                            actual = "L0"
                            leverage = "must 且履历完全无痕迹、无地基：此维度是投递的硬门槛"

        dims.append({
            "dim": dim,
            "domain": req["domain"],
            "category": req["category"],
            "required": req["minLevel"],
            "requiredLabel": LEVEL_LABEL[req["minLevel"]],
            "actual": actual,
            "actualLabel": LEVEL_LABEL.get(actual, "无痕迹"),
            "status": status,
            "gapType": gap_type,
            "weight": req["weight"],
            "coverage": req["coverage"],
            "mentions": req["mentions"],
            "leverage": leverage,
            "jdEvidence": req["jdEvidence"],
            "respVerb": req["respVerb"],
            "myEvidence": my_evidence,
        })
    # 排序：硬 > 结构 > 表述 > 迁移 > 学习 > 超配/达标，再按权重
    order = {"hard": 0, "structure": 1, "wording": 2, "migrate": 3, "learn": 4, "ok": 5, "over": 6}
    dims.sort(key=lambda d: (order[d["gapType"]], -d["weight"], d["dim"]))
    return dims


def _find_near(req, caps, lexicon):
    """近义匹配（两层，可复算）：
    1) 名字层：履历技能名与维度名/别名存在带边界包含关系；
    2) 证据层：维度别名的同义词根出现在履历技能的描述文本（statement/note）中——
       「可观测与评估」的 statement 含「评估」，即视为「评测体系」的近义证据。
    """
    import engine
    candidates = [req["dim"]]
    for d in lexicon.get("domains") or []:
        for s in d.get("skills") or []:
            if s.get("name") == req["dim"]:
                candidates += [str(a) for a in (s.get("aliases") or []) if str(a).strip()]
                break
    # 层 1：名字 label_match
    for c in caps:
        if any(engine.label_match(cand, c["skill"]) for cand in candidates):
            return c["skill"]
    # 层 2：同义词根命中履历技能描述文本
    roots = set()
    for cand in candidates:
        lc = _lower(cand)
        for root, words in SYNONYM_ROOTS.items():
            if root in lc or lc in words:
                roots.update(words)
        # 别名自身（长度≥2 的非 ASCII 词）也直接参与文本匹配
        if len(lc) >= 2 and not engine.is_pure_ascii(lc):
            roots.add(lc)
    if roots:
        for c in caps:
            blob = _lower(as_text(c.get("statement")) + " " + as_text(c.get("note")))
            if any(len(r) >= 2 and r in blob for r in roots):
                return c["skill"]
    return None


def match_rate(dims):
    """匹配率双轴：
        overall = Σ(min(actual, required) × weight) / Σ(required × weight)，超配不加分
        evidenceQuality = 命中维度中量化口径为 business/tech 的占比
    """
    num = den = 0.0
    matched = 0
    for d in dims:
        req_n = LEVELS[d["required"]]
        act_n = LEVELS.get(d["actual"], 0)
        den += req_n * d["weight"]
        num += min(act_n, req_n) * d["weight"]
        if act_n > 0:
            matched += 1
    overall = round(num / den * 100) if den else 0
    return {
        "overall": overall,
        "evidenceQuality": 0,  # 由调用方填（dims 不含 quantQuality）
        "matched": matched,
        "total": len(dims),
        "hard": sum(1 for d in dims if d["gapType"] == "hard"),
    }


# ================================================================ M4 行动建议生成器
def build_cards(dims, caps, requirements):
    """四张卡：简历定制 / 证据补全 / 学习计划 / 面试预演。只产出改写建议与证据锚点，永不生成经历。"""
    cap_by_name = _cap_map(caps)
    learn_of = {r["dim"]: r for r in requirements}
    cards = {"resume": [], "evidence": [], "learn": [], "interview": []}

    # --- 简历定制卡（表述差距 + 迁移差距）---
    for d in dims:
        if d["gapType"] in ("wording", "migrate"):
            ev = (d["jdEvidence"] or [{}])[0].get("text", "")
            if d["gapType"] == "wording":
                cap = cap_by_name.get(d["dim"])
                if cap and LEVELS.get(d["actual"], 0) > 0:
                    action = ("把「%s」的表述层级从 %s（%s）提到 %s（%s）：statement 突出「主导/搭建/体系」类动词，"
                               "只调整措辞与重点，不新增事实。JD 原文：%s" % (
                                   d["dim"], d["actual"], d["actualLabel"], d["required"],
                                   d["requiredLabel"], ev[:60]))
                else:
                    action = ("履历有近义经验但没按 JD 措辞表达：在对应项目 bullet 中显式使用「%s」术语"
                               "（JD 原文：%s）。只做措辞对齐，不新增事实。" % (d["dim"], ev[:60]))
            else:
                action = ("把邻接维度的经验迁移表述到「%s」：在项目 bullet 中显式使用该维度术语与职责动词"
                           "（JD 原文：%s），并准备一个该维度的落地案例。" % (d["dim"], ev[:60]))
            cards["resume"].append({"dim": d["dim"], "required": d["required"], "action": action})

    # --- 证据补全卡（达标/超配/表述差距但量化口径不足或置信度低）---
    for d in dims:
        cap = cap_by_name.get(d["dim"])
        if not cap or d["gapType"] not in ("ok", "over", "wording"):
            continue
        if d["gapType"] == "wording" and LEVELS.get(d["actual"], 0) > 0:
            pass  # 命中但层级不足：改写 + 补证据，进本卡
        elif d["gapType"] == "wording":
            continue  # 未命中的表述差距走简历定制卡
        qq = cap["quantQuality"]
        metrics = cap["metrics"]
        if qq == "decorative" or cap["confidence"] == "low":
            prefix = "「%s」%s：%s" % (
                d["dim"],
                "已达 %s" % d["actualLabel"] if d["gapType"] != "wording" else "有直接经验但层级不足（%s 要求 %s）" % (
                    d["actualLabel"], d["requiredLabel"]),
                "只有形容词没有数字" if qq == "decorative" else "层级置信度低（落点不足）",
            )
            cards["evidence"].append({
                "dim": d["dim"],
                "actual": d["actual"],
                "action": (prefix + "补一条可核对的量化结果（业务指标优先，如成本/效率/时间，"
                           "次选技术指标如 QPS/延迟），并据实强化职责动词，面试官会追这一条。"),
            })
        elif qq == "tech":
            cards["evidence"].append({
                "dim": d["dim"],
                "actual": d["actual"],
                "action": ("「%s」有技术量化（%s）但缺业务口径：补一个业务收益数字（如成本下降、人力节省、"
                           "效率提升），业务量化比技术指标更打动面试官。" % (d["dim"], "、".join(metrics[:2]))),
            })

    # --- 学习计划卡（学习差距 + 结构差距 + 硬差距）---
    for d in dims:
        if d["gapType"] in ("learn", "structure", "hard"):
            req = learn_of.get(d["dim"]) or {}
            learn = None
            for domain in _LEXICON_CACHE.get("domains") or []:
                for s in domain.get("skills") or []:
                    if s.get("name") == d["dim"]:
                        learn = s.get("learn") or {}
                        break
            focus = as_text((learn or {}).get("focus"))
            steps = list((learn or {}).get("steps") or [])[:3]
            resources = list((learn or {}).get("resources") or [])[:3]
            kind_map = {"learn": "加分项补齐", "structure": "硬门槛项目补强", "hard": "硬门槛从零补"}
            cards["learn"].append({
                "dim": d["dim"],
                "kind": kind_map.get(d["gapType"], "学习"),
                "required": d["required"],
                "focus": focus or "该维度是投递硬门槛：先做一个最小可演示项目，再补系统知识。",
                "steps": steps,
                "resources": resources,
                "duration": as_text((learn or {}).get("duration")),
                "verification": as_text((learn or {}).get("verification")),
            })

    # --- 面试预演卡（超配 + 置信度存疑 + 量化口径存疑）---
    for d in dims:
        cap = cap_by_name.get(d["dim"])
        if d["gapType"] == "over" or (cap and cap["confidence"] == "low") or (
                cap and cap["quantQuality"] == "decorative"):
            why = []
            if d["gapType"] == "over":
                why.append("超配维度：面试官大概率按高一级追问")
            if cap and cap["confidence"] == "low":
                why.append("层级置信度低：会被要求证明")
            if cap and cap["quantQuality"] == "decorative":
                why.append("无量化口径：必被要求给数字")
            cards["interview"].append({
                "dim": d["dim"],
                "actual": d["actual"] if cap else "L0",
                "why": "、".join(why),
                "prepare": "准备 1-2 个该维度的具体实例（背景→动作→结果→数字），按 STAR 结构组织",
            })

    # 去重（同一维度可能同时进多张卡，卡内去重）
    for k in cards:
        seen, out = set(), []
        for x in cards[k]:
            if x["dim"] in seen:
                continue
            seen.add(x["dim"])
            out.append(x)
        cards[k] = out
    return cards


_LEXICON_CACHE = {}


def _set_lexicon(lexicon):
    _LEXICON_CACHE["domains"] = lexicon.get("domains") or []


# ================================================================ 汇总
def build_summary(dims, rate, hard_gaps):
    sentences = []
    if hard_gaps:
        names = [g["dim"] for g in hard_gaps[:3]]
        sentences.append("⚠️ 该岗位族存在 %d 个硬差距维度（%s），命中这些维度的岗位建议谨慎投递：要么先补项目，"
                         "要么把简历重心移到能扬长避短的岗位。" % (len(hard_gaps), "、".join(names)))
    sentences.append("按层级语义匹配（L1 用会 → L4 治理闭环），当前匹配率 %d%%，其中 %d/%d 个需求维度在履历中有对应能力。"
                     % (rate["overall"], rate["matched"], rate["total"]))
    ok_over = [d for d in dims if d["gapType"] in ("ok", "over")]
    wording = [d for d in dims if d["gapType"] == "wording"]
    if ok_over:
        sentences.append("已达标/超配 %d 项，集中在 %s，是简历与面试的主打方向。"
                         % (len(ok_over), "、".join(d["dim"] for d in ok_over[:3])))
    if wording:
        sentences.append("%d 项属于表述差距（有经验但没按 JD 措辞说），改简历即可，成本最低收益最快。"
                         % len(wording))
    return "".join(sentences)


def build_recommendations(dims, cards, hard_gaps):
    recs = []
    if hard_gaps:
        recs.append("先处理硬差距：%s。对 must 且零痕迹的维度，要么补一个真实项目，要么把投递方向调整为不强制该维度的岗位。"
                    % "、".join(g["dim"] for g in hard_gaps[:3]))
    if cards["resume"]:
        recs.append("简历定制（成本最低）：按 JD 措辞改写 %s 等 %d 项表述/迁移差距，全部有履历原文锚点，只改措辞不新增事实。"
                    % ("、".join(c["dim"] for c in cards["resume"][:3]), len(cards["resume"])))
    if cards["evidence"]:
        recs.append("证据补全：为 %s 等 %d 项补业务量化口径（成本/效率/时间），把技术指标翻译成业务收益。"
                    % ("、".join(c["dim"] for c in cards["evidence"][:3]), len(cards["evidence"])))
    if cards["learn"]:
        recs.append("学习计划：按权重优先 %s，先做可验证产出（项目/评测报告）再考虑投递该方向的岗位。"
                    % "、".join(c["dim"] for c in cards["learn"][:3]))
    if cards["interview"]:
        recs.append("面试预演：%s 等 %d 项会被深挖（超配/低置信/无量化的交叉项），按 STAR 各准备一个实例。"
                    % ("、".join(c["dim"] for c in cards["interview"][:3]), len(cards["interview"])))
    if not recs:
        recs.append("匹配度良好：把超配维度写进简历首屏，面试主动引导到自己的武器清单。")
    return recs[:6]


def build_report(lexicon, profile, corpus, total, documented, target=None, top=28, ignore_dims=None):
    """M1-M4 全流程，返回可直接写入 gap_analysis.json 的新结构。

    ignore_dims：用户校准——从需求向量中剔除的维度名列表（如针对 Agent 岗忽略
    「大模型微调（SFT）」等非必需项）。被忽略维度不进分型/匹配率/卡片/硬差距，
    但会完整保留在报告顶层 `ignoredDims` 供前端渲染「已忽略」区并可恢复。
    """
    _set_lexicon(lexicon)
    generated_at = datetime.datetime.now().replace(microsecond=0).isoformat()
    verb_profile = build_verb_profile(corpus)

    # M1
    requirements = build_requirements(lexicon, corpus, total, documented, top=top)
    if not requirements:
        return None
    # 用户校准：按维度名剔除被忽略项（保留完整信息用于「已忽略」区与恢复）
    ignore_set = {d.strip() for d in (ignore_dims or []) if d and d.strip()}
    ignored_reqs = [r for r in requirements if r["dim"] in ignore_set]
    if ignore_set:
        requirements = [r for r in requirements if r["dim"] not in ignore_set]
    if not requirements:
        return None
    req_names = {r["dim"] for r in requirements}

    # M2（履历全量画像；_find_near 的近义匹配需要全量视角）
    caps_full = build_capabilities(profile)

    # M3
    dims = build_dims(requirements, caps_full, lexicon, profile=profile)

    # M3.5（可选）：LLM 二次确认 hard 维度——规则判成"完全无痕迹"的，让 LLM 看项目 bullet 有没有相关经验
    dims = _llm_reconsider_hard(dims, profile)

    rate = match_rate(dims)
    # 证据质量双轴：命中维度的量化口径占比
    cap_by_name = _cap_map(caps_full)
    hit_qq = [cap_by_name[d["dim"]]["quantQuality"] for d in dims
              if d["gapType"] in ("ok", "over", "wording") and d["actual"] != "L0" and d["dim"] in cap_by_name]
    rate["evidenceQuality"] = round(sum(1 for q in hit_qq if q in ("business", "tech")) / len(hit_qq) * 100) if hit_qq else 0
    hard_gaps = [{"dim": d["dim"], "required": d["required"], "reason": d["leverage"]}
                 for d in dims if d["gapType"] == "hard"]

    # M4
    cards = build_cards(dims, caps_full, requirements)
    summary = build_summary(dims, rate, hard_gaps)
    recommendations = build_recommendations(dims, cards, hard_gaps)

    # 兼容字段：gaps（需动作的维度，带 plan/action）、strengths（达标/超配）
    learn_of = {r["dim"]: r for r in requirements}
    gaps_out, strengths_out = [], []
    for d in dims:
        item = {
            "dim": d["dim"],
            "domain": d["domain"],
            "status": d["status"],
            "gapType": d["gapType"],
            "required": d["required"],
            "requiredLabel": d["requiredLabel"],
            "actual": d["actual"],
            "actualLabel": d["actualLabel"],
            "coverage": d["coverage"],
            "mentions": d["mentions"],
            "weight": d["weight"],
            "category": d["category"],
            "leverage": d["leverage"],
            "jdEvidence": d["jdEvidence"],
            "respVerb": d["respVerb"],
        }
        if d["gapType"] in ("wording", "migrate", "learn", "structure", "hard"):
            req = learn_of.get(d["dim"]) or {}
            learn = None
            for dom in lexicon.get("domains") or []:
                for s in dom.get("skills") or []:
                    if s.get("name") == d["dim"]:
                        learn = s.get("learn") or {}
                        break
            item["action"] = next((c["action"] for c in cards["resume"] if c["dim"] == d["dim"]),
                                  next((c["action"] for c in cards["evidence"] if c["dim"] == d["dim"]), ""))
            if d["gapType"] in ("learn", "structure"):
                item["plan"] = {
                    "focus": as_text((learn or {}).get("focus")),
                    "steps": list((learn or {}).get("steps") or [])[:4],
                    "resources": list((learn or {}).get("resources") or [])[:4],
                    "duration": as_text((learn or {}).get("duration")),
                    "verification": as_text((learn or {}).get("verification")),
                }
            gaps_out.append(item)
        else:
            strengths_out.append(item)

    return {
        "engine": "jd_match_v1",
        "generatedAt": generated_at,
        "target": target,
        "position": {
            "years": _dominant_years(corpus),
            "verbProfile": verb_profile,
        },
        "requirements": requirements,
        "capabilities": caps_full,
        "dims": dims,
        "ignoredDims": ignored_reqs,          # 用户校准：被忽略的需求维度（前端「已忽略」区，可恢复）
        "matchRate": rate,
        "hardGaps": hard_gaps,
        "cards": cards,
        "gaps": gaps_out,
        "strengths": strengths_out,
        "summary": summary,
        "recommendations": recommendations,
    }


def build_job_insight(job, lexicon, profile, ignore_dims=None):
    """单岗位 × 履历 的层级匹配洞察（岗位池相关度百分比 + 岗位详情面板数据源）。

    与 build_report 同口径（M1 需求向量 / M2 L1-L4 画像 / M3 六色分型 + 匹配率 / M4 四卡），
    但语料从「岗位池聚合」换成「单岗 JD」：JD 片段现扫词库维度别名 → 需求向量
    （coverage 单岗取 0/1，minLevel 取片段档位），M2 画像（build_capabilities）与岗位无关可缓存复用。

    job 无 JD 时用 position + skillTags 拼语料兜底（粗粒度报告）；两者皆空返回 None。
    """
    _set_lexicon(lexicon)
    jd = as_text(job.get("jd")) or ""
    if not jd.strip():
        parts = [as_text(job.get("position"))] + [as_text(t) for t in (job.get("skillTags") or []) if isinstance(t, str)]
        jd = " ".join(p for p in parts if p.strip())
    if not jd.strip():
        return None
    low = jd.lower()
    reqs = []
    for domain in lexicon.get("domains") or []:
        dname = domain.get("name") or "未分类"
        for skill in domain.get("skills") or []:
            name = (skill.get("name") or "").strip()
            if not name:
                continue
            aliases = [a for a in (skill.get("aliases") or []) if isinstance(a, str) and a.strip()]
            hit = next((a for a in aliases if _lower(a) in low), None)
            if not hit:
                continue
            frag = _snippet(jd, hit)
            if not frag:
                continue
            lv = _snippet_level(frag) or "L2"
            # 单岗「加分项」语段 → nice_to_have，其余为 must（JD 明确要求）
            ctx = jd[max(0, low.find(_lower(hit)) - 60): low.find(_lower(hit)) + len(hit) + 60]
            category = "nice_to_have" if any(k in ctx for k in ("加分项", "加分", "优先考虑", "加分优先", "有加分")) else "must"
            importance = int(skill.get("importance") or 3)
            reqs.append({
                "dim": name,
                "domain": dname,
                "minLevel": lv,
                "minLevelLabel": LEVEL_LABEL[lv],
                "weight": round(importance * (0.4 + 2 * 1.0), 3),
                "category": category,
                "importance": importance,
                "coverage": 1.0,
                "mentions": 1,
                "jdEvidence": [{"text": frag, "job": job.get("company") or ""}],
                "respVerb": _resp_verb(frag) or "（未识别）",
            })
    reqs.sort(key=lambda r: (-(LEVELS[r["minLevel"]]), -r["weight"], r["dim"]))
    if not reqs:
        return None
    ig = set(ignore_dims or [])
    reqs = [r for r in reqs if r["dim"] not in ig]
    if not reqs:
        return None
    caps = build_capabilities(profile)
    dims = build_dims(reqs, caps, lexicon, profile=profile)
    rate = match_rate(dims)
    hard_gaps = [d for d in dims if d["status"] == "硬差距"]
    cards = build_cards(dims, caps, reqs)
    summary = build_summary(dims, rate, hard_gaps)
    recommendations = build_recommendations(dims, cards, hard_gaps)
    # 顶层兼容 gap_analysis 结构（前端复用岗位洞察页渲染函数）
    return {
        "engine": "jd_match_v1",
        "mode": "single_job",
        "target": {"id": (job.get("targetIds") or [None])[0], "title": job.get("position") or "单岗"},
        "position": {"title": job.get("position") or "", "level": None, "years": None, "verbProfile": {}},
        "requirements": reqs,
        "capabilities": caps,
        "dims": dims,
        "gaps": [d for d in dims if d.get("gap_type")],
        "strengths": [d for d in dims if d["status"] == "超配"],
        "ignoredDims": list(ig),
        "matchRate": rate,
        "hardGaps": hard_gaps,
        "cards": cards,
        "summary": summary,
        "recommendations": recommendations,
    }


def _dominant_years(corpus):
    """岗位池主流的年限要求（用于展示）。"""
    from collections import Counter
    cnt = Counter()
    for item in corpus:
        y = job_years(item.get("job") or {})
        if y:
            cnt[y] += 1
    if not cnt:
        return None
    return cnt.most_common(1)[0][0]


def _llm_reconsider_hard(dims, profile):
    """可选 LLM 二次确认：规则判成 hard（must 且零痕迹）的维度，
    让 LLM 看项目 bullet 里有没有相关经验，避免误判。

    没配 LLM key 就原样返回。
    """
    try:
        import llm_client
    except ImportError:
        return dims
    if not llm_client.is_enabled():
        return dims
    hard_dims = [d for d in dims if d["gapType"] == "hard"]
    if not hard_dims:
        return dims
    print(f"[llm] 开始二次确认 {len(hard_dims)} 个硬差距：{[d['dim'] for d in hard_dims]}", flush=True)
    # 收集履历全文
    resume_lines = []
    for p in profile.get("projects") or []:
        if not isinstance(p, dict):
            continue
        resume_lines.append("【项目】" + (p.get("name") or ""))
        for b in (p.get("highlights") or []):
            resume_lines.append("  - " + str(b))
    for e in profile.get("experiences") or []:
        if not isinstance(e, dict):
            continue
        resume_lines.append("【工作】" + (e.get("company") or "") + " " + (e.get("role") or ""))
        for b in (e.get("highlights") or []):
            resume_lines.append("  - " + str(b))
        for sp in e.get("subProjects") or []:
            resume_lines.append("  【子项目】" + (sp.get("name") or ""))
            for b in (sp.get("highlights") or []):
                resume_lines.append("    - " + str(b))
    resume_text = "\n".join(resume_lines)[:6000]

    dims_desc = "\n".join(
        f"- {d['dim']}（要求 {d['requiredLabel']}）：JD 引用「{(d.get('jdEvidence') or [{}])[0].get('text','')[:80]}」"
        for d in hard_dims
    )
    prompt = f"""你是履历匹配专家。以下是候选人的项目/工作经历 bullet 列表，以及规则引擎判定为"硬差距（完全无经验）"的岗位要求维度。

请逐个判断：候选人的 bullet 里是否**真的有**该维度的相关经验？
（注意：即使没有显式用这个词，只要做过类似的事就算有；如果完全没沾边就判 false）

返回 JSON：{{"results": [{{"dim": "维度名", "hasExperience": true/false, "level": "L1/L2/L3/L4", "evidence": "引用的 bullet 原文"}}]}}

候选人履历：
{resume_text}

待确认维度：
{dims_desc}
"""
    result = llm_client.chat_json([
        {"role": "system", "content": "你是严谨的技术履历匹配专家，只返回 JSON。"},
        {"role": "user", "content": prompt},
    ], timeout=90)
    print(f"[llm] LLM 返回：{json.dumps(result, ensure_ascii=False)[:500] if result else 'None'}", flush=True)
    if not result or not isinstance(result.get("results"), list):
        print("[llm] enrich 无有效结果，保留规则判定", flush=True)
        return dims
    # 建索引（LLM 返回的 dim 名可能带"（要求 L3）"后缀，去掉再匹配）
    by_dim = {}
    for r in result["results"]:
        if not isinstance(r, dict):
            continue
        dname = (r.get("dim") or "").split("（")[0].split("(")[0].strip()
        if dname:
            by_dim[dname] = r
    for d in dims:
        if d["gapType"] != "hard":
            continue
        r = by_dim.get(d["dim"])
        if not r or not r.get("hasExperience"):
            continue
        lv = r.get("level") or "L1"
        if lv not in ("L1", "L2", "L3", "L4"):
            lv = "L1"
        d["gapType"] = "migrate"
        d["status"] = "迁移差距"
        d["actual"] = lv
        d["actualLabel"] = LEVEL_LABEL.get(lv, lv)
        d["leverage"] = ("LLM 二次确认：项目 bullet 里有相关经验（%s），但未在技能区显式登记为「%s」。"
                         "把技能补进技能区 + 按 JD 措辞改写，即可从硬差距降级。" % (
                             (r.get("evidence") or "")[:80], d["dim"]))
        d["myEvidence"] = d.get("myEvidence") or []
        ev = r.get("evidence")
        if ev:
            d["myEvidence"].append({"source": "LLM 复核", "text": str(ev)[:120]})
        print(f"[llm] 硬差距降级：{d['dim']} → migrate {lv}", flush=True)
    return dims


if __name__ == "__main__":
    import json
    import os
    import sys

    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, os.path.join(ROOT, "workbench"))
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
    import engine as _engine

    _lex = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "lexicon.json"), encoding="utf-8"))
    _prof = json.load(open(os.path.join(ROOT, "data", "profile.json"), encoding="utf-8"))
    _jobs = json.load(open(os.path.join(ROOT, "data", "jobs.json"), encoding="utf-8"))
    if isinstance(_jobs, dict):
        _jobs = _jobs.get("jobs") or _jobs.get("list") or []
    _corpus = _engine.build_job_corpus(_jobs)
    _total = len(_corpus)
    _doc = sum(1 for c in _corpus if c["jd"].strip() or c["tags"])
    # 先用 engine 的 analyze 打中间字段（本模块依赖 _mentions/_coverage 等）
    _engine.analyze(_lex, _prof, _jobs, baseline=None, jobs_changed=True)
    rep = build_report(_lex, _prof, _corpus, _total, _doc, target={"id": "t1", "title": "Agent系统工程师"})
    if rep is None:
        print("[!] 无需求维度（岗位池为空或 JD 为空）")
        sys.exit(1)
    print(json.dumps(rep, ensure_ascii=False, indent=1)[:4000])
