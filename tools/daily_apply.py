#!/usr/bin/env python3
"""每日投递前置流水线（cron / 调度器统一入口）。

一次运行走完「时间窗 → 批次门禁 → 简历图片检测 → 确定性校验 → 出任务单」，
任何一步不通过都不会走到投递。策略要求人工确认（require_approval=true）时，
本脚本只产出名单，实际打招呼由 Agent/用户确认后执行。

用法：
    python3 tools/daily_apply.py                 # 正常跑
    python3 tools/daily_apply.py --at 10:30      # 按指定时刻判断时间窗（演练/测试用）
    python3 tools/daily_apply.py --skip-time-window

退出码：
    0 = 可以开工（任务单已生成，等待确认/执行）
    2 = 本轮无候选岗位（idle）
    3 = 策略暂停（paused，需先复盘）
    4 = 校验失败（有简历图/内容不过关，禁止投递）
"""
import argparse
import datetime as dt
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STRATEGY = os.path.join(ROOT, "data", "strategy.json")
LOGS = os.path.join(ROOT, "data", "logs")
DAILY_DIR = os.path.join(LOGS, "daily")
EVENTS = os.path.join(LOGS, "agent-events.jsonl")


def load_json(path, default=None):
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:
        return default


def run(cmd, timeout=600):
    """跑子命令，返回 (exit_code, stdout+stderr)。"""
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=ROOT)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def http_ok(port, path="/json/version", timeout=2.0):
    """本地端口是否可用（浏览器通道/服务健康检查）。"""
    import urllib.error
    import urllib.request
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d%s" % (port, path), timeout=timeout) as r:
            return 200 <= r.status < 400
    except Exception:
        return False


def in_time_window(now, strategy):
    """是否落在允许时间段（策略硬约束）。"""
    wins = strategy.get("time_windows") or []
    if not wins:
        return True, "未设置时间窗"
    cur = now.strftime("%H:%M")
    for w in wins:
        if w.get("from", "00:00") <= cur <= w.get("to", "23:59"):
            return True, "落在时间窗 %s-%s" % (w.get("from"), w.get("to"))
    return False, "当前 %s 不在任何时间窗内（%s）" % (
        cur, "、".join("%s-%s" % (w.get("from"), w.get("to")) for w in wins))


def in_weekday(now, strategy):
    days = (strategy.get("cadence") or {}).get("weekdays") or []
    return (not days) or (now.isoweekday() in days), "周%s" % now.isoweekday()


