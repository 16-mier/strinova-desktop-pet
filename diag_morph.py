"""diag_morph.py —— 深挖 morph 为何不生效

分三步定位：
  A. 验证测量工具（旋转模型 → 像素应变化）
  B. 检查几何里的 morphAttributes（数量 / 数值 / morphTargetsRelative）
  C. 直接改 influence 后重渲染，看像素差
"""
from __future__ import annotations

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
        print(f"  [js:{level.name[:3]}] {message[:250]}")


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

const W=300,H=400;
const scene=new THREE.Scene();
const camera=new THREE.PerspectiveCamera(30,W/H,0.01,100);
const renderer=new THREE.WebGLRenderer({alpha:true,antialias:true,preserveDrawingBuffer:true});
renderer.setClearColor(0x000000,0); renderer.setSize(W,H);
renderer.toneMapping=THREE.NoToneMapping; renderer.outputColorSpace=THREE.SRGBColorSpace;
document.body.appendChild(renderer.domElement);
scene.add(new THREE.AmbientLight(0xffffff,0.6));
const dl=new THREE.DirectionalLight(0xffffff,0.7); dl.position.set(0.5,2,2.5); scene.add(dl);

let vrm=null, gltfRef=null;
const loader=new GLTFLoader();
loader.register(p=>new VRMLoaderPlugin(p));
loader.load('./models/michelle_expr.vrm',(g)=>{
  gltfRef=g; vrm=g.userData.vrm;
  try{ VRMUtils.combineMorphs(vrm); console.log('combineMorphs OK'); }catch(e){ console.log('combineMorphs ERR '+e.message); }
  scene.add(vrm.scene); vrm.scene.rotation.y=Math.PI;
  vrm.scene.traverse(o=>{ if(o.isMesh) o.frustumCulled=false; });
  const box=new THREE.Box3().setFromObject(vrm.scene);
  const size=box.getSize(new THREE.Vector3());
  const head=vrm.humanoid?.getNormalizedBoneNode('head');
  const hp=head?head.getWorldPosition(new THREE.Vector3()):new THREE.Vector3(0,size.y*0.92,0);
  camera.position.set(0,hp.y+0.03,0.30); camera.lookAt(0,hp.y-0.01,0);
  console.log('head y='+hp.y.toFixed(3)+' height='+size.y.toFixed(3));
  window.__loaded=true;
  window.__modelHeight=size.y;
  // ★ 持续渲染循环：没有它 readPixels 只会读到陈旧缓冲（实测导致"零变化"假象）
  (function loop(){ requestAnimationFrame(loop); renderer.render(scene,camera); })();
});

window.__snap=()=>{
  renderer.render(scene,camera);
  renderer.render(scene,camera);
  const url=renderer.domElement.toDataURL('image/png');
  return typeof url==='string'?url.slice(0,40):'(no)';
};

window.__geo=()=>{
  const out=[];
  vrm.scene.traverse(o=>{
    if(!o.isMesh) return;
    const g=o.geometry;
    const ma=g.morphAttributes||{};
    const pos=(ma.position||[]);
    out.push({
      name:o.name,
      verts:g.attributes.position.count,
      morphTargetsRelative:!!g.morphTargetsRelative,
      morphPosCount:pos.length,
      influences:o.morphTargetInfluences?o.morphTargetInfluences.length:0,
      firstMorphMax:(()=>{
        if(!pos.length||!pos[0]||!pos[0].array) return null;
        let mx=0; const a=pos[0].array;
        for(let i=0;i<a.length;i++) mx=Math.max(mx,Math.abs(a[i]));
        return +mx.toFixed(6);
      })(),
    });
  });
  return JSON.stringify(out.slice(0,4));
};

// 直接改指定 mesh 的 influence，绕过 expressionManager
window.__directSet=(targetIdx,w)=>{
  let touched=0;
  vrm.scene.traverse(o=>{
    if(!o.isMesh||!o.morphTargetInfluences) return;
    if(targetIdx<o.morphTargetInfluences.length){ o.morphTargetInfluences[targetIdx]=w; touched++; }
  });
  return 'set target '+targetIdx+'='+w+' on '+touched+' meshes';
};

window.__clearAll=()=>{
  vrm.scene.traverse(o=>{
    if(o.isMesh&&o.morphTargetInfluences) for(let i=0;i<o.morphTargetInfluences.length;i++) o.morphTargetInfluences[i]=0;
  });
  return 'cleared';
};

// 检查 morph target 数据本身（第 idx 个 target 的位移统计）
window.__morphData=(idx)=>{
  const out=[];
  vrm.scene.traverse(o=>{
    if(!o.isMesh) return;
    const g=o.geometry;
    const pos=(g.morphAttributes?.position||[]);
    if(idx>=pos.length||!pos[idx]) return;
    const a=pos[idx].array;
    let mx=0,nz=0;
    for(let i=0;i<a.length;i+=3){
      const m=Math.abs(a[i])+Math.abs(a[i+1])+Math.abs(a[i+2]);
      if(m>1e-9) nz++;
      mx=Math.max(mx,m);
    }
    out.push({name:o.name, verts:a.length/3, nonzero:nz, maxAbs:+mx.toFixed(6)});
  });
  return JSON.stringify(out);
};

