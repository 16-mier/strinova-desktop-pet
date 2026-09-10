"""真实 GPU 下的 three-vrm 渲染 + 帧率 + 功能测试（QtWebEngine 内）。

测什么：
- 实际帧率 (FPS)
- 是否为硬件加速
- 表情 / 视线 / 骨骼控制接口是否可用
- 抓图保存

用法：python qtweb_fps_test.py
"""
from __future__ import annotations

import base64
import http.server
import os
import socketserver
import sys
import threading
from pathlib import Path

# 允许真实 GPU
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (
    "--ignore-gpu-blocklist --enable-gpu-rasterization --enable-zero-copy "
    "--enable-unsafe-swiftshader"
)
os.environ["QT_OPENGL"] = "desktop"

from PyQt6.QtCore import QTimer, Qt, QUrl
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PyQt6.QtWebEngineWidgets import QWebEngineView

HERE = Path(__file__).resolve().parent
SRV_DIR = HERE / "webgpu_probe"
PORT = 8793
W, H = 300, 420


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(SRV_DIR), **kw)

    def log_message(self, *a):
        pass


class Page(QWebEnginePage):
    def javaScriptConsoleMessage(self, level, message, line, source):
        if level.name.startswith("Error") or "VRM OK" in message or "FPS" in message:
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
    for attr in ("WebGLEnabled", "Accelerated2dCanvasEnabled", "WebGL2Enabled"):
        try:
            s.setAttribute(getattr(QWebEngineSettings.WebAttribute, attr), True)
        except Exception:
            pass
    s.setAttribute(QWebEngineSettings.WebAttribute.ShowScrollBars, False)

    view.load(QUrl(f"http://127.0.0.1:{PORT}/perf.html"))
    w.show()

    results: dict = {}

    def q(js, key, label=None):
        def cb(v):
            results[key] = v
            print(f"[test] {label or key}: {v}")
        page.runJavaScript(js, cb)

    def phase1():
        q("window.__gpu || 'unknown'", "gpu", "GPU renderer")
        q("window.__fps ? window.__fps.toFixed(1) : 'n/a'", "fps", "FPS")
        q("window.__loaded === true", "loaded", "VRM loaded")

    def phase2():
        q("window.__listExpressions().join(',')", "exprs", "expressions")
        q("window.__listBones().length", "bones", "bone count")
        q("window.__setExpression('happy', 0.9)", "setexpr", "set happy=0.9")
        q("window.__blink(1.0)", "blink", "blink closed")
        q("window.__lookAt(0.5, 0.3)", "look", "look at")

    def phase3():
        q("window.__listExpressions().join(',')", "exprs2", "expressions (again)")
        q("JSON.stringify(window.__listMaterials().slice(0,5))", "mats", "materials")

    def phase4():
        page.runJavaScript("window.__snapshot()", on_shot)

    def on_shot(data):
        if data and str(data).startswith("data:image"):
            out = HERE / "qtweb_gpu.png"
            out.write_bytes(base64.b64decode(str(data).split(",", 1)[1]))
            print(f"[test] snapshot -> {out} ({out.stat().st_size:,} B)")
            results["png"] = str(out)
        else:
            print(f"[test] no snapshot: {str(data)[:100]}")
        app.quit()

    for ms, fn in ((7000, phase1), (11000, phase2), (16000, phase3), (20000, phase4)):
        QTimer.singleShot(ms, fn)
    QTimer.singleShot(30000, app.quit)

    app.exec()
    httpd.shutdown()

    png = HERE / "qtweb_gpu.png"
    if png.exists():
        import subprocess
        subprocess.run([sys.executable, str(HERE / "check_shot.py"), str(png)])
    print(f"\n[test] summary: gpu={results.get('gpu')} fps={results.get('fps')} "
          f"loaded={results.get('loaded')} bones={results.get('bones')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
