#!/usr/bin/env python3
"""投递前确定性校验（Deterministic pre-delivery gate）。

两层之一：本脚本做确定性校验，另一层是独立 Agent 复核（见 SKILL 第 6 步）。
图片部分直接复用 tools/check_resume_images.py 的检测，避免两套标准漂移。

用法：
    python3 tools/validate_resume.py            # 项目根任意解释器均可（缺 PIL 会自动自举）
退出码：0=全部通过；1=有硬伤；2=没有可校验的产物。
"""
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _pyboot import ensure_pillow  # noqa: E402

ensure_pillow()
from check_resume_images import check_image, check_content  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 项目根（自适应）
HTML_DIR = os.path.join(ROOT, "data", "resumes", "html")
IMG_DIR = os.path.join(ROOT, "data", "resumes", "img")
OUT = os.path.join(ROOT, "data", "raw", "validation.json")


def load_companies():
    """优先读 tailor.json；没有就按已生成的 HTML 文件名退化，保证门禁永远可跑。"""
    for p in (os.path.join(ROOT, "data", "tailor.json"),
              os.path.join(ROOT, "data", "raw", "tailor.json")):
        if os.path.exists(p):
            try:
                items = json.load(open(p, encoding="utf-8"))["items"]
                if items:
                    return [it["company"] for it in items], p
            except Exception:
                pass
    companies = []
    for h in sorted(glob.glob(os.path.join(HTML_DIR, "*.html"))):
        parts = os.path.basename(h)[:-5].split("-")
        if len(parts) >= 2:
            companies.append(parts[1])
    return companies, None


def check_one(company, html_path, png_path):
    res = {"company": company, "html": html_path, "png": png_path, "checks": {}, "errors": [], "warnings": []}

    if not os.path.exists(png_path):
        res["errors"].append("image_exists: missing png %s" % png_path)
        res["checks"]["image_exists"] = {"ok": False, "detail": "missing png"}
        res["passed"] = False
        return res

    img = check_image(png_path)
    content = check_content(os.path.basename(png_path))
    res["checks"] = dict(img["checks"], **content["checks"])
    res["errors"] = img["errors"] + content["errors"]
    res["warnings"] = img.get("warnings", []) + content.get("warnings", [])
    for k in ("width", "height", "mode", "bytes", "ink_ratio"):
        if k in img:
            res[k] = img[k]
    res["passed"] = not res["errors"]
    return res


def main():
    companies, src = load_companies()
    if not companies:
        print("没有可校验的简历产物（%s 为空）" % HTML_DIR)
        return 2
    print("校验清单来源：%s（%d 家）" % (src or "HTML 文件名推断", len(companies)))

    report = []
    for company in companies:
        htmls = glob.glob(os.path.join(HTML_DIR, "*%s*.html" % company))
        pngs = glob.glob(os.path.join(IMG_DIR, "*%s*.png" % company))
        if not htmls or not pngs:
            report.append({"company": company, "passed": False,
                           "errors": ["missing html/png artifact"], "checks": {}})
            print("FAIL %s: missing artifacts" % company)
            continue
        r = check_one(company, htmls[0], pngs[0])
        report.append(r)
        print(("PASS " if r["passed"] else "FAIL ") + company +
              (" | " + "; ".join(r["errors"]) if r["errors"] else ""))

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(report, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    passed = sum(1 for r in report if r.get("passed"))
    print("\npassed %d/%d -> %s" % (passed, len(report), OUT))
    return 0 if passed == len(report) else 1


if __name__ == "__main__":
    sys.exit(main())
