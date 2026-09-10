"""test_expr_render.py —— 实测转换后的 VRM 表情真的能改变画面

做法：在 QtWebEngine 里加载 michelle_expr.vrm，对每个表情：
  1. 归零所有表情 → 抓一帧基准
  2. 设置该表情 = 1.0 → 抓一帧
  3. 对比两帧像素差异 → 有差异说明表情生效

用法：python test_expr_render.py
"""
from __future__ import annotations

import base64
import http.server
import io
import json
import os
import socketserver
import sys
import threading
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent
SRV_DIR = HERE / "web3d"
sys.path.insert(0, str(HERE))

os.environ.setdefault(
    "QTWEBENGINE_CHROMIUM_FLAGS",
    "--ignore-gpu-blocklist --enable-gpu-renderer --enable-unsafe-swiftshader",
)

from PyQt6.QtCore import QTimer, QUrl, QEventLoop
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PyQt6.QtWebEngineWidgets import QWebEngineView

from web3d_server import serve


class Page(QWebEnginePage):
    def javaScriptConsoleMessage(self, level, message, line, source):
        if level.name.startswith("Error") or "EXPR" in message or "VRM" in message:
            print(f"  [js] {message[:200]}")


# 测试页面：加载指定 VRM，提供表情开关 + 像素摘要
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

const W = 300, H = 400;
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(25, W/H, 0.1, 100);
const renderer = new THREE.WebGLRenderer({alpha:true, antialias:true, preserveDrawingBuffer:true});
renderer.setClearColor(0x000000, 0);
renderer.setSize(W, H);
renderer.toneMapping = THREE.NoToneMapping;
renderer.outputColorSpace = THREE.SRGBColorSpace;
document.body.appendChild(renderer.domElement);
scene.add(new THREE.AmbientLight(0xffffff, 0.5));
const dl = new THREE.DirectionalLight(0xffffff, 0.55); dl.position.set(0.5,2,2.5); scene.add(dl);

let vrm = null;
window.__exprs = [];

const loader = new GLTFLoader();
loader.register(p => new VRMLoaderPlugin(p));
loader.load('./models/michelle_expr.vrm', (gltf) => {
  vrm = gltf.userData.vrm;
  // ★ 关键：合并散布在多个 primitive 上的 morph target
  //   three.js 把「一个 glTF mesh 带多 primitive」拆成多个 THREE.Mesh，
  //   而 VRM 的表情 bind 只指向其中一个 → 不合并的话表情只有 1/N 生效
  //   （实测：米雪儿 24 个 primitive，不合并时整帧像素零变化）
  try { VRMUtils.combineMorphs(vrm); console.log('EXPR combineMorphs OK'); }
  catch (e) { console.log('EXPR combineMorphs FAIL: ' + e.message); }

  scene.add(vrm.scene);
  vrm.scene.rotation.y = Math.PI;
  vrm.scene.traverse(o => { if (o.isMesh) o.frustumCulled = false; });
  // 对准脸部超特写（表情只有毫米级位移，必须贴近看）
  const box = new THREE.Box3().setFromObject(vrm.scene);
  const size = box.getSize(new THREE.Vector3());
  const head = vrm.humanoid?.getNormalizedBoneNode('head');
  const hp = head ? head.getWorldPosition(new THREE.Vector3()) : new THREE.Vector3(0, size.y*0.92, 0);
  window.__headY = hp.y;
  // 相机贴近脸部：距离 0.22m，正对头部
  camera.position.set(0, hp.y + 0.02, 0.26);
  camera.lookAt(0, hp.y - 0.01, 0);
  camera.fov = 30;
  camera.updateProjectionMatrix();
  console.log('EXPR camera near head y=' + hp.y.toFixed(3));
  window.__exprs = Object.keys(vrm.expressionManager?.expressionMap || {});
  window.__morphs = vrm.expressionManager ? Object.keys(vrm.expressionManager.expressionMap).length : 0;
  // morph target 数量
  let mt = 0; vrm.scene.traverse(o => { if (o.isMesh) mt += (o.morphTargetInfluences?.length || 0); });
  window.__morphTargetCount = mt;
  console.log('EXPR loaded: ' + window.__exprs.length + ' exprs, ' + mt + ' morph targets');
  window.__loaded = true;
});

