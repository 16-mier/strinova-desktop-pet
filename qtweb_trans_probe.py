"""qtweb_trans_probe.py —— 判定 QtWebEngine 透明背景是否"真的透到桌面"。

方法：窗口显示前先用 GDI GetPixel 采样桌面若干点，显示窗口后再采样同一批点。
      若采样值不变 → 该点处确实透出桌面；若变黑/变白 → 未透明。
另附：WebGL 可用性 + three-vrm 是否成功加载 VRM + 窗口 grab 的 alpha 通道。

用法：python qtweb_trans_probe.py [--port 8899] [--timeout 20]
"""
from __future__ import annotations

import argparse
import ctypes
import http.server
import os
import socketserver
import sys
import threading
import time
from pathlib import Path

FLAGS = os.environ.get("PROBE_FLAGS", "--enable-gpu --ignore-gpu-blocklist --enable-unsafe-swiftshader")
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = FLAGS

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

from PyQt6.QtCore import QTimer, Qt, QUrl
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6.QtWebEngineCore import QWebEngineSettings
from PyQt6.QtWebEngineWidgets import QWebEngineView

HERE = Path(__file__).resolve().parent
SRV_DIR = HERE / "webgpu_probe"
VENDOR = SRV_DIR / "vendor"

gdi32 = ctypes.windll.gdi32
user32 = ctypes.windll.user32

HTML = """<!DOCTYPE html><html><head><meta charset="utf-8"><style>
html,body{margin:0;padding:0;background:transparent;overflow:hidden}
#status{position:absolute;bottom:2px;left:2px;color:#0f0;font:10px monospace;z-index:9}
</style></head><body>
<div id="status">init</div>
<script type="importmap">
{"imports":{
 "three":"./vendor/three.module.js",
 "three/addons/":"./vendor/addons/"
}}
</script>
<script type="module">
const st = document.getElementById('status');
let webgl=false;
try { const c=document.createElement('canvas'); webgl = !!(c.getContext('webgl2')||c.getContext('webgl')); } catch(e){}
let info='webgl='+webgl;
try{
  const THREE = await import('three');
  const {GLTFLoader} = await import('three/addons/loaders/GLTFLoader.js');
  const {VRMLoaderPlugin} = await import('/vendor/three-vrm.module.js');
  const {VRMAnimationLoaderPlugin} = await import('/vendor/three-vrm-animation.module.js');
  info += ' three='+THREE.REVISION;
  const sc=new THREE.Scene();
  const cam=new THREE.PerspectiveCamera(30,1,0.1,100); cam.position.set(0,1.2,3); cam.lookAt(0,1.0,0);
  const r=new THREE.WebGLRenderer({alpha:true,antialias:true});
  r.setClearColor(0x000000,0); r.setSize(300,380);
  r.domElement.style.position='absolute'; r.domElement.style.left='0'; r.domElement.style.top='0';
  document.body.appendChild(r.domElement);
  sc.add(new THREE.AmbientLight(0xffffff,1.4));
  const dl=new THREE.DirectionalLight(0xffffff,2.0); dl.position.set(1,2,2); sc.add(dl);
  const ld=new GLTFLoader();
  ld.register(p=>new VRMLoaderPlugin(p));
  ld.register(p=>new VRMAnimationLoaderPlugin(p));
  const gltf=await ld.loadAsync('/michelle.vrm');
  info += ' | udKeys='+Object.keys(gltf.userData||{}).join(',');
  const vrm=gltf.userData.vrm;
  if(!vrm){ st.textContent=info+' | NO_VRM_IN_USERDATA'; window.__probe=info+' | NO_VRM_IN_USERDATA'; throw new Error('no vrm'); }
  sc.add(vrm.scene); vrm.scene.rotation.y=Math.PI;
  const em=vrm.expressionManager;
  const clips=gltf.userData.vrmAnimations||[];
  info += ' | VRM_OK='+(vrm.meta?.name||vrm.userData?.meta?.name||'?')
        + ' | expr='+Object.keys(em?em.expressions||{}:{}).length
        + ' | spring='+(vrm.springBoneManager?vrm.springBoneManager.springBoneGroups.length:0)
        + ' | vrma='+clips.length;
  const clock=new THREE.Clock();
  (function loop(){ requestAnimationFrame(loop);
     vrm.update(clock.getDelta()); r.render(sc,cam); })();
}catch(e){ info+=' | ERR='+e; }
st.textContent=info; window.__probe=info;
</script></body></html>
"""


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(SRV_DIR), **kw)

    def log_message(self, *a):
        pass


