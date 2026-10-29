#!/usr/bin/env python3
"""求职工作台 CLI —— 供任意 Agent 或人工调用，直接读写 data/*.json，无需启动服务。

    python3 workbench/cli.py status
    python3 workbench/cli.py brief
    python3 workbench/cli.py pending --limit 10
    python3 workbench/cli.py jobs import new_jobs.json
    python3 workbench/cli.py app add --company X --position Y --city 杭州 --salary 30-45K
    python3 workbench/cli.py app status X 已回复
    python3 workbench/cli.py feedback add --company X --type reply --content "..." --signal positive
    python3 workbench/cli.py analyze
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime

from events import append_event

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")     # ★ 用户数据目录


def now():
    return datetime.now().isoformat(timespec="seconds")


def load(name, default):
    p = os.path.join(DATA, name)
    if not os.path.exists(p):
        return default
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return default


def save(name, obj):
    os.makedirs(DATA, exist_ok=True)
    json.dump(obj, open(os.path.join(DATA, name), "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def sal_range(s):
    import re
    n = [int(x) for x in re.findall(r"(\d+)", s or "")]
    return (n[0], n[1]) if len(n) > 1 else (0, 0)


# ------------------------------------------------------------------ commands
def cmd_status(a):
    prof = load("profile.json", {})
    cfg = load("search_config.json", {})
    jobs = load("jobs.json", [])
    apps = load("applications.json", [])
    fb = load("feedback.json", [])
    targets = prof.get("targets") or []
    active = prof.get("activeTarget") or (targets[0].get("id") if targets else None)
    cur = next((t for t in targets if t.get("id") == active), None)
    print(f"候选人：{prof.get('name')}｜技能 {len(prof.get('skills', []))} 项")
    if targets:
        print(f"目标岗位：{len(targets)} 个，当前选中「{(cur or {}).get('title') or prof.get('title')}」"
              + (f"（关键词 {len((cur or {}).get('keywords') or [])} 个）" if cur and cur.get('keywords') else ""))
        for t in targets:
            mark = "●" if t.get("id") == active else "○"
            print(f"  {mark} {t.get('title') or '(未命名)'}"
                  + (f"｜关键词 {len(t.get('keywords') or [])} 个" if t.get('keywords') else ""))
    print(f"岗位池：{len(jobs)} 条（完整 JD {sum(1 for j in jobs if j.get('jd'))}）")
    print(f"投递：{len(apps)} 家｜反馈：{len(fb)} 条")
    print("状态分布：" + "，".join(f"{k}={v}" for k, v in
          {s: sum(1 for x in apps if x.get('status') == s) for s in
           ['未沟通', '已沟通', '简历已发', '已回复', '约面试', '已面试', '已offer', '已拒绝']}.items() if v))
    print(f"搜岗参数：城市 {'/'.join(c.get('name', '') for c in cfg.get('cities', []))}｜"
          f"薪资 {cfg.get('salary', {}).get('min')}-{cfg.get('salary', {}).get('max')}K｜"
          f"当前目标关键词 {len((cur or {}).get('keywords') or [])} 个｜批次 {cfg.get('batch_size')}")


def cmd_pending(a):
    """Candidate jobs that pass the configured filters and have NOT been applied to yet."""
    import server as _srv
    cfg = load("search_config.json", {})
    jobs = load("jobs.json", [])
    apps = load("applications.json", [])
    prof = load("profile.json", {})
    act = prof.get("activeTarget")
    cur_t = next((t for t in (prof.get("targets") or []) if t.get("id") == act), None)
    kws = (cur_t or {}).get("keywords") or cfg.get("keywords", [])
    applied = {x.get("company") for x in apps}
    lo, hi = cfg.get("salary", {}).get("min", 0), cfg.get("salary", {}).get("max", 999)
    exclc = set(cfg.get("exclude_companies", []))
    rt = cfg.get("recruit_types") or []
    prio = {c["name"]: c.get("priority", 9) for c in cfg.get("cities", [])}
    out = []
    for j in jobs:
        if j.get("company") in applied or j.get("company") in exclc:
            continue
        if rt and _srv.infer_recruit_type(j) not in rt:
            continue
        a_, b_ = sal_range(j.get("salary", ""))
        if b_ and (a_ > hi or b_ < lo):
            continue
        if not any(k.lower() in j.get("position", "").lower() for k in kws) and not j.get("jd"):
            continue
        act = j.get("activity", "")
        act_rank = 0 if "刚刚" in act or "今日" in act else 1 if "3日" in act else 2
        out.append((prio.get(j.get("city"), 8), act_rank, -(b_ or 0), j))
    out.sort(key=lambda x: x[:3])
    n = a.limit or cfg.get("batch_size", 10)
    print(f"符合条件且未投递：{len(out)} 条，展示前 {min(n, len(out))} 条\n")
    for _, _, _, j in out[:n]:
        print(f"  {j.get('city', ''):<4}{j.get('company', '')[:20]:<22}{j.get('position', '')[:30]:<32}"
              f"{j.get('salary', ''):<12}{j.get('activity', '') or '未标注'}")
    print("\n下一步：按 Skill 流程抓取这些岗位的 JD → 生成简历 → 校验 → 投递 → `cli.py app add` 记录")


def cmd_brief(a):
    sys.path.insert(0, HERE)
    from server import build_brief
    print(build_brief())


def cmd_jobs(a):
    jobs = load("jobs.json", [])
    if a.action == "prune":
        import job_filter
        ok, rep, err = job_filter.run_prune(DATA)
        if not ok:
            print("清洗失败：%s" % err)
            return 1
        print("岗位池清洗完成（目标 %s · %s）：" % (rep.get("active_title") or rep.get("target"), rep.get("at")))
        print("  剔除校招岗 %d 条" % len(rep["school_removed"]))
        for r in rep["school_removed"][:10]:
            print("    - %s | %s" % (r.get("position"), r.get("company")))
        print("  剔除错配岗 %d 条" % len(rep["mismatch_removed"]))
        for r in rep["mismatch_removed"][:10]:
            print("    - %s | %s" % (r.get("position"), r.get("company")))
        print("  剥离目标归属 %d 条（岗位保留给其他目标）" % len(rep["detached"]))
        for r in rep["detached"][:10]:
            print("    - %s | %s" % (r.get("position"), r.get("company")))
        print("  保留 %d 条 · 备份 %s" % (rep["kept"], rep.get("backup") or "（无变更）"))
        return 0
    if a.action == "import":
        items = json.load(open(a.file, encoding="utf-8"))
        items = items if isinstance(items, list) else items.get("jobs", [])
        idx = {j.get("id"): i for i, j in enumerate(jobs)}
        cur_tid = None
        try:
            prof = load("profile.json", {})
            cur_tid = prof.get("activeTarget") or ((prof.get("targets") or [{}])[0] or {}).get("id")
        except Exception:
            pass
        ts = now()
        add = upd = 0
        for it in items:
            jid = it.get("id")
            if not jid:
                continue
            if jid in idx:
                old = jobs[idx[jid]]
                tids = list(dict.fromkeys(list(old.get("targetIds") or []) + ([cur_tid] if cur_tid else [])))
                old.update({k: v for k, v in it.items() if k not in ("targetId", "targetIds", "firstSeenAt")})
                old.setdefault("targetId", cur_tid or old.get("targetId"))
                old["targetIds"] = tids
                old["lastSeenAt"] = ts
                upd += 1
            else:
                it.setdefault("targetId", cur_tid)
                it.setdefault("targetIds", [cur_tid] if cur_tid else [])
                it.setdefault("firstSeenAt", ts)
                it["lastSeenAt"] = ts
                it.setdefault("collectedAt", ts)
                jobs.append(it); idx[jid] = len(jobs) - 1; add += 1
        save("jobs.json", jobs)
        append_event("jobs.import", f"新增 {add}，更新 {upd}，共 {len(jobs)}", actor="cli",
                     payload={"added": add, "updated": upd, "total": len(jobs)})
        print(f"导入完成：新增 {add}，更新 {upd}，总计 {len(jobs)}")
    elif a.action == "list":
        rows = jobs
        if a.city:
            rows = [j for j in rows if j.get("city") == a.city]
        if a.has_jd:
            rows = [j for j in rows if j.get("jd")]
        for j in rows[: a.limit or 30]:
            print(f"{j.get('id', '')[:12]}  {j.get('city', ''):<4}{j.get('company', '')[:18]:<20}{j.get('position', '')[:30]:<32}{j.get('salary', '')}")
        print(f"\n共 {len(rows)} 条")


def cmd_app(a):
    apps = load("applications.json", [])
    a.company = a.company or a.company_opt or (a.value if a.action == "add" else None)
    if a.action == "add":
        if not a.company:
            print("必须提供公司名：app add --company X 或 app add X"); sys.exit(1)
        key = a.company
        hit = next((x for x in apps if x.get("company") == key), None)
        rec = {"id": key, "company": a.company, "position": a.position or "", "city": a.city or "",
               "salary": a.salary or "", "recruiter": a.recruiter or "", "activity": a.activity or "",
               "greetedAt": a.at or now(), "status": a.status or "已沟通",
               "resumeSentAt": a.resume_at or "", "review": a.review or "", "validation": a.validation or "",
               "timeline": [{"at": a.at or now(), "event": "打招呼", "note": "cli"}]}
        if hit:
            hit.update({k: v for k, v in rec.items() if v})
        else:
            apps.append(rec)
        save("applications.json", apps)
        append_event("application.add", f"已投递：{a.company}", actor="cli",
                     payload={"company": a.company, "status": rec.get("status")})
        print(f"已记录投递：{a.company}（当前共 {len(apps)} 家）")
    elif a.action == "status":
        hit = next((x for x in apps if x.get("company") == a.company), None)
        if not hit:
            print("未找到该公司记录"); sys.exit(1)
        hit["status"] = a.value
        hit.setdefault("timeline", []).append({"at": now(), "event": f"状态改为 {a.value}", "note": "cli"})
        save("applications.json", apps)
        append_event("application.status", f"{a.company} → {a.value}", actor="cli",
                     payload={"company": a.company, "status": a.value})
        print(f"{a.company} → {a.value}")
    elif a.action == "list":
        for x in apps:
            print(f"  {x.get('company', '')[:18]:<20}{x.get('position', '')[:28]:<30}{x.get('status', ''):<8}{x.get('city', '')}")
        print(f"\n共 {len(apps)} 家")
    elif a.action == "next":
        """Return the next company names that are contactable but not yet applied (dedupe check)."""
        have = {x.get("company") for x in apps}
        print(json.dumps(sorted(c for c in {j.get("company") for j in load("jobs.json", [])} - have if c),
                         ensure_ascii=False, indent=1))


def cmd_feedback(a):
    fb = load("feedback.json", [])
    fb.append({"applicationId": a.company, "company": a.company, "at": now(), "type": a.type,
               "content": a.content or "", "signal": a.signal or "neutral", "action": a.action or ""})
    save("feedback.json", fb)
    apps = load("applications.json", [])
    hit = next((x for x in apps if x.get("company") == a.company), None)
    if hit:
        new = {"reply": "已回复", "interview": "约面试", "interviewed": "已面试",
               "offer": "已offer", "reject": "已拒绝"}.get(a.type)
        if new:
            hit["status"] = new
        hit.setdefault("timeline", []).append({"at": now(), "event": f"反馈:{a.type}", "note": (a.content or "")[:120]})
        save("applications.json", apps)
    append_event("feedback.add", f"{a.company} / {a.type}", actor="cli",
                 payload={"company": a.company, "type": a.type, "signal": a.signal})
    print(f"已记录反馈：{a.company} / {a.type}（共 {len(fb)} 条）")


def cmd_cities(a):
    import json as _j
    d = _j.load(open(os.path.join(HERE, "cities.json"), encoding="utf-8"))
    if a.name:
        code = d["cities"].get(a.name)
        print(f"{a.name} -> {code}" if code else f"{a.name} 未收录；请让 Agent 打开 BOSS 首页切换城市后从 URL 读取 city= 参数")
    else:
        print(f"已收录 {len(d['cities'])} 个城市：")
        for k, v in d["cities"].items():
            print(f"  {k:<8}{v}")


def cmd_strategy(a):
    if a.set:
        st = load("strategy.json", {})
        for kv in a.set:
            k, _, v = kv.partition("=")
            cur = st
            parts = k.split(".")
            for x in parts[:-1]:
                cur = cur.setdefault(x, {})
            try:
                cur[parts[-1]] = json.loads(v)
            except Exception:
                cur[parts[-1]] = v
        st["updatedAt"] = now()
        save("strategy.json", st)
        append_event("strategy.update", "策略已更新", actor="cli",
                     payload={"enabled": st.get("enabled"), "batch_size": st.get("batch_size")})
        print("策略已更新")
    st = load("strategy.json", {})
    print(json.dumps(st, ensure_ascii=False, indent=1))


def cmd_schedule(a):
    st = load("strategy.json", {})
    cad = st.get("cadence", {})
    print(f"模式：{st.get('mode')}　周期：{cad.get('type')} {cad.get('times')} 周{cad.get('weekdays')}")
    print(f"每次 {st.get('batch_size')} 家，每日上限 {st.get('daily_limit')}，时间窗 "
          f"{'、'.join(w['from'] + '-' + w['to'] for w in st.get('time_windows', []))}")
    print(f"需人工确认：{'是' if st.get('require_approval') else '否'}　连续 {st.get('pause_after_consecutive_no_reply')} 家无回复暂停")
    if a.cron:
        print("\n可直接挂到 crontab：")
        for line in _cron_lines(st):
            print("  " + line)


def _cron_lines(st):
    cad = st.get("cadence", {}) or {}
    days = ",".join(str(int(d) % 7) for d in (cad.get("weekdays") or [1, 2, 3, 4, 5]))
    return [f"{int((t.split(':') + ['0'])[1])} {int(t.split(':')[0])} * * {days}  cd {ROOT} && python3 workbench/cli.py run-batch >> data/logs/cron.log 2>&1"
            for t in (cad.get("times") or ["09:30"])]


def cmd_onboarding(a):
    import server as _srv
    ob = _srv.build_onboarding()
    print("数据完备度：" + ("全部就绪" if ob["complete"] else "存在缺失"))
    for i in ob["items"]:
        print(f"  [{'✓' if i['done'] else ' '}] {i['label']:<10}{i['file']}")
        if not i["done"]:
            print(f"      → 向用户询问：{i['ask']}")
    sys.exit(0 if ob["complete"] else 1)


def cmd_run_batch(a):
    """cron 入口：输出本轮任务简报与候选岗位，由 Agent 接手执行。

    退出码契约（任何平台调度器据此决定是否启动 Agent）：
      0 = ready   有候选、未暂停，Agent 应开工
      2 = idle    无候选岗位，本轮无需行动
      3 = paused  策略停用或触发暂停条件（连续无回复 / 回复率过低），本轮不执行
    """
    import server as _srv
    st = _srv.compute_batch_status()
    print(_srv.build_brief())
    print("\n" + "=" * 60)
    print(f"[run-batch] status={st['status']} exit_code={st['code']} reason={st['reason']} "
          f"pending={st['pending']}")
    if st["status"] == "ready":
        cmd_pending(a)
    elif st["status"] == "idle":
        print("（无符合条件的候选岗位，本轮无需行动）")
    else:
        print(f"（策略暂停：{st['reason']}，本轮不执行；Agent 应复盘并决定是否调整策略）")
    append_event("run.batch",
                 f"status={st['status']} code={st['code']} reason={st['reason']} pending={st['pending']}",
                 actor="scheduler", payload=st)
    sys.exit(st["code"])


def cmd_links(a):
    """账实相符断链检测：技能 ↔ 项目 交叉验证（R1-R4）。"""
    import json as _json
    script = os.path.join(HERE, "skill_links.py")
    if not os.path.exists(script):
        print("skill_links.py 缺失"); sys.exit(1)
    r = subprocess.run([sys.executable, script], cwd=ROOT, capture_output=True, text=True)
    print(r.stdout or "", r.stderr or "")
    p = os.path.join(DATA, "skill_links.json")
    if os.path.exists(p):
        d = _json.load(open(p, encoding="utf-8"))
        print("\n断链 %d 条 / 缺失条目 %d 条 / 通过率 %.0f%%" % (
            len(d.get("broken", [])), len(d.get("missing", [])),
            (d.get("summary", {}) or {}).get("passRate", 0) * 100))


def cmd_analyze(a):
    r = subprocess.run([sys.executable, os.path.join(HERE, "engine.py")], cwd=ROOT, capture_output=True, text=True)
    append_event("analyze", f"重算技能树 exit={r.returncode}", actor="cli",
                 payload={"returncode": r.returncode})
    print(r.stdout or "", r.stderr or "")
    sys.exit(r.returncode)


def ensure_data():
    """新机器/首次运行：缺失的数据文件从 templates 初始化。"""
    try:
        import server as _srv
        os.makedirs(DATA, exist_ok=True)
        _srv.ensure_data_files()
    except Exception as e:
        print(f"（数据初始化跳过：{e}）", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(prog="workbench", description="求职工作台 CLI")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="总览").set_defaults(fn=cmd_status)
    p = sub.add_parser("pending", help="筛选出符合条件且未投递的岗位")
    p.add_argument("--limit", type=int); p.set_defaults(fn=cmd_pending)
    sub.add_parser("brief", help="输出给 Agent 的任务简报").set_defaults(fn=cmd_brief)

    p = sub.add_parser("jobs", help="岗位池")
    p.add_argument("action", choices=["list", "import", "prune"])
    p.add_argument("file", nargs="?")
    p.add_argument("--city"); p.add_argument("--limit", type=int); p.add_argument("--has-jd", action="store_true")
    p.set_defaults(fn=cmd_jobs)

    p = sub.add_parser("app", help="投递记录")
    p.add_argument("action", choices=["add", "status", "list", "next"])
    p.add_argument("company", nargs="?"); p.add_argument("value", nargs="?")
    p.add_argument("--company", dest="company_opt")
    p.add_argument("--position"); p.add_argument("--city"); p.add_argument("--salary"); p.add_argument("--recruiter")
    p.add_argument("--activity"); p.add_argument("--status"); p.add_argument("--at"); p.add_argument("--resume-at")
    p.add_argument("--review"); p.add_argument("--validation")
    p.set_defaults(fn=cmd_app)

    p = sub.add_parser("feedback", help="反馈")
    p.add_argument("action", choices=["add"]); p.add_argument("--company", required=True)
    p.add_argument("--type", required=True); p.add_argument("--content"); p.add_argument("--signal"); p.add_argument("--action")
    p.set_defaults(fn=cmd_feedback)

    p = sub.add_parser("cities", help="城市码字典（用户只需填城市名）")
    p.add_argument("name", nargs="?"); p.set_defaults(fn=cmd_cities)

    p = sub.add_parser("strategy", help="查看/修改投递策略")
    p.add_argument("--set", action="append", help="如 --set batch_size=5 --set cadence.times=[\"09:30\"]")
    p.set_defaults(fn=cmd_strategy)

    p = sub.add_parser("schedule", help="投递排期（可生成 crontab）")
    p.add_argument("--cron", action="store_true"); p.set_defaults(fn=cmd_schedule)

    sub.add_parser("onboarding", help="数据完备度检查").set_defaults(fn=cmd_onboarding)

    p = sub.add_parser("run-batch", help="cron 入口：输出简报与候选岗位")
    p.add_argument("--limit", type=int); p.set_defaults(fn=cmd_run_batch)

    sub.add_parser("links", help="技能↔项目 账实相符断链检测").set_defaults(fn=cmd_links)

    sub.add_parser("analyze", help="重算技能树与差距分析").set_defaults(fn=cmd_analyze)

    a = ap.parse_args()
    ensure_data()
    a.fn(a)


if __name__ == "__main__":
    main()
