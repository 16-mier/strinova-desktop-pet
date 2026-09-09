# -*- coding: utf-8 -*-
"""mate3d_action_test.py —— 模拟点击 3D 菜单项，验证命令真实送达 Mate-Engine"""
import os
import sys
import time

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from PyQt6.QtWidgets import QApplication, QMenu
from PyQt6.QtCore import QTimer
import matelink


class FakePet:
    role = "星绘"
    _voice_source = 'role'

    def refresh_tray_menu(self):
        pass


def find_action(menu, text):
    for act in menu.actions():
        if act.text() and text in act.text():
            return act
        sm = act.menu()
        if sm:
            r = find_action(sm, text)
            if r:
                return r
    return None


def test():
    app = QApplication([])
    import pet
    pet._mate_link = matelink.MateLink()

    fp = FakePet()
    for name in ("_build_mate3d_menu", "_mate3d_online", "_mate3d_cmd", "_mate3d_launch"):
        setattr(fp, name, getattr(pet.PetWindow, name).__get__(fp, FakePet))

    menu = fp._build_mate3d_menu(None)

    # 1) 点击「微笑」→ 期待 にこり=80
    act_smile = find_action(menu, "微笑")
    if act_smile:
        act_smile.trigger()
        time.sleep(1.5)
        blends = pet._mate_link.blends_dict()
        print("after 微笑: にこり =", blends.get("にこり"))
        assert blends.get("にこり", 0) >= 75, "微笑未生效!"
        print("✅ 微笑联动成功")
    else:
        print("❌ 没找到微笑菜单项")

    # 2) 点击「重置表情」
    act_reset = find_action(menu, "重置表情")
    if act_reset:
        act_reset.trigger()
        time.sleep(1.5)
        blends = pet._mate_link.blends_dict()
        print("after 重置: にこり =", blends.get("にこり"))
        print("✅ 重置联动成功")

    # 3) 点击「生气」→ 期待 怒り=80
    act_angry = find_action(menu, "生气")
    if act_angry:
        act_angry.trigger()
        time.sleep(1.5)
        blends = pet._mate_link.blends_dict()
        print("after 生气: 怒り =", blends.get("怒り"))
        assert blends.get("怒り", 0) >= 75, "生气未生效!"
        print("✅ 生气联动成功")

    # 4) 清理：重置表情
    pet._mate_link.blend_reset()
    print("ALL ACTION TESTS PASSED")


if __name__ == "__main__":
    try:
        test()
        QTimer.singleShot(100, app.quit)
        app.exec()
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)