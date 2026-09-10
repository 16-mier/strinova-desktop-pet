import json, struct
from pathlib import Path

def gj(p):
    b = Path(p).read_bytes(); off = 12
    while off < len(b):
        ln, ty = struct.unpack_from('<II', b, off); off += 8
        if ty == 0x4E4F534A: return json.loads(b[off:off+ln].decode('utf-8'))
        off += ln

for name in ['michelle_phys.vrm','michelle.vrm','michelle_expr.vrm']:
    g = gj(Path('web3d/models')/name)
    vrm = g['extensions']['VRMC_vrm']
    ex = vrm.get('expressions', {})
    preset = list((ex.get('preset') or {}).keys())
    custom = list((ex.get('custom') or {}).keys())
    # 统计有多少 mesh 带 morph targets
    morph_meshes = sum(1 for m in g['meshes'] for pr in m['primitives'] if pr.get('targets'))
    target_count = sum(len(pr.get('targets', [])) for m in g['meshes'] for pr in m['primitives'])
    print(f"=== {name} ===")
    print(f"  preset 表情 ({len(preset)}): {preset}")
    print(f"  custom 表情 ({len(custom)}): {custom}")
    print(f"  带 morph 的 primitive: {morph_meshes}, targets 总数: {target_count}")
    print(f"  lookAt: {'有' if vrm.get('lookAt') else '无'}   "
          f"humanoid 骨骼: {len(vrm.get('humanoid',{}).get('humanBones',{}))}")
    print()
