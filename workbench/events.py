#!/usr/bin/env python3
"""Agent 事件日志 + 数据文件并发锁（零依赖，Python3 标准库）。

事件日志：data/logs/agent-events.jsonl
  —— 任何 Agent / CLI / API / 调度器的可审计操作都追加一行，供：
     1) 看板「最近 Agent 操作」实时展示；
     2) 外部 Agent 断点恢复（接手时先读最近事件）；
     3) 调度器判断上次 run-batch 的结果。

并发锁：data/logs/.data.lock（fcntl.flock）
  —— 保护 HTTP API（ThreadingHTTPServer 多线程）与 CLI 的 JSON 读-改-写事务，
     避免两个写入者互相覆盖。拿不到锁的环境自动降级为无锁，绝不阻断业务。
"""
import json
import os
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")
LOGS = os.path.join(DATA, "logs")
EVENTS_FILE = os.path.join(LOGS, "agent-events.jsonl")
LOCK_FILE = os.path.join(LOGS, ".data.lock")

# 事件行动命名约定：<domain>.<action>，如 run.batch / jobs.import / application.add
ACTIONS = ("run.batch", "jobs.import", "application.add", "application.status",
           "feedback.add", "strategy.update", "config.update", "profile.update",
           "analyze", "import.restore", "export", "selftest.heartbeat")


def now():
    return datetime.now().isoformat(timespec="seconds")


def _ensure():
    os.makedirs(LOGS, exist_ok=True)


def append_event(action, detail="", actor="system", status="ok", payload=None):
    """追加一条事件。任何失败都静默降级，不阻断业务。返回事件 dict 或 None。"""
    try:
        _ensure()
        line = {"ts": now(), "actor": actor, "action": action,
                "detail": (detail or "")[:300], "status": status,
                "payload": payload if isinstance(payload, dict) else {}}
        with open(EVENTS_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
        return line
    except Exception:
        return None


def read_events(limit=50, action=None, actor=None):
    """读最近 limit 条事件（新→旧）。文件不存在或损坏行自动跳过。"""
    out = []
    try:
        if not os.path.exists(EVENTS_FILE):
            return []
        with open(EVENTS_FILE, encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    e = json.loads(ln)
                except Exception:
                    continue
                if action and e.get("action") != action:
                    continue
                if actor and e.get("actor") != actor:
                    continue
                out.append(e)
    except Exception:
        return []
    return out[-limit:][::-1]


class _NullLock:
    """拿不到 flock 时的降级锁（什么都不做）。"""
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def data_lock():
    """跨进程文件锁（flock）。线程/进程间互斥；异常环境自动降级为无锁。"""
    try:
        import fcntl
    except Exception:
        return _NullLock()
    try:
        _ensure()
        f = open(LOCK_FILE, "a+")
        fcntl.flock(f, fcntl.LOCK_EX)
    except Exception:
        try:
            f.close()
        except Exception:
            pass
        return _NullLock()

    class _Lock:
        def __init__(self, fp):
            self._fp = fp

        def __enter__(self):
            return self

        def __exit__(self, *a):
            try:
                fcntl.flock(self._fp, fcntl.LOCK_UN)
            finally:
                self._fp.close()
            return False

    return _Lock(f)
