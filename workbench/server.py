#!/usr/bin/env python3
"""求职工作台 —— 零依赖本地 Web 服务（Python3 标准库）。

启动：
    python3 workbench/server.py            # http://127.0.0.1:8787
    python3 workbench/server.py --port 9000

设计目标：
  * 完全独立于任何 Agent / 框架，只依赖 Python3 标准库；
  * 数据全部落在 workbench/data/*.json，可直接跟 Skill 一起拷贝迁移；
  * 同时提供 REST API，任何 Agent（Claude Code / Codex / DSH …）都能读写。
"""
import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import zipfile
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote

import events
from events import append_event, read_events, data_lock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)          # 项目根：代码与用户数据分离的边界
DATA = os.path.join(ROOT, "data")     # ★ 用户数据目录（可单独迁移/备份）
WEB = os.path.join(HERE, "web")
TPL_USER = os.path.join(DATA, "templates", "resume")                    # 用户添加的简历模板（优先）
TPL_BUILTIN = os.path.join(ROOT, "workbench", "templates", "resume")    # 内置简历模板
TPL_SETTING = os.path.join(DATA, "resume_template.json")                # 默认模板选择
MIME = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8", ".json": "application/json; charset=utf-8",
        ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon",
        ".pdf": "application/pdf"}

RESUMES_DIR = os.path.join(DATA, "resumes")          # 简历产物根目录（html/pdf/img 子目录）

STATUS_FLOW = ["未沟通", "已沟通", "简历已发", "已回复", "约面试", "已面试", "已offer", "已拒绝"]

# ---- 采集会话状态（后台线程分步采集，前端轮询 status 实时上屏）----
_collect_lock = threading.Lock()
_COLLECT = {"running": False, "phase": "idle", "done": 0, "total": 0, "added": 0, "updated": 0,
            "excluded": 0, "lastAt": None, "error": None, "salary": None, "recruitType": None, "kws": []}


def _collect_status():
    with _collect_lock:
        return dict(_COLLECT)


# BOSS 列表页薪资混淆字形 → 真实数字（私有字体码位映射，全局固定，5 样本实测验证）
_SALARY_MAP = {0xE031: "0", 0xE032: "1", 0xE033: "2", 0xE034: "3", 0xE035: "4",
               0xE036: "5", 0xE037: "6", 0xE038: "7", 0xE039: "8", 0xE03A: "9"}


def _decode_salary(s):
    """把 BOSS 混淆字形薪资解码为明文（如 '\\ue035\\ue031-\\ue038\\ue031K·\\ue032\\ue037薪' → '40-70K·16薪'）。"""
    if not s or not isinstance(s, str):
        return s
    out = []
    for ch in s:
        out.append(_SALARY_MAP.get(ord(ch), ch))
    return "".join(out)


def _match_level(j, kws):
    """岗位 × 目标关键词 相关度：position 命中=strong；tags/JD 命中=weak；否则 none。"""
    if not kws:
        return "none"
    pos = str(j.get("position") or "").lower()
    tags = " ".join(str(x) for x in (j.get("skillTags") or j.get("tags") or [])).lower()
    jd = str(j.get("jd") or "").lower()
    for k in kws:
        k = k.lower()
        if k and k in pos:
            return "strong"
        if k and (k in tags or k in jd):
            return "weak"
    return "none"


_DAEMON_CACHE = {"at": 0.0, "logged": None}


def _upsert_jobs(items, act):
    """按 id upsert 落盘（id = BOSS encryptJobId）。返回 (added, updated, added_ids)。"""
    import time as _time
    added = updated = 0
    added_ids = []
    with data_lock():
        jobs = read_json("jobs.json", [])
        idx = {j.get("id"): i for i, j in enumerate(jobs)}
        ts = now()
        for it in items:
            jid = it.get("id")
            if not jid:
                continue
            it.setdefault("position", it.get("name") or it.get("position"))
            if it.get("salary"):
                it["salary"] = _decode_salary(it["salary"])  # 混淆字形 → 明文（全局固定映射）
            if it.get("tags") and not it.get("skillTags"):
                it["skillTags"] = [s.strip() for s in str(it["tags"]).split("/") if s.strip()]
            h = it.get("href")
            if h and isinstance(h, str) and h.startswith("/"):
                it["href"] = "https://www.zhipin.com" + h  # 相对路径→完整 URL（JD 回填用）
            if jid in idx:
                old = jobs[idx[jid]]
                tids = list(dict.fromkeys(list(old.get("targetIds") or []) + [act]))
                old.update({k: v for k, v in it.items() if k not in ("targetId", "targetIds", "firstSeenAt")})
                old.setdefault("targetId", act)
                old["targetIds"] = tids
                old["lastSeenAt"] = ts
                updated += 1
            else:
                it.setdefault("targetId", act)
                it.setdefault("targetIds", [act])
                it.setdefault("firstSeenAt", ts)
                it["lastSeenAt"] = ts
                it.setdefault("collectedAt", ts)
                jobs.append(it)
                idx[jid] = len(jobs) - 1
                added += 1
                added_ids.append(jid)
        write_json("jobs.json", jobs)
    return added, updated, added_ids


def _salary_ok(raw, cfg):
    """详情页明文薪资是否与配置区间有重叠（10-15K vs 30-50K → False；20-40K vs 30-50K → True）。

    单位换算：元/天 ×20 → 月 K；元/时 ×160 → 月 K；元/月 ÷1000 → 月 K；万 → ×10 K。解析不出（面议等）→ 保留待人工。
    """
    try:
        cmin = float(cfg.get("min") or 0)
        cmax = float(cfg.get("max") or 1000)
    except (TypeError, ValueError):
        return True
    m = re.search(r"(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)\s*(K|k|元/天|元/时|元/月|万)?", raw or "")
    if not m:
        return True
    lo, hi = float(m.group(1)), float(m.group(2))
    u = m.group(3) or "K"
    if u == "元/天":
        lo, hi = lo * 20 / 1000, hi * 20 / 1000
    elif u == "元/时":
        lo, hi = lo * 160 / 1000, hi * 160 / 1000
    elif u == "元/月":
        lo, hi = lo / 1000, hi / 1000
    elif u == "万":
        lo, hi = lo * 10, hi * 10
    return lo <= cmax and hi >= cmin


def _collect_worker(kws, city_codes, salary, recruitType, act, cur):
    """后台分步采集：阶段1 列表批量并行（collectNavs，3 tab 并发 + 动态节流，按城市分批实时上屏）；
    阶段2 列表薪资直判剔除低薪 → 新增岗位批量并行回填（collectDetails，4 tab 并发）明文薪资 + JD；
    命中平台风控信号立即停止本轮。"""
    import time as _time
    node_bin = shutil.which("node")
    boss_mjs = os.path.join(HERE, "..", "tools", "boss-daemon.mjs")
    tot_added = tot_updated = 0
    try:
        cfg = read_json("search_config.json", {})
        s_cfg = (cfg.get("salary") or {})
        risk_stop = False
        # ---- 阶段1：列表批量并行采集（按城市分批 ≤3，每批 3 tab 并发 + 动态节流，返回后实时上屏）----
        pending_ids = []
        city_items = list(city_codes.items())
        for ci in range(0, len(city_items), 3):
            cities = dict(city_items[ci:ci + 3])
            try:
                proc = subprocess.run([node_bin, boss_mjs, "collectNavs",
                                       json.dumps({"keywords": list(kws), "cities": cities,
                                                   "salary": salary, "recruitType": recruitType,
                                                   "concurrency": 3, "navWait": 8000, "stepWait": 3000})],
                                      capture_output=True, text=True, timeout=180)
                try:
                    out = json.loads(proc.stdout[proc.stdout.index("{"):proc.stdout.rindex("}") + 1])
                    items = out.get("jobs") or []
                    risk_stop = bool(out.get("risk"))
                except Exception:
                    items = []
                if items:
                    a, u, aids = _upsert_jobs(items, act)
                    tot_added += a
                    tot_updated += u
                    pending_ids.extend(aids)
                if risk_stop:
                    with _collect_lock:
                        _COLLECT["error"] = "平台风控信号（环境异常/安全验证），已停止本轮"
                    break
            except Exception as e:
                with _collect_lock:
                    _COLLECT["error"] = str(e)[:200]
            with _collect_lock:
                _COLLECT["phase"] = "list"
                _COLLECT["done"] += 1
                _COLLECT["added"] = tot_added
                _COLLECT["updated"] = tot_updated
                _COLLECT["lastAt"] = now()
            _time.sleep(0.2)
        # ---- 阶段2：详情回填（先列表薪资直判剔除，再批量并行回填）----
        with _collect_lock:
            _COLLECT["phase"] = "detail"
            _COLLECT["total"] = _COLLECT["done"] + len(pending_ids)
        removed_low = 0
        # 2a. 列表薪资直判：阶段1 已提取 .job-salary 明文，与配置区间无重叠 → 直接移除，不进详情（省 13s/岗）
        kept = []
        for jid in pending_ids:
            job = None
            with data_lock():
                for j in read_json("jobs.json", []):
                    if j.get("id") == jid:
                        job = j
                        break
            if not job or not job.get("href"):
                with _collect_lock:
                    _COLLECT["done"] += 1
                continue
            ls = (job.get("salary") or "").strip()
            if ls and _salary_ok(ls, s_cfg) is False:
                with data_lock():
                    jobs2 = [x for x in read_json("jobs.json", []) if x.get("id") != jid]
                    write_json("jobs.json", jobs2)
                removed_low += 1
                with _collect_lock:
                    _COLLECT["done"] += 1
                    _COLLECT["excluded"] = removed_low
                    _COLLECT["lastAt"] = now()
                continue
            kept.append((jid, job["href"]))
        # 2b. 批量并行详情回填（每批 ≤12 岗，4 tab 并发，动态节流）
        for bi in range(0, len(kept), 12):
            if risk_stop:
                break
            batch = kept[bi:bi + 12]
            try:
                proc = subprocess.run([node_bin, boss_mjs, "collectDetails",
                                       json.dumps({"jobs": [{"id": jid, "href": href} for jid, href in batch],
                                                   "wait": 9000, "concurrency": 4})],
                                      capture_output=True, text=True, timeout=240)
                try:
                    out = json.loads(proc.stdout[proc.stdout.index("{"):proc.stdout.rindex("}") + 1])
                    items = out.get("items") or []
                    risk_stop = bool(out.get("risk"))
                except Exception:
                    items = []
                for it in items:
                    jid = it.get("id")
                    dv = it
                    job = None
                    with data_lock():
                        for j in read_json("jobs.json", []):
                            if j.get("id") == jid:
                                job = j
                                break
                    if not job:
                        with _collect_lock:
                            _COLLECT["done"] += 1
                        continue
                    if dv.get("salary"):
                        job["salary"] = _decode_salary(dv["salary"])
                    if dv.get("activity"):
                        job["activity"] = dv["activity"]
                    if dv.get("jd"):
                        job["jd"] = dv["jd"]
                    # 薪资过滤：明文区间与配置区间无重叠 → 垃圾岗移除
                    if dv.get("salary") and not _salary_ok(job["salary"], s_cfg):
                        with data_lock():
                            jobs2 = [x for x in read_json("jobs.json", []) if x.get("id") != jid]
                            write_json("jobs.json", jobs2)
                        removed_low += 1
                    else:
                        with data_lock():
                            jobs2 = read_json("jobs.json", [])
                            for j in jobs2:
                                if j.get("id") == jid:
                                    j.update({"salary": job["salary"], "jd": job.get("jd")})
                                    break
                            write_json("jobs.json", jobs2)
                    with _collect_lock:
                        _COLLECT["done"] += 1
                        _COLLECT["added"] = tot_added
                        _COLLECT["updated"] = tot_updated
                        _COLLECT["excluded"] = removed_low
                        _COLLECT["lastAt"] = now()
                    _time.sleep(0.2)
            except Exception as e:
                with _collect_lock:
                    _COLLECT["error"] = str(e)[:200]
            if risk_stop:
                with _collect_lock:
                    _COLLECT["error"] = "平台风控信号（环境异常/安全验证），已停止本轮"
                break
        with _collect_lock:
            _COLLECT["running"] = False
            _COLLECT["phase"] = "done"
        # 采集收尾自动清洗：剔除校招岗与当前目标错配岗（规则见 job_filter.py，纯可复现）
        try:
            sys.path.insert(0, HERE)
            import job_filter
            p_ok, p_rep, p_err = job_filter.run_prune(DATA)
            if p_ok and (p_rep.get("removed_total") or p_rep.get("detached")):
                removed_low += p_rep["removed_total"]
                with _collect_lock:
                    _COLLECT["excluded"] = removed_low
                append_event("jobs.prune", "采集后清洗：剔除校招 %d、错配 %d、剥离归属 %d"
                             % (len(p_rep["school_removed"]), len(p_rep["mismatch_removed"]),
                                len(p_rep["detached"])), actor="api",
                             payload={"school": len(p_rep["school_removed"]),
                                      "mismatch": len(p_rep["mismatch_removed"]),
                                      "detached": len(p_rep["detached"])})
        except Exception as e:  # pragma: no cover
            with _collect_lock:
                _COLLECT["error"] = ("清洗岗位池失败：%s" % e)[:200]
        write_json("raw/last_collect.json", {"at": _time.time(), "target": act,
                                             "added": tot_added, "updated": tot_updated,
                                             "excluded": removed_low})
        append_event("jobs.collect", f"目标 {cur.get('title')} 采集完成：新增 {tot_added}，更新 {tot_updated}，低薪移除 {removed_low}",
                     actor="api", payload={"target": act, "added": tot_added, "updated": tot_updated,
                                           "excluded": removed_low,
                                           "kws": list(kws), "salary": salary, "recruitType": recruitType})
    except Exception as e:
        with _collect_lock:
            _COLLECT["running"] = False
            _COLLECT["phase"] = "error"
            _COLLECT["error"] = str(e)[:200]


