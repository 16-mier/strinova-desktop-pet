"""diag_morph3.py —— 验证 combineMorphs 后 influence 是否还能生效

猜想：VRMUtils.combineMorphs() 会 clone geometry 并重建 morphAttributes，
      但 mesh.morphTargetInfluences 与 geometry.morphAttributes 的对应关系
      可能被破坏（或需要重新拿引用）。

做法：
  1. 不调用 combineMorphs，直接设 influence → 看是否有变化
  2. 调用 combineMorphs 后，打印每个 mesh 的 influence 数组与
     geometry.morphAttributes.position 的长度是否一致
  3. 用 drawRange / 材质 side 等排除干扰
  4. 尝试 material.morphTargets 相关标志

用法：python diag_morph3.py
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

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


class Page(QWebEnginePage):
    def javaScriptConsoleMessage(self, level, message, line, source):
        if level.name.startswith("Error") or "D3" in message:
            print(f"  [js] {message[:250]}")


# 关键实验：加一个 URL 参数控制是否 combineMorphs
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
scene.add(new THREE.AmbientLight(0xffffff,0.6));
const dl=new THREE.DirectionalLight(0xffffff,0.7); dl.position.set(0.5,2,2.5); scene.add(dl);

let vrm=null;
window.__ready=false;
window.__didCombine=false;
const DO_COMBINE = new URLSearchParams(location.search).get('combine') === '1';

const loader=new GLTFLoader();
loader.register(p=>new VRMLoaderPlugin(p));
loader.load('./models/michelle_expr.vrm',(g)=>{
  vrm=g.userData.vrm;
  if(DO_COMBINE){
    try{ VRMUtils.combineMorphs(vrm); window.__didCombine=true; console.log('D3 combineMorphs OK'); }
    catch(e){ console.log('D3 combineMorphs ERR '+e.message); }
  } else {
    console.log('D3 skipped combineMorphs');
  }
  scene.add(vrm.scene); vrm.scene.rotation.y=Math.PI;
  vrm.scene.traverse(o=>{ if(o.isMesh) o.frustumCulled=false; });
  const box=new THREE.Box3().setFromObject(vrm.scene);
  const head=vrm.humanoid?.getNormalizedBoneNode('head');
  const hp=head?head.getWorldPosition(new THREE.Vector3()):new THREE.Vector3(0,1.4,0);
  camera.position.set(0,hp.y+0.02,0.34); camera.lookAt(0,hp.y-0.02,0);
  console.log('D3 ready combine='+DO_COMBINE);
  window.__ready=true;
  (function loop(){ requestAnimationFrame(loop); renderer.render(scene,camera); })();
});

window.__clear=()=>{
  vrm?.scene.traverse(o=>{
    if(o.isMesh&&o.morphTargetInfluences) for(let i=0;i<o.morphTargetInfluences.length;i++) o.morphTargetInfluences[i]=0;
  });
  return 'ok';
};
window.__setTarget=(idx,w)=>{
  let n=0;
  vrm?.scene.traverse(o=>{
    if(o.isMesh&&o.morphTargetInfluences&&idx<o.morphTargetInfluences.length){ o.morphTargetInfluences[idx]=w; n++; }
  });
  return 'touched '+n;
};
window.__png=()=>{ renderer.render(scene,camera); return renderer.domElement.toDataURL('image/png'); };

// 详细结构诊断
window.__struct=()=>{
  const out=[];
  vrm?.scene.traverse(o=>{
    if(!o.isMesh) return;
    const g=o.geometry;
    const ma=g.morphAttributes||{};
    out.push({
      name:o.name,
      visible:o.visible,
      matType:o.material?.type,
      matMorphTargets:o.material?.morphTargets,
      matMorphNormals:o.material?.morphNormals,
      verts:g.attributes.position?.count,
      morphRel:g.morphTargetsRelative,
      morphPos: (ma.position||[]).length,
      morphNorm: (ma.normal||[]).length,
      inf: o.morphTargetInfluences? o.morphTargetInfluences.length : (o.morphTargetInfluences===undefined?'undef':'null'),
      infIsArray: Array.isArray(o.morphTargetInfluences),
      dictLen: o.morphTargetDictionary? Object.keys(o.morphTargetDictionary).length : 0,
      dictKeys: o.morphTargetDictionary? Object.keys(o.morphTargetDictionary).slice(0,3) : null,
    });
  });
  return JSON.stringify(out.slice(0,3), null, 1);
};

// 尝试：直接改 geometry.morphAttributes.position 的数据（绕过 influence）
window.__bumpMorph=(idx,delta)=>{
  let n=0;
  vrm?.scene.traverse(o=>{
    if(!o.isMesh) return;
    const pos=(o.geometry.morphAttributes?.position||[]);
    if(idx>=pos.length||!pos[idx]) return;
    const a=pos[idx].array;
    for(let k=1;k<a.length;k+=3) a[k]+=delta;
    pos[idx].needsUpdate=true;
    if(o.morphTargetInfluences) o.morphTargetInfluences[idx]=1.0;
    n++;
  });
  return 'bumped morph '+idx+' on '+n;
};
</script></body></html>"""


