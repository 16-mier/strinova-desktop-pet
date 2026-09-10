# -*- coding: utf-8 -*-
"""提取 VRM 的 VRMC_springBone 参数分布 + humanoid 骨骼清单，用于调参参考。"""
import json, struct, sys, collections, io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

path = sys.argv[1] if len(sys.argv) > 1 else r'C:\Users\mier\Desktop\deepseek work\strinova-desktop-pet\web3d\models\michelle_phys.vrm'

with open(path, 'rb') as f:
    data = f.read()

magic, ver, length = struct.unpack('<III', data[:12])
assert magic == 0x46546C67, 'not a glb'
off = 12
gltf = None
while off < length:
    clen, ctype = struct.unpack('<II', data[off:off + 8])
    chunk = data[off + 8: off + 8 + clen]
    if ctype == 0x4E4F534A:
        gltf = json.loads(chunk.decode('utf-8'))
        break
    off += 8 + clen

print('=== 文件 ===')
print('size = %.2f MB' % (len(data) / 1024 / 1024))
print('generator =', gltf.get('asset', {}).get('generator'))
ext = gltf.get('extensions', {})
print('extensionsUsed =', gltf.get('extensionsUsed'))

nodes = gltf.get('nodes', [])
print('\n=== 版本 / meta ===')
vrm_ext = ext.get('VRMC_vrm')
if vrm_ext:
    print('VRMC_vrm specVersion =', vrm_ext.get('specVersion'))
    print('meta =', json.dumps(vrm_ext.get('meta', {}), ensure_ascii=False)[:600])

print('\n=== humanoid ===')
h = (vrm_ext or {}).get('humanoid', {})
hb = h.get('humanBones', {})
print('humanBones 数量 =', len(hb))
groups = collections.defaultdict(list)
for k, v in hb.items():
    groups[k].append(v.get('node'))
print('骨骼名:', sorted(hb.keys()))

sb = ext.get('VRMC_springBone')
if not sb:
    print('\n>>> 没有 VRMC_springBone')
    sys.exit(0)

print('\n=== VRMC_springBone 概览 ===')
print('specVersion =', sb.get('specVersion'))
colliders = sb.get('colliders', [])
cgroups = sb.get('colliderGroups', [])
springs = sb.get('springs', [])
print('colliders =', len(colliders), ' colliderGroups =', len(cgroups), ' springs =', len(springs))
print('joint 总数 =', sum(len(s.get('joints', [])) for s in springs))
print('有 center 的 spring 数 =', sum(1 for s in springs if s.get('center') is not None))

print('\n=== collider shape ===')
shapes = collections.Counter()
radii = []
for c in colliders:
    sh = c.get('shape', {})
    if 'sphere' in sh:
        shapes['sphere'] += 1
        radii.append(sh['sphere'].get('radius'))
    elif 'capsule' in sh:
        shapes['capsule'] += 1
        radii.append(sh['capsule'].get('radius'))
    nm = nodes[c['node']].get('name', '?') if 'node' in c else '?'
    print('  %-28s %s r=%s' % (nm, list(sh.keys())[0], radii[-1] if radii else '?'))
if radii:
    print('radius: min=%.4f max=%.4f' % (min(radii), max(radii)))

def stat(vals, label):
    if not vals:
        print('  %-14s (无)' % label)
        return
    vals = sorted(vals)
    n = len(vals)
    print('  %-14s n=%3d  min=%.4f  p25=%.4f  中位=%.4f  p75=%.4f  max=%.4f  均值=%.4f'
          % (label, n, vals[0], vals[n // 4], vals[n // 2], vals[3 * n // 4], vals[-1],
             sum(vals) / n))

print('\n=== 关节参数分布（所有 joint 汇总）===')
allS, allG, allD, allH = [], [], [], []
for s in springs:
    for j in s.get('joints', []):
        if 'stiffness' in j: allS.append(j['stiffness'])
        if 'gravityPower' in j: allG.append(j['gravityPower'])
        if 'dragForce' in j: allD.append(j['dragForce'])
        if 'hitRadius' in j: allH.append(j['hitRadius'])
stat(allS, 'stiffness')
stat(allG, 'gravityPower')
stat(allD, 'dragForce')
stat(allH, 'hitRadius')

print('\n=== 按链（spring）逐条 ===')
print('%-3s %-34s %5s %9s %9s %9s %9s %s' % ('#', '根部节点名', 'joints', 'stiff', 'gravPow', 'drag', 'hitR', 'collGrp/center'))
for i, s in enumerate(springs):
    js = s.get('joints', [])
    root = nodes[js[0]['node']].get('name', '?') if js else '?'
    st = js[0].get('stiffness', '-') if js else '-'
    gp = js[0].get('gravityPower', '-') if js else '-'
    df = js[0].get('dragForce', '-') if js else '-'
    hr = js[0].get('hitRadius', '-') if js else '-'
    cg = s.get('colliderGroups', [])
    ct = s.get('center')
    print('%-3d %-34s %5d %9s %9s %9s %9s cg=%s center=%s'
          % (i, root[:34], len(js), st, gp, df, hr, cg, ct))

print('\n=== 各 spring 内 joint 参数是否一致 ===')
for i, s in enumerate(springs):
    js = s.get('joints', [])
    for key in ('stiffness', 'gravityPower', 'dragForce'):
        vals = [j.get(key) for j in js if key in j]
        if len(set(vals)) > 1:
            root = nodes[js[0]['node']].get('name', '?')
            print('  spring %d (%s) 的 %s 不一致: %s' % (i, root, key, vals))
print('(以上无输出 = 每条链内参数统一)')

print('\n=== 权重最大的 20 个 node（找出是什么在用 springBone）===')
print('springs 涉及的 node 名（前 60 个唯一名）:')
seen = []
for s in springs:
    for j in s.get('joints', []):
        nm = nodes[j['node']].get('name', '?')
        if nm not in seen:
            seen.append(nm)
for n in seen[:60]:
    print('   ', n)
print('总唯一节点数 =', len(seen))
