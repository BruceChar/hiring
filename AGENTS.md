# AGENTS.md · 求职工作台（Agent 入口）

> **任何 Agent 接手本目录时，先读这一份文件。** 它说明项目怎么组织、怎么启动、按什么流程工作、
> 以及哪些是硬约束。岗位族的业务细节见 `skills/boss-zhipin-apply/SKILL.md`。

---

## 0. 这是什么

一个**可整体迁移的求职工作台**：本地 Web 应用 + 数据文件 + HTTP API + CLI。
用于「按关键词/城市/薪资筛选岗位 → 按 JD 定制简历 → 校验后投递 → 记录反馈并评估 → 分析技能差距」的闭环。

**零依赖**：只需要 Python 3.8+ 标准库。不需要 pip / npm / 联网 / 任何 Agent 框架。

---

## 1. 目录：代码与用户数据严格分离

```
<项目根>/
├── AGENTS.md              ← 本文件（Agent 入口）
├── README.md              给人看的说明
├── workbench/             ★ 应用代码（可脱离用户数据整体迁移）
│   ├── server.py           Web 服务 + REST API
│   ├── cli.py              命令行（Agent 首选）
│   ├── engine.py           技能树聚合 + 差距分析 + 学习方案
│   ├── seed.py             从历史产物初始化数据
│   ├── selftest.py         自检（45 项）
│   ├── scoring.py          技能评分模型（四分类 / 证据强度金字塔 / 覆盖率分档）
│   ├── skill_links.py      断链检测：技能 ↔ 项目 账实相符（R1-R4）
│   ├── cities.json         城市码字典（用户只填城市名）
│   ├── lexicon.json        技能词库（8 领域 / 90 技能点，可换岗位族）
│   ├── templates/          空模板：新机器首次运行据此初始化 data/
│   ├── API.md              Agent 交互契约
│   └── web/                前端（原生 HTML/CSS/JS）
├── skills/                ★ 技能文档（Agent 读这个执行流程）
│   └── boss-zhipin-apply/SKILL.md
├── tools/                 ★ 浏览器控制与简历生成脚本
└── data/                  ★★ 用户数据（可单独迁移 / 备份 / 版本管理）
    ├── profile.json        个人履历（目标岗位列表 + 四大分类技能 + 证据强度自动标定）
    ├── search_config.json  搜岗参数（城市只填名字）
    ├── strategy.json       投递策略（周期/数量/时间窗/暂停条件）
    ├── jobs.json           岗位池（含 JD 与技能标签）
    ├── applications.json   投递记录（状态 + 时间线）
    ├── feedback.json       HR 反馈
    ├── skills_tree.json    技能树/高频技能点（engine 生成，岗位池覆盖率口径）
    ├── gap_analysis.json   层级语义匹配报告：需求向量+六色差距+匹配率双轴+四张卡（engine 调 jd_match 生成）
    ├── resumes/{html,pdf,img}/  简历产物
    ├── exports/            导出物（Excel/zip）
    ├── raw/                历史流水产物
    ├── logs/               运行日志
    └── (用户数据，模板见 workbench/templates/)
```

**迁移规则**

- 迁移「应用」：拷 `workbench/ skills/ tools/ AGENTS.md README.md`。
- 迁移「我的数据」：拷 `data/`。
- 两者可分别迁移；`data/` 缺失时，代码会自动从 `workbench/templates/` 初始化出空文件。

---

## 2. 30 秒上手

```bash
python3 workbench/server.py            # → http://127.0.0.1:8787
python3 workbench/cli.py status        # 不开服务也能用
python3 workbench/selftest.py --http   # 自检（45 项）
```

---

## 3. 开工前必做：数据完备度检查

```bash
python3 workbench/cli.py onboarding     # 缺什么一目了然（退出码 1 表示有缺失）
# 或 GET /api/onboarding
```

`onboarding.items[]` 每项含 `done`、`file`、`ask`。**若 `done=false`，不要凭空开工，必须先按 `ask`
向用户逐项询问，写入对应文件后再继续。** 需要用户提供的通常是：

| 项       | 让用户提供什么                                                                                            | 写入                        |
| -------- | --------------------------------------------------------------------------------------------------------- | --------------------------- |
| 个人履历 | 姓名、联系方式、所在城市、年限、教育/工作/项目经历、技能及其**证据**（关联经历/深度/产出/最近使用） | `data/profile.json`       |
| 目标岗位 | **在「搜岗」页顶部管理（最大前提）**：`profile.targets[]` 可多个（标题 + **各自独立的搜索关键词**），`activeTarget` 为当前选中并同步为 `title`（简历标题）；区块**默认折叠**，summary 只显示当前目标；改动即时保存。采集/筛选/简报/岗位池匹配的关键词 = 当前选中目标的关键词 | `data/profile.json`       |
| 搜岗配置 | **只问城市名**、薪资区间、本批数量、招聘类型（校招/社招，可选）；关键词在「目标岗位」里设置 | `data/search_config.json` |
| 投递策略 | 周期、每次岗位数、允许时间段、是否需确认名单、暂停条件                                                    | `data/strategy.json`      |

