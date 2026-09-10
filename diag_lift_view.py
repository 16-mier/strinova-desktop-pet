"""diag_lift_view.py —— 用 ASCII 轮廓"看"被提起时的姿态

为什么用 ASCII：本会话的视觉通道对图像无效（read_image 只回元数据），
所以用字符画把角色轮廓画出来，靠肉眼判断姿态对不对。

输出：
  · 静止站姿
  · 被从腰部提起（带摆动）
每个都给出顶/底/左/右边界，以及腰、脚、头的相对位置。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pet  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

import web3d_pet as w3  # noqa: E402

W, H = 46, 30


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    win = w3.Web3DPetWindow(model="michelle", size=(280, 380))
    win.move(300, 200)
    win.show()
    win.raise_()

    def js(code, wait=6.0):
        box = {}
        win.page.runJavaScript(code, lambda v: box.__setitem__("v", v))
        t = time.time() + wait
        while time.time() < t and "v" not in box:
            app.processEvents()
            time.sleep(0.005)
        return box.get("v")

    for _ in range(300):
        app.processEvents()
        time.sleep(0.02)
        if js("window.__hairStats() ? 1 : 0", wait=2) == 1:
            break

    js("window.__setIdleMotion(false); window.setBlinkEnabled(false); 'ok'")
    js(f"window.__setIdleMotion(false); 'ok'")

    def shot(label):
        raw = js(f"window.__silhouette({W}, {H})", wait=8)
        print(f"\n--- {label} ---")
        print(raw)

    shot("① 静止站姿")
    js("window.setDragging(true, 0); 'ok'")
    time.sleep(1.0)
    for _ in range(20):
        app.processEvents()
        time.sleep(0.01)
    shot("② 从腰部提起（正立）")

    js("window.setDragging(true, 40); 'ok'")
    time.sleep(0.5)
    for _ in range(20):
        app.processEvents()
        time.sleep(0.01)
    shot("③ 摆动中（应绕腰倾斜，腿甩出去）")

    win.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
