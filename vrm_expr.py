"""详细检查 VRM 的 expression / blendshape / springbone 定义。

用法：python vrm_expr.py <file.vrm>
"""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path


def read_glb_json(path: Path) -> dict:
    with open(path, "rb") as f:
        assert f.read(4) == b"glTF"
        struct.unpack("<II", f.read(8))
        clen, ctype = struct.unpack("<II", f.read(8))
        assert ctype == 0x4E4F534A
        raw = f.read(clen)
    return json.loads(raw.decode("utf-8"))


def main() -> int:
    path = Path(sys.argv[1])
    g = read_glb_json(path)
    ext = g.get("extensions", {}) or {}

    print(f"===== {path.name} =====")

    # ---- VRM 1.0 ----
    if "VRMC_vrm" in ext:
        info = ext["VRMC_vrm"]
        ex = info.get("expressions") or {}
        preset = ex.get("preset") or {}
        custom = ex.get("custom") or {}
        print(f"\n[VRM 1.0] preset expressions ({len(preset)}):")
        for name, d in preset.items():
            binds = d.get("morphTargetBinds") or []
            matbinds = d.get("materialColorBinds") or []
            texbinds = d.get("textureTransformBinds") or []
            print(f"   {name:14s} morph={len(binds):3d} matColor={len(matbinds):2d} texXform={len(texbinds):2d} "
                  f"isBinary={d.get('isBinary')} override={d.get('overrideBlink')}/{d.get('overrideLookAt')}")
            for b in binds[:4]:
                print(f"        -> node={b.get('node')} idx={b.get('index')} w={b.get('weight')}")
        print(f"\n[VRM 1.0] custom expressions ({len(custom)}): {list(custom.keys())}")

        lookat = info.get("lookAt") or {}
        print(f"\n[VRM 1.0] lookAt: type={lookat.get('type')} offsetFromHead={lookat.get('offsetFromHeadBone')}")

        sp = ext.get("VRMC_springBone") or {}
        print(f"[VRM 1.0] springBone: colliders={len(sp.get('colliders') or [])} "
              f"groups={len(sp.get('springBoneGroups') or sp.get('colliderGroups') or [])} "
              f"springs={len(sp.get('springs') or [])}")

    # ---- VRM 0.x ----
    if "VRM" in ext:
        info = ext["VRM"]
        bg = (info.get("blendShapeMaster") or {}).get("blendShapeGroups") or []
        print(f"\n[VRM 0.x] blendShapeGroups ({len(bg)}):")
        for x in bg:
            binds = x.get("binds") or []
            print(f"   {x.get('name'):14s} preset={x.get('presetName'):10s} binds={len(binds):3d}")
        sg = info.get("secondaryAnimation") or {}
        print(f"[VRM 0.x] springBone groups={len(sg.get('boneGroups') or [])} "
              f"colliders={len(sg.get('colliderGroups') or [])}")
        # humanoid bone names
        hb = (info.get("humanoid") or {}).get("humanBones") or []
        print(f"[VRM 0.x] humanBones: {[b.get('bone') for b in hb][:20]} ...")

    # ---- 材质 ----
    print(f"\n材料 ({len(g.get('materials', []))}):")
    for i, m in enumerate(g.get("materials", [])[:30]):
        nm = m.get("name")
        alpha = m.get("alphaMode", "OPAQUE")
        mext = list((m.get("extensions") or {}).keys())
        print(f"   [{i:2d}] {nm!r:40s} alpha={alpha:8s} ext={mext}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
