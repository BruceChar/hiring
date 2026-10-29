#!/usr/bin/env python3
"""Render a JD-tailored one/two-page resume to HTML (then Chrome prints it to PDF).

Usage: gen_resume.py <tailor.json> <outdir>
tailor.json: { items: [ {id, company, position, intent, summary, skills:[...], project_order:[...] } ] }
Fixed facts come from BASE_CONTENT; only wording/emphasis is tailored per JD (no invented experience).

Template: 布局与样式全部来自模板文件，不写死在代码里。
  查找顺序：data/resume_template.json 指定默认模板名 →
    data/templates/resume/<name>（用户添加，优先）→ workbench/templates/resume/<name>（内置）→ 内置 resume.html。
  占位符：{{HEADER}} {{SUMMARY}} {{SKILLS}} {{PROJECTS}} {{WORK}} {{EDUCATION}} {{OTHER}}
"""
import html
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
TPL_USER = os.path.join(DATA, "templates", "resume")
TPL_BUILTIN = os.path.join(ROOT, "workbench", "templates", "resume")
TPL_SETTING = os.path.join(DATA, "resume_template.json")

BASE = {
    "name": "蔡长霖",
    "phone": "18896777749",
    "email": "BruceChar@163.com",
    "city": "杭州",
    "years": "8 年工作经验",
    "github": "github.com/BruceChar/mazi",
    "education": [
        ("中国科学技术大学", "软件工程 · 硕士", "2015.09 - 2017.11"),
        ("杭州电子科技大学", "电子信息工程 · 学士", "2011.09 - 2015.06"),
        ("中科大软院机器人实验室", "研究助理（激光 SLAM / ROS）", "2016.09 - 2017.05"),
    ],
    "other": "英语六级（CET-6）· 美国 AHA 急救证书 · 浙江省大学生跆拳道锦标赛三等奖",
}

PROJECTS = {
    "harness": {
        "title": "Harness 框架 mazi",
        "meta": "个人开源项目 · github.com/BruceChar/mazi",
        "stack": "Agent Harness、Goal-Task-Step 观测、Contract 校验、RBAC 权限治理",
        "bullets": [
            "设计 Goal-Task-Step 的 Token 级可观测体系，基于 Contract 做结果可验证，支撑预算与成本审计及 Harness 策略迭代。",
            "实现 ToolGateway 权限系统：RBAC + 资源标签混合模型，默认拒绝、故障安全关闭，高危操作强制人工审批。",
            "构建结构化生成约束体系，沉淀 Skill 知识库、事实资料库与范式模板，显著降低 token 成本并提升输出一致性。",
            "设计用户思维资产沉淀系统：沉淀思维链与授权决策轨迹，与模型解耦、跨平台可迁移，反哺认知迭代。",
        ],
    },
    "socrates": {
        "title": "自动化事件预测 Agent 系统",
        "meta": "Socrates（远程）· Agent 工程师",
        "stack": "Agent Harness、TypeScript、Java、MCP、Redis、PostgreSQL",
        "bullets": [
            "主导多 Agent 协作体系落地：通过职责拆分与上下文隔离，缓解长链路任务下幻觉扩散与注意力退化。",
            "开发标准化 MCP 服务，统一封装多源异构数据抓取、外部 API 调用与链上交互，实现工具标准化接入。",
            "设计裁决记忆机制与数据源可信度评估模型（LLM-as-Judge），形成反馈自省闭环，持续提升预测准确度。",
        ],
    },
    "storage": {
        "title": "企业级全闪存储引擎",
        "meta": "北京中存超为 · 核心算法工程师",
        "stack": "C、Python、GF(2^8)、柯西矩阵 EC 纠删码、AVX512 SIMD",
        "bullets": [
            "独立负责编解码引擎，设计并实现 EC 算法，单核编解码性能达 4GB/s，为目标值的 8 倍。",
            "自研柯西矩阵求逆优化算法，复杂度由 O(k³) 降至 O(e³)，入选公司核心专利。",
        ],
    },
    "gateway": {
        "title": "高性能 JSON-RPC 代理网关",
        "meta": "杭州波卡科技 · 高级工程师",
        "stack": "TypeScript、Redis、K8s、Nginx",
        "bullets": [
            "独立负责架构重构，解决内存泄漏、长连接异常、订阅失效与扩展性问题。",
            "单节点服务能力提升 5-10 倍，支撑单日流量高峰 2TB，并支持 K8s 水平线性扩容。",
        ],
    },
}

