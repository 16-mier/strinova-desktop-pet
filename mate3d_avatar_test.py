# -*- coding: utf-8 -*-
"""mate3d_avatar_test.py —— 测试 3D 角色切换菜单项真实生效"""
import os
import sys
import time

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer
import matelink
import mate_avatar


class FakePet:
    role = "星绘"
    _voice_source = 'role'

    def refresh_tray_menu(self):
        print("[menu refresh]")


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


def main():
    app = QApplication([])
    import pet
    pet._mate_link = matelink.MateLink()

    fp = FakePet()
    for name in ("_build_mate3d_menu", "_mate3d_online", "_mate3d_cmd",
                 "_mate3d_launch", "_mate3d_switch_avatar"):
        setattr(fp, name, getattr(pet.PetWindow, name).__get__(fp, FakePet))

    print("当前模型:", os.path.basename(mate_avatar.current_model()))
    menu = fp._build_mate3d_menu(None)
    act = find_action(menu, "aldina")
    if not act:
        print("❌ 没找到 aldina 菜单项")
        return
    print("[1] 点击 aldina 菜单项（后台切换，约需 30-40s）...")
    act.trigger()

    # 等待切换完成（轮询 settings.json）
    def poll(n=0):
        cur = os.path.basename(mate_avatar.current_model() or "")
        if cur.lower().startswith("aldina"):
            time.sleep(2)
            online = matelink.MateLink().online()
            print(f"   ✅ 已切到 aldina（桥在线={online}）")
            # 再切回米雪儿
            print("[2] 切回 michelle ...")
            r = mate_avatar.set_model(
                r"C:\Users\mier\Desktop\deepseek work\mate-engine\michelle_model\michelle.vrm")
            cur2 = os.path.basename(mate_avatar.current_model() or "")
            print(f"   ✅ 已切回 {cur2}（桥状态={r.get('bridge')}）")
            print("\nALL DONE")
            QTimer.singleShot(300, app.quit)
            return
        if n > 60:
            print("   ❌ 超时")
            QTimer.singleShot(300, app.quit)
            return
        QTimer.singleShot(1000, lambda: poll(n + 1))

    QTimer.singleShot(2000, poll)
    app.exec()


if __name__ == "__main__":
    main()