def log_event(action, detail, status, payload):
    os.makedirs(LOGS, exist_ok=True)
    rec = {"ts": dt.datetime.now().isoformat(timespec="seconds"), "actor": "daily",
           "action": action, "detail": detail, "status": status, "payload": payload}
    with open(EVENTS, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + chr(10))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--at", help="按 HH:MM 判断时间窗（默认取当前时间）")
    ap.add_argument("--skip-time-window", action="store_true")
    ap.add_argument("--ignore-batch-gate", action="store_true",
                    help="演练用：忽略 run-batch 的暂停/空闲结论，继续走图片检测与校验")
    args = ap.parse_args()

    now = dt.datetime.now()
    if args.at:
        hh, mm = args.at.split(":")
        now = now.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)

    strategy = load_json(STRATEGY, {}) or {}
    os.makedirs(DAILY_DIR, exist_ok=True)
    lines = ["# 每日投递任务单 %s" % now.strftime("%Y-%m-%d %H:%M"), ""]

    # --- 0. 策略开关与时间窗 ------------------------------------------------
    if not strategy.get("enabled", True):
        lines += ["## 结论：策略已停用（enabled=false）", "", "不执行本轮。"]
        code, status = 3, "paused.strategy_disabled"
    else:
        ok_day, daytxt = in_weekday(now, strategy)
        ok_win, wintxt = in_time_window(now, strategy)
        if args.skip_time_window:
            ok_win, wintxt = True, "时间窗检查已跳过（--skip-time-window）"
        lines += ["## 1. 时间窗检查", "- 星期：%s %s" % (daytxt, "OK" if ok_day else "不在允许的星期"),
                  "- 时段：%s" % wintxt, ""]
        if not (ok_day and ok_win):
            code, status = 3, "paused.out_of_window"
        else:
            code, status = None, None

    result = {"at": now.isoformat(timespec="seconds"), "status": status, "exitCode": code,
              "images": None, "validation": None, "candidates": None}

    # --- 1. 批次门禁（退出码契约） -----------------------------------------
    if code is None:
        rc, out = run([sys.executable, os.path.join(ROOT, "workbench", "cli.py"), "run-batch"])
        tail = [l for l in out.splitlines() if l.startswith("[run-batch]")]
        lines += ["## 2. 批次门禁 run-batch", "```", (tail[-1] if tail else "exit=%d" % rc), "```", ""]
        result["batch"] = {"exitCode": rc, "summary": tail[-1] if tail else ""}
        if rc != 0 and args.ignore_batch_gate:
            lines += ["（演练：--ignore-batch-gate，忽略上面的批次结论继续走校验）", ""]
        elif rc != 0:
            code, status = rc, ("paused" if rc == 3 else "idle")
            lines += ["## 结论：本轮不投递", "",
                      ("策略暂停：先按 SKILL 第 8 步复盘（暂停原因见上），再决定是否调整 data/strategy.json。"
                       if rc == 3 else "无候选岗位，本轮无需行动。"), ""]
        else:
            code, status = None, "ready"

    # --- 1.5 投递通道健康检查（浏览器依赖）----------------------------------
    # 图片门禁/校验是纯 Python，不需要浏览器；但「同步会话去重 / 打招呼 / 发简历图」
    # 依赖 9222(独立调试 Chrome)、9223(headless 打印 Chrome) 和 8787(工作台服务)。
    # 任一 DOWN 时任务单必须写明，避免「门禁全绿 → 实际发不出去」的误判。
    if code is None:
        channels = [
            ("9222 BOSS 控制通道", 9222, "/json/version"),
            ("9223 打印 Chrome", 9223, "/json/version"),
            ("8787 工作台服务", 8787, "/api/stats"),
        ]
        lines += ["## 2.5 投递通道检查", ""]
        ch = {}
        for name, port, path in channels:
            ok = http_ok(port, path)
            ch[name] = ok
            lines += ["- %s：%s" % (name, "UP" if ok else "**DOWN**")]
        if not (ch["9222 BOSS 控制通道"] and ch["9223 打印 Chrome"]):
            lines += ["", "> ⚠️ 浏览器通道不可用：本轮的「会话去重 / 打招呼 / 发简历图」无法执行。",
                      "> 按 SKILL：Chrome 必须在**工作区文件沙盒之外**启动（沙盒内起 Chrome 会崩）。",
                      "> 恢复：普通终端跑 python3 workbench/server.py，Web 左下角点「BOSS 采集」；",
                      "> 打印通道：./tools/ensure_print_chrome.sh。"]
        lines += [""]
        result["channels"] = ch
    # --- 2. 简历图片检测（硬门禁） -----------------------------------------
    if code is None:
        lines += ["## 3. 简历图片检测（硬门禁）", ""]
        rc, out = run([sys.executable, os.path.join(ROOT, "tools", "check_resume_images.py")])
        lines += ["```", out.strip(), "```", ""]
        summary = load_json(os.path.join(ROOT, "data", "raw", "image_check.json"), {}) or {}
        failed = [i["file"] for i in summary.get("items", []) if not i.get("passed")]
        result["images"] = {"exitCode": rc, "total": summary.get("total"),
                            "passed": summary.get("passed"), "failed": failed}
        if rc != 0:
            code, status = 4, "gate.image_failed"
            lines += ["## 结论：图片检测未通过，禁止投递", "",
                      "不合格图片：%s" % ("、".join(failed) or "（见上）"), ""]

    # --- 3. 确定性校验 ------------------------------------------------------
    if code is None:
        lines += ["## 4. 投递前确定性校验", ""]
        rc, out = run([sys.executable, os.path.join(ROOT, "tools", "validate_resume.py")])
        lines += ["```", out.strip(), "```", ""]
        result["validation"] = {"exitCode": rc}
        if rc != 0:
            code, status = 4, "gate.validation_failed"
            lines += ["## 结论：校验未通过，禁止投递", ""]

    # --- 3.5 已联系去重检查（防重复打招呼）--------------------------------
    # 只按 applications.json 去重是不够的：用户本人/其他渠道主动触达的会话不在其中，
    # 会对已联系过的公司重复打招呼（打招呼不可撤回）。以 data/raw/chats.json 为「已联系」真源。
    if code is None:
        lines += ["## 5. 已联系去重检查", ""]
        chats = load_json(os.path.join(ROOT, "data", "raw", "chats.json"), None)
        tailor = load_json(os.path.join(ROOT, "data", "tailor.json"), {}) or {}
        applied_c = {a.get("company") for a in (load_json(os.path.join(ROOT, "data", "applications.json"), []) or [])}
        dup = []
        if chats is None:
            lines += ["- 未找到 data/raw/chats.json，跳过（刷新：node tools/sync_contacts.mjs）", ""]
        else:
            raws = [i.get("raw", "") for i in chats.get("items", [])]
            # 只看「已生成简历但尚未记录投递」的目标；已记录的本就该跳过
            pending_targets = [i.get("company") for i in tailor.get("items", [])
                               if i.get("company") and i.get("company") not in applied_c]
            for c in pending_targets:
                hit = next((r for r in raws if c and c in r), None)
                if hit:
                    dup.append({"company": c, "chat": hit[:120]})
            lines += ["- 会话总数：%d；本次待发目标：%d" % (len(raws), len(pending_targets))]
            if dup:
                for d in dup:
                    lines += ["- **[已联系，禁止再打招呼]** %s ← %s" % (d["company"], d["chat"])]
            else:
                lines += ["- 无重复触达"]
            lines += [""]
        result["contactDedupe"] = {"chatsLoaded": chats is not None, "duplicates": dup}
        if dup:
            code, status = 4, "gate.duplicate_contact"
    # --- 4. 候选名单 --------------------------------------------------------
    if code is None:
        limit = str(strategy.get("batch_size", 10))
        rc, out = run([sys.executable, os.path.join(ROOT, "workbench", "cli.py"),
                       "pending", "--limit", limit])
        lines += ["## 5. 本轮候选（已按策略过滤 + 排除已投递）", "", "```", out.strip(), "```", ""]
        result["candidates"] = {"exitCode": rc, "raw": out.strip()}

        need_approval = strategy.get("require_approval", True)
        lines += ["## 6. 下一步", ""]
        if need_approval:
            lines += ["**策略要求人工确认名单（require_approval=true）**：把上面候选交给用户确认后，",
                      "再按 SKILL 第 6-8 步执行「独立 Agent 复核 → 打招呼 → 发高清简历图 → 记录」。",
                      "未经确认不得打招呼（打招呼不可撤回）。"]
        else:
            lines += ["策略未要求人工确认：可直接按 SKILL 第 6-8 步执行。"]
        lines += ["", "- 只允许发送上面第 3 步检测通过的简历图；未通过的绝不发送。",
                  "- 同公司同岗位已在 data/applications.json 中的，跳过。",
                  "- 出现「环境异常」/安全校验立即停止本轮。"]

    result["status"] = status
    result["exitCode"] = code

    stamp = now.strftime("%Y-%m-%d")
    md_path = os.path.join(DAILY_DIR, "%s-%s.md" % (stamp, now.strftime("%H%M")))
    js_path = os.path.join(DAILY_DIR, "%s-%s.json" % (stamp, now.strftime("%H%M")))
    text = chr(10).join(lines) + chr(10)
    open(md_path, "w", encoding="utf-8").write(text)
    json.dump(result, open(js_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    log_event("daily.pipeline", "status=%s code=%s" % (status, code), "ok", result)
    print(text)
    print("任务单：%s" % md_path)
    return code


if __name__ == "__main__":
    sys.exit(main())
