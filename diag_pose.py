# -*- coding: utf-8 -*-
"""diag_pose.py —— 诊断「看不到头和脚 + 默认展开双臂」

用户反馈：
  ① 显示不出来脚和头的部分
  ② 动作是默认的展开双臂

已确认的数学问题：
  取景用 camera.position.z = size.y * 1.25，FOV 25°
  → 可见高度 = 2 * 1.25 * size.y * tan(12.5°) = 0.554 * size.y
  → 只看到全身 55%，对焦点又在 0.62 高度 → 头顶 10% 和腿脚 34% 正好被裁

本脚本实测：
  · 模型网格清单（确认脚/腿的 mesh 在不在）
  · 蒙皮后的真实包围盒
  · 各角度下上臂旋转 → 手的落点，找出「手下垂」的正确角度
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent
SRV_DIR = HERE / "web3d"
sys.path.insert(0, str(HERE))

os.environ.setdefault(
    "QTWEBENGINE_CHROMIUM_FLAGS",
    "--ignore-gpu-blocklist --enable-gpu-rasterization --enable-unsafe-swiftshader",
)

from PyQt6.QtCore import QTimer, QUrl, QEventLoop
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PyQt6.QtWebEngineWidgets import QWebEngineView

from web3d_server import serve

W, H = 420, 560


class Page(QWebEnginePage):
    def javaScriptConsoleMessage(self, level, message, line, source):
        if level.name.startswith("Error") or "PD" in message:
            print(f"  [js] {message[:220]}")


HTML = r"""<!DOCTYPE html><html><head><meta charset="utf-8">
<style>html,body{margin:0;background:#2b2f3a;overflow:hidden}canvas{display:block}</style></head><body>
<script type="importmap">
{"imports":{"three":"./vendor/three.module.js","three/addons/":"./vendor/addons/"}}
</script>
<script type="module">
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { VRMLoaderPlugin } from './vendor/three-vrm.module.js';

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(25, 420/560, 0.01, 100);
const renderer = new THREE.WebGLRenderer({alpha:true, antialias:true, preserveDrawingBuffer:true});
renderer.setSize(420, 560);
renderer.toneMapping = THREE.NoToneMapping;
renderer.outputColorSpace = THREE.SRGBColorSpace;
document.body.appendChild(renderer.domElement);
scene.add(new THREE.AmbientLight(0xffffff, 0.55));
const d1 = new THREE.DirectionalLight(0xffffff, 0.6); d1.position.set(0.6,2,2.5); scene.add(d1);

let vrm = null;
window.__ready = false;

const loader = new GLTFLoader();
loader.register(p => new VRMLoaderPlugin(p));
loader.load('./models/michelle_expr.vrm', (g) => {
  vrm = g.userData.vrm;
  scene.add(vrm.scene);
  vrm.scene.rotation.y = 0;
  vrm.scene.traverse(o => { if (o.isMesh) o.frustumCulled = false; });
  console.log('PD ready bones=' + Object.keys(vrm.humanoid ? vrm.humanoid.humanBones : {}).length);
  window.__ready = true;
  (function loop(){ requestAnimationFrame(loop); renderer.render(scene,camera); })();
});

function posedBox(){
  const box = new THREE.Box3();
  const v = new THREE.Vector3();
  vrm.scene.updateMatrixWorld(true);
  vrm.scene.traverse(o => {
    if (!o.isMesh) return;
    const pos = o.geometry && o.geometry.attributes && o.geometry.attributes.position;
    if (!pos) return;
    const step = Math.max(1, Math.floor(pos.count / 3000));
    for (let i = 0; i < pos.count; i += step) {
      // ★ 关键：applyBoneTransform 会拿传入向量当「基准顶点」，
      //   必须先 fromBufferAttribute 填好，否则算出来是天文数字。
      v.fromBufferAttribute(pos, i);
      if (o.isSkinnedMesh && o.applyBoneTransform) {
        o.applyBoneTransform(i, v);
      }
      v.applyMatrix4(o.matrixWorld);
      box.expandByPoint(v);
    }
  });
  return box;
}

// 不蒙皮（rest pose）的包围盒 —— 就是原代码 Box3.setFromObject 用的东西
window.__restBox = () => {
  const b = new THREE.Box3().setFromObject(vrm.scene);
  const s = b.getSize(new THREE.Vector3());
  const c = b.getCenter(new THREE.Vector3());
  return JSON.stringify({
    min:[+b.min.x.toFixed(3),+b.min.y.toFixed(3),+b.min.z.toFixed(3)],
    max:[+b.max.x.toFixed(3),+b.max.y.toFixed(3),+b.max.z.toFixed(3)],
    size:[+s.x.toFixed(3),+s.y.toFixed(3),+s.z.toFixed(3)],
    center:[+c.x.toFixed(3),+c.y.toFixed(3),+c.z.toFixed(3)]
  });
};

// 每个 mesh 各自的包围盒（找有没有「离群顶点」把整体撑大）
window.__meshBoxes = () => {
  const out = [];
  vrm.scene.updateMatrixWorld(true);
  vrm.scene.traverse(o => {
    if (!o.isMesh) return;
    const b = new THREE.Box3().setFromObject(o);
    const s = b.getSize(new THREE.Vector3());
    out.push([o.name, +b.min.y.toFixed(3), +b.max.y.toFixed(3),
              +s.x.toFixed(3), +s.y.toFixed(3)]);
  });
  out.sort((a,b) => a[1] - b[1]);
  return JSON.stringify(out);
};

// 骨骼位置（最可靠的「人在哪」度量）
window.__boneExtent = () => {
  vrm.scene.updateMatrixWorld(true);
  let minY = 1e9, maxY = -1e9, minX = 1e9, maxX = -1e9;
  const names = [];
  const hb = vrm.humanoid ? vrm.humanoid.humanBones : {};
  for (const k of Object.keys(hb)) {
    const n = vrm.humanoid.getNormalizedBoneNode(k) || hb[k].node;
    if (!n) continue;
    const p = n.getWorldPosition(new THREE.Vector3());
    if (p.y < minY) minY = p.y;
    if (p.y > maxY) maxY = p.y;
    if (p.x < minX) minX = p.x;
    if (p.x > maxX) maxX = p.x;
    names.push(k);
  }
  return JSON.stringify({
    bones: names.length,
    minY:+minY.toFixed(3), maxY:+maxY.toFixed(3), height:+(maxY-minY).toFixed(3),
    minX:+minX.toFixed(3), maxX:+maxX.toFixed(3), width:+(maxX-minX).toFixed(3)
  });
};

window.__box = () => {
  const b = posedBox();
  const s = b.getSize(new THREE.Vector3());
  const c = b.getCenter(new THREE.Vector3());
  return JSON.stringify({
    min:[+b.min.x.toFixed(3),+b.min.y.toFixed(3),+b.min.z.toFixed(3)],
    max:[+b.max.x.toFixed(3),+b.max.y.toFixed(3),+b.max.z.toFixed(3)],
    size:[+s.x.toFixed(3),+s.y.toFixed(3),+s.z.toFixed(3)],
    center:[+c.x.toFixed(3),+c.y.toFixed(3),+c.z.toFixed(3)]
  });
};

window.__bones = () => JSON.stringify(Object.keys(vrm.humanoid ? vrm.humanoid.humanBones : {}));

window.__meshes = () => {
  const out=[];
  vrm.scene.traverse(o=>{ if(o.isMesh){
    const p = o.geometry && o.geometry.attributes && o.geometry.attributes.position;
    out.push([o.name, p?p.count:0, !!o.isSkinnedMesh]);
  }});
  return JSON.stringify(out);
};

window.__probe = (rz) => {
  const L = vrm.humanoid.getNormalizedBoneNode('leftUpperArm');
  const R = vrm.humanoid.getNormalizedBoneNode('rightUpperArm');
  if (L) L.rotation.set(0,0,rz);
  if (R) R.rotation.set(0,0,-rz);
  vrm.humanoid.update();
  vrm.scene.updateMatrixWorld(true);
  const p = n => { const x = vrm.humanoid.getNormalizedBoneNode(n); return x ? x.getWorldPosition(new THREE.Vector3()) : null; };
  const a = p('leftHand'), b = p('leftUpperArm'), c = p('rightHand');
  const b2 = posedBox(); const s2 = b2.getSize(new THREE.Vector3());
  return JSON.stringify({
    rz: rz,
    shoulderY: b?+b.y.toFixed(4):null,
    handY: a?+a.y.toFixed(4):null,
    drop: (a&&b)?+(b.y-a.y).toFixed(4):null,
    handX: a?+a.x.toFixed(4):null,
    shoulderX: b?+b.x.toFixed(4):null,
    reach: (a&&b)?+(a.x-b.x).toFixed(4):null,
    rightHandY: c?+c.y.toFixed(4):null,
    boxX: +s2.x.toFixed(3), boxY: +s2.y.toFixed(3)
  });
};

window.__fit = (aspect) => {
  const b = posedBox();
  const s = b.getSize(new THREE.Vector3());
  const c = b.getCenter(new THREE.Vector3());
  const fov = 25*Math.PI/180;
  const fitH = (s.y/2)/Math.tan(fov/2);
  const fitW = (s.x/2)/Math.tan(fov/2)/aspect;
  return JSON.stringify({
    sizeX:+s.x.toFixed(3), sizeY:+s.y.toFixed(3), centerY:+c.y.toFixed(3),
    fitH:+fitH.toFixed(3), fitW:+fitW.toFixed(3),
    need:+Math.max(fitH,fitW).toFixed(3),
    needWithMargin:+(Math.max(fitH,fitW)*1.12).toFixed(3)
  });
};
</script></body></html>"""


def main() -> int:
    (SRV_DIR / "_pd.html").write_text(HTML, encoding="utf-8")
    app = QApplication(sys.argv)
    port = serve(SRV_DIR)

    w = QWidget()
    w.resize(W, H)
    view = QWebEngineView(w)
    pg = Page(view)
    view.setPage(pg)
    view.setGeometry(0, 0, W, H)
    pg.setBackgroundColor(QColor("#2b2f3a"))
    view.settings().setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, True)
    pg.load(QUrl(f"http://127.0.0.1:{port}/_pd.html"))
    w.show()

    def wait(ms):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def js(code, timeout=30000):
        box = {"v": None, "done": False}
        pg.runJavaScript(code, lambda v: box.update(v=v, done=True))
        t = 0
        while not box["done"] and t < timeout:
            wait(100)
            t += 100
        return box["v"]

    for _ in range(80):
        wait(400)
        if js("window.__ready === true", 2000):
            break
    if not js("window.__ready === true", 2000):
        print("!! 模型未加载")
        return 1
    wait(1200)

    print("=" * 72)
    print("① 网格清单（确认腿脚 mesh 在不在）")
    print("=" * 72)
    ms = json.loads(js("window.__meshes()") or "[]")
    tot = 0
    for n, c, sk in sorted(ms, key=lambda x: -x[1]):
        tot += c
        print(f"  {n:<26s} 顶点{c:>6d}  蒙皮={'是' if sk else '否'}")
    print(f"  合计 {len(ms)} mesh / {tot} 顶点")

    print()
    print("=" * 72)
    print("② 三种包围盒对照")
    print("=" * 72)
    print(f"  rest（未蒙皮，= 原代码 Box3.setFromObject）: {js('window.__restBox()')}")
    print(f"  蒙皮后                                    : {js('window.__box()')}")
    print(f"  骨骼范围                                  : {js('window.__boneExtent()')}")
    print()
    print("  各 mesh 的 Y 范围（找离群顶点）:")
    for n, mn, mx, sx, sy in (json.loads(js("window.__meshBoxes()") or "[]")):
        print(f"    {n:<26s} Y[{mn:8.3f} .. {mx:8.3f}]  宽{sx:7.3f} 高{sy:7.3f}")

    print()
    print("=" * 72)
    print("③ 相机取景：需要多远才装得下全身")
    print("=" * 72)
    fi = json.loads(js(f"window.__fit({W/H})") or "{}")
    print(f"  {fi}")
    size_y = fi.get("sizeY", 0) or 1
    cur = size_y * 1.25
    need = fi.get("needWithMargin", 0) or 1
    print(f"  当前代码距离 = sizeY*1.25 = {cur:.3f}")
    print(f"  实际需要     = {need:.3f}（已留 12% 余量）")
    print(f"  >>> 当前只装得下全身 {cur/need*100:.1f}%  → 头脚被裁掉")

    print()
    print("=" * 72)
    print("④ 上臂旋转角 → 手落点（找「手下垂」角度）")
    print("=" * 72)
    print(f"{'rz':>7s}{'肩Y':>10s}{'手Y':>10s}{'下垂量':>10s}{'横向伸展':>10s}{'盒宽':>9s}{'盒高':>9s}")
    print("-" * 72)
    best = None
    for rz in (-1.5, -1.4, -1.3, -1.2, -1.1, -1.0, -0.8, 0.0,
               0.8, 1.0, 1.1, 1.2, 1.3, 1.4, 1.5):
        d = json.loads(js(f"window.__probe({rz})") or "{}")
        if not d:
            continue
        print(f"{rz:7.2f}{d.get('shoulderY') or 0:10.4f}{d.get('handY') or 0:10.4f}"
              f"{d.get('drop') or 0:10.4f}{d.get('reach') or 0:10.4f}"
              f"{d.get('boxX') or 0:9.3f}{d.get('boxY') or 0:9.3f}")
        if (d.get("drop") or -9) > 0.15 and abs(d.get("reach") or 99) < 0.16:
            if best is None or abs(d["reach"]) < abs(best[1]["reach"]):
                best = (rz, d)
    print("-" * 72)
    if best:
        print(f"  >>> 推荐 rz = {best[0]:.2f}"
              f"（下垂 {best[1]['drop']:.3f}m，横向偏 {best[1]['reach']:.3f}m，"
              f"包围盒 {best[1]['boxX']:.2f}×{best[1]['boxY']:.2f}）")
    else:
        print("  >>> 没找到完全下垂的角度，按上表人工挑一个")
    return 0


if __name__ == "__main__":
    sys.exit(main())
