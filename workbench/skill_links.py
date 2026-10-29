#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""技能账实相符（交叉验证）断链检测 —— resume_engine 的差异化模块。

核对「技能区」与「项目经历 / 工作经历」是否构成双向佐证闭环，输出断链条目与修复建议。
**只做检测与建议，绝不修改 data/profile.json。**

四条形式化规则
--------------
R1 存在性：每条技能必须有非空 ``projectRefs``，或属于 ``skillEnvironment`` 聚合行。
           违反处理顺序：补证据 → 降格表述（自学+demo）→ 删除。
R2 一致性：``projectRefs`` 指向的项目 / 经历，其文本（项目 name+stack+highlights，
           经历 company+role+highlights）里必须出现该技能关键词或其词库别名。
           另：引用名在 projects[].name / experiences[].company 中找不到 → ``ref_not_found``
           （严重，并入 R2）。违反处理顺序同 R1。
R3 完备性：项目 / 经历中出现、且在岗位池 JD / 技能标签里被至少 2 个岗位要求的技术词，
           应出现在技能区；否则报“缺失条目”，处理方式是补充条目。
R4 真实性：无法自动判定。实现语义 = 某条技能既无落点、又无法在**任何**项目 / 经历文本中
           找到任何别名痕迹 → 判 R4（critical，强制删除，无降级路径）。

