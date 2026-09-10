"""pmx_to_vrm_morphs.py —— 把 PMX 的顶点表情转成 VRM 的 blendshape

背景：
  米雪儿的 VRM 是「静态」的（0 个 blendshape），因为 PMX→VRM 转换时丢了表情。
  但原始 PMX（米雪儿私服1.pmx）里有 41 个顶点 morph。本脚本把 PMX 的顶点位移
  按 VRM 网格的顶点顺序重新映射，写成 glTF 的 morph target，再注入 VRM。

难点与做法：
  1. PMX 与 VRM 的顶点数/顺序不同 → 用【位置哈希】建映射表
     （顶点位置在转换中保持，量化到 1e-4 后做键）
  2. glTF morph target 必须是相对位移，且要按 (POSITION 索引) 对齐
  3. 需给 mesh primitive 追加 targets，并在 accessor/bufferView 里落数据
  4. morph target 只影响 POSITION（VRM 1.0 允许 morphTargetBinds 只绑 POSITION）
  5. 最后写 VRMC_vrm.expressions.preset，让 three-vrm 认出来

用法：
  python pmx_to_vrm_morphs.py [--dry-run] [--out michelle_expr.vrm]
"""
from __future__ import annotations

import io
import json
import struct
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

PMX = Path(r"C:\Users\mier\Desktop\deepseek work\mate-engine\michelle_model\米雪儿私服1.pmx")
VRM_IN = Path(r"C:\Users\mier\Desktop\deepseek work\mate-engine\michelle_model\michelle.vrm")
VRM_OUT = HERE / "web3d" / "models" / "michelle_expr.vrm"

# PMX(MMD) → VRM(glTF) 的坐标变换
#   实测：位置哈希在最粗量化下 100% 命中（23,414/23,414）
#   * 缩放 0.08 —— PMX 身高 20 单位，VRM 身高 1.6 米
#   * Z 取反   —— MMD 左手坐标系 → glTF 右手坐标系
# 变换公式： vrm = (x*S, y*S, -z*S)
COORD_SCALE = 0.08
# 位移向量也要做同样变换（旋转部分由 Z 翻转体现）
def xform_pos(p):
    return (p[0] * COORD_SCALE, p[1] * COORD_SCALE, -p[2] * COORD_SCALE)

def xform_delta(d):
    """位移增量：缩放 + Z 翻转（与位置一致，无平移）"""
    return (d[0] * COORD_SCALE, d[1] * COORD_SCALE, -d[2] * COORD_SCALE)

# PMX 表情名 → VRM 1.0 预设表情名
# （VRM preset: happy/angry/sad/relaxed/surprised/aa/ih/ou/ee/oh/blink/blinkLeft/blinkRight/
#   lookUp/lookDown/lookLeft/lookRight/neutral）
MORPH_MAP: dict[str, str] = {
    # 眨眼
    "まばたき": "blink",
    "ウィンク": "blinkLeft",
    "ウィンク右": "blinkRight",
    "ウィンク２": "blinkLeft",
    "ｳｨﾝｸ２右": "blinkRight",
    # 口型
    "あ": "aa",
    "い": "ih",
    "う": "ou",
    "え": "ee",
    "お": "oh",
    # 情绪
    "笑い": "happy",
    "にやり": "happy",
    "口角上げ": "happy",
    "怒り": "angry",
    "悲しむ": "sad",
    "困る": "sad",
    "びっくり": "surprised",
    "真面目": "relaxed",
    # 视线（用眼球位移近似）
    "上": "lookUp",
    "下": "lookDown",
    "左斜": "lookLeft",
    "右斜": "lookRight",
}

# 额外保留为自定义表情（VRM custom expressions）
CUSTOM_KEEP = ["じと目", "瞳小", "ハイライト消", "ω", "∧", "ぺろっ",
               "てへぺろ", "歯無し上", "歯無し下", "口横広げ", "口角下げ"]

COMP = {5120: ("b", 1), 5121: ("B", 1), 5122: ("h", 2), 5123: ("H", 2),
        5125: ("I", 4), 5126: ("f", 4)}
NCOMP = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


