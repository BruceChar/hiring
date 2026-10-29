#!/usr/bin/env python3
"""简历图片检测门禁（Resume image gate）。

对 data/resumes/img/*.png 做确定性检测，任何一项硬检查不过就不允许投递。
只依赖 Pillow，输入输出都在项目根内，可脱离浏览器单独运行——因此可挂进每日自动流程。

用法：
    <python-with-PIL> tools/check_resume_images.py            # 检测全部
    <python-with-PIL> tools/check_resume_images.py --json     # 只输出 JSON

退出码：0=全部通过；1=有硬伤；2=没有可检测的图片。
"""
import argparse
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _pyboot import ensure_pillow  # noqa: E402

ensure_pillow()
from PIL import Image  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMG_DIR = os.path.join(ROOT, "data", "resumes", "img")
HTML_DIR = os.path.join(ROOT, "data", "resumes", "html")
PDF_DIR = os.path.join(ROOT, "data", "resumes", "pdf")
OUT = os.path.join(ROOT, "data", "raw", "image_check.json")

MIN_WIDTH = 2000          # A4@260dpi ≈ 2152，低于 2000 发出去会糊
MIN_BYTES = 300_000       # 网盘/聊天压缩前的体积下限
A4_RATIO = 210 / 297      # 0.7071
RATIO_TOL = 0.01
MIN_INK = 0.01            # 低于此值视为空白页
MAX_INK = 0.75            # 高于此值视为整页涂黑/渲染错误（实测正常简历约 0.19）
WHITE = (255, 255, 255)

REQUIRED_SECTIONS = ["教育经历", "个人简介", "核心能力", "核心项目经历", "工作经历"]
REQUIRED_FACTS = ["蔡长霖", "18896777749", "BruceChar@163.com", "中国科学技术大学", "Agent"]
FORBIDDEN_TITLE_WORDS = ["全栈", "大模型应用开发专家", "网联", "支付业务智能体"]