# (公司, 岗位, 时间, 描述, 技术栈[可空])
WORK = [
    ("Socrates（AI&web3 · 200人）", "Agent 工程师 · 远程", "2024.03 - 2026.03",
     "主导事件预测平台 Agent 自动化体系的架构设计与工程落地，提升团队运营效率。",
     "Agent Harness · TypeScript / Java · MCP · Redis / PostgreSQL"),
    ("ParallelFinance（DeFi · 200人）", "高级工程师 · 远程", "2022.01 - 2023.11",
     "主导多链数据中台及 GraphQL BFF 服务，接口平均响应时间由 200ms 降至 35ms，前端接入成本降 60%。",
     ""),
    ("杭州波卡科技（数据服务 · 20人）", "高级工程师", "2021.05 - 2022.01",
     "负责 Polkadot RPC 代理服务重构与核心账户模型开发，吞吐提升 10 倍，零重大故障。",
     "TypeScript · Redis · K8s · Nginx"),
    ("杭州石匍丁科技（社交 · 20人）", "联合创始人", "2018.05 - 2021.05",
     "负责技术架构与团队管理，主导多个产品 0 到 1 落地，实现万人日活，业务资金规模 2 亿。",
     ""),
    ("北京中存超为（存储文件系统 · 50人）", "核心算法工程师 · 实习", "2017.08 - 2018.05",
     "独立设计实现 EC 算法与矩阵求逆优化方案，单核编解码带宽 4GB/s，纳入公司核心专利项目。",
     "C · Python · GF(2^8) · AVX512 SIMD"),
]


def esc(s):
    return html.escape(str(s))


def load_template():
    """默认模板名来自 data/resume_template.json；用户模板优先，回退内置。"""
    name = "resume.html"
    try:
        name = json.load(open(TPL_SETTING, encoding="utf-8")).get("default") or name
    except Exception:
        pass
    if not re.fullmatch(r"[\w\-]+\.html", name or ""):
        name = "resume.html"
    for base in (TPL_USER, TPL_BUILTIN):
        p = os.path.join(base, name)
        if os.path.exists(p):
            return open(p, encoding="utf-8").read()
    return open(os.path.join(TPL_BUILTIN, "resume.html"), encoding="utf-8").read()


def load_core_projects():
    """从 data/profile.json 收集 rank>0 的核心项目（个人项目 + 工作经历子项目），按 rank 升序，最多5个。

    返回 [{key,title,meta,stack,bullets}]（stack 为顿号连接字符串）；没有任何 rank>0 时返回 None，
    调用方回退到硬编码 PROJECTS + project_order（旧行为，保证未设置 rank 的简历不变）。
    key 稳定可逆：个人项目 p{i}，工作子项目 e{expIdx}_{subIdx}。
    """
    try:
        with open(os.path.join(DATA, "profile.json"), encoding="utf-8") as f:
            prof = json.load(f)
    except Exception:
        return None
    picked = []
    for i, p in enumerate(prof.get("projects") or []):
        r = int(p.get("rank") or 0)
        if r > 0:
            meta = " · ".join(x for x in [p.get("type") or "", p.get("period") or ""] if x)
            link = p.get("link") or ""
            if link and link not in meta:
                meta = (meta + " · " + link) if meta else link
            stack = p.get("stack") or []
            picked.append((r, "p%d" % i, p.get("name") or "", meta,
                           "、".join(stack) if isinstance(stack, list) else str(stack or ""),
                           p.get("highlights") or []))
    for ei, w in enumerate(prof.get("experiences") or []):
        for si, sp in enumerate(w.get("subProjects") or []):
            r = int(sp.get("rank") or 0)
            if r > 0:
                ctx = " · ".join(x for x in [w.get("company") or "", w.get("role") or ""] if x)
                if w.get("remote"):
                    ctx = (ctx + " · 远程") if ctx else "远程"
                period = sp.get("period") or ""
                meta = " · ".join(x for x in [ctx, period] if x)
                stack = sp.get("stack") or []
                picked.append((r, "e%d_%d" % (ei, si), sp.get("name") or "", meta,
                               "、".join(stack) if isinstance(stack, list) else str(stack or ""),
                               sp.get("highlights") or []))
    if not picked:
        return None
    picked.sort(key=lambda x: (x[0],))
    return [{"key": k, "title": t, "meta": m, "stack": s, "bullets": b}
            for (r, k, t, m, s, b) in picked[:5]]


