#!/usr/bin/env python3
"""按 JD 定制简历全链路：LLM 读 JD → 产出 tailor 条目 → 不编造门禁 → 写盘 → 出图 → 校验。

用法（任一 OpenAI 兼容网关）：
    LLM_API_KEY=sk-xxx LLM_MODEL=ep-xxx python3 tools/agent_tailor.py <job_id>
可选环境变量：LLM_BASE_URL（默认豆包方舟 https://ark.cn-beijing.volces.com/api/v3）
离线通道（跳过 LLM，直接用现成 JSON 条目跑校验 + 出图 + 门禁）：
    python3 tools/agent_tailor.py <job_id> --from-json item.json
调试：--dry-run 只到"产出 + 后校验"，不写盘不出图；--no-run 只写盘不跑出图流水线。

流程：job(JD) + profile(固定事实) + 技能树侧重 → prompt → LLM JSON →
      后校验(schema / 标题 / 公司名 / 数字 / 占位符) → 合并写 data/tailor.json →
      gen_resume → print_pdf(Chrome CDP) → build_images(pdfium) → validate_resume

退出码：0=完成且门禁通过  1=LLM 输出未通过后校验  2=LLM API 失败
        3=参数/数据缺失    4=出图流水线或门禁失败
"""
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, "tools")
sys.path.insert(0, TOOLS)
sys.path.insert(0, ROOT)

import gen_resume  # noqa: E402  (main guard 保护，安全 import)

BASE = gen_resume.BASE
PROJECTS = gen_resume.PROJECTS
WORK = gen_resume.WORK
PROJECT_KEYS = list(PROJECTS.keys())          # harness / socrates / storage / gateway
TAILOR_PATH = os.path.join(ROOT, "data", "tailor.json")
TAILOR_BAK = os.path.join(ROOT, "data", "raw", "tailor.json")
EVENTS = os.path.join(ROOT, "data", "logs", "agent-events.jsonl")
RESUME_HTML = os.path.join(ROOT, "data", "resumes", "html")
RESUME_PDF = os.path.join(ROOT, "data", "resumes", "pdf")

LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "")

# 固定事实里允许出现的公司/机构名（LLM 不得引入新公司）
ALLOWED_ORGS = ["Socrates", "ParallelFinance", "杭州波卡科技", "杭州石匍丁科技",
                "北京中存超为", "中国科学技术大学", "杭州电子科技大学", "mazi"]
NUM_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:ms|倍|TB|GB|MB|KB|%|亿|万|K|QPS|节点)")
PLACEHOLDER_RE = re.compile(r"(TODO|XXX|待填|占位|\{\{|\}\})", re.I)


def log_event(action, detail, status="ok", payload=None):
    try:
        os.makedirs(os.path.dirname(EVENTS), exist_ok=True)
        ev = {"actor": "agent_tailor", "action": action, "detail": detail,
              "status": status, "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
              "payload": payload or {}}
        with open(EVENTS, "a", encoding="utf-8") as f:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")
    except Exception:
        pass


def read_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def find_job(job_id):
    for j in read_json(os.path.join(ROOT, "data", "jobs.json"), []):
        if (j.get("id") or j.get("uid")) == job_id:
            return j
    return None


def _norm_num(s):
    """数字归一化：去空格/全角空格，统一比较口径（"10 倍"=="10倍"）。"""
    return re.sub(r"[\s\u3000]", "", s)


def allowed_numbers(facts=None):
    """从固定事实里提取"数字+单位"集合，LLM 不得编造新数字。"""
    if facts is not None:
        proj_pool = [str(l) for l in facts.get("projects", [])]
    else:
        proj_pool = [p.get("stack", "") + " " + " ".join(p.get("bullets", [])) for p in PROJECTS.values()]
    pool = " ".join([str(BASE.get(k, "")) for k in ("years", "phone")] +
                    [json.dumps(BASE.get("education"), ensure_ascii=False)] +
                    proj_pool + [str(w) for w in WORK])
    return {_norm_num(n) for n in NUM_RE.findall(pool)}


