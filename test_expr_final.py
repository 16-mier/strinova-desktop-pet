"""test_expr_final.py —— 验证修正后的完整表情链路

修正了两个致命问题：
  ① 朝向：模型脸朝 −Z，之前旋转 π 导致相机看后脑勺（表情永远看不见）
  ② morph：GPU morph 在 QtWebEngine 下无效 → 改用 CPU 顶点烘焙

用法：python test_expr_final.py
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
        if level.name.startswith("Error") or "morphDriver" in message or "VRM loaded" in message:
            print(f"  [js] {message[:230]}")


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

const W=400,H=500;
const scene=new THREE.Scene();
const camera=new THREE.PerspectiveCamera(30,W/H,0.01,100);
const renderer=new THREE.WebGLRenderer({alpha:true,antialias:true,preserveDrawingBuffer:true});
renderer.setClearColor(0x000000,0); renderer.setSize(W,H);
renderer.toneMapping=THREE.NoToneMapping; renderer.outputColorSpace=THREE.SRGBColorSpace;
document.body.appendChild(renderer.domElement);
scene.add(new THREE.AmbientLight(0xffffff,0.6));
const d1=new THREE.DirectionalLight(0xffffff,0.65); d1.position.set(0.5,2,2.5); scene.add(d1);

let vrm=null, driver=null;
window.__ready=false;
const loader=new GLTFLoader();
loader.register(p=>new VRMLoaderPlugin(p));
loader.load('./models/michelle_expr.vrm',(g)=>{
  vrm=g.userData.vrm;
  scene.add(vrm.scene);
  // ★ 不旋转（脸朝 −Z，相机在 +Z）
  vrm.scene.rotation.y = 0;
  vrm.scene.traverse(o=>{ if(o.isMesh) o.frustumCulled=false; });
  driver = new MorphDriver(vrm, g);
  console.log('morphDriver ' + JSON.stringify(driver.info()));

  // 脸部特写
  const head=vrm.humanoid?.getNormalizedBoneNode('head');
  const hp=head?head.getWorldPosition(new THREE.Vector3()):new THREE.Vector3(0,1.4,0);
  camera.position.set(0, hp.y+0.005, 0.26);
  camera.lookAt(0, hp.y-0.015, 0);
  console.log('camera z=0.26 head y='+hp.y.toFixed(3));
  window.__ready=true;
  (function loop(){ requestAnimationFrame(loop); renderer.render(scene,camera); })();
});

window.__png=()=>{ renderer.render(scene,camera); return renderer.domElement.toDataURL('image/png'); };
window.__set=(n,w)=>{ if(!driver) return 'no driver'; driver.clear(); const ok=driver.set(n,w); driver.apply(); return ok?'ok':'unknown '+n; };
window.__clear=()=>{ if(driver){ driver.clear(); driver.apply(); } return 'ok'; };
window.__names=()=>JSON.stringify(driver?driver.names():[]);
window.__active=()=>JSON.stringify(driver?driver.active():[]);
window.__info=()=>JSON.stringify(driver?driver.info():{});
window.__vdelta=()=>{
  if(!driver||!driver.meshes.length) return '0';
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
    (SRV_DIR / "_expr_final.html").write_text(HTML, encoding="utf-8")
    app = QApplication(sys.argv)
    port = serve(SRV_DIR)

    w = QWidget()
    w.resize(400, 500)
    view = QWebEngineView(w)
    pg = Page(view)
    view.setPage(pg)
    view.setGeometry(0, 0, 400, 500)
    pg.setBackgroundColor(QColor(0, 0, 0, 0))
    view.settings().setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, True)
    pg.load(QUrl(f"http://127.0.0.1:{port}/_expr_final.html"))
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
    print(f"[test] driver: {js('window.__info()')}")
    wait(1500)

    names = json.loads(js("window.__names()") or "[]")
    print(f"[test] 表情 {len(names)} 个\n")

    js("window.__clear()")
    wait(800)
    base = png_bytes(js("window.__png()"))
    base_md5 = hashlib.md5(base).hexdigest()[:12] if base else None
    print(f"[test] 基准 md5 = {base_md5}")

    KEY = ["blink", "blinkLeft", "blinkRight", "happy", "angry", "sad",
           "surprised", "relaxed", "aa", "ih", "ou", "ee", "oh",
           "lookUp", "lookDown", "lookLeft", "lookRight"]
    test_list = [n for n in KEY if n in names] + [n for n in names if n not in KEY][:6]

    print(f"\n{'表情':<16s} {'顶点变化':>8s} {'像素差异':>9s}  {'占比':>6s}  判定")
    print("-" * 56)
    results = {}
    for name in test_list:
        js(f"window.__set({json.dumps(name)}, 1.0)")
        wait(700)
        vd = js("window.__vdelta()")
        try:
            nz = json.loads(vd).get("nz", 0)
        except Exception:
            nz = 0
        raw = png_bytes(js("window.__png()"))
        if raw is None:
            continue
        md5 = hashlib.md5(raw).hexdigest()[:12]
        diff, pct = 0, 0.0
        if HAS_PIL and base:
            try:
                a = Image.open(io.BytesIO(base)).convert("RGBA")
                b = Image.open(io.BytesIO(raw)).convert("RGBA")
                da = list(a.get_flattened_data()) if hasattr(a, "get_flattened_data") else list(a.getdata())
                db = list(b.get_flattened_data()) if hasattr(b, "get_flattened_data") else list(b.getdata())
                for p, q in zip(da, db):
                    if abs(p[0]-q[0]) + abs(p[1]-q[1]) + abs(p[2]-q[2]) > 10:
                        diff += 1
                pct = diff / max(1, len(da)) * 100
            except Exception:
                pass
        changed = (md5 != base_md5)
        results[name] = changed
        print(f"{name:<16s} {nz:8d} {diff:9d} {pct:5.1f}%  {'★ 生效' if changed else '无变化'}")

    ok = [k for k, v in results.items() if v]
    print("-" * 56)
    print(f"结果: {len(ok)}/{len(results)} 个表情生效")

    # 存对比图
    for nm, label in ((None, "neutral"), ("happy", "happy"), ("blink", "blink"),
                      ("surprised", "surprised")):
        if nm:
            js(f"window.__set({json.dumps(nm)}, 1.0)")
        else:
            js("window.__clear()")
        wait(700)
        r = png_bytes(js("window.__png()"))
        if r:
            (HERE / f"final_{label}.png").write_bytes(r)
    print("[test] 图: final_neutral.png / final_happy.png / final_blink.png / final_surprised.png")
    return 0 if len(ok) >= len(results) * 0.8 else 1


if __name__ == "__main__":
    sys.exit(main())
