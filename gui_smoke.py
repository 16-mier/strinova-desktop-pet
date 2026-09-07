# -*- coding: utf-8 -*-
# gui_smoke.py —— GUI 冒烟：ChatWindow 构造/发消息/AI 回复/TTS 合成（需真实 API key 演示，
# 无 key 则验证到「缺 key 提示」为止；验证 TTS 用直调合成）
import os
import sys
import time

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer
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
        from PyQt6.QtCore import QRect
        return QRect(600, 400, 200, 200)
    def update(self):
        pass

app = QApplication(sys.argv)
pet = FakePet()
mgr = ai.AiChatManager(pet)
print("manager ok; enabled =", mgr.enabled())

# 打开聊天窗
mgr.open_chat()
print("chat opened:", mgr._chat is not None)

# 模拟发消息（无 key → 应走缺 key 提示，不崩）
mgr._chat.input.setText("你好")
mgr._on_send("你好")
print("sent without key; err appended (若补 key 需真实 API)")

results = {}
def _on_bubble_ok():
    results['bubble'] = mgr._bubble is not None and mgr._bubble.isVisible()

# 手动触发一次气泡 + TTS（用直调，不依赖 key）
def _finish():
    mgr._on_ai_done("你好呀，我是你的 AI 桌宠小伙伴～", "")
    QTimer.singleShot(400, lambda: (_on_bubble_ok(), print("bubble visible:", results.get('bubble')), app.quit()))

QTimer.singleShot(1200, _finish)
QTimer.singleShot(15000, app.quit)  # 兜底超时
app.exec()
print("gui smoke done")