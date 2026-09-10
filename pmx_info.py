"""pmx_info.py —— 解析 MMD 的 PMX 模型，列出骨骼 / 表情(morph) / 材质。

PMX 是 MMD 的模型格式，通常带大量面部表情（日语叫「モーフ」）。
如果原模型的表情还在，就能把它们转成 VRM 的 blendshape，让米雪儿有表情。

用法：python pmx_info.py <file.pmx> [--dump-morphs out.json]
"""
from __future__ import annotations

import io
import json
import struct
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


class R:
    """PMX 二进制读取器（支持 UTF-16LE / UTF-8 两种编码模式）"""

    def __init__(self, data: bytes):
        self.d = data
        self.p = 0
        self.encoding = "utf-16-le"
        self.add_uv = 0
        self.vertex_index_size = 4
        self.texture_index_size = 4
        self.material_index_size = 4
        self.bone_index_size = 4
        self.morph_index_size = 4
        self.rigidbody_index_size = 4

    def u8(self):
        v = self.d[self.p]
        self.p += 1
        return v

    def i8(self):
        v = struct.unpack_from("<b", self.d, self.p)[0]
        self.p += 1
        return v

    def u16(self):
        v = struct.unpack_from("<H", self.d, self.p)[0]
        self.p += 2
        return v

    def i16(self):
        v = struct.unpack_from("<h", self.d, self.p)[0]
        self.p += 2
        return v

    def i32(self):
        v = struct.unpack_from("<i", self.d, self.p)[0]
        self.p += 4
        return v

    def f32(self):
        v = struct.unpack_from("<f", self.d, self.p)[0]
        self.p += 4
        return v

    def text(self) -> str:
        n = self.i32()
        raw = self.d[self.p:self.p + n]
        self.p += n
        return raw.decode(self.encoding, errors="replace")

    def idx(self, size: int, signed: bool = True) -> int:
        """按指定字节数读取索引（PMX 的索引宽度可变）"""
        if size == 1:
            return self.i8() if signed else self.u8()
        if size == 2:
            return self.i16() if signed else self.u16()
        return self.i32()

    def vec(self, n: int):
        return [self.f32() for _ in range(n)]


MORPH_NAMES = {0: "Group", 1: "Vertex", 2: "Bone", 3: "UV", 4: "UV1",
               5: "UV2", 6: "UV3", 7: "UV4", 8: "Material", 9: "Flip",
               10: "Impulse"}


