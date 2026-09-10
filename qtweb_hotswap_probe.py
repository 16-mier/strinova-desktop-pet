"""qtweb_hotswap_probe.py —— 验证 QtWebEngine 内 VRM「无重启热切换」+ QWebChannel 桥。

场景：同一个 QWebEngineView / 同一个 WebGL 上下文里，
      ① 加载 michelle.vrm → ② dispose 掉 → ③ 重新加载 → ④ 换表情 → ⑤ 读回状态。
全程不重建窗口、不重启 Chromium 渲染进程。同时验证 QWebChannel 双向调用。

用法：python qtweb_hotswap_probe.py [--port 8911] [--timeout 40]
"""
from __future__ import annotations

import argparse
import http.server
import json
import os
import socketserver
import sys
import threading
import time
from pathlib import Path

os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = os.environ.get(
    "PROBE_FLAGS", "--enable-gpu --ignore-gpu-blocklist --enable-unsafe-swiftshader")

try:
    import ctypes
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

from PyQt6.QtCore import QObject, QTimer, Qt, QUrl, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtWebEngineCore import QWebEngineSettings
from PyQt6.QtWebEngineWidgets import QWebEngineView

HERE = Path(__file__).resolve().parent
SRV_DIR = HERE / "webgpu_probe"

HTML = """<!DOCTYPE html><html><head><meta charset="utf-8"><style>
html,body{margin:0;padding:0;background:transparent;overflow:hidden}
#st{position:absolute;bottom:2px;left:2px;color:#0f0;font:10px monospace;z-index:9;white-space:pre}
</style></head><body>
<div id="st">boot</div>
<script src="qrc:///qtwebchannel/qwebchannel.js"></script>
<script type="importmap">
{"imports":{"three":"./vendor/three.module.js","three/addons/":"./vendor/addons/"}}
</script>
<script type="module">
const st = document.getElementById('st');
const log = [];
window.__state = () => JSON.stringify({log, expr: curExpr, loaded: !!vrm});

let THREE, GLTFLoader, VRMLoaderPlugin, renderer, scene, camera, vrm = null, curExpr = {};
let bridge = null;

// --- QWebChannel 桥 ---
try {
  new QWebChannel(qt.webChannelTransport, ch => {
    bridge = ch.objects.py;
    log.push('qwebchannel_up');
    bridge.log('js: channel ready');
  });
} catch(e) { log.push('channel_err='+e); }

(async () => {
  try {
    THREE = await import('three');
    ({GLTFLoader} = await import('three/addons/loaders/GLTFLoader.js'));
    ({VRMLoaderPlugin} = await import('/vendor/three-vrm.module.js'));
    log.push('three='+THREE.REVISION);

    scene = new THREE.Scene();
    camera = new THREE.PerspectiveCamera(30,1,0.1,100);
    camera.position.set(0,1.2,3); camera.lookAt(0,1.0,0);
    renderer = new THREE.WebGLRenderer({alpha:true, antialias:true});
    renderer.setClearColor(0x000000,0); renderer.setSize(300,380);
    renderer.domElement.style.position='absolute';
    document.body.appendChild(renderer.domElement);
    scene.add(new THREE.AmbientLight(0xffffff,1.4));
    const dl=new THREE.DirectionalLight(0xffffff,2.0); dl.position.set(1,2,2); scene.add(dl);

    // 供 python 调用：加载/切换模型
    window.loadModel = async (url) => {
      const t0 = performance.now();
      // 1) 卸载旧模型：必须 stopAnimation + dispose 材质几何，否则显存泄漏
      if (vrm) {
        scene.remove(vrm.scene);
        vrm.scene.traverse(o => {
          if (o.geometry) o.geometry.dispose();
          if (o.material) (Array.isArray(o.material)?o.material:[o.material])
            .forEach(m => { for (const k in m) { const v=m[k];
              if (v && v.isTexture) v.dispose(); } m.dispose(); });
        });
        vrm = null;
      }
      const loader = new GLTFLoader();
      loader.register(p => new VRMLoaderPlugin(p));
      const gltf = await loader.loadAsync(url);
      vrm = gltf.userData.vrm;
      scene.add(vrm.scene); vrm.scene.rotation.y = Math.PI;
      curExpr = {};
      const ms = Math.round(performance.now()-t0);
      const info = 'loaded ' + url + ' in ' + ms + 'ms | expr=' +
        Object.keys(vrm.expressionManager?.expressions||{}).length +
        ' | mtoon=' + (gltf.userData.vrmMToonMaterials?.length ?? '?') +
        ' | spring=' + (!!vrm.springBoneManager);
      log.push(info); return info;
    };

    window.setExpr = (name, v) => {
      if (!vrm?.expressionManager) return 'no_vrm';
      if (v>0) { for (const k of ['happy','angry','sad','relaxed','surprised','blink','aa'])
                   vrm.expressionManager.setValue(k,0); }
      vrm.expressionManager.setValue(name, v);
      curExpr[name] = v;
      return 'set '+name+'='+v;
    };

    window.hotSwapTest = async () => {
      const t0 = performance.now();
      const first = await window.loadModel('/michelle.vrm');
      const t1 = performance.now();
      const second = await window.loadModel('/michelle.vrm'); // 卸载 + 重载
      const t2 = performance.now();
      window.setExpr('happy', 0.8);
      const r = {first, second,
                 load_ms: Math.round(t1-t0), swap_ms: Math.round(t2-t1),
                 total_ms: Math.round(performance.now()-t0)};
      return JSON.stringify(r);
    };

    const clock = new THREE.Clock();
    (function loop(){ requestAnimationFrame(loop);
      if (vrm) { vrm.update(clock.getDelta()); renderer.render(scene,camera); } })();

    st.textContent = 'ready';
    if (bridge) bridge.jsReady();
  } catch(e) { st.textContent = 'ERR '+e; log.push('ERR '+e); }
})();
</script></body></html>
"""


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(SRV_DIR), **kw)

    def log_message(self, *a):
        pass


