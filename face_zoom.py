# -*- coding: utf-8 -*-
"""face_zoom.py —— 把多张图的脸部区域并排字符画（直接"看"表情差别）

用法：python face_zoom.py x0,y0,x1,y1 宽 图1 图2 ...
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

RAMP = " .:-=+*#%@"


def rows(im, nw):
    w, h = im.size
    nh = max(1, int(h / w * nw * 0.5))
    g = im.convert("L").resize((nw, nh), Image.LANCZOS)
    px = list(g.get_flattened_data()) if hasattr(g, "get_flattened_data") else list(g.getdata())
    return ["".join(RAMP[int((255 - px[y * nw + x]) / 255 * (len(RAMP) - 1))]
                    for x in range(nw)) for y in range(nh)]


def main():
    crop = tuple(int(v) for v in sys.argv[1].split(","))
    nw = int(sys.argv[2])
    files = [Path(a) for a in sys.argv[3:]]

    allrows = []
    for f in files:
        im = Image.open(f).convert("RGBA").crop(crop)
        bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
        im = Image.alpha_composite(bg, im).convert("RGB")
        allrows.append(rows(im, nw))

    nh = len(allrows[0])
    hdr = " | ".join(f"{f.stem[:nw-1]:<{nw}s}" for f in files)
    print(hdr)
    print("-" * len(hdr))
    for y in range(nh):
        print(" | ".join(r[y] for r in allrows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
