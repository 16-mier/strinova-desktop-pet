"""diag_facing.py —— 判断相机到底看到的是脸还是后脑勺

疑点：CPU 烘焙确实改了顶点（1620 分量、最大位移 1.3cm），但画面零变化。
      若相机看到的是后脑勺，脸上的表情就完全看不见 —— 这能解释一切。

做法：从相机向角色发射线，看第一个命中的是哪个 mesh（材质名）。
      再用头部骨骼的朝向判断脸朝哪边。

用法：python diag_facing.py
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
        if level.name.startswith("Error") or "FACE" in message:
            print(f"  [js] {message[:200]}")


HTML = """<!DOCTYPE html><html><head><meta charset="utf-8">
<style>html,body{margin:0;background:transparent}canvas{display:block}</style></head><body>
<script type="importmap">
{"imports":{"three":"./vendor/three.module.js","three/addons/":"./vendor/addons/"}}
</script>
<script type="module">
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { VRMLoaderPlugin } from './vendor/three-vrm.module.js';

const W=380,H=460;
const scene=new THREE.Scene();
const camera=new THREE.PerspectiveCamera(30,W/H,0.01,100);
const renderer=new THREE.WebGLRenderer({alpha:true,preserveDrawingBuffer:true});
renderer.setSize(W,H);
document.body.appendChild(renderer.domElement);
scene.add(new THREE.AmbientLight(0xffffff,0.8));

let vrm=null;
window.__ready=false;
const loader=new GLTFLoader();
loader.register(p=>new VRMLoaderPlugin(p));
loader.load('./models/michelle_expr.vrm',(g)=>{
  vrm=g.userData.vrm;
  scene.add(vrm.scene);
  window.__ready=true;
  (function loop(){ requestAnimationFrame(loop); renderer.render(scene,camera); })();
});

// 关键实验：不同朝向 + 射线检测
window.__probe=(rotY)=>{
  vrm.scene.rotation.y = Math.PI + rotY;
  vrm.scene.updateMatrixWorld(true);

  const head = vrm.humanoid?.getNormalizedBoneNode('head');
  const hp = head ? head.getWorldPosition(new THREE.Vector3()) : new THREE.Vector3(0,1.4,0);

  // 相机放在头部正前方
  camera.position.set(0, hp.y + 0.01, 0.26);
  camera.lookAt(0, hp.y - 0.02, 0);
  camera.updateMatrixWorld(true);

  // 从相机向头部中心发射线
  const dir = new THREE.Vector3(0, hp.y - 0.01, 0).sub(camera.position).normalize();
  const ray = new THREE.Raycaster(camera.position.clone(), dir);
  const hits = ray.intersectObject(vrm.scene, true);

  const hitInfo = hits.slice(0, 5).map(h => ({
    mesh: h.object.name,
    mat: h.object.material?.name,
    dist: +h.distance.toFixed(4),
  }));

  // 脸网格的世界包围盒 + 法线方向
  let faceInfo = null;
  vrm.scene.traverse(o => {
    if (o.isMesh && o.material?.name === '颜') {
      const box = new THREE.Box3().setFromObject(o);
      const c = box.getCenter(new THREE.Vector3());
      faceInfo = {
        mesh: o.name,
        worldCenter: [+c.x.toFixed(3), +c.y.toFixed(3), +c.z.toFixed(3)],
        worldMinZ: +box.min.z.toFixed(3),
        worldMaxZ: +box.max.z.toFixed(3),
      };
    }
  });

  // 眼睛骨骼世界位置
  const eyeL = vrm.humanoid?.getNormalizedBoneNode('leftEye')?.getWorldPosition(new THREE.Vector3());
  const eyeR = vrm.humanoid?.getNormalizedBoneNode('rightEye')?.getWorldPosition(new THREE.Vector3());

  return JSON.stringify({
    rotY: +rotY.toFixed(2),
    headWorldY: +hp.y.toFixed(3),
    cameraZ: +camera.position.z.toFixed(3),
    rayHits: hitInfo,
    topHit: hits.length ? (hits[0].object.material?.name || hits[0].object.name) : '(none)',
    face: faceInfo,
    eyeL: eyeL ? [+eyeL.x.toFixed(3), +eyeL.y.toFixed(3), +eyeL.z.toFixed(3)] : null,
    eyeR: eyeR ? [+eyeR.x.toFixed(3), +eyeR.y.toFixed(3), +eyeR.z.toFixed(3)] : null,
  });
};

window.__png=()=>{ renderer.render(scene,camera); return renderer.domElement.toDataURL('image/png'); };
</script></body></html>"""


def main() -> int:
    (SRV_DIR / "_facing.html").write_text(HTML, encoding="utf-8")
    app = QApplication(sys.argv)
    port = serve(SRV_DIR)

    w = QWidget()
    w.resize(380, 460)
    view = QWebEngineView(w)
    pg = Page(view)
    view.setPage(pg)
    view.setGeometry(0, 0, 380, 460)
    pg.setBackgroundColor(QColor(0, 0, 0, 0))
    view.settings().setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, True)
    pg.load(QUrl(f"http://127.0.0.1:{port}/_facing.html"))
    w.show()

    def wait(ms):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def js(code, timeout=10000):
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
    wait(1500)
    print("[diag] 加载完成\n")

    for rot in (0.0, 1.5708, 3.1416):
        r = js(f"window.__probe({rot})")
        try:
            d = json.loads(r)
        except Exception:
            print(f"rot={rot}: 解析失败 {str(r)[:200]}")
            continue
        print(f"===== 朝向 rotY={d['rotY']} rad =====")
        print(f"  射线首个命中: {d['topHit']}")
        print(f"  命中序列: {[h['mat'] for h in d['rayHits']]}")
        print(f"  脸网格世界中心: {d['face']['worldCenter'] if d['face'] else None}")
        print(f"  左眼世界坐标: {d['eyeL']}")
        print(f"  相机 z={d['cameraZ']}")
        print()

    print("判读：若首命中是「颜/目/白目」→ 看到的是脸；若是「Hair/猫猫眼罩」→ 是后脑勺")
    return 0


if __name__ == "__main__":
    sys.exit(main())