def build_facts():
    # 核心项目优先按 profile rank（>0）动态收集；没有任何 rank 时回退硬编码 PROJECTS（旧行为）
    core = gen_resume.load_core_projects()
    if core is not None:
        proj_lines = ["[%s] %s | %s | %s | %s"
                      % (p["key"], p["title"], p["meta"], p["stack"], " / ".join(p["bullets"]))
                      for p in core]
        keys = [p["key"] for p in core]
    else:
        proj_lines = []
        for k in PROJECT_KEYS:
            p = PROJECTS[k]
            proj_lines.append("[%s] %s | %s | %s | %s"
                              % (k, p["title"], p["meta"], p["stack"], " / ".join(p["bullets"])))
        keys = PROJECT_KEYS
    work_lines = ["%s | %s | %s | %s" % (w[0], w[1], w[2], w[3]) for w in WORK]
    edu_lines = ["%s | %s | %s" % e for e in BASE["education"]]
    return {
        "name": BASE["name"], "phone": BASE["phone"], "email": BASE["email"],
        "city": BASE["city"], "years": BASE["years"], "github": BASE["github"],
        "education": edu_lines, "work": work_lines, "projects": proj_lines,
        "project_keys": keys, "core_projects": core,
    }


def build_skill_hint():
    """技能树里必备/常见技能 → 作为侧重提示（LLM 参考，不许照抄岗位词进标题）。"""
    tree = read_json(os.path.join(ROOT, "data", "skills_tree.json"), {"domains": []})
    out = []
    for d in tree.get("domains", []) or []:
        for s in (d.get("skills", []) or []):
            tier = s.get("coverageTier") or ""
            if tier in ("必备", "常见") and s.get("name"):
                out.append("%s(%s)" % (s.get("name"), tier))
    return "、".join(out[:40])


def build_prompt(job, facts, hint):
    jd = (job.get("jd") or "").strip() or "（该岗位暂无 JD 原文）"
    core = facts.get("core_projects")
    if core:
        keys_json = json.dumps([p["key"] for p in core], ensure_ascii=False)
        # 动态模式：核心项目已按 rank 固定顺序，project_order 可省略；若输出须与固定事实一致
        po_schema = ("\"project_order\":%s（可选：核心项目 id，须逐字符等于固定事实里的 project_keys，不得增删改序）}" % keys_json)
    else:
        po_schema = "\"project_order\":[\"harness\",\"socrates\",\"storage\",\"gateway\"]按与JD相关度排序，至少3个}"
    return [
        {"role": "system", "content":
         "你是求职简历定制助手。你的唯一任务：根据岗位 JD，把候选人的【固定事实】重排为侧重合适的简历条目。"
         "铁律：只能重排、强调、措辞优化【固定事实】里的内容；禁止引入固定事实之外的任何公司、产品、数字、头衔、项目。"
         "简历标题固定为「%s」。输出必须是合法 JSON，不得包含 JSON 之外的文字。"
         "输出 schema：{\"id\":\"岗位id\",\"company\":\"公司\",\"position\":\"岗位\","
         "\"intent\":\"一句话求职意向\",\"resume_title\":\"%s\","
         "\"summary\":\"≤180字 个人简介，只能组合固定事实\","
         "\"skills\":[[\"领域名\",\"该领域能打的点，只能来自固定事实\"], 共3条],"
         "%s"
         % (BASE.get("title") or "Agent系统工程师", BASE.get("title") or "Agent系统工程师", po_schema)},
        {"role": "user", "content":
         "【岗位】\n岗位id：%s（JSON 里的 id 必须逐字符等于它）\n公司：%s\n岗位：%s\n薪资/经验：%s\n\n【JD 全文】\n%s\n\n"
         "【技能树侧重参考】\n%s\n\n【固定事实（只准从这里取材）】\n%s\n\n"
         "请输出 tailor 条目 JSON。" % (
             job.get("id", ""), job.get("company", ""), job.get("position", ""),
             "%s / %s" % (job.get("salary", ""), job.get("experience", "")),
             jd[:3000], hint or "（无）", json.dumps(facts, ensure_ascii=False)[:4000])},
    ]


def call_llm(messages, timeout=180):
    if not LLM_API_KEY or not LLM_MODEL:
        raise RuntimeError("缺少 LLM_API_KEY / LLM_MODEL 环境变量（或用 --from-json 走离线通道）")
    url = LLM_BASE_URL.rstrip("/") + "/chat/completions"
    body = {"model": LLM_MODEL, "messages": messages, "temperature": 0.3,
            "response_format": {"type": "json_object"}}
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + LLM_API_KEY})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8")[:300]
        except Exception:
            pass
        if e.code == 400 and "response_format" in str(e) or "response_format" in detail:
            body.pop("response_format", None)
            req = urllib.request.Request(
                url, data=json.dumps(body).encode("utf-8"),
                headers={"Content-Type": "application/json", "Authorization": "Bearer " + LLM_API_KEY})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.loads(r.read().decode("utf-8"))
        else:
            raise RuntimeError("LLM HTTP %s: %s" % (e.code, detail))
    except urllib.error.URLError as e:
        raise RuntimeError("LLM 网络错误: %s" % e)
    try:
        return data["choices"][0]["message"]["content"]
    except Exception:
        raise RuntimeError("LLM 响应结构异常: %s" % json.dumps(data, ensure_ascii=False)[:300])


