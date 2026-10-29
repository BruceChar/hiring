# 求职工作台 · Job Search Workbench

一个**可整体迁移、零依赖**的本地求职工作台：网页可视化 + 数据文件 + REST API + CLI。
覆盖「搜岗 → 定制简历 → 校验投递 → 反馈评估 → 技能差距与学习」的完整闭环。

> **给 Agent 看的入口是 [`AGENTS.md`](AGENTS.md)**；本文件给人看。

## 快速开始

```bash
python3 workbench/server.py        # → http://127.0.0.1:8787
python3 workbench/cli.py status    # 不开服务也能用
python3 workbench/selftest.py --http
```

只依赖 Python 3.8+ 标准库：**不用 pip、不用 node、不用联网**。

## 功能

| 页面 | 作用 |
| --- | --- |
| 概览 | 投递漏斗、转化率、维度效果、自动评估洞察、数据完备度提示 |
| 个人履历 | **单列布局**：基本信息 → 教育 → 工作 → 项目 → **技能矩阵（证据化评分）** → 高级 JSON；保存按钮在右下角。教育/工作/项目/技能全部可增删改 |
| 搜岗 | **同一页**：顶部是「搜岗设置」（城市只填名字、关键词、薪资、排除词、批次），下方是「岗位池」（带独立筛选） |
| 投递与反馈 | **策略置顶**（周期/数量/时间窗/暂停条件/去重冷却 + crontab），下面是投递记录、状态流转与反馈录入 |
| 技能树 | **两个视角同页**：①我的技能全景（证据分 0-100 + 构成明细）②目标岗位技能树（覆盖率 + 必备/常见/加分/少见分档）。差距与学习是它的子页 |
| 差距与学习 | 技能树子页面：缺口排序 + 学习方案 + 已有优势 |
| 数据与迁移 | 导出/导入、数据文件说明、Agent 交互契约 |

**技能区按四大分类组织**（`professional` 专业技能 / `tools` 工具与技术栈 / `soft` 通用能力 / `credentials` 语言与资质），
并使用**证据强度金字塔**：★★★★★ 量化结果 · ★★★★ 规模复杂度 · ★★★ 角色职责 · ★★ 外部验证 · ★ 时长频率 · ☆ 证书课程。

**证据分 = 强度分(≤50) + 项目落点(≤30) + 量化结果(≤20)**，每一项都可核对，UI 展示构成明细。
同时做**账实相符（断链检测）**：技能必须能落到具体项目上（R1 存在性 / R2 一致性 / R3 完备性 / R4 真实性），
断链条目会给出「补证据 → 降格表述 → 删除」的修复建议。
岗位侧不用人工指定的重要度，改用**覆盖率**（在有技能标签/JD 的岗位中统计）并据此分档。

## 项目结构：代码与数据分离

```
workbench/  skills/  tools/  AGENTS.md   ← 应用（可独立迁移）
data/                                    ← 我的数据（可独立迁移/备份）
├── profile.json  search_config.json  strategy.json
├── jobs.json  applications.json  feedback.json
├── skills_tree.json  gap_analysis.json
├── resumes/  exports/  raw/  logs/
```

`data/` 缺失时首次启动会自动从 `workbench/templates/` 初始化空文件，
然后用 `python3 workbench/cli.py onboarding` 看该补什么——它会告诉你「该问用户什么」。

## 迁移

```bash
# 迁移应用
cp -r workbench skills tools AGENTS.md README.md  <新目录>/
# 迁移我的数据
cp -r data  <新目录>/
```

在 `data/` 缺失的新机器上：`python3 workbench/server.py` 会自动初始化，
或先跑 `python3 workbench/cli.py onboarding` 按提示补齐履历与策略。

## 无人值守投递

```bash
python3 workbench/cli.py schedule --cron     # 生成 crontab 行
```

策略（`data/strategy.json`）里的周期、时间窗、数量上限、暂停条件会被写进
`GET /api/brief` 的任务简报，任何 Agent 接手都必须遵守。
**给 Agent 的接入声明**（交互方式、run-batch 退出码契约、事件日志）统一见
[`AGENTS.md`](AGENTS.md) 第 6 节。

## 按 JD 定制简历（LLM，可选）

```bash
LLM_API_KEY=sk-xxx LLM_MODEL=deepseek-chat python3 tools/agent_tailor.py <job_id>
```

读 JD → LLM 产出定制条目 → 不编造门禁（标题/公司名/数字逐项比对固定事实）→ 写盘 →
自动渲染 HTML → Chrome 出 PDF → 高清 PNG → validate 门禁，全链路一条命令。
无 key 时可用 `--from-json item.json` 离线通道，或直接编辑 `data/tailor.json`。


## 换行业

只替换 `workbench/lexicon.json`（技能词库结构：`domains[].skills[]`，含别名/重要度/学习方案），
然后点「重新分析技能树」。流程、页面、数据结构全部复用。
