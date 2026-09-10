"""最小化 QWebChannel 双向桥测试 —— 定位 JS→Python 调用为何不达。

用法：python diag_bridge.py
"""
from __future__ import annotations

import io
import os
import sys
import time
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

os.environ.setdefault(
    "QTWEBENGINE_CHROMIUM_FLAGS",
    "--ignore-gpu-blocklist --enable-unsafe-swiftshader",
)

from PyQt6.QtCore import QObject, QTimer, Qt, QUrl, pyqtSignal, pyqtSlot, QEventLoop
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtWebEngineCore import QWebEnginePage
from PyQt6.QtWebEngineWidgets import QWebEngineView

from web3d_server import serve


class Page(QWebEnginePage):
    def javaScriptConsoleMessage(self, level, message, line, source):
        print(f"  [js:{level.name[:3]}] {message[:200]}")


class TestBridge(QObject):
    pong = pyqtSignal(str)

    @pyqtSlot(str)
    def ping(self, msg):
        print(f"  [py] <<< JS 调用 ping({msg!r})  ← 桥已打通")
        self.pong.emit("收到:" + msg)

    @pyqtSlot(str)
    def onReady(self, name):
        print(f"  [py] <<< onReady({name!r})")

    @pyqtSlot(int, int)
    def dragWindow(self, dx, dy):
        print(f"  [py] <<< dragWindow({dx},{dy})")


HTML = """<!DOCTYPE html><html><head><meta charset="utf-8">
<script src="./qwebchannel.js"></script></head>
<body style="background:transparent">
<div id="log">init</div>
<script>
const log = (m) => { document.getElementById('log').textContent += ' | ' + m; console.log(m); };
log('QWebChannel=' + (typeof QWebChannel));
if (window.qt && window.qt.webChannelTransport) {
  log('transport OK');
  new QWebChannel(window.qt.webChannelTransport, (ch) => {
    window.py = ch.objects.py;
    log('bridge ready, py=' + (typeof window.py));
    log('py methods: ' + Object.keys(window.py).join(','));
    window.py.ping('hello');
    window.py.onReady('michelle.vrm');
  });
} else {
  log('NO TRANSPORT');
}
</script></body></html>"""


def main() -> int:
    app = QApplication(sys.argv)
    port = serve(HERE / "web3d")
    (HERE / "web3d" / "_bridge_test.html").write_text(HTML, encoding="utf-8")
    print(f"[diag] serving on {port}")

    w = QWidget()
    w.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
    w.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    w.resize(300, 200)

    view = QWebEngineView(w)
    page = Page(view)
    view.setPage(page)
    view.setGeometry(0, 0, 300, 200)
    page.setBackgroundColor(QColor(0, 0, 0, 0))

    channel = QWebChannel(w)
    bridge = TestBridge(w)
    channel.registerObject("py", bridge)
    page.setWebChannel(channel)

    got = []
    bridge.pong.connect(lambda s: got.append(s))

    page.load(QUrl(f"http://127.0.0.1:{port}/_bridge_test.html"))
    w.show()

    def wait(ms):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    wait(6000)

    r = {"v": None, "done": False}
    page.runJavaScript("document.getElementById('log').textContent",
                       lambda v: r.update(v=v, done=True))
    for _ in range(30):
        wait(150)
        if r["done"]:
            break
    print(f"\n[diag] 页面日志: {r['v']}")
    print(f"[diag] Python 收到信号: {got}")
    ok = bool(got)
    print(f"[diag] 结论: {'桥双向正常' if ok else '桥未打通 ← 需修 qwebchannel.js'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