def extract_json(text):
    text = re.sub(r"```(?:json)?", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("响应中没有 JSON 对象")
    return json.loads(text[start:end + 1])


def validate_item(item, facts, job, allowed_nums):
    """后校验（不编造门禁）。返回 (ok, errors)。"""
    errs = []
    title = BASE.get("title") or "Agent系统工程师"
    if item.get("resume_title") != title:
        errs.append("resume_title 必须为「%s」，实际「%s」" % (title, item.get("resume_title")))
    if not str(item.get("intent") or "").strip():
        errs.append("intent 为空")
    summary = str(item.get("summary") or "")
    if len(summary) < 40:
        errs.append("summary 过短（<%d 字）" % 40)
    if len(summary) > 300:
        errs.append("summary 过长（>300 字）")
    skills = item.get("skills") or []
    if not (1 <= len(skills) <= 5):
        errs.append("skills 应为 1-5 条，实际 %d" % len(skills))
    skill_pairs = []
    for s in skills:
        if isinstance(s, dict):          # 兼容 {label,text}
            label, text = s.get("label"), s.get("text")
        elif isinstance(s, list) and len(s) == 2:   # 标准 ["label","text"]
            label, text = s[0], s[1]
        else:
            label = text = None
        skill_pairs.append((label, text))
        if not str(label or "").strip() or not str(text or "").strip():
            errs.append("skills 条目 label/text 有空值")
    po = item.get("project_order") or []
    core = facts.get("core_projects")
    if core:
        # 动态模式：核心项目由 rank 固定，渲染忽略 project_order；若提供了则须是 project_keys 的无重复子集
        keys = facts.get("project_keys") or []
        if po and (not all(k in keys for k in po) or len(set(po)) != len(po)):
            errs.append("project_order 非法（应为 %s 的无重复子集）" % keys)
    else:
        if len(po) < 3 or not all(k in PROJECT_KEYS for k in po):
            errs.append("project_order 需为 %s 的子集且 ≥3 项" % PROJECT_KEYS)
        if len(set(po)) != len(po):
            errs.append("project_order 有重复")
    if str(item.get("id") or "") != job.get("id"):
        errs.append("id 与岗位不一致")
    if str(item.get("company") or "") != job.get("company"):
        errs.append("company 与岗位不一致")

    # 不编造门禁：公司名 / 数字 / 占位符
    text = " ".join([summary, item.get("intent", "")] + [str(t or "") for _, t in skill_pairs])
    facts_corpus = " ".join([
        json.dumps(facts, ensure_ascii=False),
        " ".join(str(l) for l in facts.get("projects", [])),
        " ".join(str(w) for w in WORK),
    ])
    allowed_org_pool = (ALLOWED_ORGS + [w[0].split("（")[0] for w in WORK]
                        + [e[0] for e in BASE["education"]] + [str(job.get("company") or "")])
    known_tech = {"Agent", "Harness", "mazi", "JSON", "RPC", "RBAC", "MCP", "K8s", "SIMD", "LLM",
                  "Token", "Contract", "Goal", "Task", "Step", "ToolGateway", "Goal-Task-Step",
                  "EC", "GF", "AVX512", "DeFi", "GraphQL", "BFF", "Polkadot", "Socrates",
                  "ParallelFinance", "C", "Python", "TypeScript", "Java", "Redis", "PostgreSQL",
                  "Nginx", "Docker", "Linux", "Git", "MCP"}
    orgs = re.findall(r"[A-Z][A-Za-z0-9]{2,}", text) + \
           re.findall(r"[\u4e00-\u9fa5]{2,8}(?:科技|公司|集团|银行|大学|学院|支付|物流|金融|信息|软件)", text)
    for org in orgs:
        if org in known_tech or org in facts_corpus:
            continue
        if any(o and (o in org or org in o) for o in allowed_org_pool):
            continue
        errs.append("疑似新事实「%s」（固定事实之外的机构/专名）" % org)
    new_nums = [_norm_num(n) for n in NUM_RE.findall(text)]
    for n in new_nums:
        if n not in allowed_nums:
            errs.append("疑似编造数字「%s」（固定事实之外）" % n)
    if PLACEHOLDER_RE.search(summary + str(item.get("skills"))):
        errs.append("存在占位符文本")
    return (not errs, errs)


def load_or_new_tailor():
    for p in (TAILOR_PATH, TAILOR_BAK):
        t = read_json(p, None)
        if isinstance(t, dict) and isinstance(t.get("items"), list):
            return t, p
    return {"items": []}, TAILOR_PATH


def merge_item(item):
    t, src = load_or_new_tailor()
    items = [i for i in t["items"] if i.get("id") != item["id"]]
    items.append(item)
    t["items"] = items
    os.makedirs(os.path.dirname(TAILOR_PATH), exist_ok=True)
    with open(TAILOR_PATH, "w", encoding="utf-8") as f:
        json.dump(t, f, ensure_ascii=False, indent=1)
    return src


def run(cmd, timeout=600):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def pipeline():
    """gen_resume → print_pdf(CDP) → build_images → validate_resume。返回 (ok, 摘要)。"""
    steps = []
    r = run([sys.executable, os.path.join(TOOLS, "gen_resume.py"), TAILOR_PATH, RESUME_HTML])
    if r.returncode != 0:
        return False, "gen_resume 失败: " + r.stderr[-300:]
    steps.append("gen_resume ok")

    report = read_json(os.path.join(RESUME_HTML, "render_report.json"), [])
    if isinstance(report, dict):
        report = report.get("items", []) or []
    pdfs, skipped = [], []
    os.makedirs(RESUME_PDF, exist_ok=True)
    for it in report:
        name = os.path.splitext(os.path.basename(it.get("html", "")))[0]
        pdf = os.path.join(RESUME_PDF, name + ".pdf")
        rr = run(["node", os.path.join(TOOLS, "print_pdf.mjs"), it["html"], pdf], timeout=180)
        if rr.returncode == 0 and os.path.exists(pdf):
            pdfs.append(pdf)
        else:
            skipped.append(name)
    steps.append("print_pdf %d ok%s" % (len(pdfs), ", 跳过: " + ",".join(skipped) if skipped else ""))

    r = run([sys.executable, os.path.join(TOOLS, "build_images.py"), "260"], timeout=900)
    if r.returncode != 0:
        return False, "build_images 失败: " + r.stderr[-300:]
    steps.append("build_images ok")

    r = run([sys.executable, os.path.join(TOOLS, "validate_resume.py")], timeout=300)
    ok = r.returncode == 0
    tail = r.stdout.strip().splitlines()
    return ok, " | ".join(steps + ["validate=%s" % ("PASS" if ok else "FAIL")]) + ("\n" + "\n".join(tail[-3:]) if tail else "")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 3
    job_id = sys.argv[1]
    from_json = None
    dry_run = "--dry-run" in sys.argv
    no_run = "--no-run" in sys.argv
    if "--from-json" in sys.argv:
        from_json = sys.argv[sys.argv.index("--from-json") + 1]

    job = find_job(job_id)
    if not job:
        print("未找到岗位 %s" % job_id)
        return 3
    facts = build_facts()
    allowed_nums = allowed_numbers(facts)

    if from_json:
        with open(from_json, encoding="utf-8") as f:
            item = json.load(f)
        print("离线通道：读取 %s" % from_json)
    else:
        prompt = build_prompt(job, facts, build_skill_hint())
        print("调用 LLM：%s / %s ..." % (LLM_BASE_URL, LLM_MODEL or "(未设置)"))
        try:
            raw = call_llm(prompt)
        except Exception as e:
            log_event("tailor_llm_error", str(e)[:200], status="error")
            print("LLM 失败：%s" % e)
            return 2
        try:
            item = extract_json(raw)
        except Exception as e:
            log_event("tailor_parse_error", str(e)[:200], status="error")
            print("JSON 解析失败：%s\n原始响应：%s" % (e, raw[:500]))
            return 1

    ok, errs = validate_item(item, facts, job, allowed_nums)
    if not ok:
        log_event("tailor_rejected", "%s: %s" % (job.get("company"), "; ".join(errs)), status="error", payload={"errors": errs})
        print("后校验未通过（不写盘）：")
        for e in errs:
            print("  - " + e)
        return 1

    if dry_run:
        print("dry-run：校验通过，不写盘不出图。")
        print(json.dumps(item, ensure_ascii=False, indent=1))
        return 0

    src = merge_item(item)
    log_event("tailor_generated", "%s | %s | %s" % (job.get("company"), job.get("position"), item.get("intent", "")),
              payload={"id": job_id, "src": src})
    print("已写入 %s（%d 个条目）" % (TAILOR_PATH, len(load_or_new_tailor()[0]["items"])))

    if no_run:
        print("--no-run：出图流水线未执行，请手动跑 tools/validate_resume.py 前先出图。")
        return 0

    ok, summary = pipeline()
    print(summary)
    return 0 if ok else 4


if __name__ == "__main__":
    sys.exit(main())
