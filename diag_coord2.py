"""验证 PMX→VRM 的坐标变换（缩放 + Z 翻转）。

MMD 是左手坐标系，glTF/VRM 是右手系 → Z 轴取反。
PMX 单位比 VRM 大（身高 20 vs 1.6）→ 缩放 ≈ 0.08。

用法：python diag_coord2.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from pmx_to_vrm_morphs import parse_pmx, read_glb, read_accessor, PMX, VRM_IN


def main() -> int:
    print("=" * 68)
    print("验证 PMX -> VRM 坐标变换")
    print("=" * 68)

    pmx_pos, _ = parse_pmx(PMX)
    gltf, bin_data = read_glb(VRM_IN)
    all_v = []
    for p in gltf["meshes"][0]["primitives"]:
        all_v.extend(read_accessor(gltf, bin_data, p["attributes"]["POSITION"]))

    Q = 1000.0
    def key(x, y, z, q=Q):
        return (round(x * q), round(y * q), round(z * q))

    # 用粗量化建索引，再精查
    print("\n[1] 用粗量化建 PMX 索引（容差 1mm）")
    for q in (100.0, 200.0, 500.0, 1000.0, 2000.0):
        idx = set(key(*p, q=q) for p in pmx_pos)
        print(f"    q={q:6.0f}  唯一键 {len(idx):,}")

    # 试各种缩放
    print("\n[2] 搜索最佳缩放（变换 = (x*s, y*s, -z*s)）")
    best = (0, None)
    for i in range(40, 130):
        s = i / 1000.0
        idx = {}
        for p in pmx_pos:
            idx[key(p[0] * s, p[1] * s, -p[2] * s, 500.0)] = 1
        hit = 0
        for v in all_v:
            if key(v[0], v[1], v[2], 500.0) in idx:
                hit += 1
        rate = hit / len(all_v) * 100
        if hit > best[0]:
            best = (hit, s)
        if rate > 20:
            print(f"    scale={s:.3f}  命中 {hit:6,} = {rate:5.1f}%")
    print(f"\n    ★ 最佳缩放 = {best[1]:.3f}  命中 {best[0]:,}/{len(all_v):,} "
          f"= {best[0]/len(all_v)*100:.1f}%")

    s = best[1]
    # 精调
    print("\n[3] 精调缩放（步长 0.0005）")
    fine_best = (0, s)
    for i in range(-20, 21):
        s2 = s + i * 0.0005
        if s2 <= 0:
            continue
        idx = {}
        for p in pmx_pos:
            idx[key(p[0] * s2, p[1] * s2, -p[2] * s2, 1000.0)] = 1
        hit = 0
        for v in all_v:
            if key(v[0], v[1], v[2], 1000.0) in idx:
                hit += 1
        if hit > fine_best[0]:
            fine_best = (hit, s2)
    print(f"    ★ 精调缩放 = {fine_best[1]:.4f}  命中 {fine_best[0]:,} "
          f"= {fine_best[0]/len(all_v)*100:.1f}%")

    # 用最佳值做最终验证 + 看误差
    s = fine_best[1]
    print(f"\n[4] 用 scale={s:.4f} 详细验证")
    idx_pts = {}
    for i, p in enumerate(pmx_pos):
        k = key(p[0] * s, p[1] * s, -p[2] * s, 1000.0)
        idx_pts.setdefault(k, []).append(i)

    hit = 0
    miss_samples = []
    for vi, v in enumerate(all_v):
        k = key(v[0], v[1], v[2], 1000.0)
        if k in idx_pts:
            hit += 1
        elif len(miss_samples) < 5:
            miss_samples.append((vi, v))

    print(f"    命中 {hit:,}/{len(all_v):,} = {hit/len(all_v)*100:.1f}%")
    if miss_samples:
        print("    未命中样例（VRM 坐标）:")
        for vi, v in miss_samples:
            print(f"      [{vi}] ({v[0]:8.4f}, {v[1]:8.4f}, {v[2]:8.4f})")
            # 找最近的 PMX 顶点
            t = (v[0] / s, v[1] / s, -v[2] / s)
            best_d, best_i = 1e18, None
            for i, p in enumerate(pmx_pos):
                d = sum((t[j] - p[j]) ** 2 for j in range(3))
                if d < best_d:
                    best_d, best_i = d, i
                    if d < 1e-8:
                        break
            print(f"           PMX 最近 #{best_i} 距离={best_d**0.5:.5f} (PMX 单位)")

    # 结论
    rate = hit / len(all_v) * 100
    print("\n" + "=" * 68)
    if rate > 90:
        print(f"结论：变换 = (x*{s:.4f}, y*{s:.4f}, -z*{s:.4f})  —— 可用！")
    elif rate > 50:
        print(f"结论：变换大致正确（{rate:.1f}%），但有顶点对不上")
        print("      （可能是接缝/重复顶点，或 PMX 有修改过的顶点）")
    else:
        print(f"结论：变换仍不对（{rate:.1f}%）")
    print("=" * 68)
    return 0


if __name__ == "__main__":
    sys.exit(main())