def check_image(path):
    """图片层硬检查。"""
    name = os.path.basename(path)
    res = {"file": name, "checks": {}, "errors": [], "warnings": []}

    def chk(key, ok, detail=""):
        res["checks"][key] = {"ok": bool(ok), "detail": detail}
        if not ok:
            res["errors"].append("%s: %s" % (key, detail))

    try:
        im = Image.open(path)
        im.load()
    except Exception as e:  # 损坏的 PNG
        chk("readable", False, "open failed: %s" % e)
        res["passed"] = False
        return res
    chk("readable", True)

    w, h = im.size
    chk("image_opaque", im.mode == "RGB", "mode=%s（必须 RGB，不能带 alpha）" % im.mode)
    chk("image_width", w >= MIN_WIDTH, "%dx%d（宽必须 ≥%d）" % (w, h, MIN_WIDTH))
    ratio = (w / h) if h else 0
    chk("a4_aspect", abs(ratio - A4_RATIO) <= RATIO_TOL,
        "w/h=%.4f（A4 应为 %.4f±%.4f，非 A4 会被裁切/拉伸）" % (ratio, A4_RATIO, RATIO_TOL))
    size = os.path.getsize(path)
    chk("image_filesize", size > MIN_BYTES, "%dKB（需 >%dKB）" % (size // 1024, MIN_BYTES // 1024))

    rgb = im.convert("RGB")
    corners = [rgb.getpixel(p) for p in [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]]
    chk("white_background", all(c == WHITE for c in corners),
        "四角=%s（必须纯白：非白说明背景透明或贴了底图，深色聊天背景上会发灰）" % (corners,))

    thumb = rgb.resize((215, 304))
    raw = thumb.tobytes()  # RGB，每 3 字节一个像素
    n = len(raw) // 3
    ink = sum(1 for i in range(n) if raw[3 * i] < 245 or raw[3 * i + 1] < 245 or raw[3 * i + 2] < 245) / float(n)
    res["ink_ratio"] = round(ink, 4)
    chk("not_blank", ink >= MIN_INK, "墨迹占比 %.4f（<%.2f 视为空白页，渲染失败）" % (ink, MIN_INK))
    chk("not_oversaturated", ink <= MAX_INK, "墨迹占比 %.4f（>%.2f 视为整页涂黑）" % (ink, MAX_INK))

    res["width"] = w
    res["height"] = h
    res["mode"] = im.mode
    res["bytes"] = size
    res["passed"] = not res["errors"]
    return res


def check_content(name):
    """图片对应的 HTML 内容检查（标题统一 / 板块齐全 / 关键事实 / 无占位符）。"""
    stem = os.path.splitext(name)[0]
    htmls = glob.glob(os.path.join(HTML_DIR, "*%s*.html" % stem)) or         [p for p in glob.glob(os.path.join(HTML_DIR, "*.html")) if stem.split("-")[1] in p]
    res = {"file": name, "checks": {}, "errors": [], "warnings": []}

    def chk(key, ok, detail=""):
        res["checks"][key] = {"ok": bool(ok), "detail": detail}
        if not ok:
            res["errors"].append("%s: %s" % (key, detail))

    if not htmls:
        res["warnings"].append("找不到同名 HTML，跳过内容检查")
        res["passed"] = True
        return res
    html = open(htmls[0], encoding="utf-8").read()
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)
    chk("title_unified", "求职意向：Agent系统工程师" in text, "标题必须统一为「求职意向：Agent系统工程师」")
    if "求职意向：" in text:
        tail = text.split("求职意向：", 1)[1][:30]
        for bad in FORBIDDEN_TITLE_WORDS:
            if bad in tail:
                chk("title_clean_%s" % bad, False, "JD 专属措辞「%s」混进标题" % bad)
    for s in REQUIRED_SECTIONS:
        chk("section_%s" % s, s in text, "缺板块「%s」" % s)
    for f in REQUIRED_FACTS:
        chk("fact_%s" % f, f in text, "缺关键事实「%s」" % f)
    chk("no_placeholder", not re.search(r"(TODO|XXX|待填|占位|\{\{)", html), "存在占位符文本")
    res["passed"] = not res["errors"]
    return res


PREVIEW_RE = re.compile(r"(预览|preview|草稿|draft|tmp|temp|截图)", re.I)


def deliverable_images():
    """只挑「真要发出去」的简历图。

    以 data/tailor.json 的条目为准（蔡长霖-<公司>-Agent系统工程师.png）。
    否则 data/resumes/img/ 里用户自己生成的预览图/截图会被当成交付物误判。
    没有 tailor.json 时退化为全目录扫描，但仍排除预览类文件名。
    """
    tailor = None
    for p in (os.path.join(ROOT, "data", "tailor.json"),
              os.path.join(ROOT, "data", "raw", "tailor.json")):
        if os.path.exists(p):
            try:
                tailor = json.load(open(p, encoding="utf-8")).get("items") or []
                break
            except Exception:
                pass
    if tailor:
        picked = []
        for it in tailor:
            c = it.get("company")
            if not c:
                continue
            p = os.path.join(IMG_DIR, "蔡长霖-%s-Agent系统工程师.png" % c)
            if os.path.exists(p):
                picked.append(p)
        if picked:
            return sorted(set(picked)), "tailor"
    allp = [p for p in glob.glob(os.path.join(IMG_DIR, "*.png"))
            if not os.path.basename(p).startswith("_")
            and not PREVIEW_RE.search(os.path.basename(p))]
    return sorted(allp), "glob"


def skipped_previews():
    return sorted(os.path.basename(p) for p in glob.glob(os.path.join(IMG_DIR, "*.png"))
                  if PREVIEW_RE.search(os.path.basename(p)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="只输出 JSON")
    args = ap.parse_args()

    pngs, src = deliverable_images()
    if not pngs:
        print("没有找到待检测的简历图片：%s" % IMG_DIR)
        return 2

    report = []
    for p in pngs:
        r = check_image(p)
        c = check_content(os.path.basename(p))
        r["content"] = c
        r["errors"].extend(c["errors"])
        r["warnings"].extend(c["warnings"])
        r["passed"] = r["passed"] and c["passed"]
        report.append(r)

    summary = {
        "checkedAt": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
        "source": src,
        "skippedPreviews": skipped_previews(),
        "total": len(report),
        "passed": sum(1 for r in report if r["passed"]),
        "failed": sum(1 for r in report if not r["passed"]),
        "items": report,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(summary, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=1))
    else:
        for r in report:
            flag = "PASS" if r["passed"] else "FAIL"
            extra = ""
            if r["passed"]:
                extra = " %dx%d %s %dKB ink=%.3f" % (r.get("width", 0), r.get("height", 0),
                                                     r.get("mode", "?"), r.get("bytes", 0) // 1024,
                                                     r.get("ink_ratio", 0))
            print("%s %s%s" % (flag, r["file"], extra))
            for e in r["errors"]:
                print("      ✗ " + e)
            for wn in r["warnings"]:
                print("      ! " + wn)
        if summary["skippedPreviews"]:
            print("\n（已跳过 %d 张预览/截图，不属交付物：%s）"
                  % (len(summary["skippedPreviews"]), "、".join(summary["skippedPreviews"])))
        print("\n通过 %d/%d（范围=%s），报告：%s"
              % (summary["passed"], summary["total"], summary["source"], OUT))

    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