**城市不要让用户填城市码**：只填城市名，系统用 `workbench/cities.json` 自动补 `city=` 参数。
未收录的城市会出现在 `PUT /api/config` 响应的 `unresolvedCities` 里，此时由 Agent 打开
`https://www.zhipin.com/web/geek/jobs` 切换城市，从地址栏读出 `city=` 值再补进字典。

---

## 4. 标准作业流程

完整流程见 **`skills/boss-zhipin-apply/SKILL.md`**，摘要：

0. **确认参数**（对话或网页「搜岗配置」→ 生成 Agent 任务简报）
1. 采集岗位 → `data/jobs.json`（含招聘者活跃度）；**岗位归属当前选中目标**（`targetIds[]` 自动打标）。岗位池 = 当前目标的岗位；目标无岗位时显示空态 + 「查看全部岗位（跨目标）」入口。岗位池管理：排序（目标匹配优先/活跃度/薪资/最近采集）、分页（20/50/100 条每页）、「🔄 刷新岗位」按钮 = **主动去 BOSS 采集**（`POST /api/jobs/refresh`，按当前目标关键词 + 招聘类型经 boss-daemon `collectNavs` 页面导航式**批量并行**拉取、**后台两阶段采集**、upsert 去重落盘；**阶段2 先按列表薪资直判剔除低薪岗，再对剩余新增岗位批量并行进详情页回填明文薪资 + JD，薪资与配置区间无重叠的低薪岗自动剔除**；采集期间前端轮询 `/api/jobs/refresh/status` 实时上屏；采集通道未连接时返回 `daemon_off`）
   - **岗位池清洗（校招/错配过滤）**：关键词搜索会混入校招岗与模型训练向岗位（如「大模型应用开发专家」「LLM后训练」「【校招】…」）。`workbench/job_filter.py`（纯规则可复现）按两层过滤：① **校招**（`recruit_types` 不含「校招」时）——BOSS tags 含 校招/在校/应届/实习、实习时长标记（`5天/周/2个月`）、标题含 校招/校园/实习/`20xx届`/`N届`（⚠️ 不用 JD 全文——社招 JD 常含「实习经历/接受应届」，实测误杀 20+ 条；⚠️ 「不是27校招岗」「接受应届」为社招向，有保护规则）；② **目标错配**——标题含 后训练/预训练/训练基础架构/训练推理/强化学习/`大模型应用开发专家` 或含「算法工程师」且无 agent/智能体/应用/工程/开发 保护词（模型研究/训练向，与 Agent 应用岗不匹配）。多目标岗位命中错配规则时**仅剥离当前目标归属**，不误伤其他目标。入口：Web 搜岗页「🧹 清理错配岗位」/ `POST /api/jobs/prune` / `cli.py jobs prune`；采集（`jobs/refresh`）收尾**自动执行一次**；清洗前自动备份到 `data/raw/jobs_prune_backup_<ts>.json`，事件 `jobs.prune`。
   - **岗位 ID 与去重设计**：主键 `id` = BOSS `encryptJobId`（稳定唯一）。`PUT /api/jobs` 与 refresh 均按 id upsert：已存在 → 更新业务字段（薪资/JD/活跃度）+ `targetIds` 并入当前目标（同岗可属多目标）+ `lastSeenAt` 刷新；不存在 → 新增并写 `firstSeenAt`/`lastSeenAt`。`firstSeenAt`（首采时间）区分历史/新岗位，前端对 48h 内新采集岗位打「新」标。`GET /api/jobs?target=<id>` 可按目标过滤
   - **相关度 = 岗位 × 履历 匹配度百分比**：`POST /api/jobs/match` 对全池逐岗跑 `jd_match.build_job_insight`（单岗层级匹配，corpus=该岗 JD；无 JD 用 position+skillTags 拼语料）出 `matchRate.overall`，落盘 `matchScore`（0-100）+ `matchDims`（命中维度数）+ `matchLevel`（≥60 strong / ≥35 weak / 其余 none）。⚠️ **维度置信度衰减**：`dims < 5` 时 `score = round(score × dims / 5)`——2-3 个维度全达标会刷出 100%（已实测），信息不足的岗分数打折。前端岗位池「相关度」列显示百分比 chip（hover 显示命中维度数），筛选下拉按 60/35 分档；无分数岗（无 JD）显示「—」并归入「低匹配/未评估」（GET /api/jobs 不再按关键词覆盖 matchLevel）。首次进入搜岗页自动触发一次批量重算（`autoMatch`）。点击岗位行 → 右抽屉「岗位分析」：顶部大数字 = jdMatch.matchRate.overall（与列表同口径），下接**岗位洞察详情**（硬差距横幅 + 匹配率双轴 + 六色分型表 + 四张行动卡 + 已有优势，复用岗位洞察页渲染函数 renderHardBanner/renderMatchDual/renderDims(_,_,false)/renderCards/renderStrengths）＋旧匹配明细/缺陷补充/面试注意点/JD 摘录。`build_job_insight`（jd_match.py）与 build_report 同口径（M1 需求向量现扫单岗 JD、M2 画像 build_capabilities 复用、M3 六色、M4 四卡），单岗 ~11ms，全池批量 ~1.5s。
   - **活跃度筛选**：`GET /api/jobs?active=刚刚活跃,今日活跃,…` 按档位过滤（逗号分隔，命中任一档保留）；前端岗位池「活跃度」下拉默认**按搜岗参数**（`search_config.activity_preference`，如「最大本周活跃」= 四档内），空活跃度岗位**保留不误杀**。⚠️ **BOSS 2026-10 起列表页与详情页已移除活跃度标签文本**（10-01 仍可抓到「刚刚活跃/今日活跃/…」，实测现全空），collectNav/collectDetail 的 activity 提取逻辑保留——BOSS 恢复该标签即自动回填生效
