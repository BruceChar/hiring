#!/usr/bin/env python3
"""Seed the workbench data store from the pipeline's raw artifacts.

Reads the pipeline JSON files in the project root and writes normalised data files
into workbench/data/. Safe to re-run: it never overwrites user-edited profile/config
unless --force is given.
"""
import json
import os
import sys
import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
RAWDIR = os.path.join(DATA, "raw")
os.makedirs(DATA, exist_ok=True)
FORCE = "--force" in sys.argv


def load(name, default):
    p = os.path.join(RAWDIR, name)
    if not os.path.exists(p):
        return default
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return default


def save(name, obj, overwrite=False):
    p = os.path.join(DATA, name)
    if os.path.exists(p) and not (overwrite or FORCE):
        print(f"  keep existing {name}")
        return
    json.dump(obj, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"  wrote {name}")


now = datetime.datetime.now().isoformat(timespec="seconds")

# ---------------------------------------------------------------- profile ----
PROFILE = {
    "name": "蔡长霖",
    "title": "Agent系统工程师",
    "phone": "18896777749",
    "email": "BruceChar@163.com",
    "city": "杭州",
    "years": 8,
    "github": "https://github.com/BruceChar/mazi",
    "summary": "8 年研发经验，兼具底层系统与高并发分布式服务背景，近 2 年专注 Agent 系统工程落地，"
               "覆盖 Harness 架构、多 Agent 编排、工具调用与权限治理、上下文与记忆管理、可观测与评估校准。",
    "education": [
        {"school": "中国科学技术大学", "degree": "硕士", "major": "软件工程", "start": "2015.09", "end": "2017.11"},
        {"school": "杭州电子科技大学", "degree": "学士", "major": "电子信息工程", "start": "2011.09", "end": "2015.06"},
    ],
    "experiences": [
        {"company": "Socrates", "role": "Agent 工程师", "remote": True, "start": "2024.03", "end": "2026.03",
         "highlights": ["主导事件预测平台 Agent 自动化体系的架构设计与工程落地", "推动团队运营效率提升"]},
        {"company": "ParallelFinance", "role": "高级工程师", "remote": True, "start": "2022.01", "end": "2023.11",
         "highlights": ["主导多链数据中台及 GraphQL BFF 服务", "接口平均响应时间由 200ms 降至 35ms，前端接入成本降 60%"]},
        {"company": "杭州波卡科技", "role": "高级工程师", "remote": False, "start": "2021.05", "end": "2022.01",
         "highlights": ["负责 Polkadot RPC 代理服务重构与核心账户模型开发", "吞吐提升 10 倍，零重大故障"]},
        {"company": "杭州石匍丁科技", "role": "联合创始人", "remote": False, "start": "2018.05", "end": "2021.05",
         "highlights": ["负责技术架构与团队管理，主导多个产品 0 到 1 落地", "实现万人日活，业务资金规模 2 亿"]},
        {"company": "北京中存超为", "role": "核心算法工程师（实习）", "remote": False, "start": "2017.08", "end": "2018.05",
         "highlights": ["独立设计实现 EC 算法与矩阵求逆优化方案", "单核编解码带宽 4GB/s，纳入公司核心专利项目"]},
    ],
    "projects": [
        {"name": "Harness 框架 mazi", "type": "个人开源项目", "link": "https://github.com/BruceChar/mazi",
         "stack": ["Agent Harness", "Goal-Task-Step", "Contract 校验", "RBAC 权限治理"],
         "highlights": [
             "设计 Goal-Task-Step 的 Token 级可观测体系，基于 Contract 做结果可验证，支撑预算与成本审计及 Harness 策略迭代",
             "实现 ToolGateway 权限系统：RBAC + 资源标签混合模型，默认拒绝、故障安全关闭，高危操作强制人工审批",
             "构建结构化生成约束体系，沉淀 Skill 知识库、事实资料库与范式模板，降低 token 成本并提升输出一致性",
             "设计用户思维资产沉淀系统：沉淀思维链与授权决策轨迹，与模型解耦、跨平台可迁移",
         ]},
        {"name": "自动化事件预测 Agent 系统", "type": "公司项目", "period": "Socrates",
         "stack": ["Agent Harness", "TypeScript", "Java", "MCP", "Redis", "PostgreSQL"],
         "highlights": [
             "主导多 Agent 协作体系落地：职责拆分与上下文隔离，缓解长链路任务下幻觉扩散与注意力退化",
             "开发标准化 MCP 服务，统一封装多源异构数据抓取、外部 API 调用与链上交互",
             "设计裁决记忆机制与数据源可信度评估模型（LLM-as-Judge），形成反馈自省闭环",
         ]},
        {"name": "企业级全闪存储引擎", "type": "公司项目", "period": "北京中存超为",
         "stack": ["C", "Python", "GF(2^8)", "柯西矩阵 EC 纠删码", "AVX512 SIMD"],
         "highlights": [
             "独立负责编解码引擎，单核编解码性能达 4GB/s，为目标值的 8 倍",
             "自研柯西矩阵求逆优化算法，复杂度由 O(k³) 降至 O(e³)，入选公司核心专利",
         ]},
        {"name": "高性能 JSON-RPC 代理网关", "type": "公司项目", "period": "杭州波卡科技",
         "stack": ["TypeScript", "Redis", "K8s", "Nginx"],
         "highlights": [
             "独立负责架构重构，解决内存泄漏、长连接异常、订阅失效与扩展性问题",
             "单节点服务能力提升 5-10 倍，支撑单日流量高峰 2TB，并支持 K8s 水平线性扩容",
         ]},
    ],
    # level: 1 了解 / 2 能用 / 3 熟练 / 4 精通 / 5 权威；evidence 指向可验证的经历
    "skills": [
        {"name": "Agent Harness", "category": "Agent 与编排", "level": 4, "evidence": "mazi 开源框架"},
        {"name": "多 Agent 编排", "category": "Agent 与编排", "level": 4, "evidence": "Socrates 多 Agent 协作体系"},
        {"name": "工具调用/Function Calling", "category": "Agent 与编排", "level": 4, "evidence": "MCP 服务、ToolGateway"},
        {"name": "MCP", "category": "Agent 与编排", "level": 3, "evidence": "Socrates 标准化 MCP 服务"},
        {"name": "上下文工程", "category": "Agent 与编排", "level": 4, "evidence": "上下文隔离与 Context 管理"},
        {"name": "记忆管理", "category": "Agent 与编排", "level": 3, "evidence": "裁决记忆机制"},
        {"name": "Prompt Engineering", "category": "大模型", "level": 3, "evidence": "结构化生成约束、范式模板"},
        {"name": "可观测与评估", "category": "数据与评测", "level": 4, "evidence": "Goal-Task-Step 观测、LLM-as-Judge"},
        {"name": "权限治理", "category": "治理与安全", "level": 4, "evidence": "ToolGateway RBAC + 默认拒绝"},
        {"name": "审计与回放", "category": "治理与安全", "level": 3, "evidence": "审计回放、决策轨迹沉淀"},
        {"name": "TypeScript", "category": "语言与框架", "level": 4, "evidence": "JSON-RPC 网关、Socrates"},
        {"name": "Java", "category": "语言与框架", "level": 3, "evidence": "Socrates 技术栈"},
        {"name": "Python", "category": "语言与框架", "level": 3, "evidence": "存储引擎、工具脚本"},
        {"name": "高并发与性能优化", "category": "后端与分布式", "level": 4, "evidence": "2TB/日 网关、200ms→35ms"},
        {"name": "分布式系统", "category": "后端与分布式", "level": 4, "evidence": "多链数据中台、存储引擎"},
        {"name": "Redis", "category": "后端与分布式", "level": 3, "evidence": "网关与 Agent 系统"},
        {"name": "PostgreSQL", "category": "后端与分布式", "level": 3, "evidence": "Socrates 数据层"},
        {"name": "K8s", "category": "后端与分布式", "level": 3, "evidence": "网关水平扩容"},
        {"name": "底层性能优化(C/SIMD)", "category": "后端与分布式", "level": 4, "evidence": "AVX512 EC 编解码 4GB/s"},
        {"name": "团队管理与创业", "category": "通用能力", "level": 4, "evidence": "3 年联合创始人"},
        {"name": "跨团队协作", "category": "通用能力", "level": 4, "evidence": "多段远程协作经历"},
    ],
    "updatedAt": now,
}
save("profile.json", PROFILE)

