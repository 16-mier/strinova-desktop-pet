# -*- coding: utf-8 -*-
"""设置面板导航式布局冒烟：导航6项/切页/各页控件可见性"""
import os
import sys
import types
import tempfile
import json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QTimer

app = QApplication([])
import ai_chat
import settings_panel

_TMP = tempfile.mkdtemp(prefix='nav_smoke_')


def _lc():
    try:
        with open(os.path.join(_TMP, 'c.json'), encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _sc(c):
    with open(os.path.join(_TMP, 'c.json'), 'w', encoding='utf-8') as f:
        json.dump(c, f, ensure_ascii=False, indent=2)


pm = types.ModuleType('pm')
pm.load_config = _lc
pm.save_config = _sc
pm.base_dir = lambda: _TMP
ai_chat.bind_pet_module(pm)


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
        return {}


p = Pet()
panel = settings_panel.SettingsPanel(p)
panel.show()
app.processEvents()
ok = []

# 1) 导航 7 项
ok.append(('导航7项', panel.nav.count() == 7))

# 2) 每页控件存在
pages = [
    ('🤖 AI 对话', ['chk_ai_enabled', 'ed_ai_base', 'cmb_ai_model']),
    ('🗣 语音朗读', ['chk_ai_tts', 'cmb_tts_engine', 'sld_tts_volume', 'ed_tts_local_base']),
    ('👤 形象角色', ['role_list', 'lbl_cur_role', 'sld_size', 'chk_auto_facing']),
    ('🎵 语音音频', ['audio_list', 'cmb_voice_src', 'btn_bind']),
    ('🎧 播放设备', ['cmb_bind', 'cmb_self']),
    ('⌨ 快捷键 / 开麦', ['chk_hotkeys', 'chk_numpad', 'chk_ptt', 'cmb_pttkey']),
    ('🎮 游戏设置', ['chk_meow', 'ed_meow_word']),
]
for title, ctrls in pages:
    idx = next(i for i in range(panel.nav.count())
               if panel.nav.item(i).text() == title)
    panel.nav.setCurrentRow(idx)
    app.processEvents()
    vis = all(getattr(panel, c).isVisible() for c in ctrls)
    ok.append(('%s 页控件可见' % title, vis and panel.stack.currentIndex() == idx))

# 3) 切页互斥：切到角色页后 AI 页/朗读页不叠显
ai_page_idx = next(i for i in range(panel.nav.count())
                   if panel.nav.item(i).text() == "🤖 AI 对话")
tts_page_idx = next(i for i in range(panel.nav.count())
                    if panel.nav.item(i).text() == "🗣 语音朗读")
panel.nav.setCurrentRow(tts_page_idx)
app.processEvents()
ok.append(('切到朗读页 TTS 控件可见', panel.chk_ai_tts.isVisible()))
panel.nav.setCurrentRow(ai_page_idx)
app.processEvents()
ok.append(('切回AI页后朗读控件隐藏', not panel.chk_ai_tts.isVisible()))

# 4) 旧折叠方法兼容（跳页）
panel._toggle_ai_page()
app.processEvents()
ok.append(('_toggle_ai_page 跳AI页', panel.stack.currentIndex() == ai_page_idx
           and panel.chk_ai_enabled.isVisible()))
panel._toggle_game_page()
app.processEvents()
game_idx = next(i for i in range(panel.nav.count())
                if panel.nav.item(i).text() == "🎮 游戏设置")
ok.append(('_toggle_game_page 跳游戏页', panel.stack.currentIndex() == game_idx))

# 5) 云端引擎区：切「云端」→ 预设下拉 + API 表单可见；切「本地」隐藏
tts_idx = next(i for i in range(panel.nav.count())
               if panel.nav.item(i).text() == "🗣 语音朗读")
panel.nav.setCurrentRow(tts_idx)
panel.cmb_tts_engine.setCurrentIndex(1)   # cloud
panel._ai_apply_tts_engine(1)
app.processEvents()
ok.append(('云端引擎 → 预设/API可见', panel.cmb_tts_preset.isVisible()
           and panel.api_tts_box.isVisible() and panel.local_tts_box.isVisible() is False))
panel.cmb_tts_engine.setCurrentIndex(0)   # local
panel._ai_apply_tts_engine(0)
app.processEvents()
ok.append(('本地引擎 → 云端区隐藏', not panel.api_tts_box.isVisible()
           and panel.local_tts_box.isVisible()))

for name, cond in ok:
    print(('  PASS ' if cond else '  FAIL ') + name)
    assert cond, name
print('ALL PASS: %d checks' % len(ok))