def render(item):
    proj_order = item.get("project_order") or ["harness", "socrates", "storage", "gateway"]

    header = (
        "<header>"
        f"<h1>{esc(BASE['name'])}</h1>"
        f"<span class='intent'>求职意向：{esc(item.get('resume_title') or item.get('intent') or item['position'])}</span>"
        "<div style='flex:1'></div></header>"
        "<div class='contact'>"
        f"<span><b>{esc(BASE['phone'])}</b></span><span>{esc(BASE['email'])}</span>"
        f"<span>{esc(BASE['city'])}</span><span>{esc(BASE['years'])}</span>"
        f"<span>{esc(BASE['github'])}</span>"
        "</div>"
    )

    summary = f"<p class='summary'>{esc(item['summary'])}</p>"

    skills = "<div class='cap'>" + "".join(
        f"<p><b>{esc(label)}：</b>{esc(text)}</p>" for label, text in item["skills"]
    ) + "</div>"

    # 核心项目：profile 有 rank 数据时按 rank 渲染（固定顺序）；否则回退 project_order + 硬编码 PROJECTS
    core = load_core_projects()
    projects = "<div class='work'>"
    if core:
        for p in core:
            projects += (
                "<div class='item'>"
                f"<div class='top'><span class='ttl'>{esc(p['title'])}</span><span class='meta'>{esc(p['meta'])}</span></div>"
                f"<div class='stack'>技术栈：{esc(p['stack'])}</div>"
                "<ul>" + "".join(f"<li>{esc(b)}</li>" for b in p["bullets"]) + "</ul>"
                "</div>"
            )
    else:
        for key in proj_order:
            p = PROJECTS[key]
            projects += (
                "<div class='item'>"
                f"<div class='top'><span class='ttl'>{esc(p['title'])}</span><span class='meta'>{esc(p['meta'])}</span></div>"
                f"<div class='stack'>技术栈：{esc(p['stack'])}</div>"
                "<ul>" + "".join(f"<li>{esc(b)}</li>" for b in p["bullets"]) + "</ul>"
                "</div>"
            )
    projects += "</div>"

    work = "<div class='work'>"
    for co, role, date, desc, stack in WORK:
        work += (
            f"<div class='wrow'><span class='wco'>{esc(co)}</span>"
            f"<span class='wrole'>{esc(role)}</span><span class='wdate'>{esc(date)}</span></div>"
            f"<p class='desc'>{esc(desc)}</p>"
        )
        if stack:
            work += f"<div class='wstack'>技术栈：{esc(stack)}</div>"
    work += "</div>"

    edu = "".join(
        f"<div class='edu'><span><b>{esc(s)}</b> · {esc(d)}</span><span class='wdate'>{esc(t)}</span></div>"
        for s, d, t in BASE["education"]
    )

    other = f"<div class='other'>{esc(BASE['other'])}</div>" if BASE.get("other") else ""

    tpl = load_template()
    for k, v in (("HEADER", header), ("SUMMARY", summary), ("SKILLS", skills),
                 ("PROJECTS", projects), ("WORK", work), ("EDUCATION", edu), ("OTHER", other)):
        tpl = tpl.replace("{{%s}}" % k, v)
    return tpl


def main():
    cfg = json.load(open(sys.argv[1], encoding="utf-8"))
    outdir = sys.argv[2]
    os.makedirs(outdir, exist_ok=True)
    report = []
    for item in cfg["items"]:
        safe = re.sub(r"[^\w\u4e00-\u9fa5-]", "_", item["company"])[:20]
        pos = re.sub(r"[^\w\u4e00-\u9fa5-]", "_", item.get("resume_title") or item["position"])[:22]
        name = f"蔡长霖-{safe}-{pos}"
        html_path = os.path.join(outdir, name + ".html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(render(item))
        report.append({"id": item["id"], "company": item["company"], "position": item["position"], "html": html_path})
        print("HTML", html_path)
    json.dump(report, open(os.path.join(outdir, "render_report.json"), "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
