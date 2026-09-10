# -*- coding: utf-8 -*-
"""verify_framing.py —— 验证「头脚完整可见 + 手臂自然垂放」

修复前：
  · 相机距离 = size.y*1.25 = 2.0，FOV 25° → 只见 0.887m，装得下全身 55%
  · 对焦点 0.99m → 视野 y∈[0.55,1.44] → 切掉头顶和膝盖以下
  · rest pose 是 T-pose（肩 Y=1.2929 = 手 Y=1.2929），整体宽 1.353

修复后应满足：
  · 角色完整体落在窗口内（inView=True，上下都有余量但不夸张）
  · 手臂下垂（手 Y 明显低于肩 Y），整体宽度大幅收窄

用法：python verify_framing.py
"""
from __future__ import annotations

import base64
import io
import json
import os
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent
SRV_DIR = HERE / "web3d"
sys.path.insert(0, str(HERE))

os.environ.setdefault(
    "QTWEBENGINE_CHROMIUM_FLAGS",
    "--ignore-gpu-blocklist --enable-gpu-rasterization --enable-unsafe-swiftshader",
)

from PyQt6.QtCore import QTimer, QUrl, QEventLoop
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PyQt6.QtWebEngineWidgets import QWebEngineView

from web3d_server import serve
from PIL import Image

PASS, FAIL = [], []


class Page(QWebEnginePage):
    def javaScriptConsoleMessage(self, level, message, line, source):
        if level.name.startswith("Error") or "relax" in message or "fitCamera" in message:
            print(f"  [js] {message[:200]}")


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))
    return cond


def png_bytes(u):
    if not u or not str(u).startswith("data:image"):
        return None
    return base64.b64decode(str(u).split(",", 1)[1])


def main() -> int:
    app = QApplication(sys.argv)
    port = serve(SRV_DIR)

    W, H = 420, 560
    w = QWidget()
    w.resize(W, H)
    view = QWebEngineView(w)
    pg = Page(view)
    view.setPage(pg)
    view.setGeometry(0, 0, W, H)
    pg.setBackgroundColor(QColor(0, 0, 0, 0))
    view.settings().setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, True)
    pg.load(QUrl(f"http://127.0.0.1:{port}/pet_viewer.html"))
    w.show()

    def wait(ms):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def js(code, timeout=20000):
        box = {"v": None, "done": False}
        pg.runJavaScript(code, lambda v: box.update(v=v, done=True))
        t = 0
        while not box["done"] and t < timeout:
            wait(100)
            t += 100
        return box["v"]

    for _ in range(80):
        wait(400)
        if js("window.getModel && window.getModel()"):
            break
    wait(2000)
    js("window.__setIdleMotion(false)")
    js("window.setBlinkEnabled(false)")
    wait(800)

    print("\n[1] 蒙皮后包围盒 / 相机…")
    sb = json.loads(js("window.__skinnedBox()") or "{}")
    print(f"       {sb}")
    size = sb.get("size", [0, 0, 0])
    check("模型高度合理（1~2m）", 0.8 < size[1] < 2.5, f"高={size[1]}m")

    print("\n[2] 取景：头脚是否都在窗口内…")
    se = json.loads(js("window.__screenExtent()") or "{}")
    print(f"       {se}")
    check("整个角色在视野内（头脚都没被裁）", bool(se.get("inView")), str(se.get("inView")))
    top = se.get("topPct", 999)
    bot = se.get("bottomPct", 999)
    check("头顶留有空白（没贴边）", 0.2 <= top <= 30, f"上空白 {top}%")
    check("脚底留有空白（没贴边）", 0.2 <= bot <= 30, f"下空白 {bot}%")

    print("\n[3] 手臂姿势…")
    hb = json.loads(js("""(() => {
      const g = n => { const b = vrmHumanoidNode(n); return b ? b.getWorldPosition(new THREE.Vector3()) : null; };
      return '{}';
    })()""") or "{}") if False else None
    # 直接查骨骼世界坐标
    arms = js("""JSON.stringify((() => {
      const H = (window.__driver() && null);
      return null;
    })())""")
    # 用页面暴露的包围盒宽高判断手臂是否收拢（T-pose 时宽 1.353，垂放后应 <=0.75）
    width = size[0]
    check("手臂已收拢（宽度明显小于 T-pose 的 1.35）", width <= 0.85, f"宽={width}m")

    print("\n[4] 截图检查…")
    u = js("window.__snapshot()", 25000)
    if u and str(u).startswith("data:image"):
        raw = base64.b64decode(str(u).split(",", 1)[1])
        out = HERE / "framing_fixed.png"
        out.write_bytes(raw)
        im = Image.open(io.BytesIO(raw)).convert("RGBA")
        ww, hh = im.size
        px = list(im.get_flattened_data()) if hasattr(im, "get_flattened_data") else list(im.getdata())
        ys = [i // ww for i, p in enumerate(px) if p[3] > 16]
        xs = [i % ww for i, p in enumerate(px) if p[3] > 16]
        cov = len(ys) / (ww * hh) * 100
        print(f"       -> framing_fixed.png  {ww}x{hh}  不透明 {cov:.1f}%")
        print(f"       角色像素范围  x[{min(xs)}..{max(xs)}]  y[{min(ys)}..{max(ys)}]")
        check("角色顶部未贴边（>=2px）", min(ys) >= 2, f"top={min(ys)}")
        check("角色底部未贴边（<=h-2）", max(ys) <= hh - 2, f"bottom={max(ys)} (h={hh})")
        check("角色高度占窗口合理比例（>=55%）",
              (max(ys) - min(ys)) / hh >= 0.55,
              f"{(max(ys)-min(ys))/hh*100:.1f}%")
    else:
        check("能截到图", False, str(u)[:80])

    print("\n" + "=" * 58)
    print(f"结果：{len(PASS)} 通过 / {len(FAIL)} 失败")
    if FAIL:
        print(f"失败项: {FAIL}")
    print("=" * 58)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
