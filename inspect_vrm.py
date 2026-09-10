# -*- coding: utf-8 -*-
"""inspect_vrm.py —— 扫描本机所有 .vrm，报告 VRM 版本 / SpringBone / 表情 / 动画。"""
import glob
import json
import os
import struct
import sys


def gltf_json(path):
    with open(path, "rb") as f:
        f.read(12)
        clen, _ = struct.unpack("<II", f.read(8))
        return json.loads(f.read(clen))


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\mier\Desktop\deepseek work"
    seen = set()
    for p in glob.glob(os.path.join(root, "**", "*.vrm"), recursive=True):
        b = os.path.basename(p)
        if b in seen or os.path.getsize(p) < 1000:
            continue
        seen.add(b)
        try:
            j = gltf_json(p)
            ext = j.get("extensions", {})
            used = j.get("extensionsUsed", [])
            vrm1 = ext.get("VRMC_vrm", {})
            vrm0 = ext.get("VRM", {})
            sb10 = ext.get("VRMC_springBone", {}).get("springs")
            sb0 = (vrm0.get("secondaryAnimation") or {}).get("boneGroups")
            meta = (vrm1.get("meta") or vrm0.get("meta") or {})
            preset = (vrm1.get("expressions", {}) or {}).get("preset")
            groups = (vrm0.get("blendShapeMaster") or {}).get("blendShapeGroups")
            print("=== %s (%.1f MB)" % (b, os.path.getsize(p) / 1e6))
            print("    version   : %s" % ("VRM 1.0" if vrm1 else ("VRM 0.x" if vrm0 else "unknown")))
            print("    meta.name : %s" % meta.get("name"))
            if sb10 is not None:
                print("    springBone: VRMC_springBone springs=%d" % len(sb10))
            elif sb0 is not None:
                print("    springBone: VRM0 secondaryAnimation boneGroups=%d" % len(sb0))
            else:
                print("    springBone: *** ABSENT (无头发/裙摆物理) ***")
            if preset:
                print("    expressions(VRM1 preset): %s" % sorted(preset.keys()))
            elif groups:
                print("    expressions(VRM0 blendshapes): %d groups" % len(groups))
            else:
                print("    expressions: none")
            print("    animations: %d" % len(j.get("animations", [])))
            print("    extensionsUsed: %s" % used)
        except Exception as e:
            print("%s ERR %s" % (b, e))


if __name__ == "__main__":
    main()
