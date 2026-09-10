"""提取 VRM 内嵌贴图，检查人脸贴图是否为「表情图集」（卡拉彼丘特征）。

卡拉彼丘（Strinova）模型通常没有 blendshape，表情靠**人脸贴图 UV 偏移**实现。
如果人脸贴图是一张大图集，就能用 UV 偏移做真表情。

用法：python vrm_textures.py <file.vrm> [outdir]
"""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path


def read_glb(path: Path):
    with open(path, "rb") as f:
        assert f.read(4) == b"glTF"
        struct.unpack("<II", f.read(8))
        clen, ctype = struct.unpack("<II", f.read(8))
        assert ctype == 0x4E4F534A
        g = json.loads(f.read(clen).decode("utf-8"))
        # 下一个 chunk = BIN
        blen, btype = struct.unpack("<II", f.read(8))
        assert btype == 0x004E4942, f"chunk1 not BIN: {btype:#x}"
        bin_data = f.read(blen)
    return g, bin_data


def main() -> int:
    path = Path(sys.argv[1])
    outdir = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("vrm_tex")
    outdir.mkdir(parents=True, exist_ok=True)

    g, bin_data = read_glb(path)
    bvs = g.get("bufferViews", [])

    print(f"===== {path.name} 贴图 ({len(g.get('images', []))} 张) =====")
    for i, im in enumerate(g.get("images", [])):
        name = im.get("name") or f"img{i}"
        bv = im.get("bufferView")
        if bv is None:
            print(f"  [{i}] {name}: 无 bufferView（外部引用?）")
            continue
        v = bvs[bv]
        off = v.get("byteOffset", 0)
        ln = v["byteLength"]
        data = bin_data[off:off + ln]
        ext = ".png" if (im.get("mimeType") or "").endswith("png") else ".jpg"
        safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in name)
        fp = outdir / f"{i:02d}_{safe}{ext}"
        fp.write_bytes(data)

        # 读图片尺寸
        wh = "?"
        try:
            from PIL import Image
            with Image.open(fp) as img:
                wh = f"{img.width}x{img.height} {img.mode}"
                info = f"  ratio={img.width/img.height:.2f}"
        except Exception as e:
            info = f"  (PIL: {e})"
        print(f"  [{i}] {name:32s} {ln/1024:8.1f} KB  {wh}{info}  -> {fp.name}")

    # 材质 -> 贴图 映射
    print(f"\n--- 材质使用的贴图 ---")
    texs = g.get("textures", [])
    for i, m in enumerate(g.get("materials", [])):
        pbr = m.get("pbrMetallicRoughness") or {}
        base = pbr.get("baseColorTexture")
        bti = base.get("index") if base else None
        src = texs[bti].get("source") if bti is not None and bti < len(texs) else None
        nmm = m.get("name")
        img_name = g["images"][src].get("name") if src is not None and src < len(g["images"]) else None
        uvs = (base.get("extensions") or {}).get("KHR_texture_transform") if base else None
        print(f"  [{i:2d}] {nmm!r:34s} -> img[{src}] {img_name!r}  texXform={uvs}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