2. 筛选与去重 → `cli.py pending`（薪资/城市/活跃度/招聘类型校招社招 + 排除已投递）
3. 抓 JD 回写
4. `cli.py analyze` → 技能树 + 差距 + 学习方案（决定简历写什么）。**按目标岗位口径**：`profile.targets[]` 可维护多个目标，`activeTarget` 为当前选中并同步 `title`（简历标题）；技能分析始终按全词库（8 领域），`skills_tree.json` / `gap_analysis.json` 落盘带 `target` 元信息，切换目标后访问技能树/差距页会自动重算。
   - **用户校准（忽略维度）**：JD 归纳的维度可能与岗位实际要求有出入（如 Agent 岗的「大模型微调（SFT）/RL」类训练维度并非必需）。岗位洞察页每个维度行有「忽略」按钮：写入 `data/insight_ignore.json`（按 target id 持久化，无目标用 `global` 键）→ `POST /api/analyze` 重算 → 报告重新落盘；被忽略维度从需求向量/分型/匹配率/硬差距/卡片中剔除，但保留在 `gap_analysis.json` 顶层 `ignoredDims` 供「已忽略维度」区展示并可一键恢复。API：`GET/PUT /api/insight/ignore`（PUT body `{target, dims[]}` 覆盖该目标列表）。
   - **岗位洞察 = 层级语义匹配（jd_match_v1）**：在词库覆盖率之上叠加 `workbench/jd_match.py`（M1-M4，纯规则零依赖，设计依据《履历 × 目标岗位匹配评估系统 v1.0》）——M1 JD→能力需求向量（维度×最低层级 L1-L4×权重×must/加分+职责动词画像）、M2 履历 L1-L4 判定（L1 用会/L2 负责实现/L3 主导设计/L4 治理闭环，证据锚点+子串校验+量化口径 business>tech>decorative）、M3 六色差距分型（✅达标/🌟超配/✏️表述/🔁迁移/📚学习/🏗️结构/⛔硬）+ 加权匹配率（超配不计分）、M4 四张行动卡（简历定制/证据补全/学习计划/面试预演）。`gap_analysis.json` 顶层含 `engine/requirements/capabilities/dims/ignoredDims/matchRate/hardGaps/cards`，`gaps/strengths/summary/recommendations` 为维度级口径；硬差距在报告顶部直接提示谨慎投递。前端岗位洞察页按 `g.engine === 'jd_match_v1'` 渲染新视图，旧口径兜底。
   - **洞察面板目标自选**：`engine.py` 支持 `--target <id>` 覆盖口径（只影响该次分析与展示，不改全局选中）；`POST /api/analyze?target=<id>` 透传；前端洞察页（岗位洞察/差距与学习）顶部目标下拉**面板内自选**（localStorage `insightTarget` 记忆，独立于搜岗的当前目标；选「跟随搜岗」清空后回全局 activeTarget 口径）。
   - **资料链接**：`workbench/lexicon.json` 的 `learn.resources[]` 可带 `url`（官方稳定资源已补 62 条）；gap 报告的 plan.resources 透传 url，前端渲染为可点击外链（`a.chip.link`）；学习步骤文本内嵌 http(s) URL 自动转链接。
   - **优先级热力**：缺口卡片与优先级 chip 按 1-5 火焰图色阶（蓝→青→黄→橙→红，`gapcard.p1..p5` / `chip.heat1..heat5`），阈值 4.5/3.5/2.5/1.5。
5. 生成定制简历：**LLM 按 JD 定制**（`tools/agent_tailor.py`，只调侧重不编造，退出码契约见 §6）或脚本/人工条目 `data/tailor.json`
6. **投递前双重校验**：`tools/validate_resume.py` + 独立 Agent 复核，未通过不得投递
7. 打招呼并送达简历图（平台限制对方回复前不能发 PDF 附件）
8. 记录与反馈 → `cli.py app add` / `feedback add`（状态自动推进）

任何一步都可以用「HTTP API / CLI / 直接改 JSON」三种方式完成，读写的是同一份 `data/`。
外部 Agent / 平台调度器的接入声明（交互方式、退出码契约、事件日志）统一见**第 6 节**。

