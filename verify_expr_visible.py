# -*- coding: utf-8 -*-
"""verify_expr_visible.py —— 在【真实 pet_viewer.html】上确认哪些表情肉眼可见

之前的验证都跑在自制测试页（相机怼脸特写）。本脚本跑真实页面
（真实相机距离/光照/MorphDriver），所以结论直接对应桌面上的观感。

关键方法（前面踩过的坑）：
  · 先关自动眨眼，否则基线不是 0，判定全乱
  · __snapshot 内部连画两帧，否则 toDataURL 可能拿到未上传属性的旧帧
  · 渲染是确定性的（6 帧 md5 全同），所以可以放心用像素差分

用法：python verify_expr_visible.py
"""
from __future__ import annotations

import base64
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
from PIL import Image

W, H = 420, 560


class Page(QWebEnginePage):
    def javaScriptConsoleMessage(self, level, message, line, source):
        if level.name.startswith("Error"):
            print(f"  [js] {message[:200]}")


def png_bytes(u):
    if not u or not str(u).startswith("data:image"):
        return None
    return base64.b64decode(str(u).split(",", 1)[1])


def diff(a, b, thr=10):
    pa = list(a.get_flattened_data()) if hasattr(a, "get_flattened_data") else list(a.getdata())
    pb = list(b.get_flattened_data()) if hasattr(b, "get_flattened_data") else list(b.getdata())
    n = 0
    for p, q in zip(pa, pb):
        if abs(p[0]-q[0]) + abs(p[1]-q[1]) + abs(p[2]-q[2]) + abs(p[3]-q[3]) > thr:
            n += 1
    return n, n / max(1, len(pa)) * 100


def main() -> int:
    app = QApplication(sys.argv)
    port = serve(SRV_DIR)

    w = QWidget()
    w.resize(W, H)
    view = QWebEngineView(w)
    pg = Page(view)
    view.setPage(pg)
    view.setGeometry(0, 0, W, H)
    pg.setBackgroundColor(QColor(0, 0, 0, 0))
    view.settings().setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, True)
    pg.load(QUrl(f"http://127.0.0.1:{port}/pet_viewer.html"))
    w.show()

    def wait(ms):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def js(code, timeout=20000):
        box = {"v": None, "done": False}
        pg.runJavaScript(code, lambda v: box.update(v=v, done=True))
        t = 0
        while not box["done"] and t < timeout:
            wait(100)
            t += 100
        return box["v"]

    for _ in range(80):
        wait(400)
        if js("window.getModel && window.getModel()"):
            break
    print(f"[v] 模型: {js('window.getModel()')}")
    print(f"[v] 驱动: {js('JSON.stringify(window.morphInfo())')}")
    wait(1500)

    # 关自动眨眼，保证基线干净
    js("window.setBlinkEnabled(false)")
    js("window.setExpression('neutral', 0)")
    wait(1500)

    def shot():
        raw = png_bytes(js("window.__snapshot()", 25000))
        return Image.open(io.BytesIO(raw)).convert("RGBA") if raw else None

    base = shot()
    if base is None:
        print("!! 基准帧抓取失败")
        return 1
    # 复测基准稳定性
    b2 = shot()
    n0, _ = diff(base, b2)
    print(f"[v] 基准稳定性: {n0} px 差异（应为 0）\n")

    names = json.loads(js("JSON.stringify(window.listExpressions())") or "[]")
    print(f"{'表情':<14s}{'顶点变动':>9s}{'像素差异':>10s}{'占比':>8s}  判定")
    print("-" * 60)
    good, weak, dead = [], [], []
    for nm in names:
        js(f"window.setExpression({json.dumps(nm)}, 1.0)")
        wait(1100)
        vd = js("window.__vertexDelta()")
        nz = 0
        try:
            nz = json.loads(vd).get("nz", 0)
        except Exception:
            pass
        im = shot()
        if im is None:
            continue
        d, p = diff(base, im)
        if d > 400:
            good.append(nm); tag = "★ 明显"
        elif d > 60:
            weak.append(nm); tag = "○ 轻微"
        else:
            dead.append(nm); tag = "✗ 看不出"
        print(f"{nm:<14s}{nz:9d}{d:10d}{p:7.2f}%  {tag}")

    print("-" * 60)
    print(f"明显可见 {len(good):2d}: {good}")
    print(f"轻微     {len(weak):2d}: {weak}")
    print(f"看不出   {len(dead):2d}: {dead}")

    (HERE / "expr_visible.json").write_text(json.dumps(
        {"good": good, "weak": weak, "dead": dead}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    print("\n[v] 结果已存 expr_visible.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
