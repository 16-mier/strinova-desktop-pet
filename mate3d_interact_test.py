# -*- coding: utf-8 -*-
"""mate3d_interact_test.py —— 测试 3D 互动功能（说话/Q版/大屏/气泡/粒子）+ 悬停对话"""
import os
import sys
import time

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer
import matelink


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


class FakePet:
    role = "星绘"
    _voice_source = 'role'

    def refresh_tray_menu(self):
        pass


def main():
    app = QApplication([])
    import pet
    ml = matelink.MateLink()
    pet._mate_link = ml

    fp = FakePet()
    for name in ("_build_mate3d_menu", "_mate3d_online", "_mate3d_cmd",
                 "_mate3d_launch", "_mate3d_say_dialog", "_mate3d_toggle_auto_talk",
                 "_mate3d_hover_chat", "_mate3d_switch_avatar"):
        setattr(fp, name, getattr(pet.PetWindow, name).__get__(fp, FakePet))
    fp._mate_hover_chat = True
    fp._last_hover_chat = 0

    print("=== 1) 直接测 say 说话 ===")
    r = ml.say("你好呀，我是米雪儿～")
    print("   ", r)
    time.sleep(2)

    print("\n=== 2) 测悬停对话（模拟鼠标移到浮层）===")
    fp._last_hover_chat = 0
    fp._mate3d_hover_chat()
    time.sleep(2)

    print("\n=== 3) 测互动菜单项 ===")
    menu = fp._build_mate3d_menu(None)
    for label in ("Q 版模式", "大屏模式", "气泡开关", "自动说话", "粒子特效"):
        a = find_action(menu, label)
        print(f"   找到「{label}」: {a is not None}")

    print("\n=== 4) 执行 Q版切换 ===")
    print("   ", ml.chibi())
    time.sleep(2)
    print("=== 5) 执行粒子特效 ===")
    print("   ", ml.particle_theme("default"))
    time.sleep(1)

    print("\n=== 6) 角色列表（新功能验证）===")
    for n, p in ml.avatar_list():
        print("   ", n)

    print("\nDONE")
    QTimer.singleShot(300, app.quit)
    app.exec()


if __name__ == "__main__":
    main()