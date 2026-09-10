"""分析截图，判断是否真的渲染出了 3D 模型（而非空白/背景）。

用法：python check_shot.py <png> [--name 名字]
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    print("需要 Pillow: pip install Pillow")
    sys.exit(1)


def main() -> int:
    path = Path(sys.argv[1])
    name = sys.argv[3] if len(sys.argv) > 3 and sys.argv[2] == "--name" else path.name

    im = Image.open(path).convert("RGBA")
    w, h = im.size
    px = im.load()

    # 统计
    opaque = 0
    alpha0 = 0
    colors: Counter = Counter()
    bbox = [w, h, 0, 0]  # l,t,r,b

    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a < 16:
                alpha0 += 1
                continue
            opaque += 1
            colors[(r // 16 * 16, g // 16 * 16, b // 16 * 16)] += 1
            if x < bbox[0]: bbox[0] = x
            if y < bbox[1]: bbox[1] = y
            if x > bbox[2]: bbox[2] = x
            if y > bbox[3]: bbox[3] = y

    total = w * h
    coverage = opaque / total * 100
    print(f"===== {name} ({w}x{h}) =====")
    print(f"  不透明像素 : {opaque:,} / {total:,}  ({coverage:.1f}%)")
    print(f"  全透明像素 : {alpha0:,}  ({alpha0/total*100:.1f}%)")
    print(f"  内容包围盒 : x[{bbox[0]}..{bbox[2]}] y[{bbox[1]}..{bbox[3]}]  "
          f"尺寸 {bbox[2]-bbox[0]+1}x{bbox[3]-bbox[1]+1}")
    print(f"  颜色种类   : {len(colors)}")
    print(f"  Top 8 颜色 :")
    for c, n in colors.most_common(8):
        print(f"      #{c[0]:02x}{c[1]:02x}{c[2]:02x}  {n:,} px ({n/opaque*100:.1f}%)")

    # 判定
    print()
    if opaque == 0:
        print("  >>> 判定：空白！什么都没渲染出来")
        return 2
    if len(colors) < 5:
        print("  >>> 判定：只有纯色块，可能是错误页/占位")
        return 2
    if coverage < 5:
        print(f"  >>> 判定：内容极少 ({coverage:.1f}%)，可能只有文字 UI")
        return 2
    # 人形特征：竖直方向应有内容分布（头、身、腿）
    row_fill = []
    for y in range(0, h, max(1, h // 20)):
        cnt = sum(1 for x in range(0, w, 3) if px[x, y][3] > 16)
        row_fill.append(cnt)
    nonempty = sum(1 for c in row_fill if c > 0)
    print(f"  竖直填充行  : {nonempty}/{len(row_fill)}")
    print(f"  >>> 判定：有实质 3D 内容渲染成功")
    return 0


if __name__ == "__main__":
    sys.exit(main())
