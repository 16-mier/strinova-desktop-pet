# -*- coding: utf-8 -*-
# panel_smoke2.py —— 重构后完整冒烟：AI 入口折叠 / 模型自动检测 / 提示词编辑 / TTS 依赖联动
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

app = QApplication([])
import ai_chat
import settings_panel

_TMP = tempfile.mkdtemp(prefix='panel_smoke_')


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
        return _lc()

    def save_config(self, c):
        _sc(c)

    def frameGeometry(self):
        return QRect(600, 400, 200, 200)

    def update(self):
        pass


p = Pet()
panel = settings_panel.SettingsPanel(p)
panel.show()
app.processEvents()

ok = []
# 1. AI 入口在滚动区最上面（btn_ai_head 存在）
ok.append(('AI 折叠头存在', hasattr(panel, 'btn_ai_head')))

# 2. 默认收起
ok.append(('默认收起', not panel.ai_box.isVisible()))

# 3. 点开
panel._toggle_ai_page()
app.processEvents()
ok.append(('点开可见', panel.ai_box.isVisible()))

# 4. 再点收起
panel._toggle_ai_page()
app.processEvents()
ok.append(('再点收起', not panel.ai_box.isVisible()))
panel._toggle_ai_page()   # 重新展开
app.processEvents()

# 5. 模型下拉 editable 存在
ok.append(('模型下拉存在', hasattr(panel, 'cmb_ai_model')))

# 6. TTS 依附：AI 默认关 → tts 置灰
ok.append(('AI关→TTS置灰', not panel.chk_ai_tts.isEnabled()))

# 7. 开 AI → TTS 可用
panel.chk_ai_enabled.setChecked(True)
app.processEvents()
ok.append(('开AI→TTS可用', panel.chk_ai_tts.isEnabled()))

# 8. 勾 TTS → 生效
panel.chk_ai_tts.setChecked(True)
app.processEvents()
ok.append(('TTS勾选生效', panel.chk_ai_tts.isChecked() and bool(p.ai.cfg().get('tts_enabled'))))

# 9. 关 AI → TTS 自动取消+置灰
panel.chk_ai_enabled.setChecked(False)
app.processEvents()
ok.append(('关AI→TTS自动关+置灰',
           not panel.chk_ai_tts.isChecked() and not panel.chk_ai_tts.isEnabled()
           and not bool(p.ai.cfg().get('tts_enabled'))))

# 10. 系统提示词编辑 → 存配置
panel.chk_ai_enabled.setChecked(True)
panel.ed_ai_sysprompt.setPlainText("你是我的专属语音助手")
app.processEvents()
ok.append(('系统提示词已存', p.ai.cfg().get('system_prompt') == '你是我的专属语音助手'))

# 11. TTS 提示词编辑 → 存配置
panel.ed_ai_ttsprompt.setPlainText("请把回答改写成朗读稿")
app.processEvents()
ok.append(('TTS提示词已存', p.ai.cfg().get('tts_prompt') == '请把回答改写成朗读稿'))

# 12. 模型名选择 → set_server 保存
panel.cmb_ai_model.setCurrentText('deepseek-chat')
panel._ai_save()
app.processEvents()
ok.append(('模型保存', p.ai.cfg().get('model') == 'deepseek-chat'))

# 13. 刷新模型（假 key → 显示失败提示不崩）
panel.ed_ai_base.setText('https://api.deepseek.com/v1')
panel.ed_ai_key.setText('sk-invalid')
panel._ai_auto_fetch()


def _after_wait():
    ok.append(('自动检测失败提示不崩', '失败' in panel.lbl_ai_status.text()))
    print("=== PANEL SMOKE2 ===")
    for name, res in ok:
        print(("  PASS " if res else "  FAIL ") + name)
    if all(r for _, r in ok):
        print("ALL PASS ✅")
        app.quit()
    else:
        print("SOME FAILED ❌")
        app.exit(1)


QTimer.singleShot(4000, _after_wait)
app.exec()