### 4.5 每日自动流程与简历图片门禁

每天定时只需跑一条命令，它把「时间窗 → 批次门禁 → 简历图片检测 → 确定性校验 → 任务单」串起来：

```bash
python3 tools/daily_apply.py      # 0=可开工 / 2=无候选 / 3=策略暂停 / 4=校验失败（禁止投递）
```

- 任务单落在 `data/logs/daily/<日期>-<时刻>.md`（同时写 `.json`），事件写入 `data/logs/agent-events.jsonl`。
- **简历图片是硬门禁**：`python3 tools/check_resume_images.py` ——
  可读性 / RGB 无 alpha / 宽 ≥2000px / A4 比例 / 四角纯白 / 体积 / 空白页（墨迹占比），
  外加 HTML 层内容检查（标题统一、板块齐全、关键事实、无占位符）。
  ⚠️ **只检测「要发出去的」图**：以 `data/tailor.json` 的条目为准（`蔡长霖-<公司>-Agent系统工程师.png`），
  文件名含 预览/preview/草稿/截图 的一律跳过并在报告里注明——否则用户自己生成的预览图会让整批误判 FAIL。
  报告写 `data/raw/image_check.json`，**任一交付图不过就不许发送**。
- `tools/validate_resume.py` 复用同一套图片检测，并自动定位 `data/tailor.json`
  （缺失时退回 `data/raw/tailor.json`，再退回按 HTML 文件名推断），因此随时可跑。
- 需要 Pillow；脚本经 `tools/_pyboot.py` 自动切换到自带 Pillow 的解释器，
  所以 cron 用系统 `python3` 直接调也行（也可用 `DSH_PYTHON` 指定）。
- 出 PDF 依赖 **9223 上的 headless 打印 Chrome**（9222 留给 BOSS 采集/投递，互不干扰）：
  `./tools/ensure_print_chrome.sh` 探测并按需拉起，跑 `agent_tailor.py` / `print_pdf.mjs` 前先执行。
- 没有 LLM 密钥时，`agent_tailor.py` 走**离线通道**：先按 §6 的 schema 写好条目 JSON，
  再 `python3 tools/agent_tailor.py <job_id> --from-json item.json`——不编造门禁一样生效。
- **投递链路**（三者都从最新 `data/logs/daily/batch-*.json` 取目标，不再读根目录历史快照）：
  1. `node tools/preflight_delivery.mjs` —— 批次 ↔ 简历图 ↔ 门禁 配对自检，**不发任何消息**；
  2. `node tools/apply_greet.mjs` —— 逐岗打招呼（详情页按钮 `立即沟通`/`继续沟通` 判重，13s 起随机节流）；
  3. `node tools/send_resumes.mjs` —— 进聊天页发高清简历图，**只发独立复核 verdict=pass 的**。
  匿名公司名（`某大型…`/`某知名…`）在会话列表里显示真实主体名，匹配不上，发送前需在该条上补 `match` 关键字。
- 会话列表是「已联系」真源：`node tools/sync_contacts.mjs` 拉全量会话到 `data/raw/chats.json`，
  `daily_apply.py` 的「已联系去重检查」据此阻断重复打招呼。
- **投递通道体检**：任务单第 2.5 节会探测 9222（BOSS 控制）/ 9223（打印 Chrome）/ 8787（工作台服务）。
  三者是「会话去重 / 打招呼 / 发简历图」的硬前提。⚠️ **Chrome 必须在工作区文件沙盒之外启动**，
  在沙盒内 spawn 的 Chrome 会连上调试口后立刻崩（日志见 `data/logs/daemon.log` / `chrome-print.log`）。
  恢复：普通终端 `python3 workbench/server.py` → Web 左下角点「BOSS 采集」；打印通道 `./tools/ensure_print_chrome.sh`。
- 定时：本会话用 DSH 提醒（工作日 09:30 / 14:00）；OS 级用
  `python3 workbench/cli.py schedule --cron` 生成的 crontab 行。

### 4.6 简历模板（gen_resume 渲染布局）

`tools/gen_resume.py` 的**布局与样式来自模板文件，不写死在代码里**：
- **查找顺序**：`data/resume_template.json` 指定默认模板名 → `data/templates/resume/<name>`（用户添加，优先）→
  `workbench/templates/resume/<name>`（内置）→ 回退内置 `resume.html`。
- **占位符**：`{{HEADER}} {{SUMMARY}} {{SKILLS}} {{PROJECTS}} {{WORK}} {{EDUCATION}} {{OTHER}}`，缺失即渲染为空。
- **内置默认**（`workbench/templates/resume/resume.html`）：A4 一页、核心项目在前
  （简介 → 核心能力 → 核心项目经历 → 工作经历 → 教育经历 → 其他），深蓝主色。
