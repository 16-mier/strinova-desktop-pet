# -*- coding: utf-8 -*-
"""端到端验证 rewrite_for_tts_async：真实 AI 配置下把大白话优化成朗读稿+情绪"""
import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault('PYTHONIOENCODING', 'utf-8')

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer

app = QApplication([])
import ai_chat

pm = types.ModuleType('pm')
pm.base_dir = lambda: r'C:\Users\mier\Desktop\卡丘简易桌宠数据'
import json


def _lc():
    try:
        with open(os.path.join(pm.base_dir(), 'pet_config.json'), encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


pm.load_config = _lc
pm.save_config = lambda c: None
ai_chat.bind_pet_module(pm)


class Pet:
    def __init__(self):
        self._pet_size = 200
        self.role = '星绘'
        self._voice_source = 'role'
        self._audio_hotkeys = {}
        self._hotkeys_enabled = True
        self._numpad_enabled = False
        self._auto_ptt = False
        self._ptt_key_name = 'V'
        self._bind_device = ''
        self._self_device = ''
        self._toast_text = None

    def load_config(self):
        return {}


ai = ai_chat.AiChatManager(Pet())
result = {}


def on_done(speak, emo, err):
    result['speak'] = speak
    result['emo'] = emo
    result['err'] = err
    print('--- 改写结果 ---')
    print('朗读稿:', speak)
    print('情绪 :', emo)
    print('错误 :', err or '无')
    app.quit()


print('原文: 门快开了 赶紧走 别磨蹭')
ai.rewrite_for_tts_async('门快开了 赶紧走 别磨蹭', on_done)
QTimer.singleShot(90000, app.quit)
app.exec()
assert result.get('speak'), '未拿到朗读稿'
assert result.get('emo'), '未拿到情绪指令'
print('END2END PASS')
