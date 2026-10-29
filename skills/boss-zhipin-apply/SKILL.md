---
name: boss-zhipin-apply
description: 通用求职投递流程（不限岗位族）。开跑前先用「对话」或「网页工作台」确认城市/关键词/薪资等参数，再依次完成：采集岗位 → 技能树与差距分析 → 按 JD 定制简历 → 双重校验门禁 → 打招呼并送达简历 → 记录与反馈评估。内含绕过 BOSS直聘 反自动化检测的浏览器控制通道、简历图清晰度处理、去重与节流等实战对策，以及与 Agent 解耦的本地工作台（数据文件 + HTTP API + CLI）。
---

# 通用求职投递流程

> 本 Skill **不绑定任何岗位族、城市或薪资**。所有可变参数在每轮开跑前确认。
> 岗位族相关的知识（技能词库、学习方案）放在工作台的 `workbench/lexicon.json`，换行业只换词库。

```
<项目根>/
├── AGENTS.md                  ← 任何 Agent 的入口（先读它）
├── workbench/                 ← 应用代码（零依赖，可脱离用户数据迁移）
│   ├── server.py / cli.py / engine.py / selftest.py
│   ├── cities.json            城市码字典（用户只填城市名）
│   ├── lexicon.json           技能词库（按岗位族可替换）
│   ├── API.md                 Agent 交互契约
│   └── web/                   前端（无构建、无 CDN）
├── skills/boss-zhipin-apply/  本文件
├── tools/                     浏览器控制与简历生成脚本
└── data/                      ★ 用户数据（可单独迁移/备份）
    ├── profile.json  search_config.json  strategy.json
    ├── jobs.json  applications.json  feedback.json
    ├── skills_tree.json  gap_analysis.json
    ├── resumes/{html,pdf,img}/  exports/  raw/  templates/
```

---

## 第 0 步｜确认本轮参数（**每次都必须做**）

参数包括：**目标城市（只问城市名）、关键词、薪资区间、批次数量、招聘类型（校招/社招，可选）、活跃度偏好、投递策略**。

**开工前先检查数据完备度**：
```bash
python3 workbench/cli.py onboarding     # 退出码 1 = 有缺失
```
`onboarding.items[].ask` 就是该向用户提的问题；缺什么问什么，写入对应文件后再开工。
不要凭空替用户编履历，也不要让用户填城市码（只问城市名）。

**方式 A —— 对话确认**（没有网页时）：
直接问用户，或先 `python3 workbench/cli.py status` 查看上轮参数再确认是否沿用。

**方式 B —— 网页确认（推荐）**：
```bash
python3 workbench/server.py          # → http://127.0.0.1:8787
```
在「搜岗配置」页填写/勾选 → 点「保存配置」→ 点「**生成 Agent 任务简报**」→ 复制简报作为本轮任务书。
简报也可直接取：`GET /api/brief` 或 `python3 workbench/cli.py brief`。

简报里已包含：候选人履历位置、城市与城市码、关键词、薪资区间、排除词、节流参数、去重与校验要求、Agent 交互方式。**拿到简报后严格按简报执行。**

> ⚠️ 不要让用户重复描述履历：履历是长期资产，存在 `data/profile.json`，每次投递都复用它。

---

## 第 1 步｜采集岗位

按关键词 × 城市抓取岗位列表（BOSS直聘 示例）：
- 列表页：`https://www.zhipin.com/web/geek/jobs?query=<关键词>&city=<城市码>`
  （城市码**不用问用户**：`workbench/cities.json` 已内置 46 个常用城市，`GET /api/cities` 可查；
  未收录的城市由你打开 BOSS 切换城市后从地址栏读 `city=` 补进字典）
- 解析 `.job-card-wrap`（岗位名 / 公司 / 区域 / 经验 / 学历）
- 抓完写入岗位池：`POST /api/jobs` 或 `python3 workbench/cli.py jobs import new_jobs.json`

