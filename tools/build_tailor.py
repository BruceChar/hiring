#!/usr/bin/env python3
"""Build per-JD tailored resume content (intent / summary / skills / project order)."""
import json

S = {
 "AI Agent：Harness 架构设计、Goal-Task-Step 观测、Context/记忆管理、多 Agent 编排与工具调用（MCP）",
 "系统工程：高并发分布式服务架构、性能剖析与优化（响应 200ms→35ms、吞吐提升 10 倍）、高可用与容灾",
 "工程素养：Java/TypeScript/Python、Redis/PostgreSQL/K8s、3 年创业团队管理与跨团队协作",
}

ITEMS = [
 dict(company="滴滴出行", position="AI Agent工程师", id="21bc38f3c00fbafe0nJ729u-GVBW",
      intent="AI Agent 工程师（滴滴国际金融）",
      summary="8 年后端与分布式系统经验，近 2 年专注 AI Agent 系统工程落地。具备扎实的 Java/TypeScript 工程能力与高并发服务架构经验（支撑单日流量高峰 2TB、吞吐提升 10 倍），主导过事件预测 Agent 平台从架构设计到上线的完整落地，熟悉 Agent 编排、工具调用与上下文管理，能够结合金融业务场景快速完成方案设计到工程交付。",
      skills=[
        "AI Agent：Harness 架构设计、多 Agent 协作与工具调用（MCP）、上下文隔离与任务编排",
        "系统工程：Java/TypeScript 高并发服务、分布式系统设计、性能调优（接口 200ms→35ms）、高可用容灾",
        "业务落地：金融/支付类流程拆解与工程化落地、跨团队协作、3 年创业团队管理经验",
      ],
      project_order=["socrates","gateway","harness","storage"]),

 dict(company="蚂蚁集团", position="网商银行-AI应用工程-Agent研发", id="3bdfab36539ca6c30nJ73965EVdX",
      intent="网商银行 AI 应用工程 / Agent 研发",
      summary="8 年后端与分布式系统经验，近 2 年专注 Agent Infra 与 Agent 系统工程落地。主导 Agent Harness 体系建设：Goal-Task-Step 可观测、Contract 结果可验证、ToolGateway 权限治理（RBAC+资源标签、默认拒绝、高危操作人工审批）与审计回放，具备构建高可用 Agent 运行时、权限治理与全链路可观测能力的端到端实践。",
      skills=[
        "Agent Infra：Agent Runtime 与执行链路、Context 管理、多 Agent 编排、工具/技能体系、失败恢复",
        "治理与可观测：权限治理（RBAC/资源标签/默认拒绝）、审计回放、Token 级成本与预算审计、Evaluation 校准",
        "工程底座：高并发分布式服务、Java/TypeScript/Python、Redis/PostgreSQL、K8s 水平线性扩容",
      ],
      project_order=["harness","socrates","gateway","storage"]),

 dict(company="连连支付", position="AI Agent 工程师", id="4ec4476364a2c87f0nJ92t6_EltR",
      intent="AI Agent 工程师（支付业务智能体）",
      summary="8 年后端研发经验，近 2 年专注 AI Agent 与多 Agent 协作体系落地。擅长把复杂业务链路拆解为 Agent 可执行的原子任务与协作链路，主导过 Agent Harness（编排、工具调用、上下文隔离、权限治理、结果可验证）与事件预测 Agent 平台的 0→1 落地，具备 TypeScript/Java 全栈工程能力，熟悉金融/DeFi 类场景的流程自动化与规范化落地。",
      skills=[
        "AI Agent：任务拆解与多 Agent 协作链路、工具调用（MCP）、上下文与记忆管理、结果可验证",
        "全栈工程：TypeScript/Java/Python、前后端联调与模块集成、Redis/PostgreSQL、性能优化",
        "治理落地：权限与合规边界设计（RBAC、默认拒绝、人工审批）、审计日志与结果追溯",
      ],
      project_order=["socrates","harness","gateway","storage"]),

 dict(company="珀莱雅", position="智能体应用工程师（Agent 全栈方向）", id="f45494b66593a1400nN72tq0FltW",
      intent="智能体应用工程师（Agent 全栈方向）",
      summary="8 年研发经验，近 2 年专注智能体应用落地。主导 Agent Harness 体系建设，覆盖任务编排、工具调用、知识库与事实资料库沉淀、人机协作工作流；设计 ToolGateway 权限系统（RBAC+资源标签、人工确认、调用日志与结果追溯）与 Goal-Task-Step 可观测体系，具备 TypeScript 全栈开发与多系统（知识库/文档/业务系统）集成能力。",
      skills=[
        "智能体应用：对话与任务流程设计、工具调用、知识检索与上下文组织、用户反馈闭环",
        "工作流与治理：人机协作工作流编排、权限边界控制、敏感数据保护、调用日志与结果追溯",
        "全栈开发：TypeScript/Python、接口与权限控制、异常处理与日志、可复用组件与模板沉淀",
      ],
      project_order=["harness","socrates","gateway","storage"]),

 dict(company="腾讯", position="大模型应用开发专家", id="74fb9444fdbdc25e03B-3dS7FVVT",
      intent="大模型应用开发专家",
      summary="8 年后端研发经验，近 2 年专注大模型应用与 Agent 系统工程。具备扎实的 Java/TypeScript 工程落地能力与大型系统架构经验，主导过 Agent 平台从方案设计到上线（Prompt 模板与结构化生成约束、工具调用、知识库检索与上下文组织），擅长将大模型能力融入真实业务流程，并沉淀可复用组件与最佳实践。",
      skills=[
        "大模型应用：Prompt 工程与结构化生成约束、知识库/事实资料库建设、检索与上下文组织",
        "Agent 工程：多 Agent 编排、工具调用、执行链路可观测与效果评估",
        "工程实现：Java/TypeScript/Python、高并发服务架构、Redis/PostgreSQL、性能与稳定性优化",
      ],
      project_order=["harness","socrates","gateway","storage"]),

 dict(company="昊美科技", position="大模型应用开发", id="104524e67858fb820nN93NW0FFFX",
      intent="大模型应用开发工程师",
      summary="8 年研发经验，近 2 年专注大模型应用与 Agent 系统落地。负责 Skill 知识体系与事实资料库构建、结构化生成约束与 Prompt 模板沉淀，主导多智能体编排与工具调用体系；具备评测集建设、badcase 归因与 LLM-as-Judge 质量闭环的实践经验，熟悉 Python/TypeScript 工程化落地、缓存与推理成本优化。",
      skills=[
        "大模型应用：Prompt 工程、知识库/资料库构建、检索与上下文组织、结构化输出约束",
        "Agent 与评测：工具调用/多智能体编排、评测集建设与 badcase 归因、LLM-as-Judge 质量闭环",
        "工程能力：Python/TypeScript、LLM 调用链路与缓存/成本优化、Redis/PostgreSQL、可复用组件输出",
      ],
      project_order=["harness","socrates","gateway","storage"]),

 dict(company="深圳图灵集市科技", position="全栈开发工程师（LLM应用方向）", id="f62d32b9aaa45db90nN52d67FFFU",
      intent="全栈开发工程师（LLM 应用方向）",
      summary="8 年研发经验，其中后端与分布式系统 6 年：主导过支撑单日 2TB 流量的 JSON-RPC 代理网关重构（单节点能力提升 5-10 倍、K8s 水平扩容）与多链数据中台（接口 200ms→35ms）。近 2 年投入 LLM 应用与 Agent 系统，熟悉 Agent 开发范式与 Prompt 工程化落地，具备大规模高并发系统设计、容量规划、性能调优与线上故障止损经验，并有 3 年创业团队管理经验。",
      skills=[
        "LLM 应用：Agent 开发范式、Prompt 工程化落地、工具调用、知识库检索与上下文组织",
        "后端与高并发：TypeScript/Java/Python、PostgreSQL/Redis、大规模高并发系统设计、容量规划与性能调优",
        "综合：线上故障紧急止损与稳定性治理、研发流程优化、3 年创业团队管理",
      ],
      project_order=["gateway","socrates","harness","storage"]),

 dict(company="杭州纳速码科技", position="AI Agent 工程师", id="fee0eb3063bce3f50nZ42dm1EFZW",
      intent="AI Agent 工程师（执行系统方向）",
      summary="8 年研发经验，近 2 年专注 Agent 执行系统落地。主导实现任务规划、上下文与记忆管理、工具与技能体系（Skill 知识库、事实资料库）等核心模块，打通「输入 → 意图理解 → action → 执行 → 结果返回」完整链路；对真实用户场景下的失败重试、边界处理与结果可验证有工程化实践，熟练使用 Python/TypeScript。",
      skills=[
        "Agent 系统：任务规划、memory/上下文管理、execution 链路、tool system 与 skill system 设计",
        "可靠性：失败重试与边界处理、结果可验证（Contract）、执行链路 Trace 与回放",
        "工程能力：Python/TypeScript、真实业务流程集成、LLM 调用编排、成本与稳定性优化",
      ],
      project_order=["harness","socrates","gateway","storage"]),

 dict(company="上海未见之境", position="AI agent工程师", id="5aee539d9b9d0f770nJ539S4FVVS",
      intent="AI Agent 工程师",
      summary="8 年研发经验，近 2 年专注 Agent 系统工程。主导构建 Agent Harness：负责上下文与状态管理（决定模型每次调用看到什么、记住什么）、工具集与 ToolGateway、多步任务编排及失败恢复与降级，并落地 Goal-Task-Step 可观测与可回放、Contract 可验证的评测与质量闭环，擅长把零散 badcase 收敛为可度量、可持续优化的指标。",
      skills=[
        "Agent 架构：上下文/状态管理、工具集设计与工具网关、多步任务编排与稳定性（失败/重试/降级）",
        "评测与可观测：评测集设计、badcase 归因、Goal-Task-Step 观测、决策可追溯可回放可解释",
        "工程能力：TypeScript/Python/Java、高并发分布式系统、Redis/PostgreSQL、成本与性能优化",
      ],
      project_order=["harness","socrates","gateway","storage"]),

 dict(company="京东物流", position="AI Agent全栈研发", id="6439c5f013c448240nJ-3tS4EFNX",
      intent="AI Agent 全栈研发（工业场景）",
      summary="8 年研发经验，兼具底层系统（C/AVX512 性能优化、EC 纠删码算法）与高并发分布式服务背景，近 2 年专注 Agent 系统工程。主导 Agent 全链路可观测（Goal-Task-Step、Trace、评测校准）、工具调用与领域知识库建设，熟悉 Python/TypeScript、K8s 与工业级高可靠系统的性能与稳定性保障。",
      skills=[
        "Agent 系统：任务规划与自动化执行、Function Calling/工具调用、知识库检索与上下文工程",
        "可观测与评估：全链路监控/日志/Trace、评估校准闭环、失败归因与持续迭代",
        "工程底座：Python/TypeScript/C、K8s/Docker、Redis/PostgreSQL、底层性能优化与高可靠保障",
      ],
      project_order=["harness","socrates","storage","gateway"]),
]

out = {"items": []}
for it in ITEMS:
    out["items"].append({
        "id": it["id"], "company": it["company"], "position": it["position"],
        "intent": it["intent"], "resume_title": "Agent系统工程师", "summary": it["summary"],
        "skills": [("AI Agent" if s.startswith("AI Agent") else s.split("：")[0], s.split("：", 1)[1]) for s in it["skills"]],
        "project_order": it["project_order"],
    })
os.makedirs('data', exist_ok=True)
json.dump(out, open(os.path.join('data', 'tailor.json'), 'w'), ensure_ascii=False, indent=1)
print("tailor.json written:", len(out["items"]), "items")
