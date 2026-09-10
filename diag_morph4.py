"""diag_morph4.py —— 定位 morph 不生效的真正原因

已知事实：
  * geometry 有 27 个 morphAttributes.position，morphTargetsRelative=true
  * mesh.morphTargetInfluences 长度 27，是 Array
  * 直接改 influence=1.0 → 画面零变化
  * 直接改 geometry.attributes.position → 画面有变化（管线正常）

待验证假设：
  H1. 相机没对准有 morph 的那个部件（prim[0]=「颜」脸部，但相机可能没拍到）
  H2. 画面里那个 mesh 被遮挡/在其他位置
  H3. renderer 编译 shader 时 morph 相关 define 没开
  H4. 位移太小，PNG 压缩后哈希碰撞（需要放大位移验证）

本脚本做「放大 100 倍位移」的极端测试，一次性排除 H4，并打印每个 mesh
的屏幕位置判断 H1/H2。

用法：python diag_morph4.py
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
  const box=new THREE.Box3().setFromObject(vrm.scene);
  const head=vrm.humanoid?.getNormalizedBoneNode('head');
  const hp=head?head.getWorldPosition(new THREE.Vector3()):new THREE.Vector3(0,1.4,0);
  camera.position.set(0,hp.y+0.02,0.34); camera.lookAt(0,hp.y-0.02,0);
  console.log('D4 ready');
  window.__ready=true;
  (function loop(){ requestAnimationFrame(loop); renderer.render(scene,camera); })();
});

window.__png=()=>{ renderer.render(scene,camera); return renderer.domElement.toDataURL('image/png'); };
window.__clear=()=>{
  vrm?.scene.traverse(o=>{ if(o.isMesh&&o.morphTargetInfluences) o.morphTargetInfluences.fill(0); });
  return 'ok';
};

// ★ 极端测试：把 morph target 的【数据本身】放大 100 倍，再设 influence=1
window.__amplifyMorph=(idx,scale)=>{
  let n=0;
  vrm?.scene.traverse(o=>{
    if(!o.isMesh) return;
    const pos=(o.geometry.morphAttributes?.position||[]);
    if(idx>=pos.length||!pos[idx]) return;
    const a=pos[idx].array;
    for(let i=0;i<a.length;i++) a[i]*=scale;
    pos[idx].needsUpdate=true;
    o.morphTargetInfluences[idx]=1.0;
    n++;
  });
  return 'amplified x'+scale+' on '+n+' meshes';
};

// 只对指定 mesh 名设 influence
window.__setOn=(meshName,idx,w)=>{
  let n=0;
  vrm?.scene.traverse(o=>{
    if(o.isMesh && o.name===meshName && o.morphTargetInfluences){
      o.morphTargetInfluences[idx]=w; n++;
    }
  });
  return n;
};

// 列出每个 mesh 的屏幕投影范围（判断是否在视野内）
window.__screen=()=>{
  const out=[];
  vrm?.scene.traverse(o=>{
    if(!o.isMesh) return;
    const bx=new THREE.Box3().setFromObject(o);
    if(bx.isEmpty()) return;
    // 投影 8 个角
    let minX=1e9,maxX=-1e9,minY=1e9,maxY=-1e9,anyFront=false;
    for(const X of [bx.min.x,bx.max.x]) for(const Y of [bx.min.y,bx.max.y]) for(const Z of [bx.min.z,bx.max.z]){
      const v=new THREE.Vector3(X,Y,Z).project(camera);
      if(v.z<1) anyFront=true;
      minX=Math.min(minX,v.x); maxX=Math.max(maxX,v.x);
      minY=Math.min(minY,v.y); maxY=Math.max(maxY,v.y);
    }
    const pos=(o.geometry.morphAttributes?.position||[]);
    let maxAbs=0;
    if(pos[0]?.array){ const a=pos[0].array; for(let i=0;i<a.length;i++) maxAbs=Math.max(maxAbs,Math.abs(a[i])); }
    out.push({
      name:o.name,
      inView: anyFront && maxX>-1 && minX<1 && maxY>-1 && minY<1,
      sx:[+minX.toFixed(2),+maxX.toFixed(2)],
      sy:[+minY.toFixed(2),+maxY.toFixed(2)],
      morphMax:+maxAbs.toFixed(5),
    });
  });
  return JSON.stringify(out);
};

// 用 onBeforeCompile 检查 shader 是否真的用了 morph
window.__shaderInfo=(meshName)=>{
  let info=null;
  vrm?.scene.traverse(o=>{
    if(info||!o.isMesh) return;
    if(meshName && o.name!==meshName) return;
    const mat=o.material;
    const orig=mat.onBeforeCompile;
    info={
      name:o.name,
      matType:mat.type,
      defines:JSON.stringify(mat.defines||{}),
      // three 在 WebGLProgram 里用 morphTargets 参数
      morphAttrPos:(o.geometry.morphAttributes?.position||[]).length,
      morphRel:o.geometry.morphTargetsRelative,
      hasInfluences:!!o.morphTargetInfluences,
      infLen:o.morphTargetInfluences?.length,
      // 是否有 skinning
      hasSkin:!!o.isSkinnedMesh,
    };
  });
  return JSON.stringify(info,null,1);
};

// 读取 renderer.info（判断 draw call）
window.__renderInfo=()=>JSON.stringify({
  calls:renderer.info.render.calls,
  triangles:renderer.info.render.triangles,
  programs:renderer.info.programs?.length,
});
</script></body></html>"""


