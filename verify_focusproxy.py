"""verify_focusproxy.py —— 独立核实「eventFilter 挂 focusProxy() 能不能收到鼠标事件」

为什么值得花时间核实：项目当前用 GetAsyncKeyState 全局轮询拖动，前提假设是
「Qt 在 Windows 上收不到 QWebEngineView 的鼠标事件（原生 HWND）」。
一份调研报告称这个前提是错的，真正原因是 focusProxy() 在 loadFinished 前返回 None，
导致 installEventFilter 静默失败。

如果成立，拖动可以改回官方正规做法（事件驱动，无 16ms 轮询开销、无全局钩子）。
所以必须自己验一遍，不采信二手结论。

本脚本只做【观测】，不改动项目文件。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pet  # noqa: E402  ★ 必须先 import pet（模块级预加载 QtWebEngine）
from PyQt6.QtCore import QEvent, QObject, QPoint, QPointF, Qt  # noqa: E402
from PyQt6.QtGui import QMouseEvent  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

import web3d_pet as w3  # noqa: E402

SEEN: list[str] = []


class Spy(QObject):
    """记录收到的鼠标事件（挂在谁身上由调用方决定）"""

    def __init__(self, tag: str):
        super().__init__()
        self.tag = tag

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease,
                 QEvent.Type.MouseMove, QEvent.Type.HoverMove):
            SEEN.append(f"{self.tag}:{t.name}")
        return False


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    win = w3.Web3DPetWindow(model="michelle", size=(300, 420))
    win.move(200, 200)
    win.show()

    view = win
    # 找到真正的 QWebEngineView（Web3DPetWindow 可能自己就是，也可能包了一层）
    page_obj = getattr(view, "page", None)
    print(f"Web3DPetWindow.page = {type(page_obj).__name__ if page_obj else None}")

    print("\n=== A. 加载前 focusProxy() 是什么 ===")
    fp_before = view.focusProxy()
    print(f"  focusProxy() = {fp_before!r}  ({type(fp_before).__name__ if fp_before else 'None'})")

    print("\n=== B. 等加载完成 ===")
    t0 = time.time()
    while time.time() - t0 < 90:
        app.processEvents(); time.sleep(0.05)
        if win._ready:
            break
    print(f"  _ready={win._ready}  用时 {time.time()-t0:.1f}s")

    fp_after = view.focusProxy()
    print(f"  加载后 focusProxy() = {fp_after!r}  "
          f"({type(fp_after).__name__ if fp_after else 'None'})")
    changed = (fp_before is None) != (fp_after is None)
    print(f"  → focusProxy 在加载前后{'【发生变化】' if changed else '【没有变化】'}"
          f"{'，证实了「加载前取到 None」的推断' if changed else ''}")

    # 备用：如果 view 不是 QWebEngineView，从子对象里找
    target_view = view
    if fp_after is None:
        from PyQt6.QtWebEngineWidgets import QWebEngineView
        if not isinstance(view, QWebEngineView):
            found = view.findChild(QWebEngineView)
            if found:
                target_view = found
                fp_after = found.focusProxy()
                print(f"  改为使用子对象 QWebEngineView，focusProxy()={fp_after!r}")

    print("\n=== C. 对照实验：同一次合成点击，挂不同对象 ===")
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    qview = view if isinstance(view, QWebEngineView) else view.findChild(QWebEngineView)
    print(f"  QWebEngineView = {qview!r}")
    if qview is None:
        print("  找不到 QWebEngineView，无法继续")
        return 1

    spy_view = Spy("view")
    spy_fp = Spy("focusProxy")
    spy_page = Spy("page")
    qview.installEventFilter(spy_view)
    fp = qview.focusProxy()
    if fp is not None:
        fp.installEventFilter(spy_fp)
        print(f"  已挂 eventFilter 到 focusProxy ({type(fp).__name__})")
    else:
        print("  focusProxy() 仍为 None —— 无法挂载")
    pg = qview.page()
    if pg is not None:
        pg.installEventFilter(spy_page)

    def synth(target, kind, pos=QPointF(150, 200), btn=Qt.MouseButton.LeftButton):
        """向指定对象投递合成鼠标事件（必须投给 focusProxy，投给 view 会崩）"""
        if target is None:
            return
        if kind == "press":
            e = QMouseEvent(QEvent.Type.MouseButtonPress, pos, pos,
                            btn, btn, Qt.KeyboardModifier.NoModifier)
        elif kind == "move":
            e = QMouseEvent(QEvent.Type.MouseMove, pos, pos,
                            Qt.MouseButton.NoButton, btn, Qt.KeyboardModifier.NoModifier)
        else:
            e = QMouseEvent(QEvent.Type.MouseButtonRelease, pos, pos,
                            btn, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
        app.sendEvent(target, e)

    for kind in ("press", "move", "release"):
        synth(fp, kind)
        app.processEvents(); time.sleep(0.08)

    print("\n  收到的事件：")
    if SEEN:
        for s in SEEN:
            print("    " + s)
    else:
        print("    （无）")

    print("\n=== D. 也试一下真·鼠标事件（移动到窗口上）===")
    SEEN.clear()
    from PyQt6.QtGui import QCursor
    QCursor.setPos(win.x() + 150, win.y() + 200)
    for _ in range(30):
        app.processEvents(); time.sleep(0.02)
    print(f"  仅移动光标（无按键）收到：{SEEN if SEEN else '（无）'}")

    print("\n=== 结论 ===")
    fp_ok = any(s.startswith("focusProxy:") for s in SEEN) or \
            any(s.startswith("focusProxy:") for s in SEEN)
    if fp is not None:
        print("  focusProxy() 在加载后【存在】")
        print("  → 若上面的合成事件里 focusProxy 收到了 press/move/release，")
        print("     则「挂 focusProxy 能收到鼠标事件」成立，全局轮询可考虑替换。")
    else:
        print("  focusProxy() 仍为 None —— 该方案在本环境不可用，全局轮询是必需的。")

    try:
        win.close()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
