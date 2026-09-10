"""QtWebEngine 极简加载诊断 —— 找出页面为什么没加载。"""
from __future__ import annotations

import http.server
import os
import socketserver
import sys
import threading
from pathlib import Path

os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--enable-gpu --ignore-gpu-blocklist --enable-unsafe-swiftshader --no-sandbox")

from PyQt6.QtCore import QTimer, Qt, QUrl
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PyQt6.QtWebEngineWidgets import QWebEngineView

HERE = Path(__file__).resolve().parent
SRV_DIR = HERE / "webgpu_probe"
PORT = 8778


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(SRV_DIR), **kw)

    def log_message(self, fmt, *a):
        print(f"[http] {fmt % a}")


class Page(QWebEnginePage):
    def javaScriptConsoleMessage(self, level, message, line, source):
        print(f"[js:{level.name}] {message}  ({source}:{line})")


def main():
    httpd = socketserver.TCPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    print(f"[diag] serving {HERE} on {PORT}")

    # 先用 python 自己确认 http 服务是通的
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/probe.html", timeout=5) as r:
            body = r.read()
        print(f"[diag] python http GET ok: {len(body)} bytes")
    except Exception as e:
        print(f"[diag] python http GET FAILED: {e}")
        return 1

    app = QApplication(sys.argv)

    w = QWidget()
    w.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
    w.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    w.resize(320, 420)

    view = QWebEngineView(w)
    page = Page(view)
    view.setPage(page)
    view.setGeometry(0, 0, 320, 420)
    page.setBackgroundColor(QColor(0, 0, 0, 0))
    s = view.settings()
    s.setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, True)
    s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)

    state = {"finished": False}

    def on_load(ok):
        print(f"[diag] loadFinished ok={ok}")
        state["finished"] = True
        page.runJavaScript("document.documentElement.outerHTML.length",
                           lambda v: print(f"[diag] html length = {v}"))
        page.runJavaScript("document.getElementById('status') ? document.getElementById('status').textContent : 'NO_STATUS_EL'",
                           lambda v: print(f"[diag] status = {v}"))

    view.loadFinished.connect(on_load)
    view.load(QUrl(f"http://127.0.0.1:{PORT}/probe.html"))
    w.show()

    def poll():
        page.runJavaScript("document.getElementById('info') ? document.getElementById('info').textContent : 'NO_EL'",
                           lambda v: print(f"[diag:t+10] info = {v}"))
        page.runJavaScript("document.getElementById('status') ? document.getElementById('status').textContent : 'NO_EL'",
                           lambda v: print(f"[diag:t+10] status = {v}"))

    QTimer.singleShot(10000, poll)

    def done():
        print(f"[diag] quitting (loadFinished seen: {state['finished']})")
        app.quit()

    QTimer.singleShot(18000, done)
    app.exec()
    httpd.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
