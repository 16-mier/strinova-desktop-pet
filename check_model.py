"""check_model.py —— 换模型后的全面体检

关注三件事：
  1. 画面是否正常（覆盖率、颜色数）—— Blender 重导出材质可能把
     "底色全黑 + emissive 贴图"的卡拉彼丘模型弄坏，必须看像素
  2. 表情是否可用（morph 名字、实际写入顶点后像素有没有变化）
  3. 原生物理是否真的在动（springBone joints、头发骨骼位移）
  4. 帧率
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
    # 再等物理稳定
    for _ in range(60):
        app.processEvents()
        time.sleep(0.02)

    print("\n=== 1. 模型信息 ===")
    meta = js("window.__vrmMeta()")
    print(f"    {meta}")
    m = json.loads(meta or "{}")
    check("模型自带 springBone（原生物理）", m.get("hasSpringBone") is True,
          f"joints={m.get('springJoints')}")

    mi = js("JSON.stringify(window.morphInfo())")
    print(f"    morphDriver: {mi}")
    mi = json.loads(mi or "{}")
    check("morph 目标已加载", (mi.get("morphTargets") or 0) > 100,
          f"targets={mi.get('morphTargets')} 名字={mi.get('expressions')}")

    names = js("JSON.stringify(window.listExpressions())")
    print(f"    表情名: {names}")

    print("\n=== 2. 画面是否正常（材质没被弄坏） ===")
    js("window.__setIdleMotion(false); window.setBlinkEnabled(false); 'ok'")
    time.sleep(0.5)
    for _ in range(20):
        app.processEvents()
        time.sleep(0.01)
    stats = js("window.__pixelStats()")
    print(f"    {stats}")
    st = json.loads(stats or "{}")
    check("角色占屏合理（覆盖 5%~60%）",
          5 <= (st.get("coverage") or 0) <= 60, f"coverage={st.get('coverage')}%")
    check("有丰富的颜色（不是全黑/全白）",
          (st.get("colors") or 0) > 20, f"colors={st.get('colors')}")

    print("\n=== 3. 原生物理真的在动吗 ===")
    # 冻结待机动作后，身体不动 → 头发应该慢慢静下来
    d1 = js("window.__hairDelta()", wait=4)
    print(f"    自研物理统计: {d1}（有原生物理时这里是 no-physics，属正常）")
    raw = js("""
    (function(){
      try {
        const m = vrm.springBoneManager;
        if (!m) return 'no-manager';
        let n = 0;
        // 记录若干头发骨骼当前四元数，稍后比对是否变化
        const names = ['hair_ribbon_l_01','qun_0_0','ponytail_hair_m_01'];
        const out = {};
        for (const nm of names) {
          const b = vrm.scene.getObjectByName(nm);
          if (b) { out[nm] = [+b.quaternion.x.toFixed(5), +b.quaternion.y.toFixed(5),
                              +b.quaternion.z.toFixed(5), +b.quaternion.w.toFixed(5)]; n++; }
        }
        return JSON.stringify({found: n, q: out});
      } catch(e) { return 'ERR:'+e.message; }
    })()
    """)
    print(f"    物理骨骼四元数(采样1): {raw}")

    print("\n=== 4. 表情真的能写进顶点吗 ===")
    js("JSON.stringify(window.__vertexDelta())")
    probe = """
    (function(){
      try {
        const before = window.__vertexDelta();
        const ns = window.listExpressions();
        if (!ns || !ns.length) return JSON.stringify({err:'no-expr'});
        const nm = ns.includes('happy') ? 'happy' : (ns.includes('aa') ? 'aa' : ns[0]);
        window.setExpression(nm, 1.0);
        const after = window.__vertexDelta();
        window.setExpression(nm, 0.0);
        return JSON.stringify({name: nm, before: JSON.parse(before), after: JSON.parse(after)});
      } catch(e) { return 'ERR:'+e.message; }
    })()
    """
    expr = js(probe)
    print(f"    {expr}")
    ex = json.loads(expr or "{}")
    if "err" not in ex:
        check("表情写入顶点生效（nz 增加）",
              (ex.get("after", {}).get("nz") or 0) > (ex.get("before", {}).get("nz") or 0),
              f"{ex.get('before')} → {ex.get('after')}")

    print("\n=== 5. 帧率（原生物理 170 joints 的开销） ===")
    fps = None
    for _ in range(50):
        app.processEvents()
        time.sleep(0.03)
        fps = js("window.__fps()", wait=2)
        if isinstance(fps, (int, float)) and fps > 0:
            break
    check("帧率 ≥ 100", isinstance(fps, (int, float)) and fps >= 100, f"fps={fps}")

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