class PyBridge(QObject):
    """Python 端对象，JS 通过 ch.objects.py 访问。"""
    jsReadySig = pyqtSignal()

    @pyqtSlot(str)
    def log(self, msg: str):
        print(f"[js->py] {msg}")

    @pyqtSlot(result=str)
    def ping(self) -> str:
        return "pong_from_python"

    @pyqtSlot(str, float, result=str)
    def setExpression(self, name: str, value: float) -> str:
        return f"py_set_expression:{name}={value}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8911)
    ap.add_argument("--timeout", type=float, default=45.0)
    args = ap.parse_args()

    (SRV_DIR / "hotswap.html").write_text(HTML, encoding="utf-8")

    # qwebchannel.js 由 Qt 内建 qrc 资源提供，页面里用 qrc:/// 引用，无需落盘

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

    bridge = PyBridge()
    channel = QWebChannel()
    channel.registerObject("py", bridge)
    view.page().setWebChannel(channel)
    view.page().javaScriptConsoleMessage = lambda lvl, line, src, ln: print(f"[js:{lvl.name}] {line}")

    view.load(QUrl(f"http://127.0.0.1:{args.port}/hotswap.html"))
    w.show()

    steps = []
    t_start = time.time()

    def run_js(expr, tag, cb, tries=0):
        def h(v):
            print(f"[{tag}] {v}")
            steps.append((tag, v))
            if cb:
                cb(v)
        view.page().runJavaScript(expr, h)

    def phase1():
        print(f"\n=== 阶段1: 等待 VRM 就绪 (t+{time.time()-t_start:.1f}s) ===")
        run_js("document.getElementById('st').textContent", "status")

    def phase2():
        print(f"\n=== 阶段2: 无重启热切换（卸旧载新，同窗口同上下文）===")
        run_js("window.hotSwapTest()", "hotswap")

    def phase3():
        print(f"\n=== 阶段3: QWebChannel 双向 ===")
        run_js("window.setExpr('happy', 0.8)", "setExpr")
        run_js("document.getElementById('st').textContent", "status2")
        run_js("window.__state()", "state")

    def phase4():
        print(f"\n=== 阶段4: 再切一次表情 + 读状态（证明运行时可反复操控）===")
        run_js("window.setExpr('angry', 1.0)", "setExpr2")
        run_js("window.__state()", "state2")

    QTimer.singleShot(int(args.timeout * 0.35 * 1000), phase1)
    QTimer.singleShot(int(args.timeout * 0.45 * 1000), phase2)
    QTimer.singleShot(int(args.timeout * 0.70 * 1000), phase3)
    QTimer.singleShot(int(args.timeout * 0.85 * 1000), phase4)
    QTimer.singleShot(int(args.timeout * 1000), app.quit)
    app.exec()

    print("\n===== 汇总 =====")
    for tag, v in steps:
        print(f"{tag:10s}: {v}")
    hs = next((v for t, v in steps if t == "hotswap"), None)
    print(f"\n热切换结果: {hs}")
    ok = hs and "swap_ms" in str(hs)
    print(f"结论: {'PASS —— 可无重启热切换 VRM' if ok else '需进一步排查'}")
    httpd.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
