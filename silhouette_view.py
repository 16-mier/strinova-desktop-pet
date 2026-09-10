# -*- coding: utf-8 -*-
"""silhouette_view.py —— 按【轮廓】显示字符画（用 alpha 通道，不受颜色/亮度干扰）

普通 ascii_view 按亮度映射，浅色部位（白袜子/肤色/白裙）在白色背景上会变成空格，
看起来像"缺失"，其实只是对比度低。本脚本只看 alpha，能如实反映形状。

用法：python silhouette_view.py <图> [宽=80]
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image


def main():
    p = Path(sys.argv[1])
    nw = int(sys.argv[2]) if len(sys.argv) > 2 else 80

    im = Image.open(p).convert("RGBA")
    w, h = im.size
    nh = max(1, int(h / w * nw * 0.5))
    # 用 alpha 做最近邻缩放，再用 LANCZOS 平滑出边缘灰度
    a = im.getchannel("A").resize((nw, nh), Image.LANCZOS)
    px = list(a.get_flattened_data()) if hasattr(a, "get_flattened_data") else list(a.getdata())

    RAMP = " .:-=+*#%@"
    print(f"### {p.name}  {w}x{h}  轮廓模式（@ = 实体）")
    for y in range(nh):
        print("".join(RAMP[min(9, int(px[y * nw + x] / 256 * 10))]
                      for x in range(nw)))

    # 分部位统计（按高度切片），判断头/身/腿是否都在
    print()
    print("### 分段覆盖率")
    for label, y0, y1 in (("头(上 1/4)", 0, h // 4),
                          ("上身(1/4-1/2)", h // 4, h // 2),
                          ("下身(1/2-3/4)", h // 2, h * 3 // 4),
                          ("腿脚(下 1/4)", h * 3 // 4, h)):
        op = 0
        tot = 0
        full = im.getchannel("A")
        fpx = list(full.get_flattened_data()) if hasattr(full, "get_flattened_data") else list(full.getdata())
        for y in range(y0, y1):
            for x in range(w):
                tot += 1
                if fpx[y * w + x] > 16:
                    op += 1
        print(f"  {label:<16s} 不透明 {op:6d} / {tot:6d}  ({op/max(1,tot)*100:5.1f}%)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
