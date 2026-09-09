# -*- coding: utf-8 -*-
"""聚焦诊断：btn_expand.click() 是否真的调用 toggle_expand"""
import os
import sys

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QRect
import ai_chat as ai


class FakePet:
    role = "星绘"
    def load_config(self): return {}
    def save_config(self, c): pass
    def base_dir(self): return ROOT
    def frameGeometry(self): return QRect(600, 500, 200, 200)
    def update(self): pass


app = QApplication(sys.argv)
mgr = ai.AiChatManager(FakePet())
mgr.open_chat()
cw = mgr._chat

print('receivers(clicked) =', cw.btn_expand.receivers(cw.btn_expand.clicked))

# 插桩：用 callable 替换方法并重新连接
orig = cw.toggle_expand
calls = []


def traced(*a, **k):
    calls.append((a, k))
    print('  >> toggle_expand called, _expanded was', cw._expanded)
    r = orig(*a, **k)
    print('  >> after orig: _expanded =', cw._expanded, 'height =', cw.height())
    return r


# 直接重新连接（原连接保留会导致双调用，先断开再连）
try:
    cw.btn_expand.clicked.disconnect()
except Exception as e:
    print('disconnect err:', e)
cw.btn_expand.clicked.connect(traced)
print('receivers after re-connect =', cw.btn_expand.receivers(cw.btn_expand.clicked))

cw.btn_expand.click()
import time
time.sleep(0.2)
print('calls =', len(calls))
print('final: _expanded =', cw._expanded, 'height =', cw.height())
print('DIAG DONE')