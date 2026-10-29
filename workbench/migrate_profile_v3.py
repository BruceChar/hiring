#!/usr/bin/env python3
"""profile.json v2 → v3：技能区重构为「四大分类 + 证据强度 + 项目落点」。

四大分类（group）：
  professional  专业技能 —— 可验证的方法与领域能力，技能区主体，按目标岗位匹配度排序
  tools         工具与技术栈 —— 按技能簇分组（语言/框架/数据库/中间件/云与 DevOps）
  soft          通用能力 —— 必须带场景，最多 5 条
  credentials   语言与资质 —— 按含金量降序

新增字段：
  group        四大分类之一
  cluster      技能簇
  statement    完整证据句（核心技能才需要）
  evidenceLevel 证据强度 0-5：5 量化结果 / 4 规模复杂度 / 3 角色职责 / 2 外部验证 / 1 时长频率 / 0 证书课程
  projectRefs  项目落点（R1/R2 账实相符检查的依据）
  metrics      可量化结果
  scenario     软技能的场景（soft 必填）

另有顶层 skillEnvironment：日常工作环境聚合行（豁免 R1 的存在性要求）。
"""
import json
import os
import shutil
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILE = os.path.join(ROOT, "data", "profile.json")

MAZI = "Harness 框架 mazi"
SOC = "自动化事件预测 Agent 系统"
GW = "高性能 JSON-RPC 代理网关"
PARA = "ParallelFinance"
STORE = "企业级全闪存储引擎"
SHI = "杭州石匍丁科技"

# name: (group, cluster, evidenceLevel, statement, projectRefs, metrics, scenario)
PLAN = {
    # ---------- professional ----------
    "Agent Harness": ("professional", "系统设计", 4,
        "主导 Agent Harness 体系建设：Goal-Task-Step 可观测 + Contract 结果可验证 + ToolGateway 权限治理，"
        "把模型的概率性推理收束为可回滚、可审计的行动序列。", [MAZI, SOC], ["Token 级可观测与成本审计"], ""),
    "多 Agent 编排": ("professional", "系统设计", 3,
        "主导多 Agent 协作体系落地，通过职责拆分与上下文隔离缓解长链路任务下的幻觉扩散与注意力退化。",
        [SOC, MAZI], [], ""),
    "上下文工程": ("professional", "系统设计", 3,
        "设计上下文与状态管理：决定模型每次调用看到什么、记住什么，并在多轮工具调用中保持上下文有效。",
        [MAZI, SOC], [], ""),
    "可观测与评估": ("professional", "工程方法", 4,
        "搭建 Goal-Task-Step 的 Token 级可观测体系，配合 LLM-as-Judge 建立评估校准与反馈自省闭环。",
        [MAZI, SOC], ["Token 级成本与预算审计"], ""),
    "权限治理": ("professional", "治理与安全", 3,
        "实现 ToolGateway 权限系统：RBAC + 资源标签混合模型，默认拒绝、故障安全关闭，高危操作强制人工审批。",
        [MAZI], [], ""),
    "审计与回放": ("professional", "治理与安全", 3,
        "沉淀授权决策轨迹与执行链路记录，支持审计回放，使 Agent 行为可追溯、可解释。", [MAZI], [], ""),
    "高并发与性能优化": ("professional", "性能工程", 5,
        "主导 JSON-RPC 代理网关架构重构，解决内存泄漏与长连接异常，单节点服务能力提升 5-10 倍，"
        "支撑单日流量高峰 2TB；多链数据中台接口平均响应从 200ms 降至 35ms。",
        [GW, PARA], ["吞吐提升 5-10 倍", "单日流量高峰 2TB", "接口 200ms→35ms", "前端接入成本降 60%"], ""),
    "分布式系统": ("professional", "系统设计", 4,
        "负责多链数据中台及 GraphQL BFF 服务与 K8s 水平扩容，服务 200 人规模组织的多链数据接入。",
        [PARA, GW], ["200 人组织 / 多链数据源", "K8s 水平线性扩容"], ""),
    "系统架构设计": ("professional", "系统设计", 4,
        "独立负责网关重构与多链数据中台架构设计，从架构方案到工程落地端到端交付。",
        [GW, PARA], ["单节点能力提升 5-10 倍"], ""),
    "高可用与容灾": ("professional", "系统设计", 3,
        "设计限流、熔断与降级策略，网关重构后保持零重大故障，并支持 K8s 水平扩容。",
        [GW], ["零重大故障"], ""),
    "接口与协议设计": ("professional", "系统设计", 4,
        "设计 GraphQL BFF 与 JSON-RPC 网关的接口与协议层，统一多源数据接入并降低前端接入成本 60%。",
        [PARA, GW], ["接口 200ms→35ms", "前端接入成本降 60%"], ""),
    "底层性能优化(C/SIMD)": ("professional", "性能工程", 5,
        "独立负责全闪存储编解码引擎，设计 EC 纠删码并用 AVX512 SIMD 优化，单核编解码达 4GB/s（目标 8 倍）；"
        "自研柯西矩阵求逆把复杂度从 O(k³) 降到 O(e³)，入选公司核心专利。",
        [STORE], ["单核编解码 4GB/s（目标 8 倍）", "O(k³)→O(e³)", "入选公司核心专利"], ""),
    "Prompt Engineering": ("professional", "工程方法", 3,
        "构建结构化生成约束体系，沉淀 Skill 知识库、事实资料库与范式模板，降低 token 成本并提升输出一致性。",
        [MAZI], ["降低 token 输出成本"], ""),
    "记忆管理": ("professional", "系统设计", 3,
        "设计裁决记忆机制与数据源可信度评估模型（LLM-as-Judge），形成反馈自省闭环。",
        [SOC], [], ""),
    "工具调用/Function Calling": ("professional", "系统设计", 3,
        "开发标准化 MCP 服务，统一封装多源异构数据抓取、外部 API 调用与链上交互，实现工具标准化接入。",
        [SOC, MAZI], [], ""),

    # ---------- tools ----------
    "TypeScript": ("tools", "语言", 3, "", [GW, SOC], [], ""),
    "Java": ("tools", "语言", 3, "", [SOC], [], ""),
    "Python": ("tools", "语言", 3, "", [STORE], [], ""),
    "Redis": ("tools", "中间件", 3, "", [GW, SOC], [], ""),
    "PostgreSQL": ("tools", "数据库", 3, "", [SOC], [], ""),
    "K8s": ("tools", "云与 DevOps", 3, "", [GW], [], ""),
    "MCP": ("tools", "框架", 3, "", [SOC], [], ""),

    # ---------- soft（必须带场景，最多 5 条） ----------
    "跨团队协作": ("soft", "协作", 3, "", [SOC, PARA], [], "远程团队跨时区协作，与移动端/后端/设备链路协同交付"),
    "团队管理与创业": ("soft", "管理", 3, "", [SHI], ["3 年联合创始人，万人日活"], "3 年联合创始人，主导多个产品 0→1 并管理研发团队"),
}

