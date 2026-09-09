# -*- coding: utf-8 -*-
"""完整聊天窗冒烟：展开/收起/历史填充/追加/发送行为"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QRect
from PyQt6.QtGui import QPixmap

app = QApplication([])
import ai_chat

ok = 0


def chk(name, cond):
    global ok
    assert cond, 'FAIL: ' + name
    ok += 1
    print('  PASS', name)


class FakeAI:
    _messages = [{'role': 'user', 'content': '你好', 'ts': '1'},
                 {'role': 'assistant', 'content': '嗨！', 'ts': '2'}]


class FakePet:
    def __init__(self):
        self.ai = FakeAI()
        self.role = '星绘'

    def frameGeometry(self):
        return QRect(100, 100, 200, 200)


p = FakePet()
w = ai_chat.ChatWindow(p)
w.show()
app.processEvents()

chk('初始收拢高度48', w.height() == ai_chat.ChatWindow.H_USAGE)
chk('初始未展开', not w.is_expanded())

w.toggle_expand()
app.processEvents()
chk('展开后高度560', w.height() == ai_chat.ChatWindow.H_EXPANDED)
chk('展开状态', w.is_expanded())
chk('browser可见', w.browser.isVisible())
chk('browser有历史内容', w.browser.toPlainText() != '')

w.append_line('AI：测试追加行')
app.processEvents()
chk('append_line 生效', '测试追加行' in w.browser.toPlainText())

# 展开态发送：窗口保持可见
w.input.setText('再来一条')
w._send()
app.processEvents()
chk('展开态发送后窗口仍可见', w.isVisible() and w.is_expanded())

w.toggle_expand()
app.processEvents()
chk('收起后高度48', w.height() == ai_chat.ChatWindow.H_USAGE)
chk('收起后browser隐藏', not w.browser.isVisible())

# 收起态发送：窗口自动隐藏（原行为）
w.input.setText('快速提问')
w._send()
app.processEvents()
chk('收起态发送后窗口隐藏', not w.isVisible())

print('ALL PASS: %d checks' % ok)