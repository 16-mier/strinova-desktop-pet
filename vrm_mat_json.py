"""完整打印 VRM 材质 JSON（定位脸部材质的所有纹理通道）。

用法：python vrm_mat_json.py <file.vrm> [out.json]
"""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path


def main() -> int:
    path = Path(sys.argv[1])
    with open(path, "rb") as f:
        assert f.read(4) == b"glTF"
        struct.unpack("<II", f.read(8))
        clen, ctype = struct.unpack("<II", f.read(8))
        g = json.loads(f.read(clen).decode("utf-8"))

    out = []
    for i, m in enumerate(g.get("materials", [])):
        out.append(f"===== [{i}] {m.get('name')} =====")
        out.append(json.dumps(m, ensure_ascii=False, indent=2))

    txt = "\n".join(out)
    target = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("vrm_mats.json")
    target.write_text(txt, encoding="utf-8")
    out_s = txt[:6000]
    import io, os
    os.system("")
    print(out_s if len(txt) <= 6000 else f"written {target} ({len(txt):,} chars)")
    return 0


if __name__ == "__main__":
    sys.exit(main())