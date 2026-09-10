"""shot_pet.py —— 给 3D 桌宠拍一张清晰大图（供人工/视觉确认）

用法：python shot_pet.py [--w 700] [--h 900] [--model michelle_expr]
"""
from __future__ import annotations

import argparse
import base64
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
        if level.name.startswith("Error") or "SHOT" in message:
            print(f"  [js] {message[:220]}")


HTML = """<!DOCTYPE html><html><head><meta charset="utf-8">
<style>html,body{margin:0;padding:0;background:#2b2f3a;overflow:hidden}
canvas{display:block;margin:0 auto}</style>
</head><body>
<script type="importmap">
{"imports":{"three":"./vendor/three.module.js","three/addons/":"./vendor/addons/"}}
</script>
<script type="module">
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { VRMLoaderPlugin } from './vendor/three-vrm.module.js';

const P = new URLSearchParams(location.search);
const MODEL = P.get('model') || 'michelle_expr.vrm';
const BG = P.get('bg') || '#2b2f3a';
const W = 600, H = 820;
document.body.style.background = BG;

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(28, W/H, 0.01, 100);
const renderer = new THREE.WebGLRenderer({alpha:true, antialias:true, preserveDrawingBuffer:true});
renderer.setClearColor(0x000000, 0);
renderer.setSize(W, H);
renderer.toneMapping = THREE.NoToneMapping;
renderer.outputColorSpace = THREE.SRGBColorSpace;
document.body.appendChild(renderer.domElement);

// 光照：卡拉彼丘模型是 emissive 显示，光照要克制
scene.add(new THREE.AmbientLight(0xffffff, 0.55));
const d1 = new THREE.DirectionalLight(0xffffff, 0.6); d1.position.set(0.6,2,2.5); scene.add(d1);
const d2 = new THREE.DirectionalLight(0xaaccff, 0.35); d2.position.set(-1,0.6,-1.5); scene.add(d2);

let vrm = null;
window.__ready = false;
window.__exprNames = [];

const loader = new GLTFLoader();
loader.register(p => new VRMLoaderPlugin(p));
loader.load('./models/' + MODEL, (g) => {
  vrm = g.userData.vrm;
  scene.add(vrm.scene);
  // ★ 朝向：这个模型的脸朝 −Z，相机在 +Z（实测：旋转 π 后射线首命中 'Hair' = 后脑勺）
  vrm.scene.rotation.y = 0;
  vrm.scene.traverse(o => { if (o.isMesh) o.frustumCulled = false; });

  const box = new THREE.Box3().setFromObject(vrm.scene);
  const size = box.getSize(new THREE.Vector3());
  // 全身构图
  camera.position.set(0, size.y * 0.55, size.y * 1.15);
  camera.lookAt(0, size.y * 0.52, 0);
  window.__exprNames = Object.keys(vrm.expressionManager?.expressionMap || {});
  console.log('SHOT loaded ' + MODEL + ' exprs=' + window.__exprNames.length + ' h=' + size.y.toFixed(2));
  window.__ready = true;
  (function loop(){ requestAnimationFrame(loop); renderer.render(scene, camera); })();
});

window.__png = () => { renderer.render(scene, camera); return renderer.domElement.toDataURL('image/png'); };
window.__exprs = () => JSON.stringify(window.__exprNames);
window.__setExpr = (n, w) => {
  if (!vrm?.expressionManager) return 'no mgr';
  Object.keys(vrm.expressionManager.expressionMap||{}).forEach(k => vrm.expressionManager.setValue(k, 0));
  vrm.expressionManager.setValue(n, w);
  vrm.expressionManager.update();
  return 'ok';
};
// 头部特写
window.__faceCam = () => {
  const head = vrm.humanoid?.getNormalizedBoneNode('head');
  const hp = head ? head.getWorldPosition(new THREE.Vector3()) : new THREE.Vector3(0,1.4,0);
  camera.position.set(0, hp.y + 0.02, 0.30);
  camera.lookAt(0, hp.y - 0.02, 0);
  return 'face y=' + hp.y.toFixed(3);
};
window.__bodyCam = () => {
  const box = new THREE.Box3().setFromObject(vrm.scene);
  const s = box.getSize(new THREE.Vector3());
  camera.position.set(0, s.y*0.55, s.y*1.15);
  camera.lookAt(0, s.y*0.52, 0);
  return 'body';
};
window.__rotate = (a) => { vrm.scene.rotation.y = Math.PI + a; return 'ok'; };
</script></body></html>"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="michelle_expr.vrm")
    ap.add_argument("--bg", default="#2b2f3a")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    (SRV_DIR / "_shot.html").write_text(HTML, encoding="utf-8")
    app = QApplication(sys.argv)
    port = serve(SRV_DIR)

    w = QWidget()
    w.resize(600, 830)
    view = QWebEngineView(w)
    pg = Page(view)
    view.setPage(pg)
    view.setGeometry(0, 0, 600, 820)
    pg.setBackgroundColor(QColor(args.bg))
    view.settings().setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, True)
    pg.load(QUrl(f"http://127.0.0.1:{port}/_shot.html?model={args.model}&bg={args.bg}"))
    w.show()

    def wait(ms):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def js(code, timeout=12000):
        box = {"v": None, "done": False}
        pg.runJavaScript(code, lambda v: box.update(v=v, done=True))
        t = 0
        while not box["done"] and t < timeout:
            wait(100)
            t += 100
        return box["v"]

    for _ in range(60):
        wait(400)
        if js("window.__ready === true", 2000):
            break
    print(f"[shot] {args.model} 已加载")
    print(f"[shot] 表情: {str(js('window.__exprs()'))[:180]}")
    wait(2000)

    def save(name):
        u = js("window.__png()", 15000)
        if u and str(u).startswith("data:image"):
            out = HERE / name
            out.write_bytes(base64.b64decode(str(u).split(",", 1)[1]))
            print(f"[shot] -> {out.name} ({out.stat().st_size:,} B)")
            return str(out)
        print("[shot] 抓图失败")
        return None

    suffix = args.out or args.model.replace(".vrm", "")
    # 全身像
    js("window.__bodyCam()")
    wait(900)
    save(f"shot_{suffix}_body.png")
    # 脸部特写
    print(f"[shot] {js('window.__faceCam()')}")
    wait(900)
    save(f"shot_{suffix}_face.png")

    return 0


if __name__ == "__main__":
    sys.exit(main())