def parse(path: Path) -> dict:
    data = path.read_bytes()
    header = data[:4]
    if header != b"PMX ":
        raise ValueError(f"不是 PMX 文件 (header={header!r})")
    r = R(data)
    r.p = 4                       # ★ 跳过 "PMX " 魔数（4 字节）
    version = r.f32()
    glob_count = r.u8()
    glob = [r.u8() for _ in range(glob_count)]

    # glob[0] = 编码 (0=UTF-16LE, 1=UTF-8)
    r.encoding = "utf-16-le" if glob[0] == 0 else "utf-8"
    r.add_uv = glob[1]
    r.vertex_index_size = glob[2]
    r.texture_index_size = glob[3]
    r.material_index_size = glob[4]
    r.bone_index_size = glob[5]
    r.morph_index_size = glob[6]
    r.rigidbody_index_size = glob[7]

    info = {
        "version": version,
        "encoding": r.encoding,
        "addUV": r.add_uv,
        "indexSizes": {
            "vertex": r.vertex_index_size, "texture": r.texture_index_size,
            "material": r.material_index_size, "bone": r.bone_index_size,
            "morph": r.morph_index_size, "rigidbody": r.rigidbody_index_size,
        },
    }

    info["name"] = r.text()
    info["nameEn"] = r.text()
    info["comment"] = r.text()
    info["commentEn"] = r.text()

    # ---- 顶点 ----
    nv = r.i32()
    info["vertexCount"] = nv
    for _ in range(nv):
        r.vec(3)      # position
        r.vec(3)      # normal
        r.vec(2)      # uv
        for _ in range(r.add_uv):
            r.vec(4)
        weight_type = r.u8()
        if weight_type == 0:      # BDEF1
            r.idx(r.bone_index_size)
        elif weight_type == 1:    # BDEF2
            r.idx(r.bone_index_size); r.idx(r.bone_index_size); r.f32()
        elif weight_type == 2:    # BDEF4
            for _ in range(4):
                r.idx(r.bone_index_size)
            for _ in range(4):
                r.f32()
        elif weight_type == 3:    # SDEF
            r.idx(r.bone_index_size); r.idx(r.bone_index_size)
            r.f32(); r.vec(3); r.vec(3); r.vec(3)
        elif weight_type == 4:    # QDEF
            for _ in range(4):
                r.idx(r.bone_index_size)
            for _ in range(4):
                r.f32()
        r.f32()       # edge scale

    # ---- 面 ----
    nf = r.i32()
    info["faceIndexCount"] = nf
    info["triangleCount"] = nf // 3
    r.p += nf * r.vertex_index_size

    # ---- 贴图 ----
    nt = r.i32()
    info["textures"] = [r.text() for _ in range(nt)]

    # ---- 材质 ----
    nm = r.i32()
    mats = []
    for _ in range(nm):
        m = {
            "name": r.text(), "nameEn": r.text(),
            "diffuse": r.vec(4), "specular": r.vec(3), "shininess": r.f32(),
            "ambient": r.vec(3),
            "flag": r.u8(),
            "edgeColor": r.vec(4), "edgeSize": r.f32(),
            "textureIndex": r.idx(r.texture_index_size),
            "sphereIndex": r.idx(r.texture_index_size),
            "sphereMode": r.u8(),
            "toonFlag": r.u8(),
        }
        if m["toonFlag"] == 0:
            m["toonIndex"] = r.idx(r.texture_index_size)
        else:
            m["toonIndex"] = r.u8()
        m["memo"] = r.text()
        m["faceCount"] = r.i32()
        mats.append(m)
    info["materials"] = mats

    # ---- 骨骼 ----
    nb = r.i32()
    bones = []
    for _ in range(nb):
        b = {
            "name": r.text(), "nameEn": r.text(),
            "position": r.vec(3), "parent": r.idx(r.bone_index_size),
            "layer": r.i32(), "flag": r.u16(),
        }
        if b["flag"] & 0x0001:   # 连接目标
            b["tail"] = r.idx(r.bone_index_size)
        else:
            b["tailPos"] = r.vec(3)
        if b["flag"] & 0x0100 or b["flag"] & 0x0200:
            b["grantParent"] = r.idx(r.bone_index_size)
            b["grantWeight"] = r.f32()
        if b["flag"] & 0x0400:
            b["fixedAxis"] = r.vec(3)
        if b["flag"] & 0x0800:
            b["localX"] = r.vec(3); b["localZ"] = r.vec(3)
        if b["flag"] & 0x2000:
            b["externalKey"] = r.i32()
        if b["flag"] & 0x0020:
            b["ikTarget"] = r.idx(r.bone_index_size)
            b["ikLoop"] = r.i32()
            b["ikLimitAngle"] = r.f32()
            nlink = r.i32()
            links = []
            for _ in range(nlink):
                lk = {"bone": r.idx(r.bone_index_size), "limit": r.u8()}
                if lk["limit"] == 1:
                    lk["lower"] = r.vec(3); lk["upper"] = r.vec(3)
                links.append(lk)
            b["ikLinks"] = links
        bones.append(b)
    info["bones"] = bones

    # ---- 表情 Morph（★ 关键） ----
    nmorph = r.i32()
    morphs = []
    for _ in range(nmorph):
        mm = {
            "name": r.text(), "nameEn": r.text(),
            "panel": r.u8(), "type": r.u8(),
            "offsetCount": 0, "offsets": [],
        }
        cnt = r.i32()
        mm["offsetCount"] = cnt
        t = mm["type"]
        if t == 1:      # Vertex（顶点位移）—— 最有用，可转 blendshape
            for _ in range(cnt):
                mm["offsets"].append({
                    "index": r.idx(r.vertex_index_size, signed=False),
                    "offset": r.vec(3),
                })
        elif t == 2:    # Bone
            for _ in range(cnt):
                mm["offsets"].append({
                    "index": r.idx(r.bone_index_size),
                    "translation": r.vec(3), "rotation": r.vec(4),
                })
        elif t in (3, 4, 5, 6, 7):   # UV
            for _ in range(cnt):
                mm["offsets"].append({
                    "index": r.idx(r.vertex_index_size, signed=False),
                    "offset": r.vec(4),
                })
        elif t == 8:    # Material
            for _ in range(cnt):
                mm["offsets"].append({
                    "index": r.idx(r.material_index_size),
                    "calcMode": r.u8(),
                    "diffuse": r.vec(4), "specular": r.vec(3), "shininess": r.f32(),
                    "ambient": r.vec(3), "edgeColor": r.vec(4),
                    "edgeSize": r.f32(),
                    "textureTint": r.vec(4), "sphereTint": r.vec(4),
                    "toonTint": r.vec(4),
                })
        elif t == 0:    # Group
            for _ in range(cnt):
                mm["offsets"].append({
                    "index": r.idx(r.morph_index_size),
                    "weight": r.f32(),
                })
        elif t == 9:    # Flip
            for _ in range(cnt):
                mm["offsets"].append({
                    "index": r.idx(r.morph_index_size),
                    "weight": r.f32(),
                })
        elif t == 10:   # Impulse
            for _ in range(cnt):
                mm["offsets"].append({
                    "index": r.idx(r.rigidbody_index_size),
                    "local": r.u8(), "velocity": r.vec(3), "torque": r.vec(3),
                })
        morphs.append(mm)
    info["morphs"] = morphs

    # 剩余的显示枠/刚体/关节不解析（不影响表情）
    return info


