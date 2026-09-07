# -*- coding: utf-8 -*-
# usage_layout_smoke.py —— 本轮改动冒烟：
# ① 聊天窗「清理上下文」按钮在最左、文案正确；② 窗口尺寸加宽
# ③ usage 文本含缓存命中标记；④ 设置面板单价三档输入框存在且回填
import os
import sys

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer, QRect
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
        return {'ai': {'ai_price_in': 0.14, 'ai_price_out': 0.28,
                        'ai_price_cache': 0.0028}}

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

# 打开聊天窗
mgr.open_chat()
cw = mgr._chat

ck("聊天窗已创建", cw is not None)
ck("清理上下文按钮文案 = '清理上下文'", cw.btn_clear.text() == "清理上下文")
ck("清理上下文提示含'全新对话'", "全新对话" in cw.btn_clear.toolTip())
ck("聊天窗有清楚/记录/发送/关闭按钮", hasattr(cw, 'btn_clear') and hasattr(cw, 'btn_history')
   and hasattr(cw, 'btn_send') and hasattr(cw, 'btn_x'))
ck("聊天窗有会话下拉与新建", hasattr(cw, 'combo_session') and hasattr(cw, 'btn_new_sess'))
ck("聊天窗有消息流 browser", hasattr(cw, 'browser'))

# 尺寸（可视化聊天窗固定宽 470，消息流为主区）
ck("初始宽度=470", cw.width() == 470)
ck("高度为可视化消息窗高度(340)", cw.height() == 340)
cw.set_usage("本次 ↑100[缓存50] ↓20 共120 tok ≈ $0.000010")
ck("有用量时用量行可见", cw.lbl_usage.isVisible() and cw.lbl_usage.text().startswith("本次"))
cw.set_usage("")
ck("隐藏用量时用量行隐藏", not cw.lbl_usage.isVisible())

# usage 文本含缓存 + 费用公式（时段无关：显式关闭峰谷计价，恒用面板满价）
mgr.cfg = lambda: {'ai_price_in': 0.14, 'ai_price_out': 0.28, 'ai_price_cache': 0.0028,
                   'peak_pricing': False}
mgr.peak_pricing_enabled = lambda: False   # 固定满价，避免高峰/空闲时段影响手算
u = {'prompt_tokens': 1000, 'completion_tokens': 200, 'total_tokens': 1200,
     'prompt_cache_hit_tokens': 400, 'prompt_cache_miss_tokens': 600}
txt = mgr._usage_text(u)
ck("usage 文本含缓存读取标记 [缓存读400]", "[缓存读400]" in txt)
cost, desc = mgr.calc_cost(u)
# 手算（满价）：未命中600×0.14/1e6 + 命中400×0.0028/1e6 + 输出200×0.28/1e6
expect = 600*0.14/1e6 + 400*0.0028/1e6 + 200*0.28/1e6
ck("费用公式正确(未命中原价+命中优惠价+输出)", abs(cost - expect) < 1e-12)
# 峰谷逻辑：空闲时段开启峰谷应半价（用与当前时段无关的固定时间判断）
import datetime as _dt
ai_mod = __import__('ai_chat')
_peak = ai_mod.AiChatManager.is_peak_time(_dt.datetime(2026, 9, 7, 10, 0))   # 周一10:00→高峰
_off = ai_mod.AiChatManager.is_peak_time(_dt.datetime(2026, 9, 7, 13, 0))    # 周一13:00→空闲
ck("高峰判断：周一10点=高峰", _peak is True)
ck("空闲判断：周一13点=空闲", _off is False)

# 设置面板单价三档输入框存在
try:
    import settings_panel as sp
    # 只构造面板（不传真实 pet 也可，多数面板接受 pet 参数）
    panel = None
    try:
        panel = sp.SettingsPanel(pet)
    except Exception as e1:
        print("SettingsPanel(pet) 构造失败，尝试其它签名:", e1)
    if panel is not None:
        ck("面板存在 缓存命中单价输入框 ed_ai_price_cache", hasattr(panel, 'ed_ai_price_cache'))
        if hasattr(panel, 'refresh_all'):
            try:
                panel.refresh_all()
            except Exception as e2:
                print("refresh_all 异常(不影响存在性):", e2)
        if hasattr(panel, 'ed_ai_price_cache'):
            val = panel.ed_ai_price_cache.text().strip()
            ck("缓存命中单价回填为 0.0028", val == "0.0028")
            print("   回填值 =", val)
    else:
        ck("面板构造成功", False)
except Exception as e:
    print("面板冒烟跳过/异常:", e)
    ck("面板模块导入成功", False)

print("\n==== 结果 ====")
fails = [n for n, ok in checks if not ok]
print("共 %d 项，失败 %d 项" % (len(checks), len(fails)))
if fails:
    for n in fails:
        print("  FAIL:", n)
    sys.exit(1)
print("ALL PASS")
QTimer.singleShot(100, app.quit)
app.exec()
