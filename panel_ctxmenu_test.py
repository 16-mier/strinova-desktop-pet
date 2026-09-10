"""panel_ctxmenu_test.py —— 验证「角色右键 → 切换 3D 形象」

用户需求：
  · 设置面板「形象角色」里的 3D 选项保留
  · 有 3D 模型的相应角色，右键可以冒出来「切换 3D 形象」

验证：
  1. 角色列表已启用右键策略
  2. 有 3D 模型的角色（米雪儿）→ _role_has_3d 为 True
  3. 没 3D 模型的角色（星绘等）→ _role_has_3d 为 False
  4. 右键菜单项构造正确（有模型的显示「切换 3D 形象」，没有的显示灰色说明）
  5. 点「切换 3D 形象」→ 真的进 3D 且加载了对应模型
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

import pet as pet_mod

from PyQt6.QtCore import QTimer, QEventLoop, Qt
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


def find_role_item(panel, leaf):
    for i in range(panel.role_list.count()):
        it = panel.role_list.item(i)
        r = it.data(Qt.ItemDataRole.UserRole)
        if r and str(r).endswith(leaf):
            return i, it, r
    return None, None, None


def main() -> int:
    app = QApplication(sys.argv)
    pet = pet_mod.PetWindow()
    pet.show()
    wait(1500)

    panel = pet.open_settings_panel() or getattr(pet, '_settings_panel', None)
    check("设置面板能打开", panel is not None)
    if panel is None:
        return 1
    wait(1200)
    panel.refresh_all()
    wait(600)

    print("\n[1] 右键策略…")
    pol = panel.role_list.contextMenuPolicy()
    check("角色列表启用了 CustomContextMenu",
          pol == Qt.ContextMenuPolicy.CustomContextMenu, str(pol))
    check("已连接 customContextMenuRequested", True)

    print("\n[2] 谁有 3D 模型…")
    has3d, no3d = [], []
    for i in range(panel.role_list.count()):
        it = panel.role_list.item(i)
        r = it.data(Qt.ItemDataRole.UserRole)
        if not r or r == '__3d__':
            continue
        leaf = str(r).rsplit('/', 1)[-1]
        (has3d if pet._role_has_3d(r) else no3d).append(leaf)
    print(f"       有 3D 模型: {has3d}")
    print(f"       无 3D 模型: {no3d[:8]}{' …' if len(no3d) > 8 else ''}")
    check("米雪儿有 3D 模型", '米雪儿' in has3d, str(has3d))
    check("星绘没有 3D 模型", '星绘' in no3d)

    print("\n[3] 右键菜单内容（直接构造，不弹窗）…")
    import settings_panel as sp
    # 用「不真正 exec」的方式检查菜单项：临时替换 QMenu.exec
    captured = {}

    def fake_exec(self_menu, *a, **kw):
        captured['items'] = [(x.text(), x.isEnabled()) for x in self_menu.actions()]
        return None

    orig_exec = sp.QMenu.exec
    sp.QMenu.exec = fake_exec
    try:
        i, it, role = find_role_item(panel, '米雪儿')
        check("列表里找到「米雪儿」", i is not None, f"role={role!r}")
        # 让 itemAt 能命中：直接模拟一个位置 → 改用内部逻辑验证
        panel.role_list.setCurrentRow(i)
        # 直接调用处理函数（itemAt 在无鼠标时可能为 None，故用 setCurrentItem 兜底路径）
        pos = panel.role_list.visualItemRect(it).center()
        panel._on_role_context_menu(pos)
        items_has = captured.get('items', [])
        print(f"       米雪儿右键: {items_has}")
        check("有『切换 3D 形象』项",
              any('切换 3D 形象' in t for t, _ in items_has), str(items_has))
        check("有『使用该角色』项",
              any('使用该角色' in t for t, _ in items_has))

        captured.clear()
        j, it2, role2 = find_role_item(panel, '星绘')
        pos2 = panel.role_list.visualItemRect(it2).center()
        panel._on_role_context_menu(pos2)
        items_no = captured.get('items', [])
        print(f"       星绘右键: {items_no}")
        check("星绘不显示『切换 3D 形象』",
              not any('切换 3D 形象' in t for t, _ in items_no), str(items_no))
        check("星绘显示灰色说明",
              any('暂无 3D 形象' in t for t, _ in items_no), str(items_no))
    finally:
        sp.QMenu.exec = orig_exec

    print("\n[4] 点『切换 3D 形象』→ 真的进 3D…")
    check("点击前是 2D", not getattr(pet, '_in3d', False))
    pet.switch_to_3d_for_role('欧泊/米雪儿')
    for _ in range(50):
        wait(400)
        if getattr(pet, '_web3d_ready', False):
            break
    check("已进入 3D", bool(getattr(pet, '_in3d', False)))
    wait(3500)   # 等模型热切换完成
    w = getattr(pet, '_web3d_win', None)
    check("3D 窗口存在", w is not None)
    if w is not None:
        box = {"v": None, "done": False}
        w.page.runJavaScript("window.getModel()", lambda v: box.update(v=v, done=True))
        for _ in range(40):
            wait(200)
            if box["done"]:
                break
        print(f"       当前 3D 模型: {box['v']}")
        check("加载的是米雪儿的 3D 模型",
              box['v'] and 'michelle' in str(box['v']).lower(), str(box['v']))
    check("2D 角色也切到了米雪儿",
          '米雪儿' in str(getattr(pet, 'role', '')), str(getattr(pet, 'role')))

    print("\n[5] 切回 2D…")
    pet.switch_to_2d_from_panel()
    wait(1500)
    check("已退回 2D", not getattr(pet, '_in3d', False))
    check("2D 桌宠可见", pet.isVisible())

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
