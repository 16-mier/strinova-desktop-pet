"""分析 VRM 脸部材质的 UV 范围 —— 判断是否为「表情图集 + UV 偏移」机制。

卡拉彼丘模型通常把多种表情排在一张贴图上，靠 UV 偏移切换。
若脸部材质 UV 只占贴图一小块（如 v∈[0,0.25]），即为图集。

用法：python vrm_uv.py <file.vrm> [材质名关键字...]
"""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

COMP = {5120: ("b", 1), 5121: ("B", 1), 5122: ("h", 2), 5123: ("H", 2),
        5125: ("I", 4), 5126: ("f", 4)}
NCOMP = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def read_glb(path: Path):
    with open(path, "rb") as f:
        assert f.read(4) == b"glTF"
        struct.unpack("<II", f.read(8))
        clen, ctype = struct.unpack("<II", f.read(8))
        g = json.loads(f.read(clen).decode("utf-8"))
        blen, btype = struct.unpack("<II", f.read(8))
        bin_data = f.read(blen)
    return g, bin_data


def read_accessor(g, bin_data, idx):
    acc = g["accessors"][idx]
    n = acc["count"]
    nc = NCOMP[acc["type"]]
    fmt, sz = COMP[acc["componentType"]]
    bv = g["bufferViews"][acc["bufferView"]]
    base = bv.get("byteOffset", 0) + acc.get("byteOffset", 0)
    stride = bv.get("byteStride") or (nc * sz)
    out = []
    for i in range(n):
        off = base + i * stride
        vals = struct.unpack_from("<" + fmt * nc, bin_data, off)
        out.append(vals if nc > 1 else vals[0])
    return out


def main() -> int:
    path = Path(sys.argv[1])
    keys = sys.argv[2:] or ["颜", "目", "白目", "目光", "face", "Face", "eye"]

    g, bin_data = read_glb(path)
    mats = g.get("materials", [])
    meshes = g.get("meshes", [])

    print(f"===== {path.name} 脸部材质 UV 分析 =====")

    for mi, m in enumerate(mats):
        name = m.get("name") or f"mat{mi}"
        if not any(k in name for k in keys):
            continue
        pbr = m.get("pbrMetallicRoughness") or {}
        base = pbr.get("baseColorTexture") or m.get("emissiveTexture")
        if not base:
            print(f"\n[{mi}] {name!r}: 无 baseColorTexture 也无 emissiveTexture")
            continue
        tti = base.get("index")
        tex = g["textures"][tti]
        src = tex.get("source")
        img_name = g["images"][src].get("name") if src is not None else "?"

        # 找用这个材质的 primitive
        uv_ranges = []
        for mesh in meshes:
            for p in mesh.get("primitives", []):
                if p.get("material") != mi:
                    continue
                uv_idx = (p.get("attributes") or {}).get("TEXCOORD_0")
                if uv_idx is None:
                    continue
                uvs = read_accessor(g, bin_data, uv_idx)
                us = [u for u, v in uvs]
                vs = [v for u, v in uvs]
                uv_ranges.append((min(us), max(us), min(vs), max(vs), len(uvs)))

        print(f"\n[{mi}] {name!r} -> {img_name}")
        print(f"      KHR_texture_transform: {base.get('extensions')}")
        for (u0, u1, v0, v1, n) in uv_ranges:
            print(f"      UV: u[{u0:.4f}..{u1:.4f}] span={u1-u0:.4f}   "
                  f"v[{v0:.4f}..{v1:.4f}] span={v1-v0:.4f}   verts={n}")
            # 判断是否为图集
            if (u1 - u0) < 0.9 or (v1 - v0) < 0.9:
                print(f"      >>> 只用了贴图部分区域 -> 疑似表情图集")
                # 推测网格
                for gs in (2, 3, 4):
                    if (u1 - u0) <= 1.0 / gs + 0.02 and (v1 - v0) <= 1.0 / gs + 0.02:
                        print(f"      >>> 可能 {gs}x{gs} 网格图集 -> 最多 {gs*gs} 种表情")
                        break
    return 0


if __name__ == "__main__":
    sys.exit(main())
