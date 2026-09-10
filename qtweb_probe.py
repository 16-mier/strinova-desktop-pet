"""QtWebEngine + three-vrm 透明窗口可行性探针。

验证四件事：
1. QWebEngineView 能否在透明无边框 PyQt6 窗口里正常显示
2. WebGL 是否可用（QtWebEngine 里 GPU 是否启用）
3. three-vrm 能否加载 michelle.vrm
4. 背景是否真透明（截屏采样角落像素）

用法：python qtweb_probe.py [--timeout 25]
"""
from __future__ import annotations

import argparse
import http.server
import os
import socketserver
import sys
import threading
import time
from pathlib import Path

# --- QtWebEngine 必须在 QApplication 之前设置 ---
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--enable-gpu --ignore-gpu-blocklist --enable-unsafe-swiftshader")

from PyQt6.QtCore import QTimer, Qt, QUrl
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PyQt6.QtWebEngineWidgets import QWebEngineView

HERE = Path(__file__).resolve().parent
PORT = 8777
ROOT = Path(r"C:\Users\mier\Desktop\deepseek work")
SRV_DIR = Path(__file__).resolve().parent / "webgpu_probe"


def find_vrm(name: str = "michelle.vrm") -> Path | None:
    for p in ROOT.rglob(name):
        return p
    return None


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(SRV_DIR), **kw)

    def log_message(self, *a):
        pass


def start_server(vrm: Path | None) -> socketserver.TCPServer:
    # 把 VRM 复制/链接到 probe 目录下供 HTTP 提供
    if vrm is not None:
        dst = SRV_DIR / "michelle.vrm"
        if not dst.exists():
            try:
                os.link(vrm, dst)
            except OSError:
                import shutil
                shutil.copy2(vrm, dst)

    httpd = socketserver.TCPServer(("127.0.0.1", PORT), Handler)
    httpd.allow_reuse_address = True
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd


class WebPage(QWebEnginePage):
    def javaScriptConsoleMessage(self, level, message, line, source):
        print(f"[js:{level.name}] {message}  ({source}:{line})")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeout", type=float, default=25.0)
    args = ap.parse_args()

    vrm = find_vrm()
    print(f"[probe] VRM: {vrm}")
    httpd = start_server(vrm)
    print(f"[probe] http://127.0.0.1:{PORT}/probe.html")

    app = QApplication(sys.argv)

    w = QWidget()
    w.setWindowTitle("QtWebThreeProbe")
    w.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
    w.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    w.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
    w.resize(320, 420)
    w.move(200, 200)

    view = QWebEngineView(w)
    page = WebPage(view)
    view.setPage(page)
    view.setGeometry(0, 0, 320, 420)
    page.setBackgroundColor(QColor(0, 0, 0, 0))
    s = view.settings()
    s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
    s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
    s.setAttribute(QWebEngineSettings.WebAttribute.ShowScrollBars, False)
    s.setAttribute(QWebEngineSettings.WebAttribute.Accelerated2dCanvasEnabled, True)
    s.setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, True)

    # 把 JS console 转到 python 输出
    view.load(QUrl(f"http://127.0.0.1:{PORT}/probe.html"))
    w.show()

    results: dict = {}

    def grab():
        # 截图采样：检查角落像素是否透明
        pm = w.grab()
        img = pm.toImage()
        w_, h_ = img.width(), img.height()
        samples = {
            "corner_tl": img.pixelColor(2, 2).getRgb(),
            "corner_br": img.pixelColor(w_ - 3, h_ - 3).getRgb(),
            "center": img.pixelColor(w_ // 2, h_ // 2).getRgb(),
        }
        results["samples"] = samples
        print(f"[probe] pixel samples: {samples}")

        def js_done(val):
            print(f"[probe] JS info: {val}")
            results["info"] = val
        view.page().runJavaScript("document.getElementById('info').textContent", js_done)

        def js_status(val):
            print(f"[probe] JS status: {val}")
            results["status"] = val
            app.quit()
        view.page().runJavaScript("document.getElementById('status').textContent", js_status)

    QTimer.singleShot(int(args.timeout * 1000), grab)
    app.exec()

    print("\n===== RESULT =====")
    print(f"webgl info : {results.get('info')}")
    print(f"status     : {results.get('status')}")
    print(f"pixels     : {results.get('samples')}")
    # 判断：VRM loaded 说明 three-vrm + WebGL 全通
    ok = "VRM loaded" in str(results.get("status", ""))
    print(f"VERDICT    : {'PASS three-vrm works in QtWebEngine' if ok else 'NEEDS INVESTIGATION'}")
    httpd.shutdown()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
