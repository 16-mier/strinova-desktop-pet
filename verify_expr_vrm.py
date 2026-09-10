"""verify_expr_vrm.py —— 验证转换出的 VRM 表情能否被 three-vrm 正确读取

检查项：
  1. glTF 结构合法（targets / accessors / expressions 齐全）
  2. 每个 preset 表情的 morphTargetBinds 指向正确的 target
  3. 位移数据非零且量级合理（不应该是巨大的值）
  4. three-vrm 能否列出这些表达式（浏览器实测）

用法：python verify_expr_vrm.py
"""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

VRM = HERE / "web3d" / "models" / "michelle_expr.vrm"
ORIG = Path(r"C:\Users\mier\Desktop\deepseek work\mate-engine\michelle_model\michelle.vrm")

NCOMP = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}
COMP = {5120: ("b", 1), 5121: ("B", 1), 5122: ("h", 2), 5123: ("H", 2),
        5125: ("I", 4), 5126: ("f", 4)}


def read_glb(path):
    buf = path.read_bytes()
    assert buf[:4] == b"glTF"
    off, gltf, bin_data = 12, None, b""
    while off < len(buf):
        clen, ctype = struct.unpack_from("<II", buf, off)
        cd = buf[off + 8:off + 8 + clen]
        if ctype == 0x4E4F534A:
            gltf = json.loads(cd.decode("utf-8"))
        elif ctype == 0x004E4942:
            bin_data = cd
        off += 8 + clen
    return gltf, bin_data


def read_acc(gltf, bin_data, idx):
    a = gltf["accessors"][idx]
    nc = NCOMP[a["type"]]
    fmt, sz = COMP[a["componentType"]]
    bv = gltf["bufferViews"][a["bufferView"]]
    base = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
    stride = bv.get("byteStride") or (nc * sz)
    return [struct.unpack_from("<" + fmt * nc, bin_data, base + i * stride)
            for i in range(a["count"])]


def main() -> int:
    print("=" * 70)
    print(f"验证 {VRM.name}")
    print("=" * 70)
    if not VRM.exists():
        print("文件不存在！先跑 pmx_to_vrm_morphs.py")
        return 1

    gltf, bin_data = read_glb(VRM)
    print(f"\n文件 {VRM.stat().st_size/1024/1024:.2f} MB "
          f"（原模型 {ORIG.stat().st_size/1024/1024:.2f} MB）")

    mesh = gltf["meshes"][0]
    prims = mesh["primitives"]
    print(f"\n[1] mesh[0]: {len(prims)} 个 primitive")
    target_counts = [len(p.get("targets", [])) for p in prims]
    print(f"    各 primitive 的 targets 数量: {target_counts}")
    ok_uniform = len(set(target_counts)) == 1
    print(f"    {'[OK]' if ok_uniform else '[!!]'} targets 数量一致: {ok_uniform}")

    # 表达式
    vrmc = gltf.get("extensions", {}).get("VRMC_vrm", {})
    exprs = vrmc.get("expressions", {})
    preset = exprs.get("preset", {})
    custom = exprs.get("custom", {})
    print(f"\n[2] 表达式定义")
    print(f"    预设 {len(preset)} 个: {sorted(preset.keys())}")
    print(f"    自定义 {len(custom)} 个: {sorted(custom.keys())}")

    # 检查每个表达式的 bind
    print(f"\n[3] morphTargetBinds 检查")
    all_names = list(preset.keys()) + list(custom.keys())
    bad = []
    for name in all_names:
        e = preset.get(name) or custom.get(name)
        binds = e.get("morphTargetBinds", [])
        if not binds:
            bad.append((name, "无 binds"))
            continue
        for b in binds:
            if b.get("node") is None:
                bad.append((name, "node 未设置"))
            if b.get("index") is None:
                bad.append((name, "index 未设置"))
            elif b["index"] >= max(target_counts or [0]):
                bad.append((name, f"index {b['index']} 越界"))
            if not b.get("weight"):
                bad.append((name, "weight 为 0"))
    if bad:
        print(f"    [!!] 有问题 {len(bad)} 个:")
        for n, why in bad[:10]:
            print(f"        {n}: {why}")
    else:
        print(f"    [OK] 全部 {len(all_names)} 个表达式的 bind 合法")
    print(f"    示例: preset['happy'] = "
          f"{json.dumps(preset.get('happy', {}), ensure_ascii=False)[:160]}")

    # 位移数据检查
    print(f"\n[4] 位移数据量级检查（关键：应为厘米级偏移，不能巨大）")
    f32 = struct.unpack
    report = []
    for name in ["blink", "happy", "angry", "aa", "surprised"]:
        e = preset.get(name)
        if not e:
            continue
        b0 = e["morphTargetBinds"][0]
        ti = b0["index"]
        acc_idx = prims[b0["node"] and 0 or 0]["targets"][ti]["POSITION"] if False else None
        # 从第一个 primitive 取该 target 的 accessor
        acc_idx = prims[0]["targets"][ti]["POSITION"]
        vals = read_acc(gltf, bin_data, acc_idx)
        mags = [abs(v[0]) + abs(v[1]) + abs(v[2]) for v in vals]
        nz = [m for m in mags if m > 1e-9]
        report.append((name, len(vals), len(nz), max(mags) if mags else 0,
                       (sum(nz) / len(nz)) if nz else 0))
    print(f"    {'表情':12s} {'顶点数':>7s} {'位移顶点':>7s} {'最大位移':>10s} {'平均位移':>10s}")
    for name, n, nz, mx, avg in report:
        flag = ""
        if mx > 0.5:
            flag = "  <-- 过大！"
        elif nz == 0:
            flag = "  <-- 全零！"
        print(f"    {name:12s} {n:7d} {nz:7d} {mx:10.5f} {avg:10.5f}{flag}")

    # 结构对比
    print(f"\n[5] 与原模型结构对比")
    g2, _ = read_glb(ORIG)
    m2 = g2["meshes"][0]
    print(f"    原: accessors={len(g2['accessors'])} bufferViews={len(g2['bufferViews'])} "
          f"targets={[len(p.get('targets',[])) for p in m2['primitives']][:3]}...")
    print(f"    新: accessors={len(gltf['accessors'])} bufferViews={len(gltf['bufferViews'])} "
          f"targets={target_counts[:3]}...")
    print(f"    顶点数: 原={sum(len(read_acc(g2, _, p['attributes']['POSITION'])) for p in m2['primitives'])} "
          f"新={sum(len(read_acc(gltf, bin_data, p['attributes']['POSITION'])) for p in prims)}")

    # 完整性：POSITION 数据没被破坏
    print(f"\n[6] 原始网格完整性")
    same = True
    for i, p in enumerate(prims):
        a = read_acc(gltf, bin_data, p["attributes"]["POSITION"])
        b = read_acc(g2, bin_data, m2["primitives"][i]["attributes"]["POSITION"]) \
            if i < len(m2["primitives"]) else None
        if b is None or len(a) != len(b):
            same = False
            break
        for va, vb in zip(a, b):
            if any(abs(va[j] - vb[j]) > 1e-6 for j in range(3)):
                same = False
                break
    print(f"    {'[OK] POSITION 与原模型完全一致' if same else '[!!] POSITION 被改动'}")

    print("\n" + "=" * 70)
    verdict = (ok_uniform and not bad and all(mx < 0.5 and nz > 0 for _, _, nz, mx, _ in report))
    print(f"结论: {'结构合法，可以加载' if verdict else '存在问题，需检查上面标记'}")
    print("=" * 70)
    return 0 if verdict else 1


if __name__ == "__main__":
    sys.exit(main())
