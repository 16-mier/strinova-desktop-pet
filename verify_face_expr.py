"""verify_face_expr.py —— 严格验证表情是否真的改变了「脸部」

之前全画面统计会被身体/头发稀释。本脚本：
  ① 从相机射线定位脸部的屏幕区域
  ② 只在该区域内比较像素
  ③ 输出差异热力分布（哪一块变了）

用法：python verify_face_expr.py
"""
from __future__ import annotations

import base64
import hashlib
import io
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

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


class Page(QWebEnginePage):
    def javaScriptConsoleMessage(self, level, message, line, source):
        if level.name.startswith("Error") or "VF" in message:
            print(f"  [js] {message[:220]}")


HTML = """<!DOCTYPE html><html><head><meta charset="utf-8">
<style>html,body{margin:0;background:transparent;overflow:hidden}canvas{display:block}</style>
</head><body>
<script type="importmap">
{"imports":{"three":"./vendor/three.module.js","three/addons/":"./vendor/addons/"}}
</script>
<script type="module">
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { VRMLoaderPlugin } from './vendor/three-vrm.module.js';
import { MorphDriver } from './vrm_morphs.js';

const W=512,H=512;
const scene=new THREE.Scene();
const camera=new THREE.PerspectiveCamera(30,W/H,0.01,100);
const renderer=new THREE.WebGLRenderer({alpha:true,antialias:true,preserveDrawingBuffer:true});
renderer.setClearColor(0x000000,0); renderer.setSize(W,H);
renderer.toneMapping=THREE.NoToneMapping; renderer.outputColorSpace=THREE.SRGBColorSpace;
document.body.appendChild(renderer.domElement);
scene.add(new THREE.AmbientLight(0xffffff,0.62));
const d1=new THREE.DirectionalLight(0xffffff,0.68); d1.position.set(0.5,2,2.5); scene.add(d1);

let vrm=null, driver=null;
window.__ready=false;
const loader=new GLTFLoader();
loader.register(p=>new VRMLoaderPlugin(p));
loader.load('./models/michelle_expr.vrm',(g)=>{
  vrm=g.userData.vrm;
  scene.add(vrm.scene);
  vrm.scene.rotation.y = 0;                 // 脸朝 −Z，相机在 +Z
  vrm.scene.traverse(o=>{ if(o.isMesh) o.frustumCulled=false; });
  driver = new MorphDriver(vrm, g);

  // 相机正对脸部中央（眼睛高度）
  const eyeL = vrm.humanoid?.getNormalizedBoneNode('leftEye')?.getWorldPosition(new THREE.Vector3());
  const eyeR = vrm.humanoid?.getNormalizedBoneNode('rightEye')?.getWorldPosition(new THREE.Vector3());
  let cy = 1.46;
  if (eyeL && eyeR) cy = (eyeL.y + eyeR.y) / 2;
  window.__eyeY = cy;
  camera.position.set(0, cy, 0.22);
  camera.lookAt(0, cy - 0.015, 0);
  camera.updateMatrixWorld(true);

  // 计算脸部在屏幕上的像素范围（把「颜」网格的包围盒投影）
  vrm.scene.traverse(o=>{
    if(o.isMesh && o.material?.name === '颜'){
      const box = new THREE.Box3().setFromObject(o);
      let minX=1e9,maxX=-1e9,minY=1e9,maxY=-1e9;
      for(const X of [box.min.x,box.max.x]) for(const Y of [box.min.y,box.max.y]) for(const Z of [box.min.z,box.max.z]){
        const v=new THREE.Vector3(X,Y,Z).project(camera);
        minX=Math.min(minX,v.x); maxX=Math.max(maxX,v.x);
        minY=Math.min(minY,v.y); maxY=Math.max(maxY,v.y);
      }
      // NDC -> 像素（y 轴翻转）
      window.__faceRect = {
        x0: Math.max(0, Math.floor((minX*0.5+0.5)*W)),
        x1: Math.min(W, Math.ceil((maxX*0.5+0.5)*W)),
        y0: Math.max(0, Math.floor((-maxY*0.5+0.5)*H)),
        y1: Math.min(H, Math.ceil((-minY*0.5+0.5)*H)),
      };
      console.log('VF faceRect ' + JSON.stringify(window.__faceRect));
    }
  });

  console.log('VF ready eyeY='+cy.toFixed(3)+' driver='+JSON.stringify(driver.info()));
  window.__ready=true;
  (function loop(){ requestAnimationFrame(loop); renderer.render(scene,camera); })();
});

window.__png=()=>{ renderer.render(scene,camera); return renderer.domElement.toDataURL('image/png'); };
window.__set=(n,w)=>{ if(!driver) return 'no'; driver.clear(); const ok=driver.set(n,w); driver.apply(); return ok?'ok':'unknown'; };
window.__clear=()=>{ if(driver){ driver.clear(); driver.apply(); } return 'ok'; };
window.__names=()=>JSON.stringify(driver?driver.names():[]);
window.__rect=()=>JSON.stringify(window.__faceRect||null);
window.__vdelta=()=>{
  if(!driver||!driver.meshes.length) return '{}';
  const e=driver.meshes[0];
  const cur=e.mesh.geometry.attributes.position.array;
  let mx=0,nz=0;
  for(let i=0;i<cur.length;i++){ const d=Math.abs(cur[i]-e.base[i]); if(d>1e-7)nz++; if(d>mx)mx=d; }
  return JSON.stringify({nz:nz,max:+mx.toFixed(5)});
};
</script></body></html>"""


