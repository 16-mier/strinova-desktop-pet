# -*- coding: utf-8 -*-
# session_smoke.py —— 冒烟：每角色独立会话（磁盘持久化/只删不建） + 可视化聊天窗 + 口语化提示词
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
    def assets_dir(self):
        return os.path.join(ROOT, 'assets')
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

# 1. 会话初始：无默认会话（改为角色会话体系）
ck("初始无默认会话", '默认会话' not in mgr.session_names())

# 2. 切角色自动建角色会话 + 隔离
mgr.switch_to_role('欧泊/米雪儿')
ck("切米雪儿→角色会话", mgr.current_session() == '角色:米雪儿')
mgr._messages.append({'role': 'user', 'content': '米雪儿消息', 'ts': 't'})
ck("会话消息已入", len(mgr._messages) == 1)
ck("会话名含角色前缀", all(s.startswith('角色:') for s in mgr.session_names()))
# 切星绘 → 独立空
mgr.switch_to_role('乌尔比诺/星绘')
ck("切星绘独立空会话", mgr.current_session() == '角色:星绘' and len(mgr._messages) == 0)
# 切回米雪儿 → 上下文保留
mgr.switch_to_role('欧泊/米雪儿')
ck("切回米雪儿上下文保留", len(mgr._messages) == 1)

# 3. 不可新建（只删不建）
r = mgr.new_session('临时会话X')
ck("禁止新建会话", r[0] is False)

# 4. 删除（清空）会话：角色仍在、切回自动空
wd = mgr.delete_session('角色:米雪儿')
ck("清空米雪儿会话成功", wd[0] and len(mgr._messages) == 0)
ck("角色会话仍存在(只清空不删角色)", '角色:米雪儿' in mgr.session_names())
mgr.switch_to_role('乌尔比诺/星绘')
mgr.switch_to_role('欧泊/米雪儿')
ck("切回后为空(自动重建)", mgr.current_session() == '角色:米雪儿' and len(mgr._messages) == 0)

# 5. 世界书注入（角色世界书常驻）
mgr.switch_to_role('欧泊/米雪儿')
mgr._load_world_book()
hits = mgr._world_entries_for('你好')
ck("角色世界书注入非空", len(hits) > 0)

# 6. 聊天窗构建（可视化控件存在）
chat = ai.ChatWindow(pet)
ck("聊天窗有会话下拉", hasattr(chat, 'combo_session'))
ck("聊天窗有删除按钮", hasattr(chat, 'btn_del_sess'))
chat.set_sessions(['角色:a', '角色:b'], '角色:a')
ck("set_sessions 填充", chat.combo_session.count() == 2)
cc = mgr.cfg
mgr_cfg_ok = callable(cc) if hasattr(mgr, 'cfg') else False
# 7. TTS 提示词
ttp = ai.AiChatManager.default_tts_prompt()
ck("TTS 提示词含口语规则", '朗读' in ttp and '情绪' in ttp)

# 8. 延迟后缀
mgr._last_delay = {'api': 1234.5, 'tts': 567.8}
s = mgr._delay_suffix()
ck("延迟后缀含 LLM/TTS", 'LLM' in s and 'TTS' in s)

# 清理测试上下文文件
try:
    for f in os.listdir(os.path.join(ROOT, 'contexts')):
        os.remove(os.path.join(ROOT, 'contexts', f))
except Exception:
    pass

print("\n==== 结果 ====")
fails = [n for n, ok in checks if not ok]
print("共 %d 项，失败 %d 项" % (len(checks), len(fails)))
if fails:
    for n in fails:
        print("  -", n)
sys.exit(1 if fails else 0)
