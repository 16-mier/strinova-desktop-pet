# -*- coding: utf-8 -*-
"""pet_window_smoke.py —— 完整实例化 PetWindow 5 秒，验证主菜单含 3D 联动且无崩溃"""
import os
import sys
import time

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer


def main():
    app = QApplication([])
    # 延迟到事件循环里实例化（PetWindow __init__ 里有 QTimer 等）
    win_holder = {}

    def boot():
        try:
            import pet
            w = pet.PetWindow()
            win_holder['w'] = w
            print("PetWindow created OK")
            # 构建主菜单检查 3D 项
            m = w._build_role_menu(None)
            texts = []
            for act in m.actions():
                texts.append(act.text() or "(sep)")
                sm = act.menu()
                if sm:
                    for a in sm.actions():
                        texts.append("  └ " + (a.text() or "(sep)"))
            joined = "\n".join(texts)
            print("--- main menu ---")
            print(joined)
            assert "3D" in joined or "形象" in joined, "主菜单缺少 3D 联动入口!"
            print("PASS: 主菜单含 3D 联动入口")
            # 找到 3D 子菜单并 dump
            for act in m.actions():
                if act.menu() and ("3D" in (act.text() or "") or "形象" in (act.text() or "")):
                    sm = act.menu()
                    print("--- 3D submenu ---")
                    def dump(mm, ind=0):
                        for a in mm.actions():
                            print("  " * ind + (a.text() or "(sep)"))
                            if a.menu():
                                dump(a.menu(), ind + 1)
                    dump(sm)
        except Exception:
            import traceback
            traceback.print_exc()
            print("FAIL")
        finally:
            QTimer.singleShot(3000, app.quit)

    QTimer.singleShot(0, boot)
    app.exec()
    # 清理
    w = win_holder.get('w')
    if w is not None:
        try:
            w.close()
        except Exception:
            pass
    print("DONE")


if __name__ == "__main__":
    main()