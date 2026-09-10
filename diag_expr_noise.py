# -*- coding: utf-8 -*-
"""diag_expr_noise.py —— 一锤定音：先量化「噪声」，再测表情

上两轮结论互相矛盾：
  · test_expr_final.py  : aa 5.3% 差异
  · verify_face_expr.py : aa 0.0% 差异，但「瞳小」顶点变化 0 却有 4.5% 差异
后者说明「拍到的图」和「当前状态」可能不同步（toDataURL 拿到旧帧 / 合成延迟）。

本脚本：
  ① 连续拍 6 张「无表情」帧，两两比较 → 量化基线噪声
  ② 对每个表情：设值 → 等 1600ms → 拍 A → 再等 600ms → 拍 B
     比较 A/B（噪声）与 基准/A（信号）
  ③ 同时输出 PNG 的 md5，判断到底是「真变了」还是「拿到同一张图」
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

from PIL import Image


class Page(QWebEnginePage):
    def javaScriptConsoleMessage(self, level, message, line, source):
        if level.name.startswith("Error") or "DN" in message:
            print(f"  [js] {message[:200]}")


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

let vrm=null, driver=null, frameNo=0;
window.__ready=false;

function draw(){ renderer.render(scene,camera); frameNo++; }

const loader=new GLTFLoader();
loader.register(p=>new VRMLoaderPlugin(p));
loader.load('./models/michelle_expr.vrm',(g)=>{
  vrm=g.userData.vrm;
  scene.add(vrm.scene);
  vrm.scene.rotation.y = 0;
  vrm.scene.traverse(o=>{ if(o.isMesh) o.frustumCulled=false; });
  driver = new MorphDriver(vrm, g);

  const eyeL = vrm.humanoid?.getNormalizedBoneNode('leftEye')?.getWorldPosition(new THREE.Vector3());
  const eyeR = vrm.humanoid?.getNormalizedBoneNode('rightEye')?.getWorldPosition(new THREE.Vector3());
  let cy = 1.46;
  if (eyeL && eyeR) cy = (eyeL.y + eyeR.y) / 2;
  camera.position.set(0, cy, 0.24);
  camera.lookAt(0, cy - 0.02, 0);
  camera.updateMatrixWorld(true);

  console.log('DN ready ' + JSON.stringify(driver.info()));
  window.__ready=true;
  (function loop(){ requestAnimationFrame(loop); draw(); })();
});

// 渲染两帧再取图：强制走完一次完整的「属性上传 → 绘制 → 合成」链路
window.__png=()=>{ draw(); draw(); return renderer.domElement.toDataURL('image/png'); };
window.__set=(n,w)=>{ if(!driver) return 'no'; driver.clear(); const ok=driver.set(n,w); driver.apply(); draw(); return ok?'ok':'unknown'; };
window.__clear=()=>{ if(driver){ driver.clear(); driver.apply(); } draw(); return 'ok'; };
window.__names=()=>JSON.stringify(driver?driver.names():[]);
// 全 mesh 的顶点变化统计（不只看 meshes[0]）
window.__vdelta=()=>{
  if(!driver) return '{}';
  let nz=0, mx=0, meshesTouched=0;
  for(const e of driver.meshes){
    const cur=e.mesh.geometry.attributes.position.array;
    let t=0;
    for(let i=0;i<cur.length;i++){ const d=Math.abs(cur[i]-e.base[i]); if(d>1e-7){nz++;t++;} if(d>mx)mx=d; }
    if(t) meshesTouched++;
  }
  return JSON.stringify({nz:nz,max:+mx.toFixed(6),meshesTouched:meshesTouched,total:driver.meshes.length});
};
window.__frame=()=>frameNo;
</script></body></html>"""


def png_bytes(u):
    if not u or not str(u).startswith("data:image"):
        return None
    return base64.b64decode(str(u).split(",", 1)[1])


def diff_px(im_a, im_b, thr=8):
    da = list(im_a.getdata())
    db = list(im_b.getdata())
    n = 0
    for p, q in zip(da, db):
        if abs(p[0]-q[0]) + abs(p[1]-q[1]) + abs(p[2]-q[2]) > thr:
            n += 1
    return n, n / max(1, len(da)) * 100


