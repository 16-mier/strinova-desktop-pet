# -*- coding: utf-8 -*-
"""mate3d_keepfunc_test.py —— 验证 3D 模式下原有功能是否照常（热键注册/托盘/音频/右键）"""
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
    holder = {}

    def boot():
        import pet
        w = pet.PetWindow()
        holder['w'] = w
        w.show()
        print("PetWindow shown")

        def step1():
            print("\n[1] 切到 3D ...")
            w.switch_face()
            QTimer.singleShot(3000, step2)

        def step2():
            print("   当前 _in3d =", w._in3d, "| 2D 可见 =", w.isVisible())
            print("\n[2] 3D 模式下检查原功能：")
            # 热键注册状态
            print("   _hotkey_ids 数量 =", len(getattr(w, '_hotkey_ids', {})))
            print("   _custom_hk_map =", len(getattr(w, '_custom_hk_map', {})))
            print("   音频热键映射 =", list(getattr(w, '_audio_hotkeys', {}).values()))
            # 托盘
            print("   托盘可见 =", w.tray.isVisible() if w.tray else None)
            # 音频列表（语音功能基础）
            try:
                audios = w.current_audio_list()
                print("   当前角色音频数 =", len(audios))
            except Exception as e:
                print("   音频列表 err:", e)
            # 右键菜单能否正常构建（3D 模式下）
            m = w._build_role_menu(None)
            print("   右键菜单项数 =", len(m.actions()))
            # 语音播放链路（不实际出声，只验证播放器可用）
            print("   QMediaPlayer =", "可用" if w.player is not None else "不可用")
            # 3D 控制命令仍可用
            try:
                import matelink
                ml = matelink.MateLink()
                r = ml.blend_set("にこり", 50)
                print("   3D 表情命令 =", r)
                time.sleep(1.5)
                print("   读回 にこり =", ml.blends_dict().get("にこり"))
                ml.blend_reset()
            except Exception as e:
                print("   3D 命令 err:", e)
            print("\n[3] 切回 2D ...")
            w.switch_face()
            QTimer.singleShot(2000, step3)

        def step3():
            print("   _in3d =", w._in3d, "| 2D 可见 =", w.isVisible())
            print("   桥仍在线 =", w._mate3d_online())
            print("\nALL DONE")
            QTimer.singleShot(500, app.quit)

        QTimer.singleShot(1200, step1)

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