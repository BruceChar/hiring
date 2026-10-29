# 求职工作台 · Agent 交互契约

任何 Agent（Claude Code / Codex / DSH / 自研脚本）都可以通过下面三种方式驱动本工作台。
三种方式读写的是**同一份数据**（`data/*.json`），可以混用。

---

## 0. 启动

```bash
python3 workbench/server.py            # 默认 http://127.0.0.1:8787
python3 workbench/server.py --port 9000
```

零依赖：只需要 Python 3.8+ 标准库。整个 `workbench/` 目录可直接拷贝到任何机器。

---

## 1. HTTP API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 健康检查 |
| GET | `/api/contract` | 本文件 |
| GET | `/api/profile` | 读取通用履历 |
| PUT | `/api/profile` | 覆盖写入履历（自动补 `updatedAt`） |
| GET | `/api/config` | 读取搜岗参数（城市码已自动补全） |
| GET | `/api/cities` | 城市码字典（用户只需填城市名） |
| GET | `/api/strategy` | 读取投递策略 |
| PUT | `/api/strategy` | 覆盖写入投递策略 |
| GET | `/api/onboarding` | 数据完备度：缺什么、该问用户什么 |
| GET | `/api/schedule` | 投递排期 + 可用的 crontab 行 |
| PUT | `/api/config` | 覆盖写入搜岗参数；**城市码自动补全**，未收录的城市在 `unresolvedCities` 返回 |
| GET | `/api/jobs?city=&q=&hasJd=1&target=<targetId>` | 岗位池（可筛选，`target` 按目标归属过滤）；每岗位附 `recruitType`（校招/社招，按 岗位名+标签+JD+经验 推断） |
| GET | `/api/jobmatch?id=<jobId>` | 单岗位 × 履历 匹配分析：`matchScore` / `matched`（命中且有证据）/ `gaps`（空白/薄弱 + 学习重点）/ `interviewPoints` / `jd`（原文，供前端折叠展示） |
| POST/PUT | `/api/jobs` | 批量 upsert，body 为数组或 `{jobs:[...]}`，按 `id` 去重；新增写 `targetIds=[当前目标]`+`firstSeenAt`，更新并入目标+刷 `lastSeenAt` |
| POST | `/api/jobs/refresh` | **主动采集（后台两阶段）**：按当前目标关键词（无关键词时用目标标题兜底）+ 招聘类型（社招=默认列表；校招=collectNav 页面内点击筛选，失败不阻断）→ 阶段1 逐 关键词×城市 `collectNav` 列表快采 + upsert 落盘；阶段2 对新增岗位逐个 `collectDetail` 进详情页回填**明文薪资 + JD**，薪资与配置区间（`search_config.salary`，重叠即保留，元/天×20、元/时×160 折算）无重叠的低薪岗自动移除。**立即返回** `{ok,started,status}`；采集状态实时轮询 `GET /api/jobs/refresh/status`；`no_keywords` / `no_city` / `daemon_off` / `busy`(429 采集中) / `cooldown`(429 完成后 10s 内)。注：BOSS `salary=min_max` URL 参数已失效（不真正过滤），薪资过滤以阶段2 详情页明文为准 |
| GET | `/api/jobs/refresh/status` | 采集会话状态：`{running,phase,done,total,added,updated,excluded,lastAt,error,salary,recruitType,kws}`；`phase` = `list`（阶段1 列表采集）/ `detail`（阶段2 详情回填）；前端 3s 轮询实现「采集一条显示一条」实时上屏 |
| POST | `/api/jobs/clear` | **清空指定目标的岗位**（重新采集前置）：body `{"target": "<目标id>"}` → `{ok,removed,left}`。按 `targetId`/`targetIds` 移除仅属于该目标的岗位（多目标共有的只摘除该目标归属） |
| GET | `/api/daemon` | boss-daemon 采集通道状态：`{running,pid,loggedIn,lastCollect,lastAdded,lastUpdated}`（pid 文件探测 + loginCheck；`loggedIn` 显示 BOSS 登录态，未登录返回 false） |
| POST | `/api/daemon/start` | 手动启动 boss-daemon：**纯 CDP 独立调试 Chrome 模式**——复用已有 9222（排除 headless）；未就绪则自动拉起独立 Chrome（profile=`data/raw/chrome-boss-profile`，项目内避开 TCC），与用户日常 Chrome 互不干扰；无 zhipin 标签则自动新建并激活到前台供登录 |
| POST | `/api/daemon/stop` | 优雅停止（写 `commands/STOP`，daemon 自行退出并清理 pid 文件） |
| GET | `/api/applications` | 投递记录 |
| POST/PATCH | `/api/applications` | 新增/更新记录（按 `id` 或 `company` 匹配） |
| GET | `/api/feedback` | 反馈列表 |
| POST | `/api/feedback` | 追加反馈；`type` 会自动推进投递状态 |
| GET | `/api/skills` | 技能树（聚合结果） |
| GET | `/api/gap` | 差距分析 + 学习方案 |
| GET / PUT | `/api/insight/ignore` | 读取 / 覆盖指定目标的「忽略维度」列表（用户校准，`PUT` body `{target, dims[]}`） |
| POST | `/api/jobs/match` | 岗位池匹配度批量重算：逐岗 jd_match 单岗层级匹配 → matchScore（% ，dims<5 置信度衰减）+ matchDims + matchLevel，落盘 jobs.json（~1.5s/331 岗） |
| POST | `/api/jobs/prune` | 清洗岗位池：剔除校招/应届/实习岗 + 当前目标错配训练/算法向岗位（job_filter.py 纯规则，清洗前自动备份到 raw/） |
| POST | `/api/analyze` | 重算技能树与层级匹配（调用 `engine.py`，内部含 `jd_match` M1-M4） |
| GET | `/api/scoring` | 评分模型说明：四大分类 / 工具技能簇 / 证据强度金字塔 / 分档阈值 |
| GET | `/api/skill-links` | 账实相符断链检测结果；带 `?refresh=1` 会先重跑检测 |
| GET | `/api/stats` | 漏斗、转化率、维度对比、最新反馈 |
| GET | `/api/events?limit=50` | Agent 操作事件日志（最近 N 条，新→旧，供看板与断点恢复） |
| GET | `/api/brief` | 生成给 Agent 的任务简报（Markdown） |
| GET | `/api/export` | 打包 `data/` 为 `workbench/export_bundle.zip` |
| POST | `/api/import` | 用该 zip 覆盖恢复 |
| GET | `/api/resume/templates` | 简历模板列表 + 默认；`?name=xxx` 返回单个模板内容 |
| PUT/DELETE | `/api/resume/templates` | 设默认模板 / 新增用户模板 / 删除用户模板（内置不可删） |
| POST | `/api/resume/generate` | **按目标岗位直接生成 PDF**：body `{targetId?}`（默认 activeTarget）。从 `data/profile.json` 结构化渲染 HTML（不依赖 tailor.json、不调 LLM、不编造），自动拉起 9223 打印 Chrome 出 PDF，落盘 `data/resumes/{html,pdf}/`。返回 `{ok,targetId,targetTitle,fileStem,htmlUrl,pdfUrl,pdfBytes}` |
| GET | `/resumes/<sub>/<file>` | 静态暴露 `data/resumes/`（html/pdf/img），供前端预览与下载；PDF 内联打开（Content-Disposition: inline; filename*=UTF-8''…） |

