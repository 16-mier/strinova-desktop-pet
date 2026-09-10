"""qtweb_hotswap2.py —— 隔离测试：VRM 无重启热切换，自驱式（JS 内部自动跑，Python 只轮询）。

排除 runJavaScript 时序 / QWebChannel 干扰，定位 0xC0000409 崩溃点。
每个阶段把结果写进 #st，Python 每 1.5s 读一次，崩溃前最后一条即崩点。

用法：python -u qtweb_hotswap2.py [--port 8931] [--timeout 60] [--mode A|B|C]
  A = 只加载1次（基线）
  B = 加载 → 卸载(dispose) → 再加载
  C = 加载 → 卸载 → 再加载 → 设表情 → 读状态
"""
from __future__ import annotations

import argparse
import http.server
import os
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
const st=document.getElementById('st');
const lines=[]; const P=(m)=>{lines.push(m); st.textContent=lines.join('\\n');};
const MODE = new URLSearchParams(location.search).get('mode') || 'B';

let THREE,GLTFLoader,VRMLoaderPlugin,VRMUtils,renderer,scene,camera,vrm=null;

async function loadModel(url){
  const t0=performance.now();
  const loader=new GLTFLoader();
  loader.register(p=>new VRMLoaderPlugin(p));
  const gltf=await loader.loadAsync(url);
  const v=gltf.userData.vrm;
  scene.add(v.scene); v.scene.rotation.y=Math.PI;
  P('loaded '+url.split('/').pop()+' in '+Math.round(performance.now()-t0)+'ms expr='+
    Object.keys(v.expressionManager?.expressions||{}).length);
  return v;
}

function unload(){
  if(!vrm) return;
  const t0=performance.now();
  scene.remove(vrm.scene);
  try{ VRMUtils.deepDispose(vrm.scene); P('deepDispose ok'); }
  catch(e){ P('deepDispose ERR '+e); }
  vrm=null;
  P('unloaded in '+Math.round(performance.now()-t0)+'ms');
}

(async()=>{
 try{
  THREE=await import('three');
  ({GLTFLoader}=await import('three/addons/loaders/GLTFLoader.js'));
  const m=await import('/vendor/three-vrm.module.js');
  VRMLoaderPlugin=m.VRMLoaderPlugin; VRMUtils=m.VRMUtils;
  P('three='+THREE.REVISION+' VRMUtils='+(!!VRMUtils));

  scene=new THREE.Scene();
  camera=new THREE.PerspectiveCamera(30,1,0.1,100);
  camera.position.set(0,1.2,3); camera.lookAt(0,1.0,0);
  renderer=new THREE.WebGLRenderer({alpha:true,antialias:true});
  renderer.setClearColor(0x000000,0); renderer.setSize(300,380);
  renderer.domElement.style.position='absolute';
  document.body.appendChild(renderer.domElement);
  scene.add(new THREE.AmbientLight(0xffffff,1.4));
  const dl=new THREE.DirectionalLight(0xffffff,2.0); dl.position.set(1,2,2); scene.add(dl);
  P('renderer ready');

  const clock=new THREE.Clock();
  (function loop(){requestAnimationFrame(loop);
    if(vrm){vrm.update(clock.getDelta()); renderer.render(scene,camera);} })();
  P('loop started');

  await new Promise(r=>setTimeout(r,1500));

  if(MODE==='A'){ vrm=await loadModel('/michelle.vrm'); P('A DONE'); return; }

  P('--- swap 1 ---');
  vrm=await loadModel('/michelle.vrm');
  await new Promise(r=>setTimeout(r,800));
  unload();
  await new Promise(r=>setTimeout(r,300));
  P('--- swap 2 (reload) ---');
  vrm=await loadModel('/michelle.vrm');

  if(MODE==='B'){ P('B DONE'); return; }

  await new Promise(r=>setTimeout(r,500));
  const em=vrm.expressionManager;
  for(const k of ['happy','angry','sad','relaxed','surprised']) em.setValue(k,0);
  em.setValue('happy',0.8);
  P('expr happy=0.8 set, readback='+em.getValue('happy'));
  await new Promise(r=>setTimeout(r,800));
  em.setValue('happy',0); em.setValue('angry',1.0);
  P('expr angry=1.0 readback='+em.getValue('angry'));
  await new Promise(r=>setTimeout(r,800));
  P('C DONE | spring='+(!!vrm.springBoneManager)+
    ' | vrma_clips=0 | exprCount='+Object.keys(em.expressions||{}).length);
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
    ap.add_argument("--port", type=int, default=8931)
    ap.add_argument("--timeout", type=float, default=60.0)
    ap.add_argument("--mode", default="B")
    args = ap.parse_args()

    (SRV_DIR / "hotswap2.html").write_text(HTML, encoding="utf-8")
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
    view.page().javaScriptConsoleMessage = lambda lvl, line, src, ln: print(f"[js:{lvl.name}] {line}", flush=True)

    url = f"http://127.0.0.1:{args.port}/hotswap2.html?mode={args.mode}"
    print(f"[run] mode={args.mode} url={url}", flush=True)
    view.load(QUrl(url))
    w.show()

    last = [""]
    t0 = time.time()
    poll_n = [0]

    def poll():
        poll_n[0] += 1
        el = time.time() - t0

        def h(v):
            v = v or ""
            if v != last[0]:
                # 只打印新增行
                old = set(last[0].split("\n"))
                for ln in v.split("\n"):
                    if ln and ln not in old:
                        print(f"[t+{el:5.1f}s] {ln}", flush=True)
                last[0] = v
            if "DONE" in v or "ERR" in v:
                print(f"\n[result] mode={args.mode}\n{v}\n", flush=True)
                app.quit()
        view.page().runJavaScript("document.getElementById('st').textContent", h)

    tm = QTimer()
    tm.timeout.connect(poll)
    tm.start(1500)
    QTimer.singleShot(int(args.timeout * 1000), app.quit)
    app.exec()
    print(f"[final] elapsed={time.time()-t0:.1f}s", flush=True)
    httpd.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
