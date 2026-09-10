# -*- coding: utf-8 -*-
"""render_real.py —— 渲染【真实运行中的 pet_viewer.html】，抓图供检查

与 shot_pet.py 的区别：这个直接加载桌宠真正用的页面（含 MorphDriver、
正确的朝向、真实光照），所以拍到的就是用户看到的东西。

用法：python render_real.py [--w 420] [--h 560]
"""
from __future__ import annotations

import argparse
import base64
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


class Page(QWebEnginePage):
    def javaScriptConsoleMessage(self, level, message, line, source):
        print(f"  [js/{level.name[:4]}] {message[:200]}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--w", type=int, default=420)
    ap.add_argument("--h", type=int, default=560)
    args = ap.parse_args()

    app = QApplication(sys.argv)
    port = serve(SRV_DIR)
    url = f"http://127.0.0.1:{port}/pet_viewer.html"
    print(f"[r] 加载真实页面: {url}")

    w = QWidget()
    w.resize(args.w, args.h)
    view = QWebEngineView(w)
    pg = Page(view)
    view.setPage(pg)
    view.setGeometry(0, 0, args.w, args.h)
    pg.setBackgroundColor(QColor(0, 0, 0, 0))
    view.settings().setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, True)
    pg.load(QUrl(url))
    w.show()

    def wait(ms):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def js(code, timeout=15000):
        box = {"v": None, "done": False}
        pg.runJavaScript(code, lambda v: box.update(v=v, done=True))
        t = 0
        while not box["done"] and t < timeout:
            wait(100)
            t += 100
        return box["v"]

    for i in range(90):
        wait(400)
        if js("window.getModel && window.getModel() ? true : false", 2000):
            break
    print(f"[r] 当前模型: {js('window.getModel()')}")
    print(f"[r] 表情驱动: {js('JSON.stringify(window.morphInfo && window.morphInfo())')}")
    wait(1500)

    def shot(name):
        u = js("window.__snapshot()", 20000)
        if u and str(u).startswith("data:image"):
            out = HERE / name
            out.write_bytes(base64.b64decode(str(u).split(",", 1)[1]))
            print(f"[r] -> {out.name} ({out.stat().st_size:,} B)")
        else:
            print(f"[r] 抓图失败: {str(u)[:100]}")

    shot("real_neutral.png")
    print(f"[r] 像素统计: {js('window.__pixelStats()')}")

    for expr in ("happy", "blink", "aa"):
        js(f"window.setExpression({json.dumps(expr)}, 1.0)")
        wait(1200)
        shot(f"real_{expr}.png")

    js("window.setExpression('neutral', 0)")
    wait(800)
    js("window.say('我是米雪儿～')")
    wait(600)
    shot("real_say.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
