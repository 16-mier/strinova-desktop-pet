# -*- coding: utf-8 -*-
"""diag_expr_detail.py —— 精确诊断：为什么某些表情「顶点动了但像素没变」

假设 A：位移量太小（浮点噪声级别），nz 阈值 1e-7 太宽松
假设 B：位移顶点在屏幕上不可见（被遮挡/在视野外）
假设 C：位移方向错了（例如口型往深处动而不是张开）

本脚本对每个表情输出：
  · 每个 mesh 的位移统计：nz(>1e-6) / nz(>1e-3) / max 位移 / 变动顶点质心
  · 据此判断属于哪种情况
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


class Page(QWebEnginePage):
    def javaScriptConsoleMessage(self, level, message, line, source):
        if level.name.startswith("Error") or "DD" in message:
            print(f"  [js] {message[:220]}")


HTML = """<!DOCTYPE html><html><head><meta charset="utf-8">
<style>html,body{margin:0}canvas{display:block}</style></head><body>
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
renderer.setSize(W,H); renderer.toneMapping=THREE.NoToneMapping;
scene.add(new THREE.AmbientLight(0xffffff,0.62));
const d1=new THREE.DirectionalLight(0xffffff,0.68); d1.position.set(0.5,2,2.5); scene.add(d1);

let vrm=null, driver=null;
window.__ready=false;
const loader=new GLTFLoader();
loader.register(p=>new VRMLoaderPlugin(p));
loader.load('./models/michelle_expr.vrm',(g)=>{
  vrm=g.userData.vrm; scene.add(vrm.scene);
  vrm.scene.rotation.y = 0;
  vrm.scene.traverse(o=>{ if(o.isMesh) o.frustumCulled=false; });
  driver=new MorphDriver(vrm,g);
  const eL=vrm.humanoid?.getNormalizedBoneNode('leftEye')?.getWorldPosition(new THREE.Vector3());
  const eR=vrm.humanoid?.getNormalizedBoneNode('rightEye')?.getWorldPosition(new THREE.Vector3());
  let cy=1.46; if(eL&&eR) cy=(eL.y+eR.y)/2;
  camera.position.set(0,cy,0.24); camera.lookAt(0,cy-0.02,0); camera.updateMatrixWorld(true);
  console.log('DD ready '+JSON.stringify(driver.info()));
  window.__ready=true;
  (function loop(){ requestAnimationFrame(loop); renderer.render(scene,camera); })();
});

// 每个 mesh 的名称/顶点数/可见性
window.__meshes=()=>JSON.stringify(driver.meshes.map(e=>({
  name:e.name, count:e.count, visible:e.mesh.visible,
  mat:e.mesh.material?.name||'', transparent:!!e.mesh.material?.transparent,
  opacity:e.mesh.material?.opacity
})));

