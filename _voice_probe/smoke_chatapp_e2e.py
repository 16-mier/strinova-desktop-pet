# -*- coding: utf-8 -*-
"""端到端：open_chat_app 打开聊天窗口 + 真实角色列表 + 回复进聊天窗"""
import os
import sys
import types
import json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QRect, QTimer

app = QApplication([])
import ai_chat

DATA = r'C:\Users\mier\Desktop\卡丘简易桌宠数据'


def _lc():
    try:
        with open(os.path.join(DATA, 'pet_config.json'), encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


pm = types.ModuleType('pm')
pm.load_config = _lc
pm.save_config = lambda c: None
pm.base_dir = lambda: DATA
ai_chat.bind_pet_module(pm)


class FakePet:
    roles = ['乌尔比诺/星绘', '乌尔比诺/白墨', '欧泊/米雪儿', '剪刀手/令']
    role = '乌尔比诺/星绘'
    _pet_size = 200
    _voice_source = 'role'
    _audio_hotkeys = {}
    _hotkeys_enabled = True
    _numpad_enabled = False
    _auto_ptt = False
    _ptt_key_name = 'V'
    _bind_device = ''
    _self_device = ''
    _toast_text = None

    def __init__(self):
        self.ai = None

    def frameGeometry(self):
        return QRect(600, 500, 200, 200)

    def update(self):
        pass


pet = FakePet()
mgr = ai_chat.AiChatManager(pet)
pet.ai = mgr

# 1) 打开聊天窗口
mgr.open_chat_app()
import time
time.sleep(0.3)
app.processEvents()
w = mgr._app
print('app created:', w is not None)
print('app visible:', w.isVisible())
print('active:', mgr._chat_app_active())
print('title:', w.lbl_title.text())
print('role items:', w.role_list.count())

# 2) 角色列表真实填充（阵营分组）
import pet as pet_mod
print('roles in list:', w.role_list.count() > 3)

# 3) 消息改道：回复进聊天窗而不是气泡
mgr._messages = [{'role': 'user', 'content': '测试', 'ts': '10:00'}]
mgr._on_ai_done('你好呀，这是端到端测试回复～', '')
time.sleep(0.2)
app.processEvents()
print('reply in app:', '端到端测试回复' in w.browser.toPlainText())
print('bubble not used:', mgr._bubble is None or not mgr._bubble.isVisible())

print('E2E DONE')