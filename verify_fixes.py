"""verify_fixes.py —— 验证用户反馈的 5 个问题都已修复

用户原话：
  「右键没有任何选项了」
  「3D角色的三横跟随延迟很高」
  「没有动作」
  「拖动没有任何反应很生硬」
  「鼠标移入没有显示输入栏了」
"""
from __future__ import annotations

import io
import os
import sys
import time
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.environ.setdefault(
    "QTWEBENGINE_CHROMIUM_FLAGS",
    "--ignore-gpu-blocklist --enable-gpu-rasterization --enable-unsafe-swiftshader",
)

import pet as pet_mod

from PyQt6.QtCore import QTimer, QEventLoop, Qt, QPoint, QEvent, QPointF
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QApplication

PASS, FAIL = [], []


def wait(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))
    return cond


def js(win, code, timeout=15000):
    box = {"v": None, "done": False}
    win.page.runJavaScript(code, lambda v: box.update(v=v, done=True))
    t = 0
    while not box["done"] and t < timeout:
        wait(100)
        t += 100
    return box["v"]


def main() -> int:
    app = QApplication(sys.argv)
    pet = pet_mod.PetWindow()
    pet.show()
    wait(1500)

    print("\n【问题1】右键没有任何选项…")
    menu = pet._build_role_menu(None)
    check("主菜单第一层有项", len(menu.actions()) > 5, f"{len(menu.actions())} 项")
    # 关键：3D 子菜单必须是活的（之前 full 被 GC → QMenu 已删除）
    d3 = None
    for a in menu.actions():
        if '3D桌宠' in (a.text() or '') and a.menu():
            d3 = a.menu()
            break
    check("找到「3D桌宠」菜单", d3 is not None)
    if d3 is not None:
        kids = []
        for a in d3.actions():
            if a.menu():
                # 访问子菜单 → 若已被 GC 会抛 RuntimeError
                try:
                    n = len(a.menu().actions())
                    kids.append((a.text(), n, True))
                except RuntimeError as e:
                    kids.append((a.text(), 0, False))
                    print(f"       ✗ {a.text()} 子菜单已失效: {e}")
            else:
                kids.append((a.text(), 0, True))
        for t, n, ok in kids:
            print(f"       {t}  {'(%d 项)' % n if n else ''}  {'OK' if ok else '已失效'}")
        check("所有子菜单都存活（未被 GC）", all(k[2] for k in kids))
        subs = [k for k in kids if k[1] > 0]
        check("至少有 5 个非空分组", len(subs) >= 5, f"{len(subs)} 个")
        # 表情子菜单应有内容
        expr_sub = next((a.menu() for a in d3.actions() if '表情' in (a.text() or '')), None)
        check("表情菜单有内容", expr_sub is not None and len(expr_sub.actions()) > 5,
              f"{len(expr_sub.actions()) if expr_sub else 0} 项")

    print("\n【问题2】切到 3D（后续测试的前提）…")
    pet.switch_face()
    for _ in range(50):
        wait(400)
        if getattr(pet, '_web3d_ready', False):
            break
    w = getattr(pet, '_web3d_win', None)
    check("3D 已就绪", bool(getattr(pet, '_web3d_ready', False)))
    check("3D 窗口存在", w is not None)
    if w is None:
        return 1
    wait(2000)

    print("\n【问题3】三横跟随延迟…")
    ov = getattr(pet, '_mate_overlay', None)
    check("三横浮层已创建", ov is not None)
    if ov is not None:
        t = getattr(pet, '_mate_overlay_timer', None)
        iv = t.interval() if t else -1
        check("跟随间隔已缩短（原 400ms）", 0 < iv <= 40, f"{iv} ms")
        # 拖动 3D 窗口 → 浮层应立刻跟上
        w.move(w.x() + 120, w.y() + 60)
        pet._sync_overlay_now()
        wait(200)
        g = w.geometry()
        expect_x = g.right() - ov.width() - 8
        check("拖动后浮层立即对齐", abs(ov.x() - expect_x) <= 3,
              f"浮层x={ov.x()} 期望={expect_x}")

    print("\n【问题4】拖动有没有反应…")
    # ⚠ 拖动实现已经换过一代：
    #   旧版走 QWidget.eventFilter，但 QtWebEngine 的渲染控件在 Windows 上是
    #   独立原生 HWND，鼠标事件被 Chromium 直接消费 → 过滤器根本收不到，
    #   拖动完全无效（这是用户报的"3D桌宠无法拖动"）。
    #   现在改成全局鼠标轮询 _mouse_tick（GetAsyncKeyState + QCursor.pos）。
    #   所以这里不再构造 QMouseEvent，而是替换掉两个输入源再驱动 tick。
    check("3D 窗口有全局鼠标轮询定时器",
          getattr(w, '_mouse_timer', None) is not None)
    start = w.pos()
    fake = {"pos": QPoint(start.x() + 50, start.y() + 50), "down": True}
    w._lbutton_down = staticmethod(lambda: fake["down"])      # type: ignore
    w._cursor_pos = staticmethod(lambda: fake["pos"])         # type: ignore
    w._ready = True
    w._hit_cache_fn = lambda x, y: True          # 假装点在角色身上
    w._mouse_tick()                              # 按下 → 开始拖
    fake["pos"] = QPoint(start.x() + 130, start.y() + 90)
    w._mouse_tick()                              # 移动 → 窗口跟过去
    wait(200)
    print(f"       拖动前 {start.x()},{start.y()}  →  拖动后 {w.x()},{w.y()}")
    check("窗口跟着鼠标移动了", (w.x(), w.y()) != (start.x(), start.y()),
          f"{start.x()},{start.y()} -> {w.x()},{w.y()}")
    check("位移量正确（+80,+40）",
          w.x() == start.x() + 80 and w.y() == start.y() + 40,
          f"Δ=({w.x()-start.x()},{w.y()-start.y()})")
    # 松手
    fake["down"] = False
    w._mouse_tick()
    check("松手后拖动状态结束", w._dragging is False)

    print("\n【问题5】鼠标移入显示输入栏…")
    pet._on_web3d_hover(True)
    wait(1500)
    chat = getattr(pet.ai, '_chat', None) if getattr(pet, 'ai', None) else None
    vis = chat.isVisible() if chat is not None else False
    print(f"       ai={pet.ai is not None}  ai.enabled={pet.ai.enabled() if pet.ai else None}"
          f"  chat_bar_visible={vis}")
    check("悬停后输入栏已显示", vis)
    if vis and chat is not None:
        cg, wg = chat.geometry(), w.geometry()
        scr = QApplication.primaryScreen().availableGeometry()
        print(f"       输入栏 {cg.x()},{cg.y()} {cg.width()}x{cg.height()}"
              f"   3D窗口 {wg.x()},{wg.y()} {wg.width()}x{wg.height()}"
              f"   屏幕x[{scr.left()}..{scr.right()}] y[{scr.top()}..{scr.bottom()}]")
        # 期望位置：水平居中于 3D 窗口；若超出屏幕则夹紧到边缘（这是正确行为）
        want_x = wg.center().x() - cg.width() // 2
        want_x = max(scr.left(), min(want_x, scr.right() - cg.width() + 1))
        near_x = abs(cg.x() - want_x) <= 4
        check("输入栏水平对齐 3D 窗口（超出则夹紧屏幕）", near_x,
              f"实际x={cg.x()} 期望x={want_x}")
        # 垂直：贴在 3D 窗口下方，或在屏幕底时改到上方 —— 两者都算合理
        below = abs(cg.y() - (wg.bottom() + 6)) <= 12
        above = cg.y() + cg.height() <= wg.top()
        check("输入栏垂直贴着 3D 窗口（下/上）", below or above,
              f"输入栏y={cg.y()} 3D底边={wg.bottom()} 3D顶边={wg.top()}"
              f" ({'下方' if below else '上方' if above else '不贴合'})")
    # 离开 → 0.5s 后隐藏
    pet._on_web3d_hover(False)
    wait(1600)
    vis2 = chat.isVisible() if chat is not None else False
    check("离开后输入栏已收起", not vis2, f"visible={vis2}")
    check("3D 窗口有 hoverChanged 信号", hasattr(w, 'hoverChanged'))

    print("\n【问题3b】待机动作…")
    # 冻结前后各拍一帧，检查画面确实在动
    import base64, hashlib
    def snap():
        u = js(w, "window.__snapshot()", 20000)
        if u and str(u).startswith('data:image'):
            return hashlib.md5(base64.b64decode(str(u).split(',', 1)[1])).hexdigest()[:10]
        return None
    js(w, "window.__setIdleMotion(true)")
    js(w, "window.setBlinkEnabled(false)")
    wait(1200)
    frames = []
    for _ in range(6):
        frames.append(snap())
        wait(700)
    uniq = len(set(f for f in frames if f))
    print(f"       6 帧的 md5: {frames}")
    check("画面在持续变化（有动作）", uniq >= 3, f"{uniq} 种不同画面")
    idle = js(w, "JSON.stringify({pos: typeof idleTime !== 'undefined'})")
    print(f"       idle 状态: {idle}")

    print("\n" + "=" * 62)
    print(f"结果：{len(PASS)} 通过 / {len(FAIL)} 失败")
    if FAIL:
        print(f"失败项: {FAIL}")
    print("=" * 62)
    try:
        pet.close()
    except Exception:
        pass
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
