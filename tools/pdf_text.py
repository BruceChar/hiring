#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Minimal Chrome/Skia PDF text extractor (Identity-H + ToUnicode CMaps).
Used to verify that the regenerated PDFs match the reviewed HTML text."""
import re, sys, zlib, os

def objects(data):
    objs = {}
    for m in re.finditer(rb"(\d+)\s+0\s+obj\b(.*?)endobj", data, re.S):
        objs[int(m.group(1))] = m.group(2)
    return objs

def get_stream(body):
    m = re.search(rb"stream\r?\n", body)
    if not m:
        return None
    raw = body[m.end():]
    raw = re.sub(rb"\r?\nendstream\s*$", b"", raw)
    if b"/FlateDecode" in body[:m.start()]:
        try:
            return zlib.decompress(raw)
        except Exception:
            try:
                return zlib.decompressobj().decompress(raw)
            except Exception:
                return None
    return raw

def parse_tounicode(cmap_bytes):
    m = {}
    txt = cmap_bytes
    for blk in re.findall(rb"beginbfchar(.*?)endbfchar", txt, re.S):
        for a, b in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", blk):
            code = int(a, 16)
            m[code] = bytes.fromhex(b.decode()).decode("utf-16-be", "ignore")
    for blk in re.findall(rb"beginbfrange(.*?)endbfrange", txt, re.S):
        for lo, hi, dst in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", blk):
            l, h = int(lo, 16), int(hi, 16)
            base = int(dst, 16)
            for i in range(h - l + 1):
                m[l + i] = chr(base + i)
    return m

def extract(path):
    data = open(path, "rb").read()
    objs = objects(data)
    # font name -> tounicode map, per page resources (single page here)
    fontmaps = {}
    for num, body in objs.items():
        if b"/Type0" in body or b"/ToUnicode" in body:
            mm = re.search(rb"/ToUnicode\s+(\d+)\s+0\s+R", body)
            if mm:
                tgt = int(mm.group(1))
                tb = objs.get(tgt)
                if tb is None:
                    continue
                st = get_stream(tb)
                if st:
                    fontmaps[num] = parse_tounicode(st)
    # map resource names (/F1) -> object numbers
    res = {}
    for num, body in objs.items():
        for name, ref in re.findall(rb"/(F\d+)\s+(\d+)\s+0\s+R", body):
            res.setdefault(name.decode(), int(ref))
    out = []
    for num, body in objs.items():
        if b"stream" not in body:
            continue
        st = get_stream(body)
        if not st or b"Tf" not in st or b"BT" not in st:
            continue
        cur = None
        for tok in re.finditer(rb"/(F\d+)\s+[\d.]+\s+Tf|<([0-9A-Fa-f\s]+)>|(TJ|Tj|T\*|Td|TD)", st):
            if tok.group(1):
                cur = res.get(tok.group(1).decode())
            elif tok.group(2) is not None:
                cmap = fontmaps.get(cur, {})
                hexs = re.sub(rb"\s", b"", tok.group(2)).decode()
                s = ""
                for i in range(0, len(hexs) - 1, 2):
                    code = int(hexs[i:i+2], 16)
                    s += cmap.get(code, "")
                    if cur is None:
                        s = ""
                out.append(s)
    return "".join(out)

if __name__ == "__main__":
    for p in sys.argv[1:]:
        t = extract(p)
        dest = os.path.join("_review3", "PDF_" + os.path.basename(p).replace(".pdf", ".txt"))
        open(dest, "w", encoding="utf-8").write(t)
        print("=" * 20, os.path.basename(p), len(t), "chars ->", dest)
        print(t[:400].replace("\n", " "))
