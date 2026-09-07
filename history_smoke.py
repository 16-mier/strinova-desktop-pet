# -*- coding: utf-8 -*-
# history_smoke.py —— 完整对话上下文窗口冒烟
import os
import sys

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QRect
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
        return {'ai': {'enabled': True, 'tts_enabled': False,
                       'base_url': 'x', 'api_key': 'x', 'model': 'x'}}

    def save_config(self, c):
        pass

    def base_dir(self):
        return ROOT

    def frameGeometry(self):
        return QRect(600, 400, 200, 200)

    def update(self):
        pass


checks = []
def ck(name, cond):
    checks.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name)


app = QApplication(sys.argv)
pet = FakePet()
mgr = ai.AiChatManager(pet)

# 1. open chat (输入条) -> manager 存在
mgr.open_chat()
cw = mgr._chat
ck("chat window created", cw is not None)
ck("input bar visible", cw.isVisible())
ck("has input", hasattr(cw, 'input'))
ck("无消息流 browser", cw.browser is None)

# 2. seed history messages with ts
mgr._messages = [
    {'role': 'user', 'content': 'ni hao ya', 'ts': '10:00:01'},
    {'role': 'assistant', 'content': 'ni hao! wo shi xinghui', 'ts': '10:00:03'},
    {'role': 'user', 'content': 'bang wo xie shi', 'ts': '10:01:00'},
    {'role': 'assistant', 'content': 'hao de, chun feng shi li bu ru ni', 'ts': '10:01:08'},
]

# 3. 打开完整记录（右键菜单的 show_history，等价于旧记录按钮）
mgr.show_history()
ck("manager created history window", mgr._history is not None)
hw = mgr._history
ck("history window visible", hw.isVisible())
ck("count label = 4", hw.lbl_count.text() == "4 条")

plain = hw.browser.toPlainText()
html_txt = hw.browser.toHtml()
ck("plain contains user msg", "ni hao ya" in plain)
ck("plain contains ai msg", "chun feng" in plain)
ck("html has <br>", "<br />" in html_txt or "<br>" in html_txt)
ck("plain contains timestamp", "10:01:08" in plain)

meta = hw.lbl_meta.text()
ck("meta has user count", "用户 2 条" in meta)
ck("meta has ai count", "AI 2 条" in meta)

# 4. empty session hint
mgr._messages = []
hw.show_history([], mgr.system_prompt())
ck("empty shows hint", "暂无对话内容" in hw.browser.toPlainText())

# 5. copy all
try:
    hw._copy_all()
    clip = QApplication.clipboard().text()
    ck("copy all works", len(clip) > 0)
except Exception as e:
    print("copy err:", e)
    ck("copy all works", False)

# 6. html escape injection
import html
safe = html.escape('<script>alert(1)</script>')
ck("html escaped", '<script>' not in safe and '&lt;' in safe)

# ===== 7. 跟随桌宠 + 实时刷新 =====
# 重新打开历史窗（带消息）
mgr._messages = [
    {'role': 'user', 'content': 'msg one', 'ts': '10:00:01'},
    {'role': 'assistant', 'content': 'reply one', 'ts': '10:00:02'},
]
hw.show_history(mgr._messages, mgr.system_prompt())
hw.show()
mgr._history = hw
hw._start_follow()
app.processEvents()
ck("follow timer running", hw._follow.isActive())

# 记录初始位置，模拟桌宠从 (600,400) 移到 (700,500)
pos0 = hw.pos()
hw._follow_offset = hw.pos() - pet.frameGeometry().topLeft()
# 模拟 pet.frameGeometry 改变
class _Pet2:
    role = 'xinghui'
    def frameGeometry(self):
        return QRect(700, 500, 200, 200)
    def load_config(self): return {}
    def save_config(self, c): pass
    def base_dir(self): return '.'
hw._pet = _Pet2()
hw._follow_pet()   # 手动触发一次跟移
app.processEvents()
pos1 = hw.pos()
ck("history follows pet move (x changed)", pos1.x() == pos0.x() + 100 and pos1.y() == pos0.y() + 100)
ck("follow continues after move", hw._follow.isActive())

# 实时刷新：历史窗开着时往 _messages 加消息再调刷新
mgr._messages.append({'role': 'user', 'content': 'brand new q', 'ts': '10:02:00'})
mgr._refresh_history_if_open()
ck("refresh adds new msg", "brand new q" in hw.browser.toPlainText())
mgr._messages.append({'role': 'assistant', 'content': 'brand new a', 'ts': '10:02:01'})
mgr._refresh_history_if_open()
ck("refresh adds new ai reply", "brand new a" in hw.browser.toPlainText())

# 清理后刷新 → 空提示
mgr._messages = []
mgr._refresh_history_if_open()
ck("refresh after clear shows empty", "暂无对话内容" in hw.browser.toPlainText())
ck("follow stopped after hide", (hw.hide(), not hw._follow.isActive())[1])

# 恢复 pet 供后续（无）

print("\n==== results ====")
fails = [n for n, ok in checks if not ok]
print("total %d, failed %d" % (len(checks), len(fails)))
if fails:
    for n in fails:
        print("  FAIL:", n)
    sys.exit(1)
print("ALL PASS")
app.quit()
