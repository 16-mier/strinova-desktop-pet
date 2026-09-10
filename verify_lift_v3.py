"""verify_lift_v3.py —— 验证「从腰部被提起来」第三版改造

对应用户本轮反馈：「现在的动作和拖动的动作都过于生硬了」
以及明确要求：「是从腰部被提起来」。

本轮改了 5 件事，逐条验收：
  1. springBone 调参   —— 把 ζ 从 1.40（过阻尼钢丝）降到 ~0.18（欠阻尼会飘）
  2. 骨骼下垂 U 形     —— spine/chest/neck/head 前弯 + shoulder 下沉（旧版完全没有）
  3. 提起高度 + 横向比 —— 提升高度必须 > 横向摆动位移（旧版是 11cm vs 22cm，反的）
  4. 垂直速度通道      —— setDragging 收 dy，向上提/向下放能驱动姿态
  5. 归位正确          —— 松手后回到 restRot，不能打回 T-pose

方向符号（PITCH_FWD / LEG_Z_MIRROR）用页面里的 __probeSigns() 实测标定，
不靠肉眼、不靠猜 —— 因为 read_image 在本环境不可用。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

# Windows 控制台默认 GBK，中文/符号会炸；强制 UTF-8 输出
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pet  # noqa: E402  ★ 必须先 import pet（模块级预加载 QtWebEngine）
from PyQt6.QtWidgets import QApplication  # noqa: E402

import web3d_pet as w3  # noqa: E402

ROOT = Path(__file__).resolve().parent
PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = ""):
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail else ""))


class Page:
    """runJavaScript 的同步包装（QtWebEngine 的 JS 是异步回调，这里轮询等结果）"""

    def __init__(self, win, app):
        self.win, self.app = win, app

    def js(self, expr: str, timeout: float = 20.0):
        box = {}
        self.win.page.runJavaScript("(function(){try{return JSON.stringify(" + expr + ");}"
                                    "catch(e){return JSON.stringify({__err:String(e)});}})()",
                                    lambda v: box.setdefault("v", v))
        t0 = time.time()
        while "v" not in box and time.time() - t0 < timeout:
            self.app.processEvents()
            time.sleep(0.02)
        raw = box.get("v")
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except Exception:
            return raw

    def wait_ready(self, timeout: float = 90.0):
        t0 = time.time()
        while time.time() - t0 < timeout:
            self.app.processEvents()
            time.sleep(0.05)
            if self.win._ready and self.js("!!(window.__dragState)", timeout=5):
                # 模型加载完还要等一帧让 restRot 记录完
                time.sleep(0.6)
                return True
        return False


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    print("\n=== 0. 源码层：本轮改造是否真的落进文件 ===")
    html = (ROOT / "web3d" / "pet_viewer.html").read_text(encoding="utf-8")
    py = (ROOT / "web3d_pet.py").read_text(encoding="utf-8")
    check("springBone 调参函数已加入", "function tuneSpringBone" in html)
    check("按链名分组调参（裙/发/披风分别给值）", "SB_RULES" in html and "qun_" in html)
    check("拖拽时动态改 dragForce", "function stepSpringBoneDrag" in html)
    check("[关键] 没有设 center（桌宠要惯性甩动，设了=焊死）",
          "joint.center" not in html and "j.center =" not in html)
    check("骨骼下垂弹簧已加入（spineSag/neckSag/shoulderSag）",
          all(k in html for k in ("spineSag", "neckSag", "shoulderSag")))
    check("肩带下沉已实现（旧版完全没用 shoulder）",
          "leftShoulder" in html and "sagH" in html)
    check("提起高度已从 0.110 提到 0.180", "dA * 0.180" in html)
    check("整体倾斜系数已从 0.42 降到 0.20", "sway * 0.20" in html)
    check("垂直通道 setDragging(on, dx, dy)", "window.setDragging = (on, dx, dy)" in html)
    check("归位回到 restRot（不再 set(0,0,0) 打回 T-pose）",
          "restRot[n]" in html)
    check("Python 侧传了 dy", "_notify_drag_visual(self, dragging: bool, dx: int = 0, dy: int = 0)" in py
          and "self._notify_drag_visual(True, dx, dy)" in py)
    # 旧注释必须已更正（实测 209 joint 全是导出器默认值，不是原作者调的）
    check("过时注释已更正（不再是'参数是原作者调的'）",
          "参数是原作者调的，质量最好" not in html)

    print("\n=== 起窗口（加载 29MB 模型需要时间）===")
    win = w3.Web3DPetWindow(model="michelle", size=(300, 420))
    win.move(300, 200)
    win.show()
    p = Page(win, app)
    ok = p.wait_ready()
    check("模型加载完成、诊断接口就绪", bool(ok), f"_ready={win._ready}")
    if not ok:
        print("\n模型没加载起来，后续运行时检查跳过")
        return report()

    print("\n=== 1. 方向符号实测标定（__probeSigns）===")
    pr = p.js("window.__probeSigns()")
    print("     probe =", json.dumps(pr, ensure_ascii=False))
    if isinstance(pr, dict) and "pitch" in pr:
        chk = pr["pitch"]
        check("脊柱 rotation.x 负号 = 前弯（PITCH_FWD=-1 正确）",
              chk.get("verdict") == -1,
              f"headDeltaZ={chk.get('headDeltaZ')} → {chk.get('note')}")
        lm = pr.get("legMirror", {})
        expect = lm.get("verdict")
        check("左右腿 Z 轴镜像方向已判定",
              expect in (1, -1),
              f"左脚ΔX={lm.get('leftFootDeltaX')} 右脚ΔX={lm.get('rightFootDeltaX')} "
              f"→ {lm.get('note')}")
        cur = pr.get("current", {})
        check("代码里的 LEG_Z_MIRROR 与实际一致",
              cur.get("LEG_Z_MIRROR") == expect,
              f"代码={cur.get('LEG_Z_MIRROR')} 实测={expect}")
    else:
        check("__probeSigns 可用", False, str(pr))

    print("\n=== 2. springBone 调参已生效（从过阻尼钢丝 → 欠阻尼）===")
    sb = p.js("window.__springBoneState()")
    print("     springBone =", json.dumps(sb, ensure_ascii=False))
    if isinstance(sb, dict) and sb.get("native"):
        check("用的是模型原生 springBone", sb.get("native") is True,
              f"joints={sb.get('joints')}")
        check("调参已应用", sb.get("applied") is True)
        f0 = sb.get("first", {})
        # 模型原始值：stiffness=1.0、gravityPower=0.0、dragForce=0.5、hitRadius=0.0
        # （209 个 joint 全一样，是 Blender 导出器的默认落值，没人调过）
        check("stiffness 已从 1.0 明显下调（社区共识：这是'摇动范围'）",
              f0.get("stiffness", 9) < 0.5,
              f"stiffness={f0.get('stiffness')}（原 1.0）")
        check("gravityPower 保持模型原值 0（不加：加了会把头发压塌）",
              (f0.get("gravityPower") or 0) == 0,
              f"gravityPower={f0.get('gravityPower')}")
        check("dragForce 已从 0.5 明显下调（社区共识：这是'摇动时间'，0.5=猛踩刹车）",
              f0.get("dragForce", 9) < 0.20,
              f"dragForce={f0.get('dragForce')}（原 0.5）")
        # ζ = γ/ω：原始组合是过阻尼（约 1.4，零回摆=钢丝）；调后应落在自然的欠阻尼区
        B, dt = 0.034, 1.0 / 120.0
        try:
            import math
            omega = math.sqrt(f0.get("stiffness", 0.3) / (B * dt))
            gamma = -math.log(1 - f0.get("dragForce", 0.1)) * 120
            zeta = gamma / omega
        except Exception:
            zeta = float("nan")
        check("阻尼比落在自然区间 0.15~0.75（<1 才有回摆，不是钢丝）",
              0.15 < zeta < 0.75,
              f"ζ={zeta:.3f}（模型原始组合约 1.40=过阻尼钢丝）")
        check("hitRadius 远低于骨段长一半（0.017），避免碰撞球互顶崩链",
              (f0.get("hitRadius") or 0) < 0.017,
              f"hitRadius={f0.get('hitRadius')}")
        g = sb.get("groups", {})
        check("按链分组调参（头发/裙摆分开）", len(g) >= 2, f"分组={g}")
    else:
        check("原生 springBone 存在", False, str(sb))

    print("\n=== 3. 拖动反应：骨骼下垂 U 形真的出现 ===")
    # 冻结待机微动，避免噪声干扰数值判读
    p.js("window.__setIdleMotion(false)")
    time.sleep(0.3)

    idle = p.js("window.__dragState()")
    print("     静止 =", json.dumps(idle, ensure_ascii=False))
    check("静止时下垂量为 0", (idle or {}).get("spineSag", 9) < 0.05,
          f"spineSag={idle.get('spineSag')}")

    # 模拟「被拎起来」：持续水平拖动
    p.js("window.setDragging(true, 20, 0)")
    for i in range(30):
        p.js(f"window.setDragging(true, {12 if i % 2 else -8}, 0)")
        app.processEvents(); time.sleep(0.03)
    time.sleep(0.5)
    drag = p.js("window.__dragState()")
    print("     拖动中 =", json.dumps(drag, ensure_ascii=False))
    d = drag or {}
    check("dragAmount 已升到接近 1（被拎起来）", d.get("amount", 0) > 0.6,
          f"amount={d.get('amount')}")
    check("★ 脊柱下垂已启动（U 形左上臂）", d.get("spineSag", 0) > 0.25,
          f"spineSag={d.get('spineSag')}")
    check("★ 颈头下坠已启动（U 形顶部塌下）", d.get("neckSag", 0) > 0.25,
          f"neckSag={d.get('neckSag')}")
    check("★ 肩带下沉已启动（旧版完全缺失）", d.get("shoulderSag", 0) > 0.25,
          f"shoulderSag={d.get('shoulderSag')}")

    # 关键几何验收：横向摆动位移必须【小于】提起高度（旧版是反的，22cm vs 11cm）
    geo = p.js("window.__sceneGeo()")
    print("     几何 =", json.dumps(geo, ensure_ascii=False))
    g = geo or {}
    check("★ 提升高度 > 横向摆动（观感是'被提起来'而非'左右平移'）",
          g.get("lift", 0) > g.get("lateral", 9),
          f"lift={g.get('lift')} lateral={g.get('lateral')}（旧版约 0.11 vs 0.22）")
    check("提升高度达到身高的 ~11%（0.18m 量级）", g.get("lift", 0) > 0.14,
          f"lift={g.get('lift')}")
    check("整体倾斜已收小（不再是主力）", abs(g.get("rotZ", 9)) < 0.16,
          f"rotZ={g.get('rotZ')}（旧版上限 0.24）")
    check("scale.y 拉伸已收小（不再像橡皮人）", abs(g.get("scaleY", 9) - 1) < 0.015,
          f"scaleY={g.get('scaleY')}（旧版 1.02）")

    print("\n=== 3b. ★ U 形姿态分解（真实骨骼角度，不是弹簧值）===")
    print("     下垂链 =", json.dumps({
        k: g.get(k) for k in ("spineX", "chestX", "neckX", "headX",
                              "shoulderLZ", "shoulderRZ", "footLX", "lowerLegLX")
    }, ensure_ascii=False))
    # PITCH_FWD = -1 → 前弯是负值。腰→头顶累计前弯应达 25°~40°（约 0.45~0.70 rad）
    chain = sum(abs(g.get(k) or 0) for k in ("spineX", "chestX", "neckX", "headX"))
    check("★ 脊柱链累计前弯 ≥ 0.40 rad（约 23°，够读出 U 形）", chain >= 0.40,
          f"累计={chain:.3f} rad（spine+chest+neck+head）")
    check("★ 肩带下沉已生效（旧版肩是平的）",
          abs(g.get("shoulderLZ") or 0) > 0.10 and abs(g.get("shoulderRZ") or 0) > 0.10,
          f"shoulderLZ={g.get('shoulderLZ')} shoulderRZ={g.get('shoulderRZ')}")
    check("★ 脚背绷直下垂（'被提着'最强提示）", abs(g.get("footLX") or 0) > 0.20,
          f"footLX={g.get('footLX')}")

    print("\n=== 4. 垂直通道：向上提 / 向下放要有不同反应 ===")
    # 向上猛提 → stretch 为正 → 下垂量被"抽紧"减小（看真实骨骼角度，不是弹簧）
    sag_before = g.get("spineX")
    for _ in range(20):
        p.js("window.setDragging(true, 0, -30)")
        app.processEvents(); time.sleep(0.03)
    up = p.js("window.__dragState()")
    upg = p.js("window.__sceneGeo()")
    print("     上提 =", json.dumps(up, ensure_ascii=False))
    check("上提时垂直速度被记录（velY 明显为负）", (up or {}).get("velY", 0) < -3,
          f"velY={up.get('velY')}")
    check("上提时身体被'抽紧'→ 脊柱前弯减小",
          abs((upg or {}).get("spineX") or 0) < abs(sag_before or 0) * 0.995,
          f"上提 spineX={upg.get('spineX')} vs 水平拖 {sag_before}")

    # 向下快放 → velY 为正
    for _ in range(15):
        p.js("window.setDragging(true, 0, 30)")
        app.processEvents(); time.sleep(0.03)
    dn = p.js("window.__dragState()")
    check("下放时垂直速度反向（velY 明显为正）", (dn or {}).get("velY", 0) > 3,
          f"velY={dn.get('velY')}")

    print("\n=== 5. 松手归位：回 restRot，不能打回 T-pose ===")
    p.js("window.setDragging(false, 0, 0)")
    for _ in range(60):
        app.processEvents(); time.sleep(0.03)
    time.sleep(0.8)
    rest = p.js("window.__dragState()")
    print("     松手后 =", json.dumps(rest, ensure_ascii=False))
    r = rest or {}
    check("放下后下垂量归零", r.get("spineSag", 9) < 0.05 and r.get("neckSag", 9) < 0.05,
          f"spineSag={r.get('spineSag')} neckSag={r.get('neckSag')}")
    check("放下后 dragAmount 归零", r.get("amount", 9) < 0.05, f"amount={r.get('amount')}")

    pose = p.js("window.__sceneGeo()")
    print("     归位姿态 =", json.dumps({
        k: (pose or {}).get(k) for k in ("armLZ", "spineX", "neckX", "footLX", "lowerLegLX")
    }, ensure_ascii=False))
    po = pose or {}
    check("★ 松手后手臂仍是自然垂放（没被打回 T-pose）",
          abs(po.get("armLZ") or 0) > 0.5,
          f"leftUpperArm.rotation.z={po.get('armLZ')}（T-pose 时约 0；自然垂放约 ±1.45）")
    check("松手后脊柱/颈/脚全部回静止值",
          abs(po.get("spineX") or 0) < 0.02 and abs(po.get("neckX") or 0) < 0.02
          and abs(po.get("footLX") or 0) < 0.02,
          f"spineX={po.get('spineX')} neckX={po.get('neckX')} footLX={po.get('footLX')}")

    print("\n=== 6. 帧率未受影响 ===")
    p.js("window.__resetStats && window.__resetStats()")
    time.sleep(4.0)
    fps = p.js("window.__fps ? window.__fps() : null")
    print("     fps =", fps)
    check("帧率仍然 ≥ 100（加了骨骼下垂与 springBone 动态改参没有掉帧）",
          isinstance(fps, (int, float)) and fps >= 100, f"fps={fps}")
    # 顺带确认没有每帧异常（之前 R 遮蔽导致 animate 每帧抛错）
    err = p.js("window.__lastError || ''")
    check("主循环无残留异常（R 遮蔽 bug 已修）", not err, f"lastError={err!r}")

    try:
        win.close()
    except Exception:
        pass
    return report()


def report():
    print("\n" + "=" * 60)
    print(f"结果：PASS {len(PASS)} / FAIL {len(FAIL)}")
    if FAIL:
        print("失败项：")
        for f in FAIL:
            print("  -", f)
    print("=" * 60)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