// 单个表情的详细位移统计（跨所有 mesh）
window.__detail=(name)=>{
  const binds=driver.bindings[name]; if(!binds) return '{}';
  const out=[];
  for(const e of driver.meshes){
    for(const b of binds){
      const m=e.morphs[b.index]; if(!m||!m.array) continue;
      const arr=m.array;
      let nz6=0,nz3=0,nz4=0,max=0,sx=0,sy=0,sz=0,cnt=0;
      const pos=e.base;
      for(let v=0;v<arr.length/3;v++){
        const dx=arr[v*3],dy=arr[v*3+1],dz=arr[v*3+2];
        const a=Math.max(Math.abs(dx),Math.abs(dy),Math.abs(dz));
        if(a>1e-6)nz6++;
        if(a>1e-4)nz4++;
        if(a>1e-3)nz3++;
        if(a>max)max=a;
        if(a>1e-4){ sx+=pos[v*3]; sy+=pos[v*3+1]; sz+=pos[v*3+2]; cnt++; }
      }
      if(nz6||max>0){
        out.push({mesh:e.name, idx:b.index, w:b.weight, verts:arr.length/3,
          nz6:nz6, nz4:nz4, nz3:nz3, max:+max.toFixed(6),
          cx:cnt?+(sx/cnt).toFixed(3):0, cy:cnt?+(sy/cnt).toFixed(3):0, cz:cnt?+(sz/cnt).toFixed(3):0});
      }
    }
  }
  return JSON.stringify(out);
};
// 所有表情概览：每个表情的总 max 位移 + 位移>1mm 的顶点数
window.__summary=()=>{
  const r={};
  for(const name of driver.names()){
    const binds=driver.bindings[name];
    let mx=0,big=0,mid=0,small=0;
    for(const e of driver.meshes) for(const b of binds){
      const m=e.morphs[b.index]; if(!m||!m.array) continue;
      const arr=m.array;
      for(let v=0;v<arr.length/3;v++){
        const a=Math.max(Math.abs(arr[v*3]),Math.abs(arr[v*3+1]),Math.abs(arr[v*3+2]));
        if(a>mx)mx=a;
        if(a>1e-3)big++; else if(a>1e-4)mid++; else if(a>1e-6)small++;
      }
    }
    r[name]={max:+mx.toFixed(6),gt1mm:big,gt01mm:mid,noise:small};
  }
  return JSON.stringify(r);
};
</script></body></html>"""


def main() -> int:
    (SRV_DIR / "_dd.html").write_text(HTML, encoding="utf-8")
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
    pg.load(QUrl(f"http://127.0.0.1:{port}/_dd.html"))
    w.show()

    def wait(ms):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def js(code, timeout=25000):
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
        print("!! 未加载")
        return 1
    wait(1000)

    print("=" * 78)
    print("mesh 清单（按顶点数排序）")
    print("=" * 78)
    ms = json.loads(js("window.__meshes()") or "[]")
    for m in sorted(ms, key=lambda x: -x["count"]):
        print(f"  {m['name']:<24s} 顶点{m['count']:>6d}  vis={m['visible']}  mat={m['mat']:<16s} "
              f"transp={m['transparent']} op={m['opacity']}")
    tot = sum(m["count"] for m in ms)
    print(f"  合计: {tot} 顶点 / {len(ms)} mesh")

    print("\n" + "=" * 78)
    print("全部表情位移量级总览")
    print("   gt1mm = 位移>1mm 的顶点数 | gt01mm = >0.1mm | noise = >1e-6(可能是浮点噪声)")
    print("=" * 78)
    s = json.loads(js("window.__summary()") or "{}")
    print(f"{'表情':<14s}{'max位移':>10s}{'gt1mm':>8s}{'gt01mm':>8s}{'noise':>8s}  判定")
    print("-" * 78)
    for nm, d in sorted(s.items(), key=lambda kv: -kv[1]["max"]):
        verdict = "★ 位移充分" if d["gt1mm"] > 0 else ("△ 位移极小" if d["gt01mm"] > 0 else "✗ 纯噪声")
        print(f"{nm:<14s}{d['max']:10.6f}{d['gt1mm']:8d}{d['gt01mm']:8d}{d['noise']:8d}  {verdict}")

    print("\n" + "=" * 78)
    print("失败表情逐个解剖")
    print("=" * 78)
    for nm in ["ih", "ou", "lookLeft", "lookRight", "ω", "∧", "ぺろっ", "口横広げ"]:
        if nm not in s:
            print(f"\n【{nm}】不在表达式中")
            continue
        print(f"\n【{nm}】 {s[nm]}")
        det = json.loads(js(f"window.__detail({json.dumps(nm)})") or "[]")
        if not det:
            print("    (无任何位移)")
        for d in det:
            print(f"    mesh={d['mesh']:<22s} target#{d['idx']:<3d} w={d['weight']}  "
                  f"nz6={d['nz6']:<5d} nz4={d['nz4']:<5d} nz3={d['nz3']:<4d} max={d['max']:.6f}")
            print(f"      变动顶点质心: ({d['cx']}, {d['cy']}, {d['cz']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
