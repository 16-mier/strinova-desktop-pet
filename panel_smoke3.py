# -*- coding: utf-8 -*-
# panel_smoke3.py —— TTS API 表单 + 滑块禁滚轮冒烟
# 说明：面板 TTS 已精简为「唯一 API 地址引擎」（历史 cloud/local/api 引擎下拉已移除），
#       故本测试聚焦当前真实存在的控件：api_tts_box 表单 / 填字段保存 / 缺字段提示 / 滑块防滚轮。
import os
import sys
import types
import tempfile
import json

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QRect, QTimer, QEvent

app = QApplication([])
import ai_chat
import settings_panel

_TMP = tempfile.mkdtemp(prefix='panel_smoke3_')


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
# 1. TTS API 表单控件存在（当前唯一朗读引擎）
ok.append(('API 表单控件存在', all(hasattr(panel, n) for n in
          ('ed_tts_api_base', 'ed_tts_api_key', 'ed_tts_api_model',
           'ed_tts_api_voice', 'api_tts_box'))))
ok.append(('克隆三件套存在', all(hasattr(panel, n) for n in
          ('ed_tts_api_ref', 'ed_tts_api_ref_text', 'ed_tts_api_instr'))))
ok.append(('模型版本下拉存在', hasattr(panel, 'cmb_tts_model_kind')))
ok.append(('滑块是 NoWheelSlider', isinstance(panel.sld_size, settings_panel.NoWheelSlider)))

# 2. 展开 AI 配置区后 api_tts_box 可见（AI 区默认折叠，展开是预期交互）
panel._toggle_ai_page()
app.processEvents()
ok.append(('展开AI后 api_tts_box 可见', panel.api_tts_box.isVisible()))

# 3. 填 API 字段并保存 → 配置持久化
panel.ed_tts_api_base.setText('https://tts.example.com/v1')
panel.ed_tts_api_key.setText('sk-tts-test')
panel.ed_tts_api_model.setText('tts-1')
panel.ed_tts_api_voice.setText('alloy')
panel._ai_apply_tts_api()
app.processEvents()
c = p.ai.cfg()
ok.append(('API TTS 配置保存', c.get('tts_api_base') == 'https://tts.example.com/v1'
           and c.get('tts_api_key') == 'sk-tts-test'
           and c.get('tts_api_model') == 'tts-1'
           and c.get('tts_api_voice') == 'alloy'))

# 4. 缺字段测试 → 提示不崩
panel.ed_tts_api_base.setText('')
panel._ai_test_tts_api()
app.processEvents()
ok.append(('缺字段测试有提示', '请先填' in panel.lbl_tts_api_status.text()))

# 5. 滑块滚轮事件忽略
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtCore import QPointF, QPoint
before = panel.sld_size.value()
ev = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, -120),
                 Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                 Qt.ScrollPhase.NoScrollPhase, False)
app.sendEvent(panel.sld_size, ev)
app.processEvents()
after = panel.sld_size.value()
ok.append(('滑块滚轮被忽略', before == after))

# 6. refresh_all 后表单仍在
panel.refresh_all()
app.processEvents()
ok.append(('refresh后面板可再用', hasattr(panel, 'ed_tts_api_base')))


def _finish():
    print("=== PANEL SMOKE3 ===")
    for name, res in ok:
        print(("  PASS " if res else "  FAIL ") + name)
    if all(r for _, r in ok):
        print("ALL PASS ✅")
        app.quit()
    else:
        print("SOME FAILED ❌")
        app.exit(1)


QTimer.singleShot(300, _finish)
app.exec()