def png_md5(u):
    if not u or not str(u).startswith("data:image"):
        return None
    return hashlib.md5(base64.b64decode(str(u).split(",", 1)[1])).hexdigest()[:12]


def main() -> int:
    (SRV_DIR / "_morph_diag3.html").write_text(HTML, encoding="utf-8")
    app = QApplication(sys.argv)
    port = serve(SRV_DIR)

    results = {}

    for label, combine in (("不做 combineMorphs", False), ("做 combineMorphs", True)):
        print("\n" + "=" * 64)
        print(f"实验: {label}")
        print("=" * 64)

        w = QWidget()
        w.resize(320, 420)
        view = QWebEngineView(w)
        page = Page(view)
        view.setPage(page)
        view.setGeometry(0, 0, 320, 420)
        page.setBackgroundColor(QColor(0, 0, 0, 0))
        view.settings().setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, True)
        url = f"http://127.0.0.1:{port}/_morph_diag3.html?combine={'1' if combine else '0'}"
        page.load(QUrl(url))
        w.show()

        def wait(ms):
            loop = QEventLoop()
            QTimer.singleShot(ms, loop.quit)
            loop.exec()

        def js(code, timeout=10000):
            box = {"v": None, "done": False}
            page.runJavaScript(code, lambda v: box.update(v=v, done=True))
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
        print(f"  combine 已执行: {js('window.__didCombine')}")

        # 结构
        st = js("window.__struct()")
        print(f"\n  结构（前 3 个 mesh）:")
        print("  " + str(st).replace("\n", "\n  ")[:1400])

        # 基准
        js("window.__clear()")
        wait(700)
        base = png_md5(js("window.__png()"))
        print(f"\n  基准 md5 = {base}")

        # 逐个 target 测
        print(f"\n  逐个 morph target 测试（直接设 influence=1.0）:")
        hits = []
        for idx in range(0, 12):
            js(f"window.__setTarget({idx}, 1.0)")
            wait(650)
            m = png_md5(js("window.__png()"))
            ok = m != base
            if ok:
                hits.append(idx)
            print(f"    target[{idx:2d}] -> md5={m}  {'★ 生效' if ok else '无变化'}")
            js("window.__clear()")
            wait(400)
        print(f"\n  => 生效的 target: {hits if hits else '（无）'}")

        # 直接改 morph 数据
        print(f"\n  直接改 morphAttributes 数据 + influence=1:")
        js("window.__clear()")
        wait(500)
        js("window.__bumpMorph(0, 0.05)")
        wait(800)
        m = png_md5(js("window.__png()"))
        print(f"    改 morph[0] 数据 -> md5={m}  {'★ 生效' if m != base else '无变化'}")

        results[label] = {"hits": hits, "base": base}
        w.hide()
        page.deleteLater()
        wait(400)

    print("\n" + "=" * 64)
    print("汇总")
    print("=" * 64)
    for k, v in results.items():
        print(f"  {k}: 生效 target {v['hits'] if v['hits'] else '无'}")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    sys.exit(main())
