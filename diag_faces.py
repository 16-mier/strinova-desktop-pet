"""diag_faces.py —— 查看脸部/眼睛 mesh 的坐标范围，确认真实可见性

用法：python diag_faces.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from verify_expr_vrm import read_glb, read_acc

VRM = HERE / "web3d" / "models" / "michelle_expr.vrm"

# 名字映射（材质名在 VRM 里是 UTF-16，读出来是 '颜' 等）
FACE_MATS = ("颜", "白目", "目", "目光")


def main() -> int:
    g, b = read_glb(VRM)
    prims = g["meshes"][0]["primitives"]
    nodes = g["nodes"]
    print("=" * 70)
    print(f"检查脸部网格的坐标范围（判断相机视角是否看到脸）")
    print("=" * 70)
    for i, p in enumerate(prims):
        mat_name = g["materials"][p["material"]]["name"] if "material" in p else "?"
        v = read_acc(g, b, p["attributes"]["POSITION"])
        if not v:
            continue
        xs = [x[0] for x in v]; ys = [x[1] for x in v]; zs = [x[2] for x in v]
        if mat_name in FACE_MATS or "眼" in mat_name:
            print(f"\n  [{i:2d}] 材质={mat_name!r}")
            print(f"       X[{min(xs):7.4f} .. {max(xs):7.4f}]  "
                  f"Y[{min(ys):7.4f} .. {max(ys):7.4f}]  "
                  f"Z[{min(zs):7.4f} .. {max(zs):7.4f}]  ({len(v)} 顶点)")
    # 眼睛骨骼位置
    print("\n  眼睛/头部骨骼（世界坐标，经过节点变换）:")
    vrmc = g.get("extensions", {}).get("VRMC_vrm", {})
    hb = vrmc.get("humanoid", {}).get("humanBones", {})
    for bname in ("head", "leftEye", "rightEye", "neck"):
        b = hb.get(bname) or {}
        ni = b.get("node")
        if ni is None:
            continue
        n = nodes[ni]
        print(f"    {bname:10s} -> node[{ni}] {n.get('name')!r}  "
              f"translation={n.get('translation')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())