**注意**
- 列表页的薪资数字被平台做了**字体混淆**，取到的是乱码；**详情页可正常读取**，一切以详情页为准。
- 不要高频调平台内部 XHR：连续几次就会返回「环境异常」并把你跳到安全校验页。优先用页面导航。
- 每个岗位都要抓**招聘者活跃度**（刚刚活跃 / 今日活跃 / 3日内活跃 …），它是回复率最强的预测因子。

## 第 2 步｜筛选与去重

```bash
python3 workbench/cli.py pending --limit 10     # 已按配置过滤 + 排除已投递
```
硬规则：
1. 薪资区间有重叠才保留；2. 城市按优先级；3. 活跃度高的优先；4. 按招聘类型筛选（`recruit_types`，校招/社招，空=不限）；
5. **去重**：比对 `data/applications.json`，同公司同岗位不得重复投递；
6. 详情页按钮文案 `立即沟通` = 未联系、`继续沟通` = 已联系 → 后者跳过。

## 第 3 步｜抓取 JD 并回写

逐个打开详情页取职位描述全文，回写 `jobs.json` 的 `jd` 字段。
抓完**必须校验标题与目标一致**，否则会把上一页内容当过页结果。

## 第 4 步｜技能树与差距分析（决定简历写什么）

```bash
python3 workbench/cli.py analyze      # 或点网页右上角「重新分析技能树」
```
产出两份数据：网页「技能树」页展示**目标岗位覆盖率视角**（每个技能被岗位池中多少岗位要求），
「差距与学习」是其子页；个人证据明细（证据句 / 量化结果 / 项目落点 / 可验证产出）在
「搜岗 → 点击岗位 → 右侧匹配分析面板」中查看：
- `data/skills_tree.json`：把岗位池按技能词库聚合，得到**覆盖率**（提到该技能的岗位数 ÷ 有技能标签或 JD 的岗位数）并据此分档
  （≥40% 必备 / ≥20% 常见 / ≥8% 加分 / 其余少见）；**不使用人工指定的"重要度"**；
- `data/gap_analysis.json`：缺口排序 + **学习方案**（为什么重要 / 学习重点 / 步骤 / 资源 / 周期 / 验证方式）+ 已有优势。

**怎么用**：
- 技能区按**四大分类**组织（professional 专业技能 / tools 工具与技术栈 / soft 通用能力 / credentials 语言与资质），
  用**证据强度金字塔**标注（★★★★★ 量化结果 → ☆ 证书课程），由 `workbench/scoring.py` 算出证据分并展示构成；
- **账实相符**：每条技能必须有 `projectRefs` 落点（`workbench/skill_links.py` / `cli.py links` 做 R1–R4 断链检测，
  断链按「补证据 → 降格表述 → 删除」修复，R4 真实性问题强制删除）；
- 简历写法：核心技能 3-5 条完整证据句 + 指向项目；次要技能聚合为一行（如「日常工作环境：Docker / Nginx / ES」）；
- 简历的「核心能力」优先写**高覆盖率且证据分高**的技能（优势项）；
- 面试话术围绕优势项组织；
- 高优先级缺口 = 下一阶段的学习与项目计划，也是下一批投递选岗的依据；
- 换行业时只替换 `workbench/lexicon.json`，其余不动。

## 第 5 步｜生成定制简历

- **标题统一**取 `profile.title`（如「Agent系统工程师」），不要写 JD 里的具体头衔（全栈/专家…）。
- 可定制：个人简介、核心能力侧重、项目顺序；**不得编造**履历之外的技术栈与数字。

### 5A. LLM 按 JD 定制（生产路径，推荐）

```bash
LLM_API_KEY=sk-xxx LLM_MODEL=deepseek-chat python3 tools/agent_tailor.py <job_id>
# 任意 OpenAI 兼容网关：LLM_BASE_URL 默认豆包方舟 https://ark.cn-beijing.volces.com/api/v3
```

