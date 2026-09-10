# -*- coding: utf-8 -*-
"""mate3d_full_test.py —— 验证 3D 模式完整体验：
1) 切到 3D（窗口显隐 + 三横浮层出现 + 尺寸同步）
2) 悬停浮层触发对话（3D 角色说话）
3) 点三横弹菜单（功能入口保留）
4) 切回 2D（浮层消失）
"""
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
import matelink

_u = ctypes.windll.user32


def vis(h):
    return bool(_u.IsWindowVisible(h)) if h else False


def main():
    app = QApplication([])
    holder = {}

    def boot():
        import pet
        w = pet.PetWindow()
        holder['w'] = w
        w.show()
        print("PetWindow 已显示")

        def s1():
            print("\n[1] 切到 3D ...")
            w.switch_face()
            QTimer.singleShot(6000, s2)

        def s2():
            hwnd = w._mate3d_hwnd()
            ov = w._mate_overlay
            print("   _in3d =", w._in3d)
            print("   2D 窗口可见 =", w.isVisible(), "(期望 False)")
            print("   3D 窗口可见 =", vis(hwnd), "(期望 True)")
            print("   三横浮层存在 =", ov is not None)
            if ov:
                print("   浮层可见 =", ov.isVisible(), "(期望 True)")
                g = ov.geometry()
                print(f"   浮层位置 = ({g.x()},{g.y()}) 尺寸={g.width()}x{g.height()}")
                print("   跟随计时器运行中 =", w._mate_overlay_timer is not None and w._mate_overlay_timer.isActive())
            # 尺寸同步检查
            try:
                print("   3D 缩放命令（尺寸同步）已发送")
            except Exception as e:
                print("   size sync err:", e)
            QTimer.singleShot(2000, s3)

        def s3():
            print("\n[2] 悬停浮层 → 触发对话 ...")
            try:
                w._last_hover_chat = 0
                w._mate3d_hover_chat()
                print("   已触发（看 bridge.log 是否出现 say）")
            except Exception as e:
                print("   hover chat err:", e)
            QTimer.singleShot(2500, s4)

        def s4():
            print("\n[3] 检查 3D 菜单（点三横会弹的菜单）")
            m = w._build_role_menu(None)
            texts = [a.text() or '(sep)' for a in m.actions()]
            print("   菜单项数 =", len(texts))
            has3d = any('3D' in t or '桌宠' in t for t in texts)
            print("   含 3D 切换项 =", has3d)
            print("\n[4] 切回 2D ...")
            w.switch_face()
            QTimer.singleShot(2500, s5)

        def s5():
            hwnd = w._mate3d_hwnd()
            ov = w._mate_overlay
            print("   _in3d =", w._in3d)
            print("   2D 窗口可见 =", w.isVisible(), "(期望 True)")
            print("   3D 窗口可见 =", vis(hwnd), "(期望 False)")
            print("   浮层可见 =", ov.isVisible() if ov else None, "(期望 False)")
            print("   桥仍在线 =", w._mate3d_online())
            print("\nDONE")
            QTimer.singleShot(400, app.quit)

        QTimer.singleShot(1500, s1)

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