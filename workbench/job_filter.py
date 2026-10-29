"""岗位池清洗过滤器：招聘类型过滤（校招剔除）+ 目标相关性过滤（错配岗位剔除/剥离归属）。

纯规则可复现，供 server（POST /api/jobs/prune + 采集收尾自动清洗）与 cli.py jobs prune 调用。
设计依据用户反馈：岗位池混入校招岗、以及与当前目标（如 Agent系统工程师）不匹配的
模型训练/算法研究向岗位（如「大模型应用开发专家」「LLM后训练算法工程师」）。

规则（全部可复算）：
1. 校招过滤（全局）：当 recruit_types 不含「校招」时，tags/标题/JD 命中校招强特征 → 剔除。
2. 目标错配（按当前目标）：标题命中训练/模型向模式且无保护词（agent/智能体/应用/工程/开发）→
   - 单目标岗位直接剔除；多目标岗位仅剥离当前目标归属（不误伤其他目标）。
"""
import json
import os
import re
import shutil
import datetime

# ---- 校招强特征（recruit_types 为社招时剔除）----
# 只信标题 + BOSS tags 显式标记；⚠️ 不用 JD 全文——社招 JD 常含「实习经历/面向 N 届/接受应届」等字样，
# 会把正常社招岗误杀（已实测：JD 关键词误剔 20+ 条）。
_SCHOOL_TAGS = ("校招", "在校", "应届", "实习")
# 实习时长标记：BOSS tags 里的「5天/周/2个月」为实习岗特征（实例如「AI应用工程师 | 比特无限」）
_SCHOOL_TAG_RE = re.compile(r"\d+\s*天|\d+\s*个月|实习")
# 标题特征：⚠️ 不含裸「应届」——「接受应届」是社招向岗位（非凸科技等），误杀；
# 「20xx届/N届」才是校招。⚠️ 「不是27校招岗」这类否定标题（智慧芽）用 _NOT_SCHOOL_RE 保护。
_SCHOOL_RE = re.compile(
    r"校招|校园|实习|面向\s*20\d{2}\s*届|20\d{2}\s*届|【\s*20\d{2}届|(^|[\s·\-【])\d{4}届"
)
_NOT_SCHOOL_RE = re.compile(r"不是\s*.{0,12}(校招|应届|实习)")

# ---- 目标错配：训练/模型研究向标题模式 ----
_TRAIN_RE = re.compile(
    r"后训练|Post[- ]?training|预训练|训练基础架构|训练推理|训练工程|基础模型算法|"
    r"模型微调|强化学习|Reward ?Model|大模型应用开发专家"
)
# 纯算法研究岗：含「算法工程师」且无保护词（Agent 应用方向常见「Agent/智能体/应用/工程/开发」）
_ALGO_RE = re.compile(r"算法工程师|LLM算法|大模型算法|AIGC|多模态|视觉算法|NLP算法")
_PROTECT_RE = re.compile(r"agent|智能体|应用|工程|开发|平台|产品", re.IGNORECASE)


def _is_school(pos, tags, jd):
    if any(t in tags for t in _SCHOOL_TAGS):
        return True
    if _SCHOOL_TAG_RE.search(tags):
        return True
    blob = "%s %s" % (pos, tags)
    if _NOT_SCHOOL_RE.search(blob):
        return False
    return bool(_SCHOOL_RE.search(blob))


def _is_mismatch(pos):
    if not pos:
        return False
    if _TRAIN_RE.search(pos):
        return True
    if _ALGO_RE.search(pos) and not _PROTECT_RE.search(pos):
        return True
    return False


def prune_jobs(jobs, target_id, recruit_types=None, target_title=""):
    """清洗岗位池。

    jobs: 岗位列表（可变副本由调用方保证）。
    target_id: 当前目标 id（只清洗该目标的错配岗；None 时跳过目标错配）。
    recruit_types: 招聘类型配置；不含「校招」时执行校招过滤（None 按「未配校招」处理）。
    返回 (kept_jobs, report)。report 含明细，供事件日志与前端展示。
    """
    keep_school = bool(recruit_types and "校招" in recruit_types)
    report = {
        "at": datetime.datetime.now().replace(microsecond=0).isoformat(),
        "target": target_id,
        "school_removed": [],
        "mismatch_removed": [],
        "detached": [],   # 多目标岗位剥离当前目标归属（岗位保留）
        "kept": 0,
    }
    kept = []
    for j in jobs:
        pos = j.get("position") or j.get("title") or ""
        tags = " ".join(j.get("skillTags") or []) or ""
        jd = (j.get("jd") or "")[:800]
        ids = list(j.get("targetIds") or ([] if j.get("targetId") is None else [j.get("targetId")]))
        row = {"id": j.get("id"), "position": pos, "company": j.get("company") or ""}
        # 1) 校招过滤（全局）
        if not keep_school and _is_school(pos, tags, jd):
            report["school_removed"].append(row)
            continue
        # 2) 目标错配（仅当前目标）
        if target_id and target_id in ids and _is_mismatch(pos):
            if len(ids) > 1:
                ids.remove(target_id)
                j["targetIds"] = ids
                report["detached"].append(row)
            else:
                report["mismatch_removed"].append(row)
                continue
        kept.append(j)
    report["kept"] = len(kept)
    report["removed_total"] = len(report["school_removed"]) + len(report["mismatch_removed"])
    return kept, report


def run_prune(data_dir, profile=None, config=None):
    """独立入口：读 jobs.json → 备份 → 清洗 → 落盘。返回 (ok, report, error)。"""
    jobs_path = os.path.join(data_dir, "jobs.json")
    if not os.path.exists(jobs_path):
        return False, None, "jobs.json 不存在"
    try:
        with open(jobs_path, encoding="utf-8") as f:
            jobs = json.load(f)
    except Exception as e:
        return False, None, "读取 jobs.json 失败：%s" % e
    if not jobs:
        return False, None, "岗位池为空"
    prof = profile or _load_json(os.path.join(data_dir, "profile.json"), {})
    cfg = config or _load_json(os.path.join(data_dir, "search_config.json"), {})
    active_id = prof.get("activeTarget")
    active_title = ""
    for t in (prof.get("targets") or []):
        if t.get("id") == active_id:
            active_title = t.get("title") or ""
            break
    recruit_types = cfg.get("recruit_types") or cfg.get("recruitTypes") or []
    kept, report = prune_jobs(jobs, active_id, recruit_types=recruit_types, target_title=active_title)
    report["active_title"] = active_title
    # 备份后再落盘（可恢复）
    if report["removed_total"] or report["detached"]:
        raw = os.path.join(data_dir, "raw")
        os.makedirs(raw, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = os.path.join(raw, "jobs_prune_backup_%s.json" % ts)
        shutil.copy2(jobs_path, backup)
        report["backup"] = backup
        with open(jobs_path, "w", encoding="utf-8") as f:
            json.dump(kept, f, ensure_ascii=False, indent=1)
    else:
        report["backup"] = None
    return True, report, None


def _load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


if __name__ == "__main__":
    import sys
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data = os.path.join(ROOT, "data")
    ok, rep, err = run_prune(data)
    if not ok:
        print("prune 失败：%s" % err)
        sys.exit(1)
    print(json.dumps(rep, ensure_ascii=False, indent=1))
