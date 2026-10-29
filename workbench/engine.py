#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""岗位技能树聚合与差距分析引擎（零第三方依赖，仅用 Python3 标准库）。

用法（在项目根目录或 workbench 目录执行都可以）：
    python3 workbench/engine.py

输入：
    workbench/lexicon.json     分层技能词库（人工维护）
    workbench/data/profile.json 候选人履历（skills: [{name, category, level, evidence}]）
    workbench/data/jobs.json    岗位池（数组，含 position / skillTags / jd 等字段）

输出：
    workbench/data/skills_tree.json   技能需求树（按领域聚合）
    workbench/data/gap_analysis.json  差距分析与学习方案

匹配口径（可解释、可复现）：
    * 需求度：岗位标题 + skillTags + JD 全文 作为匹配文本，逐个别名做「大小写不敏感」匹配；
      中文（含中英混排）别名直接子串匹配；纯 ASCII 别名加词边界，避免
      “Go” 命中 “Golang”、“Java” 命中 “JavaScript”、“React” 命中 “ReAct” 之类的误匹配。
      一个岗位命中该技能任意一个别名即计 1 次，不重复计数。
    * demand = 命中岗位数 / 岗位总数，保留 3 位小数。
    * 候选人水平：把词库技能的 name + aliases 与 profile.skills 的 name + aliases 逐一比对，
      规范化（小写、去空白）后完全相等，或存在带边界的包含关系（如 “Harness” ⊂ “Agent Harness”）。
    * priority = round(demand * importance * (5 - myLevel) / 5, 2)；
      myLevel < 3（含未掌握，myLevel = 0）才算「有缺口」，非缺口技能 priority 记为 0.0。

岗位洞察的「层级语义匹配」（v1.0 设计）：
    analyze() 之上叠加 jd_match.py（M1-M4）——从 JD 语料解析能力需求向量
    （维度 × 最低层级 L1-L4 × 权重 × must/nice_to_have + 职责动词画像），
    对履历做 L1-L4 层级判定（L1 用会 / L2 负责实现 / L3 主导设计 / L4 治理闭环），
    输出六色差距分型（达标/超配/表述/迁移/学习/结构/硬）+ 加权匹配率 + 四张行动卡。
    gap_analysis.json 顶层新增 engine/requirements/capabilities/dims/matchRate/
    hardGaps/cards 字段；gaps/strengths/summary/recommendations 改为维度级口径。
    jd_match 直接消费 analyze() 打好的 _mentions/_coverage/_myScore 等中间字段，
    增量基线自动继承（岗位池或履历无变化时不重算）。
"""

import datetime
import json
import math
import os
import sys
import re
import hashlib

# ---------------------------------------------------------------- 路径定位
WORKBENCH_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(WORKBENCH_DIR)
DATA_DIR = os.path.join(ROOT_DIR, "data")   # ★ 用户数据目录

LEXICON_PATH = os.path.join(WORKBENCH_DIR, "lexicon.json")
PROFILE_PATH = os.path.join(DATA_DIR, "profile.json")
JOBS_PATH = os.path.join(DATA_DIR, "jobs.json")

TREE_PATH = os.path.join(DATA_DIR, "skills_tree.json")
GAP_PATH = os.path.join(DATA_DIR, "gap_analysis.json")
BASE_PATH = os.path.join(DATA_DIR, "raw", "analyze_baseline.json")   # 增量分析基线（履历/岗位指纹 + 上次技能结果）
IGNORE_PATH = os.path.join(DATA_DIR, "insight_ignore.json")          # 用户校准：按目标忽略的需求维度名列表

def _load_ignored_dims(target_id):
    """读取按目标持久化的「忽略维度」列表；无目标 id 时用 global 键，均缺省为空列表。"""
    try:
        with open(IGNORE_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return []
    targets = data.get("targets") or {}
    key = target_id or "global"
    return list(targets.get(key) or targets.get("global") or [])

GAP_LEVEL_THRESHOLD = 3   # 兼容旧口径
GAP_SCORE_THRESHOLD = 60  # 证据分 < 60（低于「生产级」）视为有缺口
TOP_GAPS = 15
TOP_STRENGTHS = 10
MAX_SAMPLES = 3
MAX_RELATED_JOBS = 5
MAX_RECOMMENDATIONS = 5


# ---------------------------------------------------------------- 基础工具
def log(msg):
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


def load_json(path, default=None, required=True):
    """容错读取 JSON：文件缺失或损坏时给出明确提示（required=False 时返回 default）。"""
    if not os.path.exists(path):
        if required:
            log("[错误] 找不到文件：%s" % path)
            sys.exit(1)
        return default
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (ValueError, OSError) as exc:
        if required:
            log("[错误] 解析失败：%s（%s）" % (path, exc))
            sys.exit(1)
        log("[警告] 忽略无法解析的文件：%s（%s）" % (path, exc))
        return default


def as_text(value):
    """把任意字段安全地转成字符串（None / 数字 / 列表都能处理）。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        return " ".join(as_text(v) for v in value)
    if isinstance(value, dict):
        return " ".join(as_text(v) for v in value.values())
    return str(value)


