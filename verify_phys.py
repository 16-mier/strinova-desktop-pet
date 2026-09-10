"""verify_phys.py —— 验证原生物理（VRMC_springBone）真的在工作

背景：模型已换成 michelle_phys.vrm，它自带从 MMD 刚体转出来的 springBone
（39 条链 / 209 joint / 19 collider）。three-vrm 会自动接管，自研物理让位。

要验证的三件事：
  1. three-vrm 确实建立了 springBoneManager（而不是静默失败）
  2. 角色一动，头发/裙摆骨骼的四元数真的跟着变（物理在跑，不是摆设）
  3. 物理不会发散（骨骼角度不出现离谱值）
  4. 帧率仍然达标
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pet  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

import web3d_pet as w3  # noqa: E402

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail else ""))


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    win = w3.Web3DPetWindow(model="michelle", size=(280, 380))
    win.move(300, 200)
    win.show()
    win.raise_()

    def js(code, wait=8.0):
        box = {}
        win.page.runJavaScript(code, lambda v: box.__setitem__("v", v))
        t = time.time() + wait
        while time.time() < t and "v" not in box:
            app.processEvents()
            time.sleep(0.005)
        return box.get("v")

    for _ in range(400):
        app.processEvents()
        time.sleep(0.02)
        if js("window.morphInfo && window.morphInfo() ? 1 : 0", wait=2) == 1:
            break
    for _ in range(60):
        app.processEvents()
        time.sleep(0.02)

    print("\n=== 1. springBoneManager 已建立 ===")
    st = js("JSON.stringify(window.__hairStats())")
    print(f"    {st}")
    s = json.loads(st or "{}")
    check("使用原生物理（不是自研）", s.get("native") is True, f"stats={s}")
    check("joint 数量正常（>100）", (s.get("joints") or 0) > 100, f"joints={s.get('joints')}")

    print("\n=== 2. 静止时物理应收敛（不该自己乱抖） ===")
    js("window.__setIdleMotion(false); window.setBlinkEnabled(false); 'ok'")
    # ⚠ 先等【姿势切换本身】带起的摆动停下来，再记基准。
    #   否则基准是在"身体刚归位、头发还在甩"的瞬间取的，测出来的
    #   全是那次切换的惯性，不是自激振荡（曾经在这里误判过）。
    for _ in range(100):
        app.processEvents()
        time.sleep(0.02)
    # ⚠ __hairDelta 的原生模式是"第一次调用记录基准、之后才测量"，
    #   所以必须先空调一次把它喂饱，再读第二次才是真实活动量。
    js("window.__resetPhysProbe(); 'ok'")
    time.sleep(0.3)
    js("window.__hairDelta()")            # 记录基准
    time.sleep(1.2)
    for _ in range(20):
        app.processEvents()
        time.sleep(0.01)
    idle = js("window.__hairDelta()")     # 这一次才是测量
    print(f"    静止 1.2 秒后: {idle}")
    i = json.loads(idle or "{}")
    check("静止时基本收敛（残留摆动 < 12°，不是自激振荡）",
          (i.get("maxAngle") or 0) < 0.21,
          f"maxAngle={i.get('maxAngle')} worst={i.get('worst')}")

    print("\n=== 3. 身体运动时物理必须跟着动 ===")
    js("window.__resetPhysProbe(); 'ok'")
    time.sleep(0.3)
    js("window.__hairDelta()")            # 记录基准
    # 用拖动反应给身体一个大幅摆动，物理应该被甩起来
    js("window.setDragging(true, 0); 'ok'")
    time.sleep(0.3)
    for i in range(10):
        js(f"window.setDragging(true, {60 if i % 2 == 0 else -60}); ''", wait=2)
        time.sleep(0.06)
        app.processEvents()
    time.sleep(0.5)
    for _ in range(20):
        app.processEvents()
        time.sleep(0.01)
    moved = js("window.__hairDelta()")
    print(f"    拖动甩动后: {moved}")
    m = json.loads(moved or "{}")
    check("物理骨骼确实被甩动（maxAngle 明显 > 0）",
          (m.get("maxAngle") or 0) > 0.02,
          f"maxAngle={m.get('maxAngle')} worst={m.get('worst')} moving={m.get('moving')}/{m.get('sampled')}")

    print("\n=== 4. 物理不发散（没有翻飞的骨骼） ===")
    js("window.setDragging(false, 0); 'ok'")
    worst = 0.0
    for _ in range(40):
        app.processEvents()
        time.sleep(0.05)
        d = js("window.__hairDelta()", wait=2)
        try:
            worst = max(worst, json.loads(d or "{}").get("maxAngle") or 0)
        except Exception:
            pass
    # ⚠ 判据说明：加了"软弹簧"之后，用力甩动时头发摆到 100° 上下是【正常的】
    #   （真头发也会甩成这样），所以不能再用"偏角 < 90°"当发散判据 ——
    #   那是按旧的硬弹簧（ζ=1.4、几乎不摆）写的阈值。
    #   真正能区分"发散"和"甩得开"的是两件事：
    #     ① 四元数是否出现 NaN/Infinity（数值爆炸的硬信号）
    #     ② 松手后能不能回落到接近静止（发散的话永远回不来）
    sanity = js("window.__physSanity()", wait=2)
    try:
        sn = json.loads(sanity or "{}")
    except Exception:
        sn = {}
    check("四元数无 NaN/Infinity（数值健全）",
          (sn.get("nonFinite") or 0) == 0,
          f"nonFinite={sn.get('nonFinite')} maxQuat={sn.get('maxQuatComponent')}")
    check("甩动幅度在合理范围内（不翻飞）",
          worst < 2.62, f"观测到的最大偏角={worst:.3f} rad ({worst*57.3:.1f}°)")

    # 松手静置后必须回落 —— 这是"不发散"最有力的证据
    js("window.__resetPhysProbe(); 'ok'")
    time.sleep(0.3)
    js("window.__hairDelta()")            # prime
    for _ in range(60):
        app.processEvents()
        time.sleep(0.03)
    settled = js("window.__hairDelta()", wait=2)
    try:
        se = json.loads(settled or "{}")
    except Exception:
        se = {}
    check("松手静置后回落到接近静止（证明是阻尼振荡而非发散）",
          (se.get("maxAngle") or 0) < 0.25,
          f"静置后 maxAngle={se.get('maxAngle')}（甩动峰值 {worst:.3f}）")

    print("\n=== 5. 帧率 ===")
    fps = None
    for _ in range(50):
        app.processEvents()
        time.sleep(0.03)
        fps = js("window.__fps()", wait=2)
        if isinstance(fps, (int, float)) and fps > 0:
            break
    check("帧率 ≥ 100（170 joints 原生物理）",
          isinstance(fps, (int, float)) and fps >= 100, f"fps={fps}")

    win.close()
    for _ in range(10):
        app.processEvents()

    print("\n" + "=" * 56)
    print(f"通过 {len(PASS)} / {len(PASS) + len(FAIL)}")
    for f in FAIL:
        print("  - 失败:", f)
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