def main() -> int:
    if len(sys.argv) < 2:
        root = Path(r"C:\Users\mier\Desktop\deepseek work")
        cands = list(root.rglob("*.pmx"))
        if not cands:
            print("未找到 .pmx 文件")
            return 1
        path = cands[0]
    else:
        path = Path(sys.argv[1])

    print(f"===== {path.name} ({path.stat().st_size/1024/1024:.2f} MB) =====")
    try:
        info = parse(path)
    except Exception as e:
        print(f"解析失败: {e}")
        import traceback
        traceback.print_exc()
        return 1

    print(f"  模型名   : {info['name']}  ({info['nameEn']})")
    print(f"  PMX 版本 : {info['version']}   编码: {info['encoding']}")
    print(f"  顶点数   : {info['vertexCount']:,}")
    print(f"  三角面   : {info['triangleCount']:,}")
    print(f"  材质数   : {len(info['materials'])}")
    print(f"  骨骼数   : {len(info['bones'])}")
    print(f"  表情数   : {len(info['morphs'])}   ★★★")

    print(f"\n--- 全部表情（{len(info['morphs'])} 个） ---")
    by_type: dict[int, list] = {}
    for m in info["morphs"]:
        by_type.setdefault(m["type"], []).append(m)

    for t, lst in sorted(by_type.items()):
        print(f"\n  [{MORPH_NAMES.get(t, t)}] {len(lst)} 个：")
        for m in lst:
            nm = m["name"]
            en = m["nameEn"]
            extra = f"  (英文: {en})" if en and en != nm else ""
            print(f"      {nm:24s} 位移点={m['offsetCount']:5d}{extra}")

    # 关注面部
    print(f"\n--- 面部相关表情（关键词过滤） ---")
    FACE = ("まばたき", "ウィンク", "笑", "怒", "困", "悲", "泣", "照", "にこ",
            "あ", "い", "う", "え", "お", "目", "口", "眉", "歯", "舌",
            "blink", "wink", "smile", "angry", "sad", "mouth", "eye", "brow")
    face_morphs = [m for m in info["morphs"]
                   if any(k in m["name"] or k.lower() in m["nameEn"].lower()
                          for k in FACE)]
    print(f"  命中 {len(face_morphs)} 个：")
    for m in face_morphs:
        print(f"      [{MORPH_NAMES.get(m['type'], m['type'])}] {m['name']:24s} "
              f"位移点={m['offsetCount']:5d}")

    if "--dump-morphs" in sys.argv:
        i = sys.argv.index("--dump-morphs")
        out = Path(sys.argv[i + 1]) if i + 1 < len(sys.argv) else Path("pmx_morphs.json")
        out.write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n完整数据已写入 {out} ({out.stat().st_size/1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
