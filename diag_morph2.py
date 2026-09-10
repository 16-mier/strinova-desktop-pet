"""diag_morph2.py —— 用 PNG 快照哈希测表情（绕开 readPixels 陈旧缓冲问题）

思路：
  readPixels 在 QtWebEngine + 软件渲染下可能读到旧缓冲（实测连"直接改顶点"
  都读不出变化，明显是缓冲问题）。改用 renderer.domElement.toDataURL() 取
  完整 PNG，在 Python 侧算哈希 + 逐像素差分 —— 这个路径经过编码，可靠。

用法：python diag_morph2.py
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
        if level.name.startswith("Error") or "DIAG" in message:
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
const loader=new GLTFLoader();
loader.register(p=>new VRMLoaderPlugin(p));
loader.load('./models/michelle_expr.vrm',(g)=>{
  vrm=g.userData.vrm;
  try{ VRMUtils.combineMorphs(vrm); console.log('DIAG combineMorphs OK'); }catch(e){ console.log('DIAG cm ERR '+e.message); }
  scene.add(vrm.scene); vrm.scene.rotation.y=Math.PI;
  vrm.scene.traverse(o=>{ if(o.isMesh) o.frustumCulled=false; });
  const box=new THREE.Box3().setFromObject(vrm.scene);
  const head=vrm.humanoid?.getNormalizedBoneNode('head');
  const hp=head?head.getWorldPosition(new THREE.Vector3()):new THREE.Vector3(0,1.4,0);
  camera.position.set(0,hp.y+0.02,0.34); camera.lookAt(0,hp.y-0.02,0);
  console.log('DIAG ready head='+hp.y.toFixed(3));
  window.__ready=true;
  (function loop(){ requestAnimationFrame(loop); renderer.render(scene,camera); })();
});

// 全清
window.__clear=()=>{
  vrm?.scene.traverse(o=>{
    if(o.isMesh&&o.morphTargetInfluences) for(let i=0;i<o.morphTargetInfluences.length;i++) o.morphTargetInfluences[i]=0;
  });
  vrm?.expressionManager && Object.keys(vrm.expressionManager.expressionMap||{}).forEach(k=>vrm.expressionManager.setValue(k,0));
  vrm?.expressionManager?.update();
  return 'ok';
};
// 用 expressionManager 设表情
window.__setExpr=(n,w)=>{
  if(!vrm?.expressionManager) return 'no mgr';
  Object.keys(vrm.expressionManager.expressionMap||{}).forEach(k=>vrm.expressionManager.setValue(k,0));
  vrm.expressionManager.setValue(n,w); vrm.expressionManager.update();
  return 'ok';
};
// 直接设某个 target 的 influence（所有 mesh）
window.__setTarget=(idx,w)=>{
  let n=0;
  vrm?.scene.traverse(o=>{
    if(o.isMesh&&o.morphTargetInfluences&&idx<o.morphTargetInfluences.length){ o.morphTargetInfluences[idx]=w; n++; }
  });
  return 'touched '+n;
};
// 暴力几何修改（验证管线）
window.__bump=(delta)=>{
  let n=0;
  vrm?.scene.traverse(o=>{
    if(!o.isMesh) return;
    const a=o.geometry.attributes.position.array;
    for(let k=1;k<a.length;k+=3) a[k]+=delta;
    o.geometry.attributes.position.needsUpdate=true; n++;
  });
  return 'bumped '+n;
};
window.__rotate=(a)=>{ if(vrm) vrm.scene.rotation.y=Math.PI+a; return 'ok'; };
// 完整 PNG
window.__png=()=>{
  renderer.render(scene,camera);
  return renderer.domElement.toDataURL('image/png');
};
window.__names=()=>JSON.stringify(Object.keys(vrm?.expressionManager?.expressionMap||{}));
</script></body></html>"""


def png_stats(data_url: str):
    """把 dataURL 解成 PNG bytes，返回 (md5, 平均像素, 非透明像素数)"""
    if not data_url or not str(data_url).startswith("data:image"):
        return None
    raw = base64.b64decode(str(data_url).split(",", 1)[1])
    md5 = hashlib.md5(raw).hexdigest()[:12]
    if not HAS_PIL:
        return {"md5": md5, "len": len(raw), "mean": None, "n": None}
    im = Image.open(io.BytesIO(raw)).convert("RGBA")
    # 缩成小图算均值（快）
    small = im.resize((32, 42))
    px = list(small.getdata())
    op = [p for p in px if p[3] > 32]
    mean = (sum(p[0] for p in op) / len(op),
            sum(p[1] for p in op) / len(op),
            sum(p[2] for p in op) / len(op)) if op else (0, 0, 0)
    return {"md5": md5, "len": len(raw),
            "mean": tuple(round(v, 2) for v in mean), "n": len(op)}