- **Web 管理**：投递与反馈页「简历模板」tab（页面顶部 tab：策略 / 简历模板 / 反馈）——下拉选模板（内置/自定义标记）
  + **预览即编辑**：示例数据实时渲染的预览页上直接拖拽区块调序（区块右上角 × 移除、「恢复全部区块」找回）；
  **点击编辑样式（两级）**：点区块 → 右侧面板汇总该区块全部相关规则（标题 h2 + 正文 + 小标题 + 要点列表，如工作经历 11 条）；
  **点区块内某个元素**（如 bullet 要点 li、公司名 .wco）→ 只显示该元素的样式规则，**共用选择器（如 li 多处使用）会把所有使用处一起高亮**（选中=实线蓝框、共用=虚线橙框），修改应用即全局生效；
  面板为单一格式化 JSON 编辑区，改后「应用样式」JSON→CSS 写回模板并刷新预览；非法 JSON 报错提示；
  「保存」= **重命名**（输入框填名则用新名保存并删除旧自定义模板，留空覆盖当前）、「另存」= 新模板（后缀 .html 自动补全，未填名自动生成 resume-copy.html 类副本名）、「删除模板」删自定义（内置拦截）、「设为默认」；
  策略页**无右侧卡片**，表单底部一行「保存 / ▶ 运行 / 重新载入」按钮；`POST /api/run-batch` 同步执行 run-batch 返回退出码（0=可开工/2=无候选/3=暂停）；
  全局：`.tag` 说明性 hint 全部隐藏（CSS `display:none`，各页区块标题旁说明、sectionhead 说明均不可见）；左侧栏宽度随内容自适应（`max-content`，min 150 / max 250）；
  API `GET /api/resume/templates`（列表含 builtin 标记 + default；`?name=xxx` 返回单模板内容）、
  `PUT`（`{default}` 或 `{name,content}`，内容需 ≥200 字符且含 `{{`）。
- 区块样式选择器映射（app.js `TPL_SELS`）：SUMMARY→h2/.summary；SKILLS→h2/.cap；PROJECTS→h2/.work/.item/.top/.ttl/.meta/.stack；WORK→h2/.work/.wrow/.wco/.wrole/.wdate/.desc/.wstack；EDUCATION→h2/.edu；OTHER→.other（.work 为项目/工作共用容器样式）。
- 用户添加的模板落在 `data/templates/resume/`，随 data/ 迁移；校验门禁 REQUIRED_SECTIONS/FACTS 与模板无关（检查渲染后的 HTML 文本）。

### 4.7 岗位分析增量模式（履历 diff → 只重算受影响技能）

`workbench/engine.py` 的 `analyze` 支持**增量分析**：履历/岗位池未变则秒退复用，只改一个技能也只重算那一个：

- **指纹**：`profile_skill_fp`（技能全字段 md5：name/aliases/group/cluster/level/evidenceLevel/projectRefs/metrics/statement/note/skillEnvironment）、
  `profile_fingerprint`（技能名→指纹）、`jobs_fingerprint`（id/jd/skillTags/targetIds 排序哈希）。
- **基线**：`data/raw/analyze_baseline.json`（`{target, profileFp, jobsFp, skills{技能名: 可沿用字段子集}}`）；
  沿用字段分两类——岗位侧 `_mentions/_demand/_coverage/_coverageTier/_coverageTierDesc/_samples/_hitLabels`（jobs 未变才沿用）、
  履历侧 `_myScore/_myTier/_evidenceCount/_inProfile/_myLevel/_matchedProfile`（该技能指纹未变即沿用）；
  派生字段 `_isGap/_gap/_priority/_domain` 总是按最终 coverage+myScore 现算，口径不漂移。
- **判定**（engine main）：`--full` 或切换目标（target id 不同）→ 全量；否则 diff profileFp+jobsFp →
  noop（无变化时**不再 exit(0)**，复用上次中间字段继续生成报告）/ partial（只重算 added∪changed 技能，覆盖率在 jobs 未变时沿用）。
  `tree.delta`（skills_tree.json 顶层）记录 mode/added/changed/removed/kept/jobsChanged/elapsedMs；stdout 尾部打 `[delta] …` 行。
- **jd_match 继承增量**：`jd_match.build_report` 直接消费 analyze() 打好的 `_mentions/_coverage/_myScore/_inProfile` 等中间字段（noop/partial 均有效），无需独立指纹；每次运行都会刷新 gap_analysis.json 的 `generatedAt` 与维度级结果。
- **入口**：CLI `python3 workbench/engine.py [--full] [--target <id>]`；API `POST /api/analyze[?full=1][&target=<id>]`；
  前端岗位洞察页「重新分析」按钮 toast 解析 `[delta]` 显示「新增/重算/移除/沿用」摘要。
- **坑**：`btnAnalyze` 绑定必须在 `route()` 渲染**之后**取 DOM（绑定到渲染前取的元素会无效——曾导致「重新分析无效」）。
- 实测：首次全量 ~1071ms；无变化 noop ~170ms（复用中间字段+刷新报告）；单技能修改 partial 6ms（~180x 提速）；改技能 myScore 74→94、未变技能沿用 94 不变。


---

## 5. 投递策略是硬约束

