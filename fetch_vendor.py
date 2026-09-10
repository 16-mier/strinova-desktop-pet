"""下载 three.js + three-vrm 到本地 vendor 目录（离线可用，绕过 CORS）。

用法：python fetch_vendor.py [--force]
"""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

VENDOR = Path(__file__).resolve().parent / "webgpu_probe" / "vendor"
THREE_VER = "0.170.0"
VRM_VER = "3.5.5"

# (url, 目标相对路径)
FILES = [
    (f"https://unpkg.com/three@{THREE_VER}/build/three.module.js", "three.module.js"),
    (f"https://unpkg.com/three@{THREE_VER}/examples/jsm/loaders/GLTFLoader.js", "addons/loaders/GLTFLoader.js"),
    (f"https://unpkg.com/three@{THREE_VER}/examples/jsm/utils/BufferGeometryUtils.js", "addons/utils/BufferGeometryUtils.js"),
    (f"https://unpkg.com/three@{THREE_VER}/examples/jsm/libs/meshopt_decoder.module.js", "addons/libs/meshopt_decoder.module.js"),
    (f"https://unpkg.com/@pixiv/three-vrm@{VRM_VER}/lib/three-vrm.module.js", "three-vrm.module.js"),
    (f"https://unpkg.com/@pixiv/three-vrm-animation@{VRM_VER}/lib/three-vrm-animation.module.js", "three-vrm-animation.module.js"),
]


def fetch(url: str, dest: Path, force: bool) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and not force and dest.stat().st_size > 1000:
        print(f"  SKIP {dest.name} (exists, {dest.stat().st_size:,} B)")
        return True
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=90) as r:
            data = r.read()
        dest.write_bytes(data)
        print(f"  OK   {dest.name}  ({len(data):,} B)")
        return True
    except Exception as e:
        print(f"  ERR  {dest.name}: {e}")
        return False


def main() -> int:
    force = "--force" in sys.argv
    print(f"[vendor] three@{THREE_VER} + three-vrm@{VRM_VER} -> {VENDOR}")
    ok = 0
    for url, rel in FILES:
        if fetch(url, VENDOR / rel, force):
            ok += 1
    print(f"[vendor] {ok}/{len(FILES)} ok")
    return 0 if ok == len(FILES) else 1


if __name__ == "__main__":
    sys.exit(main())