def now():
    return datetime.now().isoformat(timespec="seconds")


RECRUIT_KEYWORDS = ("校招", "校园招聘", "应届", "在校")


def _text(*values):
    """把任意字段（str/list/None）拼成可匹配的文本。"""
    out = []
    for v in values:
        if isinstance(v, str):
            out.append(v)
        elif isinstance(v, (list, tuple)):
            out.extend(str(x) for x in v if x is not None)
        elif v is not None:
            out.append(str(v))
    return " ".join(out)


def infer_recruit_type(job):
    """按岗位文本判断 校招/社招（没有显式 recruitType 字段时的兜底口径）。

    命中 校招/校园招聘/应届/在校（如经验「在校/应届」、标签「校招」）→ 校招，其余默认社招。
    """
    text = _text(job.get("position"), job.get("skillTags"), job.get("jd"), job.get("experience"))
    return "校招" if any(k in text for k in RECRUIT_KEYWORDS) else "社招"


def read_json(name, default):
    p = os.path.join(DATA, name)
    if not os.path.exists(p):
        return default
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return default


# ---- 主题设置（data/settings.json）----
# 预设主题：侧栏背景/文字 + 品牌色 + 页面背景。字段与 style.css 的 CSS 变量一一对应。
THEME_PRESETS = {
    "灰紫": {"sideBg": "#5a5480", "sideText": "#e6e2f5", "sideText2": "#d3cdee", "sideMuted": "#b3abdd",
            "brand": "#8b5cf6", "brand2": "#a855f7", "brandSoft": "#f3f0ff", "bg": "#f4f6f8"},
    "亮紫": {"sideBg": "#6d28d9", "sideText": "#ede9fe", "sideText2": "#ddd6fe", "sideMuted": "#c4b5fd",
            "brand": "#7c3aed", "brand2": "#a855f7", "brandSoft": "#f3eefe", "bg": "#f7f5fc"},
    "深紫": {"sideBg": "#3b2a5c", "sideText": "#e2dcf2", "sideText2": "#c9c0e4", "sideMuted": "#9d93c4",
            "brand": "#7c3aed", "brand2": "#8b5cf6", "brandSoft": "#efeaf9", "bg": "#f4f2f9"},
    "墨绿": {"sideBg": "#0f2f38", "sideText": "#dbe9ec", "sideText2": "#c6dbe0", "sideMuted": "#8fb0b8",
            "brand": "#16697a", "brand2": "#16b39a", "brandSoft": "#e6f2f4", "bg": "#f4f6f8"},
    "深蓝": {"sideBg": "#1e3a5f", "sideText": "#dbe9f5", "sideText2": "#c6d7e8", "sideMuted": "#93a7bd",
            "brand": "#2563eb", "brand2": "#3b82f6", "brandSoft": "#eff6ff", "bg": "#f4f7fb"},
}


def read_settings():
    """当前主题（用户自定义合并到默认灰紫之上）+ 全部预设。返回 {theme, presetName, presets}。"""
    s = read_json("settings.json", {}) or {}
    base = dict(THEME_PRESETS["灰紫"])
    theme = dict(base)
    theme.update(s.get("theme") or {})
    name = "自定义"
    for pn, pv in THEME_PRESETS.items():
        if theme == dict(base, **pv):
            name = pn
            break
    return {"theme": theme, "presetName": name, "presets": THEME_PRESETS, "file": "data/settings.json"}


def save_settings(theme):
    s = read_json("settings.json", {}) or {}
    s["theme"] = theme
    write_json("settings.json", s)


