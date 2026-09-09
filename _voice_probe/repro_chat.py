# -*- coding: utf-8 -*-
"""复现：聊天窗（输入条）弹出 + 展开按钮 是否正常工作（真实 GUI）"""
import os
import sys

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QRect, QTimer

import ai_chat as ai


class FakePet:
    _pet_size = 200
    role = "星绘"
    _voice_source = 'role'
    _audio_hotkeys = {}
    _hotkeys_enabled = True
    _numpad_enabled = False
    _auto_ptt = False
    _ptt_key_name = 'V'
    _bind_device = ''
    _self_device = ''
    _toast_text = None

    def load_config(self):
        return {}

    def save_config(self, c):
        pass

    def base_dir(self):
        return ROOT

    def frameGeometry(self):
        return QRect(600, 500, 200, 200)

    def update(self):
        pass


app = QApplication(sys.argv)
pet = FakePet()
mgr = ai.AiChatManager(pet)
print('enabled =', mgr.enabled())

mgr.open_chat()
import time
time.sleep(0.3)
cw = mgr._chat
print('chat created:', cw is not None)
print('chat visible:', cw.isVisible())
print('chat geometry:', cw.geometry().getRect() if cw else None)
print('chat height:', cw.height() if cw else None)

# 模拟悬停进入
mgr.chat_bar_on_enter()
time.sleep(0.3)
print('after enter -> visible:', cw.isVisible(), 'height:', cw.height())

# 点展开按钮
if cw is not None:
    print('--- 直接调用 toggle_expand ---')
    cw.toggle_expand()
    time.sleep(0.3)
    print('direct -> height:', cw.height(), 'expanded:', cw.is_expanded())

    print('--- 收起后点按钮 ---')
    cw.toggle_expand()
    time.sleep(0.2)
    print('signals blocked:', cw.btn_expand.signalsBlocked())
    print('enabled:', cw.btn_expand.isEnabled(), 'visible:', cw.btn_expand.isVisible())
    fired = []
    cw.btn_expand.clicked.connect(lambda: fired.append(1))
    cw.btn_expand.click()
    time.sleep(0.2)
    print('clicked fired times:', len(fired))
    print('click -> height:', cw.height(), 'expanded:', cw.is_expanded(),
          'browser visible:', cw.browser.isVisible())
    print('btn text:', cw.btn_expand.text())

print('REPRO DONE')