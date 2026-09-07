# -*- coding: utf-8 -*-
# session_smoke.py —— 本轮冒烟：多会话上下文 + 可视化聊天窗 + 口语化提示词
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

# 1. 会话初始
ck("初始会话名含默认会话", '默认会话' in mgr.session_names())
ck("初始当前=默认会话", mgr.current_session() == '默认会话')

# 2. 新建会话并隔离
n1 = mgr.new_session()
ck("新建会话非空且为当前", n1 and mgr.current_session() == n1)
mgr._messages.append({'role': 'user', 'content': '消息A', 'ts': '10:00'})
ck("新建会话有1条", len(mgr._messages) == 1)
mgr.switch_session('默认会话')
ck("切回默认后为空", len(mgr._messages) == 0 and mgr.current_session() == '默认会话')
mgr.switch_session(n1)
ck("切回会话1 内容保留", len(mgr._messages) == 1 and mgr._messages[0]['content'] == '消息A')

# 3. 清理只清当前会话，不删会话
mgr.clear_context()
ck("清理后当前会话空", len(mgr._messages) == 0)
ck("清理后会话仍在", n1 in mgr.session_names())
mgr.switch_session('默认会话')
ck("默认会话仍存在", mgr.current_session() == '默认会话')

# 4. 可视化聊天窗
mgr.open_chat()
cw = mgr._chat
ck("聊天窗有会话下拉", hasattr(cw, 'combo_session'))
ck("聊天窗有消息流 browser", hasattr(cw, 'browser'))
ck("聊天窗保留输入框", hasattr(cw, 'input') and hasattr(cw, 'btn_send'))
ck("聊天窗有清理/记录按钮", hasattr(cw, 'btn_clear') and hasattr(cw, 'btn_history'))
ck("聊天窗有新建会话按钮", hasattr(cw, 'btn_new_sess'))
cw.set_sessions(mgr.session_names(), mgr.current_session())
ck("下拉含两个会话", cw.combo_session.count() == 2)

# 5. 消息流渲染（用户右/AI 左已由 _msg_html 保证）
cw.set_content([
    {'role': 'user', 'content': '用户消息XYZ', 'ts': '10:00:01'},
    {'role': 'assistant', 'content': 'AI 回复ABC', 'ts': '10:00:02'},
], mgr.system_prompt())
# 5b. 聊天窗用 plain-right 样式：无气泡背景、文字靠右
plain = cw.browser.toPlainText()
ck("消息流含用户消息", '用户消息XYZ' in plain)
ck("消息流含AI回复", 'AI 回复ABC' in plain)
# 用户与 AI 消息都靠右（新设计：对话内容在右边）
from PyQt6.QtCore import Qt as _Qt
doc = cw.browser.document()
_ok_u = _ok_a = False
for i in range(doc.blockCount()):
    b = doc.findBlockByNumber(i)
    txt = b.text()
    al = b.blockFormat().alignment()
    if '用户消息XYZ' in txt and al == _Qt.AlignmentFlag.AlignRight:
        _ok_u = True
    if 'AI 回复ABC' in txt and al == _Qt.AlignmentFlag.AlignRight:
        _ok_a = True
ck("消息流用户块右对齐", _ok_u)
ck("消息流AI块也右对齐(对话内容在右边)", _ok_a)
# 无气泡背景：检查渲染 HTML 无内联 background 色块样式（span 不带 background）
html_out = cw.browser.toHtml().lower()
ck("消息流无气泡背景块", 'background:#1e3a5f' not in html_out and 'background:#2a2e3d' not in html_out)

# 6. 口语化规则强制追加
sp = mgr.system_prompt()
ck("系统提示词含口语规则", '口语自然' in sp and '嘻嘻' in sp)
ck("系统提示词含基础人设", '桌宠' in sp)

# 7. TTS 提示词强化
ttp = ai.AiChatManager.default_tts_prompt()
ck("TTS 提示词含口语/去拟声规则", '嘻嘻' in ttp and '朗读' in ttp and '情绪' in ttp)

# 8. 删除会话
mgr.new_session('临时会话X')
mgr._messages.append({'role': 'user', 'content': '待删', 'ts': 'x'})
ck("删除前存在 临时会话X", '临时会话X' in mgr.session_names())
ok_del, msg = mgr.delete_session('临时会话X')
ck("删除会话成功", ok_del and '临时会话X' not in mgr.session_names())
# 删除当前会话会自动切到相邻
n_keep = mgr.new_session('保留会话Y')
mgr._messages.append({'role': 'user', 'content': 'keep', 'ts': 'y'})
mgr.switch_session('默认会话')
mgr.switch_session(n_keep)
cur_before = mgr.current_session()
mgr.delete_session('保留会话Y')
ck("删除当前会话后自动切换", mgr.current_session() != '保留会话Y')
ck("其它会话内容未受影响", '默认会话' in mgr.session_names())
# 删除全部 → 自动重建默认
for s in list(mgr.session_names()):
    mgr.delete_session(s)
ck("删除全部后重建默认会话", '默认会话' in mgr.session_names() and mgr.current_session() == '默认会话')

print("\n==== 结果 ====")
fails = [n for n, ok in checks if not ok]
print("共 %d 项，失败 %d 项" % (len(checks), len(fails)))
if fails:
    for n in fails:
        print("  FAIL:", n)
    sys.exit(1)
print("ALL PASS")
app.quit()
