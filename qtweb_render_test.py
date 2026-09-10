"""QtWebEngine 内渲染 VRM 并抓图验证（最接近最终效果的验证）。

用法：python qtweb_render_test.py [--timeout 40]
输出：qtweb_render.png + 控制台统计
"""
from __future__ import annotations

import base64
import http.server
import os
import socketserver
import sys
import threading
from pathlib import Path

os.environ.setdefault(
    "QTWEBENGINE_CHROMIUM_FLAGS",
    "--enable-unsafe-swiftshader --ignore-gpu-blocklist --enable-gpu-rasterization",
)

from PyQt6.QtCore import QTimer, Qt, QUrl
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PyQt6.QtWebEngineWidgets import QWebEngineView

HERE = Path(__file__).resolve().parent
SRV_DIR = HERE / "webgpu_probe"
PORT = 8791
W, H = 360, 480


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(SRV_DIR), **kw)

    def log_message(self, *a):
        pass


class Page(QWebEnginePage):
    def javaScriptConsoleMessage(self, level, message, line, source):
        if level.name.startswith("Error"):
            print(f"[js:ERR] {message}")
        elif "VRM OK" in message or "ERROR" in message or "FATAL" in message:
            print(f"[js] {message}")


def main() -> int:
    httpd = socketserver.TCPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    app = QApplication(sys.argv)
    w = QWidget()
    w.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
    w.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    w.resize(W, H)

    view = QWebEngineView(w)
    page = Page(view)
    view.setPage(page)
    view.setGeometry(0, 0, W, H)
    page.setBackgroundColor(QColor(0, 0, 0, 0))
    s = view.settings()
    s.setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, True)
    s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
    s.setAttribute(QWebEngineSettings.WebAttribute.ShowScrollBars, False)

    view.load(QUrl(f"http://127.0.0.1:{PORT}/probe.html"))
    w.show()
    print(f"[test] window shown {W}x{H}")

    state = {"phase": 0, "log": []}

    def step1():
        page.runJavaScript("window.__loaded === true", lambda v: (print(f"[test] __loaded={v}"), state.update(loaded=bool(v))))
        page.runJavaScript("document.getElementById('status').textContent",
                           lambda v: print(f"[test] status: {v}"))

    def step2():
        # 抓 WebGL canvas 的 dataURL
        page.runJavaScript("window.__snapshot ? window.__snapshot() : 'NO_SNAPSHOT'", on_snapshot)

    def on_snapshot(data):
        if not data or data == "NO_SNAPSHOT" or not str(data).startswith("data:image"):
            print(f"[test] snapshot unavailable: {str(data)[:120]}")
            finish()
            return
        b64 = str(data).split(",", 1)[1]
        out = HERE / "qtweb_render.png"
        out.write_bytes(base64.b64decode(b64))
        print(f"[test] canvas snapshot -> {out} ({out.stat().st_size:,} B)")

        # 同时抓窗口合成结果
        pm = w.grab()
        pm.save(str(HERE / "qtweb_window.png"))
        img = pm.toImage()
        c = img.pixelColor(W // 2, H // 2).getRgb()
        edge = img.pixelColor(3, 3).getRgb()
        print(f"[test] window grab: center={c} corner={edge}")

        # 逐个测试表情接口
        page.runJavaScript("window.__listExpressions().join(',')",
                           lambda v: print(f"[test] expressions: {v}"))
        page.runJavaScript("window.__setExpression('happy', 0.8)", lambda v: print(f"[test] setExpression happy -> {v}"))
        page.runJavaScript("window.__setViseme('aa')", lambda v: print(f"[test] setViseme aa -> {v}"))
        page.runJavaScript("window.__setMapOffset('NONE', 0, 0)", lambda v: print(f"[test] setMapOffset -> {v}"))
        finish()

    def finish():
        print("[test] done")
        app.quit()

    QTimer.singleShot(6000, step1)
    QTimer.singleShot(14000, step2)
    QTimer.singleShot(22000, lambda: (print("[test] timeout"), app.quit()))

    app.exec()
    httpd.shutdown()

    png = HERE / "qtweb_render.png"
    if png.exists():
        import subprocess
        print("\n[test] 分析 canvas 截图:")
        subprocess.run([sys.executable, str(HERE / "check_shot.py"), str(png)])
    return 0


if __name__ == "__main__":
    sys.exit(main())
