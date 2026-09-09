# -*- coding: utf-8 -*-
"""输入条（ChatWindow）冒烟：聊天按钮发信号/发送/清理/跟随"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QRect

app = QApplication([])
import ai_chat

ok = 0


def chk(name, cond):
    global ok
    assert cond, 'FAIL: ' + name
    ok += 1
    print('  PASS', name)


class FakePet:
    def __init__(self):
        self.ai = self

    def frameGeometry(self):
        return QRect(100, 100, 200, 200)


p = FakePet()
w = ai_chat.ChatWindow(p)
w.show()
app.processEvents()

chk('高度48', w.height() == ai_chat.ChatWindow.H_USAGE)
chk('有聊天按钮', hasattr(w, 'btn_chat_app'))

# 1) 点「💬 聊天」→ chatAppRequested 信号
got = []
w.chatAppRequested.connect(lambda: got.append(1))
w.btn_chat_app.click()
app.processEvents()
chk('聊天按钮发信号', len(got) == 1)

# 2) 发送 → sendRequested + 输入条隐藏（快速提问模式）
got_send = []
w.sendRequested.connect(lambda t: got_send.append(t))
w.input.setText(' 快速提问 ')
w._send()
app.processEvents()
chk('发送信号带文本', got_send == ['快速提问'])
chk('发送后自动收起', not w.isVisible())

# 3) 清理按钮 → clearRequested
w.show()
got_clr = []
w.clearRequested.connect(lambda: got_clr.append(1))
w.btn_clear_input.click()
app.processEvents()
chk('清理按钮发信号', len(got_clr) == 1)

print('ALL PASS: %d checks' % ok)