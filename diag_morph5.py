"""diag_morph5.py —— 最终验证：强制 material 重新编译后 morph 是否生效

关键假设：three.js 的 WebGLProgram 编译时根据 morphAttributes 长度决定是否
加入 MORPHTARGETS define。第一次渲染时可能因为某些时序问题没开 morph，
导致所有 influence 改动都无效。强制 material.needsUpdate = true 重新编译。

用法：python diag_morph5.py
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
    "--ignore-gpu-blocklist --enable-unsafe-swiftshader",
)

from PyQt6.QtCore import QTimer, QUrl, QEventLoop
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PyQt6.QtWebEngineWidgets import QWebEngineView

from web3d_server import serve


class Page(QWebEnginePage):
    def javaScriptConsoleMessage(self, level, message, line, source):
        if level.name.startswith("Error") or "D5" in message:
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
import { VRMLoaderPlugin, VRMUtils } from './vendor/three-vrm.module.js';

const W=320,H=420;
const scene=new THREE.Scene();
const camera=new THREE.PerspectiveCamera(30,W/H,0.01,100);
const renderer=new THREE.WebGLRenderer({alpha:true,antialias:true,preserveDrawingBuffer:true});
renderer.setClearColor(0x000000,0); renderer.setSize(W,H);
renderer.toneMapping=THREE.NoToneMapping; renderer.outputColorSpace=THREE.SRGBColorSpace;
document.body.appendChild(renderer.domElement);
scene.add(new THREE.AmbientLight(0xffffff,0.7));
const dl=new THREE.DirectionalLight(0xffffff,0.8); dl.position.set(0.5,2,2.5); scene.add(dl);

let vrm=null;
window.__ready=false;
const loader=new GLTFLoader();
loader.register(p=>new VRMLoaderPlugin(p));
loader.load('./models/michelle_expr.vrm',(g)=>{
  vrm=g.userData.vrm;
  scene.add(vrm.scene); vrm.scene.rotation.y=Math.PI;
  vrm.scene.traverse(o=>{ if(o.isMesh) o.frustumCulled=false; });
  const head=vrm.humanoid?.getNormalizedBoneNode('head');
  const hp=head?head.getWorldPosition(new THREE.Vector3()):new THREE.Vector3(0,1.4,0);
  camera.position.set(0,hp.y+0.03,0.36); camera.lookAt(0,hp.y-0.01,0);
  window.__ready=true;
  (function loop(){ requestAnimationFrame(loop); renderer.render(scene,camera); })();
});

window.__png=()=>{ renderer.render(scene,camera); return renderer.domElement.toDataURL('image/png'); };
window.__clear=()=>{
  vrm?.scene.traverse(o=>{ if(o.isMesh&&o.morphTargetInfluences) o.morphTargetInfluences.fill(0); });
  return 'ok';
};

// ★ 设置 influence + 强制材质重编译
window.__setAndRecompile=(idx,w)=>{
  let n=0;
  vrm?.scene.traverse(o=>{
    if(!o.isMesh||!o.morphTargetInfluences) return;
    if(idx<o.morphTargetInfluences.length){ o.morphTargetInfluences[idx]=w; n++; }
    // 强制每个材质重新编译，让 shader 带上 MORPHTARGETS
    if(o.material){ o.material.needsUpdate=true; }
  });
  return 'set '+idx+'='+w+' on '+n+' meshes, materials recompiled';
};

// 设置 influence 且强制重新编译（但只对第一个 mesh）
window.__setFirst=(idx,w)=>{
  let n=0;
  vrm?.scene.traverse(o=>{
    if(n>0||!o.isMesh||!o.morphTargetInfluences) return;
    if(idx<o.morphTargetInfluences.length){ o.morphTargetInfluences[idx]=w; n++; }
    if(o.material) o.material.needsUpdate=true;
  });
  return 'first mesh set '+idx+'='+w;
};

// 查看渲染器 program 里的 morph 相关 define
window.__programs=()=>{
  try{
    return JSON.stringify(renderer.info.programs?.map(p=>(
      p.getUniforms?.() ? {name:p.name, defines:p.defines||{}} : {name:p.name}
    )));
  }catch(e){ return 'ERR '+e.message; }
};

const sleep=(ms)=>new Promise(r=>setTimeout(r,ms));

window.__run=async()=>{
  await sleep(1500);
  const out={};
  out.base = __png();
  out.baseHash = (typeof out.base==='string')?out.base.slice(0,20):'(none)';
  await sleep(500);

  // 1. 不重编译：直接设
  out.step1 = (()=>{
    __clear();
    let n=0;
    vrm.scene.traverse(o=>{ if(o.isMesh&&o.morphTargetInfluences){ o.morphTargetInfluences[0]=1; n++; } });
    return 'set influence[0]=1 on '+n+' meshes';
  })();
  await sleep(800);
  out.snap1 = __png();
  out.hash1 = (typeof out.snap1==='string')?out.snap1.slice(0,20):'(none)';

  // 2. 重编译后再设
  out.step2 = __setAndRecompile(0, 1);
  await sleep(1000);
  out.snap2 = __png();
  out.hash2 = (typeof out.snap2==='string')?out.snap2.slice(0,20):'(none)';

  // 3. 只对第一个mesh重编译
  out.step3 = __setFirst(0, 1);
  await sleep(1000);
  out.snap3 = __png();
  out.hash3 = (typeof out.snap3==='string')?out.snap3.slice(0,20):'(none)';

  out.programs = (()=>{
    try{
      return JSON.stringify(renderer.info.programs?.map(p=>p.defines||{}));
    }catch(e){ return 'ERR'; }
  })();

  window.__result = JSON.stringify(out);
  return 'done';
};
</script></body></html>"""


def main() -> int:
    (SRV_DIR / "_morph_diag5.html").write_text(HTML, encoding="utf-8")
    app = QApplication(sys.argv)
    port = serve(SRV_DIR)

    w = QWidget()
    w.resize(320, 420)
    view = QWebEngineView(w)
    p = Page(view)
    view.setPage(p)
    view.setGeometry(0, 0, 320, 420)
    p.setBackgroundColor(QColor(0, 0, 0, 0))
    view.settings().setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, True)
    p.load(QUrl(f"http://127.0.0.1:{port}/_morph_diag5.html"))
    w.show()

    def wait(ms):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def js(code, timeout=12000):
        box = {"v": None, "done": False}
        p.runJavaScript(code, lambda v: box.update(v=v, done=True))
        t = 0
        while not box["done"] and t < timeout:
            wait(100)
            t += 100
        return box["v"]

    for _ in range(50):
        wait(400)
        if js("window.__ready === true", 2000):
            break
    wait(1500)

    print("[diag] 启动实验…")
    js("window.__run()")
    wait(1000)
    result = js("window.__result", 20000)
    print(f"\n结果: {result}")
    try:
        r = json.loads(result)
        hashes = {
            "base": r["hash1"],
            "先设后重编译": r["hash3"],
            "重编译后再设": r["hash2"],
        }
        for label, h in hashes.items():
            print(f"  {label:12s} {h}")
        b = r["hash1"]
        for label, h in list(hashes.items())[1:]:
            print(f"  → {label}: {'★ 生效' if h != b else '无变化'}")
        print(f"\n  programs: {r['programs']}")
    except Exception as e:
        print(f"  解析失败: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())