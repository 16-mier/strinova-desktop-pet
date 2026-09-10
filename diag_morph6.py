"""diag_morph6.py —— 决定性对照实验

核心问题：为什么 morph influence 设了但画面不变？
对照实验：同时测「转换出的 michelle_expr.vrm」和「原生带表情的 Lazuli_VRM.vrm」
  * Lazuli 有 719 个原生 blendshape，是公认能用的 VRM
  * 如果 Lazuli 的表情能生效 → 测量方法没问题，是我的转换器有问题
  * 如果 Lazuli 也不生效 → 是 QtWebEngine + three.js + 软件渲染的环境限制

同时 dump 顶点着色器源码，看 USE_MORPHTARGETS 是否真的被启用。

用法：python diag_morph6.py
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
        if level.name.startswith("Error") or "D6" in message:
            print(f"  [js] {message[:240]}")


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

const MODEL = new URLSearchParams(location.search).get('model') || 'michelle_expr.vrm';
const USE_COMBINE = new URLSearchParams(location.search).get('combine') === '1';

const W=300,H=380;
const scene=new THREE.Scene();
const camera=new THREE.PerspectiveCamera(30,W/H,0.01,100);
const renderer=new THREE.WebGLRenderer({alpha:true,antialias:true,preserveDrawingBuffer:true});
renderer.setClearColor(0x000000,0); renderer.setSize(W,H);
renderer.toneMapping=THREE.NoToneMapping; renderer.outputColorSpace=THREE.SRGBColorSpace;
document.body.appendChild(renderer.domElement);
scene.add(new THREE.AmbientLight(0xffffff,0.9));
const dl=new THREE.DirectionalLight(0xffffff,0.9); dl.position.set(0.5,2,2.5); scene.add(dl);

let vrm=null;
window.__ready=false;
window.__exprs=[];
window.__shaderDump='';

const loader=new GLTFLoader();
loader.register(p=>new VRMLoaderPlugin(p));
loader.load('./models/'+MODEL,(g)=>{
  vrm=g.userData.vrm;
  if(USE_COMBINE){ try{ VRMUtils.combineMorphs(vrm); }catch(e){} }
  scene.add(vrm.scene); vrm.scene.rotation.y=Math.PI;
  vrm.scene.traverse(o=>{ if(o.isMesh) o.frustumCulled=false; });
  const head=vrm.humanoid?.getNormalizedBoneNode('head');
  const hp=head?head.getWorldPosition(new THREE.Vector3()):new THREE.Vector3(0,1.4,0);
  camera.position.set(0,hp.y+0.02,0.34); camera.lookAt(0,hp.y-0.02,0);
  window.__exprs=Object.keys(vrm.expressionManager?.expressionMap||{});
  console.log('D6 loaded '+MODEL+' exprs='+window.__exprs.length+' combine='+USE_COMBINE);
  window.__ready=true;
  (function loop(){ requestAnimationFrame(loop); renderer.render(scene,camera); })();
});

window.__png=()=>{ renderer.render(scene,camera); return renderer.domElement.toDataURL('image/png'); };
window.__clear=()=>{
  vrm?.scene.traverse(o=>{ if(o.isMesh&&o.morphTargetInfluences) o.morphTargetInfluences.fill(0); });
  if(vrm?.expressionManager){ Object.keys(vrm.expressionManager.expressionMap||{}).forEach(k=>vrm.expressionManager.setValue(k,0)); vrm.expressionManager.update(); }
  return 'ok';
};

// 走 three-vrm 的 expressionManager
window.__setExpr=(n,w)=>{
  if(!vrm?.expressionManager) return 'no mgr';
  Object.keys(vrm.expressionManager.expressionMap||{}).forEach(k=>vrm.expressionManager.setValue(k,0));
  vrm.expressionManager.setValue(n,w);
  vrm.expressionManager.update();
  return 'ok';
};

// 直接设 influence（所有 mesh）
window.__setInfluence=(idx,w)=>{
  let n=0;
  vrm?.scene.traverse(o=>{ if(o.isMesh&&o.morphTargetInfluences&&idx<o.morphTargetInfluences.length){ o.morphTargetInfluences[idx]=w; n++; } });
  return n;
};

// 手动为第一个 mesh 注入一个巨大的 morph target（验证渲染器是否支持 morph）
window.__injectMorph=()=>{
  let done=false;
  vrm?.scene.traverse(o=>{
    if(done||!o.isMesh) return;
    const g=o.geometry;
    const n=g.attributes.position.count;
    const arr=new Float32Array(n*3);
    for(let i=0;i<n;i++){ arr[i*3]=0; arr[i*3+1]=0.25; arr[i*3+2]=0; }  // 整体上移 25cm
    const attr=new THREE.BufferAttribute(arr,3);
    g.morphAttributes.position = g.morphAttributes.position || [];
    g.morphAttributes.position.push(attr);
    g.morphTargetsRelative = true;
    const idx=g.morphAttributes.position.length-1;
    o.morphTargetInfluences = o.morphTargetInfluences || [];
    o.morphTargetInfluences[idx]=1.0;
    o.material.needsUpdate=true;
    g.computeBoundingSphere();
    done=true;
    return {mesh:o.name, idx:idx, verts:n};
  });
  return done;
};

// 手动建一个纯几何体 + morph，最干净的验证
window.__boxMorph=()=>{
  const g=new THREE.BoxGeometry(1,1,1);
  const n=g.attributes.position.count;
  const arr=new Float32Array(n*3);
  for(let i=0;i<n;i++){ arr[i*3+1]=0.8; }
  g.morphAttributes.position=[new THREE.BufferAttribute(arr,3)];
  g.morphTargetsRelative=true;
  const m=new THREE.MeshStandardMaterial({color:0xff0000});
  const mesh=new THREE.Mesh(g,m);
  mesh.morphTargetInfluences=[0];
  mesh.position.set(0,1.4,0.35);
  scene.add(mesh);
  window.__boxMesh=mesh;
  return 'box added, verts='+n;
};
window.__boxSet=(w)=>{ if(window.__boxMesh) window.__boxMesh.morphTargetInfluences[0]=w; return 'ok'; };

// dump 顶点着色器（看 USE_MORPHTARGETS 有没有被定义）
window.__dumpShader=()=>{
  let src='';
  const mats=[];
  vrm?.scene.traverse(o=>{ if(o.isMesh&&o.material&&mats.indexOf(o.material)<0) mats.push(o.material); });
  if(mats.length) {
    const mat=mats[0];
    mat.onBeforeCompile=function(shader){
      window.__vsPrefix = shader.vertexShader.slice(0,1500);
      window.__shaderDump = shader.vertexShader;
    };
    mat.needsUpdate=true;
    renderer.render(scene,camera);
  }
  const vs = window.__shaderDump||'';
  const hasMorphIfdef = vs.indexOf('USE_MORPHTARGETS')>=0;
  const hasMorphRef = vs.indexOf('morphTargetInfluences')>=0;
  return JSON.stringify({
    hasUseMorphTargets: hasMorphIfdef,
    hasMorphInfluences: hasMorphRef,
    vsLen: vs.length,
    // 截取 morph 相关片段
    snippet: (()=>{ const i=vs.indexOf('morphTarget'); return i<0?'(none)':vs.slice(Math.max(0,i-200), i+300); })(),
  });
};
</script></body></html>"""


