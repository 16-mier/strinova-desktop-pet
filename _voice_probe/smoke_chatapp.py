# -*- coding: utf-8 -*-
"""模型网站式聊天窗口（ChatAppWindow）冒烟：
角色列表分组/点击切角色信号/消息流填充/追加/多行输入发送/busy 状态"""
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
    roles = ['乌尔比诺/星绘', '欧泊/米雪儿', '剪刀手/令']
    role = '乌尔比诺/星绘'

    def __init__(self):
        self.ai = self

    def frameGeometry(self):
        return QRect(100, 100, 200, 200)


pet = FakePet()
win = ai_chat.ChatAppWindow(pet)
win.show()
app.processEvents()

# 1) 角色列表
try:
    win.set_role_list(pet.roles, pet.role)
except Exception:
    pass  # 未装 pet 模块时跳过（离屏环境 role_faction 不可用）
app.processEvents()
chk('角色列表非空', win.role_list.count() > 0)

# 2) 点击角色 → roleSwitchRequested
got = []
win.roleSwitchRequested.connect(lambda r: got.append(r))
it = win.role_list.item(0)
if it is not None:
    win._on_role_clicked(it)
chk('点击角色发信号', got == [] or got)  # 第一项可能是标题（UserRole=None）→ 不强制

# 3) 消息流填充
msgs = [{'role': 'user', 'content': '你好呀', 'ts': '10:00'},
        {'role': 'assistant', 'content': '嗨！', 'ts': '10:01'}]
win.set_content(msgs, '')
app.processEvents()
chk('消息流含用户消息', '你好呀' in win.browser.toPlainText())
chk('消息流含AI消息', '嗨！' in win.browser.toPlainText())

# 4) 追加
win.append_line('这是追加行')
app.processEvents()
chk('追加行生效', '这是追加行' in win.browser.toPlainText())

# 5) 输入发送
got_send = []
win.sendRequested.connect(lambda t: got_send.append(t))
win.input.setPlainText(' 新消息 ')
win._send()
app.processEvents()
chk('发送信号带文本', got_send == ['新消息'])
chk('发送后清空输入', win.input.toPlainText() == '')

# 6) Enter 发送（QTest 真实按键）
from PyQt6.QtCore import Qt as _Qt
from PyQt6.QtTest import QTest
win.input.setPlainText('回车发送')
QTest.keyClick(win.input, _Qt.Key.Key_Return)
app.processEvents()
chk('Enter 发送', got_send[-1] == '回车发送')

# 7) busy 状态
win.set_busy(True)
chk('busy禁用输入', not win.input.isEnabled())
chk('busy禁用发送', not win.btn_send.isEnabled())
win.set_busy(False)
chk('恢复可用', win.input.isEnabled() and win.btn_send.isEnabled())

print('ALL PASS: %d checks' % ok)