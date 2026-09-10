"""诊断：pet.py 里 QtWebEngine 的正确初始化方式。

测试三种顺序，找出不崩溃的那种：
  A. 模块级 import QtWebEngineWidgets → 再 QApplication（pet.py 当前做法）
  B. QApplication 前设 Qt.AA_ShareOpenGLContexts 属性
  C. QApplication 前 import + setAttribute 双保险

用法：python diag_qtwe_order.py [A|B|C]
"""
from __future__ import annotations

import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

os.environ.setdefault(
    "QTWEBENGINE_CHROMIUM_FLAGS",
    "--ignore-gpu-blocklist --enable-unsafe-swiftshader",
)

MODE = (sys.argv[1] if len(sys.argv) > 1 else 'C').upper()
print(f"[diag] mode {MODE}")

if MODE == 'A':
    # 只 import，不设属性
    from PyQt6 import QtWebEngineWidgets  # noqa

elif MODE == 'C':
    # 先 import，再在 QApplication 前设属性
    from PyQt6 import QtWebEngineWidgets  # noqa

from PyQt6.QtCore import Qt, QTimer, QUrl, QEventLoop
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication, QWidget

if MODE in ('B', 'C'):
    # ★ 关键：必须在 QApplication 实例化之前设置
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    print("[diag] set AA_ShareOpenGLContexts = True")

print("[diag] creating QApplication…")
app = QApplication(sys.argv)
print("[diag] QApplication OK")

from PyQt6.QtWebEngineWidgets import QWebEngineView  # noqa
from PyQt6.QtWebEngineCore import QWebEngineSettings

print("[diag] creating window…")
w = QWidget()
w.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
w.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
w.resize(300, 400)
view = QWebEngineView(w)
view.setGeometry(0, 0, 300, 400)
w.show()
print("[diag] window shown")

# 简单页面测试
view.setHtml("<html><body style='background:transparent'><h1 style='color:red'>OK</h1></body></html>",
             QUrl("about:blank"))

def done():
    print("[diag] event loop ran 3s without crash")
    app.quit()

QTimer.singleShot(3000, done)
app.exec()
print(f"[diag] MODE {MODE} -> SUCCESS")