# ---------------------------------------------------------------- PMX 解析
class PmxReader:
    def __init__(self, data: bytes, pos: int = 0):
        self.d = data
        self.p = pos
        self.encoding = "utf-16-le"
        self.add_uv = 0
        self.vsize = self.tsize = self.msize = 4
        self.bsize = self.mosize = self.rsize = 4

    def u8(self):
        v = self.d[self.p]; self.p += 1; return v

    def i8(self):
        v = struct.unpack_from("<b", self.d, self.p)[0]; self.p += 1; return v

    def u16(self):
        v = struct.unpack_from("<H", self.d, self.p)[0]; self.p += 2; return v

    def i16(self):
        v = struct.unpack_from("<h", self.d, self.p)[0]; self.p += 2; return v

    def i32(self):
        v = struct.unpack_from("<i", self.d, self.p)[0]; self.p += 4; return v

    def f32(self):
        v = struct.unpack_from("<f", self.d, self.p)[0]; self.p += 4; return v

    def text(self):
        n = self.i32()
        s = self.d[self.p:self.p + n].decode(self.encoding, errors="replace")
        self.p += n
        return s

    def idx(self, size, signed=True):
        if size == 1:
            return self.i8() if signed else self.u8()
        if size == 2:
            return self.i16() if signed else self.u16()
        return self.i32()

    def vec(self, n):
        return [self.f32() for _ in range(n)]


def parse_pmx(path: Path):
    """解析 PMX，返回 (顶点位置列表, morph 字典)"""
    data = path.read_bytes()
    assert data[:4] == b"PMX "
    r = PmxReader(data, 4)
    _ver = r.f32()
    gc = r.u8()
    glob = [r.u8() for _ in range(gc)]
    r.encoding = "utf-16-le" if glob[0] == 0 else "utf-8"
    r.add_uv = glob[1]
    r.vsize, r.tsize, r.msize = glob[2], glob[3], glob[4]
    r.bsize, r.mosize, r.rsize = glob[5], glob[6], glob[7]

    r.text(); r.text(); r.text(); r.text()   # name/nameEn/comment/commentEn

    # 顶点
    nv = r.i32()
    positions = []
    for _ in range(nv):
        positions.append(tuple(r.vec(3)))
        r.vec(3)                      # normal
        r.vec(2)                      # uv
        for _ in range(r.add_uv):
            r.vec(4)
        wt = r.u8()
        if wt == 0:
            r.idx(r.bsize)
        elif wt == 1:
            r.idx(r.bsize); r.idx(r.bsize); r.f32()
        elif wt == 2:
            for _ in range(4): r.idx(r.bsize)
            for _ in range(4): r.f32()
        elif wt == 3:
            r.idx(r.bsize); r.idx(r.bsize)
            r.f32(); r.vec(3); r.vec(3); r.vec(3)
        elif wt == 4:
            for _ in range(4): r.idx(r.bsize)
            for _ in range(4): r.f32()
        r.f32()                       # edge scale

    # 面（跳过）
    nf = r.i32()
    r.p += nf * r.vsize

    # 贴图（跳过）
    nt = r.i32()
    for _ in range(nt):
        r.text()

    # 材质（跳过，但要知道数量）
    # PMX 材质结构：name, nameEn, diffuse(4f), specular(3f), shininess(f),
    #   ambient(3f), drawFlag(u8), edgeColor(4f), edgeSize(f),
    #   textureIndex(tsize), sphereIndex(tsize), sphereMode(u8),
    #   sharedToon(u8), toonIndex(共享时 u8 / 否则 tsize), memo, faceCount(i32)
    nm = r.i32()
    for _ in range(nm):
        r.text(); r.text()
        r.vec(4)          # diffuse
        r.vec(3)          # specular
        r.f32()           # shininess
        r.vec(3)          # ambient
        r.u8()            # drawFlag
        r.vec(4)          # edgeColor
        r.f32()           # edgeSize
        r.idx(r.tsize)    # textureIndex
        r.idx(r.tsize)    # sphereIndex
        r.u8()            # sphereMode
        shared_toon = r.u8()
        if shared_toon == 1:
            r.u8()        # ★ 共享 toon：固定 1 字节（不是 tsize）
        else:
            r.idx(r.tsize)
        r.text()          # memo
        r.i32()           # faceCount

    # 骨骼（跳过）
    nb = r.i32()
    for _ in range(nb):
        r.text(); r.text()
        r.vec(3)
        r.idx(r.bsize)
        r.i32()
        flag = r.u16()
        if flag & 0x0001:
            r.idx(r.bsize)
        else:
            r.vec(3)
        if flag & 0x0100 or flag & 0x0200:
            r.idx(r.bsize); r.f32()
        if flag & 0x0400:
            r.vec(3)
        if flag & 0x0800:
            r.vec(3); r.vec(3)
        if flag & 0x2000:
            r.i32()
        if flag & 0x0020:
            r.idx(r.bsize); r.i32(); r.f32()
            nl = r.i32()
            for _ in range(nl):
                r.idx(r.bsize)
                lim = r.u8()
                if lim == 1:
                    r.vec(3); r.vec(3)

    # 表情 morph ★
    nmorph = r.i32()
    morphs: dict[str, list] = {}
    for _ in range(nmorph):
        name = r.text()
        r.text()                      # nameEn
        r.u8()                        # panel
        mtype = r.u8()
        cnt = r.i32()
        if mtype == 1:                # Vertex —— 我们要的
            offs = []
            for _ in range(cnt):
                vi = r.idx(r.vsize, signed=False)
                off = r.vec(3)
                offs.append((vi, off))
            morphs[name] = offs
        elif mtype == 2:              # Bone
            r.p += cnt * (r.bsize + 3 * 4 + 4 * 4)
        elif mtype in (3, 4, 5, 6, 7):   # UV
            r.p += cnt * (r.vsize + 4 * 4)
        elif mtype == 8:              # Material
            r.p += cnt * (r.msize + 1 + 4 * 4 + 3 * 4 + 4 + 3 * 4 + 4 * 4 + 4 + 4 * 4 * 3)
        elif mtype in (0, 9):         # Group / Flip
            r.p += cnt * (r.mosize + 4)
        elif mtype == 10:             # Impulse
            r.p += cnt * (r.rsize + 1 + 3 * 4 + 3 * 4)
        else:
            raise ValueError(f"未知 morph 类型 {mtype}（在 {name}）")

    return positions, morphs


