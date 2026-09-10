"""列出 VRM 全部面部/日文节点与父子关系，找可动骨骼。

用法：python vrm_face_bones.py <file.vrm>
"""
from __future__ import annotations

import io
import json
import re
import struct
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


def main() -> int:
    path = Path(sys.argv[1])
    with open(path, "rb") as f:
        assert f.read(4) == b"glTF"
        struct.unpack("<II", f.read(8))
        clen, ctype = struct.unpack("<II", f.read(8))
        g = json.loads(f.read(clen).decode("utf-8"))

    nodes = g["nodes"]
    # 父子表
    parent = {}
    for i, n in enumerate(nodes):
        for c in n.get("children", []) or []:
            parent[c] = i

    def path_of(i):
        parts = []
        seen = set()
        while i is not None and i not in seen:
            seen.add(i)
            parts.append(nodes[i].get("name") or f"<{i}>")
            i = parent.get(i)
        return " / ".join(reversed(parts))

    print(f"===== {path.name} 非 ASCII 节点（面部/日系骨骼） =====")
    for i, n in enumerate(nodes):
        nm = n.get("name") or ""
        if re.search(r"[^\x00-\x7f]", nm):
            kids = n.get("children") or []
            print(f"  [{i:3d}] {nm:20s} 子={[nodes[c].get('name') for c in kids]}")

    # 头部子树
    ext = g.get("extensions", {}) or {}
    hb = ((ext.get("VRMC_vrm") or {}).get("humanoid") or {}).get("humanBones") or {}
    head_i = (hb.get("head") or {}).get("node")
    if head_i is not None:
        print(f"\n===== head 子树 (node {head_i} = {nodes[head_i].get('name')}) =====")
        stack = [(head_i, 0)]
        while stack:
            i, d = stack.pop(0)
            if d > 4:
                continue
            n = nodes[i]
            extra = ""
            if "mesh" in n:
                extra += f" mesh={n['mesh']}"
            if "skin" in n:
                extra += f" skin={n['skin']}"
            print(f"  {'  '*d}[{i:3d}] {n.get('name') or '<anon>':22s}{extra}")
            for c in n.get("children", []) or []:
                stack.append((c, d + 1))

    # 眼睛骨骼详情
    print(f"\n===== 眼球骨骼 =====")
    for side in ("leftEye", "rightEye"):
        ni = (hb.get(side) or {}).get("node")
        if ni is None:
            print(f"  {side}: 无")
            continue
        n = nodes[ni]
        print(f"  {side}: node {ni} '{n.get('name')}' "
              f"children={[nodes[c].get('name') for c in n.get('children') or []]}")
        if "mesh" in n:
            m = g["meshes"][n["mesh"]]
            print(f"      mesh[{n['mesh']}] name={m.get('name')} prims={len(m.get('primitives', []))}")

    # 找出所有「有 mesh 且被 skin 引用」的节点的材质
    print(f"\n===== 面部网格归属 =====")
    for i, n in enumerate(nodes):
        if "mesh" not in n:
            continue
        m = g["meshes"][n["mesh"]]
        mats = {p.get("material") for p in m.get("primitives", [])}
        names = [g["materials"][x].get("name") for x in mats if x is not None]
        if any(k in (x or "") for x in names for k in ("颜", "目")):
            print(f"  node[{i}] '{n.get('name')}' mesh={n['mesh']} 材质={names}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