- 读岗位 JD + 履历固定事实 + 技能树侧重 → LLM 产出 tailor 条目（固定 schema）→
  **后校验**（标题 / 公司名 / 数字 / 占位符，逐项比对固定事实，编造即拒绝不写盘）→
  合并 `data/tailor.json` → 自动渲染 HTML → Chrome 出 PDF → 高清 PNG → validate 门禁。
- 退出码契约：`0`=完成且门禁过 / `1`=LLM 输出未过后校验 / `2`=LLM API 失败 / `3`=参数或数据缺失 / `4`=出图或门禁失败。
- 离线通道（跳过 LLM）：`python3 tools/agent_tailor.py <job_id> --from-json item.json`；
  调试用 `--dry-run`（校验不写盘）、`--no-run`（写盘不出图）。
- 环境变量：`LLM_API_KEY` / `LLM_MODEL` / `LLM_BASE_URL`。事件写入 `data/logs/agent-events.jsonl`。
- 渲染链路（避免中文丢字与图片发虚）：
  1. 结构化内容 → A4 HTML（**显式白底**，`tools/gen_resume.py`）
  2. Chrome `Page.printToPDF` 出 PDF（`tools/print_pdf.mjs`，需 CDP 9222；无实例时用
     `--headless=new --remote-debugging-port=9222 --user-data-dir=<独立目录>` 拉起打印实例）
  3. 高 DPI 光栅化为 PNG（`tools/build_images.py`，A4@260dpi ≈ 2152×3041），**Pillow 合成白底去 alpha**
- ⚠️ 用 `sips` 之类从 PDF 转 PNG 会按 72dpi 先栅格再放大 → 图必糊；PDF 页面背景透明 → PNG 带 alpha，在深色聊天背景上是透明的。

### 5B. 脚本/人工定制（保留路径）

`tools/build_tailor.py` 的预写条目或直接编辑 `data/tailor.json`（字段同上），改完跑
`python3 tools/gen_resume.py data/tailor.json data/resumes/html` + print_pdf + build_images + validate。

### 5C. 核心能力区写作规范（**必照此写**）

核心能力区是 ATS 关键词命中密度最高的地方，也是 HR 扫简历前 6 秒看的区块。写法硬约束：

1. **每条 = 能力域标签 + 一句话方法论**，形如 `RAG 知识工程：分层事实模型治理、审批状态机与时效控制、混合检索双路召回、动态事实双轨核验——构建从入库治理到发布门禁的完整防幻觉链路`。
2. **不放任何数字**（性能毫秒、倍率、百分比、用户量）——量化结果全部下沉到项目 bullet，核心能力区只做方法论与关键词索引。
3. **ATS 关键词必须自然嵌入句子**（不要堆在一行），例如 RAG、Multi-Agent、Function Calling、pgvector、Agent Harness、LLM-as-Judge、Goal-Task-Step、Contract、ToolGateway、K8s、RBAC、CI/SIMD……按目标岗位 JD 高频词调整。
4. 用顿号串联并列方法论，末尾用破折号「——」收一句价值/成果定位；**不要 bullet 展开、不要括号里塞数字**。
5. 一个能力域一行（系统设计/工程方法/性能工程/治理与安全/……），整区控制在 6-8 行，占第一页不超过 1/3。

**标准范例**（Agent 系统工程师岗位）：

```
▸ 核心能力
RAG 知识工程：分层事实模型治理、审批状态机与时效控制、混合检索双路召回、动态事实双轨核验——构建从入库治理到发布门禁的完整防幻觉链路
Agent 工程：多 Agent 编排（职责拆分与上下文隔离）、Function Calling 标准化、自研 Agent Harness（Goal-Task-Step 可观测 + Contract 可验证 + ToolGateway 权限治理），将概率性推理收束为可回滚、可审计的行动序列
上下文与记忆：上下文与状态管理、裁决记忆机制、LLM-as-Judge 可信度评估，形成反馈自省闭环
评测驱动迭代：分层黄金集 + 红线负样本 + 回归门禁，以评测拦截劣化发布、驱动配置与模型迭代
系统架构与高可用：高并发网关重构、多链数据中台、K8s 水平扩容，限流/熔断/降级设计
底层性能优化：C/SIMD 指令级优化、编解码引擎、算法复杂度优化（具公司核心专利）
治理与安全：RBAC + 资源标签混合权限、审计回放、红线规则代码化
```

