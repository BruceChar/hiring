# 求职工作台 · Job Search Workbench

一个**零依赖、可迁移、与 Agent 解耦**的本地求职工作台：网页可视化 + 数据文件 + REST API + CLI。

## 快速开始

```bash
python3 workbench/server.py            # → http://127.0.0.1:8787
python3 workbench/server.py --port 9000
python3 workbench/selftest.py --http   # 自检（29 项）
```

只需要 Python 3.8+ 标准库，**不需要 pip install，不需要 node，不需要联网**。

## 页面

| 页面 | 作用 |
| --- | --- |
| 概览 | 投递漏斗、转化率、维度效果、自动评估洞察、数据完备度提示 |
| 个人履历 | **单列布局**：基本信息 → 教育 → 工作 → 项目 → **技能矩阵（证据化评分）** → 高级 JSON；保存按钮在右下角。教育/工作/项目/技能全部可增删改 |
| 搜岗 | **同一页**：顶部是「搜岗设置」（城市只填名字、关键词、薪资、排除词、批次），下方是「岗位池」（带独立筛选） |
| 投递与反馈 | **策略置顶**（周期/数量/时间窗/暂停条件/去重冷却 + crontab），下面是投递记录、状态流转与反馈录入 |
| 技能树 | **两个视角同页**：①我的技能全景（证据分 0-100 + 构成明细）②目标岗位技能树（覆盖率 + 必备/常见/加分/少见分档）。差距与学习是它的子页 |
| 差距与学习 | 技能树子页面：缺口排序 + 学习方案 + 已有优势 |
| 数据与迁移 | 导出/导入、数据文件说明、Agent 交互契约 |

**技能不靠自评**：`掌握度 = 证据引用(≤36) + 实践深度(≤32) + 可验证产出(≤16) + 时效性(≤16)`，
每一项都是可核对的事实（关联了哪些项目、做到哪一步、有没有可点开的产出、最近何时用过），
UI 会展示分数构成。岗位侧不用人工指定的重要度，改用**覆盖率**（在有技能标签/JD 的岗位中统计）并据此分档。

## 目录

```
workbench/
├── server.py        HTTP 服务 + REST API（标准库）
├── cli.py           Agent/人工命令行
├── engine.py        技能树聚合 + 差距分析 + 学习方案（叠加 jd_match 层级语义匹配）
├── lexicon.json     技能词库（8 领域 / 90 技能点，可替换为其它岗位族）
├── seed.py          从历史产物初始化数据
├── selftest.py      自检脚本
├── API.md           Agent 交互契约
├── cities.json      城市码字典（用户只填城市名）

（用户数据在项目根的 data/，与本目录分离）
└── web/             前端（原生 HTML/CSS/JS，无构建无 CDN）
```

## 与 Agent 交互（三种方式，同一份数据）

```bash
python3 workbench/cli.py status        # ① CLI
python3 workbench/cli.py pending --limit 10
python3 workbench/cli.py brief
curl -s localhost:8787/api/stats       # ② HTTP API（契约见 API.md）
# ③ 直接读写 data/*.json
```

标准作业顺序见 `API.md` 第 4 节；完整流程见 `../skills/boss-zhipin-apply/SKILL.md`。

## 迁移

1. 拷贝整个 `workbench/` 目录到新机器（数据在 `data/`，代码零依赖）。
2. `python3 workbench/server.py` 即可，新机器无需任何安装。
3. 也可在网页「数据与迁移」点 **导出 zip**，在新机器放入同目录后点 **从 zip 恢复**。

## 换行业怎么用

只替换 `workbench/lexicon.json`（按 `domains[].skills[]` 结构填目标岗位族的技能、别名、
重要度、学习方案），然后点「重新分析技能树」。其余流程、页面、数据完全复用。

## 数据文件

| 文件 | 作用 |
| --- | --- |
| `data/profile.json` | 通用个人履历（技能矩阵 level 1-5 + evidence） |
| `data/search_config.json` | 搜岗参数：城市/关键词/薪资/排除词/节流 |
| `data/jobs.json` | 岗位池（含 JD 原文与技能标签） |
| `data/applications.json` | 投递记录（status + timeline） |
| `data/feedback.json` | HR 反馈与评估信号 |
| `data/skills_tree.json` | 技能树/高频技能点（engine 生成，岗位池覆盖率口径） |
| `data/gap_analysis.json` | 层级语义匹配报告：需求向量 + 六色差距 + 匹配率双轴 + 四张卡（engine 调 jd_match 生成） |

状态取值：`未沟通 / 已沟通 / 简历已发 / 已回复 / 约面试 / 已面试 / 已offer / 已拒绝`。