// 直接改几何顶点（强制测试渲染管线是否响应）
window.__bump=(meshIdx,delta)=>{
  let i=0;
  let done=false;
  vrm.scene.traverse(o=>{
    if(done||!o.isMesh) return;
    if(i++!==meshIdx) return;
    const a=o.geometry.attributes.position.array;
    for(let k=1;k<a.length;k+=3) a[k]+=delta;   // Y 上移
    o.geometry.attributes.position.needsUpdate=true;
    done=true;
  });
  return done?'bumped':'not found';
};
</script></body></html>"""


def main() -> int:
    (SRV_DIR / "_morph_diag.html").write_text(HTML, encoding="utf-8")
    app = QApplication(sys.argv)
    port = serve(SRV_DIR)

    w = QWidget()
    w.resize(300, 400)
    view = QWebEngineView(w)
    page = Page(view)
    view.setPage(page)
    view.setGeometry(0, 0, 300, 400)
    page.setBackgroundColor(QColor(0, 0, 0, 0))
    view.settings().setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, True)
    page.load(QUrl(f"http://127.0.0.1:{port}/_morph_diag.html"))
    w.show()

    def wait(ms):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def js(code, timeout=8000):
        box = {"v": None, "done": False}
        page.runJavaScript(code, lambda v: box.update(v=v, done=True))
        t = 0
        while not box["done"] and t < timeout:
            wait(100)
            t += 100
        return box["v"]

    print("[diag] 等待加载…")
    for _ in range(50):
        wait(400)
        if js("window.__loaded === true", 2000):
            break
    print("[diag] 已加载")
    wait(1500)

    # ---- A. 验证测量工具 ----
    print("\n" + "=" * 60)
    print("A. 验证测量工具（改变画面 → 哈希应该变）")
    print("=" * 60)
    js("window.__clearAll()")
    wait(600)
    s1 = js("window.__sig()")
    print(f"  基准            : {s1}")
    js("window.__rotate(0.5)")
    wait(800)
    s2 = js("window.__sig()")
    print(f"  旋转 0.5 rad 后 : {s2}")
    try:
        h1 = json.loads(s1)["hash"]; h2 = json.loads(s2)["hash"]
        print(f"  => 哈希{'已改变（工具正常）' if h1 != h2 else '未变（工具失效！）'}")
        tool_ok = h1 != h2
    except Exception as e:
        print(f"  解析失败 {e}")
        tool_ok = False
    js("window.__rotate(0)")
    wait(600)

    # ---- B. 几何数据 ----
    print("\n" + "=" * 60)
    print("B. 几何 morphAttributes 检查")
    print("=" * 60)
    geo = js("window.__geo()")
    print(f"  {geo}")
    try:
        g = json.loads(geo)
        print(f"  第一个 mesh: morphTargetsRelative={g[0]['morphTargetsRelative']}, "
              f"morphPosCount={g[0]['morphPosCount']}, influences={g[0]['influences']}")
        print(f"  第一个 target 的最大位移 = {g[0]['firstMorphMax']}")
    except Exception as e:
        print(f"  解析失败: {e}")

    # ---- C. 直接改 influence ----
    print("\n" + "=" * 60)
    print("C. 直接改 influence（绕过 expressionManager）")
    print("=" * 60)
    base = js("window.__sig()")
    print(f"  基准: {base}")
    for idx in (0, 2, 6, 8):
        js(f"window.__directSet({idx}, 1.0)")
        wait(700)
        s = js("window.__sig()")
        same = str(s) == str(base)
        print(f"  target[{idx}] = 1.0 -> {s}   {'无变化' if same else '★ 有变化'}")
        js("window.__clearAll()")
        wait(500)

    # ---- D. 直接改顶点（测试渲染管线）----
    print("\n" + "=" * 60)
    print("D. 直接改顶点位置（验证渲染管线是否响应几何变化）")
    print("=" * 60)
    js("window.__clearAll()")
    wait(500)
    b1 = js("window.__sig()")
    print(f"  基准: {b1}")
    js("window.__bump(0, 0.05)")
    wait(800)
    b2 = js("window.__sig()")
    same = str(b1) == str(b2)
    print(f"  顶点 Y+0.05 后: {b2}   {'无变化（管线有问题）' if same else '★ 有变化（管线正常）'}")

    # ---- E. morph 数据内容 ----
    print("\n" + "=" * 60)
    print("E. 各 mesh 的 morph target[0] 数据内容")
    print("=" * 60)
    print(js("window.__morphData(0)"))

    print("\n" + "=" * 60)
    print("结论")
    print("=" * 60)
    print(f"  测量工具: {'正常' if tool_ok else '失效'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
