#!/usr/bin/env python3
"""把 profile.skills 从主观 level(1-5) 迁移到证据化字段（一次性脚本，可重复运行）。

新字段：
  evidence  : ["项目名/公司名", ...]   —— 从自己的工作/项目经历里勾选，可核对
  depth     : concept|demo|production|lead|external —— 做到了哪一步（行为事实）
  artifacts : ["github.com/...", "公司核心专利", ...] —— 可点开/可验证的产出
  lastUsed  : "2026"                   —— 最近一次使用
  note      : 原来自述的补充说明（保留，不计分）
"""
import json
import os
import shutil
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILE = os.path.join(ROOT, "data", "profile.json")

LEVEL2DEPTH = {1: "concept", 2: "demo", 3: "production", 4: "lead", 5: "external"}

# 基于原始履历人工核对过的关联（比模糊匹配更准）
LINKS = {
    "Agent Harness": (["Harness 框架 mazi", "自动化事件预测 Agent 系统"], "lead", ["github.com/BruceChar/mazi"], "2026"),
    "多 Agent 编排": (["自动化事件预测 Agent 系统", "Harness 框架 mazi"], "lead", [], "2026"),
    "工具调用/Function Calling": (["Harness 框架 mazi", "自动化事件预测 Agent 系统"], "lead", [], "2026"),
    "MCP": (["自动化事件预测 Agent 系统"], "production", [], "2026"),
    "上下文工程": (["Harness 框架 mazi", "自动化事件预测 Agent 系统"], "lead", [], "2026"),
    "记忆管理": (["自动化事件预测 Agent 系统"], "production", [], "2026"),
    "Prompt Engineering": (["Harness 框架 mazi"], "production", [], "2026"),
    "可观测与评估": (["Harness 框架 mazi", "自动化事件预测 Agent 系统"], "lead", [], "2026"),
    "权限治理": (["Harness 框架 mazi"], "lead", [], "2026"),
    "审计与回放": (["Harness 框架 mazi"], "production", [], "2026"),
    "TypeScript": (["高性能 JSON-RPC 代理网关", "自动化事件预测 Agent 系统"], "lead", [], "2026"),
    "Java": (["自动化事件预测 Agent 系统"], "production", [], "2026"),
    "Python": (["企业级全闪存储引擎"], "production", [], "2018"),
    "高并发与性能优化": (["高性能 JSON-RPC 代理网关", "ParallelFinance", "企业级全闪存储引擎"], "lead", [], "2023"),
    "分布式系统": (["ParallelFinance", "高性能 JSON-RPC 代理网关"], "lead", [], "2023"),
    "Redis": (["高性能 JSON-RPC 代理网关", "自动化事件预测 Agent 系统"], "production", [], "2026"),
    "PostgreSQL": (["自动化事件预测 Agent 系统"], "production", [], "2026"),
    "K8s": (["高性能 JSON-RPC 代理网关"], "production", [], "2022"),
    "底层性能优化(C/SIMD)": (["企业级全闪存储引擎"], "lead", ["公司核心专利：EC 矩阵求逆优化"], "2018"),
    "团队管理与创业": (["杭州石匍丁科技"], "lead", [], "2021"),
    "跨团队协作": (["Socrates", "ParallelFinance", "杭州石匍丁科技"], "lead", [], "2026"),
    "系统架构设计": (["高性能 JSON-RPC 代理网关", "ParallelFinance"], "lead", [], "2023"),
    "高可用与容灾": (["高性能 JSON-RPC 代理网关"], "production", [], "2022"),
    "接口与协议设计": (["ParallelFinance", "高性能 JSON-RPC 代理网关"], "lead", [], "2023"),
}


def main():
    p = json.load(open(PROFILE, encoding="utf-8"))
    if not p.get("skills"):
        print("没有 skills，跳过")
        return
    if all("depth" in s for s in p["skills"]):
        print("已是新格式，跳过")
        return

    shutil.copyfile(PROFILE, PROFILE + ".v1.bak")
    for s in p["skills"]:
        name = s.get("name", "")
        old_note = s.get("evidence") if isinstance(s.get("evidence"), str) else None
        if name in LINKS:
            ev, depth, arts, last = LINKS[name]
        else:
            ev, arts, last = [], [], str(datetime.now().year)
            depth = LEVEL2DEPTH.get(int(s.get("level") or 1), "concept")
        s["evidence"] = ev
        s["depth"] = depth
        s["artifacts"] = arts
        s["lastUsed"] = last
        if old_note:
            s["note"] = old_note          # 原来的自述说明保留，不计分
        s.pop("level", None)

    p["schemaVersion"] = 2
    p["skillsNote"] = "掌握度由 scoring.py 依据 evidence/depth/artifacts/lastUsed 计算，不做主观自评"
    json.dump(p, open(PROFILE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"已迁移 {len(p['skills'])} 项技能 → 证据化字段（备份 profile.json.v1.bak）")


if __name__ == "__main__":
    main()
