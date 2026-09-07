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

# 验证按钮在最左：取第一行 layout 的 widget 顺序
row = cw.findChildren(type(cw.btn_clear.parent().layout().itemAt(0).widget()))
ly = cw.layout().itemAt(0).layout()  # root(QVBoxLayout).itemAt(0) 是 row1
w0 = ly.itemAt(0).widget()
ck("第一行第一个控件是 btn_clear(清理上下文)", w0 is cw.btn_clear)

# 尺寸
ck("初始宽度=470", cw.width() == 470)
cw.set_usage("本次 ↑100[缓存50] ↓20 共120 tok ≈ $0.000010")
ck("有用量时高度=70", cw.height() == 70)
cw.set_usage("")
ck("隐藏用量时高度=46", cw.height() == 46)

# usage 文本含缓存
mgr.cfg = lambda: {'ai_price_in': 0.14, 'ai_price_out': 0.28, 'ai_price_cache': 0.0028}
u = {'prompt_tokens': 1000, 'completion_tokens': 200, 'total_tokens': 1200,
     'prompt_cache_hit_tokens': 400, 'prompt_cache_miss_tokens': 600}
txt = mgr._usage_text(u)
ck("usage 文本含缓存读取标记 [缓存读400]", "[缓存读400]" in txt)
cost, desc = mgr.calc_cost(u)
# 手算：未命中600×0.14/1e6 + 命中400×0.0028/1e6 + 输出200×0.28/1e6
expect = 600*0.14/1e6 + 400*0.0028/1e6 + 200*0.28/1e6
ck("费用公式正确(未命中原价+命中优惠价+输出)", abs(cost - expect) < 1e-12)

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
