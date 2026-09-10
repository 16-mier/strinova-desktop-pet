import json, struct
from pathlib import Path
def gj(p):
    b = Path(p).read_bytes(); off = 12
    while off < len(b):
        ln, ty = struct.unpack_from('<II', b, off); off += 8
        if ty == 0x4E4F534A: return json.loads(b[off:off+ln].decode('utf-8'))
        off += ln
for name in ['michelle_phys.vrm','michelle_expr.vrm']:
    g = gj(Path('web3d/models')/name)
    print(f"===== {name} =====")
    for i, m in enumerate(g['meshes']):
        tn = (m.get('extras') or {}).get('targetNames')
        if tn:
            print(f"  mesh[{i}] name={m.get('name')!r} targetNames({len(tn)}): {tn}")
    # 看看 VRM 扩展里 preset 的 binds 指向哪些 index
    ex = g['extensions']['VRMC_vrm']['expressions']
    for grp in ('preset','custom'):
        d = ex.get(grp) or {}
        if not d: continue
        print(f"  -- {grp} --")
        for k, v in d.items():
            binds = v.get('morphTargetBinds') or []
            idxs = [b.get('index') for b in binds]
            print(f"     {k:12s} binds={len(binds)} idx={idxs}")
    print()
