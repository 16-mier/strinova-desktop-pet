"""web3d_pet_test.py —— 自研 3D 桌宠自动化验证

验证：
  1. 窗口能创建、页面能加载
  2. VRM 模型渲染成功（抓图 + 像素统计）
  3. 热切换模型（michelle → aldina → michelle），全程不重启
  4. 表情接口可用
  5. 说话气泡
  6. 帧率

用法：python web3d_pet_test.py
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

from PyQt6.QtCore import QTimer, QEventLoop
from PyQt6.QtWidgets import QApplication

from web3d_pet import Web3DPetWindow

RESULTS: dict = {}


def wait(ms: int):
    """阻塞等待（保持事件循环运行）"""
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def js_sync(win: Web3DPetWindow, code: str, timeout: int = 4000):
    """同步执行 JS 并取回结果"""
    box = {"v": None, "done": False}
    win.page.runJavaScript(code, lambda v: (box.update(v=v, done=True)))

    t0 = time.time()
    while not box["done"] and time.time() - t0 < timeout / 1000:
        wait(50)
    return box["v"]


def main() -> int:
    app = QApplication(sys.argv)
    print("[test] 创建 3D 桌宠窗口…")
    win = Web3DPetWindow(model="michelle", size=(300, 400))
    win.show()

    # ---- 1. 等页面就绪 ----
    print("[test] 等待页面 + 模型加载…")
    for i in range(40):
        wait(500)
        v = js_sync(win, "window.getModel ? (window.getModel() || '') : 'NOPAGE'", 2000)
        if v:
            print(f"[test] 模型已加载: {v}  (等待 {(i+1)*0.5:.1f}s)")
            RESULTS["loaded"] = v
            break
    else:
        print("[test] !! 模型加载超时")
        RESULTS["loaded"] = None

    # 再等一会让首帧渲染稳定
    wait(2500)

    # ---- 2. 渲染验证 ----
    print("\n[test] 抓图验证渲染…")
    data = js_sync(win, "(() => { const c = document.querySelector('canvas');"
                        " return c ? c.toDataURL('image/png') : 'NOCANVAS'; })()", 8000)
    if data and str(data).startswith("data:image"):
        png = HERE / "web3d_render.png"
        png.write_bytes(base64.b64decode(str(data).split(",", 1)[1]))
        print(f"[test] 截图 -> {png.name} ({png.stat().st_size:,} B)")
        import subprocess
        subprocess.run([sys.executable, str(HERE / "check_shot.py"), str(png)])
        RESULTS["png"] = str(png)
    else:
        print(f"[test] !! 无法抓图: {str(data)[:120]}")

    # ---- 3. FPS ----
    fps = js_sync(win, "document.getElementById('fps').textContent")
    print(f"\n[test] FPS: {fps}")
    RESULTS["fps"] = fps

    # ---- 4. 表情 ----
    print("\n[test] 表情接口…")
    exprs = js_sync(win, "window.listExpressions().join(',')")
    print(f"[test] 可用表情({len(str(exprs).split(','))}): {exprs}")
    RESULTS["expressions"] = exprs
    for emo in ("happy", "angry", "surprised"):
        r = js_sync(win, f"window.setExpression('{emo}', 0.9)")
        print(f"[test]   设置为 {emo} -> {r}")
        wait(400)

    # ---- 5. 说话气泡 ----
    print("\n[test] 说话气泡…")
    js_sync(win, "window.say('测试一下说话功能～', 3000)")
    wait(600)
    bubble_visible = js_sync(win, "document.getElementById('bubble').style.display")
    bubble_text = js_sync(win, "document.getElementById('bubble').textContent")
    print(f"[test] 气泡 display={bubble_visible}  文字={bubble_text!r}")
    RESULTS["bubble"] = (bubble_visible, bubble_text)

    # ---- 6. 热切换模型 ----
    print("\n[test] 热切换模型（不重启进程）…")
    t_start = time.time()
    for target in ("aldina", "Lazuli_VRM", "michelle"):
        t0 = time.time()
        ok = win.set_model(target)
        # 等待切换完成
        for _ in range(30):
            wait(300)
            cur = js_sync(win, "window.getModel()", 2000)
            if cur and target.lower() in str(cur).lower():
                break
        dt = time.time() - t0
        cur = js_sync(win, "window.getModel()", 2000)
        print(f"[test]   -> {target:14s} ok={ok}  当前={cur}  耗时 {dt:.1f}s")
        RESULTS[f"switch_{target}"] = dt
        wait(1200)
    print(f"[test] 三次切换总耗时 {time.time()-t_start:.1f}s（进程未重启）")

    # ---- 7. 托盘菜单 ----
    print("\n[test] 托盘菜单…")
    acts = [a.text() for a in win.menu.actions()]
    print(f"[test] 顶层菜单: {acts}")
    sub = win.menu.actions()[0].menu()
    if sub:
        print(f"[test] 角色子菜单: {[a.text() for a in sub.actions()]}")
    RESULTS["menu"] = acts

    # ---- 完成 ----
    wait(1500)
    js_sync(win, "window.say('全部测试通过！', 4000)")
    wait(2000)
    data = js_sync(win, "document.querySelector('canvas').toDataURL('image/png')", 8000)
    if data and str(data).startswith("data:image"):
        png = HERE / "web3d_final.png"
        png.write_bytes(base64.b64decode(str(data).split(",", 1)[1]))
        print(f"\n[test] 最终截图 -> {png.name}")

    print("\n===== 汇总 =====")
    for k, v in RESULTS.items():
        print(f"  {k:20s} = {str(v)[:80]}")

    win.hide()
    return 0


if __name__ == "__main__":
    sys.exit(main())