// 全清
window.__clear = () => {
  if (!vrm?.expressionManager) return 'no mgr';
  const em = vrm.expressionManager;
  em.expressionMap && Object.keys(em.expressionMap).forEach(k => em.setValue(k, 0));
  em.update();
  return 'cleared';
};
// 设一个表情
window.__set = (name, w) => {
  if (!vrm?.expressionManager) return 'no mgr';
  const em = vrm.expressionManager;
  Object.keys(em.expressionMap || {}).forEach(k => em.setValue(k, 0));
  em.setValue(name, w);
  em.update();
  return 'set ' + name + '=' + w;
};
// 查看各 mesh 的实际 morph 权重（关键调试）
window.__influences = () => {
  const out = [];
  vrm?.scene.traverse(o => {
    if (o.isMesh && o.morphTargetInfluences) {
      const nz = [];
      o.morphTargetInfluences.forEach((v, i) => { if (v > 0.01) nz.push(i + ':' + v.toFixed(2)); });
      out.push({name: o.name, count: o.morphTargetInfluences.length, active: nz.slice(0, 8)});
    }
  });
  return JSON.stringify(out);
};
// 表达式映射（确认 index 对应关系）
window.__map = () => {
  const d = {};
  vrm?.expressionManager?.expressionMap && Object.keys(vrm.expressionManager.expressionMap).forEach(k => {
    d[k] = vrm.expressionManager.expressionMap[k].index;
  });
  return JSON.stringify(d);
};
// 像素摘要：全画面（脸部特写下整屏都是脸）
window.__faceSig = () => {
  renderer.render(scene, camera);
  const gl = renderer.getContext();
  const w = renderer.domElement.width, h = renderer.domElement.height;
  const buf = new Uint8Array(w*h*4);
  gl.readPixels(0, 0, w, h, gl.RGBA, gl.UNSIGNED_BYTE, buf);
  const bins = new Array(16).fill(0);
  let n = 0, sum = [0,0,0];
  // 全画面 + 精确哈希（捕捉细微差异）
  let hash = 0;
  for (let y = 0; y < h; y += 2) {
    for (let x = 0; x < w; x += 2) {
      const i = (y*w + x)*4;
      if (buf[i+3] < 32) continue;
      const lum = (buf[i]*0.299 + buf[i+1]*0.587 + buf[i+2]*0.114);
      bins[Math.min(15, Math.floor(lum/16))]++;
      sum[0] += buf[i]; sum[1] += buf[i+1]; sum[2] += buf[i+2];
      hash = (hash * 31 + buf[i] + buf[i+1]*3 + buf[i+2]*7) | 0;
      n++;
    }
  }
  return JSON.stringify({n: n, bins: bins, hash: hash,
    mean: n ? [sum[0]/n, sum[1]/n, sum[2]/n].map(v => +v.toFixed(3)) : [0,0,0]});
};
window.__snap = () => { renderer.render(scene, camera); return renderer.domElement.toDataURL('image/png'); };
window.__info = () => JSON.stringify({
  exprs: window.__exprs, morphTargets: window.__morphTargetCount,
  loaded: !!window.__loaded,
  influences: (() => { const r = []; vrm?.scene.traverse(o => { if (o.isMesh && o.morphTargetInfluences) r.push(o.morphTargetInfluences.length); }); return r; })(),
});
</script></body></html>"""


def main() -> int:
    (SRV_DIR / "_expr_test.html").write_text(HTML, encoding="utf-8")

    app = QApplication(sys.argv)
    port = serve(SRV_DIR)
    print(f"[test] 服务 http://127.0.0.1:{port}/")

    w = QWidget()
    w.setWindowFlags(w.windowFlags() | w.windowFlags().FramelessWindowHint)
    w.setAttribute(w.windowFlags().__class__.FramelessWindowHint, False) if False else None
    w.resize(300, 400)

    view = QWebEngineView(w)
    page = Page(view)
    view.setPage(page)
    view.setGeometry(0, 0, 300, 400)
    page.setBackgroundColor(QColor(0, 0, 0, 0))
    s = view.settings()
    s.setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, True)
    s.setAttribute(QWebEngineSettings.WebAttribute.ShowScrollBars, False)

    page.load(QUrl(f"http://127.0.0.1:{port}/_expr_test.html"))
    w.show()

    def wait(ms):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def js(code, timeout=6000):
        box = {"v": None, "done": False}
        page.runJavaScript(code, lambda v: box.update(v=v, done=True))
        t0 = 0
        while not box["done"] and t0 < timeout:
            wait(100)
            t0 += 100
        return box["v"]

    # 等加载
    print("[test] 等待模型加载…")
    for i in range(50):
        wait(400)
        if js("window.__loaded === true", 2000):
            print(f"[test] 加载完成 ({(i+1)*0.4:.1f}s)")
            break
    else:
        print("[test] 加载超时")
        return 1

    info = js("window.__info()")
    print(f"\n[test] 模型信息: {info}")
    try:
        d = json.loads(info)
        print(f"       表达式 {len(d['exprs'])} 个")
        print(f"       morph target 总数: {d['morphTargets']}")
        print(f"       各 mesh influences: {d['influences']}")
    except Exception:
        pass

    wait(1500)

    # 基准
    js("window.__clear()")
    wait(800)
    base = js("window.__faceSig()")
    print(f"\n[test] 基准（无表情）: {base}")
    try:
        b = json.loads(base)
    except Exception:
        b = {"n": 0, "bins": [0] * 16, "mean": [0, 0, 0]}

    # 调试: 看 morph target 的 index 映射 + 影响值
    print(f"\n[test] 表达式 index 映射: {js('window.__map()')}")
    js("window.__set('happy', 1.0)")
    wait(500)
    print(f"[test] happy=1.0 后各 mesh 影响值:")
    print(f"       {js('window.__influences()')}")
    js("window.__set('blink', 1.0)")
    wait(500)
    print(f"[test] blink=1.0 后各 mesh 影响值:")
    print(f"       {js('window.__influences()')}")

    # 逐个表情测试
    exprs = json.loads(info)["exprs"] if info else []
    KEY = ["blink", "blinkLeft", "blinkRight", "happy", "angry", "sad",
           "surprised", "relaxed", "aa", "ih", "ou", "ee", "oh",
           "lookUp", "lookDown", "lookLeft", "lookRight"]
    test_list = [e for e in KEY if e in exprs] + [e for e in exprs if e not in KEY][:5]

    print(f"\n[test] 逐个表情测试（对比脸部像素分布变化）")
    print(f"       {'表情':14s} {'像素数':>7s} {'亮度均值变化':>14s} {'直方图差异':>10s}  判定")
    results = {}
    for name in test_list:
        js(f"window.__set({json.dumps(name)}, 1.0)")
        wait(700)
        sig = js("window.__faceSig()")
        try:
            s2 = json.loads(sig)
        except Exception:
            continue
        dm = [abs(s2["mean"][i] - b["mean"][i]) for i in range(3)]
        dmean = sum(dm) / 3
        dhist = sum(abs(s2["bins"][i] - b["bins"][i]) for i in range(16))
        dn = abs(s2["n"] - b["n"])
        # 哈希不同 = 像素真的变了（最灵敏）
        dhash = (s2.get("hash") != b.get("hash"))
        changed = dhash or (dmean > 0.05) or (dhist > 50) or (dn > 50)
        results[name] = {"dmean": round(dmean, 3), "dhist": dhist, "dn": dn,
                         "dhash": dhash, "changed": changed}
        mark = "生效" if changed else "无变化"
        print(f"       {name:14s} {s2['n']:7d} {dmean:14.3f} {dhist:10d}  {mark}")

    # 截图对比
    js("window.__set('happy', 1.0)")
    wait(800)
    snap = js("window.__snap()", 10000)
    if snap and str(snap).startswith("data:image"):
        out = HERE / "expr_happy.png"
        out.write_bytes(base64.b64decode(str(snap).split(",", 1)[1]))
        print(f"\n[test] happy 表情截图 -> {out.name} ({out.stat().st_size:,} B)")
    js("window.__clear()")
    wait(600)
    snap = js("window.__snap()", 10000)
    if snap and str(snap).startswith("data:image"):
        out = HERE / "expr_neutral.png"
        out.write_bytes(base64.b64decode(str(snap).split(",", 1)[1]))
        print(f"[test] 无表情截图 -> {out.name} ({out.stat().st_size:,} B)")

    # 汇总
    ok = [k for k, v in results.items() if v["changed"]]
    print(f"\n{'='*70}")
    print(f"结果: {len(ok)}/{len(results)} 个表情确认生效")
    if len(ok) < len(results):
        print("未生效:", [k for k in results if k not in ok])
    print("=" * 70)
    return 0 if len(ok) >= max(1, len(results) * 0.7) else 1


if __name__ == "__main__":
    sys.exit(main())