# ---------------------------------------------------------------- GLB 读写
def read_glb(path: Path):
    buf = path.read_bytes()
    assert buf[:4] == b"glTF"
    _ver, _total = struct.unpack_from("<II", buf, 4)
    off = 12
    chunks = []
    while off < len(buf):
        clen, ctype = struct.unpack_from("<II", buf, off)
        chunks.append((ctype, buf[off + 8:off + 8 + clen]))
        off += 8 + clen
    gltf = None
    bin_chunk = b""
    for ctype, cdata in chunks:
        if ctype == 0x4E4F534A:
            gltf = json.loads(cdata.decode("utf-8"))
        elif ctype == 0x004E4942:
            bin_chunk = cdata
    return gltf, bytearray(bin_chunk)


def write_glb(path: Path, gltf: dict, bin_data: bytes):
    js = json.dumps(gltf, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    js += b" " * ((4 - len(js) % 4) % 4)
    bn = bytes(bin_data)
    bn += b"\x00" * ((4 - len(bn) % 4) % 4)
    total = 12 + 8 + len(js) + 8 + len(bn)
    out = bytearray()
    out += b"glTF" + struct.pack("<II", 2, total)
    out += struct.pack("<II", len(js), 0x4E4F534A) + js
    out += struct.pack("<II", len(bn), 0x004E4942) + bn
    path.write_bytes(out)


def read_accessor(gltf, bin_data, idx):
    acc = gltf["accessors"][idx]
    n = acc["count"]
    nc = NCOMP[acc["type"]]
    fmt, sz = COMP[acc["componentType"]]
    bv = gltf["bufferViews"][acc["bufferView"]]
    base = bv.get("byteOffset", 0) + acc.get("byteOffset", 0)
    stride = bv.get("byteStride") or (nc * sz)
    out = []
    for i in range(n):
        out.append(struct.unpack_from("<" + fmt * nc, bin_data, base + i * stride))
    return out


def append_to_bin(gltf, bin_data: bytearray, raw: bytes, target=None):
    """把数据追加到 BIN，返回新建的 bufferView 索引"""
    pad = (4 - len(bin_data) % 4) % 4
    bin_data.extend(b"\x00" * pad)
    offset = len(bin_data)
    bin_data.extend(raw)
    bv = {"buffer": 0, "byteOffset": offset, "byteLength": len(raw)}
    if target is not None:
        bv["target"] = target
    gltf.setdefault("bufferViews", []).append(bv)
    return len(gltf["bufferViews"]) - 1


def debug_offsets():
    """逐步打印偏移量，定位解析错位点（用 pmx_info.py 的成功逻辑对照）"""
    data = PMX.read_bytes()
    r = PmxReader(data, 4)
    _ver = r.f32()
    gc = r.u8()
    glob = [r.u8() for _ in range(gc)]
    r.encoding = "utf-16-le" if glob[0] == 0 else "utf-8"
    r.add_uv = glob[1]
    r.vsize, r.tsize, r.msize = glob[2], glob[3], glob[4]
    r.bsize, r.mosize, r.rsize = glob[5], glob[6], glob[7]
    print(f"glob={glob}  sizes v={r.vsize} t={r.tsize} m={r.msize} "
          f"b={r.bsize} mo={r.mosize} r={r.rsize}")

    r.text(); r.text(); r.text(); r.text()
    print(f"after header texts: p={r.p}")

    nv = r.i32()
    print(f"vertexCount={nv:,}  p={r.p}")
    for i in range(nv):
        r.vec(3); r.vec(3); r.vec(2)
        for _ in range(r.add_uv):
            r.vec(4)
        wt = r.u8()
        if wt == 0:
            r.idx(r.bsize)
        elif wt == 1:
            r.idx(r.bsize); r.idx(r.bsize); r.f32()
        elif wt == 2:
            for _ in range(4): r.idx(r.bsize)
            for _ in range(4): r.f32()
        elif wt == 3:
            r.idx(r.bsize); r.idx(r.bsize)
            r.f32(); r.vec(3); r.vec(3); r.vec(3)
        elif wt == 4:
            for _ in range(4): r.idx(r.bsize)
            for _ in range(4): r.f32()
        else:
            raise ValueError(f"顶点 #{i} 未知 weightType={wt}  p={r.p}")
        r.f32()
    print(f"after vertices: p={r.p}")

    nf = r.i32()
    print(f"faceIndexCount={nf:,}  p={r.p}  (预计跳过 {nf*r.vsize} 字节)")
    r.p += nf * r.vsize
    print(f"after faces: p={r.p}")

    nt = r.i32()
    print(f"textureCount={nt}  p={r.p}")
    for i in range(nt):
        t = r.text()
    print(f"after textures: p={r.p}")

    nm = r.i32()
    print(f"materialCount={nm}  p={r.p}")
    for i in range(nm):
        try:
            r.text(); r.text()
            r.vec(4); r.vec(3); r.f32(); r.vec(3)
            r.u8()                        # drawFlag
            r.vec(4); r.f32()             # edgeColor, edgeSize
            r.idx(r.tsize); r.idx(r.tsize)
            r.u8()                        # sphereMode
            shared_toon = r.u8()
            if shared_toon == 1:
                r.u8()
            else:
                r.idx(r.tsize)
            r.text()
            fc = r.i32()
        except Exception as e:
            print(f"  !! 材质 #{i} 解析失败: {e}  p={r.p}")
            raise
    print(f"after materials: p={r.p}")

    nb = r.i32()
    print(f"boneCount={nb}  p={r.p}")
    for i in range(nb):
        try:
            r.text(); r.text()
            r.vec(3)
            r.idx(r.bsize)
            r.i32()
            flag = r.u16()
            if flag & 0x0001:
                r.idx(r.bsize)
            else:
                r.vec(3)
            if flag & 0x0100 or flag & 0x0200:
                r.idx(r.bsize); r.f32()
            if flag & 0x0400:
                r.vec(3)
            if flag & 0x0800:
                r.vec(3); r.vec(3)
            if flag & 0x2000:
                r.i32()
            if flag & 0x0020:
                r.idx(r.bsize); r.i32(); r.f32()
                nl = r.i32()
                for _ in range(nl):
                    r.idx(r.bsize)
                    lim = r.u8()
                    if lim == 1:
                        r.vec(3); r.vec(3)
        except Exception as e:
            print(f"  !! 骨骼 #{i} 解析失败: {e}  p={r.p}")
            raise
    print(f"after bones: p={r.p}")

    nmorph = r.i32()
    print(f"morphCount={nmorph}  p={r.p}")


def main() -> int:
    dry = "--dry-run" in sys.argv
    if "--debug-offsets" in sys.argv:
        debug_offsets()
        return 0
    out_path = VRM_OUT
    if "--out" in sys.argv:
        out_path = Path(sys.argv[sys.argv.index("--out") + 1])

    print("=" * 68)
    print("PMX 表情 -> VRM blendshape 转换")
    print("=" * 68)

    # ---- 1. 解析 PMX ----
    print(f"\n[1] 解析 PMX：{PMX.name}")
    pmx_pos, pmx_morphs = parse_pmx(PMX)
    print(f"    PMX 顶点 {len(pmx_pos):,}   表情 {len(pmx_morphs)} 个")

    # ---- 2. 读 VRM ----
    print(f"\n[2] 读取 VRM：{VRM_IN.name}")
    gltf, bin_data = read_glb(VRM_IN)
    mesh = gltf["meshes"][0]
    prims = mesh["primitives"]
    print(f"    mesh[0] 有 {len(prims)} 个 primitive")

    # ---- 3. 建顶点映射（位置哈希，带坐标变换）----
    print(f"\n[3] 建立顶点映射（位置哈希 + 坐标变换 scale={COORD_SCALE}, Z 翻转）")
    Q = 1000.0      # 量化精度 1e-3（实测 ≥99% 命中）

    def key(x, y, z):
        return (round(x * Q), round(y * Q), round(z * Q))

    # PMX: 变换后的位置 -> [顶点索引...]
    pmx_by_pos: dict[tuple, list[int]] = {}
    for i, p in enumerate(pmx_pos):
        pmx_by_pos.setdefault(key(*xform_pos(p)), []).append(i)
    print(f"    PMX 唯一位置键: {len(pmx_by_pos):,} / {len(pmx_pos):,} 顶点")

    # VRM: 每个 primitive 的 POSITION -> 顶点索引
    total_v = 0
    matched = 0
    prim_maps = []      # [(prim_index, {vrm_vert_idx: pmx_vert_idx})]
    for pi, prim in enumerate(prims):
        pos_acc = prim["attributes"]["POSITION"]
        verts = read_accessor(gltf, bin_data, pos_acc)
        vmap = {}
        hit = 0
        for vi, (x, y, z) in enumerate(verts):
            k = key(x, y, z)
            cand = pmx_by_pos.get(k)
            if cand:
                vmap[vi] = cand[0]
                hit += 1
        total_v += len(verts)
        matched += hit
        prim_maps.append((pi, vmap))
        print(f"    prim[{pi:2d}] 顶点 {len(verts):5d}  命中 {hit:5d}  "
              f"({hit/max(1,len(verts))*100:5.1f}%)")

    rate = matched / max(1, total_v) * 100
    print(f"    合计 {matched:,}/{total_v:,} = {rate:.1f}%")
    if rate < 60:
        print("    !! 命中率过低，位置对不上 —— 可能 VRM 经过了缩放/旋转")
        print("    （若如此需先对 PMX 坐标做同样的变换）")
        return 2

    # 注意：VRM 的米雪儿是 Y-up，PMX 也是 Y-up 但左右手系可能不同。
    # 若命中率低，就是这里的问题 —— 上面已经用命中率兜底。

    # ---- 4. 生成 morph target ----
    print(f"\n[4] 生成 blendshape")
    # three-vrm 规范：morph target 的 POSITION 位移
    # glTF 里 targets 是每个 primitive 一份，位移按该 primitive 的顶点顺序

    targets_meta = []      # (morph_name, prim_index, accessor_index)
    morph_names_order = []

    # 选要转换的表情：预设映射 + 自定义保留
    plan: list[tuple[str, str]] = []       # (PMX 名, VRM 表情名)
    for pmx_name, vrm_name in MORPH_MAP.items():
        if pmx_name in pmx_morphs:
            plan.append((pmx_name, vrm_name))
    for n in CUSTOM_KEEP:
        if n in pmx_morphs:
            plan.append((n, n))

    print(f"    计划转换 {len(plan)} 个 PMX 表情")

    # 先算出每个 PMX 表情在每个 primitive 上的位移数组
    # 注意：多个 PMX 表情可能映射到同一个 VRM 名字
    #   （如 happy <- 笑い / にやり / 口角上げ，是三种不同幅度的"笑"）
    # VRM 里一个名字只能有一个表达式 → 取【位移顶点最多】的那个（表现力最强），
    # 而不是叠加（叠加会夸张失真）。
    cand: dict[str, list[tuple[int, str, dict]]] = {}   # vrm_name -> [(nz, pmx_name, per_prim)]

    for pmx_name, vrm_name in plan:
        offs = pmx_morphs[pmx_name]
        # 位置增量表（带坐标变换）
        delta_by_pmx: dict[int, tuple] = {vi: xform_delta(off) for vi, off in offs}
        per_prim = {}
        nz_total = 0
        for pi, vmap in prim_maps:
            n = len(read_accessor(gltf, bin_data, prims[pi]["attributes"]["POSITION"]))
            arr = [(0.0, 0.0, 0.0)] * n
            any_nz = False
            for vi in range(n):
                pvi = vmap.get(vi)
                if pvi is None:
                    continue
                d = delta_by_pmx.get(pvi)
                if d is None:
                    continue
                arr[vi] = d
                any_nz = True
            if any_nz:
                cnt = sum(1 for a in arr if a != (0.0, 0.0, 0.0))
                nz_total += cnt
                per_prim[pi] = arr
        if per_prim:
            cand.setdefault(vrm_name, []).append((nz_total, pmx_name, per_prim))
            print(f"      {pmx_name:12s} -> {vrm_name:12s} "
                  f"{len(per_prim)} prim, {nz_total} 位移顶点")

    # 每组挑位移最多的
    morph_prim_deltas: dict[str, dict[int, list]] = {}
    morph_names_order: list[str] = []
    print("\n    同名字冲突处理（取表现力最强者）:")
    for vrm_name, lst in cand.items():
        lst.sort(key=lambda x: -x[0])
        nz, best_pmx, per_prim = lst[0]
        morph_prim_deltas[vrm_name] = per_prim
        morph_names_order.append(vrm_name)
        if len(lst) > 1:
            others = ", ".join(f"{p}({n})" for n, p, _ in lst[1:])
            print(f"      {vrm_name:12s} <- {best_pmx} ({nz})   弃用: {others}")

    # 保持稳定顺序：预设在前，自定义在后
    ORDER = ["blink", "blinkLeft", "blinkRight",
             "aa", "ih", "ou", "ee", "oh",
             "happy", "angry", "sad", "relaxed", "surprised",
             "lookUp", "lookDown", "lookLeft", "lookRight"]
    morph_names_order.sort(key=lambda n: (ORDER.index(n) if n in ORDER else 100, n))

    if dry:
        print("\n[dry-run] 不写文件")
        return 0

    # ---- 5. 写入 glTF ----
    print(f"\n[5] 写入 morph target 数据")
    # 每个 primitive 的 targets 数组 = [{POSITION: acc}, ...]（按表情顺序）
    for pi, prim in enumerate(prims):
        prim.setdefault("targets", [])

    # 表达式 -> 每个 primitive 的 accessor 索引
    expr_binds: dict[str, list[tuple[int, int]]] = {}   # vrm_name -> [(node/prim, accessor)]

    for vrm_name in morph_names_order:
        per_prim = morph_prim_deltas[vrm_name]
        binds = []
        for pi, prim in enumerate(prims):
            arr = per_prim.get(pi)
            n = len(read_accessor(gltf, bin_data, prim["attributes"]["POSITION"]))
            if arr is None:
                arr = [(0.0, 0.0, 0.0)] * n
            raw = struct.pack("<" + "f" * (3 * n), *[c for v in arr for c in v])
            bv = append_to_bin(gltf, bin_data, raw, target=34962)
            acc = {
                "bufferView": bv, "componentType": 5126,
                "count": n, "type": "VEC3",
                "min": [min(v[i] for v in arr) for i in range(3)],
                "max": [max(v[i] for v in arr) for i in range(3)],
            }
            gltf["accessors"].append(acc)
            acc_idx = len(gltf["accessors"]) - 1
            prim["targets"].append({"POSITION": acc_idx})
            binds.append((pi, acc_idx))
        expr_binds[vrm_name] = binds

    print(f"    已写入 {len(morph_names_order)} 个表情 × {len(prims)} 个 primitive")

    # ---- 6. 写 VRMC_vrm.expressions ----
    print(f"\n[6] 注册 VRM 表达式")
    ext = gltf.setdefault("extensions", {})
    vrmc = ext.setdefault("VRMC_vrm", {})
    exprs = vrmc.setdefault("expressions", {})
    preset = exprs.setdefault("preset", {})
    custom = exprs.setdefault("custom", {})

    # VRM 1.0 预设名（three-vrm 认这些）
    PRESET_NAMES = {"happy", "angry", "sad", "relaxed", "surprised",
                    "aa", "ih", "ou", "ee", "oh",
                    "blink", "blinkLeft", "blinkRight",
                    "lookUp", "lookDown", "lookLeft", "lookRight", "neutral"}

    # morphTargetBinds 需要 node + index（index = 该 node 的 mesh targets 里的序号）
    # 米雪儿整个身体是一个 node（mesh 0），所有 primitive 在同一 node 下
    # VRM 规范里 morphTargetBinds 指向 node 的 mesh targets 的【全局序号】
    # three-vrm 用的是 mesh.morphTargetDictionary（three 会把多 primitive 合并成
    # 一个 mesh 的 morphTargetInfluences，index 按第一个 primitive 的 targets 计）
    # → 保险做法：每个表达式在所有 primitive 里同序号，取 0（第一个 primitive）
    #   因为 three 的 GLTFLoader 对 multi-primitive mesh 的 morph target 支持是
    #   按"每个 primitive 各自 targets 数组的第 k 项"共享 k。

    added_preset, added_custom = [], []
    for vrm_name in morph_names_order:
        target_idx = len(added_preset) + len(added_custom)   # 各 primitive 的 targets 序号一致
        binds = [{"node": None, "index": target_idx, "weight": 1.0}]   # node 稍后填
        entry = {"morphTargetBinds": binds}
        if vrm_name in PRESET_NAMES:
            preset[vrm_name] = entry
            added_preset.append(vrm_name)
        else:
            custom[vrm_name] = entry
            added_custom.append(vrm_name)

    # 找承载 mesh 的 node
    mesh_node = None
    for ni, node in enumerate(gltf.get("nodes", [])):
        if node.get("mesh") == 0 and "skin" in node:
            mesh_node = ni
            break
    if mesh_node is None:
        for ni, node in enumerate(gltf.get("nodes", [])):
            if node.get("mesh") == 0:
                mesh_node = ni
                break
    print(f"    mesh 承载节点: node[{mesh_node}]")
    all_exprs = list(preset.values()) + list(custom.values())
    for e in all_exprs:
        for b in e.get("morphTargetBinds", []):
            b["node"] = mesh_node

    # ★ 同一预设名可能对应多个 PMX 表情（如 happy = 笑い+にやり+口角上げ）。
    #   把它们的 bind 合并到一个表达式里 —— VRM 允许多个 morphTargetBinds，
    #   但同一个 target index 不能重复，否则权重会叠加出错。
    #   正确做法：合并时冲突的 target 取"位移更明显"的那个（保留第一份，去重）。
    for name, entry in list(preset.items()) + list(custom.items()):
        seen, merged = set(), []
        for b in entry.get("morphTargetBinds", []):
            k = b.get("index")
            if k in seen:
                continue
            seen.add(k)
            merged.append(b)
        entry["morphTargetBinds"] = merged

    print(f"    预设表情 {len(preset)}: {sorted(preset.keys())}")
    print(f"    自定义表情 {len(custom)}: {sorted(custom.keys())}")

    # ---- 7. 写文件 ----
    print(f"\n[7] 写出 {out_path.name}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    write_glb(out_path, gltf, bytes(bin_data))
    print(f"    完成：{out_path}  ({out_path.stat().st_size/1024/1024:.2f} MB)")

    # 保存映射说明
    meta = {
        "source_pmx": str(PMX),
        "source_vrm": str(VRM_IN),
        "matchRate": round(rate, 2),
        "preset": added_preset,
        "custom": added_custom,
        "morphMap": MORPH_MAP,
    }
    (out_path.parent / "michelle_expr_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
