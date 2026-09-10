# -*- coding: utf-8 -*-
"""qtweb_spring_probe.py —— 验证 QtWebEngine 内 VRM SpringBone 物理确实在动。

用带 springBone 的模型（Lazuli_VRM.vrm，21 组）：
  1. 确认 springBoneManager 存在且组数 > 0
  2. 让模型头部骨骼猛转，看 springBone 关节的世界坐标是否随之变化（证明确实在算物理）
  3. 报告 VRM0 blendshape / expression 数量

用法：python -u qtweb_spring_probe.py --vrm <路径> [--port 8941]
"""
from __future__ import annotations

import argparse
import glob
import http.server
import os
import shutil
import socketserver
import sys
import threading
import time
from pathlib import Path

os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = os.environ.get(
    "PROBE_FLAGS", "--enable-gpu --ignore-gpu-blocklist --enable-unsafe-swiftshader")

from PyQt6.QtCore import QTimer, Qt, QUrl
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6.QtWebEngineCore import QWebEngineSettings
from PyQt6.QtWebEngineWidgets import QWebEngineView

SRV_DIR = Path(__file__).resolve().parent / "webgpu_probe"

HTML = """<!DOCTYPE html><html><head><meta charset="utf-8"><style>
html,body{margin:0;padding:0;background:transparent;overflow:hidden}
#st{position:absolute;top:2px;left:2px;color:#0f0;font:10px monospace;z-index:9;white-space:pre-wrap;width:310px}
</style></head><body><div id="st">boot</div>
<script type="importmap">
{"imports":{"three":"./vendor/three.module.js","three/addons/":"./vendor/addons/"}}
</script>
<script type="module">
const st=document.getElementById('st'); const L=[]; const P=m=>{L.push(m);st.textContent=L.join('\\n');};
const FILE = new URLSearchParams(location.search).get('f');

(async()=>{
 try{
  const THREE=await import('three');
  const {GLTFLoader}=await import('three/addons/loaders/GLTFLoader.js');
  const {VRMLoaderPlugin,VRMUtils}=await import('/vendor/three-vrm.module.js');

  const scene=new THREE.Scene();
  const cam=new THREE.PerspectiveCamera(30,1,0.1,100);
  cam.position.set(0,1.2,3); cam.lookAt(0,1.0,0);
  const r=new THREE.WebGLRenderer({alpha:true,antialias:true});
  r.setClearColor(0x000000,0); r.setSize(300,380);
  r.domElement.style.position='absolute'; document.body.appendChild(r.domElement);
  scene.add(new THREE.AmbientLight(0xffffff,1.5));
  const dl=new THREE.DirectionalLight(0xffffff,2.0); dl.position.set(1,2,2); scene.add(dl);

  const loader=new GLTFLoader(); loader.register(p=>new VRMLoaderPlugin(p));
  const gltf=await loader.loadAsync('/'+FILE);
  let vrm=gltf.userData.vrm;
  scene.add(vrm.scene); vrm.scene.rotation.y=Math.PI;

  const sbm=vrm.springBoneManager;
  // three-vrm v3: sbm.joints 是 Set<VRMSpringBone>（扁平的关节集合），
  // 老写法 sbm.springBones 已 deprecated，且它是 Set 不是数组 —— .length 恒为 0。
  const allJoints = sbm ? Array.from(sbm.joints || []) : [];
  P('file='+FILE);
  P('springBoneManager='+(!!sbm)+' joints='+allJoints.length);
  P('colliderGroups='+(sbm ? sbm.colliderGroups.length : 0));
  P('expressionManager='+(!!vrm.expressionManager)+' exprCount='+
     Object.keys(vrm.expressionManager?.expressions||{}).length);
  P('humanoid='+(!!vrm.humanoid)+' mtoon='+(gltf.userData.vrmMToonMaterials?.length ?? '?'));

  // 收集 spring bone 关节，记录初始世界坐标
  const joints = allJoints;
  P('joints='+joints.length);
  if(!joints.length){ P('NO_SPRING_JOINTS -> 无法测物理'); P('DONE'); return; }

  const V=(j)=>{ const p=new THREE.Vector3(); (j.bone||j).getWorldPosition(p); return p; };
  const clock=new THREE.Clock();
  (function loop(){requestAnimationFrame(loop); vrm.update(clock.getDelta()); r.render(scene,cam);})();

  // 稳定 1s，记录基准
  await new Promise(res=>setTimeout(res,1000));
  const base=joints.map(V);
  P('baseline captured');

  // 猛转头部 + 整体旋转，制造明显位移
  const head=vrm.humanoid?.getNormalizedBoneNode?.('head');
  let maxDelta=0;
  for(let i=0;i<40;i++){
    if(head) head.rotation.z = 1.2;
    vrm.scene.rotation.y = Math.PI + 0.6;
    await new Promise(res=>setTimeout(res,25));
    for(let k=0;k<joints.length;k++){
      const d=V(joints[k]).distanceTo(base[k]);
      if(d>maxDelta) maxDelta=d;
    }
  }
  P('maxJointWorldDelta='+maxDelta.toFixed(4)+' (米)');
  P('SPRING_MOVING='+(maxDelta>0.0005));
  P('DONE');
 }catch(e){ P('ERR '+e); }
})();
</script></body></html>
"""


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(SRV_DIR), **kw)

    def log_message(self, *a):
        pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vrm", default="")
    ap.add_argument("--port", type=int, default=8941)
    ap.add_argument("--timeout", type=float, default=60.0)
    args = ap.parse_args()

    src = args.vrm
    if not src:
        hits = glob.glob(r"C:\Users\mier\Desktop\deepseek work\**\Lazuli_VRM.vrm", recursive=True)
        src = hits[0] if hits else ""
    if not src or not os.path.isfile(src):
        print(f"[err] VRM not found: {src!r}")
        return 1
    name = "spring_test.vrm"
    dst = SRV_DIR / name
    if not dst.exists() or os.path.getsize(dst) != os.path.getsize(src):
        print(f"[setup] copying {src} -> {dst} ({os.path.getsize(src)/1e6:.1f} MB)")
        shutil.copy2(src, dst)

    (SRV_DIR / "spring.html").write_text(HTML, encoding="utf-8")
    httpd = socketserver.TCPServer(("127.0.0.1", args.port), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    app = QApplication(sys.argv)
    w = QWidget()
    w.setWindowFlags(Qt.WindowType.FramelessWindowHint
                     | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
    w.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    w.setGeometry(300, 300, 320, 400)

    view = QWebEngineView(w)
    view.setGeometry(0, 0, 320, 400)
    view.page().setBackgroundColor(QColor(0, 0, 0, 0))
    s = view.settings()
    for a in ("WebGLEnabled", "Accelerated2dCanvasEnabled",
              "LocalContentCanAccessFileUrls", "LocalContentCanAccessRemoteUrls"):
        s.setAttribute(getattr(QWebEngineSettings.WebAttribute, a), True)
    s.setAttribute(QWebEngineSettings.WebAttribute.ShowScrollBars, False)
    view.page().javaScriptConsoleMessage = lambda lvl, line, src_, ln: print(f"[js] {line}", flush=True)

    view.load(QUrl(f"http://127.0.0.1:{args.port}/spring.html?f={name}"))
    w.show()

    last = [""]
    t0 = time.time()

    def poll():
        el = time.time() - t0

        def h(v):
            v = v or ""
            old = set(last[0].split("\n"))
            for ln in v.split("\n"):
                if ln and ln not in old:
                    print(f"[t+{el:5.1f}s] {ln}", flush=True)
            last[0] = v
            if "DONE" in v or "ERR" in v:
                app.quit()
        view.page().runJavaScript("document.getElementById('st').textContent", h)

    tm = QTimer()
    tm.timeout.connect(poll)
    tm.start(1200)
    QTimer.singleShot(int(args.timeout * 1000), app.quit)
    app.exec()
    print(f"\n[final]\n{last[0]}\n", flush=True)
    httpd.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