class Page_:
    pass


def get_pixel(x: int, y: int) -> tuple:
    hdc = user32.GetDC(0)
    try:
        c = gdi32.GetPixel(hdc, int(x), int(y))
    finally:
        user32.ReleaseDC(0, hdc)
    if c == 0xFFFFFFFF:
        return (-1, -1, -1)
    return (c & 0xFF, (c >> 8) & 0xFF, (c >> 16) & 0xFF)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8899)
    ap.add_argument("--timeout", type=float, default=20.0)
    ap.add_argument("--x", type=int, default=300)
    ap.add_argument("--y", type=int, default=300)
    args = ap.parse_args()

    (SRV_DIR / "trans_probe.html").write_text(HTML, encoding="utf-8")

    httpd = socketserver.TCPServer(("127.0.0.1", args.port), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    W, H = 320, 400
    X, Y = args.x, args.y
    # 采样点：四角 + 窗口中部空白处（故意避开 canvas 区域）
    pts = {
        "corner_tl": (X + 3, Y + 3),
        "corner_tr": (X + W - 4, Y + 3),
        "corner_bl": (X + 3, Y + H - 4),
        "corner_br": (X + W - 4, Y + H - 4),
        "center": (X + W // 2, Y + H // 2),
    }

    app = QApplication(sys.argv)

    # --- 背景底板：纯洋红窗口，铺在探测窗口正后方 ---
    from PyQt6.QtWidgets import QLabel
    backdrop = QLabel()
    backdrop.setStyleSheet("background-color: rgb(255,0,255);")
    backdrop.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
    backdrop.setGeometry(X, Y, W, H)
    backdrop.show()

    w = QWidget()
    w.setWindowFlags(Qt.WindowType.FramelessWindowHint
                     | Qt.WindowType.WindowStaysOnTopHint
                     | Qt.WindowType.Tool)
    w.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    w.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
    w.setGeometry(X, Y, W, H)

    view = QWebEngineView(w)
    view.setGeometry(0, 0, W, H)
    view.page().setBackgroundColor(QColor(0, 0, 0, 0))
    s = view.settings()
    s.setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, True)
    s.setAttribute(QWebEngineSettings.WebAttribute.Accelerated2dCanvasEnabled, True)
    s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
    s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
    s.setAttribute(QWebEngineSettings.WebAttribute.ShowScrollBars, False)

    msgs = []
    view.page().javaScriptConsoleMessage = lambda lvl, line, src, ln: msgs.append(line)

    before = {k: get_pixel(*p) for k, p in pts.items()}
    print(f"[flags] {FLAGS}")
    print(f"[before] window hidden -> {before}")

    view.load(QUrl(f"http://127.0.0.1:{args.port}/trans_probe.html"))
    w.show()

    out = {}

    def step2():
        after = {k: get_pixel(*p) for k, p in pts.items()}
        print(f"[after ] window shown  -> {after}")
        out["after"] = after

        same = {k: (before[k] == after[k]) for k in pts}
        print(f"[same? ] pixel unchanged (==透出桌面) -> {same}")
        out["same"] = same

        # 窗口自身 grab 的 alpha（Qt 侧是否认为透明）
        pm = w.grab()
        img = pm.toImage()
        out["grab_alpha_tl"] = img.pixelColor(2, 2).alpha()
        out["grab_alpha_ctr"] = img.pixelColor(W // 2, H // 2).alpha()
        print(f"[grab  ] alpha tl={out['grab_alpha_tl']} center={out['grab_alpha_ctr']}")

        def on_js(v):
            out["js"] = v
            print(f"[js    ] {v}")
            app.quit()

        view.page().runJavaScript("window.__probe || document.getElementById('status').textContent", on_js)

    QTimer.singleShot(int(args.timeout * 1000), step2)
    app.exec()

    print("\n===== 判定 =====")
    js = str(out.get("js", ""))
    trans_ok = sum(1 for v in out.get("same", {}).values() if v)
    print(f"JS          : {js}")
    print(f"透出桌面的采样点数: {trans_ok}/{len(pts)}")
    print(f"grab alpha  : tl={out.get('grab_alpha_tl')} center={out.get('grab_alpha_ctr')}")
    print(f"VRM 加载    : {'OK' if 'VRM_OK=' in js else 'FAIL'}")
    print(f"结论        : {'透明背景可用' if trans_ok >= 4 else '透明背景不可用/部分失败'}")
    httpd.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