`data/strategy.json` 定义了 Agent 必须遵守的执行规则：

```bash
python3 workbench/cli.py strategy                    # 查看
python3 workbench/cli.py strategy --set batch_size=5 # 修改
python3 workbench/cli.py schedule --cron             # 生成 crontab 行
```

必须遵守：**允许时间段**、**每次/每日数量上限**、**是否需要用户确认名单**、
**连续 N 家无回复则暂停复盘**、**回复率低于阈值则暂停**、**同公司冷却期与去重**、
**命中平台风控立即停止**。策略变化会实时反映到 `GET /api/brief` 生成的简报里。

---

## 6. Agent 接入声明（外部 Agent / 平台调度器统一入口）

> 任何 Agent 平台（Codex / DSH / 豆包 / 自研脚本）接入本项目，只看这一节 + 第 4 节作业流程。

### 交互方式（三选一，读写同一份 data/）

```bash
python3 workbench/cli.py status        # ① CLI（推荐，无需服务在跑）
curl -s localhost:8787/api/stats       # ② HTTP API（完整端点参考见 workbench/API.md）
# ③ 直接读写 data/*.json（UTF-8 JSON，最稳零耦合）
```

常用端点：`/api/onboarding`、`/api/brief`、`/api/config`、`/api/strategy`、`/api/cities`、
`/api/jobs`、`/api/applications`、`/api/feedback`、`/api/skills`、`/api/gap`、
`/api/analyze`、`/api/stats`、`/api/events`、`/api/schedule`、`/api/export`、`/api/import`。

### run-batch 退出码契约（调度器唤醒点）

`python3 workbench/cli.py run-batch` 是 cron / 任意平台定时任务的统一唤醒命令，
输出本轮简报 + 候选岗位，并用退出码告知调度器该不该启动 Agent：

| 退出码 | 含义                                       | 调度器动作                           |
| ------ | ------------------------------------------ | ------------------------------------ |
| `0`  | ready：有候选且未暂停                      | 启动 Agent 开工（按第 4 节流程执行） |
| `2`  | idle：无候选岗位                           | 本轮无需行动                         |
| `3`  | paused：策略停用 / 连续无回复 / 回复率过低 | 不执行，先复盘调整                   |

判定复用 `server.compute_batch_status()`；暂停条件来自 `data/strategy.json`
（`enabled`、`pause_after_consecutive_no_reply`、`min_reply_rate`）。

### agent_tailor 退出码契约（LLM 按 JD 定制简历）

```bash
LLM_API_KEY=sk-xxx LLM_MODEL=deepseek-chat python3 tools/agent_tailor.py <job_id>
# 任意 OpenAI 兼容网关；LLM_BASE_URL 默认豆包方舟 https://ark.cn-beijing.volces.com/api/v3
```

读 JD → LLM 产出定制条目 → 后校验（标题/公司名/数字/占位符，比对固定事实，编造即拒）→
写 `data/tailor.json` → 自动渲染 HTML → Chrome 出 PDF → 高清 PNG → validate 门禁。

| 退出码 | 含义 | 调度器动作 |
| --- | --- | --- |
| `0` | 完成且门禁通过 | 可进入投递流程 |
| `1` | LLM 输出未过后校验（不写盘） | 重试一次或降级用预写条目 |
| `2` | LLM API 失败 / 缺 key | 检查网关配置后重试 |
| `3` | 岗位或数据缺失 | 先补数据 |
| `4` | 出图流水线或门禁失败 | 修产物后重跑 |

离线通道：`--from-json item.json`（跳过 LLM）；调试：`--dry-run` / `--no-run`。
事件：`actor=agent_tailor`，`tailor_generated / tailor_rejected / tailor_llm_error / tailor_parse_error`。

### 事件日志（断点恢复与审计）

所有写操作（CLI/API）自动追加到 `data/logs/agent-events.jsonl`
（`actor/action/detail/status/payload`），`GET /api/events?limit=N` 可读。
**接手任务先读最近事件**（上次 run-batch 结果、最近投递/反馈），用于断点恢复与审计。

### 采集通道 boss-daemon（刷新/采集的硬前提）

`/api/jobs/refresh`、脚本采集与登录态检测统一走 **`tools/boss-daemon.mjs`**（**纯原生 CDP**，零第三方依赖）：
- **单次命令模式（server 采集/登录检测的调用方式）**：`_collect_worker` 与 `GET /api/daemon` 均以
  `subprocess.run([node, tools/boss-daemon.mjs, <action>, '<json>'])` 单次执行（`loginCheck` / `collectNavs` /
  `collectDetails` / `collectNav` / `collectDetail` / `state`）——脚本直接连 9222 Chrome 执行对应动作并输出 JSON 后退出，**不写命令队列、
  不创建任何根目录产物**。根目录 `commands/ results/` 已废除（曾由旧 `tools/boss.mjs` 每次运行重建，
  现已全面切到 `data/raw/commands|results`）；常驻 daemon（Web 左下角启动）用于保持独立 Chrome 与登录态，
  与单次模式互不干扰。

