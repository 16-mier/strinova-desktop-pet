"""检查 VRM/GLB 文件结构，判断 three-vrm 能否解析。

用法：python vrm_info.py <file.vrm> [...]
"""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path


def read_glb_json(path: Path) -> dict:
    with open(path, "rb") as f:
        magic = f.read(4)
        if magic != b"glTF":
            raise ValueError(f"不是 GLB 文件 (magic={magic!r})")
        version, total = struct.unpack("<II", f.read(8))
        # chunk 0
        clen, ctype = struct.unpack("<II", f.read(8))
        if ctype != 0x4E4F534A:  # 'JSON'
            raise ValueError(f"第一个 chunk 不是 JSON: {ctype:#x}")
        raw = f.read(clen)
    return json.loads(raw.decode("utf-8"))


def summarize(path: Path) -> None:
    print(f"\n===== {path.name}  ({path.stat().st_size / 1024 / 1024:.1f} MB) =====")
    g = read_glb_json(path)

    asset = g.get("asset", {})
    print(f"  generator : {asset.get('generator')}")
    print(f"  glTF ver  : {asset.get('version')}")

    used = g.get("extensionsUsed", []) or []
    req = g.get("extensionsRequired", []) or []
    print(f"  extUsed   : {used}")
    print(f"  extReq    : {req}")

    vrm_ext = [e for e in used if e.startswith("VRM") or e.startswith("KHR_vrm")]
    print(f"  >>> VRM ext: {vrm_ext if vrm_ext else 'NONE  <-- three-vrm 不会识别!'}")

    print(f"  scenes={len(g.get('scenes', []))} nodes={len(g.get('nodes', []))} "
          f"meshes={len(g.get('meshes', []))} mats={len(g.get('materials', []))} "
          f"skins={len(g.get('skins', []))} anims={len(g.get('animations', []))} "
          f"imgs={len(g.get('images', []))}")

    # 表情 / blendshape 数量
    total_bs = 0
    for m in g.get("meshes", []):
        for p in m.get("primitives", []):
            tg = p.get("targets") or []
            total_bs += len(tg)
    print(f"  blendshape targets: {total_bs}")

    # VRM0 humanoid bones
    ext = g.get("extensions", {}) or {}
    for key in ("VRM", "VRMC_vrm"):
        if key in ext:
            info = ext[key]
            if key == "VRM":
                hb = (info.get("humanoid") or {}).get("humanBones") or []
                print(f"  [{key}] humanBones={len(hb)} version={info.get('exporterVersion')}")
                bg = (info.get("blendShapeMaster") or {}).get("blendShapeGroups") or []
                print(f"  [{key}] blendShapeGroups={len(bg)}: "
                      f"{[x.get('name') for x in bg[:12]]}")
                sg = info.get("secondaryAnimation") or {}
                print(f"  [{key}] springBone groups={len(sg.get('boneGroups') or [])}")
                if info.get("meta"):
                    print(f"  [{key}] meta.name={info['meta'].get('title') or info['meta'].get('name')}")
            else:
                hb = (info.get("humanoid") or {}).get("humanBones") or {}
                print(f"  [{key}] humanBones={len(hb)}")
                ex = (info.get("expressions") or {})
                print(f"  [{key}] expression keys={list(ex.keys())}")
                print(f"  [{key}] meta.name={(info.get('meta') or {}).get('name')}")


def main() -> int:
    args = sys.argv[1:]
    if not args:
        root = Path(r"C:\Users\mier\Desktop\deepseek work")
        args = [str(p) for p in root.rglob("*.vrm")]
    for a in args:
        try:
            summarize(Path(a))
        except Exception as e:
            print(f"\n===== {a} =====\n  ERROR: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