> 切岗位时只换能力域标签与关键词组合，保持「标签：方法论——价值定位」句式不变。
> 渲染时 `render_resume_html` 会自动按 cluster 合并成紧凑段落（技能名粗体 + statement 截到 35 字），
> 写 profile 时按上述规范写 statement，PDF 输出即符合此样式。


## 第 6 步｜投递前校验门禁（**未通过不得投递**）

两层，缺一不可：
1. **确定性校验**：图片存在 / `RGB` 无 alpha / 宽度 ≥2000px / 四角纯白 / 标题统一 / 必要板块齐全 / 联系方式齐全 / 无占位符。
2. **独立 Agent 复核**：把简历纯文本 + JD 交给一个**独立子 Agent**，对照履历事实基准逐条比对，专抓三类问题：
   - 基准外技术栈（写了自己没有的框架/技术）；
   - 虚构数字与体量（把 JD 里的「百万级用户系统」搬进自己简历）；
   - 标题不统一、板块缺失。
   结论写入 `data/applications.json` 对应记录的 `review` 字段，**只有 pass 才投递**。

> 实测教训：关键词存在性检查会 10/10 全绿，而独立复核能抓出「编造 RAG 经历」「虚构百万级体量」这类真问题。两者不可互相替代。

## 第 7 步｜打招呼并送达简历

1. 详情页点「立即沟通」→ 校验出现「已发送」且按钮变「继续沟通」。
2. **平台限制：对方回复前不能发附件简历（PDF）**（按钮提示「求简历：双方回复后可用」）。
   → 即时送达用**高清简历图**：进聊天页 → 确保切到「全部」筛选 → 点目标会话 → 点图片按钮 → 拦截文件选择器注入 PNG（选完即自动发送）。
   → 等 HR 回复后，「发简历」解锁，再补发真正的 PDF 附件。
3. 节奏：导航 12–16s、动作间 4–6s、岗位间隔 15–35s 随机。单批建议 ≤10 家。

## 第 7.5 步｜遵守投递策略（硬约束）

`data/strategy.json` 定义执行规则，必须逐条遵守：
```bash
python3 workbench/cli.py strategy          # 查看
python3 workbench/cli.py schedule --cron   # 生成 crontab（无人值守）
```
- **时间窗**：只在 `time_windows` 内操作；
- **数量**：每次 ≤ `batch_size`，每日 ≤ `daily_limit`；
- **人工确认**：`require_approval=true` 时先把名单给用户确认再投；
- **暂停条件**：连续 `pause_after_consecutive_no_reply` 家无回复、或回复率低于 `min_reply_rate` → 暂停复盘；
- **去重/冷却**：同公司 `per_company_cooldown_days` 天内不重复，最多 `max_per_company` 次；
- **风控**：`stop_on_risk_control=true` 时，一出现异常立即停止本轮。

## 第 8 步｜记录与反馈评估

每投一家立即记录（**不要攒到最后**）：
```bash
python3 workbench/cli.py app add --company X --position Y --city 杭州 --salary 30-45K --status 已沟通
```
收到回复/面试/拒绝就用反馈接口，状态会自动推进：
```bash
python3 workbench/cli.py feedback add --company X --type reply --content "HR 索要附件简历" --signal positive
# type: reply→已回复  interview→约面试  interviewed→已面试  offer→已offer  reject→已拒绝
```
网页「概览」看漏斗与转化率，「投递与反馈」看状态与时间线。评估口径：
投递转化率 / 简历送达率 / **回复率** / **面试转化率**，并按**城市、活跃度、薪资区间、简历版本**分组对比，
用数据决定下一批的关键词与选岗策略（例如「刚刚活跃的回复率显著更高 → 下批只投刚刚活跃」）。