# --------------------------------------------------------- search config ----
CONFIG = {
    "cities": [
        {"name": "杭州", "code": "101210100", "priority": 1},
        {"name": "上海", "code": "101020100", "priority": 2},
        {"name": "苏州", "code": "101190400", "priority": 3},
        {"name": "全国", "code": "100010000", "priority": 4},
    ],
    "keywords": ["Agent应用工程师", "AI Agent工程师", "大模型应用开发", "LLM应用工程师", "AI应用工程师"],
    "salary": {"min": 30, "max": 50, "unit": "K"},
    "activity_preference": ["刚刚活跃", "今日活跃", "3日内活跃"],
    "exclude_title_keywords": ["销售", "客服", "运营", "产品", "项目经理", "市场", "招聘", "实习", "培训", "讲师", "设计", "测试", "前端", "运维", "实施", "售前", "售后", "商务", "BD", "猎头", "架构师"],
    "exclude_companies": [],
    "batch_size": 10,
    "throttle": {"nav_seconds": 13, "action_seconds": 4, "job_interval_seconds": [18, 32]},
    "updatedAt": now,
}
save("search_config.json", CONFIG)

# ------------------------------------------------------------------ jobs ----
rows = load("jobs_ranked.json", [])
final = {j["id"]: j for j in load("final_jds.json", [])}
short = {s["id"]: s for s in load("shortlist.json", [])}
apps = {a["company"]: a for a in load("投递记录.json", [])}
acts = {a["id"]: a for a in load("activity.json", [])}

