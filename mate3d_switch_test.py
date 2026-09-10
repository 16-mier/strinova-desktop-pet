# -*- coding: utf-8 -*-
"""mate3d_switch_test.py —— 验证 2D↔3D 一键切换（窗口显隐 + 功能保留）"""
import os
import sys
import time
import ctypes
from ctypes import wintypes

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer

_u = ctypes.windll.user32


def visible(hwnd):
    return bool(_u.IsWindowVisible(hwnd)) if hwnd else False


def main():
    app = QApplication([])
    holder = {}

    def boot():
        import pet
        w = pet.PetWindow()
        holder['w'] = w
        w.show()
        print("PetWindow created; visible =", w.isVisible())

        def step0():
            m = w._build_role_menu(None)
            texts = [a.text() or '(sep)' for a in m.actions()]
            print("--- 3D 相关菜单项 ---")
            for t in texts:
                if '3D' in t or '桌宠' in t or '米雪儿' in t:
                    print("   ", t)
            assert any('3D' in t for t in texts), "主菜单缺少 3D 切换入口"
            print("Mate 运行中:", w._mate3d_running(), "| 桥在线:", w._mate3d_online())
            hwnd0 = w._mate3d_hwnd()
            print("切前 3D 窗口 hwnd =", hwnd0, "visible =", visible(hwnd0))
            QTimer.singleShot(500, step1)

        def step1():
            print("\n[1] 点击 → 切换到 3D 米雪儿")
            w.switch_face()
            QTimer.singleShot(3000, step2)

        def step2():
            hwnd = w._mate3d_hwnd()
            print("   _in3d =", w._in3d)
            print("   2D 窗口可见 =", w.isVisible(), "(期望 False)")
            print("   3D 窗口 hwnd =", hwnd, "visible =", visible(hwnd), "(期望 True)")
            print("   桥在线 =", w._mate3d_online())
            ok1 = (w._in3d is True) and (not w.isVisible()) and visible(hwnd)
            print("   => 切到 3D:", "✅ 成功" if ok1 else "❌ 失败")
            QTimer.singleShot(1500, step3)

        def step3():
            print("\n[2] 点击 → 返回简易桌宠")
            w.switch_face()
            QTimer.singleShot(2500, step4)

        def step4():
            hwnd = w._mate3d_hwnd()
            print("   _in3d =", w._in3d)
            print("   2D 窗口可见 =", w.isVisible(), "(期望 True)")
            print("   3D 窗口 hwnd =", hwnd, "visible =", visible(hwnd), "(期望 False)")
            print("   桥仍在线 =", w._mate3d_online(), "(期望 True，进程没退)")
            ok2 = (w._in3d is False) and w.isVisible() and (not visible(hwnd)) and w._mate3d_online()
            print("   => 切回 2D:", "✅ 成功" if ok2 else "❌ 失败")

            print("\n[3] 再切一次（验证可反复切换）")
            w.switch_face()
            QTimer.singleShot(2500, step5)

        def step5():
            hwnd = w._mate3d_hwnd()
            ok3 = (w._in3d is True) and (not w.isVisible()) and visible(hwnd)
            print("   第二次切到 3D:", "✅ 成功" if ok3 else "❌ 失败")
            print("   3D 窗口 visible =", visible(hwnd))
            # 收尾：切回 2D
            w.switch_face()
            QTimer.singleShot(1500, step6)

        def step6():
            print("\n功能保留检查（3D 切换过程中）：")
            print("   托盘图标存在 =", w.tray is not None)
            print("   托盘可见 =", w.tray.isVisible() if w.tray else None)
            print("   音频热键映射 =", list(getattr(w, '_audio_hotkeys', {}).values()))
            print("   AI 模块 =", getattr(w, 'ai', None) is not None)
            print("   右键菜单项数 =", len(w._build_role_menu(None).actions()))
            print("\nALL DONE")
            QTimer.singleShot(500, app.quit)

        QTimer.singleShot(1500, step0)

    QTimer.singleShot(0, boot)
    app.exec()
    w = holder.get('w')
    if w:
        try:
            w.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()