def png_md5(u):
    if not u or not str(u).startswith("data:image"):
        return None
    return hashlib.md5(base64.b64decode(str(u).split(",", 1)[1])).hexdigest()[:12]


def main() -> int:
    (SRV_DIR / "_morph_diag4.html").write_text(HTML, encoding="utf-8")
    app = QApplication(sys.argv)
    port = serve(SRV_DIR)

    w = QWidget()
    w.resize(320, 420)
    view = QWebEngineView(w)
    page = QWebEnginePage(view)
    view.setPage(page)
    view.setGeometry(0, 0, 320, 420)
    page.setBackgroundColor(QColor(0, 0, 0, 0))
    view.settings().setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, True)

    msgs = []
    class P(QWebEnginePage):
        def javaScriptConsoleMessage(self, level, message, line, source):
            msgs.append(message[:200])
            if level.name.startswith("Error") or "D4" in message:
                print(f"  [js] {message[:200]}")
    p2 = P(view)
    view.setPage(p2)
    p2.setBackgroundColor(QColor(0, 0, 0, 0))

    p2.load(QUrl(f"http://127.0.0.1:{port}/_morph_diag4.html"))
    w.show()

    def wait(ms):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def js(code, timeout=10000):
        box = {"v": None, "done": False}
        p2.runJavaScript(code, lambda v: box.update(v=v, done=True))
        t = 0
        while not box["done"] and t < timeout:
            wait(100)
            t += 100
        return box["v"]

    for _ in range(50):
        wait(400)
        if js("window.__ready === true", 2000):
            break
    wait(1200)
    print("[diag] 已加载")

    print(f"\n  renderer.info: {js('window.__renderInfo()')}")
    print(f"\n  shader 信息:\n  {str(js('window.__shaderInfo()')).replace(chr(10), chr(10)+'  ')}")

    # 屏幕投影
    print(f"\n  各 mesh 屏幕投影（inView=是否在视野内）:")
    try:
        sc = json.loads(js("window.__screen()"))
        for s in sc[:10]:
            print(f"    {s['name']:20s} inView={str(s['inView']):5s} "
                  f"sx={s['sx']} sy={s['sy']} morphMax={s['morphMax']}")
    except Exception as e:
        print(f"    解析失败 {e}")

    # 基准
    print(f"\n  ---- 极限测试：morph 数据放大 100 倍 ----")
    js("window.__clear()")
    wait(700)
    base = png_md5(js("window.__png()"))
    print(f"  基准 md5 = {base}")

    js("window.__amplifyMorph(0, 100.0)")
    wait(900)
    m1 = png_md5(js("window.__png()"))
    print(f"  morph[0] x100 -> md5={m1}  {'★ 生效！' if m1 != base else '无变化'}")

    js("window.__clear()")
    wait(500)
    # 复位并测试原始量级
    js("window.__amplifyMorph(0, 0.01)")
    wait(900)
    m2 = png_md5(js("window.__png()"))
    print(f"  morph[0] 复位 -> md5={m2}  {'★ 生效！' if m2 != base else '无变化'}")

    # 只对第一个 mesh 设 influence
    print(f"\n  ---- 只对 prim[0] 设 influence ----")
    js("window.__clear()")
    wait(600)
    b2 = png_md5(js("window.__png()"))
    for nm in ("米雪儿私服1_1", "米雪儿私服1_2"):
        r = js(f"window.__setOn({json.dumps(nm)}, 0, 1.0)")
        wait(700)
        m = png_md5(js("window.__png()"))
        print(f"  {nm}: setOn 返回 {r}  md5={m}  {'★ 生效' if m != b2 else '无变化'}")
        js("window.__clear()")
        wait(400)

    print("\n" + "=" * 64)
    return 0


if __name__ == "__main__":
    sys.exit(main())