- **通道**：只连调试口 **9222** 上的 Chrome。**模式 = 独立调试 Chrome**（用户拍板）：daemon 启动时若 9222 未就绪 → 自动拉起**独立 Chrome 实例**（**独立 profile = `data/raw/chrome-boss-profile`**，放项目内 → 避开 `~/Library` 的 TCC 权限限制、可随 data/ 迁移；spawn 直接执行 Chrome 二进制 + `--user-data-dir`，**不用 `open -a`**——会激活用户日常 Chrome 干扰用户）。**与用户日常 Chrome 完全互不干扰**：不要求退出、不导航它的标签页、不碰它的 profile。已有 zhipin 标签 → 复用；无 → 新建。**排除 headless 实例**（无窗口/无登录态/独立指纹，曾长期占用 9222 骗过探测）。
- **命令面**：只用 `Runtime.evaluate` / `Page.navigate` / `Page.captureScreenshot` / `Target.createTarget` / `Target.activateTarget`；**永不 enable Runtime/Console/Log 域**（playwright-core 必开 Runtime 域 → 4 秒内被 BOSS console-getter 探针清成 about:blank，已实测否决）。
- **采集方式**：`collectNavs` 页面导航式**批量并行**（组合分片到 2-4 个独立 tab 并发，`Target.createTarget` 建、用完 `closeTarget` 关；`Page.navigate` 列表页 → DOM 提取 `.job-card-wrap`：`a.job-name` 职位 / `.job-salary` 薪资 / `.boss-name` 公司 / `.company-location` 地区 / `.tag-list li` 按「年$/经验→exp、本科…→degree、其余→skillTags」分类）；**动态节流**：新 tab 首轮等待 14s+（前端 JS 加载），后续快参数 8s/3s 起手、连续正常渐进到最低 6s/2.5s、遇异常/风控特征立即退回保守 13s/4s，任一 tab 连续 2 次风控信号 → 全局 risk=true 停止本轮；**不用内部 XHR**（高频调用返回「环境异常」code 37，已实测否决）。单组合兼容旧 `collectNav`（复用现有 tab，13s/4s）。
- **采集筛选**：**薪资 URL 参数已失效**（`salary=min_max` 只在筛选栏留个「薪资待遇(1)」标记、服务端不真正过滤，实测 100_200 极端值也照样返回 10K 岗位——勿再依赖）；**真正的薪资过滤在阶段2**：先按列表页明文薪资（`.job-salary`）直判——与配置区间无重叠的直接剔除**不进详情**（省 13s/岗），剩余新增岗位批量并行进详情页（`collectDetails`，2-5 tab 并发、9s 起手最低 6s）回填明文薪资 + JD，详情薪资复核与配置区间（重叠即保留）比对，不符的直接剔除不进池。**招聘类型**——BOSS 默认列表即社招（`recruit_types=["社招"]` 零成本正确），配置 `["校招"]` 时 collectNavs 导航后页面内点击「求职类型→校招」（失败不阻断，记日志继续）；`recruitType`/`jobType` URL 参数新版已废弃（实测不生效，勿依赖）。
- **两阶段采集 + 实时上屏**：`POST /api/jobs/refresh` 只做校验并**立即返回** `{ok,started,status}`。**阶段1（phase=list）**：后台线程按城市分批（每批 ≤3 城市 × 全部关键词）跑 `collectNavs`（3 tab 并发 + 动态节流），每批完成即 upsert 落盘并刷新会话状态，新增岗位的 id 收集进待回填队列；**阶段2（phase=detail）**：先对新增岗位按**列表薪资直判**剔除与配置区间无重叠的低薪岗（不进详情），再对剩余岗位每批 ≤12 跑 `collectDetails`（4 tab 并发）回填明文薪资 + JD，`_salary_ok()` 判定薪资区间与配置区间（`search_config.salary{min,max}`，重叠即保留；元/天×20、元/时×160、元/月÷1000 折算月薪 K；万×10；解析不出如「面议」→ 保留待人工）无重叠 → **从岗位池移除**（低薪垃圾岗不进池）；任一批返回 `risk=true` → 立即停止本轮并记录风控错误。前端轮询 `GET /api/jobs/refresh/status`（`{running,phase,done,total,added,updated,excluded,lastAt,error,salary,recruitType,kws}`）3s 一次拉取 + 全量重渲染——**采到一条显示一条**（新岗位带「新」标），无需手动刷新。冷却：采集中返回 `busy`(429)；完成后 10s 内防连点 `cooldown`(429)。
- **登录态**：登录态持久化在**独立 profile**（`data/raw/chrome-boss-profile`），与用户日常 Chrome 登录态隔离；首次使用需用户在独立 Chrome 窗口完成 BOSS 验证码 + 登录（验证码**必须真人操作**，CDP 模拟轨迹更易被标记）。`GET /api/daemon` 返回 `loggedIn`（loginCheck：非 passport/verify 页 + 有头像/用户区）；未登录时 Web 左下角状态行显示「运行中·待登录」。
- **启停**：Web 左下角「BOSS 采集」状态行点击启动/停止；或 `POST /api/daemon/start|stop`；状态 `GET /api/daemon`。
- **存活判定**：daemon 启动后写 `data/raw/daemon.pid`，退出清理；server 用 pid 文件 + `kill(pid,0)` 探测（不要用 pgrep 文本匹配，会误报）。
- **风控纪律**：命中平台安全校验（verify.html / code 35+）立即停止本轮，不硬刚；放慢节奏后由用户人工完成校验。验证码只在首次/长期未用后出现，通过后 cookie 固化无需重复。

