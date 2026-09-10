# -*- coding: utf-8 -*-
"""ascii_view.py —— 把 PNG 变成字符画（让文字模型也能"看"到画面）

用法：
    python ascii_view.py <图片> [宽=100] [--crop x0,y0,x1,y1] [--color]
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

RAMP = " .:-=+*#%@"


def to_ascii(path, width=100, crop=None, show_color=False, bg_transparent=None):
    im = Image.open(path).convert("RGBA")
    if crop:
        im = im.crop(crop)

    # 透明背景合成到白底（桌宠截图是透明底）
    if bg_transparent is None:
        bg_transparent = True
    if bg_transparent:
        bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
        im = Image.alpha_composite(bg, im)

    im = im.convert("L")
    w, h = im.size
    # 字符高宽比约 2:1
    nw = width
    nh = max(1, int(h / w * nw * 0.5))
    small = im.resize((nw, nh), Image.LANCZOS)
    px = list(small.getdata())

    lines = []
    for y in range(nh):
        row = []
        for x in range(nw):
            v = px[y * nw + x]
            idx = int((255 - v) / 255 * (len(RAMP) - 1))
            row.append(RAMP[idx])
        lines.append("".join(row))
    return lines


def stats(path):
    im = Image.open(path).convert("RGBA")
    w, h = im.size
    px = list(im.getdata())
    opaque = [p for p in px if p[3] > 16]
    if not opaque:
        return f"{w}x{h} 全透明"
    xs = [i % w for i, p in enumerate(px) if p[3] > 16]
    ys = [i // w for i, p in enumerate(px) if p[3] > 16]
    return (f"{w}x{h} 不透明像素 {len(opaque)} ({len(opaque)/(w*h)*100:.1f}%) "
            f"包围盒 x[{min(xs)}..{max(xs)}] y[{min(ys)}..{max(ys)}]")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    p = Path(sys.argv[1])
    width = 100
    crop = None
    for i, a in enumerate(sys.argv[2:], 2):
        if a.startswith("--crop"):
            if "=" in a:
                vals = a.split("=", 1)[1]
            else:
                vals = sys.argv[i + 1]
            crop = tuple(int(v) for v in vals.split(","))
        elif a.isdigit():
            width = int(a)

    print(f"### {p.name}  {stats(p)}")
    if crop:
        print(f"### 裁剪区域: {crop}")
    for line in to_ascii(p, width, crop):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