def png_bytes(u):
    if not u or not str(u).startswith("data:image"):
        return None
    return base64.b64decode(str(u).split(",", 1)[1])


def main() -> int:
    if not HAS_PIL:
        print("需要 Pillow")
        return 1
    (SRV_DIR / "_vf.html").write_text(HTML, encoding="utf-8")
    app = QApplication(sys.argv)
    port = serve(SRV_DIR)

    w = QWidget()
    w.resize(512, 512)
    view = QWebEngineView(w)
    pg = Page(view)
    view.setPage(pg)
    view.setGeometry(0, 0, 512, 512)
    pg.setBackgroundColor(QColor(0, 0, 0, 0))
    view.settings().setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, True)
    pg.load(QUrl(f"http://127.0.0.1:{port}/_vf.html"))
    w.show()

    def wait(ms):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def js(code, timeout=12000):
        box = {"v": None, "done": False}
        pg.runJavaScript(code, lambda v: box.update(v=v, done=True))
        t = 0
        while not box["done"] and t < timeout:
            wait(100)
            t += 100
        return box["v"]

    for _ in range(60):
        wait(400)
        if js("window.__ready === true", 2000):
            break
    rect = json.loads(js("window.__rect()") or "null")
    print(f"[vf] 脸部屏幕区域: {rect}")
    wait(1500)

    names = json.loads(js("window.__names()") or "[]")

    js("window.__clear()")
    wait(900)
    base_raw = png_bytes(js("window.__png()"))
    base = Image.open(io.BytesIO(base_raw)).convert("RGBA")

    # 脸部裁剪
    if rect:
        fb = base.crop((rect["x0"], rect["y0"], rect["x1"], rect["y1"]))
    else:
        fb = base
    print(f"[vf] 脸部裁剪尺寸: {fb.size}")

    KEY = ["blink", "blinkLeft", "blinkRight", "happy", "angry", "sad", "surprised",
           "relaxed", "aa", "ih", "ou", "ee", "oh",
           "lookUp", "lookDown", "lookLeft", "lookRight",
           "ω", "∧", "じと目", "ぺろっ", "口横広げ", "瞳小"]
    test = [n for n in KEY if n in names]

    print(f"\n{'表情':<14s} {'顶点变化':>8s} {'脸部差异px':>10s} {'脸部占比':>8s}  判定")
    print("-" * 58)
    hits = []
    for nm in test:
        js(f"window.__set({json.dumps(nm)}, 1.0)")
        wait(750)
        vd = js("window.__vdelta()")
        try:
            nz = json.loads(vd).get("nz", 0)
        except Exception:
            nz = 0
        raw = png_bytes(js("window.__png()"))
        if raw is None:
            continue
        cur = Image.open(io.BytesIO(raw)).convert("RGBA")
        fc = cur.crop((rect["x0"], rect["y0"], rect["x1"], rect["y1"])) if rect else cur
        da = list(fb.get_flattened_data()) if hasattr(fb, "get_flattened_data") else list(fb.getdata())
        db = list(fc.get_flattened_data()) if hasattr(fc, "get_flattened_data") else list(fc.getdata())
        diff = 0
        for p, q in zip(da, db):
            if abs(p[0]-q[0]) + abs(p[1]-q[1]) + abs(p[2]-q[2]) > 8:
                diff += 1
        pctv = diff / max(1, len(da)) * 100
        ok = diff > 30
        if ok:
            hits.append(nm)
        print(f"{nm:<14s} {nz:8d} {diff:10d} {pctv:7.1f}%  {'★ 生效' if ok else '差异过小'}")

    print("-" * 58)
    print(f"脸部确认生效: {len(hits)}/{len(test)}  {hits}")

    # 存脸部对比图
    for nm in (None, "aa", "ee", "blink", "happy"):
        if nm:
            js(f"window.__set({json.dumps(nm)}, 1.0)")
        else:
            js("window.__clear()")
        wait(750)
        raw = png_bytes(js("window.__png()"))
        if raw and rect:
            im = Image.open(io.BytesIO(raw)).convert("RGB")
            im.crop((rect["x0"], rect["y0"], rect["x1"], rect["y1"])).resize((320, 320)).save(
                HERE / f"face_{nm or 'neutral'}.png")
    print("[vf] 脸部图: face_neutral.png / face_aa.png / face_ee.png / face_blink.png / face_happy.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
