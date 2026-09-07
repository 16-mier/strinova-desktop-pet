# -*- coding: utf-8 -*-
# bubble_smoke.py —— 迷你输入条 + 思考动画 + 逐字蹦字冒烟
import os
import sys
import types
import tempfile
import json

ROOT = r"C:\Users\mier\Desktop\deepseek work\dsh-desktop-pet"
sys.path.insert(0, ROOT)
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QRect, QTimer
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtCore import Qt

app = QApplication([])
import ai_chat

_TMP = tempfile.mkdtemp(prefix='bubble_smoke_')


def _lc():
    try:
        with open(os.path.join(_TMP, 'c.json'), encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _sc(c):
    with open(os.path.join(_TMP, 'c.json'), 'w', encoding='utf-8') as f:
        json.dump(c, f, ensure_ascii=False)


pm = types.ModuleType('pm')
pm.load_config = _lc
pm.save_config = _sc
pm.base_dir = lambda: _TMP
ai_chat.bind_pet_module(pm)
ai_chat._save_ai_cfg(enabled=True, tts_enabled=False)


class Pet:
    def __init__(self):
        self.ai = ai_chat.AiChatManager(self)
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
        return _lc()

    def save_config(self, c):
        _sc(c)

    def frameGeometry(self):
        return QRect(600, 400, 200, 200)

    def update(self):
        pass


p = Pet()
mgr = p.ai
ok = []

# 1. 打开迷你条
mgr.open_chat()
app.processEvents()
ok.append(('聊天窗创建且可见', mgr._chat is not None and mgr._chat.isVisible()))
ok.append(('聊天窗为可视化消息窗(宽470高340)', mgr._chat.width() == 470 and mgr._chat.height() == 340))
ok.append(('有关闭按钮(自绘)', hasattr(mgr._chat, 'btn_x')))
ok.append(('无大历史框', not hasattr(mgr._chat, 'history')))
ok.append(('有消息流 browser', hasattr(mgr._chat, 'browser')))

# 2. 思考动画
mgr._show_thinking()
app.processEvents()
ok.append(('思考气泡可见', mgr._bubble is not None and mgr._bubble.isVisible()))
ok.append(('思考定时器在跑', mgr._bubble._think_timer.isActive()))

# 3. 逐字蹦字
text = "你好呀，这是一段用来测试逐字蹦字效果的文字，速度要快一点！"
mgr._get_bubble().show_text(text)
app.processEvents()
ok.append(('蹦字前只显示部分', mgr._bubble._shown() != text
           or mgr._bubble._type_pos < len(text)))
ok.append(('蹦字定时器在跑', mgr._bubble._type_timer.isActive()))


def _check_done():
    ok.append(('蹦字最终完整', mgr._bubble._shown() == text))
    ok.append(('蹦字定时器停', not mgr._bubble._type_timer.isActive()))
    ok.append(('跟随定时器在跑', mgr._bubble._follow.isActive()))
    # 测试跟随：移动宠物 → 气泡跟着挪
    p.frameGeometry = lambda: QRect(700, 500, 200, 200)
    app.processEvents()
    import time
    time.sleep(0.15)
    app.processEvents()
    ok.append(('气泡跟随桌宠移动', mgr._bubble.x() != 600 or mgr._bubble.y() != 400))
    # 4. Esc 关闭迷你条
    ev = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape,
                   Qt.KeyboardModifier.NoModifier)
    mgr._chat.keyPressEvent(ev)
    app.processEvents()
    ok.append(('Esc 关闭迷你条', not mgr._chat.isVisible()))
    print("=== BUBBLE SMOKE ===")
    for n, r in ok:
        print(("  PASS " if r else "  FAIL ") + n)
    if all(r for _, r in ok):
        print("ALL PASS ✅")
        app.quit()
    else:
        print("SOME FAILED ❌")
        app.exit(1)


# 给蹦字足够时间（文本 ~30 字 * 18ms = 540ms）
QTimer.singleShot(2500, _check_done)
app.exec()