示例：

```bash
curl -s localhost:8787/api/stats | python3 -m json.tool
curl -s -X POST localhost:8787/api/jobs -H 'Content-Type: application/json' \
  -d '[{"id":"abc123","company":"某公司","position":"AI Agent 工程师","city":"杭州","salary":"30-50K","jd":"..."}]'
curl -s -X POST localhost:8787/api/feedback -H 'Content-Type: application/json' \
  -d '{"applicationId":"某公司","type":"reply","signal":"positive","content":"HR 索要附件简历"}'
```

`/api/feedback` 的 `type` → 状态映射：
`reply→已回复`、`interview→约面试`、`interviewed→已面试`、`offer→已offer`、`reject→已拒绝`。

---

## 2. CLI（推荐给 Agent，无需服务在跑）

```bash
python3 workbench/cli.py status                  # 总览
python3 workbench/cli.py brief                   # 打印任务简报
python3 workbench/cli.py pending --limit 10      # 符合配置且未投递的岗位
python3 workbench/cli.py jobs list --city 杭州 --has-jd
python3 workbench/cli.py jobs import new_jobs.json
python3 workbench/cli.py app add --company X --position Y --city 杭州 --salary 30-45K --status 已沟通
python3 workbench/cli.py app status X 已回复
python3 workbench/cli.py app next                # 未投递公司白名单（去重用）
python3 workbench/cli.py feedback add --company X --type reply --content "HR 回复" --signal positive
python3 workbench/cli.py links                   # 技能↔项目 账实相符断链检测（R1-R4）
python3 workbench/cli.py analyze                 # 重算技能树与差距
```

