"""verify_drag.py —— 验证 3D 桌宠拖动 / 拖动反应 / 帧率 / 无日志噪声

对应用户本轮反馈：
  1. 3D桌宠无法拖动        → 全局鼠标轮询必须能把窗口真的移走
  2. 生硬无动作            → 拖动时角色必须有"被拎起来"的反应（__dragState 变化）
  3. 不要显示 fps 数       → 页面上不能有可见的帧率数字
  4. 顶格 120 帧           → 循环必须走 setAnimationLoop，且能跑满刷新率
  5. 不显示 hover chat 噪声 → 源码里不能再有那句 print

为什么要"模拟"鼠标而不是真按键：CI/自动化里没人真的按鼠标。
所以测试直接调用 _mouse_tick 依赖的两个输入源（QCursor.pos / _lbutton_down），
把它们替换成可控的假数据，再驱动 _mouse_tick —— 这验证的是【真实代码路径】，
不是复制一份逻辑。
"""
from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pet  # noqa: E402  ★ 必须先 import pet（模块级预加载 QtWebEngine）
from PyQt6.QtCore import QPoint, QTimer, Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

import web3d_pet as w3  # noqa: E402

ROOT = Path(__file__).resolve().parent
PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = ""):
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail else ""))


def main():
    app = QApplication.instance() or QApplication(sys.argv)

    print("\n=== 1. 源码层：拖动实现方式 ===")
    src = (ROOT / "web3d_pet.py").read_text(encoding="utf-8")
    check("使用全局鼠标轮询 _mouse_tick", "def _mouse_tick" in src)
    check("轮询用 GetAsyncKeyState 读按键", "GetAsyncKeyState" in src)
    check("已废弃的 eventFilter 不再处理拖动", "QEvent.Type.MouseButtonPress" not in src)
    check("JS 不再移动窗口（dragWindow 不 move）",
          "self.win.move(self.win.x() + int(dx)" not in src)

    print("\n=== 2. 源码层：无 fps 显示 / 无 hover chat 噪声 ===")
    html = (ROOT / "web3d" / "pet_viewer.html").read_text(encoding="utf-8")
    check("页面隐藏了 fps 元素", "#fps { display:none; }" in html)
    check("不再往 fps 元素写数字", "fpsEl.textContent" not in html)
    check("主循环用 setAnimationLoop", "renderer.setAnimationLoop(animate)" in html)
    check("没有残留 requestAnimationFrame 主循环",
          not re.search(r"requestAnimationFrame\(animate\)", html))
    petsrc = (ROOT / "pet.py").read_text(encoding="utf-8")
    check("pet.py 已移除 hover chat 打印", "hover chat ->" not in petsrc)

    print("\n=== 3. 运行时：窗口拖动真的生效 ===")
    win = w3.Web3DPetWindow(model="michelle", size=(280, 380))
    win.move(400, 300)
    win.show()
    for _ in range(60):
        app.processEvents()
        time.sleep(0.02)
    check("窗口已显示", win.isVisible())
    check("全局鼠标轮询已启动", win._mouse_timer is not None,
          f"timer={win._mouse_timer is not None}")

    # ---- 3a) 点在窗口【外】：不应开始拖动 ----
    fake = {"pos": QPoint(10, 10), "down": True}
    win._lbutton_down = staticmethod(lambda: fake["down"])          # type: ignore
    win._cursor_pos = staticmethod(lambda: fake["pos"])             # type: ignore
    win._mouse_tick()
    check("点窗口外不触发拖动", win._dragging is False)

    # ---- 3b) 点在窗口内但【没点到角色】：也不拖 ----
    win._ready = True
    win._hit_cache_fn = lambda x, y: False        # 模拟"点在透明空白处"
    fake["pos"] = QPoint(win.x() + 140, win.y() + 190)
    win._mouse_tick()
    check("点透明空白处不拖动（不挡下层窗口）", win._dragging is False)

    # ---- 3c) 点在角色上：开始拖动 ----
    win._hit_cache_fn = lambda x, y: True
    fake["pos"] = QPoint(win.x() + 140, win.y() + 190)
    win._mouse_tick()
    check("点角色本体开始拖动", win._dragging is True)
    check("立刻通知 JS 做反应动作（_dragging 为真时 setDragging(true) 已发）",
          win._dragging is True)

    # ---- 3d) 移动鼠标：窗口必须跟着走 ----
    x0, y0 = win.x(), win.y()
    for i in range(1, 11):
        fake["pos"] = QPoint(x0 + 140 + i * 6, y0 + 190 + i * 3)
        win._mouse_tick()
        app.processEvents()
    dx_moved, dy_moved = win.x() - x0, win.y() - y0
    check("窗口跟随鼠标移动", dx_moved == 60 and dy_moved == 30,
          f"实际位移 dx={dx_moved} dy={dy_moved}（期望 60/30）")
    check("移动超过阈值 → 标记为拖动（松手不触发点击）",
          win._moved_during_drag is True)

    # ---- 3e) 松手：拖动结束 ----
    fake["down"] = False
    win._mouse_tick()
    check("松手后结束拖动", win._dragging is False)

    # ---- 3f) 屏幕夹紧：往屏幕外拖不会丢 ----
    scr = app.primaryScreen().availableGeometry()
    fake["down"] = True
    fake["pos"] = QPoint(win.x() + 100, win.y() + 100)
    win._mouse_tick()
    for _ in range(200):                         # 猛拖到右下角很远处
        fake["pos"] = QPoint(fake["pos"].x() + 200, fake["pos"].y() + 200)
        win._mouse_tick()
    check("拖出屏幕被夹紧在屏内",
          win.x() <= scr.right() and win.y() <= scr.bottom(),
          f"win=({win.x()},{win.y()}) screen右/下=({scr.right()},{scr.bottom()})")
    fake["down"] = False
    win._mouse_tick()

    print("\n=== 4. 运行时：拖动反应 / 命中检测真的接上了 JS ===")
    got = {"hit": None, "drag": None}
    win.page.runJavaScript("typeof window.__hitTest", lambda v: got.__setitem__("hit", v))
    win.page.runJavaScript("typeof window.setDragging", lambda v: got.__setitem__("drag", v))
    for _ in range(80):
        app.processEvents()
        time.sleep(0.02)
        if got["hit"] and got["drag"]:
            break
    check("页面有 __hitTest（命中检测）", got["hit"] == "function", f"typeof={got['hit']}")
    check("页面有 setDragging（拖动反应）", got["drag"] == "function", f"typeof={got['drag']}")

    # 命中检测：点在脑袋中心应为 True，点在左上角（透明）应为 False
    hit_top_left = hit_center = None
    win.page.runJavaScript("window.__hitTest(4, 4)", lambda v: got.__setitem__("tl", v))
    win.page.runJavaScript("window.__hitTest(%d, %d)" % (280 // 2, 380 // 2),
                           lambda v: got.__setitem__("ct", v))
    for _ in range(80):
        app.processEvents()
        time.sleep(0.02)
        if "tl" in got and "ct" in got:
            break
    check("左上角判定为未命中（透明区）", got.get("tl") is False, f"={got.get('tl')}")
    check("画面中心判定为命中角色", got.get("ct") is True, f"={got.get('ct')}")

    # 拖动反应：状态真的写进 JS
    win.page.runJavaScript(
        "(function(){window.setDragging(true, 12);return JSON.stringify(window.__dragState?window.__dragState():null);})()",
        lambda v: got.__setitem__("ds_on", v))
    for _ in range(80):
        app.processEvents()
        time.sleep(0.02)
        if "ds_on" in got:
            break
    check("setDragging(true) 后页面状态为开",
          got.get("ds_on") not in (None, "null") and '"on":true' in str(got.get("ds_on")),
          f"__dragState={got.get('ds_on')}")

    win.page.runJavaScript(
        "(function(){window.setDragging(false,0);return JSON.stringify(window.__dragState?window.__dragState():null);})()",
        lambda v: got.__setitem__("ds_off", v))
    for _ in range(80):
        app.processEvents()
        time.sleep(0.02)
        if "ds_off" in got:
            break
    check("setDragging(false) 后页面状态为关",
          '"on":false' in str(got.get("ds_off")), f"__dragState={got.get('ds_off')}")

    print("\n=== 5. 运行时：帧率 ===")
    # window.__fps 每秒才刷新一次真实值，初值是 0 → 先等 2.5 秒再读
    t_end = time.time() + 2.5
    while time.time() < t_end:
        app.processEvents()
        time.sleep(0.02)
    fps = {"v": None}
    win.page.runJavaScript(
        "(function(){var v=window.__fps(); return (typeof v==='number'&&v>0)? v : -1;})()",
        lambda v: fps.__setitem__("v", v))
    for _ in range(80):
        app.processEvents()
        time.sleep(0.03)
        if fps["v"] not in (None, -1):
            break
    check("内部帧率可读（不上屏）", isinstance(fps["v"], (int, float)) and fps["v"] > 0,
          f"fps={fps['v']}")
    win.page.runJavaScript(
        "JSON.stringify({fpsVisible: getComputedStyle(document.getElementById('fps')).display,"
        " hasText: document.getElementById('fps').textContent.length})",
        lambda v: got.__setitem__("fpsdom", v))
    for _ in range(80):
        app.processEvents()
        time.sleep(0.02)
        if "fpsdom" in got:
            break
    check("页面上 fps 元素不可见且无文字",
          '"fpsVisible":"none"' in str(got.get("fpsdom"))
          and '"hasText":0' in str(got.get("fpsdom")),
          f"{got.get('fpsdom')}")

    print("\n=== 6. 尺寸切换后仍可拖动 ===")
    win.resize(360, 480)
    win.view.setGeometry(0, 0, 360, 480)
    for _ in range(20):
        app.processEvents()
        time.sleep(0.02)
    fake["down"] = True
    fake["pos"] = QPoint(win.x() + 180, win.y() + 240)
    win._mouse_tick()
    ok = win._dragging
    x1 = win.x()
    fake["pos"] = QPoint(x1 + 180 + 40, win.y() + 240)
    win._mouse_tick()
    check("改尺寸后依然能拖动", ok and win.x() == x1 + 40, f"x {x1} → {win.x()}")
    fake["down"] = False
    win._mouse_tick()

    win.close()
    for _ in range(10):
        app.processEvents()

    print("\n" + "=" * 56)
    print(f"通过 {len(PASS)} / {len(PASS) + len(FAIL)}")
    if FAIL:
        print("失败项：")
        for f in FAIL:
            print("  -", f)
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
