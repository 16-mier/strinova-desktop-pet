# -*- coding: utf-8 -*-
"""ascii_compare.py —— 多张图并排/叠加显示为字符画，用于对比表情差异

用法：
    python ascii_compare.py 宽 图1 图2 图3 ...          # 并排
    python ascii_compare.py --diff 宽 基准 图A 图B       # 只显示与基准不同的像素
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

RAMP = " .:-=+*#%@"


def load(path, size=None):
    im = Image.open(path).convert("RGBA")
    bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
    im = Image.alpha_composite(bg, im).convert("RGB")
    if size:
        im = im.resize(size, Image.LANCZOS)
    return im


def to_rows(im, nw):
    w, h = im.size
    nh = max(1, int(h / w * nw * 0.5))
    small = im.convert("L").resize((nw, nh), Image.LANCZOS)
    px = list(small.getdata())
    out = []
    for y in range(nh):
        row = []
        for x in range(nw):
            v = px[y * nw + x]
            row.append(RAMP[int((255 - v) / 255 * (len(RAMP) - 1))])
        out.append("".join(row))
    return out


def main():
    args = sys.argv[1:]
    mode = "side"
    if args and args[0] == "--diff":
        mode = "diff"
        args = args[1:]
    nw = int(args[0])
    files = [Path(a) for a in args[1:]]

    if mode == "side":
        ims = [load(f, (nw * 2, nw * 2)) for f in files]
        rows = [to_rows(im, nw) for im in ims]
        nh = len(rows[0])
        # 标题
        hdr = "".join(f"{f.stem[:nw-1]:<{nw}s}" for f in files)
        print(hdr)
        print("-" * len(hdr))
        for y in range(nh):
            print("".join(r[y] for r in rows))
    else:
        base = to_rows(load(files[0], (nw * 2, nw * 2)), nw)
        for f in files[1:]:
            cur = to_rows(load(f, (nw * 2, nw * 2)), nw)
            print(f"\n### {files[0].stem}  vs  {f.stem}   (# = 有差异)")
            for y in range(len(base)):
                line = "".join("#" if base[y][x] != cur[y][x] else "."
                               for x in range(nw))
                print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