def main() -> int:
    (SRV_DIR / "_morph_diag2.html").write_text(HTML, encoding="utf-8")
    app = QApplication(sys.argv)
    port = serve(SRV_DIR)

    w = QWidget()
    w.resize(320, 420)
    view = QWebEngineView(w)
    page = Page(view)
    view.setPage(page)
    view.setGeometry(0, 0, 320, 420)
    page.setBackgroundColor(QColor(0, 0, 0, 0))
    view.settings().setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, True)
    page.load(QUrl(f"http://127.0.0.1:{port}/_morph_diag2.html"))
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
    print(f"[diag] 加载完成 (PIL={'有' if HAS_PIL else '无'})")
    wait(1500)

    # ---------- A. 工具验证 ----------
    print("\n" + "=" * 60)
    print("A. 工具验证（改画面 → PNG 哈希应变化）")
    print("=" * 60)
    js("window.__clear()")
    wait(700)
    a0 = png_stats(js("window.__png()"))
    print(f"  基准       : md5={a0['md5']}  mean={a0['mean']}  n={a0['n']}")
    js("window.__rotate(0.4)")
    wait(900)
    a1 = png_stats(js("window.__png()"))
    print(f"  旋转后     : md5={a1['md5']}  mean={a1['mean']}  n={a1['n']}")
    tool_ok = a0["md5"] != a1["md5"]
    print(f"  => {'工具正常 ✅' if tool_ok else '工具仍失效 ❌'}")
    js("window.__rotate(0)")
    wait(700)

    # ---------- B. 暴力几何修改 ----------
    print("\n" + "=" * 60)
    print("B. 暴力改顶点位置（验证渲染管线是否响应几何）")
    print("=" * 60)
    b0 = png_stats(js("window.__png()"))
    js("window.__bump(0.08)")
    wait(900)
    b1 = png_stats(js("window.__png()"))
    print(f"  基准     : md5={b0['md5']}  n={b0['n']}")
    print(f"  顶点上移 : md5={b1['md5']}  n={b1['n']}")
    pipe_ok = b0["md5"] != b1["md5"]
    print(f"  => 渲染管线{'正常 ✅' if pipe_ok else '不响应几何 ❌'}")
    # 复位
    js("window.__bump(-0.08)")
    wait(700)

    # ---------- C. 表情测试 ----------
    print("\n" + "=" * 60)
    print("C. 表情生效测试（PNG 哈希 + 逐像素差分）")
    print("=" * 60)
    names = js("window.__names()")
    try:
        names = json.loads(names)
    except Exception:
        names = []
    print(f"  可用表情 {len(names)} 个")

    js("window.__clear()")
    wait(800)
    base_url = js("window.__png()")
    base = png_stats(base_url)
    base_raw = base64.b64decode(str(base_url).split(",", 1)[1]) if base_url else b""
    print(f"  基准: md5={base['md5']} mean={base['mean']}")

    results = {}
    for name in names:
        js(f"window.__setExpr({json.dumps(name)}, 1.0)")
        wait(750)
        u = js("window.__png()")
        st = png_stats(u)
        if st is None:
            continue
        # 逐像素差分（用 PIL 精确算）
        diff_px = None
        if HAS_PIL and u:
            try:
                im = Image.open(io.BytesIO(base64.b64decode(str(u).split(",", 1)[1]))).convert("RGBA")
                im0 = Image.open(io.BytesIO(base_raw)).convert("RGBA")
                if im.size == im0.size:
                    d = 0
                    for p, q in zip(im.getdata(), im0.getdata()):
                        if abs(p[0] - q[0]) + abs(p[1] - q[1]) + abs(p[2] - q[2]) > 12:
                            d += 1
                    diff_px = d
            except Exception:
                pass
        changed = (st["md5"] != base["md5"])
        results[name] = {"md5": st["md5"], "diff": diff_px, "changed": changed}
        mark = "★ 生效" if changed else "无变化"
        dstr = f"{diff_px:6d}px" if diff_px is not None else "     -"
        print(f"    {name:14s} md5={st['md5']}  差异={dstr}  {mark}")

    ok = [k for k, v in results.items() if v["changed"]]
    print(f"\n  结果: {len(ok)}/{len(results)} 个表情改变了画面")
    if ok:
        print(f"  生效的: {ok}")

    print("\n" + "=" * 60)
    print(f"工具: {'正常' if tool_ok else '失效'} | "
          f"管线: {'正常' if pipe_ok else '不响应'} | "
          f"表情: {len(ok)}/{len(results)}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
