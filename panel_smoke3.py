# -*- coding: utf-8 -*-
# panel_smoke3.py —— TTS API 引擎 + 滑块禁滚轮冒烟
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
# 展开 AI 配置区（否则子控件不可见是预期）
panel._toggle_ai_page()
app.processEvents()
assert panel.ai_box.isVisible()

ok = []
# 1. 新控件存在
ok.append(('引擎含 API 项', panel.cmb_ai_tts_mode.findData('api') >= 0))
ok.append(('API 表单控件存在', all(hasattr(panel, n) for n in
          ('ed_tts_api_base', 'ed_tts_api_key', 'ed_tts_api_model',
           'ed_tts_api_voice', 'api_tts_box', 'cloud_voice_box'))))
ok.append(('滑块是 NoWheelSlider', isinstance(panel.sld_size, settings_panel.NoWheelSlider)))

# 2. 默认 cloud 模式 → api_tts_box 隐藏, cloud_voice_box 可见
ok.append(('默认cloud: api表单隐藏', not panel.api_tts_box.isVisible()))
ok.append(('默认cloud: 云端音色可见', panel.cloud_voice_box.isVisible()))

# 3. 切到 api → api 表单可见、云端音色隐藏
panel.cmb_ai_tts_mode.setCurrentIndex(panel.cmb_ai_tts_mode.findData('api'))
app.processEvents()
ok.append(('切api: api表单可见', panel.api_tts_box.isVisible()))
ok.append(('切api: 云端音色隐藏', not panel.cloud_voice_box.isVisible()))
ok.append(('切api: 配置已存 mode=api', p.ai.cfg().get('tts_mode') == 'api'))

# 4. 填 API 字段并保存
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

# 5. 缺字段测试 → 提示不崩
panel.ed_tts_api_base.setText('')
panel._ai_test_tts_api()
app.processEvents()
ok.append(('缺字段测试有提示', '请先填' in panel.lbl_tts_api_status.text()))

# 6. 滑块滚轮事件忽略
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtCore import QPointF, QPoint
before = panel.sld_size.value()
# 构造真实滚轮事件（angleDelta 向上滚动 = 数值增加方向）
ev = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, -120),
                 Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                 Qt.ScrollPhase.NoScrollPhase, False)
app.sendEvent(panel.sld_size, ev)
app.processEvents()
after = panel.sld_size.value()
ok.append(('滑块滚轮被忽略', before == after))

# 7. 引擎切回 cloud 恢复
panel.cmb_ai_tts_mode.setCurrentIndex(panel.cmb_ai_tts_mode.findData('cloud'))
app.processEvents()
ok.append(('切回cloud: api表单隐藏', not panel.api_tts_box.isVisible()))

# 8. refresh_all 后仍一致
panel.refresh_all()
app.processEvents()
ok.append(('refresh后cloud: api隐藏', not panel.api_tts_box.isVisible()))


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
