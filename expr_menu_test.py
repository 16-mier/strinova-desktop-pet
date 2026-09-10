"""expr_menu_test.py —— 验证「内置引擎下表情菜单」真的能用

背景：表情菜单原本统一走 _mate_link.blends_dict()，那是【外置 Mate-Engine】
的日文表情表（にこり/笑い/…）。内置引擎的表情是 VRM 标准名（happy/blink/aa…），
两边对不上 → 在 3D 里点表情是落空的。

本测试验证：
  1. 切到 3D 后，菜单里出现「😊 表情」子菜单
  2. 菜单项是 VRM 表情名（不是日文）
  3. 点一个表情 → 顶点真的位移（__vertexDelta）
  4. 重置 → 顶点回到原位
  5. 窗口能报出当前模型的表情列表
"""
from __future__ import annotations

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

import pet as pet_mod  # noqa: E402  必须先 import pet（模块级预加载 QtWebEngine）

from PyQt6.QtCore import QTimer, QEventLoop  # noqa: E402
from PyQt6.QtWidgets import QApplication, QMenu  # noqa: E402

PASS, FAIL = [], []


def wait(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))
    return cond


def find_menu(menu, keyword):
    for a in menu.actions():
        sub = a.menu()
        if sub and keyword in a.text():
            return sub
    return None


def main() -> int:
    app = QApplication(sys.argv)

    pet = pet_mod.PetWindow()
    pet.show()
    wait(1200)

    print("\n[1] 切到内置 3D…")
    pet.switch_face()
    for _ in range(40):
        wait(300)
        if getattr(pet, '_web3d_ready', False):
            break
    check("3D 已就绪", bool(getattr(pet, '_web3d_ready', False)))
    win = getattr(pet, '_web3d_win', None)
    check("3D 窗口存在", win is not None)
    wait(2500)

    print("\n[2] 表情列表…")
    exprs = []
    for _ in range(20):
        exprs = win.expressions() if win else []
        if exprs:
            break
        wait(400)
    check("窗口能报出表情列表", bool(exprs), f"{len(exprs)} 个")
    print(f"       {exprs}")

    print("\n[3] 菜单结构…")
    menu = pet.build_menu() if hasattr(pet, 'build_menu') else None
    if menu is None:
        # 找构建菜单的方法
        for cand in ('_build_menu', 'make_menu', 'build_tray_menu', '_build_tray_menu'):
            if hasattr(pet, cand):
                menu = getattr(pet, cand)()
                break
    if menu is None:
        try:
            menu = pet.tray.contextMenu()
        except Exception:
            menu = None
    check("能拿到菜单", menu is not None)

    if menu is not None:
        m3d = find_menu(menu, '3D 控制')
        check("存在「3D 控制」子菜单", m3d is not None)
        if m3d is not None:
            me = find_menu(m3d, '表情')
            check("存在「表情」子菜单", me is not None)
            if me is not None:
                items = [a.text() for a in me.actions() if a.text()]
                print(f"       表情菜单: {items}")
                has_vrm = any(('happy' in t or 'blink' in t or 'aa' in t) for t in items)
                has_jp = any(('にこり' in t or '笑い' in t) for t in items)
                check("菜单是 VRM 表情名（非日文 Mate 表）", has_vrm and not has_jp)

    print("\n[4] 点表情 → 顶点真的动了…")
    js = lambda code, t=10000: _run_js(win, code, t)  # noqa: E731
    # ★ 先关掉自动眨眼：否则 blink 每几百毫秒变一次权重，
    #   「基准」永远不是 0，重置也回不到原位（测试会假失败）。
    js("window.setBlinkEnabled(false)")
    wait(600)
    js("window.setExpression('neutral', 0)")
    wait(900)
    base = js("window.__vertexDelta()")
    print(f"       基准: {base}")
    check("关闭自动眨眼后基准为 0", base and '"nz":0' in str(base), str(base))
    js("window.setExpression('happy', 1.0)")
    wait(1200)
    hap = js("window.__vertexDelta()")
    print(f"       happy: {hap}")
    check("happy 改变了顶点", hap and hap != base and '"nz":0' not in str(hap))

    js("window.setExpression('blink', 1.0)")
    wait(1200)
    blk = js("window.__vertexDelta()")
    print(f"       blink: {blk}")
    check("blink 改变了顶点", blk and '"nz":0' not in str(blk))

    js("window.setBlinkEnabled(false)")
    js("window.setExpression('neutral', 0)")
    wait(1200)
    rst = js("window.__vertexDelta()")
    print(f"       重置后: {rst}")
    check("重置回到原位", rst and '"nz":0' in str(rst))

    print("\n[5] pet.py 命令链路（_mate3d_cmd → web）…")
    pet._mate3d_cmd('blend_set', name='happy', value=100.0)
    wait(1200)
    via_cmd = js("window.__vertexDelta()")
    print(f"       经 _mate3d_cmd: {via_cmd}")
    check("_mate3d_cmd('blend_set') 生效", via_cmd and '"nz":0' not in str(via_cmd))
    pet._mate3d_cmd('blend_reset')
    wait(1500)
    after = js("window.__vertexDelta()")
    print(f"       blend_reset 后: {after}")
    check("_mate3d_cmd('blend_reset') 生效", after and '"nz":0' in str(after))

    print("\n" + "=" * 60)
    print(f"结果：{len(PASS)} 通过 / {len(FAIL)} 失败")
    if FAIL:
        print(f"失败项: {FAIL}")
    print("=" * 60)

    try:
        pet.close()
    except Exception:
        pass
    return 1 if FAIL else 0


_boxes: dict = {}


def _run_js(win, code, timeout=10000):
    """在窗口页面上执行 JS 并等结果（走事件循环）"""
    box = {"v": None, "done": False}

    def _cb(v):
        box["v"] = v
        box["done"] = True

    win.page.runJavaScript(code, _cb)
    t = 0
    while not box["done"] and t < timeout:
        wait(100)
        t += 100
    return box["v"]


if __name__ == "__main__":
    sys.exit(main())