def write_json(name, obj):
    os.makedirs(DATA, exist_ok=True)
    p = os.path.join(DATA, name)
    tmp = p + ".tmp"
    json.dump(obj, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(tmp, p)
    return {"ok": True, "file": name, "at": now()}


def _daemon_pid():
    """boss-daemon 存活探测：读 daemon 自写的 pid 文件 + kill(pid,0) + 进程命令名校验（防 pid 复用误报）"""
    try:
        pf = os.path.join(DATA, "raw", "daemon.pid")
        if not os.path.exists(pf):
            return None
        pid = int(open(pf).read().strip())
        os.kill(pid, 0)
        cmd = subprocess.run(["ps", "-p", str(pid), "-o", "command="],
                             capture_output=True, text=True, timeout=5).stdout
        if "boss-daemon.mjs" not in cmd:   # pid 已被复用成别的进程 → 不算存活
            return None
        return str(pid)
    except (ValueError, ProcessLookupError):
        return None
    except Exception:
        return None


CITIES_PATH = os.path.join(HERE, "cities.json")
TEMPLATES = os.path.join(HERE, "templates")   # ★ 模板属于 App 资产，随代码迁移


# ------------------------------------------------------- data bootstrapping --
def load_cities():
    try:
        return json.load(open(CITIES_PATH, encoding="utf-8"))
    except Exception:
        return {"cities": {}, "aliases": {}}


def resolve_city_code(name, dict_=None):
    """城市名 → BOSS 城市码。用户只需填名字，码由系统补。"""
    d = dict_ or load_cities()
    name = (name or "").strip()
    if not name:
        return "", False
    if name in d.get("cities", {}):
        return d["cities"][name], True
    for canon, aliases in (d.get("aliases") or {}).items():
        if name in aliases:
            return d["cities"].get(canon, ""), True
    return "", False


def autofill_city_codes(cfg, d=None):
    d = d or load_cities()
    for c in cfg.get("cities", []) or []:
        code, ok = resolve_city_code(c.get("name"), d)
        if ok:
            c["code"], c["resolved"] = code, True
        else:
            c["code"] = c.get("code", "")
            c["resolved"] = bool(c["code"])
    return cfg


REQUIRED_FILES = ["profile.json", "search_config.json", "strategy.json", "jobs.json",
                  "applications.json", "feedback.json"]


def ensure_data_files():
    """首次运行/迁移到新机器：缺失的数据文件从 templates 初始化。"""
    os.makedirs(TEMPLATES, exist_ok=True)
    for name in REQUIRED_FILES:
        p = os.path.join(DATA, name)
        if os.path.exists(p):
            continue
        t = os.path.join(TEMPLATES, name)
        if os.path.exists(t):
            shutil.copyfile(t, p)
        else:
            write_json(name, [] if name.endswith("s.json") else {})
    # 搜岗配置缺少城市码时自动补全
    cfg = read_json("search_config.json", {})
    if cfg.get("cities"):
        autofill_city_codes(cfg)
        write_json("search_config.json", cfg)


def _norm(s):
    return "".join(str(s or "").lower().split())


def attach_match(prof, tree):
    """技能 → 目标岗位匹配度：按技能树的覆盖率回填（名称/别名匹配，取最高）。"""
    idx = []
    for d in tree.get("domains", []) or []:
        for sk in d.get("skills", []) or []:
            for lab in [sk.get("name")] + list(sk.get("aliases") or []):
                if lab:
                    idx.append((_norm(lab), sk))
    for s in prof.get("skills", []) or []:
        key = _norm(s.get("name"))
        hit = None
        for lab, sk in idx:
            if not lab or not key:
                continue
            if lab == key or (len(key) >= 3 and (key in lab or lab in key)):
                if hit is None or (sk.get("coverage") or 0) > (hit.get("coverage") or 0):
                    hit = sk
        if hit:
            s["_match"] = {"coverage": hit.get("coverage"), "tier": hit.get("coverageTier"),
                           "matchedSkill": hit.get("name")}
    return prof


def decorate_profile(prof):
    try:
        import scoring
        for sk in prof.get("skills", []) or []:
            sk["_score"] = scoring.evidence_score(sk)
        prof["_health"] = scoring.profile_health(prof)
    except Exception:
        pass
    return attach_match(prof, read_json("skills_tree.json", {}))


def _active_keywords(prof):
    """当前选中目标的搜索关键词。关键词归目标所有；未填关键词时回退到目标岗位名（如「区块链开发」），
    再回退旧 search_config.keywords"""
    act = prof.get("activeTarget")
    t = next((x for x in (prof.get("targets") or []) if x.get("id") == act), None)
    kws = (t or {}).get("keywords") or []
    if kws:
        return kws
    title = (t or {}).get("title")
    if title:
        return [title]
    cfg = read_json("search_config.json", {})
    return cfg.get("keywords") or []


def build_onboarding():
    """数据完备度清单：缺什么、让 Agent 提示用户补什么。"""
    prof = read_json("profile.json", {})
    cfg = read_json("search_config.json", {})
    st = read_json("strategy.json", {})
    jobs = read_json("jobs.json", [])
    apps = read_json("applications.json", [])
    items = [
        {"key": "profile", "label": "个人履历", "file": "data/profile.json",
         "done": bool(prof.get("name") and prof.get("skills")),
         "ask": "请提供姓名、联系方式、所在城市、工作年限、教育/工作/项目经历，以及技能清单（每项含熟练度 1-5 与可验证出处）。我帮你录入。"},
        {"key": "search_config", "label": "搜岗配置", "file": "data/search_config.json",
         "done": bool(_active_keywords(prof) and cfg.get("cities")),
         "ask": "请告诉我：目标城市（只填城市名即可）、岗位关键词（在「搜岗 → 目标岗位」里设置）、薪资区间、本批投递数量。"},
        {"key": "strategy", "label": "投递策略", "file": "data/strategy.json",
         "done": bool(st and st.get("batch_size") is not None and st.get("mode")),
         "ask": "请确认投递策略：周期（每天/每周/间隔小时）、每次岗位数、允许投递的时间段、是否需要你确认名单后再投、连续无回复多少家后暂停。"},
        {"key": "jobs", "label": "岗位池", "file": "data/jobs.json",
         "done": len(jobs) > 0,
         "ask": "岗位池为空。确认搜岗配置后，我可以按配置采集岗位。"},
    ]
    return {
        "complete": all(i["done"] for i in items),
        "items": items,
        "missing": [i for i in items if not i["done"]],
        "stats": {"jobs": len(jobs), "applications": len(apps)},
        "agentInstruction": "若存在 missing 项，先用对话向用户逐项询问并写入对应文件，再开始采集与投递。",
    }


# --------------------------------------------------------------- analytics --
def compute_stats():
    apps = read_json("applications.json", [])
    jobs = read_json("jobs.json", [])
    fb = read_json("feedback.json", [])
    cfg = read_json("search_config.json", {})
    prof = read_json("profile.json", {})

    def count(st):
        return sum(1 for a in apps if a.get("status") == st)

    reached = lambda *names: sum(1 for a in apps if a.get("status") in names)
    contacted = reached("已沟通", "简历已发", "已回复", "约面试", "已面试", "已offer", "已拒绝")
    resume = reached("简历已发", "已回复", "约面试", "已面试", "已offer", "已拒绝")
    replied = reached("已回复", "约面试", "已面试", "已offer", "已拒绝")
    interview = reached("约面试", "已面试", "已offer")
    pct = lambda a, b: round(a / b * 100, 1) if b else 0.0

    def breakdown(field):
        buckets = {}
        for a in apps:
            k = a.get(field) or "未标注"
            b = buckets.setdefault(k, {"total": 0, "replied": 0, "interview": 0})
            b["total"] += 1
            if a.get("status") in ("已回复", "约面试", "已面试", "已offer", "已拒绝"):
                b["replied"] += 1
            if a.get("status") in ("约面试", "已面试", "已offer"):
                b["interview"] += 1
        for k, v in buckets.items():
            v["replyRate"] = pct(v["replied"], v["total"])
            v["interviewRate"] = pct(v["interview"], v["total"])
        return dict(sorted(buckets.items(), key=lambda x: -x[1]["total"]))

    stats = {
        "generatedAt": now(),
        "funnel": [
            {"stage": "岗位池", "value": len(jobs)},
            {"stage": "已沟通", "value": contacted},
            {"stage": "简历已发", "value": resume},
            {"stage": "已回复", "value": replied},
            {"stage": "约面试", "value": interview},
            {"stage": "已面试", "value": reached("已面试", "已offer")},
            {"stage": "offer", "value": count("已offer")},
        ],
        "rates": {
            "投递转化率": pct(contacted, len(jobs)),
            "回复率": pct(replied, resume) if resume else 0.0,
            "面试转化率": pct(interview, replied) if replied else 0.0,
            "简历送达率": pct(resume, contacted),
        },
        "statusCounts": {s: count(s) for s in STATUS_FLOW},
        "breakdowns": {"city": breakdown("city"), "activity": breakdown("activity"),
                       "salary": breakdown("salary"), "recruiter": breakdown("recruiter")},
        "feedback": {"total": len(fb),
                     "positive": sum(1 for f in fb if f.get("signal") == "positive"),
                     "negative": sum(1 for f in fb if f.get("signal") == "negative")},
        "configSummary": {"cities": [c.get("name") for c in cfg.get("cities", [])],
                          "keywords": _active_keywords(prof),
                          "salary": cfg.get("salary", {}),
                          "batch_size": cfg.get("batch_size"),
                          "recruit_types": cfg.get("recruit_types", [])},
        "recentFeedback": sorted(fb, key=lambda x: x.get("at", ""), reverse=True)[:10],
    }
    stats["insights"] = build_insights(stats)
    return stats


def build_insights(stats):
    """Rule-based evaluation: what the data says about where to focus next."""
    out = []
    apps_total = stats["funnel"][1]["value"]
    replied = stats["funnel"][3]["value"]
    if apps_total == 0:
        return [{"level": "info", "text": "还没有投递记录。先完成一轮投递，评估数据才有意义。"}]

    def best(bd, label, min_total=2):
        rows = [(k, v) for k, v in bd.items() if v["total"] >= min_total]
        if len(rows) < 2:
            return None
        rows.sort(key=lambda kv: (-kv[1]["replyRate"], -kv[1]["total"]))
        top, bottom = rows[0], rows[-1]
        if top[1]["replyRate"] == bottom[1]["replyRate"]:
            return None
        return {"level": "good",
                "text": f"{label}：「{top[0]}」回复率 {top[1]['replyRate']}%（{top[1]['replied']}/{top[1]['total']}）"
                        f"高于「{bottom[0]}」的 {bottom[1]['replyRate']}%，下一批优先前者。"}

    for bd, label in [(stats["breakdowns"]["activity"], "活跃度"), (stats["breakdowns"]["city"], "城市")]:
        r = best(bd, label)
        if r:
            out.append(r)

    funnel = stats["funnel"]
    # 岗位池 → 已沟通 是本批数量的主动选择，不算流失，从「已沟通」起算
    stages = ["已沟通", "简历已发", "已回复", "约面试"]
    fmap = {f["stage"]: f["value"] for f in funnel}
    drops = []
    for i in range(1, len(stages)):
        a, b = fmap.get(stages[i - 1], 0), fmap.get(stages[i], 0)
        if a >= 3:
            drops.append((stages[i], round((a - b) / a * 100, 1), a, b))
    if drops:
        worst = max(drops, key=lambda x: x[1])
        if worst[1] > 0 and worst[2] >= 3:
            out.append({"level": "warn",
                        "text": f"最大流失在「{worst[0]}」：{worst[2]} → {worst[3]}（流失 {worst[1]}%）。"
                                + ("若流失在打招呼后，多半是招呼语与简历首屏不匹配；" if worst[0] in ("已回复", "约面试") else "检查岗位与简历的匹配度。")})

    if replied == 0:
        out.append({"level": "warn", "text": "目前回复率为 0，样本量小属正常；建议下一批优先「刚刚活跃」的招聘者，并把最相关的项目放到简历前三行。"})
    elif stats["rates"]["回复率"] >= 20:
        out.append({"level": "good", "text": f"回复率 {stats['rates']['回复率']}% 高于常见水平，当前选岗与简历策略有效，可沿用并扩大批次。"})

    fb = stats["feedback"]
    if fb["total"]:
        out.append({"level": "info", "text": f"已记录 {fb['total']} 条反馈：积极 {fb['positive']}、消极 {fb['negative']}；消极反馈要回写到选岗规则里。"})
    pos = [f for f in stats["recentFeedback"] if f.get("signal") == "positive"]
    for f in pos[:2]:
        if f.get("action"):
            out.append({"level": "action", "text": f"{f.get('company', '')}：{f['action']}"})
    return out


def build_cron(st):
    """把策略翻译成 crontab 行，方便用户挂到系统调度。"""
    cad = st.get("cadence", {}) or {}
    days = ",".join(str(int(d) % 7) for d in (cad.get("weekdays") or [1, 2, 3, 4, 5]))
    lines = []
    for t in cad.get("times") or ["09:30"]:
        hh, mm = (t.split(":") + ["0"])[:2]
        lines.append(f"{int(mm)} {int(hh)} * * {days}  cd {ROOT} && python3 workbench/cli.py run-batch >> data/logs/cron.log 2>&1")
    return lines


def compute_batch_status(cfg=None, st=None, jobs=None, apps=None):
    """给调度器 / 外部 Agent 的批处理状态判定（run-batch 退出码契约）。

    退出码：0 = ready（有活干，可开工）
             2 = idle（无候选岗位，无需行动）
             3 = paused（策略停用或触发暂停条件，本轮不执行）

    暂停条件（对应 data/strategy.json）：
      - strategy.enabled = false
      - 连续 pause_after_consecutive_no_reply 家未回复（按最近投递倒序，排除已拒绝）
      - 回复率低于 min_reply_rate（至少投了 3 家才判定）
    """
    cfg = cfg if cfg is not None else read_json("search_config.json", {})
    st = st if st is not None else read_json("strategy.json", {})
    jobs = jobs if jobs is not None else read_json("jobs.json", [])
    apps = apps if apps is not None else read_json("applications.json", [])
    applied = {x.get("company") for x in apps}
    rt = cfg.get("recruit_types") or []
    pending = [j for j in jobs if j.get("company") not in applied
               and (not rt or infer_recruit_type(j) in rt)]

    reason = None
    if not st.get("enabled", True):
        reason = "strategy.disabled"
    else:
        replied_set = {"已回复", "约面试", "已面试", "已offer"}
        seq = sorted((a for a in apps if a.get("status") != "已拒绝"),
                     key=lambda x: x.get("greetedAt") or "", reverse=True)
        consecutive = 0
        for a in seq:
            if a.get("status") in replied_set:
                break
            consecutive += 1
        thr = int(st.get("pause_after_consecutive_no_reply") or 0)
        if thr and consecutive >= thr:
            reason = f"pause.consecutive_no_reply({consecutive}≥{thr})"
        else:
            resume_sent = sum(1 for a in apps if a.get("status") in
                              {"简历已发", "已回复", "约面试", "已面试", "已offer", "已拒绝"})
            replied = sum(1 for a in apps if a.get("status") in replied_set)
            rate = (replied / resume_sent) if resume_sent else None
            mr = st.get("min_reply_rate")
            if mr is not None and rate is not None and resume_sent >= 3 and rate < mr:
                reason = f"pause.low_reply_rate({rate:.2f}<{mr})"
    if reason:
        return {"status": "paused", "code": 3, "reason": reason, "pending": len(pending)}
    if not pending:
        return {"status": "idle", "code": 2, "reason": "no_pending_jobs", "pending": 0}
    return {"status": "ready", "code": 0, "reason": "has_pending_jobs", "pending": len(pending)}


def build_job_match(job_id):
    """单岗位 × 履历 的匹配分析（右侧面板数据源）。

    口径与 engine.py 一致：用词库别名在「岗位标题 + 技能标签 + JD 全文」里做匹配，
    再用 profile 的证据分判断掌握程度；覆盖率取 skills_tree.json（岗位池占比）用于排序。
    """
    jobs = read_json("jobs.json", [])
    job = next((j for j in jobs if (j.get("id") or j.get("uid")) == job_id), None)
    if job is None:
        return None
    try:
        import engine
    except Exception:
        engine = None
    try:
        lexicon = json.load(open(os.path.join(HERE, "lexicon.json"), encoding="utf-8"))
    except Exception:
        lexicon = {}
    profile = read_json("profile.json", {})
    tree = read_json("skills_tree.json", {"domains": []})
    cov_map = {}
    for d in tree.get("domains") or []:
        for s in d.get("skills") or []:
            cov_map[s.get("name")] = s.get("coverage") or 0.0

    tags = job.get("skillTags") or []
    if isinstance(tags, str):
        tags = [tags]
    haystack = " ".join([_text(job.get("position")),
                         " ".join(_text(t) for t in tags),
                         _text(job.get("jd"))]).lower()
    profile_entries = engine.build_profile_index(profile) if engine else []
    prof_raw = {((p or {}).get("name") or ""): p for p in (profile.get("skills") or []) if isinstance(p, dict)}

    matched, gaps = [], []
    for domain in lexicon.get("domains") or []:
        dname = domain.get("name") or "未分类"
        for skill in domain.get("skills") or []:
            aliases = [a for a in (skill.get("aliases") or []) if isinstance(a, str) and a.strip()]
            if not aliases or not any(engine.text_hit(a, haystack) for a in aliases):
                continue
            in_prof, my_score, my_tier, _names, m_entries = engine.match_profile(skill, profile_entries) if engine else (False, 0, "", [], [])
            learn = skill.get("learn") or {}
            ev = {}
            for me in m_entries[:1]:
                raw = prof_raw.get(me.get("name"))
                if raw:
                    for k in ("statement", "scenario", "metrics", "projectRefs", "artifacts"):
                        if raw.get(k):
                            ev[k] = raw.get(k)
            item = {
                "name": skill.get("name"),
                "category": dname,
                "myScore": int(my_score),
                "myTier": my_tier or "",
                "inProfile": in_prof,
                "coverage": cov_map.get(skill.get("name"), 0.0),
                "why": _text(learn.get("why")),
                "plan": {"focus": _text(learn.get("focus")), "duration": _text(learn.get("duration")),
                         "verification": _text(learn.get("verification"))},
                "evidence": ev,
            }
            if in_prof and my_score >= 60:
                matched.append(item)
            else:
                item["level"] = "空白" if not in_prof else "薄弱"
                gaps.append(item)
    matched.sort(key=lambda x: (-x["coverage"], -x["myScore"], x["name"]))
    gaps.sort(key=lambda x: (-x["coverage"], x["myScore"], x["name"]))
    required = matched + gaps
    match_score = round(100 * sum(min(x["myScore"], 100) for x in required) / (100.0 * len(required))) if required else None

    points = []
    for s in matched[:3]:
        points.append("主打项「%s」：证据分 %d（%s），准备 1 个带量化结果的项目案例，开场先讲它。" % (s["name"], s["myScore"], s["myTier"] or "-"))
    for g in gaps[:3]:
        if g["level"] == "空白":
            points.append("岗位会问「%s」，履历中暂无证据：先做到能讲清原理 + 最小 demo，简历里先不写深。" % g["name"])
        else:
            points.append("「%s」证据分仅 %d：补一个可验证产出，或准备「承认薄弱 + 补救计划」的话术。" % (g["name"], g["myScore"]))
    if not required:
        points.append("该岗位 JD / 技能标签未命中词库技能，或 JD 为空：先抓全 JD 再评估，避免盲投。")
    exp = _text(job.get("experience"))
    if exp and "不限" not in exp:
        points.append("岗位要求经验 %s，履历年限 %s 年：若不匹配，招呼语里说明最相关的项目年限。" % (exp, profile.get("years") or "未填"))
    deg = _text(job.get("degree"))
    if deg:
        points.append("岗位要求学历 %s：确认履历教育经历与此对齐，面试可能被问到。" % deg)

    # 单岗层级匹配洞察（jd_match_v1 口径，与岗位洞察页一致；不可用时降级 None）
    jd_match_report = None
    try:
        import jd_match as _jdm
        ig = engine._load_ignored_dims((job.get("targetIds") or [None])[0]) if engine else []
        jd_match_report = _jdm.build_job_insight(job, lexicon, profile, ig)
    except Exception:
        jd_match_report = None

    return {
        "job": {k: job.get(k) for k in ("id", "uid", "company", "position", "city", "salary",
                                         "activity", "recruiter", "url", "experience", "degree",
                                         "skillTags", "collectedAt") if k in job},
        "recruitType": infer_recruit_type(job),
        "matchScore": match_score,
        "matched": matched,
        "gaps": gaps,
        "interviewPoints": points,
        "jd": _text(job.get("jd")),
        "jdMatch": jd_match_report,
        "generatedAt": now(),
    }


def build_brief():
    """Turn the confirmed web config + strategy into an executable instruction for any Agent."""
    cfg = read_json("search_config.json", {})
    st = read_json("strategy.json", {})
    onb = build_onboarding()
    prof = read_json("profile.json", {})
    cities = "、".join(c.get("name", "") for c in cfg.get("cities", []) if c.get("priority", 9) <= 3)
    codes = ", ".join(f"{c.get('name')}={c.get('code')}" for c in cfg.get("cities", []))
    kw = "、".join(_active_keywords(prof))
    if not kw:
        kw = "、".join(cfg.get("keywords", []))
    sal = cfg.get("salary", {})
    cad = st.get("cadence", {}) or {}
    cad_txt = (f"每天 {'/'.join(cad.get('times', []))}（周 {'/'.join(str(x) for x in cad.get('weekdays', []))}）"
               if cad.get("type") == "daily" else
               f"每 {cad.get('interval_hours')} 小时" if cad.get("type") == "interval" else
               f"每周 {'/'.join(str(x) for x in cad.get('weekdays', []))} {'/'.join(cad.get('times', []))}")
    win = "、".join(f"{w.get('from')}-{w.get('to')}" for w in (st.get("time_windows") or [])) or "不限"
    onb_txt = "、".join(i["label"] for i in onb["missing"]) or "全部就绪"
    rg = st.get("review_gate", {}) or {}
    last_run = next((e for e in read_events(limit=20) if e.get("action") == "run.batch"), None)
    run_txt = (f"{last_run.get('ts')}：{last_run.get('detail')}" if last_run else "（尚无 run-batch 记录）")
    return f"""# 求职投递任务简报（由工作台生成，{now()}）

## 候选人
- 姓名：{prof.get('name', '')}｜求职方向：{prof.get('title', '')}｜城市：{prof.get('city', '')}｜经验：{prof.get('years', '')} 年
- 履历数据：`data/profile.json`（已结构化，含技能矩阵与熟练度）
- 搜岗配置：`data/search_config.json`　投递策略：`data/strategy.json`

## 本轮参数（已在网页确认）
- 目标城市（优先级）：{cities}
- 城市码（**无需用户填写，系统已自动补全**）：{codes}
- 关键词：{kw}
- 薪资区间：{sal.get('min')}-{sal.get('max')}{sal.get('unit', 'K')}（与该区间有重叠即保留）
- 活跃度偏好：{'、'.join(cfg.get('activity_preference', []))}
- 招聘类型：{'、'.join(cfg.get('recruit_types', [])) or '不限（校招/社招均可）'}
- 排除公司：{'、'.join(cfg.get('exclude_companies', [])) or '（无）'}
- 本批数量：{cfg.get('batch_size')} 家
- 节流：导航 {cfg.get('throttle', {}).get('nav_seconds')}s，动作 {cfg.get('throttle', {}).get('action_seconds')}s，岗位间隔 {cfg.get('throttle', {}).get('job_interval_seconds')}s

## 要求
1. 采集岗位写入 `data/jobs.json`（可用 `POST /api/jobs` 或 `python3 workbench/cli.py jobs import <file>`）。
2. **去重**：先读 `data/applications.json`，已投递的公司/岗位不得重复投递。
3. 筛选时排除 `exclude_companies`，按招聘类型 `recruit_types`（空=不限）过滤，并优先活跃度高的招聘者。
4. 简历标题统一为「{prof.get('title', '')}」；正文可依据 JD 调整侧重，**不得编造**履历外的技术栈与数字。
5. 投递前必须通过校验：`python3 tools/validate_resume.py` + 独立复核；未通过不得投递。
6. 每投递一家，用 `POST /api/applications` 写入记录；收到 HR 回复用 `POST /api/feedback` 记录。
7. 严格遵守上面的投递策略（时间窗、数量上限、暂停条件）。
8. 完成后在网页「概览/投递与反馈」查看统计。

## 投递策略（已确认，必须遵守）
- 模式：{st.get('mode')}（batch=按批执行 / schedule=按周期执行）
- 周期：{cad_txt}
- 每次岗位数：{st.get('batch_size')}　每日上限：{st.get('daily_limit')}
- 允许时间段：{win}
- 投递前需要用户确认名单：{'是' if st.get('require_approval') else '否（自动投递）'}
- 连续 {st.get('pause_after_consecutive_no_reply')} 家无回复则暂停并复盘
- 回复率低于 {st.get('min_reply_rate')} 时暂停并复盘
- 去重：同公司 {st.get('per_company_cooldown_days')} 天内不重复；同一公司最多 {st.get('max_per_company')} 次
- 命中平台风控立即停止：{'是' if st.get('stop_on_risk_control') else '否'}
- 校验门禁：确定性校验 {'开' if rg.get('deterministic') else '关'}、独立 Agent 复核 {'开' if rg.get('independent_agent') else '关'}

## 最近运行状态
- 上次 run-batch：{run_txt}

## 数据完备度
缺失项：{onb_txt}。若缺失，先按 `GET /api/onboarding` 里的 ask 逐项向用户确认并写入，再开始采集。

## Agent 交互方式（任选其一）
- HTTP API：见 `workbench/API.md`（`GET /api/contract` 也可取到）
- 文件直读直写：`data/*.json`
- CLI：`python3 workbench/cli.py --help`
"""


# ------------------------------------------------------ 简历渲染（从 profile 直渲） --
def _esc(s):
    return html.escape(str(s if s is not None else ""))


def load_resume_template(override_name=None):
    """默认模板名来自 data/resume_template.json；用户模板优先，回退内置。
    override_name 非空时用指定模板（用于「生成 PDF 时选模板」）。"""
    name = override_name or "resume.html"
    if not override_name:
        try:
            name = read_json("resume_template.json", {}).get("default") or name
        except Exception:
            pass
    if not re.fullmatch(r"[\w\-]+\.html", name or ""):
        name = "resume.html"
    for base in (TPL_USER, TPL_BUILTIN):
        p = os.path.join(base, name)
        if os.path.exists(p):
            return open(p, encoding="utf-8").read()
    return open(os.path.join(TPL_BUILTIN, "resume.html"), encoding="utf-8").read()


def _fmt_years(v):
    try:
        n = float(v)
        if n.is_integer():
            n = int(n)
        return f"{n} 年工作经验"
    except (TypeError, ValueError):
        return _esc(v) if v else ""


def _core_projects(prof):
    """按 rank 收集简历「核心项目经历」：rank>0 的个人 projects[] + 工作经历子项目（showInWork=false 的）。

    showInWork=true 的子项目已在工作经历区块内联展示，这里跳过避免重复。
    返回 [(title, meta, link, stack_str, bullets)]，rank 升序最多5个。
    """
    picked = []
    for p in prof.get("projects") or []:
        r = int(p.get("rank") or 0)
        if r > 0:
            meta = " · ".join(x for x in [p.get("type") or "", p.get("period") or ""] if x)
            stack = p.get("stack") or []
            picked.append((r, p.get("name") or "", meta, p.get("link") or "",
                           "、".join(stack) if isinstance(stack, list) else str(stack or ""),
                           p.get("highlights") or []))
    for w in prof.get("experiences") or []:
        for sp in w.get("subProjects") or []:
            if sp.get("showInWork"):
                continue   # 已在工作经历区展示，不重复进核心项目区
            r = int(sp.get("rank") or 0)
            if r > 0:
                ctx = " · ".join(x for x in [w.get("company") or "", w.get("role") or ""] if x)
                if w.get("remote"):
                    ctx = (ctx + " · 远程") if ctx else "远程"
                period = sp.get("period") or ""
                meta = " · ".join(x for x in [ctx, period] if x)
                stack = sp.get("stack") or []
                picked.append((r, sp.get("name") or "", meta, "",
                               "、".join(stack) if isinstance(stack, list) else str(stack or ""),
                               sp.get("highlights") or []))
    picked.sort(key=lambda x: (x[0],))
    return [(t, m, l, s, b) for (r, t, m, l, s, b) in picked[:5]]


def render_resume_html(prof, target, template_name=None, font_scale=None):
    """从 profile.json（schemaVersion=3）直接渲染完整简历 HTML。

    不依赖 tailor.json、不硬编码 BASE/PROJECTS/WORK——所有事实都来自 profile。
    仅按 target.title 调整求职意向行，不做任何编造。
    template_name：指定模板文件名（如 myresume.html）；None 时用 data/resume_template.json 的 default。
    font_scale：整体字号缩放（0.8-1.4），通过 .page 的 zoom 实现，同比例放大/缩小。
    """
    name = prof.get("name") or ""
    phone = prof.get("phone") or ""
    email = prof.get("email") or ""
    city = prof.get("city") or ""
    years = _fmt_years(prof.get("years"))
    github = prof.get("github") or ""
    intent = (target or {}).get("title") or prof.get("title") or ""

    # HEADER：左侧 姓名+性别年龄，右侧 联系方式（按 contactVisibility 开关筛选）
    vis = prof.get("contactVisibility") or {}
    def _show(k, default=True):
        return vis.get(k, default)
    contact_items = []
    if _show("phone") and phone:
        contact_items.append(f"<b>{_esc(phone)}</b>")
    if _show("email") and email:
        contact_items.append(_esc(email))
    if _show("city") and city:
        contact_items.append(_esc(city))
    if _show("years") and years:
        contact_items.append(_esc(years))
    if _show("github") and github:
        contact_items.append(_esc(github))
    # 性别/年龄放姓名旁边（同一行）
    id_meta = []
    if _show("gender") and prof.get("gender"):
        id_meta.append(_esc(prof["gender"]))
    if _show("age") and prof.get("age"):
        id_meta.append(f"{_esc(prof['age'])} 岁")
    header = (
        "<header>"
        "<div class='id'>"
        f"<h1>{_esc(name)}</h1>"
        + (f"<span class='meta'>{' · '.join(id_meta)}</span>" if id_meta else "")
        + "</div>"
        f"<div class='contact'>{'<br>'.join(contact_items)}</div>"
        "</header>"
    )

    # SUMMARY：三段式拼接
    parts = [prof.get("summaryPosition"), prof.get("summaryResult"), prof.get("summaryRarity")]
    summary_text = "　".join(p for p in parts if p and p.strip()) or prof.get("summary") or ""
    summary = f"<p class='summary'>{_esc(summary_text)}</p>" if summary_text else ""

    # SKILLS：professional 按 cluster 聚合；tools 聚合一行
    skills_html = ["<div class='cap'>"]
    prof_skills = [s for s in prof.get("skills", []) if s.get("group", "professional") == "professional"]
    tools_skills = [s for s in prof.get("skills", []) if s.get("group") == "tools"]
    soft_skills = [s for s in prof.get("skills", []) if s.get("group") == "soft"]
    cred_skills = [s for s in prof.get("skills", []) if s.get("group") == "credentials"]

    clusters = {}
    for s in prof_skills:
        clusters.setdefault(s.get("cluster") or "其他", []).append(s)
    for cluster, items in clusters.items():
        # 每个技能一行：name 里若含「：」则前半加粗后半正常；statement 存在则 name：statement
        for s in items:
            stmt = (s.get("statement") or "").strip()
            raw_name = (s.get("name") or "").strip()
            # name 自身含冒号（如 "RAG 知识工程：分层事实模型治理..."）→ 冒号前加粗，冒号后正常
            if not stmt and ("：" in raw_name or ":" in raw_name):
                sep = "：" if "：" in raw_name else ":"
                head, tail = raw_name.split(sep, 1)
                seg = f"<b>{_esc(head)}{sep}</b>{_esc(tail)}"
            else:
                head = _esc(raw_name)
                if stmt:
                    seg = f"<b>{head}：</b>{_esc(stmt)}"
                else:
                    seg = f"<b>{head}</b>"
            skills_html.append(f"<p style='margin:2px 0'>{seg}</p>")
    if tools_skills:
        # 工具与技术栈：不区分语言/中间件/云，所有名字平铺一行
        tnames = [s.get("name") for s in tools_skills if s.get("name")]
        skills_html.append(f"<p style='margin:2px 0'><b>工具与技术栈：</b>{_esc('、'.join(tnames))}</p>")
    if soft_skills:
        sline = "、".join(s.get("name", "") for s in soft_skills if s.get("name"))
        if sline:
            skills_html.append(f"<p style='margin:2px 0'><b>通用能力：</b>{_esc(sline)}</p>")
    skills_html.append("</div>")
    skills = "".join(skills_html)

    # PROJECTS（核心项目经历）：rank>0 的个人项目 + 工作经历子项目，按 rank 升序（1→5，最多5个）。
    # 没有任何 rank 时回退旧行为（渲染全部个人项目），保证未设置 rank 的简历不空。
    core_ranked = _core_projects(prof)
    projects = ["<div class='work'>"]
    if core_ranked:
        for title, meta, link, stack, bullets in core_ranked:
            if link and link not in meta:
                meta = (meta + " · " + link) if meta else link
            projects.append("<div class='item'>"
                            f"<div class='top'><span class='ttl'>{_esc(title)}</span><span class='meta'>{_esc(meta)}</span></div>"
                            + (f"<div class='stack'>技术栈：{_esc(stack)}</div>" if stack else "")
                            + "<ul>" + "".join(f"<li>{_esc(b)}</li>" for b in bullets) + "</ul>"
                            "</div>")
    else:
        for p in prof.get("projects", []):
            title = p.get("name") or ""
            ptype = p.get("type") or ""
            link = p.get("link") or ""
            meta_bits = [x for x in [ptype, p.get("period") or ""] if x]
            meta = " · ".join(meta_bits)
            if link and link != ptype:
                meta = (meta + " · " + link) if meta else link
            stack = p.get("stack") or []
            if isinstance(stack, list):
                stack = "、".join(stack)
            bullets = p.get("highlights") or []
            projects.append("<div class='item'>"
                            f"<div class='top'><span class='ttl'>{_esc(title)}</span><span class='meta'>{_esc(meta)}</span></div>"
                            + (f"<div class='stack'>技术栈：{_esc(stack)}</div>" if stack else "")
                            + "<ul>" + "".join(f"<li>{_esc(b)}</li>" for b in bullets) + "</ul>"
                            "</div>")
    projects.append("</div>")
    projects_html = "".join(projects)

    # WORK：工作经历按 start 倒序（最新在前），不管 profile.json 里数组顺序
    def _parse_period(s):
        """'2024.03' / '2024-03' / '2024/03' → (year, month)；解析失败返回 (0,0) 排到最后"""
        m = re.match(r"(\d{4})\D?(\d{1,2})?", str(s or ""))
        return (int(m.group(1)), int(m.group(2) or 0)) if m else (0, 0)

    exps = list(prof.get("experiences") or [])
    exps.sort(key=lambda w: _parse_period(w.get("start")), reverse=True)

    work = ["<div class='work'>"]
    for w in exps:
        company = w.get("company") or ""
        role = w.get("role") or ""
        if w.get("remote"):
            role = (role + " · 远程") if role else "远程"
        period = " - ".join(x for x in [w.get("start"), w.get("end")] if x)
        highlights = w.get("highlights") or []
        work.append(
            f"<div class='wrow'><span class='wco'>{_esc(company)}</span>"
            f"<span class='wrole'>{_esc(role)}</span><span class='wdate'>{_esc(period)}</span></div>"
        )
        if highlights:
            work.append("<ul>" + "".join(f"<li>{_esc(h)}</li>" for h in highlights) + "</ul>")
        # 工作经历内嵌子项目（showInWork=true 才展示）；核心项目经历区不重复收
        for sp in (w.get("subProjects") or []):
            if not sp.get("showInWork"):
                continue
            sp_name = sp.get("name") or ""
            sp_period = sp.get("period") or ""
            if sp_name:
                work.append(
                    f"<div class='wrow' style='margin-top:4px'><span class='wco' style='font-weight:600'>▸ {_esc(sp_name)}</span>"
                    f"<span class='wdate'>{_esc(sp_period)}</span></div>"
                )
            sp_stack = sp.get("stack") or []
            if isinstance(sp_stack, list):
                sp_stack = " · ".join(sp_stack)
            if sp_stack:
                work.append(f"<div class='wstack'>技术栈：{_esc(sp_stack)}</div>")
            sp_hl = sp.get("highlights") or []
            if sp_hl:
                work.append("<ul>" + "".join(f"<li>{_esc(h)}</li>" for h in sp_hl) + "</ul>")
    work.append("</div>")
    work_html = "".join(work)

    # EDUCATION
    edu_parts = []
    for e in prof.get("education", []):
        period = " - ".join(x for x in [e.get("start"), e.get("end")] if x)
        line = f"{e.get('school') or ''} · {e.get('degree') or ''} {e.get('major') or ''}".strip(" ·")
        edu_parts.append(
            f"<div class='edu'><span><b>{_esc(e.get('school') or '')}</b> · "
            f"{_esc(e.get('degree') or '')} {_esc(e.get('major') or '')}</span>"
            f"<span class='wdate'>{_esc(period)}</span></div>"
        )
    edu_html = "".join(edu_parts)

    # OTHER：skillEnvironment + credentials
    other_bits = []
    if prof.get("skillEnvironment"):
        other_bits.append(prof["skillEnvironment"])
    if cred_skills:
        other_bits.append(" · ".join(s.get("name", "") for s in cred_skills if s.get("name")))
    other_html = f"<div class='other'>{_esc('　'.join(other_bits))}</div>" if other_bits else ""

    tpl = load_resume_template(template_name)
    # 整体字号缩放：在 .page 上加 zoom（Chrome printToPDF 原生支持）
    if font_scale:
        try:
            fs = float(font_scale)
            if 0.7 <= fs <= 1.6:
                tpl = tpl.replace("<div class='page'>",
                                   f"<div class='page' style='zoom:{fs}'>", 1)
        except (TypeError, ValueError):
            pass
    for k, v in (("HEADER", header), ("SUMMARY", summary), ("SKILLS", skills),
                 ("PROJECTS", projects_html), ("WORK", work_html),
                 ("EDUCATION", edu_html), ("OTHER", other_html)):
        tpl = tpl.replace("{{%s}}" % k, v)
    return tpl


def generate_resume_pdf(target_id=None, template_name=None, font_scale=None):
    """按目标岗位渲染 HTML 并出 PDF。返回 dict(paths + urls)。

    不依赖 tailor.json / agent_tailor.py——这是"基于当前 profile 直出一份 PDF"的快速通道。
    LLM 按 JD 深度定制仍走 agent_tailor.py；本接口用于"立即生成一份可用 PDF"。
    template_name：指定模板（如 temp1.html）；None 时用默认模板。
    font_scale：整体字号缩放（0.8-1.4），同比例大一号/小一号。
    """
    prof = read_json("profile.json", {})
    targets = prof.get("targets") or []
    if not targets:
        raise RuntimeError("profile.json 还没有目标岗位，请先在「搜岗 → 目标岗位」里添加")
    tgt = None
    if target_id:
        tgt = next((t for t in targets if t.get("id") == target_id), None)
    if tgt is None:
        tgt = next((t for t in targets if t.get("id") == prof.get("activeTarget")), targets[0])

    ts = datetime.now().strftime("%Y%m%d-%H%M")
    safe_name = re.sub(r"[^\w\u4e00-\u9fa5-]", "_", prof.get("name") or "resume")[:20]
    safe_tgt = re.sub(r"[^\w\u4e00-\u9fa5-]", "_", tgt.get("title") or "default")[:30]
    stem = f"{safe_name}-{safe_tgt}-{ts}"

    html_dir = os.path.join(RESUMES_DIR, "html")
    pdf_dir = os.path.join(RESUMES_DIR, "pdf")
    os.makedirs(html_dir, exist_ok=True)
    os.makedirs(pdf_dir, exist_ok=True)

    html_path = os.path.join(html_dir, stem + ".html")
    pdf_path = os.path.join(pdf_dir, stem + ".pdf")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(render_resume_html(prof, tgt, template_name, font_scale))

    # 拉起 9223 打印 Chrome（幂等：已在线则直接跳过）
    ensure_sh = os.path.join(ROOT, "tools", "ensure_print_chrome.sh")
    try:
        subprocess.run(["bash", ensure_sh], cwd=ROOT, capture_output=True, text=True, timeout=30)
    except Exception as e:
        raise RuntimeError(f"拉起打印 Chrome 失败：{e}")

    # 调 print_pdf.mjs 出 PDF
    print_js = os.path.join(ROOT, "tools", "print_pdf.mjs")
    proc = subprocess.run(["node", print_js, html_path, pdf_path],
                          cwd=ROOT, capture_output=True, text=True, timeout=60)
    if proc.returncode != 0 or not os.path.exists(pdf_path):
        raise RuntimeError(f"PDF 生成失败：{(proc.stderr or proc.stdout or '').strip()[-300:]}")

    return {
        "ok": True,
        "targetId": tgt.get("id"),
        "targetTitle": tgt.get("title"),
        "templateName": template_name or (read_json("resume_template.json", {}).get("default") or "resume.html"),
        "fontScale": float(font_scale) if font_scale else 1.0,
        "fileStem": stem,
        "htmlPath": html_path,
        "pdfPath": pdf_path,
        "htmlUrl": f"/resumes/html/{stem}.html",
        "pdfUrl": f"/resumes/pdf/{stem}.pdf",
        "pdfBytes": os.path.getsize(pdf_path),
        "generatedAt": now(),
    }


# ------------------------------------------------------------------ handler --
class Handler(BaseHTTPRequestHandler):
    server_version = "JobWorkbench/1.0"

    def log_message(self, fmt, *args):
        if os.environ.get("WORKBENCH_QUIET"):
            return
        sys.stderr.write("  %s - %s\n" % (self.address_string(), fmt % args))

    # -- helpers
    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False, indent=1)
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, must-revalidate")   # 本地开发：避免改前端后拿到旧缓存
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,PUT,PATCH,DELETE,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception:
            return {}

    def do_OPTIONS(self):
        self._send(204, b"")

    # -- GET
    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        p = u.path
        if p.startswith("/api/"):
            return self.api_get(p, q)
        if p.startswith("/resumes/"):
            return self.serve_resume_file(p)
        return self.serve_static(p)

    def api_get(self, p, q):
        if p == "/api/health":
            return self._send(200, {"ok": True, "at": now(), "dataDir": DATA, "root": ROOT})
        if p == "/api/daemon":   # boss-daemon 状态（pid 文件 + 存活探测 + 登录态；loginCheck 走命令队列，5s 缓存防刷爆）
            pid = _daemon_pid()
            last = read_json("raw/last_collect.json", {})
            logged = None
            if pid:
                import time as _t
                _c = _DAEMON_CACHE
                if _t.time() - _c["at"] < 5 and _c["logged"] is not None:
                    logged = _c["logged"]
                else:
                    try:
                        node_bin = shutil.which("node")
                        boss_mjs = os.path.join(HERE, "..", "tools", "boss-daemon.mjs")
                        pr = subprocess.run([node_bin, boss_mjs, "loginCheck"], capture_output=True,
                                            text=True, timeout=10)
                        if pr.returncode == 0 and pr.stdout.strip().startswith("{"):
                            lg = json.loads(pr.stdout[pr.stdout.index("{"):pr.stdout.rindex("}") + 1])
                            logged = bool(lg.get("logged"))
                            _c.update(at=_t.time(), logged=logged)
                    except Exception:
                        logged = None
            return self._send(200, {"ok": True, "running": bool(pid), "pid": pid,
                                    "loggedIn": logged,
                                    "lastCollect": last.get("at"), "lastAdded": last.get("added"),
                                    "lastUpdated": last.get("updated"), "lastTarget": last.get("target")})
        if p == "/api/daemon/start":   # 手动启动 boss-daemon（后台常驻 Chrome）
            # 兜底清理：残留 STOP 会让刚启动的 daemon 秒退（kill -9 的实例不会清理）
            try:
                os.makedirs(os.path.join(ROOT, "data", "raw", "commands"), exist_ok=True)
                sp = os.path.join(ROOT, "data", "raw", "commands", "STOP")
                if os.path.exists(sp):
                    os.remove(sp)
            except Exception:
                pass
            if _daemon_pid():
                return self._send(200, {"ok": True, "running": True, "pid": _daemon_pid(), "note": "已在运行"})
            boss_daemon = os.path.join(ROOT, "tools", "boss-daemon.mjs")
            os.makedirs(os.path.join(DATA, "logs"), exist_ok=True)
            logf = open(os.path.join(DATA, "logs", "daemon.out"), "a")
            try:
                proc = subprocess.Popen(["node", boss_daemon], cwd=ROOT, stdout=logf, stderr=logf,
                                        start_new_session=True)
                append_event("daemon.start", "手动启动 boss-daemon", actor="api")
                return self._send(200, {"ok": True, "running": True, "pid": proc.pid, "note": "已启动"})
            except Exception as e:
                return self._send(200, {"ok": False, "error": "启动失败：" + str(e)[:120]})
        if p == "/api/daemon/stop":   # 优雅停止（commands/STOP）
            try:
                os.makedirs(os.path.join(ROOT, "data", "raw", "commands"), exist_ok=True)
                open(os.path.join(ROOT, "data", "raw", "commands", "STOP"), "w").close()
                append_event("daemon.stop", "停止 boss-daemon", actor="api")
                return self._send(200, {"ok": True, "note": "已发送停止指令"})
            except Exception as e:
                return self._send(200, {"ok": False, "error": str(e)[:120]})
        if p == "/api/profile":
            prof = read_json("profile.json", {})
            # 目标岗位迁移：旧数据无 targets 时，用现有 title 初始化默认目标
            if not prof.get("targets"):
                prof["targets"] = [{"id": "t1", "title": prof.get("title") or "Agent系统工程师", "note": ""}]
                prof["activeTarget"] = "t1"
                write_json("profile.json", prof)
            elif not prof.get("activeTarget"):
                prof["activeTarget"] = (prof.get("targets") or [{}])[0].get("id")
                write_json("profile.json", prof)
            # 关键词迁移：目标还没有关键词时，把旧 search_config.keywords 并入当前选中目标
            if not any(t.get("keywords") for t in (prof.get("targets") or [])):
                old_kws = read_json("search_config.json", {}).get("keywords") or []
                if old_kws:
                    act = prof.get("activeTarget") or (prof.get("targets") or [{}])[0].get("id")
                    for t in prof.get("targets") or []:
                        if t.get("id") == act:
                            t["keywords"] = old_kws
                    write_json("profile.json", prof)
            return self._send(200, decorate_profile(prof))
        if p == "/api/scoring":
            try:
                import scoring
                return self._send(200, {"groups": scoring.GROUPS, "toolClusters": scoring.TOOL_CLUSTERS,
                                        "softLimit": scoring.SOFT_LIMIT, "evidenceLevels": scoring.EVIDENCE_LEVELS,
                                        "tiers": scoring.TIERS, "coverageTiers": scoring.COVERAGE_TIERS})
            except Exception as e:
                return self._send(200, {"error": str(e)})
        if p == "/api/skill-links":
            if (q.get("refresh") or [""])[0] == "1":
                script = os.path.join(HERE, "skill_links.py")
                if os.path.exists(script):
                    try:
                        subprocess.run([sys.executable, script], capture_output=True, text=True, timeout=180, cwd=ROOT)
                    except Exception:
                        pass
            return self._send(200, read_json("skill_links.json", {"summary": {}, "broken": [], "missing": []}))
        if p == "/api/config":
            cfg = read_json("search_config.json", {})
            return self._send(200, autofill_city_codes(cfg))
        if p == "/api/resume/templates":   # 简历模板列表 + 默认；?name=xxx 返回单个模板内容
            name = (q.get("name") or [""])[0]
            if name:
                if not re.fullmatch(r"[\w\-]+\.html", name or ""):
                    return self._send(400, {"ok": False, "error": "模板名非法"})
                for base in (TPL_USER, TPL_BUILTIN):
                    fp = os.path.join(base, name)
                    if os.path.exists(fp):
                        return self._send(200, {"name": name, "content": open(fp, encoding="utf-8").read(),
                                                "builtin": not os.path.isdir(TPL_USER) or name not in set(os.listdir(TPL_USER))})
                return self._send(404, {"ok": False, "error": "模板不存在"})
            user_names = set(os.listdir(TPL_USER)) if os.path.isdir(TPL_USER) else set()
            names = set()
            for base in (TPL_USER, TPL_BUILTIN):
                if os.path.isdir(base):
                    names.update(f for f in os.listdir(base) if f.endswith(".html"))
            items = sorted(({"name": f, "builtin": f not in user_names} for f in names), key=lambda x: x["name"])
            default = read_json("resume_template.json", {}).get("default") or "resume.html"
            if default not in names:
                default = "resume.html"
            return self._send(200, {"templates": items, "default": default})
        if p == "/api/resume/skill":   # 简历撰写规范（Markdown）
            skill_path = os.path.join(DATA, "resume_skill.md")
            builtin = os.path.join(ROOT, "skills", "boss-zhipin-apply", "SKILL.md")
            if not os.path.exists(skill_path):
                # 首次：从内置 SKILL.md 拷贝
                if os.path.exists(builtin):
                    shutil.copy(builtin, skill_path)
                else:
                    open(skill_path, "w", encoding="utf-8").write("# 简历撰写规范\n\n")
            return self._send(200, {"content": open(skill_path, encoding="utf-8").read(),
                                     "path": "data/resume_skill.md"})
        if p == "/api/strategy":
            return self._send(200, read_json("strategy.json", {}))
        if p == "/api/cities":
            d = load_cities()
            return self._send(200, {"count": len(d.get("cities", {})), "cities": d.get("cities", {})})
        if p == "/api/onboarding":
            return self._send(200, build_onboarding())
        if p == "/api/schedule":
            st = read_json("strategy.json", {})
            return self._send(200, {"strategy": st, "cron": build_cron(st)})
        if p == "/api/jobs/refresh/status":   # 采集会话状态（前端轮询实时上屏）
            return self._send(200, _collect_status())
        if p == "/api/jobs":
            jobs = read_json("jobs.json", [])
            jobs = [dict(j, recruitType=infer_recruit_type(j)) for j in jobs]
            city = (q.get("city") or [""])[0]
            kw = (q.get("q") or [""])[0]
            has_jd = (q.get("hasJd") or [""])[0]
            tgt = (q.get("target") or [""])[0]
            actv = (q.get("active") or [""])[0]
            if tgt:
                jobs = [j for j in jobs if tgt in (j.get("targetIds") or []) or j.get("targetId") == tgt]
            if city:
                jobs = [j for j in jobs if j.get("city") == city]
            if kw:
                jobs = [j for j in jobs if kw in (j.get("company", "") + j.get("position", "") + j.get("jd", ""))]
            if has_jd == "1":
                jobs = [j for j in jobs if j.get("jd")]
            if actv:   # 活跃度筛选：按档位过滤（activity 为空=未标注，保留不误杀）
                want = {x.strip() for x in actv.split(",") if x.strip()}
                jobs = [j for j in jobs if not (j.get("activity") or "").strip() or (j.get("activity") or "").strip() in want]
            # 展示兜底：解码历史混淆薪资 + 按目标动态算相关度（matchLevel: strong/weak/none）
            prof = read_json("profile.json", {})
            act = prof.get("activeTarget") or ((prof.get("targets") or [{}])[0] or {}).get("id")
            kws = []
            if act:
                t = next((x for x in (prof.get("targets") or []) if x.get("id") == act), None)
                kws = list(t.get("keywords") or []) or ([t.get("title")] if t and t.get("title") else [])
            out = []
            for j in jobs:
                jj = dict(j)
                if jj.get("salary"):
                    jj["salary"] = _decode_salary(jj["salary"])
                # 已落盘 matchScore（岗位×履历层级匹配度）→ 用其分档；无分数（无 JD）归入
                # 「低匹配 / 未评估」档（不再按关键词标强相关——相关度语义已改为履历匹配度）
                jj["matchLevel"] = jj.get("matchLevel") if jj.get("matchScore") is not None else "none"
                out.append(jj)
            return self._send(200, out)
        if p == "/api/jobmatch":
            jid = (q.get("id") or [""])[0]
            if not jid:
                return self._send(400, {"error": "missing id"})
            m = build_job_match(jid)
            if m is None:
                return self._send(404, {"error": "job not found", "id": jid})
            return self._send(200, m)
        if p == "/api/applications":
            return self._send(200, read_json("applications.json", []))
        if p == "/api/feedback":
            return self._send(200, read_json("feedback.json", []))
        if p == "/api/skills":
            return self._send(200, read_json("skills_tree.json", {"domains": [], "corpus": {}}))
        if p == "/api/gap":
            return self._send(200, read_json("gap_analysis.json", {"gaps": [], "strengths": []}))
        if p == "/api/insight/ignore":
            cur = read_json("insight_ignore.json", {"targets": {}})
            return self._send(200, {"ok": True, "targets": (cur or {}).get("targets") or {}})
        if p == "/api/stats":
            return self._send(200, compute_stats())
        if p == "/api/brief":
            return self._send(200, {"brief": build_brief()})
        if p == "/api/contract":
            f = os.path.join(HERE, "API.md")
            return self._send(200, open(f, encoding="utf-8").read() if os.path.exists(f) else "# API.md 缺失",
                              "text/markdown; charset=utf-8")
        if p == "/api/events":
            try:
                limit = min(int((q.get("limit") or ["50"])[0]), 500)
            except Exception:
                limit = 50
            return self._send(200, {"events": read_events(limit=limit),
                                    "file": "data/logs/agent-events.jsonl"})
        if p == "/api/settings":
            return self._send(200, read_settings())
        if p == "/api/llm-config":
            # 返回配置（api_key 脱敏）
            cfg_path = os.path.join(DATA, "llm_config.json")
            cfg = {}
            try:
                with open(cfg_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
            except Exception:
                pass
            key = cfg.get("api_key", "")
            masked = (key[:6] + "***" + key[-4:]) if len(key) > 12 else ("*" * len(key) if key else "")
            return self._send(200, {
                "base_url": cfg.get("base_url", "https://ark.cn-beijing.volces.com/api/v3"),
                "model": cfg.get("model", ""),
                "api_key_masked": masked,
                "enabled": bool(key and cfg.get("model")),
            })
        if p == "/api/export":
            os.makedirs(os.path.join(DATA, "exports"), exist_ok=True)
            out = os.path.join(DATA, "exports", "export_bundle.zip")
            with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
                for root, _, files in os.walk(DATA):
                    for fn in files:
                        fp = os.path.join(root, fn)
                        if not os.path.isfile(fp):   # 跳过 socket/FIFO/设备（Chrome profile 有 Unix socket）
                            continue
                        if fn.endswith(".zip") or fn.endswith(".lock") or fn.startswith("Singleton"):
                            continue                      # 导出物自身 + Chrome 运行时锁/临时文件
                        z.write(fp, os.path.relpath(fp, ROOT))
                for extra in ["API.md"]:
                    fp = os.path.join(HERE, extra)
                    if os.path.exists(fp):
                        z.write(fp, extra)
            return self._send(200, {"ok": True, "bundle": "data/exports/export_bundle.zip",
                                    "bytes": os.path.getsize(out), "at": now()})
        if p == "/api/export/download":
            fp = os.path.join(DATA, "exports", "export_bundle.zip")
            if not os.path.exists(fp):
                return self._send(404, {"error": "还没有备份文件，请先点击「导出备份」生成"})
            from urllib.parse import quote as _q
            fname = "boss-workbench-backup.zip"
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Length", str(os.path.getsize(fp)))
            self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{_q(fname)}")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            with open(fp, "rb") as f:
                self.wfile.write(f.read())
            return
        return self._send(404, {"error": "unknown api", "path": p})

    # -- write
    def do_POST(self):
        return self.api_write()

    def do_PUT(self):
        return self.api_write()

    def do_PATCH(self):
        return self.api_write()

    def do_DELETE(self):
        return self.api_write()

    def api_write(self):
        u = urlparse(self.path)
        p, body = u.path, self._body()
        if p == "/api/daemon/start" or p == "/api/daemon/stop":   # 启停无 body，复用 GET 处理
            return self.do_GET()
        if p == "/api/settings":
            theme = body.get("theme") or {}
            allowed = {"sideBg", "sideText", "sideText2", "sideMuted", "brand", "brand2", "brandSoft", "bg"}
            clean = {k: str(v) for k, v in theme.items() if k in allowed and str(v).startswith("#")}
            if clean:
                save_settings(clean)
            append_event("settings.update", "主题设置已保存", actor="api", payload={"theme": clean})
            return self._send(200, read_settings())
        if p == "/api/llm-config":
            cfg_path = os.path.join(DATA, "llm_config.json")
            existing = {}
            try:
                with open(cfg_path, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except Exception:
                pass
            base_url = (body.get("base_url") or existing.get("base_url")
                        or "https://ark.cn-beijing.volces.com/api/v3").rstrip("/")
            model = body.get("model") or existing.get("model", "")
            new_key = body.get("api_key", "").strip()
            # api_key 传空或传 *** 时保留旧 key
            if new_key and not new_key.endswith("***"):
                existing["api_key"] = new_key
            existing["base_url"] = base_url
            existing["model"] = model
            os.makedirs(os.path.dirname(cfg_path), exist_ok=True)
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump(existing, f, ensure_ascii=False, indent=2)
            append_event("llm_config.update", f"LLM 配置已保存（{model}）", actor="api")
            return self._send(200, {"ok": True, "enabled": bool(existing.get("api_key") and model)})
        if p == "/api/profile":
            body["updatedAt"] = now()
            for sk in body.get("skills", []) or []:      # 计算字段不入库
                sk.pop("_score", None)
                sk.pop("_match", None)
            for k in [k for k in list(body) if k.startswith("_")]:
                body.pop(k, None)                        # _health 等装饰字段不入库
            # 防回滚：旧标签页里的过期副本不允许覆盖新 schema 的数据
            current = read_json("profile.json", {})
            try:
                cur_v = int(current.get("schemaVersion") or 1)
                new_v = int(body.get("schemaVersion") or 1)
            except (TypeError, ValueError):
                cur_v = new_v = 1
            if new_v < cur_v:
                return self._send(409, {"ok": False, "error": "stale_client",
                                        "message": f"服务端履历已是 v{cur_v}，你的页面还是 v{new_v}。请刷新页面后重新编辑，避免覆盖新数据。",
                                        "serverSchemaVersion": cur_v, "clientSchemaVersion": new_v})
            with data_lock():
                write_json("profile.json", body)
            append_event("profile.update", "履历已保存", actor="api",
                         payload={"skills": len(body.get("skills") or [])})
            return self._send(200, {"ok": True, "file": "profile.json", "at": now()})
        if p == "/api/config":
            body["updatedAt"] = now()
            autofill_city_codes(body)          # 城市码自动补全，用户只填城市名
            unresolved = [c.get("name") for c in body.get("cities", []) if not c.get("resolved")]
            with data_lock():
                write_json("search_config.json", body)
            append_event("config.update", "搜岗配置已保存", actor="api",
                         payload={"unresolvedCities": unresolved})
            return self._send(200, {"ok": True, "file": "search_config.json",
                                    "unresolvedCities": unresolved, "at": now()})
        if p == "/api/run-batch":   # 策略中心「立即跑一次任务」：同步执行 run-batch 并返回退出码
            import subprocess as _sp, sys as _sys
            try:
                proc = _sp.run([_sys.executable, os.path.join("workbench", "cli.py"), "run-batch"],
                               cwd=ROOT, capture_output=True, text=True, timeout=180)
                out = (proc.stdout or "")[-2500:] + (("\n[stderr] " + proc.stderr[-800:]) if proc.stderr else "")
                return self._send(200, {"ok": True, "code": proc.returncode, "output": out.strip()})
            except Exception as e:
                return self._send(500, {"ok": False, "error": str(e)[:200]})
        if p == "/api/resume/generate":   # 个人履历页「生成简历」：按目标岗位出 PDF
            target_id = (body.get("targetId") or "").strip() or None
            template_name = (body.get("templateName") or "").strip() or None
            font_scale = body.get("fontScale") or None
            try:
                result = generate_resume_pdf(target_id, template_name, font_scale)
            except Exception as e:
                append_event("resume.generate", f"生成失败：{e}", actor="api", status="error")
                return self._send(500, {"ok": False, "error": str(e)[:300]})
            append_event("resume.generate",
                         f"已生成 PDF：{result['fileStem']}.pdf（{result['pdfBytes']//1024} KB，模板 {result['templateName']}，字号 ×{result['fontScale']}）",
                         actor="api", payload={"target": result["targetTitle"], "template": result["templateName"], "fontScale": result["fontScale"]})
            return self._send(200, result)
        if p == "/api/resume/templates" and self.command == "DELETE":   # 删除用户模板（内置不可删）
            import re as _re
            name = str(body.get("name") or "")
            if not _re.fullmatch(r"[\w\-]+\.html", name):
                return self._send(400, {"ok": False, "error": "模板名非法"})
            fp = os.path.join(TPL_USER, name)
            if not os.path.exists(fp):
                return self._send(404, {"ok": False, "error": "模板不存在或为内置模板（内置不可删除）"})
            with data_lock():
                os.remove(fp)
            append_event("resume_template.delete", "删除简历模板 " + name, actor="api")
            return self._send(200, {"ok": True, "removed": name})
        if p == "/api/resume/templates":   # 简历模板：PUT {default} 设默认；PUT {name,content} 添加用户模板
            if body.get("default"):
                name = str(body.get("default"))
                all_names = set()
                for base in (TPL_USER, TPL_BUILTIN):
                    if os.path.isdir(base):
                        all_names.update(f for f in os.listdir(base) if f.endswith(".html"))
                if not re.fullmatch(r"[\w\-]+\.html", name) or name not in all_names:
                    return self._send(400, {"ok": False, "error": "模板不存在或名称非法"})
                with data_lock():
                    write_json("resume_template.json", {"default": name})
                append_event("resume_template.default", "默认简历模板已设为 " + name, actor="api")
                return self._send(200, {"ok": True, "default": name})
            name = str(body.get("name") or "").strip()
            content = str(body.get("content") or "")
            if not re.fullmatch(r"[\w\-]+\.html", name):
                return self._send(400, {"ok": False, "error": "模板名须为 [\\w\\-]+.html，如 myresume.html"})
            if len(content) < 200:
                return self._send(400, {"ok": False, "error": "模板内容过短（需 ≥200 字符，包含完整 CSS 与结构）"})
            if "{{" not in content:
                return self._send(400, {"ok": False, "error": "模板缺少 {{占位符}}（需含 {{HEADER}} 等 7 个区块占位符）"})
            os.makedirs(TPL_USER, exist_ok=True)
            with data_lock():
                with open(os.path.join(TPL_USER, name), "w", encoding="utf-8") as f:
                    f.write(content)
            append_event("resume_template.add", "新增简历模板 " + name, actor="api")
            return self._send(200, {"ok": True, "added": name})
        if p == "/api/resume/skill":   # 保存简历撰写规范
            content = str(body.get("content") or "")
            if len(content) < 20:
                return self._send(400, {"ok": False, "error": "内容过短"})
            skill_path = os.path.join(DATA, "resume_skill.md")
            with data_lock():
                with open(skill_path, "w", encoding="utf-8") as f:
                    f.write(content)
            append_event("resume_skill.update", f"简历撰写规范已更新（{len(content)} 字符）", actor="api")
            return self._send(200, {"ok": True, "path": "data/resume_skill.md", "bytes": len(content)})
        if p == "/api/strategy":
            body["updatedAt"] = now()
            with data_lock():
                write_json("strategy.json", body)
            append_event("strategy.update", "投递策略已保存", actor="api",
                         payload={"enabled": body.get("enabled"),
                                  "batch_size": body.get("batch_size")})
            return self._send(200, {"ok": True, "file": "strategy.json", "at": now()})
        if p == "/api/jobs":  # bulk upsert，去重主键 id（BOSS encryptJobId）
            with data_lock():
                jobs = read_json("jobs.json", [])
                idx = {j.get("id"): i for i, j in enumerate(jobs)}
                items = body if isinstance(body, list) else body.get("jobs", [])
                cur_tid = None
                try:
                    prof = read_json("profile.json", {})
                    cur_tid = prof.get("activeTarget") or ((prof.get("targets") or [{}])[0] or {}).get("id")
                except Exception:
                    pass
                ts = now()
                added = updated = 0
                for it in items:
                    jid = it.get("id")
                    if jid in idx:
                        old = jobs[idx[jid]]
                        # 归属目标并入数组（同岗可被多个目标采集）；首采时间保留；最近看到刷新
                        tids = list(dict.fromkeys(list(old.get("targetIds") or []) + ([cur_tid] if cur_tid else [])))
                        old.update({k: v for k, v in it.items() if k not in ("targetId", "targetIds", "firstSeenAt")})
                        old.setdefault("targetId", cur_tid or old.get("targetId"))
                        old["targetIds"] = tids
                        old["lastSeenAt"] = ts
                        updated += 1
                    else:
                        tids = [cur_tid] if cur_tid else list(it.get("targetIds") or ([] if it.get("targetId") else []))
                        it.setdefault("targetId", cur_tid)
                        it.setdefault("targetIds", tids)
                        it.setdefault("firstSeenAt", ts)
                        it["lastSeenAt"] = ts
                        it.setdefault("collectedAt", ts)
                        jobs.append(it); idx[jid] = len(jobs) - 1; added += 1
                write_json("jobs.json", jobs)
            append_event("jobs.import", f"新增 {added}，更新 {updated}，共 {len(jobs)}", actor="api",
                         payload={"added": added, "updated": updated, "total": len(jobs)})
            return self._send(200, {"ok": True, "added": added, "updated": updated, "total": len(jobs)})
        if p == "/api/jobs/prune":   # 清洗岗位池：校招剔除 + 当前目标错配岗位剔除/剥离归属
            try:
                sys.path.insert(0, HERE)
                import job_filter
                ok, rep, err = job_filter.run_prune(DATA)
                if not ok:
                    return self._send(200, {"ok": False, "error": err})
                append_event("jobs.prune", "清洗岗位池：剔除校招 %d、错配 %d、剥离归属 %d（保留 %d）"
                             % (len(rep["school_removed"]), len(rep["mismatch_removed"]),
                                len(rep["detached"]), rep["kept"]), actor="api",
                             payload={"school": len(rep["school_removed"]),
                                      "mismatch": len(rep["mismatch_removed"]),
                                      "detached": len(rep["detached"]), "kept": rep["kept"]})
                return self._send(200, {"ok": True, "report": rep})
            except Exception as e:
                return self._send(200, {"ok": False, "error": str(e)})
        if p == "/api/jobs/refresh":   # 主动采集：启动后台采集会话（分步落盘，前端轮询 status 实时上屏）
            import time as _time
            st = _collect_status()
            if st["running"]:
                return self._send(429, {"ok": False, "code": "busy",
                                        "error": f"采集进行中（已完成 {st['done']}/{st['total']}），无需重复触发"})
            last = read_json("raw/last_collect.json", {})
            gap = _time.time() - (last.get("at") or 0)
            if 0 < gap < 10:
                return self._send(429, {"ok": False, "code": "cooldown",
                                        "error": f"刚完成采集（{int(gap)} 秒前），稍等片刻再刷新"})
            prof = read_json("profile.json", {})
            act = prof.get("activeTarget") or ((prof.get("targets") or [{}])[0] or {}).get("id")
            cur = next((t for t in (prof.get("targets") or []) if t.get("id") == act), None)
            kws = _active_keywords(prof)
            if not kws:
                return self._send(200, {"ok": False, "code": "no_keywords",
                                        "error": "当前目标未设置关键词且无标题，请先在「目标岗位」里填写"})
            city_codes = {}
            try:
                cd = json.load(open(os.path.join(HERE, "cities.json"), encoding="utf-8")).get("cities") or {}
            except Exception:
                cd = {}
            for c in (read_json("search_config.json", {}).get("cities") or []):
                nm = c.get("name")
                code = c.get("code") or cd.get(nm)
                if code:
                    city_codes[nm] = code
            if not city_codes:
                return self._send(200, {"ok": False, "code": "no_city", "error": "未配置城市，先在搜岗设置里添加"})
            # 采集筛选口径：薪资区间（BOSS 新版 URL 参数已失效，仅作提示；真正的区间过滤在阶段2详情页明文薪资上做）
            #            + 招聘类型（BOSS 默认列表即社招；校招走页面点击）
            salary = None
            _s = (read_json("search_config.json", {}) or {}).get("salary") or {}
            if _s.get("min"):
                salary = str(_s["min"]) + "_" + str(_s.get("max") or "")
            _rts = (read_json("search_config.json", {}) or {}).get("recruit_types") or []
            recruitType = "校招" if _rts == ["校招"] else ("社招" if _rts == ["社招"] else None)
            # 探测 boss-daemon 是否在线（快速失败；退出码 0 = 命令处理成功）
            node_bin = shutil.which("node")
            boss_mjs = os.path.join(HERE, "..", "tools", "boss-daemon.mjs")
            probe = subprocess.run([node_bin, boss_mjs, "state"], capture_output=True, text=True, timeout=15)
            if probe.returncode != 0:
                return self._send(200, {"ok": False, "code": "daemon_off",
                                        "error": "BOSS 采集通道未连接：需启动 boss-daemon（左下角状态行或 /api/daemon/start）后再刷新"})
            with _collect_lock:
                _COLLECT.update(running=True, phase="list", done=0, total=len(kws) * len(city_codes),
                                added=0, updated=0, excluded=0, lastAt=None, error=None,
                                salary=salary, recruitType=recruitType, kws=list(kws))
            threading.Thread(target=_collect_worker,
                             args=(list(kws), dict(city_codes), salary, recruitType, act, cur),
                             daemon=True).start()
            return self._send(200, {"ok": True, "started": True, "status": _collect_status()})
        if p == "/api/jobs/refresh-activity":   # 批量刷新岗位活跃度（重新访问详情页抓 .boss-active-time）
            st = _collect_status()
            if st["running"]:
                return self._send(429, {"ok": False, "code": "busy",
                                        "error": f"采集进行中（已完成 {st['done']}/{st['total']}），无需重复触发"})
            with data_lock():
                jobs = read_json("jobs.json", [])
                # 只刷 activity 为空的岗位（最多 50 个一批）
                todo = [{"id": j["id"], "href": j.get("href") or ""}
                        for j in jobs if not (j.get("activity") or "").strip() and j.get("href")]
                todo = todo[:50]
            if not todo:
                return self._send(200, {"ok": True, "refreshed": 0, "msg": "没有待刷新的岗位（都有活跃度标签）"})
            import shutil
            node_bin = shutil.which("node") or "node"
            boss_mjs = os.path.join(ROOT, "tools", "boss-daemon.mjs")
            def _refresh_worker():
                with _collect_lock:
                    _COLLECT.update(running=True, phase="activity", done=0, total=len(todo),
                                    added=0, updated=0, excluded=0, lastAt=None, error=None)
                try:
                    for bi in range(0, len(todo), 12):
                        batch = todo[bi:bi + 12]
                        try:
                            proc = subprocess.run([node_bin, boss_mjs, "collectDetails",
                                                   json.dumps({"jobs": batch, "wait": 9000, "concurrency": 4})],
                                                  capture_output=True, text=True, timeout=240)
                            out = json.loads(proc.stdout[proc.stdout.index("{"):proc.stdout.rindex("}") + 1])
                            items = out.get("items") or []
                        except Exception as e:
                            items = []
                            with _collect_lock:
                                _COLLECT["error"] = str(e)[:200]
                        for it in items:
                            jid = it.get("id")
                            if it.get("activity"):
                                with data_lock():
                                    jobs2 = read_json("jobs.json", [])
                                    for j in jobs2:
                                        if j.get("id") == jid:
                                            j["activity"] = it["activity"]
                                            j["lastSeenAt"] = now()
                                            break
                                    write_json("jobs.json", jobs2)
                        with _collect_lock:
                            _COLLECT["done"] = min(bi + 12, len(todo))
                            _COLLECT["lastAt"] = now()
                finally:
                    with _collect_lock:
                        _COLLECT["running"] = False
            threading.Thread(target=_refresh_worker, daemon=True).start()
            return self._send(200, {"ok": True, "started": True, "todo": len(todo),
                                    "status": _collect_status()})
        if p == "/api/jobs/clear":   # 清空指定目标的岗位（重新采集前置）
            tgt = body.get("target") or ""   # body 来自 api_write 开头统一读取
            if not tgt:
                return self._send(400, {"ok": False, "error": "missing target"})
            with data_lock():
                jobs = read_json("jobs.json", [])
                keep, removed = [], 0
                for j in jobs:
                    tids = [x for x in (j.get("targetIds") or []) if x != tgt]
                    if j.get("targetId") == tgt and not tids:
                        removed += 1
                        continue
                    if j.get("targetId") == tgt and tids:
                        j["targetId"] = tids[0]
                        j["targetIds"] = tids
                    keep.append(j)
                write_json("jobs.json", keep)
            append_event("jobs.clear", f"清空目标岗位 {tgt}：移除 {removed} 条",
                         actor="api", payload={"target": tgt, "removed": removed})
            return self._send(200, {"ok": True, "removed": removed, "left": len(keep)})
        if p == "/api/applications":
            with data_lock():
                apps = read_json("applications.json", [])
                items = body if isinstance(body, list) else [body]
                for it in items:
                    key = it.get("id") or it.get("company")
                    hit = next((a for a in apps if (a.get("id") or a.get("company")) == key), None)
                    if hit:
                        hit.update(it)
                    else:
                        it.setdefault("id", key)
                        it.setdefault("company", it.get("id"))
                        it.setdefault("position", ""); it.setdefault("city", ""); it.setdefault("salary", "")
                        it.setdefault("recruiter", ""); it.setdefault("activity", "")
                        it.setdefault("greetedAt", now()); it.setdefault("resumeSentAt", "")
                        it.setdefault("validation", ""); it.setdefault("review", "")
                        it.setdefault("status", "已沟通")
                        it.setdefault("timeline", [{"at": now(), "event": "创建记录", "note": "api"}])
                        apps.append(it)
                write_json("applications.json", apps)
            append_event("application.add", f"更新投递记录（共 {len(apps)} 家）", actor="api",
                         payload={"total": len(apps)})
            return self._send(200, {"ok": True, "total": len(apps)})
        if p == "/api/feedback":
            with data_lock():
                items = body if isinstance(body, list) else [body]
                cur = read_json("feedback.json", [])
                for it in items:
                    it.setdefault("at", now())
                    cur.append(it)
                    aid = it.get("applicationId") or it.get("company")
                    apps = read_json("applications.json", [])
                    a = next((x for x in apps if (x.get("id") or x.get("company")) == aid), None)
                    if a:
                        t = it.get("type", "")
                        new = {"reply": "已回复", "interview": "约面试", "interviewed": "已面试",
                               "offer": "已offer", "reject": "已拒绝"}.get(t)
                        if new:
                            a["status"] = new
                        a.setdefault("timeline", []).append({"at": it["at"], "event": "反馈:" + t, "note": it.get("content", "")[:120]})
                        write_json("applications.json", apps)
                write_json("feedback.json", cur)
            append_event("feedback.add", f"记录反馈（共 {len(cur)} 条）", actor="api",
                         payload={"total": len(cur)})
            return self._send(200, {"ok": True, "total": len(cur)})
        if p == "/api/insight/ignore":
            if self.command == "PUT":
                tgt = (body.get("target") or "global").strip() or "global"
                dims = [str(d).strip() for d in (body.get("dims") or []) if str(d).strip()]
                cur = read_json("insight_ignore.json", {"targets": {}}) or {"targets": {}}
                cur["targets"][tgt] = dims
                with data_lock():
                    write_json("insight_ignore.json", cur)
                append_event("insight.ignore", f"目标 {tgt} 忽略维度 {len(dims)} 个", actor="api",
                             payload={"target": tgt, "dims": dims})
                return self._send(200, {"ok": True, "target": tgt, "dims": dims})
        if p == "/api/jobs/match" and self.command == "POST":
            # 岗位池匹配度批量重算：每岗按 jd_match 单岗层级匹配出 matchRate.overall（%），
            # 落盘 matchScore + matchLevel（≥60 强相关 / ≥35 弱相关 / 其余无关），前端相关度列显示百分比。
            try:
                import engine as _engine
                import jd_match as _jdm
            except Exception:
                _engine, _jdm = None, None
            if not _jdm:
                return self._send(200, {"ok": False, "error": "jd_match 引擎不可用"})
            jbs = read_json("jobs.json", [])
            prof = read_json("profile.json", {})
            tgt = (body.get("target") or prof.get("activeTarget") or "").strip()
            ig = _engine._load_ignored_dims(tgt) if _engine else []
            lex = json.load(open(os.path.join(HERE, "lexicon.json"), encoding="utf-8"))
            scored = 0
            for j in jbs:
                rep = _jdm.build_job_insight(j, lex, prof, ig)
                if rep is None:
                    j["matchScore"] = None
                    continue
                score = rep["matchRate"]["overall"]
                nd = len(rep["dims"])
                # 维度过少（JD 信息不足/文本过短）→ 置信度衰减，避免 2-3 个维度全达标刷出 100%
                if nd < 5:
                    score = round(score * nd / 5)
                j["matchScore"] = score
                j["matchDims"] = nd
                j["matchLevel"] = "strong" if score >= 60 else ("weak" if score >= 35 else "none")
                scored += 1
            with data_lock():
                write_json("jobs.json", jbs)
            append_event("jobs.match", f"岗位池匹配度重算 {scored}/{len(jbs)} 岗", actor="api",
                         payload={"scored": scored, "total": len(jbs), "target": tgt})
            return self._send(200, {"ok": True, "scored": scored, "total": len(jbs)})
        if p == "/api/analyze":
            try:
                q = parse_qs(u.query)
                tgt = (q.get("target") or [""])[0]
                full = (q.get("full") or ["0"])[0] == "1"
                cmd = [sys.executable, os.path.join(HERE, "engine.py")]
                if tgt:
                    cmd += ["--target", tgt]
                if full:
                    cmd += ["--full"]
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=300, cwd=os.path.dirname(HERE))
                append_event("analyze", f"重算技能树 exit={r.returncode} target={tgt or '-'} full={full}", actor="api",
                             payload={"returncode": r.returncode, "target": tgt, "full": full})
                return self._send(200, {"ok": r.returncode == 0, "stdout": r.stdout[-4000:], "stderr": r.stderr[-1500:]})
            except Exception as e:
                return self._send(200, {"ok": False, "error": str(e)})
        if p == "/api/import":
            bundle = os.path.join(DATA, "exports", "export_bundle.zip")
            if not os.path.exists(bundle):
                return self._send(404, {"error": "no export_bundle.zip to import"})
            with zipfile.ZipFile(bundle) as z:
                z.extractall(HERE)
            append_event("import.restore", "从导出包恢复数据", actor="api")
            return self._send(200, {"ok": True, "restored": bundle})
        return self._send(404, {"error": "unknown api", "path": p})

    # -- static
    def serve_static(self, p):
        if p in ("/", ""):
            p = "/index.html"
        fp = os.path.normpath(os.path.join(WEB, p.lstrip("/")))
        if not fp.startswith(WEB) or not os.path.exists(fp):
            return self._send(404, "not found", "text/plain; charset=utf-8")
        ext = os.path.splitext(fp)[1]
        self._send(200, open(fp, "rb").read(), MIME.get(ext, "application/octet-stream"))

    def serve_resume_file(self, p):
        """暴露 data/resumes/ 下的 HTML/PDF/PNG 给前端预览与下载。"""
        rel = unquote(p[len("/resumes/"):])
        fp = os.path.normpath(os.path.join(RESUMES_DIR, rel))
        if not fp.startswith(RESUMES_DIR) or not os.path.exists(fp) or os.path.isdir(fp):
            return self._send(404, "not found", "text/plain; charset=utf-8")
        ext = os.path.splitext(fp)[1]
        ctype = MIME.get(ext, "application/octet-stream")
        # PDF 允许浏览器内联预览，同时支持下载；文件名做 RFC 5987 编码避免 latin-1 报错
        if ext == ".pdf":
            from urllib.parse import quote as _q
            fname = os.path.basename(fp)
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(os.path.getsize(fp)))
            self.send_header("Content-Disposition",
                             f"inline; filename*=UTF-8''{_q(fname)}")
            self.send_header("Cache-Control", "no-store, must-revalidate")
            self.end_headers()
            with open(fp, "rb") as f:
                self.wfile.write(f.read())
            return
        self._send(200, open(fp, "rb").read(), ctype)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.environ.get("WORKBENCH_PORT", 8787)))
    ap.add_argument("--host", default="127.0.0.1")
    a = ap.parse_args()
    os.makedirs(DATA, exist_ok=True)
    ensure_data_files()
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    print(f"求职工作台已启动 → http://{a.host}:{a.port}")
    print(f"数据目录：{DATA}")
    print(f"Agent 契约：http://{a.host}:{a.port}/api/contract")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")


if __name__ == "__main__":
    main()
