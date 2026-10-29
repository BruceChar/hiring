#!/usr/bin/env python3
"""工作台自检：验证 CLI 与 HTTP API 的读写链路，跑完自动清理测试数据。

    python3 workbench/selftest.py            # 只测 CLI + 文件
    python3 workbench/selftest.py --http     # 额外测 HTTP API（需先启动 server.py）
"""
import json
import os
import subprocess
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")     # ★ 用户数据目录
PY = sys.executable
sys.path.insert(0, HERE)
import server  # noqa: E402
from events import append_event, read_events, EVENTS_FILE  # noqa: E402
TEST_COMPANY = "【自检】测试公司"
TEST_JOB_ID = "selftest-job-001"
ok = fail = 0


def check(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  PASS  {name}")
    else:
        fail += 1
        print(f"  FAIL  {name} {extra}")


def cli(*args):
    r = subprocess.run([PY, os.path.join(HERE, "cli.py"), *args], cwd=ROOT, capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def load(name):
    p = os.path.join(DATA, name)
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None


def save(name, obj):
    json.dump(obj, open(os.path.join(DATA, name), "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def cleanup():
    for name, key, val in [("jobs.json", "id", TEST_JOB_ID), ("applications.json", "company", TEST_COMPANY)]:
        rows = load(name) or []
        rows = [r for r in rows if r.get(key) != val]
        save(name, rows)
    fb = load("feedback.json") or []
    save("feedback.json", [f for f in fb
                           if f.get("company") != TEST_COMPANY
                           and f.get("applicationId") != TEST_COMPANY])
    if os.path.exists(EVENTS_FILE):
        lines = [l for l in open(EVENTS_FILE, encoding="utf-8")
                 if TEST_COMPANY not in l and "selftest.heartbeat" not in l]
        open(EVENTS_FILE, "w", encoding="utf-8").writelines(lines)


def main():
    http = "--http" in sys.argv
    print("== 数据文件 ==")
    for f in ["profile.json", "search_config.json", "strategy.json", "jobs.json",
              "applications.json", "feedback.json"]:
        check(f"{f} 存在且合法", isinstance(load(f), (dict, list)))
    check("templates 目录存在(App 资产)", os.path.isdir(os.path.join(HERE, "templates")))

    print("\n== CLI 只读 ==")
    rc, out = cli("status")
    check("cli status", rc == 0 and "候选人" in out, out[:120])
    rc, out = cli("pending", "--limit", "5")
    check("cli pending", rc == 0, out[:120])
    rc, out = cli("brief")
    check("cli brief", rc == 0 and "任务简报" in out, out[:120])
    rc, out = cli("app", "list")
    check("cli app list", rc == 0, out[:120])
    rc, out = cli("cities", "杭州")
    check("cli cities 解析城市码", rc == 0 and "101210100" in out, out[:80])
    rc, out = cli("strategy")
    check("cli strategy", rc == 0 and "batch_size" in out, out[:80])
    rc, out = cli("schedule", "--cron")
    check("cli schedule 生成 cron", rc == 0 and "* * " in out, out[:120])
    rc, out = cli("onboarding")
    check("cli onboarding 可执行", "数据完备度" in out, out[:120])

    print("\n== CLI 写路径 ==")
    tmp = os.path.join(HERE, "_selftest_job.json")
    json.dump([{"id": TEST_JOB_ID, "company": TEST_COMPANY, "position": "AI Agent 工程师",
                "city": "杭州", "salary": "30-50K", "jd": "自检用 JD", "skillTags": ["Agent"]}],
              open(tmp, "w", encoding="utf-8"), ensure_ascii=False)
    rc, out = cli("jobs", "import", tmp)
    check("cli jobs import", rc == 0 and "新增 1" in out, out[:120])
    check("岗位已落库", any(j.get("id") == TEST_JOB_ID for j in (load("jobs.json") or [])))
    os.remove(tmp)

    rc, out = cli("app", "add", "--company", TEST_COMPANY, "--position", "AI Agent 工程师",
                  "--city", "杭州", "--salary", "30-50K", "--status", "已沟通")
    check("cli app add", rc == 0 and TEST_COMPANY in out, out[:120])
    rc, out = cli("app", "status", TEST_COMPANY, "简历已发")
    check("cli app status", rc == 0 and "简历已发" in out, out[:120])
    rec = next((x for x in (load("applications.json") or []) if x.get("company") == TEST_COMPANY), None)
    check("状态已更新", rec and rec.get("status") == "简历已发")

    rc, out = cli("feedback", "add", "--company", TEST_COMPANY, "--type", "interview",
                  "--content", "自检：约面试", "--signal", "positive")
    check("cli feedback add", rc == 0, out[:120])
    rec = next((x for x in (load("applications.json") or []) if x.get("company") == TEST_COMPANY), None)
    check("反馈自动推进状态->约面试", rec and rec.get("status") == "约面试", str(rec and rec.get("status")))
    check("时间线已追加", rec and len(rec.get("timeline", [])) >= 3)

    print("\n== run-batch 退出码契约 ==")
    jobs2 = [{"id": "j1", "company": "C1"}, {"id": "j2", "company": "C2"}]
    st_on = {"enabled": True, "pause_after_consecutive_no_reply": 5, "min_reply_rate": 0.1}
    b = server.compute_batch_status(cfg={}, st=st_on, jobs=jobs2, apps=[{"company": "C1", "status": "简历已发"}])
    check("有候选未投 → exit 0", b["code"] == 0, str(b))
    b = server.compute_batch_status(cfg={}, st=st_on, jobs=jobs2,
                                    apps=[{"company": "C1", "status": "简历已发"},
                                          {"company": "C2", "status": "简历已发"}])
    check("全部已投 → exit 2", b["code"] == 2, str(b))
    b = server.compute_batch_status(cfg={}, st={"enabled": False, "pause_after_consecutive_no_reply": 5, "min_reply_rate": 0.1},
                                    jobs=jobs2, apps=[])
    check("策略停用 → exit 3", b["code"] == 3, str(b))
    seq = [{"company": f"N{i}", "status": "简历已发", "greetedAt": f"2026-01-0{i + 1}T09:00:00"} for i in range(5)]
    b = server.compute_batch_status(cfg={}, st=st_on, jobs=jobs2, apps=seq)
    check("连续无回复触发暂停 → exit 3", b["code"] == 3, str(b))
    rc, out = cli("run-batch")
    check("cli run-batch 退出码∈{0,2,3}", rc in (0, 2, 3), f"rc={rc} {out[:100]}")
    check("run-batch 输出状态行", "run-batch] status=" in out, out[-160:])

    print("\n== agent_tailor 退出码契约 ==")
    tail = os.path.join(ROOT, "tools", "agent_tailor.py")
    real_job = next((j for j in (load("jobs.json") or []) if j.get("jd")), None)
    if real_job:
        # 核心项目 key 由 profile 的 rank 动态决定（与 agent_tailor 校验同一来源）
        sys.path.insert(0, os.path.join(ROOT, "tools"))
        import agent_tailor as _at
        _keys = (_at.build_facts().get("project_keys") or [])[:3]
        t_item = os.path.join("/tmp", "selftest_tailor_item.json")
        # 合法条目：把真实岗位的 id/company 填进去，dry-run 应通过且不写盘
        ok_item = {"id": real_job["id"], "company": real_job["company"],
                   "position": real_job["position"], "intent": "自检求职意向",
                   "resume_title": "Agent系统工程师", "summary": "8 年研发经验，主导 Agent 系统工程落地与多 Agent 协作体系，具备高并发、存储引擎与评测闭环能力。",
                   "skills": [["Agent 架构", "多 Agent 协作、上下文管理、工具调用与编排"]],
                   "project_order": _keys}
        bad_item = dict(ok_item, id="wrong-id-000")
        for p, label in ((ok_item, "ok"), (bad_item, "bad")):
            json.dump(p, open(f"/tmp/selftest_tailor_{label}.json", "w", encoding="utf-8"), ensure_ascii=False)
        env = dict(os.environ, LLM_API_KEY="", LLM_MODEL="")
        r = subprocess.run([PY, tail, real_job["id"], "--from-json", "/tmp/selftest_tailor_ok.json", "--dry-run"],
                           cwd=ROOT, capture_output=True, text=True, env=env, timeout=120)
        check("合法条目 dry-run → exit 0", r.returncode == 0, r.stdout[-120:])
        r = subprocess.run([PY, tail, real_job["id"], "--from-json", "/tmp/selftest_tailor_bad.json", "--dry-run"],
                           cwd=ROOT, capture_output=True, text=True, env=env, timeout=120)
        check("非法条目(错id) → exit 1 不写盘", r.returncode == 1, r.stdout[-120:])
        r = subprocess.run([PY, tail, "no-such-job-id", "--from-json", "/tmp/selftest_tailor_ok.json", "--dry-run"],
                           cwd=ROOT, capture_output=True, text=True, env=env, timeout=120)
        check("岗位不存在 → exit 3", r.returncode == 3, r.stdout[-120:])
        env_nokey = dict(os.environ, LLM_API_KEY="", LLM_MODEL="")
        r = subprocess.run([PY, tail, real_job["id"], "--dry-run"],
                           cwd=ROOT, capture_output=True, text=True, env=env_nokey, timeout=120)
        check("无 LLM key → exit 2 且明确提示", r.returncode == 2 and "LLM_API_KEY" in r.stdout, r.stdout[-120:])
    else:
        check("存在可测岗位(jobs.json 有 JD)", False)

    print("\n== Agent 事件日志 ==")
    e0 = append_event("selftest.heartbeat", "自检写入", actor="selftest", payload={"x": 1})
    check("append_event 写入成功", e0 and e0.get("action") == "selftest.heartbeat")
    evs = read_events(limit=100)
    check("事件可读回(新→旧)", evs and evs[0].get("action") == "selftest.heartbeat",
          str(evs[0] if evs else None)[:80])
    check("文件路径正确", os.path.exists(EVENTS_FILE) and EVENTS_FILE.endswith("agent-events.jsonl"))
    mine = [x for x in evs if TEST_COMPANY in (x.get("detail") or "")]
    check("CLI 写路径自动埋点(≥2)", len(mine) >= 2, f"got {len(mine)}")
    rb = [x for x in read_events(limit=20) if x.get("action") == "run.batch"]
    check("run-batch 已埋点", len(rb) >= 1, str(rb[:1]))

    if http:
        print("\n== HTTP API ==")
        base = "http://127.0.0.1:8787/api"
        def get(p):
            with urllib.request.urlopen(base + p, timeout=10) as r:
                return json.loads(r.read().decode())
        def post(p, body, method="POST"):
            req = urllib.request.Request(base + p, data=json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json"}, method=method)
            with urllib.request.urlopen(req, timeout=10) as r:
                return json.loads(r.read().decode())
        try:
            check("GET /health", get("/health").get("ok") is True)
            check("GET /profile", get("/profile").get("name") is not None)
            check("GET /stats 含 insights", "insights" in get("/stats"))
            check("GET /cities", get("/cities").get("count", 0) > 20)
            check("GET /strategy", "batch_size" in get("/strategy"))
            check("GET /onboarding", "items" in get("/onboarding"))
            check("GET /scoring", "evidenceLevels" in get("/scoring") and "groups" in get("/scoring"))
            prof = get("/profile")
            sk = (prof.get("skills") or [{}])[0]
            check("技能为 v3 四分类字段",
                  {"group", "cluster", "evidenceLevel", "projectRefs"} <= set(sk.keys()), str(list(sk.keys()))[:90])
            check("profile schemaVersion=3", prof.get("schemaVersion") == 3, str(prof.get("schemaVersion")))
            groups = {x.get("group") for x in prof.get("skills", [])}
            check("四大分类至少覆盖三类", len(groups & {"professional", "tools", "soft", "credentials"}) >= 3, str(groups))
            check("GET /skill-links", isinstance(get("/skill-links"), dict))
            check("技能附带客观评分", isinstance(sk.get("_score", {}).get("score"), int), str(sk.get("_score"))[:60])
            check("GET /schedule 含 cron", isinstance(get("/schedule").get("cron"), list))
            check("GET /events 返回事件列表", isinstance(get("/events").get("events"), list))
            cfg = get("/config")
            check("城市码自动补全", all(c.get("code") for c in cfg.get("cities", [])) if cfg.get("cities") else True)
            code, resolved = server.resolve_city_code("南京市")   # 返回 (code, resolved)
            check("别名解析(南京市→南京)", code == "101190100" and resolved is True, f"{code} {resolved}")
            check("未收录城市返回 False", server.resolve_city_code("不存在的城市")[1] is False)
            check("GET /config", "keywords" in get("/config"))
            check("GET /jobs", isinstance(get("/jobs"), list))
            r = post("/applications", {"id": TEST_COMPANY, "status": "已面试"}, "PATCH")
            check("PATCH /applications", r.get("ok") is True)
            check("PATCH 已生效", next(x for x in get("/applications") if x["company"] == TEST_COMPANY)["status"] == "已面试")
            r = post("/feedback", {"applicationId": TEST_COMPANY, "type": "offer", "content": "自检 offer", "signal": "positive"})
            check("POST /feedback", r.get("ok") is True)
            check("状态推进到已offer", next(x for x in get("/applications") if x["company"] == TEST_COMPANY)["status"] == "已offer")
        except Exception as e:
            check("HTTP API 可访问", False, str(e)[:120])

    cleanup()
    print("\n== 清理 ==")
    check("测试岗位已移除", not any(j.get("id") == TEST_JOB_ID for j in (load("jobs.json") or [])))
    check("测试投递已移除", not any(x.get("company") == TEST_COMPANY for x in (load("applications.json") or [])))
    check("测试反馈已移除", not any(f.get("company") == TEST_COMPANY for f in (load("feedback.json") or [])))

    print(f"\n结果：{ok} 通过 / {fail} 失败")
    sys.exit(1 if fail else 0)


if __name__ == "__main__":
    main()