def main() -> int:
    (SRV_DIR / "_dn.html").write_text(HTML, encoding="utf-8")
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
    pg.load(QUrl(f"http://127.0.0.1:{port}/_dn.html"))
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

    for _ in range(75):
        wait(400)
        if js("window.__ready === true", 2000):
            break
    if not js("window.__ready === true", 2000):
        print("!! 模型未加载完成")
        return 1
    wait(1200)

    def shot():
        raw = png_bytes(js("window.__png()"))
        if raw is None:
            return None, None
        return Image.open(io.BytesIO(raw)).convert("RGBA"), hashlib.md5(raw).hexdigest()[:10]

    # ---------- ① 噪声基线 ----------
    print("=" * 66)
    print("① 噪声基线：连续 6 张「无表情」帧")
    print("=" * 66)
    js("window.__clear()")
    wait(1200)
    base_frames = []
    for i in range(6):
        im, md5 = shot()
        base_frames.append((im, md5))
        print(f"  帧{i+1}  md5={md5}  frameNo={js('window.__frame()')}")
        wait(400)

    print("\n  两两差异（对比帧1）：")
    for i in range(1, 6):
        n, p = diff_px(base_frames[0][0], base_frames[i][0])
        print(f"    帧1 vs 帧{i+1}: {n:7d} px  ({p:5.2f}%)")

    noise = max(diff_px(base_frames[0][0], base_frames[i][0])[0] for i in range(1, 6))
    print(f"\n  >>> 基线噪声上限 = {noise} px")
    if noise > 100:
        print("  >>> 警告：画面本身不稳定，后续判定阈值必须 > 噪声")
    thr = max(120, int(noise * 3))
    print(f"  >>> 判定阈值 = {thr} px")

    # ---------- ② 表情测试 ----------
    names = json.loads(js("window.__names()") or "[]")
    KEY = ["blink", "blinkLeft", "blinkRight", "happy", "angry", "sad", "surprised",
           "relaxed", "aa", "ih", "ou", "ee", "oh",
           "lookUp", "lookDown", "lookLeft", "lookRight",
           "ω", "∧", "じと目", "ぺろっ", "口横広げ", "瞳小"]
    test = [n for n in KEY if n in names]

    print("\n" + "=" * 66)
    print("② 表情逐个测试（每个表情：设值 → 等 1600ms → 拍 A → 等 600ms → 拍 B）")
    print("=" * 66)
    print(f"{'表情':<13s}{'顶点nz':>8s}{'mesh':>6s}{'A-B噪声':>9s}{'基准-A':>9s}{'占比':>7s}  判定")
    print("-" * 66)

    base_im = base_frames[0][0]
    hits, dead = [], []
    for nm in test:
        r = js(f"window.__set({json.dumps(nm)}, 1.0)")
        wait(1600)
        imA, mdA = shot()
        wait(600)
        imB, mdB = shot()
        vd = json.loads(js("window.__vdelta()") or "{}")

        if imA is None or imB is None:
            print(f"{nm:<13s}  拍图失败")
            continue
        nab, _ = diff_px(imA, imB)
        nba, pba = diff_px(base_im, imA)
        ok = nba > thr and nba > nab * 4
        (hits if ok else dead).append(nm)
        print(f"{nm:<13s}{vd.get('nz',0):8d}{vd.get('meshesTouched',0):6d}{nab:9d}{nba:9d}{pba:6.1f}%  {'★ 生效' if ok else '✗ 无变化'}")

    print("-" * 66)
    print(f"\n>>> 确认生效 {len(hits)}/{len(test)}: {hits}")
    print(f">>> 未生效   {len(dead)}: {dead}")

    # ---------- ③ 存对比图 ----------
    for nm in (None, "aa", "blink", "happy", "surprised"):
        js("window.__clear()" if nm is None else f"window.__set({json.dumps(nm)},1.0)")
        wait(1400)
        im, _ = shot()
        if im:
            im.convert("RGB").save(HERE / f"dn_{nm or 'neutral'}.png")
    print("[dn] 对比图: dn_neutral.png / dn_aa.png / dn_blink.png / dn_happy.png / dn_surprised.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
