"""诊断材质贴图绑定情况（为什么模型是灰白的）。

用法：python qtweb_mat_diag.py
"""
from __future__ import annotations

import http.server
import io
import os
import socketserver
import sys
import threading
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--ignore-gpu-blocklist --enable-unsafe-swiftshader"

from PyQt6.QtCore import QTimer, Qt, QUrl
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PyQt6.QtWebEngineWidgets import QWebEngineView

HERE = Path(__file__).resolve().parent
SRV_DIR = HERE / "webgpu_probe"
PORT = 8794


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(SRV_DIR), **kw)

    def log_message(self, *a):
        pass


class Page(QWebEnginePage):
    def javaScriptConsoleMessage(self, level, message, line, source):
        if "VRM OK" in message or level.name.startswith("Error"):
            print(f"[js] {message}")


def main() -> int:
    httpd = socketserver.TCPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    app = QApplication(sys.argv)
    w = QWidget()
    w.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
    w.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    w.resize(300, 420)

    view = QWebEngineView(w)
    page = Page(view)
    view.setPage(page)
    view.setGeometry(0, 0, 300, 420)
    page.setBackgroundColor(QColor(0, 0, 0, 0))
    view.settings().setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, True)
    view.load(QUrl(f"http://127.0.0.1:{PORT}/probe.html"))
    w.show()

    def dump():
        js = (SRV_DIR / "mat_diag.js").read_text(encoding="utf-8")

        def cb(res):
            print("[diag] result:")
            print(str(res)[:4000])

        page.runJavaScript(js, cb)

    def dump2():
        def cb(res):
            print(f"\n[diag2] vrm.scene children: {str(res)[:1500]}")
        page.runJavaScript("""
          (() => {
            const vrm = window.__vrm; if (!vrm) return 'no vrm';
            const out = [];
            vrm.scene.traverse(o => {
              if (o.isMesh) {
                const ms = Array.isArray(o.material) ? o.material : [o.material];
                ms.forEach(m => {
                  if (!m) return;
                  const keys = Object.keys(m).filter(k => /map/i.test(k) && m[k]);
                  out.push(m.name + '|' + m.type + '|maps:' + keys.join(',') +
                           '|col:' + (m.color ? m.color.getHexString() : '-') +
                           '|emi:' + (m.emissive ? m.emissive.getHexString() : '-'));
                });
              }
            });
            return out.join('\\n');
          })()
        """, cb)

    QTimer.singleShot(8000, dump)
    QTimer.singleShot(12000, dump2)
    QTimer.singleShot(16000, app.quit)
    app.exec()
    httpd.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