---

## 2.5 Agent 接入声明

> **Agent 接入声明统一见项目根 `AGENTS.md` 第 6 节**：交互方式、run-batch 退出码契约
> （`0`=有活干 / `2`=无候选 / `3`=暂停中）、事件日志用法。本文件只保留 HTTP API 端点参考。

---

## 3. 直接读写文件（最稳，零耦合）

```
data/profile.json        # 履历。技能条目 v3 字段：
                         #   {name, group(professional|tools|soft|credentials), cluster,
                         #    evidenceLevel(0-5), projectRefs[], metrics[], statement, scenario}
                         # 顶层 skillEnvironment 为「日常工作环境」聚合行（豁免 R1 落点要求）
data/search_config.json  # 城市/关键词/薪资/排除词/节流
data/jobs.json           # 岗位池
data/applications.json   # 投递记录（status + timeline）
data/feedback.json       # 反馈
data/skills_tree.json    # 技能树/高频技能点（engine 生成）
data/gap_analysis.json   # 层级语义匹配报告（engine 调 jd_match 生成：requirements/dims/matchRate/cards）
workbench/lexicon.json             # 技能词库（可扩展其它岗位族）
workbench/scoring.py               # 技能评分模型（四分类 + 证据强度金字塔）
workbench/skill_links.py           # 断链检测（R1 存在性 / R2 一致性 / R3 完备性 / R4 真实性）
data/skill_links.json              # 断链检测结果
workbench/cities.json              # 城市码字典
data/strategy.json                 # 投递策略（周期/数量/时间窗/暂停条件）
data/logs/agent-events.jsonl       # Agent 操作事件日志（每次写操作追加一行）
workbench/templates/               # 空模板（App 资产）：新机器首次运行据此初始化 data/
```

写入约定：UTF-8、JSON、`indent=1`；`applications.json` 的 `status` 取值必须属于
`未沟通 / 已沟通 / 简历已发 / 已回复 / 约面试 / 已面试 / 已offer / 已拒绝`。

事件日志（`data/logs/agent-events.jsonl`）与并发锁（`data/logs/.data.lock`）的
使用说明统一见 `AGENTS.md` 第 6 节；读取事件用 `GET /api/events?limit=N`。

---

## 4. Agent 标准作业顺序

见 `AGENTS.md` 第 4 节（流程摘要）与 `skills/boss-zhipin-apply/SKILL.md`（完整细节）；
API 只负责数据读写，不承载作业编排。

> 去重是硬约束：投递前必须比对 `applications.json`，同一公司的同一岗位不得重复投递。