---

## 6.5 技能区规范（写简历前必读）

`data/profile.json`（schemaVersion=3）的 `skills[]` 按**四大分类**组织：

| group | 承载内容 | 简历位置 | 排序原则 |
| --- | --- | --- | --- |
| `professional` | 专业技能（硬技能）：可验证的方法与领域能力 | 技能区主体，置顶 | 按目标岗位匹配度从高到低 |
| `tools` | 语言 / 框架 / 数据库 / 中间件 / 云与 DevOps | 紧随其后，按技能簇分组 | 核心工具在前 |
| `soft` | 通用能力：沟通协作、项目管理 | 不单列罗列，靠经历 bullet 证明；确需列出**≤5 条且必须带场景** | 仅列与岗位强相关的 |
| `credentials` | 外语等级、证书、执照 | 单独一栏 | 按含金量降序 |

另有 `skillEnvironment` 聚合行（如「日常工作环境：Linux / Git / Docker / Nginx」）——
整体声明的可信度高于十个「熟练」，且豁免 R1 落点要求。

**证据强度金字塔**（`evidenceLevel`，取该技能最强的那一类）：

| 星级 | 证据类型 |
| --- | --- |
| ★★★★★ 5 | 可量化的项目结果（GC 800ms→120ms；挽回率 +12%） |
| ★★★★ 4 | 规模 / 复杂度上下文（日活 500 万、QPS 3 万、200 节点） |
| ★★★ 3 | 角色与职责（主导 / 独立负责） |
| ★★ 2 | 外部验证（开源 PR 合并、竞赛名次、专利） |
| ★ 1 | 时长与频率（主力语言 3 年） |
| ☆ 0 | 证书 / 课程（只证明学过） |

写条目时**优先用高强度证据**；时长与证书是兜底项，不是主体。

**履历列表字段多分隔符解析**：Web 履历表单保存时 `splitList()` 自动拆分——技术栈（stack/techstack）按 逗号/顿号/分号/斜杠/换行/中点 宽拆，` + ` 组合技术视为分隔（PostgreSQL + pgvector → 两条）；亮点/主要工作（highlights）保守拆 换行 + 分号 + 行首项目符号（•·-），**逗号/顿号保留句内**不拆碎长句；engine 对 `aliases` 字符串同样按分隔符拆分（`re.split(r"[，,、;；\n\r]+")`）。历史脏数据（一行多词技术栈）已按同规则清洗（中小外贸项目 1 条串 → 9 条独立技术词）。

**账实相符（交叉验证）**——`python3 workbench/cli.py links` 或 `GET /api/skill-links`：

| 规则 | 内容 | 违反处理顺序 |
| --- | --- | --- |
| R1 存在性 | 每条技能必须有非空 `projectRefs`，或属于 `skillEnvironment` 聚合行 | 补证据 → 降格表述（自学+demo）→ 删除 |
| R2 一致性 | `projectRefs` 指向的项目/经历文本里必须出现该技能关键词或别名 | 同上 |
| R3 完备性 | 项目中出现且与目标岗位相关的技术词，应出现在技能区 | 补充条目 |
| R4 真实性 | 所有证据必须是真实经历 | 无降级路径，**强制删除** |

**写作纪律**：核心技能 3-5 条完整证据句 + 指向项目；次要技能聚合为一行；
写愿意被深挖的，删不愿意被问的；空间不足时砍次要技能，不砍核心技能的证据句。

---

## 7. 红线（不要越界）

1. **不得编造简历内容**：定制只做措辞与重点重排，技术栈/数字必须来自 `data/profile.json`。
2. **不得重复投递**：投递前必须比对 `data/applications.json`。
3. **打招呼不可撤回**：`require_approval=true` 时，必须先把名单给用户确认。
4. **尊重平台风控**：出现「环境异常」或安全校验立刻停止本轮，不要硬刚。
5. **只用于本人账号求职**，不得用于骚扰或商业推广。

---

## 8. 自检与排错

```bash
python3 workbench/selftest.py --http     # 50+ 项（CLI + API + 退出码 + 事件日志 + 清理）
python3 workbench/cli.py status          # 数据总览
python3 workbench/cli.py cities 杭州      # 城市码查询
```

服务日志：`data/logs/server.log`；Agent 事件日志：`data/logs/agent-events.jsonl`
（`GET /api/events`）；平台侧浏览器控制细节与坑位速查见 SKILL.md 最后一节。
