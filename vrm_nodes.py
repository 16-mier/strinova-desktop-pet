"""列出 VRM 的全部节点名 / 材质名（UTF-8 写入文件，避免控制台编码问题）。

用法：python vrm_nodes.py <file.vrm> [outfile.txt]
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


FACE_KEYS = ("eye", "eyes", "eyelid", "brow", "mouth", "lip", "teeth", "tongue",
             "face", "head", "jaw", "cheek", "nose", "hair", "skirt", "breast",
             "eye", "hitomi", "mayu", "kuchi", "kao", "mabuta", "shita", "kami",
             "眼", "眉", "口", "唇", "齿", "舌", "脸", "头", "发", "裙", "胸", "尾")


def main() -> int:
    path = Path(sys.argv[1])
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("vrm_nodes_dump.txt")
    g = read_glb_json(path)

    lines: list[str] = []
    lines.append(f"===== {path.name} =====")

    nodes = g.get("nodes", [])
    lines.append(f"\n--- 全部 {len(nodes)} 个节点 ---")
    for i, n in enumerate(nodes):
        nm = n.get("name", "")
        if not nm:
            if "mesh" in n:
                nm = f"<mesh{n['mesh']}>"
            elif "camera" in n:
                nm = "<camera>"
            elif n.get("children"):
                nm = "<group>"
            else:
                nm = "<empty>"
        tags = []
        if "skin" in n:
            tags.append(f"skin={n['skin']}")
        if "mesh" in n:
            tags.append(f"mesh={n['mesh']}")
        lines.append(f"  [{i:3d}] {nm}  {' '.join(tags)}")

    # 面部相关节点
    lines.append(f"\n--- 疑似面部/物理相关节点 ---")
    for i, n in enumerate(nodes):
        nm = (n.get("name") or "").lower()
        if any(k in nm for k in FACE_KEYS):
            lines.append(f"  [{i:3d}] {n.get('name')}")

    # humanoid 骨骼映射
    ext = g.get("extensions", {}) or {}
    info = ext.get("VRMC_vrm") or ext.get("VRM") or {}
    hb = (info.get("humanoid") or {}).get("humanBones")
    lines.append(f"\n--- humanoid 骨骼 ---")
    if isinstance(hb, list):  # VRM 0.x
        for b in hb:
            lines.append(f"  {b.get('bone'):24s} -> node {b.get('node')} "
                         f"({nodes[b['node']].get('name') if b.get('node') is not None and b['node'] < len(nodes) else '?'})")
    elif isinstance(hb, dict):  # VRM 1.0
        for name, d in hb.items():
            ni = d.get("node")
            nm = nodes[ni].get("name") if isinstance(ni, int) and ni < len(nodes) else "?"
            lines.append(f"  {name:24s} -> node {ni} ({nm})")

    # 材质
    lines.append(f"\n--- 全部 {len(g.get('materials', []))} 个材质 ---")
    for i, m in enumerate(g.get("materials", [])):
        lines.append(f"  [{i:2d}] {m.get('name')!r}  alpha={m.get('alphaMode', 'OPAQUE')}  "
                     f"doubleSided={m.get('doubleSided')}  ext={list((m.get('extensions') or {}).keys())}")

    # 图片
    lines.append(f"\n--- 贴图 ---")
    for i, im in enumerate(g.get("images", [])):
        lines.append(f"  [{i}] {im.get('name')}  {im.get('mimeType')}")

    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"written {out} ({len(lines)} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
