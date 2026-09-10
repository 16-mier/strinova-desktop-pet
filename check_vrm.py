import json, struct, sys
from pathlib import Path

def read_glb_json(p):
    b = Path(p).read_bytes()
    assert b[:4] == b'glTF', "not a glb"
    off = 12
    while off < len(b):
        ln, ty = struct.unpack_from('<II', b, off)
        off += 8
        if ty == 0x4E4F534A:   # JSON
            return json.loads(b[off:off+ln].decode('utf-8'))
        off += ln
    raise RuntimeError('no json chunk')

for name in ['michelle_phys.vrm', 'michelle.vrm', 'michelle_expr.vrm']:
    p = Path('web3d/models') / name
    if not p.exists():
        print(f"{name}: 不存在"); continue
    try:
        g = read_glb_json(p)
    except Exception as e:
        print(f"{name}: 读取失败 {e}"); continue
    ext = g.get('extensions', {})
    sb = ext.get('VRMC_springBone')
    nodes = g.get('nodes', [])
    hairish = [n.get('name','') for n in nodes
               if any(str(n.get('name','')).startswith(x) for x in
                      ('hair','qun','ponytail','cloak','earring','weiba'))]
    print(f"=== {name}  ({p.stat().st_size/1024/1024:.2f} MB) ===")
    print(f"  extensionsUsed : {g.get('extensionsUsed')}")
    print(f"  VRMC_springBone: {'有' if sb else '无'}")
    if sb:
        # ⚠ VRM 1.0 的 joints 是【嵌在每个 spring 里】的，顶层并没有 joints 键。
        #   一开始我只查顶层 sb['joints']，读到 0 就误判成"没有物理"，
        #   白折腾了一轮排查导出器。
        springs = sb.get('springs', [])
        n_joints = sum(len(sp.get('joints', [])) for sp in springs)
        print(f"    specVersion  : {sb.get('specVersion')}")
        print(f"    colliders    : {len(sb.get('colliders', []))}")
        print(f"    colliderGroup: {len(sb.get('colliderGroups', []))}")
        print(f"    springs      : {len(springs)}")
        print(f"    joints(合计) : {n_joints}")
        for sp in springs[:3]:
            js = sp.get('joints', [])
            extra = ""
            if js:
                extra = (f"  首个: stiffness={js[0].get('stiffness')} "
                         f"drag={js[0].get('dragForce')} "
                         f"grav={js[0].get('gravityPower')}")
            print(f"      · name={sp.get('name')!r} joints={len(js)}{extra}")
    print(f"  nodes={len(nodes)}  悬垂骨骼={len(hairish)}")
    print(f"  meshes={len(g.get('meshes',[]))}  materials={len(g.get('materials',[]))}")
    # 检查表情是否还在
    vrm = ext.get('VRMC_vrm', {})
    exprs = vrm.get('expressions', {})
    print(f"  VRM spec={vrm.get('specVersion')} 表情组={list(exprs.keys())[:6]}")
    print()
