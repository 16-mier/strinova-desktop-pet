"""web3d_integration_test.py —— pet.py 集成自研 3D 引擎的端到端验证

验证链条（用户真实操作路径）：
  1. PetWindow 正常启动（2D 桌宠）
  2. 菜单里有「✨ 切换到 3D」入口
  3. 点它 → 内置 3D 窗口出现 + 模型渲染成功 + 三横浮层出现
  4. 浮层跟随 3D 窗口右上角
  5. 悬停浮层 → 角色说话
  6. 改 2D 尺寸 → 3D 窗口跟着变
  7. 点「3D 角色」→ 即时切换（无需重启）
  8. 点三横 → 弹出与 2D 相同的完整菜单（功能保留）
  9. 切回 2D → 浮层消失 + 3D 窗口隐藏 + 2D 桌宠回来

用法：python web3d_integration_test.py
"""
from __future__ import annotations

import base64
import io
import sys
import time
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import os
os.environ.setdefault(
    "QTWEBENGINE_CHROMIUM_FLAGS",
    "--ignore-gpu-blocklist --enable-gpu-rasterization --enable-unsafe-swiftshader",
)

# ⚠ 顺序关键：必须先 import pet（它在模块级预加载 QtWebEngineWidgets），
#   再创建 QApplication。真实运行 python pet.py 时就是这个顺序。
import pet as pet_mod

from PyQt6.QtCore import QTimer, QEventLoop
from PyQt6.QtWidgets import QApplication, QMenu

RESULTS: dict = {}
PASS: list[str] = []
FAIL: list[str] = []


def wait(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))
    RESULTS[name] = bool(cond)
    return cond