def is_pure_ascii(text):
    return all(ord(ch) < 128 for ch in text)


_ALIAS_PATTERN_CACHE = {}


def _ascii_pattern(alias):
    """纯 ASCII 别名的词边界正则：允许英文复数（agent → agents / llms）。"""
    pattern = _ALIAS_PATTERN_CACHE.get(alias)
    if pattern is None:
        pattern = re.compile(
            r"(?<![a-z0-9])" + re.escape(alias) + r"(?:s|es)?(?![a-z0-9])"
        )
        _ALIAS_PATTERN_CACHE[alias] = pattern
    return pattern


def text_hit(alias, haystack_lower):
    """判断别名是否命中已小写的匹配文本。"""
    needle = alias.strip().lower()
    if len(needle) < 2:
        return False
    if is_pure_ascii(needle):
        return _ascii_pattern(needle).search(haystack_lower) is not None
    # 中文/中英混排：直接子串匹配
    return needle in haystack_lower


_NORM_STRIP_RE = re.compile(r"[\s\u3000]+")


def normalize_label(text):
    """技能标签规范化：小写 + 去掉空白，便于「多 Agent 编排」与「多Agent编排」对齐。"""
    return _NORM_STRIP_RE.sub("", as_text(text).lower())


def bounded_in(needle, haystack):
    """needle 是否以「带边界」的方式出现在 haystack 中（两者均已规范化）。"""
    if not needle or not haystack:
        return False
    if is_pure_ascii(needle):
        return _ascii_pattern(needle).search(haystack) is not None
    return needle in haystack


def label_match(left, right):
    """两个技能标签是否指同一个技能（完全相等，或带边界的包含关系）。"""
    a, b = normalize_label(left), normalize_label(right)
    if not a or not b:
        return False
    if a == b:
        return True
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    if len(short) < 2:
        return False
    return bounded_in(short, long_)


# ---------------------------------------------------------------- 输入装载
def build_job_corpus(jobs):
    """把岗位池转成匹配语料，缺失字段一律容错。"""
    corpus = []
    for job in jobs:
        if not isinstance(job, dict):
            continue
        tags = job.get("skillTags") or []
        if isinstance(tags, str):
            tags = [tags]
        tags = [as_text(t) for t in tags if as_text(t).strip()]
        haystack = " ".join(
            [as_text(job.get("position")), " ".join(tags), as_text(job.get("jd"))]
        ).lower()
        corpus.append(
            {
                "job": job,
                "position": as_text(job.get("position")).strip(),
                "company": as_text(job.get("company")).strip(),
                "tags": tags,
                "jd": as_text(job.get("jd")),
                "haystack": haystack,
            }
        )
    return corpus


try:                       # 与 Web 端共用的客观评分模型
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import scoring
except Exception:          # pragma: no cover
    scoring = None


def build_profile_index(profile):
    """把 profile.skills 转成可匹配的标签集合。"""
    entries = []
    skills = (profile or {}).get("skills") or []
    if not isinstance(skills, list):
        skills = []
    for item in skills:
        if not isinstance(item, dict):
            continue
        labels = [item.get("name")]
        extra = item.get("aliases")
        if isinstance(extra, str):
            # 字符串别名可能含多种分隔符（逗号/顿号/分号/换行），自动拆分
            labels.extend([x for x in re.split(r"[，,、;；\n\r]+", extra) if x.strip()])
        elif isinstance(extra, list):
            labels.extend(extra)
        labels = [as_text(x).strip() for x in labels if as_text(x).strip()]
        # 新模型：由 evidence/depth/artifacts/lastUsed 计算客观分；旧 level 仅作兼容
        if scoring is not None and ("evidenceLevel" in item or "projectRefs" in item):
            sc = scoring.evidence_score(item)
            score, tier, breakdown = sc["score"], sc["tier"], sc["breakdown"]
            facts = sc["facts"]
        else:
            try:
                lv = int(item.get("level") or 0)
            except (TypeError, ValueError):
                lv = 0
            score = max(0, min(5, lv)) * 20
            tier, breakdown, facts = "（旧口径 level×20）", {}, {}
        entries.append(
            {
                "name": as_text(item.get("name")).strip(),
                "labels": labels,
                "score": int(score),
                "tier": tier,
                "breakdown": breakdown,
                "facts": facts,
                "level": max(0, min(5, round(score / 20.0))),
            }
        )
    return entries


