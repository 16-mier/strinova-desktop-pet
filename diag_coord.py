"""对比 PMX 与 VRM 的顶点坐标，找出坐标变换关系。

用法：python diag_coord.py
"""
from __future__ import annotations

import io
import json
import os
import struct
import sys
from pathlib import Path

# 不包 TextIOWrapper（避免关闭顺序问题）
sys.stdout.reconfigure(encoding="utf-8", errors="replace") if hasattr(sys.stdout, "reconfigure") else None
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

def _print(*a, **kw):
    out = " ".join(str(x) for x in a)
    sys.stdout.write(out + "\n")
    sys.stdout.flush()

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from pmx_to_vrm_morphs import parse_pmx, read_glb, read_accessor, PMX, VRM_IN


def main() -> int:
    _print("=" * 68)
    _print("PMX vs VRM 坐标对比")
    _print("=" * 68)

    pmx_pos, _ = parse_pmx(PMX)
    _print(f"\n[PMX] 顶点 {len(pmx_pos):,}")

    def stat(name, pts):
        xs = [p[0] for p in pts]; ys = [p[1] for p in pts]; zs = [p[2] for p in pts]
        _print(f"  {name:8s} X[{min(xs):8.3f} .. {max(xs):8.3f}]  "
               f"Y[{min(ys):8.3f} .. {max(ys):8.3f}]  "
               f"Z[{min(zs):8.3f} .. {max(zs):8.3f}]")

    stat("PMX", pmx_pos)
    _print(f"\n  PMX 前 5 个顶点:")
    for p in pmx_pos[:5]:
        _print(f"      ({p[0]:9.4f}, {p[1]:9.4f}, {p[2]:9.4f})")

    gltf, bin_data = read_glb(VRM_IN)
    prim = gltf["meshes"][0]["primitives"][0]
    verts = read_accessor(gltf, bin_data, prim["attributes"]["POSITION"])
    _print(f"\n[VRM] prim[0] 顶点 {len(verts):,}")
    stat("VRM", verts)
    _print(f"\n  VRM 前 5 个顶点:")
    for v in verts[:5]:
        _print(f"      ({v[0]:9.4f}, {v[1]:9.4f}, {v[2]:9.4f})")

    # 全部 VRM 顶点
    all_v = []
    for p in gltf["meshes"][0]["primitives"]:
        all_v.extend(read_accessor(gltf, bin_data, p["attributes"]["POSITION"]))
    _print(f"\n[VRM] 全部 {len(all_v):,} 顶点")
    stat("VRM全部", all_v)

    # ---- 试各种变换 ----
    _print("\n" + "=" * 68)
    _print("尝试坐标变换，看哪种能匹配")
    _print("=" * 68)

    Q = 10000.0
    def key(x, y, z):
        return (round(x * Q), round(y * Q), round(z * Q))

    pmx_by_pos = {}
    for p in pmx_pos:
        pmx_by_pos.setdefault(key(*p), 0)
        pmx_by_pos[key(*p)] += 1

    def test(name, fn):
        hit = 0
        for v in all_v:
            t = fn(v)
            if key(*t) in pmx_by_pos:
                hit += 1
        _print(f"  {name:34s} 命中 {hit:6,}/{len(all_v):,} = {hit/len(all_v)*100:5.1f}%")
        return hit

    import itertools
    results = {}
    # 尝试所有轴排列 + 符号组合
    for perm in itertools.permutations(range(3)):
        for signs in itertools.product((1, -1), repeat=3):
            name = (f"({'+' if signs[0]>0 else '-'}x{perm[0]}, "
                    f"{'+' if signs[1]>0 else '-'}x{perm[1]}, "
                    f"{'+' if signs[2]>0 else '-'}x{perm[2]})")
            def fn(v, perm=perm, signs=signs):
                return (signs[0]*v[perm[0]], signs[1]*v[perm[1]], signs[2]*v[perm[2]])
            hit = test(name, fn)
            results[name] = hit

    best = max(results.items(), key=lambda kv: kv[1])
    _print(f"\n  ★ 最佳变换: {best[0]}  ({best[1]:,} 命中 = {best[1]/len(all_v)*100:.1f}%)")

    # 若有命中，检查缩放
    if best[1] > 0:
        _print("\n  --- 检查是否需要缩放 ---")
        import re
        nums = re.findall(r'([+-])x(\d)', best[0])
        sg = [1 if nums[i][0] == '+' else -1 for i in range(3)]
        pm_ = [int(nums[i][1]) for i in range(3)]
        ratios = []
        for v in all_v[:2000]:
            t = (sg[0]*v[pm_[0]], sg[1]*v[pm_[1]], sg[2]*v[pm_[2]])
            if key(*t) in pmx_by_pos and max(abs(c) for c in t) > 0.1:
                best_d, best_p = 1e9, None
                for p in pmx_pos[:3000]:
                    d = sum((t[i]-p[i])**2 for i in range(3))
                    if d < best_d:
                        best_d, best_p = d, p
                if best_p and max(abs(c) for c in t) > 0.5:
                    r_ = [best_p[i]/t[i] for i in range(3) if abs(t[i]) > 0.5]
                    if r_:
                        ratios.append(sum(r_)/len(r_))
        if ratios:
            ratios.sort()
            _print(f"      比例中位数 ≈ {ratios[len(ratios)//2]:.6f}")
            _print(f"      比例范围 [{ratios[0]:.4f} .. {ratios[-1]:.4f}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