# 旧 category → 新 cluster 的兜底（未在 PLAN 中的技能）
FALLBACK_CLUSTER = {"Agent 与编排": "系统设计", "后端与分布式": "系统设计", "大模型": "工程方法",
                    "数据与评测": "工程方法", "治理与安全": "治理与安全", "语言与框架": "语言", "通用能力": "协作"}
LEVEL_BY_DEPTH = {"external": 2, "lead": 3, "production": 3, "demo": 1, "concept": 0}


def main():
    p = json.load(open(PROFILE, encoding="utf-8"))
    if p.get("schemaVersion") == 3:
        print("已是 v3，跳过")
        return
    shutil.copyfile(PROFILE, PROFILE + f".v{p.get('schemaVersion', 1)}.bak")

    out, unknown = [], []
    for s in p.get("skills", []):
        name = s.get("name", "")
        plan = PLAN.get(name)
        if not plan:
            unknown.append(name)
            group = "soft" if s.get("category") == "通用能力" else "professional"
            plan = (group, FALLBACK_CLUSTER.get(s.get("category"), "其他"),
                    LEVEL_BY_DEPTH.get(s.get("depth"), 3), "", list(s.get("evidence") or []), [], "")
        group, cluster, level, statement, refs, metrics, scenario = plan
        item = {
            "name": name,
            "group": group,
            "cluster": cluster,
            "evidenceLevel": level,
            "projectRefs": refs,
            "metrics": metrics,
            "statement": statement,
        }
        if group == "soft":
            item["scenario"] = scenario or s.get("note") or ""
        if s.get("artifacts"):
            item["artifacts"] = list(s["artifacts"])
        if s.get("note"):
            item["note"] = s["note"]
        out.append(item)

    p["skills"] = out
    p["skillEnvironment"] = "日常工作环境：Linux / Git / Docker / Nginx"
    p["skillGroups"] = {
        "professional": "专业技能：可验证的方法与领域能力",
        "tools": "工具与技术栈：语言 / 框架 / 数据库 / 中间件 / 云与 DevOps",
        "soft": "通用能力：通过经历 bullet 证明，确需列出时带场景且不超过 5 条",
        "credentials": "语言与资质：外语等级、证书、执照（按含金量降序）",
    }
    p["evidencePyramid"] = {
        "5": "可量化的项目结果（如 GC 800ms→120ms、挽回率 +12%）",
        "4": "规模 / 复杂度上下文（如日活 500 万、QPS 3 万、200 节点集群）",
        "3": "角色与职责（主导 / 独立负责 / 参与 3 个模块）",
        "2": "外部验证（开源 PR 被合并、竞赛名次、专利）",
        "1": "时长与频率（主力语言 3 年）",
        "0": "证书 / 课程（仅证明学过，不证明会用）",
    }
    p["schemaVersion"] = 3
    p["skillsNote"] = ("掌握度由 workbench/scoring.py 依据证据强度金字塔计算；"
                       "每条技能必须有 projectRefs（账实相符），或归入 skillEnvironment 聚合行")
    json.dump(p, open(PROFILE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    from collections import Counter
    print("已迁移 → v3（备份 profile.json.v2.bak）")
    print("  分类分布：", dict(Counter(x["group"] for x in out)))
    print("  技能簇  ：", dict(Counter(x["cluster"] for x in out)))
    if unknown:
        print("  未在映射表中、按兜底规则处理：", unknown)


if __name__ == "__main__":
    main()
