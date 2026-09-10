"""panel_3d_test.py —— 验证设置面板「形象角色」里的 3D 选项

用户需求：设置面板 → 形象角色 → 能选 3D 桌宠（不是只有右键菜单）

验证：
  1. 角色列表第一项是「3D 米雪儿」，且 UserRole 是哨兵值
  2. 列表有「2D 图片角色」分组标题
  3. 点 3D 条目 → 真的切到 3D（_in3d=True，窗口出现）
  4. 再点普通图片角色 → 退回 2D（_in3d=False）
  5. 当前角色标签显示正确
"""
from __future__ import annotations

import io
import os
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.environ.setdefault(
    "QTWEBENGINE_CHROMIUM_FLAGS",
    "--ignore-gpu-blocklist --enable-gpu-rasterization --enable-unsafe-swiftshader",
)

import pet as pet_mod  # 必须先 import pet

from PyQt6.QtCore import QTimer, QEventLoop, Qt
from PyQt6.QtWidgets import QApplication

import settings_panel as sp

PASS, FAIL = [], []


def wait(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))
    return cond


def main() -> int:
    app = QApplication(sys.argv)
    pet = pet_mod.PetWindow()
    pet.show()
    wait(1500)

    panel = pet.open_settings_panel()
    if panel is None:
        panel = getattr(pet, '_settings_panel', None)
    check("设置面板能打开", panel is not None)
    if panel is None:
        return 1
    wait(1200)
    panel.refresh_all()
    wait(600)

    print("\n[1] 角色列表内容…")
    items = []
    for i in range(panel.role_list.count()):
        it = panel.role_list.item(i)
        items.append((it.text(), it.data(Qt.ItemDataRole.UserRole)))
    for t, r in items[:6]:
        print(f"       {t!r}  role={r!r}")

    first_txt, first_role = items[0]
    check("第一项是 3D 条目", first_role == sp._ROLE_3D, f"role={first_role!r}")
    check("3D 条目文案含「3D」", '3D' in first_txt, first_txt)
    check("有「2D 图片角色」分组标题",
          any('2D 图片角色' in t for t, _ in items),
          str([t for t, _ in items[:3]]))
    check("3D 条目不指向任何图片角色",
          first_role not in (getattr(pet, 'roles', []) or []))

    print("\n[2] 点 3D 条目 → 切到 3D…")
    check("点击前是 2D", not getattr(pet, '_in3d', False))
    panel._on_role_clicked(panel.role_list.item(0))
    for _ in range(40):
        wait(400)
        if getattr(pet, '_web3d_ready', False):
            break
    check("已切到 3D（_in3d=True）", bool(getattr(pet, '_in3d', False)))
    win = getattr(pet, '_web3d_win', None)
    check("3D 窗口已创建并可见", win is not None and win.isVisible(),
          f"win={win} visible={win.isVisible() if win else None}")
    panel.refresh_all()
    wait(600)
    cur_txt = panel.lbl_cur_role.text()
    print(f"       当前角色标签: {cur_txt!r}")
    check("标签显示 3D", '3D' in cur_txt, cur_txt)
    it0 = panel.role_list.item(0).text()
    check("列表首项标记 ←当前", '←当前' in it0, it0)

    print("\n[3] 点普通图片角色 → 退回 2D…")
    target = None
    for i in range(1, panel.role_list.count()):
        it = panel.role_list.item(i)
        r = it.data(Qt.ItemDataRole.UserRole)
        if r and r != sp._ROLE_3D:
            target = (i, it.text(), r)
            break
    check("列表里有可选的 2D 图片角色", target is not None,
          str(target[1]) if target else "无")
    if target:
        i, txt, role = target
        panel._on_role_clicked(panel.role_list.item(i))
        wait(2500)
        check("已退回 2D（_in3d=False）", not getattr(pet, '_in3d', False))
        check("2D 桌宠已显示", pet.isVisible())
        check("切换到了该角色", getattr(pet, 'role', None) == role,
              f"当前={getattr(pet, 'role', None)!r} 期望={role!r}")

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


if __name__ == "__main__":
    sys.exit(main())
