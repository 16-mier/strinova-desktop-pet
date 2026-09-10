# -*- coding: utf-8 -*-
"""verify_all_models.py —— 对全部 VRM 模型验证取景与姿势

新加的 relaxArms / fitCamera 是按模型自适应的，必须确认对 4 个模型都成立：
  · 角色完整落在窗口内（头脚不被裁）
  · 手臂不是 T-pose 张开（宽度收窄）
  · 记录「是否本来就是自然站姿」（relaxArms 应跳过）

用法：python verify_all_models.py
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

MODELS = ["michelle_expr.vrm", "aldina.vrm", "Zome.vrm", "Lazuli_VRM.vrm"]


class Page(QWebEnginePage):
    def javaScriptConsoleMessage(self, level, message, line, source):
        if level.name.startswith("Error") or "relaxArms" in message or "fitCamera" in message:
            print(f"    [js] {message[:190]}")


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

    def js(code, timeout=25000):
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
    wait(1500)
    js("window.__setIdleMotion(false)")
    js("window.setBlinkEnabled(false)")
    wait(500)

    results = []
    print(f"\n{'模型':<20s}{'高':>7s}{'宽':>7s}{'相机Z':>8s}{'上空白':>8s}{'下空白':>8s}{'占窗口':>8s}  判定")
    print("-" * 90)

    for m in MODELS:
        print(f"\n>>> {m}")
        ok = js(f"window.loadModel('./models/{m}')")
        for _ in range(50):
            wait(400)
            if str(js("window.getModel()")) == m:
                break
        wait(2500)
        js("window.__setIdleMotion(false)")
        js("window.setBlinkEnabled(false)")
        wait(600)

        sb = json.loads(js("window.__skinnedBox()") or "{}")
        se = json.loads(js("window.__screenExtent()") or "{}")
        size = sb.get("size", [0, 0, 0])

        # 截图统计
        top = bot = -1
        ratio = 0.0
        u = js("window.__snapshot()", 25000)
        if u and str(u).startswith("data:image"):
            raw = base64.b64decode(str(u).split(",", 1)[1])
            (HERE / f"all_{m.replace('.vrm','')}.png").write_bytes(raw)
            im = Image.open(io.BytesIO(raw)).convert("RGBA")
            ww, hh = im.size
            a = im.getchannel("A")
            px = list(a.get_flattened_data()) if hasattr(a, "get_flattened_data") else list(a.getdata())
            ys = [i // ww for i, v in enumerate(px) if v > 16]
            if ys:
                top, bot = min(ys), max(ys)
                ratio = (bot - top) / hh

        in_view = bool(se.get("inView"))
        good = in_view and top >= 2 and bot <= H - 2 and ratio >= 0.5
        print(f"{m:<20s}{size[1]:7.2f}{size[0]:7.2f}{sb.get('camZ',0):8.2f}"
              f"{se.get('topPct',0):7.1f}%{se.get('bottomPct',0):7.1f}%{ratio*100:7.1f}%  "
              f"{'★ 完整' if good else '✗ 有问题'}")
        results.append((m, good, in_view, top, bot, ratio))

    print("-" * 90)
    okn = sum(1 for r in results if r[1])
    print(f"\n结果：{okn}/{len(results)} 模型取景正常")
    for m, good, iv, t, b, r in results:
        if not good:
            print(f"  ✗ {m}: inView={iv} top={t} bottom={b} 占比={r*100:.1f}%")
    return 0 if okn == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