关键词匹配（R2 / R3 / 词库扫描共用一套）
----------------------------------------
* 词表 = 技能名本身 + 技能名拆分出的关键词 + 该技能在词库里命中的条目的全部别名；
* 大小写不敏感（统一小写后比较），空白不敏感（``多 Agent`` ≡ ``多Agent``）；
* 含中文（非纯 ASCII）的词做**子串匹配**；
* 纯 ASCII 的词加**词边界**：``(?<![A-Za-z0-9_+#])term(?![A-Za-z0-9_+#])``，
  避免 ``Go`` 命中 ``Golang``、``Java`` 命中 ``JavaScript``、``JSON`` 被 ``JS`` 命中；
* 额外一条内部大小写守卫：避免 ``React`` 命中 ``ReAct``（匹配文本是混排大小写、
  且词本身没有内部大写字母时判为假朋友；``REACT`` / ``react`` 仍接受）。

容错
----
* 只用标准库；``python3 workbench/skill_links.py`` 在项目根或 workbench 目录都能跑
  （路径基于 ``__file__`` 绝对定位）。
* ``skills`` / ``projects`` / ``experiences`` 缺失或为 null、``projectRefs`` 不是数组、
  ``evidenceLevel`` 非数字、输入文件缺失或 JSON 损坏 —— 均不报错，降级为空数据继续出报告。
* 除 ``generatedAt`` 外结果稳定（全部输出前做确定性排序）。
"""

from __future__ import annotations

import datetime
import difflib
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

# --------------------------------------------------------------------------------------
# 路径（绝对定位：从项目根或 workbench 目录执行都一致）
# --------------------------------------------------------------------------------------

WORKBENCH_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = WORKBENCH_DIR.parent
OUTPUT_NAME = "skill_links.json"

# --------------------------------------------------------------------------------------
# 可调参数
# --------------------------------------------------------------------------------------

R3_MIN_JOB_DEMAND = 2          # R3：至少被 N 个岗位要求才算“目标岗位相关技术词”
ENV_ROW_COUNTS_AS_R3_COVERAGE = True   # 「日常工作环境」聚合行视为技能区的一部分（R1 亦豁免落点）
EVIDENCE_TERM_LIMIT = 4        # 每条证据串最多列几个命中关键词

SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2}
RULE_RANK = {"R4": 0, "R2": 1, "R1": 2, "R3": 3}

# 缺失条目的 cluster 提示（词库领域 → 与 profile 现有 cluster 词汇对齐）
ENTRY_CLUSTER_HINTS = {
    "容器化与镜像工程": "云与 DevOps",
    "Kubernetes 与云原生": "云与 DevOps",
    "网关与流量治理": "云与 DevOps",
    "CI/CD 与工程化": "云与 DevOps",
    "Serverless 与弹性伸缩": "云与 DevOps",
    "可观测性建设": "云与 DevOps",
    "缓存设计": "中间件",
    "消息队列与异步处理": "中间件",
    "关系型数据库与数据建模": "数据库",
    "SQL 与数据分析": "数据库",
    "Python": "语言",
    "TypeScript / JavaScript": "语言",
    "Java": "语言",
    "Go": "语言",
    "C/C++ 与系统编程": "语言",
    "Agent 开发框架（LangChain/LlamaIndex）": "框架",
    "PyTorch 与深度学习框架": "框架",
    "Spring 生态": "框架",
    "Web 服务框架（FastAPI/Flask/Django）": "框架",
    "分布式系统设计": "系统设计",
    "微服务架构": "系统设计",
    "系统架构设计": "系统设计",
    "高并发与性能优化": "性能工程",
}
DOMAIN_DEFAULT_CLUSTER = {
    "Agent 与编排": "系统设计",
    "大模型与算法": "算法与模型",
    "后端与分布式": "系统设计",
    "语言与框架": "框架",
    "数据与评测": "数据与评测",
    "治理与安全": "治理与安全",
    "业务领域": "业务领域",
    "通用能力": "通用能力",
}
DOMAIN_GROUP_HINT = {
    "Agent 与编排": "professional",
    "大模型与算法": "professional",
    "后端与分布式": "tools",
    "语言与框架": "tools",
    "数据与评测": "professional",
    "治理与安全": "professional",
    "业务领域": "soft",
    "通用能力": "soft",
}

AGENT_INSTRUCTION = (
    "对每条 broken：先按 suggestion 补证据；补不上则降格表述为「自学+demo」，仍不行才删除。"
    "R4 条目一律删除。"
)


# --------------------------------------------------------------------------------------
# 基础工具：文本容错 / 归一化 / 关键词匹配
# --------------------------------------------------------------------------------------

_FULLWIDTH_MAP = {
    "／": "/", "（": "(", "）": ")", "：": ":", "，": ",",
    "－": "-", "～": "~", "　": " ", "\u00a0": " ",
}
_SEGMENT_SPLIT_RE = re.compile(r"[与和及、,，/／|｜;；:：()（）\[\]【】{}<>《》]+")
_ASCII_RE_CACHE: Dict[str, "re.Pattern[str]"] = {}


def _text(value: Any) -> str:
    """把任意值安全地转成去首尾空白的字符串（None / 复杂类型 → ''）。"""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, bool):
        return ""
    if isinstance(value, (int, float)):
        return str(value)
    return ""


def _as_list(value: Any) -> List[Any]:
    """list/tuple → list；dict → values；None / 其它 → []（容错用）。"""
    if isinstance(value, (list, tuple)):
        return list(value)
    if isinstance(value, dict):
        return list(value.values())
    return []


def _obj_list(value: Any) -> List[Dict[str, Any]]:
    """只保留 dict 元素（skills / projects / experiences 容错）。"""
    return [x for x in _as_list(value) if isinstance(x, dict)]


_ARROW_VARIANTS = ("→", "⇒", "➔", "➜", "⟶", "->", "=>", "-->")


def norm(value: Any) -> str:
    """归一化：全角转半角、去空白、转小写、箭头统一为「到」。

    箭头统一是必要的：「0→1」与「0到1」在简历里是同一种表述，若不归一化，
    账实相符检测会把已在技能区声明过的词误报为 R3 缺失。
    """
    s = _text(value)
    if not s:
        return ""
    for full, half in _FULLWIDTH_MAP.items():
        s = s.replace(full, half)
    for arrow in _ARROW_VARIANTS:
        s = s.replace(arrow, "到")
    s = re.sub(r"\s+", "", s)
    return s.lower()


def is_ascii_term(term: str) -> bool:
    try:
        return term.isascii()
    except AttributeError:  # pragma: no cover - Python < 3.7
        return all(ord(ch) < 128 for ch in term)


def _internal_case_conflict(term: str, matched: str) -> bool:
    """假朋友守卫：``React`` 不应命中 ``ReAct``（但应命中 ``react`` / ``REACT``）。"""
    if matched == term:
        return False
    if matched.isupper():
        return False
    if any(ch.isupper() for ch in term[1:]):
        return False
    return any(ch.isupper() for ch in matched[1:])


def _ascii_term_in_text(term: str, text: str) -> bool:
    """纯 ASCII 词：词边界 + 大小写不敏感。"""
    pattern = _ASCII_RE_CACHE.get(term)
    if pattern is None:
        pattern = re.compile(
            r"(?<![A-Za-z0-9_+#])" + re.escape(term) + r"(?![A-Za-z0-9_+#])",
            re.IGNORECASE,
        )
        _ASCII_RE_CACHE[term] = pattern
    for match in pattern.finditer(text):
        if _internal_case_conflict(term, match.group(0)):
            continue
        return True
    return False


def term_in_text(term: Any, text: Any) -> bool:
    """判断一个技术词是否出现在文本里（ASCII 走词边界，中文走归一化子串）。"""
    t = _text(term)
    if not t:
        return False
    body = text if isinstance(text, str) else _text(text)
    if not body:
        return False
    if is_ascii_term(t):
        return _ascii_term_in_text(t, body)
    return norm(t) in norm(body)


def matched_terms(terms: Sequence[str], text: str) -> List[str]:
    """返回文本中命中的词（按具体度排序：长词优先，再字典序，保证稳定）。"""
    hits = [t for t in terms if term_in_text(t, text)]
    return sorted(set(hits), key=lambda x: (-len(x), x))


def join_text(*parts: Any) -> str:
    """把若干字段（字符串或字符串列表）拼成一段可扫描文本。"""
    chunks: List[str] = []
    for part in parts:
        if isinstance(part, str):
            if part.strip():
                chunks.append(part)
        elif isinstance(part, (list, tuple)):
            chunks.extend(_text(x) for x in part if _text(x))
    return " \n ".join(chunks)


def load_json(path: Path, default: Any, warnings: Optional[List[str]] = None) -> Any:
    """宽容读 JSON：文件缺失 / 编码异常 / 解析失败 → 返回默认值，不抛异常。"""
    try:
        if not path.is_file():
            if warnings is not None:
                warnings.append("缺少文件 %s（按空数据继续）" % path)
            return default
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception as exc:  # noqa: BLE001 - 检测器必须容错
        if warnings is not None:
            warnings.append("读取 %s 失败：%s（按空数据继续）" % (path, exc))
        return default


# --------------------------------------------------------------------------------------
# 输入装载
# --------------------------------------------------------------------------------------

def resolve_data_dir(base: Optional[Path] = None) -> Path:
    """定位 data/ ：优先 <code>/../data，其次当前工作目录，最后 workbench/data。"""
    candidates = []
    if base is not None:
        candidates.append(Path(base))
    candidates.append(PROJECT_ROOT / "data")
    candidates.append(Path.cwd() / "data")
    candidates.append(WORKBENCH_DIR / "data")
    for cand in candidates:
        if cand.is_dir():
            return cand
    return PROJECT_ROOT / "data"


def load_inputs(data_dir: Optional[Path] = None,
                lexicon_path: Optional[Path] = None) -> Tuple[Dict[str, Any], Any, Any, List[str]]:
    """读取 profile / jobs / lexicon，返回 (profile, jobs, lexicon, warnings)。"""
    warnings: List[str] = []
    ddir = resolve_data_dir(data_dir)
    profile = load_json(ddir / "profile.json", {}, warnings)
    jobs = load_json(ddir / "jobs.json", [], warnings)
    lex = load_json(lexicon_path or (WORKBENCH_DIR / "lexicon.json"), {}, warnings)
    if not isinstance(profile, dict):
        warnings.append("profile.json 顶层不是对象（按空数据继续）")
        profile = {}
    return profile, jobs, lex, warnings


def parse_lexicon(lexicon: Any) -> List[Dict[str, Any]]:
    """把 lexicon.json 展开成条目列表：[{name, aliases, domain}, ...]（保持文件顺序）。"""
    entries: List[Dict[str, Any]] = []
    domains = lexicon.get("domains") if isinstance(lexicon, dict) else None
    for dom in _obj_list(domains):
        domain_name = _text(dom.get("name"))
        for ent in _obj_list(dom.get("skills")):
            name = _text(ent.get("name"))
            if not name:
                continue
            aliases = [_text(a) for a in _as_list(ent.get("aliases")) if _text(a)]
            entries.append({"name": name, "aliases": aliases, "domain": domain_name})
    return entries


def resolve_entry(skill_name: str,
                  entries: Sequence[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """技能名 → 词库条目：先整体精确（名称 / 别名），再退化为“互为子串”且取最长命中。"""
    n = norm(skill_name)
    if not n:
        return None
    for ent in entries:
        if norm(ent["name"]) == n:
            return ent
    for ent in entries:
        for alias in ent["aliases"]:
            if norm(alias) == n:
                return ent
    best: Optional[Dict[str, Any]] = None
    best_len = 0
    for ent in entries:
        for alias in [ent["name"]] + list(ent["aliases"]):
            na = norm(alias)
            if len(na) < 2:
                continue
            if na in n or (len(n) >= 2 and n in na):
                if len(na) > best_len:
                    best, best_len = ent, len(na)
    return best


def skill_terms(skill: Dict[str, Any], entries: Sequence[Dict[str, Any]]) -> List[str]:
    """一条技能的关键词表：技能名 + 名称拆分关键词 + 词库命中条目的名称与全部别名。"""
    name = _text(skill.get("name"))
    terms: List[str] = []
    if not name:
        return terms
    terms.append(name)
    for seg in _SEGMENT_SPLIT_RE.split(name):
        seg = seg.strip()
        if len(seg) >= 2:
            terms.append(seg)
    entry = resolve_entry(name, entries)
    if entry is not None:
        terms.append(entry["name"])
        terms.extend(entry["aliases"])
    ordered: List[str] = []
    seen: Set[str] = set()
    for term in terms:
        key = norm(term)
        if not key or key in seen:
            continue
        seen.add(key)
        ordered.append(term)
    return ordered


# --------------------------------------------------------------------------------------
# 简历侧实体（项目 / 经历）与落点文本
# --------------------------------------------------------------------------------------

def project_text(project: Dict[str, Any]) -> str:
    """项目文本 = name + stack + highlights。"""
    return join_text(project.get("name"), project.get("stack"), project.get("highlights"))


def experience_text(experience: Dict[str, Any]) -> str:
    """经历文本 = company + role + highlights。"""
    return join_text(experience.get("company"), experience.get("role"),
                     experience.get("highlights"))


def build_ref_index(projects: Sequence[Dict[str, Any]],
                    experiences: Sequence[Dict[str, Any]]) -> Dict[str, Tuple[str, Dict[str, Any]]]:
    """落点索引：归一化名称 → (kind, 实体)。项目名与公司名同级。"""
    index: Dict[str, Tuple[str, Dict[str, Any]]] = {}
    for proj in projects:
        key = norm(proj.get("name"))
        if key and key not in index:
            index[key] = ("project", proj)
    for exp in experiences:
        key = norm(exp.get("company"))
        if key and key not in index:
            index[key] = ("experience", exp)
    return index


def refs_of(skill: Dict[str, Any]) -> List[str]:
    """projectRefs 容错解析：list / str / dict 都能处理，非法值返回 []。"""
    raw = skill.get("projectRefs")
    if isinstance(raw, list):
        out: List[str] = []
        for item in raw:
            if isinstance(item, str):
                if item.strip():
                    out.append(item.strip())
            elif isinstance(item, dict):
                nm = _text(item.get("name"))
                if nm:
                    out.append(nm)
        return out
    if isinstance(raw, str):
        return [raw.strip()] if raw.strip() else []
    if isinstance(raw, dict):
        nm = _text(raw.get("name"))
        return [nm] if nm else []
    return []


def resolve_ref(ref: str,
                index: Dict[str, Tuple[str, Dict[str, Any]]]) -> Optional[Tuple[str, Dict[str, Any]]]:
    hit = index.get(norm(ref))
    if hit is not None:
        return hit
    for key, value in index.items():
        if key and (key in norm(ref) or norm(ref) in key):
            return value
    return None


def scan_traces(terms: Sequence[str], projects: Sequence[Dict[str, Any]],
                experiences: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """在整个项目 / 经历语料里找该技能的关键词痕迹（供 R1/R4 判断与证据定位）。"""
    traces: List[Dict[str, Any]] = []
    for proj in projects:
        hits = matched_terms(terms, project_text(proj))
        if hits:
            traces.append({"kind": "project", "name": _text(proj.get("name")) or "(未命名项目)",
                           "terms": hits})
    for exp in experiences:
        hits = matched_terms(terms, experience_text(exp))
        if hits:
            traces.append({"kind": "experience", "name": _text(exp.get("company")) or "(未命名经历)",
                           "terms": hits})
    return traces


def evidence_line(trace: Dict[str, Any]) -> str:
    label = "项目" if trace["kind"] == "project" else "经历"
    shown = "」「".join(trace["terms"][:EVIDENCE_TERM_LIMIT])
    return "在%s《%s》中出现过关键词「%s」" % (label, trace["name"], shown)


def describe_term_list(terms: Sequence[str], limit: int = 5) -> str:
    return " / ".join(terms[:limit])


# --------------------------------------------------------------------------------------
# R3：技能区文本 + 岗位池需求
# --------------------------------------------------------------------------------------

SKILL_AREA_FIELDS = ("name", "cluster", "statement", "note", "scenario", "metrics", "artifacts")


def skill_area_text(skills: Sequence[Dict[str, Any]], environment_row: str) -> str:
    """技能区全文：技能条目各字段 + 「日常工作环境」聚合行。"""
    chunks: List[str] = []
    for skill in skills:
        for field in SKILL_AREA_FIELDS:
            chunks.append(join_text(skill.get(field)))
    if ENV_ROW_COUNTS_AS_R3_COVERAGE and environment_row:
        chunks.append(environment_row)
    return " \n ".join(c for c in chunks if c)


def job_text(job: Dict[str, Any]) -> str:
    return join_text(job.get("jd"), job.get("skillTags"), job.get("position"))


def cluster_for_entry(entry: Dict[str, Any], skills: Sequence[Dict[str, Any]],
                      entries: Sequence[Dict[str, Any]]) -> str:
    """缺失条目的 cluster：优先沿用已有技能簇 → 词库条目的显式提示 → 领域默认。"""
    for skill in skills:
        if resolve_entry(_text(skill.get("name")), entries) is entry:
            cluster = _text(skill.get("cluster"))
            if cluster:
                return cluster
    hint = ENTRY_CLUSTER_HINTS.get(entry["name"])
    if hint:
        return hint
    return DOMAIN_DEFAULT_CLUSTER.get(entry["domain"], entry["domain"] or "未分类")


def variant_note(term: str, area_text: str,
                 skills: Sequence[Dict[str, Any]]) -> str:
    """同一含义的变体写法提示（如 0到1 ↔ 0→1），避免把“写法不同”误报成缺失。"""
    if "到" not in term:
        return ""
    variant = term.replace("到", "→")
    if not term_in_text(variant, area_text):
        return ""
    where: List[str] = []
    for skill in skills:
        blob = join_text(*[skill.get(f) for f in SKILL_AREA_FIELDS])
        if term_in_text(variant, blob):
            where.append(_text(skill.get("name")))
    owner = "、".join([w for w in where if w][:3]) or "技能区"
    return "（技能区已有变体写法「%s」，出现在 %s；若认可该声明可忽略本项）" % (variant, owner)


def compute_missing(entries: Sequence[Dict[str, Any]], skills: Sequence[Dict[str, Any]],
                    projects: Sequence[Dict[str, Any]], experiences: Sequence[Dict[str, Any]],
                    jobs: Sequence[Dict[str, Any]], environment_row: str) -> List[Dict[str, Any]]:
    """R3：词库别名扫描项目/经历 → 岗位需求 ≥2 → 技能区未覆盖 → 缺失条目。"""
    area = skill_area_text(skills, environment_row)
    corpus: List[Tuple[str, str, str]] = []
    for proj in projects:
        corpus.append(("project", _text(proj.get("name")) or "(未命名项目)", project_text(proj)))
    for exp in experiences:
        corpus.append(("experience", _text(exp.get("company")) or "(未命名经历)",
                       experience_text(exp)))
    jtexts = [job_text(job) for job in _obj_list(jobs)]
    jtexts = [t for t in jtexts if t]

    missing: List[Dict[str, Any]] = []
    for entry in entries:
        terms: List[str] = [entry["name"]] + list(entry["aliases"])
        terms = [t for t in terms if _text(t)]
        # 1) 该条目是否已在技能区出现（任一名称 / 别名形式即可）
        if any(term_in_text(t, area) for t in terms):
            continue
        # 2) 词库别名扫描项目 / 经历，找出真实出现的词形与出处
        hit_terms: List[str] = []
        appears: List[str] = []
        for kind, name, text in corpus:
            hits = matched_terms(terms, text)
            if not hits:
                continue
            hit_terms.extend(hits)
            if name not in appears:
                appears.append(name)
        if not hit_terms:
            continue
        # 3) 岗位需求：JD / 技能标签里至少 R3_MIN_JOB_DEMAND 个岗位要求
        demand: Dict[str, int] = {}
        for term in hit_terms:
            demand[term] = sum(1 for jt in jtexts if term_in_text(term, jt))
        # 取需求最高的词形作为上报 term（同分保持词库顺序，结果稳定）
        best_term = entry["name"] if entry["name"] in demand else hit_terms[0]
        best_demand = demand.get(best_term, 0)
        for term in hit_terms:
            if demand[term] > best_demand:
                best_term, best_demand = term, demand[term]
        if best_demand < R3_MIN_JOB_DEMAND:
            continue
        cluster = cluster_for_entry(entry, skills, entries)
        group = DOMAIN_GROUP_HINT.get(entry["domain"], "professional")
        suggestion = (
            "在技能区补一条 %s 条目（对齐词库「%s」），并用真实项目 bullet 支撑；"
            "或用「日常工作环境」聚合行声明" % (group, entry["name"])
        )
        note = variant_note(best_term, area, skills)
        missing.append({
            "term": best_term,
            "rule": "R3",
            "severity": "medium",
            "cluster": cluster,
            "demandJobs": best_demand,
            "appearsIn": appears,
            "suggestion": suggestion + note,
        })

    missing.sort(key=lambda item: (-item["demandJobs"], item["term"]))
    return missing


# --------------------------------------------------------------------------------------
# 主检测：R1 / R2 / R4 + 断链建议
# --------------------------------------------------------------------------------------

def _suggestion_for_r1(skill_name: str, traces: Sequence[Dict[str, Any]]) -> Dict[str, str]:
    if traces:
        first = traces[0]
        label = "项目" if first["kind"] == "project" else "经历"
        term = first["terms"][0] if first["terms"] else skill_name
        return {
            "action": "补证据",
            "detail": "把它挂到《%s》上（%s），并在该项目 bullet 里补一句含「%s」的描述；"
                      "补不上则降格表述为「自学 + demo」，仍不行再删除。" % (first["name"], label, term),
        }
    return {
        "action": "补证据",
        "detail": "现有项目与经历文本中查不到该技能的痕迹：先在相关项目 bullet 里补上真实证据；"
                  "补不上则降格表述为「自学 + demo」，仍不行再删除。",
    }


def _suggestion_for_ref_not_found(refs: Sequence[str],
                                  index: Dict[str, Tuple[str, Dict[str, Any]]]) -> Dict[str, str]:
    candidates = difflib.get_close_matches(norm(refs[0]), list(index.keys()), n=3, cutoff=0.4)
    pretty: List[str] = []
    for cand in candidates:
        kind, obj = index[cand]
        pretty.append(_text(obj.get("name") if kind == "project" else obj.get("company")))
    hint = ("；现有落点里最接近的是《%s》" % "》《".join([p for p in pretty if p])) if pretty else ""
    return {
        "action": "修正引用",
        "detail": "projectRefs 里的「%s」在 projects[].name / experiences[].company 中都不存在，"
                  "属于引用不存在的项目%s。改成真实存在的项目名或公司名后重跑检测；"
                  "确实无落点则按 R1 顺序降级（补证据 → 降格为「自学 + demo」→ 删除）。"
                  % ("」「".join(refs), hint),
    }


def _suggestion_for_r2(skill_name: str, ref_names: Sequence[str], terms: Sequence[str],
                       traces: Sequence[Dict[str, Any]] = ()) -> Dict[str, str]:
    ref_label = "》《".join(ref_names[:2])
    outside = [t for t in traces if t["name"] not in set(ref_names)]
    if outside:
        first = outside[0]
        label = "项目" if first["kind"] == "project" else "经历"
        term = first["terms"][0] if first["terms"] else skill_name
        return {
            "action": "补证据",
            "detail": "引用的《%s》文本里没有该技能关键词，但它其实出现在%s《%s》（关键词「%s」）："
                      "把《%s》加进 projectRefs 即可对上账；或直接在《%s》的 stack / bullet 里"
                      "补一句含「%s」或其别名（%s）的真实描述。补不上则降格表述为「自学 + demo」，"
                      "仍不行再删除。"
                      % (ref_label, label, first["name"], term, first["name"], ref_label,
                         skill_name, describe_term_list(terms)),
        }
    return {
        "action": "补证据",
        "detail": "在《%s》的 stack 或 bullet 里补一句含「%s」或其别名（%s）的真实描述；"
                  "补不上则降格表述为「自学 + demo」，仍不行再删除。"
                  % (ref_label, skill_name, describe_term_list(terms)),
    }


def _suggestion_for_r4() -> Dict[str, str]:
    return {
        "action": "强制删除",
        "detail": "R4 真实性：既没有 projectRefs 落点，全部项目 / 经历文本里也查不到该技能或"
                  "其别名的任何痕迹，无法用真实经历支撑，无降级路径，直接从技能区删除。",
    }


def detect(profile: Dict[str, Any], jobs: Any, lexicon: Any,
           generated_at: Optional[str] = None) -> Dict[str, Any]:
    """执行 R1-R4 检测，返回 data/skill_links.json 的结构化结果。"""
    if not isinstance(profile, dict):
        profile = {}
    skills = _obj_list(profile.get("skills"))
    projects = _obj_list(profile.get("projects"))
    experiences = _obj_list(profile.get("experiences"))
    environment_row = _text(profile.get("skillEnvironment"))
    entries = parse_lexicon(lexicon)
    index = build_ref_index(projects, experiences)
    job_list = _obj_list(jobs)

    broken: List[Dict[str, Any]] = []
    order: List[Dict[str, str]] = []   # 与 broken 同步的排序键
    r1_pass = r1_fail = 0
    r2_pass = r2_fail = 0
    r4_pass = r4_fail = 0
    credential_count = 0

    for position, skill in enumerate(skills):
        name = _text(skill.get("name")) or "(未命名技能)"
        group = _text(skill.get("group"))
        cluster = _text(skill.get("cluster"))
        if group == "credentials":
            credential_count += 1

        terms = skill_terms(skill, entries)
        if not terms:
            terms = [name]
        refs = refs_of(skill)
        env_only = bool(environment_row) and any(term_in_text(t, environment_row) for t in terms)
        traces = scan_traces(terms, projects, experiences)

        # ---- R1 存在性 ----
        has_landing = bool(refs) or env_only
        if has_landing:
            r1_pass += 1
        else:
            r1_fail += 1

        # ---- R4 真实性（无落点 + 全语料无痕迹 → critical）----
        r4_broken = (not has_landing) and (not traces)

        entry: Optional[Dict[str, Any]] = None

        if not has_landing:
            if r4_broken:
                r4_fail += 1
                entry = {
                    "skill": name, "group": group, "cluster": cluster,
                    "rule": "R4", "severity": "critical", "reason": "no_evidence_anywhere",
                    "issue": "技能区无落点（projectRefs 为空且不在「日常工作环境」聚合行内），"
                             "全部项目 / 经历文本里也找不到该技能或其别名的任何痕迹，"
                             "无法用真实经历佐证。",
                    "evidenceInProjects": [],
                    "suggestion": _suggestion_for_r4(),
                }
            else:
                entry = {
                    "skill": name, "group": group, "cluster": cluster,
                    "rule": "R1", "severity": "high", "reason": "no_project_refs",
                    "issue": "projectRefs 为空且未归入「日常工作环境」聚合行，"
                             "但有 %d 处项目 / 经历文本出现过该技能关键词，可补证据挂靠。" % len(traces),
                    "evidenceInProjects": [evidence_line(t) for t in traces],
                    "suggestion": _suggestion_for_r1(name, traces),
                }
        else:
            # ---- R2 一致性（只对通过 R1 的技能判定）----
            if refs:
                missing_refs = [r for r in refs if resolve_ref(r, index) is None]
                ref_hits: List[Dict[str, Any]] = []
                for ref in refs:
                    resolved = resolve_ref(ref, index)
                    if resolved is None:
                        continue
                    kind, obj = resolved
                    text = project_text(obj) if kind == "project" else experience_text(obj)
                    hits = matched_terms(terms, text)
                    if hits:
                        ref_hits.append({"kind": kind, "name": ref, "terms": hits})
                if missing_refs:
                    r2_fail += 1
                    evidence = [evidence_line(t) for t in traces]
                    entry = {
                        "skill": name, "group": group, "cluster": cluster,
                        "rule": "R2", "severity": "critical", "reason": "ref_not_found",
                        "issue": "projectRefs 引用了不存在的项目 / 经历：「%s」；"
                                 "其余引用中%s出现该技能关键词。"
                                 % ("」「".join(missing_refs),
                                    "有" if ref_hits else "也没有"),
                        "evidenceInProjects": evidence,
                        "suggestion": _suggestion_for_ref_not_found(missing_refs, index),
                    }
                elif not ref_hits:
                    r2_fail += 1
                    ref_names = list(refs)
                    entry = {
                        "skill": name, "group": group, "cluster": cluster,
                        "rule": "R2", "severity": "high", "reason": "no_evidence_in_refs",
                        "issue": "projectRefs 指向的 %d 个落点文本里都没有出现「%s」或其别名"
                                 "（关键词表：%s），属于账实不符。"
                                 % (len(refs), name, describe_term_list(terms)),
                        "evidenceInProjects": [evidence_line(t) for t in traces],
                        "suggestion": _suggestion_for_r2(name, ref_names, terms, traces),
                    }
                else:
                    r2_pass += 1
            else:
                # 仅靠「日常工作环境」聚合行豁免 R1，R2 无引用可校验 → 记通过
                r2_pass += 1

        if not r4_broken:
            r4_pass += 1

        if entry is not None:
            broken.append(entry)
            order.append({
                "severity": entry["severity"],
                "rule": entry["rule"],
                "position": position,
            })

    # 断链排序：严重度 → 规则优先级 → 履历中的原始顺序（确定性）
    decorated = sorted(
        zip(broken, order),
        key=lambda pair: (SEVERITY_RANK.get(pair[1]["severity"], 9),
                          RULE_RANK.get(pair[1]["rule"], 9),
                          pair[1]["position"]),
    )
    broken = [item[0] for item in decorated]

    missing = compute_missing(entries, skills, projects, experiences, job_list, environment_row)

    total = len(skills)
    broken_skills = len({entry["skill"] for entry in broken})
    ok = max(total - broken_skills, 0)
    pass_rate = round(ok / total, 2) if total else 0.0

    if generated_at is None:
        generated_at = datetime.datetime.now().astimezone().isoformat(timespec="seconds")

    return {
        "generatedAt": generated_at,
        "summary": {
            "skills": total,
            "ok": ok,
            "broken": len(broken),
            "missing": len(missing),
            "credentialCount": credential_count,
            "passRate": pass_rate,
        },
        "broken": broken,
        "missing": missing,
        "checks": {
            "R1": {"passed": r1_pass, "failed": r1_fail},
            "R2": {"passed": r2_pass, "failed": r2_fail},
            "R3": {"passed": not missing, "missingCount": len(missing)},
            "R4": {"passed": r4_pass, "failed": r4_fail},
        },
        "environmentRow": environment_row,
        "agentInstruction": AGENT_INSTRUCTION,
    }


# --------------------------------------------------------------------------------------
# 输出
# --------------------------------------------------------------------------------------

def write_result(result: Dict[str, Any], path: Optional[Path] = None) -> Path:
    target = Path(path) if path is not None else (resolve_data_dir() / OUTPUT_NAME)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    return target


def format_summary(result: Dict[str, Any]) -> str:
    summary = result.get("summary", {})
    checks = result.get("checks", {})
    lines = [
        "技能账实相符（交叉验证）断链检测",
        "-" * 46,
        "技能条目：%s 条（credentials %s 条）" % (summary.get("skills", 0),
                                                 summary.get("credentialCount", 0)),
        "断链：%s 条　缺失条目：%s 条　通过率：%.0f%%"
        % (summary.get("broken", 0), summary.get("missing", 0),
           float(summary.get("passRate", 0.0)) * 100),
        "规则：R1 %s/%s　R2 %s/%s　R4 %s/%s　R3 缺失 %s"
        % (checks.get("R1", {}).get("passed", 0), checks.get("R1", {}).get("failed", 0),
           checks.get("R2", {}).get("passed", 0), checks.get("R2", {}).get("failed", 0),
           checks.get("R4", {}).get("passed", 0), checks.get("R4", {}).get("failed", 0),
           checks.get("R3", {}).get("missingCount", 0)),
    ]
    top = result.get("broken", [])[:3]
    lines.append("Top3 待修复：")
    if top:
        for i, item in enumerate(top, 1):
            suggestion = item.get("suggestion", {})
            action = suggestion.get("action", "") if isinstance(suggestion, dict) else str(suggestion)
            lines.append("  %d. [%s/%s] %s → %s：%s"
                         % (i, item.get("rule"), item.get("severity"), item.get("skill"),
                            action, item.get("issue", "")))
    else:
        lines.append("  无（技能区与项目经历账实相符）")
    missing = result.get("missing", [])
    if missing:
        lines.append("R3 缺失条目 Top3：")
        for i, item in enumerate(missing[:3], 1):
            lines.append("  %d. %s（%s 个岗位要求；出现在 %s）"
                         % (i, item.get("term"), item.get("demandJobs"),
                            "、".join(item.get("appearsIn", [])[:3])))
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    out_arg = None
    if "--out" in argv:
        idx = argv.index("--out")
        if idx + 1 < len(argv):
            out_arg = argv[idx + 1]

    profile, jobs, lexicon, warnings = load_inputs()
    result = detect(profile, jobs, lexicon)
    target = write_result(result, Path(out_arg) if out_arg else None)

    for warning in warnings:
        sys.stderr.write("[skill_links][warn] %s\n" % warning)
    print(format_summary(result))
    print("输出：%s" % target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