---

## 工作台：三种 Agent 交互方式（同一份数据）

```bash
python3 workbench/server.py        # ① HTTP API + 网页  → 契约见 workbench/API.md
python3 workbench/cli.py status    # ② CLI（无需服务在跑）
# ③ 直接读写 data/*.json（最稳，零耦合）
```
关键端点：`/api/profile`(GET/PUT)、`/api/config`(GET/PUT)、`/api/jobs`(GET/POST)、
`/api/applications`(GET/POST/PATCH)、`/api/feedback`(GET/POST)、`/api/skills`、`/api/gap`、
`/api/analyze`、`/api/stats`、`/api/events`、`/api/brief`、`/api/export`、`/api/import`。

**调度器接入与事件日志**：run-batch 退出码契约、事件日志用法统一见项目根
`AGENTS.md` 第 6 节「Agent 接入声明」；接手任务前先读最近事件做断点恢复。

**迁移**：
- 迁移应用 → 拷 `workbench/ skills/ tools/ AGENTS.md README.md`；
- 迁移数据 → 拷 `data/`（含履历、策略、岗位池、投递记录、简历产物）；
- 二者可分别迁移；`data/` 缺失时首次启动会自动从 `data/templates/` 初始化空文件，
  然后按 `cli.py onboarding` 向用户补齐。

---

## 平台技术要点（BOSS直聘，实测）

| 要点 | 说明 |
| --- | --- |
| 反自动化检测 | 页内脚本用 **console 序列化探针**判断是否附着调试器；一旦命中就把页面清成 `about:blank` |
| 可用通道 | **原生 CDP 且只用 `Runtime.evaluate`**，绝不调用 `Runtime.enable`/`Console.enable`/`Log.enable`；Playwright/Puppeteer 会必然开启 Runtime 域，4 秒内被识别（stealth 插件无效） |
| 启动环境 | Chrome 必须在**工作区文件沙盒之外**运行，否则其自身沙盒初始化失败 |
| 标签页 | **只保留一个**目标站标签页（多标签会导致导航与点击落在不同页面） |
| 点击 | 用 `Input.dispatchMouseEvent` 真实鼠标事件；先 `scrollIntoView` 再等 ~700ms 取坐标（平滑滚动会让坐标算早），必要时用 `el.click()` 兜底 |
| 探测 | 平台会主动探测本地调试端口，端口存在本身是弱信号；如需更隐蔽用 `--remote-debugging-pipe` |

## 坑位速查

| 现象 | 根因 | 对策 |
| --- | --- | --- |
| 页面约 4 秒变 `about:blank` | CDP `Runtime` 域被开启 | 只保留 `Runtime.evaluate`，永不 enable Runtime |
| Chrome 启动即崩 | 工作区沙盒禁止其自身沙盒 | 完整权限启动 |
| 点击无效 / 操作错页 | 多个目标站标签页 | 只留一个，脚本统一选页 |
| 列表页薪资乱码 | 数字字体混淆 | 以详情页为准 |
| `环境异常` / 跳安全校验页 | 高频内部 XHR | 停止 XHR，改页面导航，放慢 |
| 「发简历」点不动 | 平台要求双方回复后解锁 | 先发高清简历图 |
| 简历图糊 / 背景透明 | 低 DPI 放大 + PDF 透明底 | kit `render --dpi 260` + 白底合成 |
| 中文丢字 | 文档指定了系统没有的中文字体 | 走 Chrome `printToPDF` 或替换字体 |
| 重复投递 | 无去重 | 投前读 `applications.json` + 看按钮文案 |

## 合规

- 仅用于**本人账号**求职投递，不得用于骚扰或商业推广。
- 打招呼不可撤回；投递前必须确认目标名单（网页配置页即确认动作）。
- 简历内容必须真实；定制只做**措辞与重点重排**。
