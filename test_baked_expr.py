"""test_baked_expr.py —— 验证 CPU 顶点烘焙方案真的能让表情生效

原理：morph target 在 QtWebEngine 里不生效（已证实），
      本测试改用 MorphDriver 直接在 CPU 上改顶点位置。

判定：对每个表情，比较「基准帧」与「设置表情后」的 PNG 像素差异。
      差异 > 0 像素 = 生效。

用法：python test_baked_expr.py
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
    "--ignore-gpu-blocklist --enable-gpu-rasterization --enable-unsafe-swiftshader",
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
        if level.name.startswith("Error") or "BAKE" in message:
            print(f"  [js] {message[:220]}")


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
import { MorphDriver } from './vrm_morphs.js';

const W = 380, H = 460;
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(30, W/H, 0.01, 100);
const renderer = new THREE.WebGLRenderer({alpha:true, antialias:true, preserveDrawingBuffer:true});
renderer.setClearColor(0x000000, 0);
renderer.setSize(W, H);
renderer.toneMapping = THREE.NoToneMapping;
renderer.outputColorSpace = THREE.SRGBColorSpace;
document.body.appendChild(renderer.domElement);
scene.add(new THREE.AmbientLight(0xffffff, 0.55));
const d1 = new THREE.DirectionalLight(0xffffff, 0.6); d1.position.set(0.6,2,2.5); scene.add(d1);

let vrm = null, driver = null;
window.__ready = false;

const loader = new GLTFLoader();
loader.register(p => new VRMLoaderPlugin(p));
loader.load('./models/michelle_expr.vrm', (g) => {
  vrm = g.userData.vrm;
  scene.add(vrm.scene);
  vrm.scene.rotation.y = Math.PI;
  vrm.scene.traverse(o => { if (o.isMesh) o.frustumCulled = false; });

  // ★ 建 CPU 烘焙驱动器
  driver = new MorphDriver(vrm, g);
  window.__driver = driver;
  console.log('BAKE driver: ' + JSON.stringify(driver.info()));

  // 相机对准脸部（表情细微，要贴近看）
  const head = vrm.humanoid?.getNormalizedBoneNode('head');
  const hp = head ? head.getWorldPosition(new THREE.Vector3()) : new THREE.Vector3(0,1.4,0);
  camera.position.set(0, hp.y + 0.005, 0.24);
  camera.lookAt(0, hp.y - 0.02, 0);

  window.__ready = true;
  (function loop(){ requestAnimationFrame(loop); renderer.render(scene, camera); })();
});

window.__exprs = () => JSON.stringify(driver ? driver.names() : []);
window.__info  = () => JSON.stringify(driver ? driver.info() : {});
window.__png   = () => { renderer.render(scene, camera); return renderer.domElement.toDataURL('image/png'); };

// 通过 driver 设表情（CPU 烘焙）
window.__set = (n, w) => {
  if (!driver) return 'no driver';
  driver.clear();
  const ok = driver.set(n, w);
  driver.apply();
  return ok ? ('set ' + n + '=' + w) : ('unknown expr ' + n);
};
window.__clear = () => { if (driver) { driver.clear(); driver.apply(); } return 'ok'; };
window.__active = () => JSON.stringify(driver ? driver.active() : []);
// 读顶点实际位移量（证明 CPU 真的改了数据）
window.__vertexDelta = () => {
  if (!driver || !driver.meshes.length) return 'no driver';
  const e = driver.meshes[0];
  const cur = e.mesh.geometry.attributes.position.array;
  let maxd = 0, nz = 0;
  for (let i = 0; i < cur.length; i++) {
    const d = Math.abs(cur[i] - e.base[i]);
    if (d > 1e-7) nz++;
    if (d > maxd) maxd = d;
  }
  return JSON.stringify({mesh: e.name, verts: e.count, changedComponents: nz, maxDelta: +maxd.toFixed(6)});
};
</script></body></html>"""


