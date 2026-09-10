"""提取 Qt 内置的 qwebchannel.js 到 web3d 目录（供本地 HTTP 服务使用）。

用法：python extract_qwebchannel.py
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "web3d" / "qwebchannel.js"

# QWebChannel 必须在 QApplication 之后才可访问 Qt 资源
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QFile, QIODevice

app = QApplication(sys.argv)

CANDIDATES = [
    ":/qtwebchannel/qwebchannel.js",
    ":/qwebchannel/qwebchannel.js",
    "qrc:///qtwebchannel/qwebchannel.js",
]

for path in CANDIDATES:
    f = QFile(path)
    if f.open(QIODevice.OpenModeFlag.ReadOnly):
        data = bytes(f.readAll())
        OUT.write_bytes(data)
        print(f"OK {path} -> {OUT} ({len(data):,} bytes)")
        break
    else:
        print(f"miss {path}")
else:
    # 兜底：从 QWebEngineScript 的 world 拿不到，尝试 Qt 安装目录搜
    import subprocess
    print("尝试在 Qt 安装目录搜索…")
    for base in (Path(sys.prefix), Path(r"C:\Users\mier\AppData\Roaming\Python\Python314\site-packages")):
        for p in base.rglob("qwebchannel.js"):
            print(f"  found {p}")
            OUT.write_bytes(p.read_bytes())
            print(f"  -> {OUT}")
            sys.exit(0)
    print("FAILED: 未找到 qwebchannel.js")
    sys.exit(1)
