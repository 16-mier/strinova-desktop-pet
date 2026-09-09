# -*- coding: utf-8 -*-
"""mate3d_smoke.py —— 验证 PetWindow._build_mate3d_menu 构建（真实方法，Fake 实例）"""
import os
import sys

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
        print("[menu refresh called]")


def test():
    app = QApplication([])
    # 从真实 PetWindow 拿方法并绑定到 fake（不实例化 PetWindow，避免副作用）
    import pet
    pet._mate_link = matelink.MateLink()

    fp = FakePet()
    for name in ("_build_mate3d_menu", "_mate3d_online", "_mate3d_cmd", "_mate3d_launch"):
        setattr(fp, name, getattr(pet.PetWindow, name).__get__(fp, FakePet))

    bound_build = fp._build_mate3d_menu
    bound_online = fp._mate3d_online

    online = bound_online()
    print("bridge online:", online)

    menu = bound_build(None)
    def dump(m, indent=0):
        for act in m.actions():
            txt = act.text() or "(sep)"
            print("  " * indent + "| " + txt)
            sm = act.menu()
            if sm:
                dump(sm, indent + 1)
    dump(menu)
    print("SMOKE OK")


if __name__ == "__main__":
    try:
        test()
    except Exception:
        import traceback
        traceback.print_exc()
        print("SMOKE FAIL")