def png_hash(u):
    if not u or not str(u).startswith("data:image"):
        return None
    return hashlib.md5(base64.b64decode(str(u).split(",", 1)[1])).hexdigest()[:12]


def main() -> int:
    (SRV_DIR / "_morph_diag6.html").write_text(HTML, encoding="utf-8")
    app = QApplication(sys.argv)
    port = serve(SRV_DIR)

    def wait(ms):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def run_case(model: str, combine: bool, tests: str) -> dict:
        """跑一个模型，返回各测试的哈希"""
        print("\n" + "=" * 66)
        print(f"模型: {model}   combineMorphs={combine}")
        print("=" * 66)
        w = QWidget()
        w.resize(300, 380)
        view = QWebEngineView(w)
        pg = Page(view)
        view.setPage(pg)
        view.setGeometry(0, 0, 300, 380)
        pg.setBackgroundColor(QColor(0, 0, 0, 0))
        view.settings().setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, True)
        pg.load(QUrl(f"http://127.0.0.1:{port}/_morph_diag6.html"
                     f"?model={model}&combine={'1' if combine else '0'}"))
        w.show()

        def js(code, timeout=10000):
            box = {"v": None, "done": False}
            pg.runJavaScript(code, lambda v: box.update(v=v, done=True))
            t = 0
            while not box["done"] and t < timeout:
                wait(100)
                t += 100
            return box["v"]

        for _ in range(50):
            wait(400)
            if js("window.__ready === true", 2000):
                break
        else:
            print("  !! 加载超时")
            w.hide()
            return {}
        wait(1200)

        exprs = js("window.__exprs ? window.__exprs.join(',') : ''")
        print(f"  表达式数: {len(str(exprs).split(',')) if exprs else 0}")
        print(f"  表达式: {str(exprs)[:200]}")

        out = {}
        js("window.__clear()")
        wait(700)
        base = png_hash(js("window.__png()"))
        out["_base"] = base
        print(f"  基准 md5 = {base}")

        # 测试 1: 注入一个巨大的 morph（+25cm）
        r = js("window.__injectMorph()")
        wait(900)
        h = png_hash(js("window.__png()"))
        out["injectMorph"] = h
        print(f"  注入 +25cm morph -> {h}  {'★ 生效' if h != base else '无变化'}")
        js("window.__clear()")
        wait(500)

        # 测试 2: 立方体 morph（最干净的验证）
        js("window.__boxMorph()")
        wait(800)
        b0 = png_hash(js("window.__png()"))
        js("window.__boxSet(1.0)")
        wait(800)
        b1 = png_hash(js("window.__png()"))
        out["boxMorph"] = (b0, b1)
        print(f"  立方体 morph: 0.0 -> {b0} / 1.0 -> {b1}  "
              f"{'★ 生效' if b0 != b1 else '无变化'}")

        # 测试 3: 直接设 influence
        if tests == "influence":
            js("window.__clear()")
            wait(600)
            base2 = png_hash(js("window.__png()"))
            for idx in (0, 1, 2):
                n = js(f"window.__setInfluence({idx}, 1.0)")
                wait(700)
                h = png_hash(js("window.__png()"))
                out[f"infl{idx}"] = h
                print(f"  influence[{idx}]=1 on {n} meshes -> {h}  "
                      f"{'★ 生效' if h != base2 else '无变化'}")
                js("window.__clear()")
                wait(400)

        # 测试 4: 用 expressionManager 逐个表情
        if tests == "expr" and exprs:
            names = [x for x in str(exprs).split(",") if x][:6]
            for nm in names:
                js(f"window.__setExpr({json.dumps(nm)}, 1.0)")
                wait(700)
                h = png_hash(js("window.__png()"))
                out[nm] = h
                print(f"  expr {nm:14s} -> {h}  {'★ 生效' if h != base else '无变化'}")

        # shader dump
        sd = js("window.__dumpShader()", 12000)
        print(f"\n  着色器检查: {sd}")
        try:
            d = json.loads(sd)
            out["shader"] = d
        except Exception:
            pass

        w.hide()
        pg.deleteLater()
        wait(500)
        return out

    # ---- 对照实验 ----
    r1 = run_case("michelle_expr.vrm", False, "influence")
    r2 = run_case("Lazuli_VRM.vrm", False, "expr")

    print("\n" + "=" * 66)
    print("结论")
    print("=" * 66)

    def verdict(r, key):
        if key not in r:
            return "未测"
        b = r.get("_base")
        v = r[key]
        if isinstance(v, tuple):
            return "★ 生效" if v[0] != v[1] else "无变化"
        return "★ 生效" if v and v != b else "无变化"

    print(f"  michelle_expr 注入大 morph : {verdict(r1, 'injectMorph')}")
    print(f"  michelle_expr 立方体 morph : "
          f"{'★ 生效' if r1.get('boxMorph') and r1['boxMorph'][0] != r1['boxMorph'][1] else '无变化'}")
    print(f"  michelle_expr influence[0] : {verdict(r1, 'infl0')}")
    print(f"  Lazuli 原生表情            : ", end="")
    lz = [k for k in r2 if k not in ("_base", "injectMorph", "boxMorph", "shader")
          and not k.startswith("infl")]
    if lz:
        hits = [k for k in lz if r2[k] != r2["_base"]]
        print(f"{len(hits)}/{len(lz)} 生效  {hits}")
    else:
        print("未测")
    print(f"  michelle shader 有 MORPHTARGETS: "
          f"{r1.get('shader', {}).get('hasUseMorphTargets')}")
    print(f"  Lazuli shader 有 MORPHTARGETS: "
          f"{r2.get('shader', {}).get('hasUseMorphTargets')}")
    print("=" * 66)
    return 0


if __name__ == "__main__":
    sys.exit(main())