def match_profile(lexicon_skill, profile_entries):
    """返回 (inProfile, myScore0-100, myTier, matchedNames, matchedEntries)。"""
    candidates = [lexicon_skill.get("name")] + list(lexicon_skill.get("aliases") or [])
    candidates = [c for c in candidates if isinstance(c, str) and c.strip()]
    best, matched, matched_entries = 0, [], []
    for entry in profile_entries:
        hit = any(label_match(c, p) for c in candidates for p in entry["labels"])
        if hit:
            matched.append(entry["name"])
            matched_entries.append(entry)
            best = max(best, entry.get("score") or 0)
    tier = ""
    if matched_entries:
        top = max(matched_entries, key=lambda e: e.get("score") or 0)
        tier = top.get("tier") or ""
    return (bool(matched), best, tier, matched, matched_entries)


# ---------------------------------------------------------------- 增量基线（履历 diff → 只重算受影响技能）
def profile_skill_fp(item):
    """技能指纹：任何影响匹配或证据打分的字段变化都会触发该技能重算。"""
    data = {
        "name": item.get("name"),
        "aliases": item.get("aliases"),
        "group": item.get("group"),
        "cluster": item.get("cluster"),
        "level": item.get("level"),
        "evidenceLevel": item.get("evidenceLevel"),
        "projectRefs": item.get("projectRefs"),
        "metrics": item.get("metrics"),
        "statement": item.get("statement"),
        "note": item.get("note"),
        "skillEnvironment": item.get("skillEnvironment"),
    }
    return hashlib.md5(json.dumps(data, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def profile_fingerprint(profile):
    out = {}
    for s in (profile or {}).get("skills") or []:
        if isinstance(s, dict) and s.get("name"):
            out[str(s["name"]).strip()] = profile_skill_fp(s)
    return out


def profile_text_fp(profile):
    """履历文本指纹：skills 之外的经历/项目/教育等文本变化（如新增 RAG 项目经历）也会触发重算。"""
    body = {k: v for k, v in (profile or {}).items() if k != "skills"}
    return hashlib.md5(json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def jobs_fingerprint(jobs):
    """岗位池指纹：jd/技能标签/归属目标任一变化即触发覆盖率全量重算。"""
    h = hashlib.md5()
    for j in sorted(jobs, key=lambda x: str(x.get("id") or x.get("url") or x.get("position") or "")):
        h.update(str(j.get("id") or "").encode("utf-8", "ignore"))
        h.update(str(j.get("jd") or "").encode("utf-8", "ignore"))
        h.update("|".join(j.get("skillTags") or []).encode("utf-8", "ignore"))
        h.update(str(j.get("targetIds") or j.get("targetId") or "").encode("utf-8", "ignore"))
    return h.hexdigest()


# ---------------------------------------------------------------- 统计计算
def analyze(lexicon, profile, jobs, baseline=None, jobs_changed=True, changed_names=None, profile_changed_all=False):
    corpus = build_job_corpus(jobs)
    total = len(corpus)
    with_jd = sum(1 for c in corpus if c["jd"].strip())
    with_tags = sum(1 for c in corpus if c["tags"])
    # 覆盖率口径：只在「有技能标签或完整 JD」的岗位里算，避免被只有标题的岗位稀释
    documented = sum(1 for c in corpus if (c.get("jd") or "").strip() or c.get("tags"))
    profile_entries = build_profile_index(profile)
    changed = set(changed_names or [])
    base_skills = (baseline or {}).get("skills") or {}

    for domain in lexicon.get("domains") or []:
        skills = domain.get("skills") or []
        for skill in skills:
            name = (skill.get("name") or "").strip()
            base = base_skills.get(name)
            # 命中该词库技能的 profile 技能名（增量按匹配关系判定，而非名字相等——
            # profile 技能名可能与词库名不同，如 profile「RAG」匹配词库「RAG 全流程」）
            candidates = [skill.get("name")] + list(skill.get("aliases") or [])
            candidates = [c for c in candidates if isinstance(c, str) and c.strip()]
            hit_profile_names = [e["name"] for e in profile_entries
                                 if any(label_match(c, p) for c in candidates for p in e["labels"])]
            skill_changed = bool(profile_changed_all) or any(n in changed for n in hit_profile_names)
            cover_reuse = base is not None and not jobs_changed
            my_reuse = base is not None and not skill_changed
            if cover_reuse:
                # 岗位侧沿用：覆盖率 / 需求度 / 岗位样本 / 命中岗位标签全部复用上次结果
                for k in ("_mentions", "_demand", "_coverage", "_coverageTier", "_coverageTierDesc", "_samples", "_hitLabels"):
                    skill[k] = base[k]
            else:
                aliases = [a for a in (skill.get("aliases") or []) if isinstance(a, str) and a.strip()]
                hits = []
                for item in corpus:
                    if any(text_hit(alias, item["haystack"]) for alias in aliases):
                        hits.append(item)
                mentions = len(hits)
                demand = round(mentions / total, 3) if total else 0.0
                coverage = round(mentions / documented, 3) if documented else 0.0
                cov = scoring.coverage_tier(coverage) if scoring else {"tier": "", "tierDesc": ""}
                samples, seen_positions = [], set()
                for item in hits:
                    title = item["position"] or item["company"] or "（无标题）"
                    if title in seen_positions:
                        continue
                    seen_positions.add(title)
                    samples.append(title)
                    if len(samples) >= MAX_SAMPLES:
                        break
                skill["_mentions"] = mentions
                skill["_demand"] = demand
                skill["_coverage"] = coverage
                skill["_coverageTier"] = cov.get("tier", "")
                skill["_coverageTierDesc"] = cov.get("tierDesc", "")
                skill["_samples"] = samples
                skill["_hitLabels"] = [job_label(item) for item in hits]

            if my_reuse:
                # 履历侧沿用：证据分 / 命中技能 / 缺口判定全部复用上次结果（该技能未变）
                for k in ("_myScore", "_myTier", "_evidenceCount", "_inProfile", "_myLevel", "_matchedProfile"):
                    skill[k] = base[k]
            else:
                in_profile, my_score, my_tier, matched_names, matched_entries = match_profile(skill, profile_entries)
                my_level = max(0, min(5, round(my_score / 20.0)))          # 兼容字段
                evidence_count = (matched_entries[0].get("facts", {}) or {}).get("evidenceCount", 0) if matched_entries else 0
                skill["_myScore"] = int(my_score)
                skill["_myTier"] = my_tier
                skill["_evidenceCount"] = evidence_count
                skill["_inProfile"] = in_profile
                skill["_myLevel"] = my_level
                skill["_matchedProfile"] = matched_names

            # 派生字段（缺口/优先级）：由最终 coverage 与 myScore 现算，保证口径一致
            skill["_domain"] = domain.get("name") or "未分类"
            skill["_isGap"] = skill["_myScore"] < GAP_SCORE_THRESHOLD
            skill["_gap"] = round(max(0.0, (GAP_SCORE_THRESHOLD - skill["_myScore"]) / float(GAP_SCORE_THRESHOLD)), 2) if skill["_isGap"] else 0.0
            skill["_priority"] = scoring.gap_priority(skill["_coverage"], skill["_myScore"]) if scoring else 0.0

    return corpus, total, with_jd, with_tags, documented


def build_tree(lexicon, corpus, total, with_jd, with_tags, generated_at, documented=0):
    domains_out = []
    for domain in lexicon.get("domains") or []:
        skills = list(domain.get("skills") or [])
        skills.sort(key=lambda s: (-s["_coverage"], -s["_mentions"], s.get("name") or ""))
        items = []
        for skill in skills:
            items.append(
                {
                    "name": skill.get("name"),
                    "category": skill["_domain"],
                    "aliases": list(skill.get("aliases") or []),
                    "mentions": skill["_mentions"],
                    "coverage": skill["_coverage"],
                    "coverageTier": skill["_coverageTier"],
                    "coverageTierDesc": skill["_coverageTierDesc"],
                    "demand": skill["_demand"],
                    "inProfile": skill["_inProfile"],
                    "myScore": skill["_myScore"],
                    "myTier": skill["_myTier"],
                    "evidenceCount": skill["_evidenceCount"],
                    "gap": skill["_gap"],
                    "priority": skill["_priority"],
                    "samples": skill["_samples"],
                }
            )
        domain_demand = round(max([i["coverage"] for i in items]), 3) if items else 0.0
        domains_out.append(
            {
                "name": domain.get("name"),
                "demand": domain_demand,
                "skillCount": len(items),
                "gapCount": sum(1 for i in items if i.get("myScore", 0) < GAP_SCORE_THRESHOLD),
                "skills": items,
            }
        )
    domains_out.sort(key=lambda d: (-d["demand"], d["name"] or ""))
    return {
        "generatedAt": generated_at,
        "families": list(lexicon.get("families") or []),
        "corpus": {"jobs": total, "withJd": with_jd, "withTags": with_tags, "documented": documented},
        "domains": domains_out,
    }


def job_label(item):
    company = (item["company"] or "").strip()
    position = (item["position"] or "").strip()
    if company and position:
        return "%s-%s" % (company, position)
    return position or company or "（未知岗位）"


def hot_threshold(all_skills):
    """动态「热门线」：需求度是相对指标，绝对阈值会随语料稀释程度失效，故取最大值的一半（下限 0.10）。"""
    max_demand = max([s["_coverage"] for s in all_skills] or [0.0])
    return max(0.10, round(max_demand * 0.5, 3))


def build_gap_analysis(lexicon, corpus, total, generated_at):
    documented = sum(1 for c in corpus if c["jd"].strip() or c["tags"])
    all_skills = []
    for domain in lexicon.get("domains") or []:
        for skill in domain.get("skills") or []:
            all_skills.append(skill)

    gaps = [s for s in all_skills if s["_isGap"]]
    gaps.sort(key=lambda s: (-s["_priority"], -s["_coverage"], s.get("name") or ""))
    top_gaps = gaps[:TOP_GAPS]

    def plan_of(skill):
        learn = skill.get("learn") or {}
        return {
            "why": as_text(learn.get("why")),
            "focus": as_text(learn.get("focus")),
            "steps": list(learn.get("steps") or []),
            "resources": list(learn.get("resources") or []),
            "duration": as_text(learn.get("duration")),
            "verification": as_text(learn.get("verification")),
        }

    gaps_out = []
    n = len(top_gaps)
    step = max(1, math.ceil(n / 3))
    for idx, skill in enumerate(top_gaps):
        # 优先级三等分（展示口径）：前 1/3 = L1 必须处理 / 中 1/3 = L2 最好处理 / 后 1/3 = L3 可处理可不处理
        level = min(3, idx // step + 1)
        plan = plan_of(skill)
        related, seen = [], set()
        for label in skill["_hitLabels"]:
            if label in seen:
                continue
            seen.add(label)
            related.append(label)
            if len(related) >= MAX_RELATED_JOBS:
                break
        gaps_out.append(
            {
                "skill": skill.get("name"),
                "domain": skill["_domain"],
                "demand": skill["_demand"],
                "mentions": skill["_mentions"],
                "coverage": skill["_coverage"],
                "coverageTier": skill["_coverageTier"],
                "myScore": skill["_myScore"],
                "myTier": skill["_myTier"],
                "gap": skill["_gap"],
                "priority": skill["_priority"],
                "priorityLevel": level,
                "why": plan["why"],
                "plan": {
                    "focus": plan["focus"],
                    "steps": plan["steps"],
                    "resources": plan["resources"],
                    "duration": plan["duration"],
                    "verification": plan["verification"],
                },
                "relatedJobs": related,
                "samples": skill["_samples"],
            }
        )

    strengths_pool = [s for s in all_skills if s["_myScore"] >= GAP_SCORE_THRESHOLD]
    strengths_pool.sort(key=lambda s: (-s["_coverage"], -s["_myScore"], s.get("name") or ""))
    hot = hot_threshold(all_skills)
    strengths = []
    for skill in strengths_pool[:TOP_STRENGTHS]:
        if skill["_myScore"] >= 60 and skill["_coverage"] >= hot:
            note = "证据分 %d（%s）且覆盖率 %d%%（热门线以上）：简历主打项，建议把支撑它的项目数据写进首屏。" % (
                skill["_myScore"], skill["_myTier"] or "-", round(skill["_coverage"] * 100),
            )
        elif skill["_coverage"] >= hot:
            note = "覆盖率 %d%% 高于热门线（%d%%），但证据分只有 %d：补一个可验证产出的落地案例即可显著加分。" % (
                round(skill["_coverage"] * 100), round(hot * 100), skill["_myScore"],
            )
        elif skill["_myScore"] >= 60:
            note = "证据分 %d 但覆盖率 %d%% 低于热门线：属于稀缺深度能力，作差异化亮点而非主打项。" % (
                skill["_myScore"], round(skill["_coverage"] * 100),
            )
        else:
            note = "覆盖率 %d%%、证据分 %d：属岗位基础项，保持即可，学习时间留给更高优先级缺口。" % (
                round(skill["_coverage"] * 100), skill["_myScore"],
            )
        strengths.append(
            {
                "skill": skill.get("name"),
                "domain": skill["_domain"],
                "myScore": skill["_myScore"],
                "myTier": skill["_myTier"],
                "coverage": skill["_coverage"],
                "inProfile": True,
                "note": note,
            }
        )

    summary = build_summary(total, documented, all_skills, gaps, top_gaps, strengths, hot)
    recommendations = build_recommendations(all_skills, gaps, top_gaps, strengths, total, hot)

    return {
        "generatedAt": generated_at,
        "families": list(lexicon.get("families") or []),
        "corpus": {"jobs": total},
        "summary": summary,
        "gaps": gaps_out,
        "strengths": strengths,
        "recommendations": recommendations,
    }


def top_domain_names(skills, limit=3):
    order, seen = [], set()
    for skill in skills:
        name = skill["_domain"]
        if name in seen:
            continue
        seen.add(name)
        order.append(name)
        if len(order) >= limit:
            break
    return order


def build_summary(total, documented, all_skills, gaps, top_gaps, strengths, hot):
    if not all_skills:
        return "词库为空，无法生成差距分析。"
    total_skills = len(all_skills)
    gap_count = len(gaps)
    hot_skills = [s for s in all_skills if s["_demand"] >= hot]
    missing_hot = [s for s in all_skills if s["_myScore"] == 0 and s["_coverage"] >= hot]
    missing_hot.sort(key=lambda s: (-s["_priority"], -s["_demand"], s.get("name") or ""))
    sentences = []
    sentences.append(
        "本次共分析 %d 个岗位（其中 %d 个带官方技能标签或完整 JD，需求度以全部岗位数为分母计算），"
        "覆盖 %d 个技能点：%d 个已具备、%d 个存在缺口，其中 %d 个技能需求度 ≥ %.2f（热门线，取最高需求度的一半）。"
        % (total, documented, total_skills, total_skills - gap_count, gap_count, len(hot_skills), hot)
    )
    if top_gaps:
        focus = "、".join(
            "%s（需求度 %.3f，优先级 %.2f）" % (s.get("name"), s["_demand"], s["_priority"])
            for s in top_gaps[:3]
        )
        sentences.append(
            "最大缺口集中在「%s」方向，按优先级排在最前的是 %s。"
            % ("、".join(top_domain_names(top_gaps)), focus)
        )
    if missing_hot:
        names = [s.get("name") for s in missing_hot]
        if len(names) == 1:
            listed = names[0]
        elif len(names) == 2:
            listed = "、".join(names)
        else:
            listed = "%s 等 %d 项" % ("、".join(names[:3]), len(names))
        sentences.append(
            "其中 %s 属于「岗位常要但履历中完全没有」的空白项，建议作为下一阶段学习与简历补强的第一优先级。"
            % listed
        )
    elif strengths:
        sentences.append(
            "整体技能结构与岗位需求匹配度较高，重点是把 %s 等已有优势转成可验证、可量化的成果。"
            % "、".join(s["skill"] for s in strengths[:3])
        )
    return "".join(sentences)


def build_recommendations(all_skills, gaps, top_gaps, strengths, total, hot):
    recs = []
    if top_gaps:
        def at(i):
            return (top_gaps[i].get("name"), top_gaps[i]["_priority"]) if len(top_gaps) > i else ("-", 0.0)
        one, two, three = at(0), at(1), at(2)
        recs.append(
            "按优先级顺序补齐缺口：#1 %s（优先级 %.2f）→ #2 %s（%.2f）→ #3 %s（%.2f）；"
            "建议先做出 #1 的可验证产出再启动下一项，避免并行学习但都拿不出证据。"
            % (one[0], one[1], two[0], two[1], three[0], three[1])
        )
    strengths_high = [s for s in strengths if s.get("demand", 0) >= hot][:3]
    if strengths_high:
        recs.append(
            "把已有优势写成简历主打证据：%s 需求度在热门线以上且自身已有基础，"
            "每项补一个「业务场景 + 量化结果」的案例（如「成本下降 30%%」「成功率提升 15 个百分点」），比罗列技能名更有效。"
            % "、".join(s["skill"] for s in strengths_high)
        )
    missing = [s for s in top_gaps if s["_myScore"] == 0][:4]
    if missing:
        recs.append(
            "优先消除「零基础」项：%s。这些技能在多份 JD 中直接出现，"
            "先用 1-2 周做到能讲清原理并跑通最小 demo，再决定是否投入深入。"
            % "、".join(s.get("name") for s in missing)
        )
    domain_counter = {}
    for skill in all_skills:
        if skill["_isGap"] and skill["_demand"] >= hot:
            domain_counter[skill["_domain"]] = domain_counter.get(skill["_domain"], 0) + 1
    if domain_counter:
        ranked = sorted(domain_counter.items(), key=lambda kv: (-kv[1], kv[0]))[:2]
        recs.append(
            "下一批投递优先选择「%s」方向：这些方向的高需求缺口项最集中，补齐后的边际收益最大；"
            "投递前按 skills_tree.json 中每个技能的 aliases 与 samples 逐条对齐简历措辞。"
            % "、".join(name for name, _ in ranked)
        )
    recs.append(
        "为每个补齐项建立可验证产出（开源仓库 / 评测报告 / 设计文档 / trace 截图），"
        "补齐后重新运行 engine.py，用 gap 与 priority 的变化核对进展，用数据驱动下一轮学习排期。"
    )
    return recs[:MAX_RECOMMENDATIONS]


# ---------------------------------------------------------------- 输出
def write_json(path, payload):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    os.replace(tmp, path)


def main():
    lexicon = load_json(LEXICON_PATH, required=True)
    if not isinstance(lexicon, dict) or not lexicon.get("domains"):
        log("[错误] lexicon.json 结构异常：缺少 domains 数组")
        sys.exit(1)
    profile = load_json(PROFILE_PATH, default={}, required=False) or {}
    if not isinstance(profile, dict):
        log("[警告] profile.json 不是对象，按空履历处理")
        profile = {}
    jobs = load_json(JOBS_PATH, default=[], required=False)
    if isinstance(jobs, dict):
        jobs = jobs.get("jobs") or jobs.get("list") or []
    if not isinstance(jobs, list):
        log("[警告] jobs.json 不是数组，按空岗位池处理")
        jobs = []

    generated_at = datetime.datetime.now().replace(microsecond=0).isoformat()

    # 目标岗位口径：profile.targets[] + activeTarget → 作为简历标题与展示口径（技能分析始终按全词库）
    # 支持 --target <id> 覆盖 activeTarget（岗位洞察面板按目标切换重算，不改动全局选中）
    override_id = None
    if "--target" in sys.argv:
        try:
            override_id = sys.argv[sys.argv.index("--target") + 1]
        except IndexError:
            log("[警告] --target 缺少 id 参数，忽略")
    target = None
    targets = profile.get("targets") or []
    active_id = override_id or profile.get("activeTarget") or (targets[0].get("id") if targets else None)
    for t in targets:
        if t.get("id") == active_id:
            target = t
            break

    # 洞察口径：技能分析按「当前目标的岗位池」（targetIds 归属）过滤——
    # 切换洞察目标会重算出不同的技能匹配/缺口，而不是只改落盘元信息
    all_jobs_n = len(jobs)
    target_id = (target or {}).get("id")
    if target_id:
        jobs = [j for j in jobs
                if target_id in (j.get("targetIds") or []) or j.get("targetId") == target_id]
        log("洞察口径按目标过滤：%d / %d（全池）" % (len(jobs), all_jobs_n))
        if not jobs:
            log("[提示] 目标「%s」暂无岗位池，本次按空池分析（先到搜岗页从 BOSS 拉取）"
                % ((target or {}).get("title") or target_id))

    # ------------------------------------------------------------ 增量判定（履历 diff → 只重算受影响技能）
    t0 = datetime.datetime.now()
    force_full = "--full" in sys.argv
    prev = load_json(BASE_PATH, default=None, required=False) or None
    cur_profile_fp = profile_fingerprint(profile)
    cur_text_fp = profile_text_fp(profile)
    cur_jobs_fp = jobs_fingerprint(jobs)
    prev_target = (prev or {}).get("target") or {}
    target_same = bool(prev) and prev_target.get("id") == (target or {}).get("id")
    jobs_changed = not prev or cur_jobs_fp != (prev or {}).get("jobsFp")
    text_changed = prev is not None and cur_text_fp != (prev or {}).get("profileTextFp")
    if force_full or not target_same:
        baseline, changed_names = None, None
        added, removed, changed, kept = [], [], [], 0
        mode = "full"
    else:
        prev_fp = (prev or {}).get("profileFp") or {}
        added = [n for n in cur_profile_fp if n not in prev_fp]
        removed = [n for n in prev_fp if n not in cur_profile_fp]
        changed = [n for n in cur_profile_fp if n in prev_fp and prev_fp[n] != cur_profile_fp[n]]
        changed_names = set(added) | set(changed)
        kept = len(cur_profile_fp) - len(changed_names)
        if not added and not removed and not changed and not jobs_changed and not text_changed:
            log("[增量] 履历与岗位池均无变化（技能 %d 个），复用上次分析结果，未重算。" % len(cur_profile_fp))
            mode = "noop"
            baseline, changed_names = prev, None
        else:
            mode = "partial"
            baseline = prev
            if text_changed and not changed_names:
                log("[增量] 履历文本有变化（技能条目未变，项目/经历文本变更），按全词库重算履历侧匹配；岗位池%s。"
                    % ("有变化" if jobs_changed else "未变化"))
            else:
                log("[增量] 履历 diff：新增技能 %d、修改 %d、删除 %d、未变沿用 %d；岗位池%s；%s。仅重算 %d 个受影响技能。"
                    % (len(added), len(changed), len(removed), kept, "有变化" if jobs_changed else "未变化",
                       "履历文本有变化" if text_changed else "履历文本未变化", len(changed_names)))

    corpus, total, with_jd, with_tags, documented = analyze(lexicon, profile, jobs, baseline=baseline,
                                                            jobs_changed=jobs_changed, changed_names=changed_names,
                                                            profile_changed_all=text_changed)
    tree = build_tree(lexicon, corpus, total, with_jd, with_tags, generated_at, documented)
    gap_report = build_gap_analysis(lexicon, corpus, total, generated_at)
    meta = {"id": target.get("id") if target else None,
            "title": (target.get("title") or "").strip() or None}
    tree["target"] = meta
    gap_report["target"] = meta

    # 层级语义匹配（M1-M4）：消费 analyze 中间字段，覆盖为维度级口径；失败则保留旧口径
    try:
        import jd_match
        jd_report = jd_match.build_report(lexicon, profile, corpus, total, documented, target=meta,
                                          ignore_dims=_load_ignored_dims(meta.get("id")))
        if jd_report:
            for k in ("engine", "position", "requirements", "capabilities",
                      "dims", "ignoredDims", "matchRate", "hardGaps", "cards",
                      "gaps", "strengths", "summary", "recommendations"):
                gap_report[k] = jd_report[k]
            log("[jd_match] 层级语义匹配完成：%d 个需求维度，硬差距 %d，匹配率 %d%%（证据质量 %d%%）"
                % (len(jd_report["dims"]), len(jd_report["hardGaps"]),
                   jd_report["matchRate"]["overall"], jd_report["matchRate"]["evidenceQuality"]))
        else:
            log("[警告] jd_match 未产出需求维度（岗位池 JD 为空？），保留旧口径差距报告")
    except Exception as exc:  # pragma: no cover
        log("[警告] jd_match 层级匹配失败（%s），保留旧口径差距报告" % exc)

    # 落盘增量基线：存每个技能的「可沿用字段」子集，供下次 diff 复用
    base_skills = {}
    for domain in lexicon.get("domains") or []:
        for skill in domain.get("skills") or []:
            base_skills[skill.get("name") or ""] = {
                "_mentions": skill["_mentions"],
                "_demand": skill["_demand"],
                "_coverage": skill["_coverage"],
                "_coverageTier": skill["_coverageTier"],
                "_coverageTierDesc": skill["_coverageTierDesc"],
                "_samples": skill["_samples"],
                "_hitLabels": skill["_hitLabels"],
                "_myScore": skill["_myScore"],
                "_myTier": skill["_myTier"],
                "_evidenceCount": skill["_evidenceCount"],
                "_inProfile": skill["_inProfile"],
                "_myLevel": skill["_myLevel"],
                "_matchedProfile": skill["_matchedProfile"],
            }
    delta = {
        "mode": mode,
        "added": added, "changed": changed, "removed": removed, "kept": kept,
        "jobsChanged": bool(jobs_changed), "textChanged": bool(text_changed),
        "elapsedMs": int((datetime.datetime.now() - t0).total_seconds() * 1000),
    }
    tree["delta"] = delta
    write_json(BASE_PATH, {"target": meta, "profileFp": cur_profile_fp, "profileTextFp": cur_text_fp,
                           "jobsFp": cur_jobs_fp, "skills": base_skills})
    log("[delta] mode=%s added=%d changed=%d removed=%d kept=%d jobs=%s text=%s elapsedMs=%d"
        % (mode, len(added), len(changed), len(removed), kept, "changed" if jobs_changed else "same",
           "changed" if text_changed else "same", delta["elapsedMs"]))

    write_json(TREE_PATH, tree)
    write_json(GAP_PATH, gap_report)

    all_skills = [s for d in lexicon.get("domains") or [] for s in (d.get("skills") or [])]
    gaps = [s for s in all_skills if s["_isGap"]]
    gaps.sort(key=lambda s: (-s["_priority"], -s["_demand"], s.get("name") or ""))

    log("")
    log("=== 技能树聚合与差距分析 ===")
    log("目标岗位：%s" % ((target or {}).get("title") or "（未设置，按全词库分析）"))
    log("语料：%d 个岗位（含完整 JD %d 个，含官方技能标签 %d 个）" % (total, with_jd, with_tags))
    log("词库：%d 个领域 / %d 个技能点（全量口径）" % (len(lexicon.get("domains") or []), len(all_skills)))
    log("缺口：%d 个技能（证据分 < %d），证据充分：%d 个" % (len(gaps), GAP_SCORE_THRESHOLD, len(all_skills) - len(gaps)))
    log("")
    log("Top5 缺口（按 priority 降序）：")
    for idx, skill in enumerate(gaps[:5], 1):
        log(
            "  %d. %-22s 领域=%-8s 覆盖率=%.0f%%(%s) 我的证据分=%d(%s) 优先级=%.2f"
            % (
                idx,
                skill.get("name"),
                skill["_domain"],
                skill["_coverage"] * 100,
                skill["_coverageTier"],
                skill["_myScore"],
                skill["_myTier"] or "-",
                skill["_priority"],
            )
        )
    log("")
    log("Top5 高需求技能：")
    high = sorted(all_skills, key=lambda s: (-s["_coverage"], -s["_mentions"], s.get("name") or ""))[:5]
    for idx, skill in enumerate(high, 1):
        log(
            "  %d. %-22s 覆盖率=%.0f%% 命中 %d/%d 个岗位 我的证据分=%d"
            % (idx, skill.get("name"), skill["_coverage"] * 100, skill["_mentions"], documented, skill["_myScore"])
        )
    log("")
    log("已写出：%s" % TREE_PATH)
    log("已写出：%s" % GAP_PATH)


if __name__ == "__main__":
    main()