jobs = {}
for r in rows:
    jid = r.get("id")
    if not jid:
        continue
    jobs[jid] = {
        "id": jid,
        "company": r.get("company", ""),
        "position": r.get("name", ""),
        "city": r.get("city", ""),
        "salary": r.get("salary", ""),
        "area": r.get("area", ""),
        "experience": r.get("exp", ""),
        "degree": r.get("degree", ""),
        "industry": r.get("industry", ""),
        "scale": r.get("scale", ""),
        "skillTags": r.get("skills", []),
        "jd": "",
        "activity": "",
        "recruiter": "",
        "url": f"https://www.zhipin.com/job_detail/{jid}.html",
        "source": "api",
        "collectedAt": now,
    }
for jid, f in final.items():
    j = jobs.setdefault(jid, {"id": jid, "source": "jd-page", "collectedAt": now})
    j.update({"company": f.get("company", j.get("company", "")), "position": f.get("position", j.get("position", "")),
              "city": f.get("city", j.get("city", "")), "salary": f.get("salary", j.get("salary", "")),
              "jd": f.get("jd", ""), "url": f"https://www.zhipin.com/job_detail/{jid}.html"})
for jid, a in acts.items():
    if jid in jobs:
        jobs[jid].update({"activity": a.get("activity", ""), "recruiter": a.get("boss", ""), "contacted": a.get("contacted", False)})

for jid, j in jobs.items():
    j["site"] = None
    j["matchScore"] = None
    if j["position"] and j["company"]:
        j["uid"] = jid
jobs_list = sorted(jobs.values(), key=lambda x: (x.get("city", ""), x.get("company", "")))
save("jobs.json", jobs_list, overwrite=True)

# ---------------------------------------------------------- applications ----
records = load("投递记录.json", [])
replies = {r["company"]: r for r in load("replies.json", [])}
review = {r["company"]: r for r in load("resume_review.json", {}).get("reviews", [])}
val = {v["company"]: v for v in load("validation.json", [])}

status_map = {}
applications = []
for rec in records:
    comp = rec.get("company", "")
    rep = replies.get(comp, {})
    if rep.get("replied") == "yes":
        st = "已回复"
    elif rec.get("resume") == "image_sent":
        st = "简历已发"
    elif rec.get("greet") in ("sent", "uncertain", "already_contacted"):
        st = "已沟通"
    else:
        st = "未沟通"
    status_map[comp] = st
    timeline = []
    if rec.get("at"):
        timeline.append({"at": rec["at"], "event": "打招呼", "note": rec.get("greet", "")})
    if rec.get("resumeAt"):
        timeline.append({"at": rec["resumeAt"], "event": "发送定制简历", "note": "高清简历图"})
    if rep.get("replied") == "yes":
        timeline.append({"at": now, "event": "HR 回复", "note": rep.get("snippet", "")[:120]})
    applications.append({
        "id": rec.get("id", comp),
        "company": comp,
        "position": rec.get("position", ""),
        "city": rec.get("city", ""),
        "salary": rec.get("salary", ""),
        "recruiter": next((c[1] for c in load("chats_final.json", {}).get("chats", []) if comp in " ".join(c)), ""),
        "activity": next((a.get("activity", "") for a in acts.values() if a.get("company") == comp), ""),
        "greetedAt": rec.get("at", ""),
        "resumeSentAt": rec.get("resumeAt", ""),
        "resumeType": "定制简历图（首次投递）",
        "validation": "通过" if val.get(comp, {}).get("passed") else "未校验",
        "review": review.get(comp, {}).get("verdict", "未复核"),
        "status": st,
        "timeline": timeline,
    })
save("applications.json", applications, overwrite=True)

# -------------------------------------------------------------- feedback ----
feedback = []
for a in applications:
    rep = replies.get(a["company"], {})
    if rep.get("replied") == "yes":
        feedback.append({
            "applicationId": a["id"],
            "company": a["company"],
            "at": now,
            "type": "reply",
            "content": rep.get("snippet", "")[:200],
            "signal": "positive",
            "action": "HR 索要附件简历：可在对方回复后发送定制 PDF，或直接确认发送",
        })
save("feedback.json", feedback, overwrite=True)

print("seed done ->", DATA)
