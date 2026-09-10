"""逐步定位崩溃点：import pet → QApplication → PetWindow → Web3DPetWindow

用法：python diag_crash_steps.py <step>
  step: 1=import pet
        2=+QApplication
        3=+PetWindow().show()
        4=+Web3DPetWindow()
        5=+switch_face()
"""
from __future__ import annotations

import faulthandler
import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
faulthandler.enable()

os.environ.setdefault(
    "QTWEBENGINE_CHROMIUM_FLAGS",
    "--ignore-gpu-blocklist --enable-unsafe-swiftshader",
)

STEP = int(sys.argv[1]) if len(sys.argv) > 1 else 4
print(f"[crash] step={STEP}", flush=True)

print("[crash] 1) import pet …", flush=True)
import pet as pet_mod
print(f"[crash]    pet OK  _WEB3D_OK={pet_mod._WEB3D_OK}  backend={pet_mod._3D_BACKEND_DEFAULT}", flush=True)

if STEP < 2:
    sys.exit(0)

print("[crash] 2) QApplication …", flush=True)
from PyQt6.QtCore import QTimer, QEventLoop
from PyQt6.QtWidgets import QApplication
app = QApplication(sys.argv)
print("[crash]    QApplication OK", flush=True)

if STEP < 3:
    sys.exit(0)


def wait(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


print("[crash] 3) PetWindow …", flush=True)
win = pet_mod.PetWindow()
win.show()
wait(1000)
print(f"[crash]    PetWindow OK  visible={win.isVisible()} backend={win._3d_backend}", flush=True)

if STEP < 4:
    sys.exit(0)

print("[crash] 4) Web3DPetWindow 直接创建 …", flush=True)
w3 = pet_mod._web3d.Web3DPetWindow(model='michelle', size=(300, 400))
print("[crash]    Web3DPetWindow 构造 OK", flush=True)
w3.show()
print("[crash]    show() OK", flush=True)
wait(6000)
print("[crash]    等待 6s 完成", flush=True)
r = {"v": None, "done": False}
w3.page.runJavaScript("window.getModel()", lambda v: r.update(v=v, done=True))
for _ in range(40):
    wait(200)
    if r["done"]:
        break
print(f"[crash]    getModel -> {r['v']}", flush=True)

if STEP < 5:
    print("[crash] ALL OK (step 4)", flush=True)
    sys.exit(0)

print("[crash] 5) switch_face() …", flush=True)
win.switch_face()
for i in range(60):
    wait(500)
    if getattr(win, '_web3d_ready', False):
        print(f"[crash]    ready after {(i+1)*0.5:.1f}s", flush=True)
        break
print(f"[crash]    _in3d={win._in3d} win3={win._web3d_win is not None}", flush=True)
wait(2000)
print("[crash] ALL OK (step 5)", flush=True)
