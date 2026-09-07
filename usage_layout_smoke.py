# -*- coding: utf-8 -*-
# usage_layout_smoke.py —— 本轮改动冒烟：
# ① 聊天窗重构为「横线输入条」（宽度 640，单行，含会话下拉/新建/删除/输入/发送）
# ② 体系提示词不再渲染；③ usage 文本含缓存命中标记；④ 峰谷计价公式；⑤ 面板单价回填
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

# 打开输入条
mgr.open_chat()
cw = mgr._chat

ck("输入条已创建", cw is not None)
ck("输入条为单行横条(宽640 高48)", cw.width() == 640 and cw.height() == 48)
ck("输入条有会话下拉", hasattr(cw, 'combo_session'))
ck("输入条有新建/删除/发送按钮", hasattr(cw, 'btn_new_sess') and hasattr(cw, 'btn_del_sess')
   and hasattr(cw, 'btn_send'))
ck("输入条保留输入框", hasattr(cw, 'input') and cw.input.isVisible())
# 无大消息流（历史走右键「记录」回看）
ck("输入条无消息流 browser", cw.browser is None)

# 发送后输入条自动收起（极简交互）
cw.input.setText("你好")
cw._send()
ck("发送后输入条自动收起", not cw.isVisible())
ck("发送即清空输入框", cw.input.text() == "")

# 桌面移动 → 输入条跟随桌宠正下方（重新打开）
mgr.open_chat()
cw.show_near(pet.frameGeometry())
app.processEvents()
_old = (cw.x(), cw.y())
class _Mov:
    def frameGeometry(self):
        return QRect(700, 500, 200, 200)
cw._pet = _Mov()
cw._follow_pet()
app.processEvents()
ck("输入条跟随桌宠移动(位置变化)", cw.x() != _old[0] or cw.y() != _old[1])
cw._pet = pet

# 体系提示词不再渲染到任何界面
html_out = ai._msg_html([{'role': 'user', 'content': 'x', 'ts': 't'}],
                        '某个系统提示词', pet, style='bubble')
ck("消息渲染不含体系提示词", '某个系统提示词' not in html_out and '体系提示词' not in html_out)

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