def main() -> int:
    app = QApplication(sys.argv)

    print("=" * 64)
    print("集成测试：pet.py + 自研 3D 引擎（three-vrm 内置）")
    print("=" * 64)

    # ---------- 1. 启动 PetWindow ----------
    print("\n[1] 启动 2D 桌宠…")
    win = pet_mod.PetWindow()
    win.show()
    wait(1500)
    check("2D 桌宠启动", win.isVisible(), f"{win.width()}x{win.height()}")
    check("3D 后端=内置 web", getattr(win, '_3d_backend', '') == 'web',
          f"backend={getattr(win, '_3d_backend', '?')}")

    # ---------- 2. 菜单入口 ----------
    print("\n[2] 检查菜单入口…")
    menu = win._build_role_menu(None)
    labels = [a.text() for a in menu.actions()]
    print(f"      菜单项: {labels}")
    has_switch = any('3D' in l for l in labels)
    check("菜单有 3D 切换入口", has_switch)
    # 找 3D 控制子菜单
    sub3d = None
    for a in menu.actions():
        if '3D' in a.text() and a.menu() is not None:
            sub3d = a.menu()
            break
    if sub3d:
        sub_labels = [x.text() for x in sub3d.actions()]
        print(f"      3D 子菜单: {sub_labels}")
        check("3D 子菜单含角色切换", any('角色' in l for l in sub_labels))
        check("3D 子菜单含互动/动作", any(('互动' in l or '动作' in l) for l in sub_labels))

    # ---------- 3. 切换到 3D ----------
    print("\n[3] 切换到 3D（内置引擎）…")
    t0 = time.time()
    win.switch_face()
    check("切换后进入 3D 状态", getattr(win, '_in3d', False))
    check("2D 窗口已隐藏", not win.isVisible())

    # 等 3D 窗口 + 模型就绪
    w3 = None
    for i in range(60):
        wait(500)
        w3 = getattr(win, '_web3d_win', None)
        if w3 is not None and getattr(win, '_web3d_ready', False):
            break
    dt = time.time() - t0
    check("3D 窗口已创建", w3 is not None, f"耗时 {dt:.1f}s")
    if w3 is None:
        print("\n!! 3D 窗口未创建，终止")
        return 1
    check("3D 模型已就绪", getattr(win, '_web3d_ready', False))
    wait(2000)
    check("3D 窗口可见", w3.isVisible(), f"{w3.width()}x{w3.height()}")

    # 渲染验证：用 GL 像素统计（比 toDataURL 更可靠，不受窗口遮挡/合成影响）
    box = {"v": None, "done": False}
    w3.page.runJavaScript("window.__pixelStats ? window.__pixelStats() : 'NO_FN'",
                          lambda v: box.update(v=v, done=True))
    for _ in range(60):
        wait(200)
        if box["done"]:
            break
    raw = str(box["v"] or "")
    cov, ncolors = 0.0, 0
    if raw.startswith("{"):
        import json as _json
        try:
            st = _json.loads(raw)
            cov = float(st.get("coverage", 0))
            ncolors = int(st.get("colors", 0))
        except Exception:
            pass
    check("3D 渲染有实质内容", cov > 5 and ncolors > 20,
          f"覆盖 {cov:.1f}% / {ncolors} 种颜色")
    # 同时存一张图便于人工查看
    snap = {"v": None, "done": False}
    w3.page.runJavaScript("window.__snapshot ? window.__snapshot() : 'NO_FN'",
                          lambda v: snap.update(v=v, done=True))
    for _ in range(40):
        wait(200)
        if snap["done"]:
            break
    if snap["v"] and str(snap["v"]).startswith("data:image"):
        png = HERE / "integration_3d.png"
        png.write_bytes(base64.b64decode(str(snap["v"]).split(",", 1)[1]))
        print(f"      （截图已存 {png.name}, {png.stat().st_size:,} B）")

    # ---------- 4. 三横浮层 ----------
    print("\n[4] 三横浮层…")
    for _ in range(20):
        wait(300)
        ov = getattr(win, '_mate_overlay', None)
        if ov is not None and ov.isVisible():
            break
    ov = getattr(win, '_mate_overlay', None)
    check("浮层已显示", ov is not None and ov.isVisible())
    if ov is not None:
        g = w3.geometry()
        # 期望位置（与 MateOverlay.follow_mate 一致）
        exp_x = g.right() - ov.width() - 8
        exp_y = g.top() + 8
        # 若 3D 窗口贴屏幕边缘，浮层会被夹到屏幕内 —— 这时比较夹紧后的期望值
        scr = QApplication.primaryScreen().availableGeometry()
        exp_x = max(scr.left(), min(exp_x, scr.right() - ov.width()))
        exp_y = max(scr.top(), min(exp_y, scr.bottom() - ov.height()))
        dx = abs(ov.x() - exp_x)
        dy = abs(ov.y() - exp_y)
        check("浮层跟随 3D 窗口右上角", dx <= 20 and dy <= 20,
              f"浮层({ov.x()},{ov.y()}) 期望({exp_x},{exp_y})")
        # 先把 3D 窗口挪到屏幕中部，确保浮层不被夹紧，再验证跟随
        w3.move(400, 300)
        wait(1200)
        g2 = w3.geometry()
        exp_x2 = g2.right() - ov.width() - 8
        dx2 = abs(ov.x() - exp_x2)
        check("拖动后浮层继续跟随", dx2 <= 20,
              f"浮层x={ov.x()} 期望x={exp_x2}")

    # ---------- 5. 悬停对话 ----------
    print("\n[5] 悬停对话…")
    ok_hover = False
    try:
        win._last_hover_chat = 0.0
        win._mate_overlay_hover(True)
        wait(900)
        r = {"v": None, "done": False}
        w3.page.runJavaScript("document.getElementById('bubble').textContent",
                              lambda v: r.update(v=v, done=True))
        for _ in range(20):
            wait(150)
            if r["done"]:
                break
        vis = {"v": None, "done": False}
        w3.page.runJavaScript("document.getElementById('bubble').style.display",
                              lambda v: vis.update(v=v, done=True))
        for _ in range(20):
            wait(150)
            if vis["done"]:
                break
        ok_hover = bool(r["v"]) and vis["v"] == "block"
        check("悬停浮层 → 角色说话", ok_hover, f"气泡={r['v']!r} display={vis['v']}")
    except Exception as e:
        check("悬停浮层 → 角色说话", False, str(e))

    # ---------- 6. 尺寸同步 ----------
    print("\n[6] 尺寸同步…")
    old_size = (w3.width(), w3.height())
    win.set_pet_size(320)
    wait(1000)
    new_size = (w3.width(), w3.height())
    check("改 2D 尺寸 → 3D 跟着变", new_size != old_size,
          f"{old_size} -> {new_size}")
    win.set_pet_size(200)
    wait(800)

    # ---------- 7. 热切换角色 ----------
    # 只保留米雪儿后，用 michelle ↔ michelle_expr 验证热切换（同一个角色的两份模型）
    print("\n[7] 热切换 3D 角色（重点：不重启）…")
    t0 = time.time()
    win._mate3d_switch_avatar('michelle.vrm', 'michelle.vrm')
    cur = None
    for _ in range(50):
        wait(300)
        r = {"v": None, "done": False}
        w3.page.runJavaScript("window.getModel()", lambda v: r.update(v=v, done=True))
        for _ in range(10):
            wait(100)
            if r["done"]:
                break
        cur = r["v"]
        if cur and 'michelle' in str(cur).lower() and 'expr' not in str(cur).lower():
            break
    dt = time.time() - t0
    check("热切换模型（无需重启）",
          cur and 'michelle' in str(cur).lower(),
          f"当前={cur} 耗时 {dt:.1f}s")
    check("切换速度 < 8 秒（对比 Mate 的 5~40s）", dt < 8, f"{dt:.1f}s")
    # 切回带表情的版本（默认启动就是这个）
    win._mate3d_switch_avatar('michelle_expr.vrm', 'michelle_expr.vrm')
    for _ in range(40):
        wait(300)
        r = {"v": None, "done": False}
        w3.page.runJavaScript("window.getModel()", lambda v: r.update(v=v, done=True))
        for _ in range(10):
            wait(100)
            if r["done"]:
                break
        if r["v"] and 'michelle_expr' in str(r["v"]).lower():
            break
    check("切回米雪儿（带表情版）", 'michelle_expr' in str(r["v"]).lower(), f"当前={r['v']}")

    # ---------- 8. 三横菜单（功能保留） ----------
    print("\n[8] 三横菜单功能保留…")
    try:
        m = win._build_role_menu(None)
        n_items = len(m.actions())
        check("菜单项数量完整（≥15）", n_items >= 15, f"{n_items} 项")
        keys = ["设置", "聊天", "切换角色", "AI 用量", "绑定麦克风"]
        texts = " ".join(a.text() for a in m.actions())
        for k in keys:
            check(f"保留功能：{k}", k in texts)
    except Exception as e:
        check("菜单构建", False, str(e))

    # ---------- 9. 切回 2D ----------
    print("\n[9] 切回 2D…")
    win.switch_face()
    wait(1200)
    check("回到 2D 模式", not getattr(win, '_in3d', False))
    check("2D 桌宠已显示", win.isVisible())
    ov2 = getattr(win, '_mate_overlay', None)
    check("浮层已隐藏", ov2 is None or not ov2.isVisible())
    check("3D 窗口已隐藏（未退出）", not w3.isVisible())
    # 再切回 3D 验证可往返
    win.switch_face()
    wait(2500)
    check("再次切到 3D 成功（往返）", getattr(win, '_in3d', False) and w3.isVisible())

    # ---------- 汇总 ----------
    print("\n" + "=" * 64)
    print(f"结果：{len(PASS)} 通过 / {len(FAIL)} 失败")
    if FAIL:
        print("失败项：")
        for f in FAIL:
            print(f"  ✗ {f}")
    print("=" * 64)
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
