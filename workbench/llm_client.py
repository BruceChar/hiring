"""LLM 客户端（零依赖，OpenAI 兼容协议）。

设计：
- 读 data/llm_config.json（base_url / api_key / model），没配就 disabled
- 自动读 macOS 系统代理（scutil --proxy），否则国内网关可能 DNS 解析失败
- 只暴露 chat(messages, json_mode=False, timeout=60) 一个函数
- 失败/超时/没配 key 都返回 None，调用方降级到规则结果
"""
import json
import os
import re
import subprocess
import urllib.error
import urllib.request

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "data", "llm_config.json")


def _system_proxy():
    """读 macOS 系统代理，返回 http_proxy 或 None。"""
    try:
        out = subprocess.check_output(["scutil", "--proxy"], timeout=3).decode("utf-8", "ignore")
        if "HTTPSEnable : 1" in out:
            m = re.search(r'HTTPSProxy : (\S+)', out)
            p = re.search(r'HTTPSPort : (\d+)', out)
            if m and p:
                return f"http://{m.group(1)}:{p.group(1)}"
        if "HTTPEnable : 1" in out:
            m = re.search(r'HTTPProxy : (\S+)', out)
            p = re.search(r'HTTPPort : (\d+)', out)
            if m and p:
                return f"http://{m.group(1)}:{p.group(1)}"
    except Exception:
        pass
    return None


def _opener():
    proxy = _system_proxy()
    if proxy:
        return urllib.request.build_opener(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    return urllib.request.build_opener()


def _load():
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        if isinstance(cfg, dict) and cfg.get("api_key") and cfg.get("model"):
            return cfg
    except Exception:
        pass
    # 环境变量兜底
    key = os.environ.get("LLM_API_KEY", "")
    model = os.environ.get("LLM_MODEL", "")
    if key and model:
        return {
            "base_url": os.environ.get("LLM_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3"),
            "api_key": key,
            "model": model,
        }
    return None


def is_enabled():
    return _load() is not None


def chat(messages, json_mode=False, timeout=60):
    """调 /chat/completions，返回 content 字符串；失败返回 None。

    messages: [{"role":"system"/"user", "content":"..."}, ...]
    json_mode: True 时 response_format={"type":"json_object"}
    """
    cfg = _load()
    if not cfg:
        return None
    url = cfg["base_url"].rstrip("/") + "/chat/completions"
    body = {
        "model": cfg["model"],
        "messages": messages,
        "temperature": 0.1,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + cfg["api_key"]})
    try:
        with _opener().open(req, timeout=timeout) as r:
            resp = json.loads(r.read().decode("utf-8"))
        return resp["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"[llm] 调用失败：{e}", flush=True)
        return None


def chat_json(messages, timeout=60):
    """调 LLM 并解析 JSON 返回；失败/解析错返回 None。"""
    txt = chat(messages, json_mode=True, timeout=timeout)
    if not txt:
        return None
    try:
        # 兼容 ```json 包裹
        txt = txt.strip()
        if txt.startswith("```"):
            txt = txt.split("```", 2)[1] if txt.count("```") >= 2 else txt.strip("`")
            if txt.startswith("json"):
                txt = txt[4:]
        return json.loads(txt)
    except Exception as e:
        print(f"[llm] JSON 解析失败：{e}；原文：{txt[:200]}", flush=True)
        return None