def png_bytes(u):
    if not u or not str(u).startswith("data:image"):
        return None
    return base64.b64decode(str(u).split(",", 1)[1])


def main() -> int:
    (SRV_DIR / "_bake_test.html").write_text(HTML, encoding="utf-8")
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
    pg.load(QUrl(f"http://127.0.0.1:{port}/_bake_test.html"))
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
    print("[test] 加载完成")
    print(f"[test] driver 信息: {js('window.__info()')}")
    wait(1500)

    # 基准
    js("window.__clear()")
    wait(800)
    base_raw = png_bytes(js("window.__png()"))
    base_md5 = hashlib.md5(base_raw).hexdigest()[:12] if base_raw else None
    print(f"[test] 基准 md5 = {base_md5}")

    names = js("window.__exprs()")
    try:
        names = json.loads(names)
    except Exception:
        names = []
    print(f"[test] 表达式 {len(names)} 个\n")

    # 测试一个表情的顶点位移（先证明 CPU 真的改了数据）
    js("window.__set('happy', 1.0)")
    wait(400)
    print(f"[test] happy 顶点位移: {js('window.__vertexDelta()')}")

    KEY = ["blink", "blinkLeft", "blinkRight", "happy", "angry", "sad",
           "surprised", "relaxed", "aa", "ih", "ou", "ee", "oh",
           "lookUp", "lookDown", "lookLeft", "lookRight"]
    test_list = [n for n in KEY if n in names] + [n for n in names if n not in KEY][:8]

    print(f"\n{'表情':<16s} {'顶点变化':>9s} {'像素差异':>9s}  判定")
    print("-" * 52)
    results = {}
    for name in test_list:
        r = js(f"window.__set({json.dumps(name)}, 1.0)")
        wait(650)
        vd = js("window.__vertexDelta()")
        try:
            vdj = json.loads(vd)
            vchanged = vdj.get("changedComponents", 0)
        except Exception:
            vchanged = 0
        raw = png_bytes(js("window.__png()"))
        if raw is None:
            continue
        md5 = hashlib.md5(raw).hexdigest()[:12]

        diff = 0
        if HAS_PIL and base_raw:
            try:
                a = Image.open(io.BytesIO(base_raw)).convert("RGBA")
                b = Image.open(io.BytesIO(raw)).convert("RGBA")
                if a.size == b.size:
                    da = list(a.getdata())
                    db = list(b.getdata())
                    for p, q in zip(da, db):
                        if abs(p[0]-q[0]) + abs(p[1]-q[1]) + abs(p[2]-q[2]) > 10:
                            diff += 1
            except Exception:
                pass

        changed = (md5 != base_md5)
        results[name] = {"md5": md5, "diff": diff, "vchanged": vchanged, "changed": changed}
        mark = "★ 生效" if changed else "无变化"
        print(f"{name:<16s} {vchanged:9d} {diff:9d}  {mark}")

    ok = [k for k, v in results.items() if v["changed"]]
    print("-" * 52)
    print(f"结果: {len(ok)}/{len(results)} 个表情生效")

    # 存两张对比图
    js("window.__clear()")
    wait(700)
    r = png_bytes(js("window.__png()"))
    if r:
        (HERE / "bake_neutral.png").write_bytes(r)
    js("window.__set('happy', 1.0)")
    wait(700)
    r = png_bytes(js("window.__png()"))
    if r:
        (HERE / "bake_happy.png").write_bytes(r)
    js("window.__set('blink', 1.0)")
    wait(700)
    r = png_bytes(js("window.__png()"))
    if r:
        (HERE / "bake_blink.png").write_bytes(r)
    print("[test] 对比图: bake_neutral.png / bake_happy.png / bake_blink.png")

    print(f"\n[test] driver 最终信息: {js('window.__info()')}")
    return 0 if len(ok) >= len(results) * 0.8 else 1


if __name__ == "__main__":
    sys.exit(main())
