"""dump WebChannel init 原始报文 —— 看清 Qt 到底下发了什么结构。

用法：python diag_wc_raw.py
"""
from __future__ import annotations

import io
import json
import os
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

os.environ.setdefault(
    "QTWEBENGINE_CHROMIUM_FLAGS",
    "--ignore-gpu-blocklist --enable-unsafe-swiftshader",
)

from PyQt6.QtCore import QObject, QTimer, Qt, QUrl, pyqtSlot, QEventLoop
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtWebEngineCore import QWebEnginePage
from PyQt6.QtWebEngineWidgets import QWebEngineView

from web3d_server import serve


class Page(QWebEnginePage):
    def javaScriptConsoleMessage(self, level, message, line, source):
        print(f"  [js] {message[:900]}")


class B(QObject):
    @pyqtSlot(str)
    def ping(self, m):
        print(f"  [py] ping({m!r})")


# 用最小自实现，但在 transport.onmessage 里先打印原始 data
HTML = """<!DOCTYPE html><html><head><meta charset="utf-8"></head>
<body style="background:transparent"><div id="log">-</div>
<script>
const log = m => { document.getElementById('log').textContent = m; console.log(m); };
(function(){
  if (!(window.qt && window.qt.webChannelTransport)) { log('NO TRANSPORT'); return; }
  const t = window.qt.webChannelTransport;
  let id = 0; const cbs = {};
  window.__ALL = [];
  function exec(d, cb) { if (!cb) { t.send(JSON.stringify(d)); return; } d.id = id++; cbs[d.id] = cb; t.send(JSON.stringify(d)); }
  window.__exec = exec;
  t.onmessage = function(msg) {
    let d = msg.data; if (typeof d === 'string') d = JSON.parse(d);
    window.__ALL.push(JSON.stringify(d).slice(0, 4000));
    if (d.type === 10) { const c = cbs[d.id]; if (c) c(d.data); delete cbs[d.id]; return; }
    if (d.type === 3) { log('GOT TYPE 3'); }
  };
  exec({ type: 3 }, function(data) { log('init cb, objects=' + Object.keys(data).join(',')); });
})();
</script></body></html>"""


def main() -> int:
    app = QApplication(sys.argv)
    port = serve(HERE / "web3d")
    (HERE / "web3d" / "_wc_raw.html").write_text(HTML, encoding="utf-8")

    w = QWidget()
    w.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
    w.resize(320, 200)
    view = QWebEngineView(w)
    pg = Page(view)
    view.setPage(pg)
    view.setGeometry(0, 0, 320, 200)
    pg.setBackgroundColor(QColor(0, 0, 0, 0))

    ch = QWebChannel(w)
    b = B(w)
    ch.registerObject("py", b)
    pg.setWebChannel(ch)

    pg.load(QUrl(f"http://127.0.0.1:{port}/_wc_raw.html"))
    w.show()

    def wait(ms):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    wait(6000)
    r = {"v": None, "done": False}
    pg.runJavaScript("JSON.stringify(window.__ALL || [])",
                     lambda v: r.update(v=v, done=True))
    for _ in range(40):
        wait(150)
        if r["done"]:
            break
    print(f"\n[diag] ===== WebChannel 收到的全部报文 =====")
    raw = r["v"]
    if raw:
        try:
            msgs = json.loads(raw)
            for i, m in enumerate(msgs):
                print(f"\n--- 报文[{i}] ---")
                try:
                    print(json.dumps(json.loads(m), ensure_ascii=False, indent=1)[:2500])
                except Exception:
                    print(m[:2500])
        except Exception as e:
            print("parse err:", e, str(raw)[:1000])
    else:
        print("(无报文)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
