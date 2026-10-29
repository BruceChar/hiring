#!/usr/bin/env python3
"""Render resume PDFs to crisp, opaque PNGs (for sending in the BOSS chat).

Uses the bundled LibreOffice kit (pdfium) at real DPI, then flattens alpha onto white
so the image has no transparent background when BOSS displays it.
"""
import glob
import json
import os
import subprocess
import sys

from PIL import Image

NODE = "/Applications/DeepSeek Harness.app/Contents/Resources/runtime/primary-runtime/dependencies/node/bin/node"
CLI = "/Applications/DeepSeek Harness.app/Contents/Resources/app.asar.unpacked/dsh/node_modules/@deepseek-ai/libreoffice-kit/lib/cli.js"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 项目根（自适应，可整体迁移）
DPI = int(sys.argv[1]) if len(sys.argv) > 1 else 260
TMP = os.path.join(ROOT, "data", ".raster_tmp")
os.makedirs(TMP, exist_ok=True)
os.makedirs(os.path.join(ROOT, "data", "resumes", "img"), exist_ok=True)

out = []
for i, pdf in enumerate(sorted(glob.glob(os.path.join(ROOT, "data", "resumes", "pdf", "*.pdf")))):
    name = os.path.splitext(os.path.basename(pdf))[0]
    if name.startswith("_"):
        continue
    # the kit requires a fresh output directory for every render
    page_dir = os.path.join(TMP, f"p{i}")
    subprocess.run(["rm", "-rf", page_dir], check=False)
    r = subprocess.run([NODE, CLI, "render", "--input", pdf, "--output-dir", page_dir, "--pages", "1", "--dpi", str(DPI)],
                       capture_output=True, text=True, timeout=300)
    if not r.stdout.strip():
        print("RENDER FAILED", name, r.stderr[-300:])
        continue
    info = json.loads(r.stdout.strip().splitlines()[-1])
    src = info["images"][0]["path"]
    im = Image.open(src).convert("RGBA")
    bg = Image.new("RGB", im.size, (255, 255, 255))
    bg.paste(im, mask=im.split()[3])
    dst = os.path.join(ROOT, "data", "resumes", "img", name + ".png")
    bg.save(dst, "PNG", optimize=True)
    out.append({"name": name, "png": dst, "size": f"{im.size[0]}x{im.size[1]}", "bytes": os.path.getsize(dst)})
    print(f"OK {im.size[0]}x{im.size[1]} {os.path.getsize(dst)//1024}KB  {name}")

json.dump(out, open(os.path.join(ROOT, "data", "resumes", "img", "images.json"), "w"), ensure_ascii=False, indent=1)
print("total", len(out))
