# -*- coding: utf-8 -*-
"""补全 VRM 的表情定义（GLB 后处理）

## 为什么需要这一步
Blender 的 VRM Addon 在 `assign_vrm1_expressions_from_mmd` 里只会把 MMD 形态键
映射到 VRM 的【18 个预设表情】（aa/ee/ih/oh/ou/blink/happy/angry/sad/surprised…），
模型自带的日文形态键（ω / ∧ / じと目 / てへぺろ / 歯無し上 …）不会被注册，
于是从 41 个形态键里只剩 14 个能用。

但这些形态键【本身还在 mesh 里】（glTF 的 mesh.extras.targetNames 有全部 41 个名字，
primitive.targets 也有对应的 41 组数据），只是没人把它们接到 VRM 表情上。

所以这里直接改 GLB 的 JSON chunk，往 VRMC_vrm.expressions 里补 custom 表情，
以及把 lookLeft / lookRight / relaxed 这几个空的预设填上。
形态数据一个字节都不用动。

## 用法
  python tools/pmx_to_vrm/add_expressions.py <vrm路径>
"""
from __future__ import annotations

import json
import shutil
import struct
import sys
from pathlib import Path

# 形态键名(idx) → 要注册成的 VRM 表情名
#
# 左边是 Blender 导出后 targetNames 里的原始名字，右边是 VRM 表情名。
# 预设补全（原本 binds=0 的三个）：
#   左斜(13)/右斜(14) 是眼球左右，正好对应 lookLeft/lookRight
#   口角上げ(6) 是嘴角上扬，用作 relaxed
# 其余按原名注册成 custom（保留日文名，菜单里能直接认出来）
CUSTOM_BY_INDEX = {
    5: 'にやり',            # 坏笑
    6: '口角上げ',          # 嘴角上扬
    7: 'ω',                # 嘴型 ω
    8: 'ワ',                # 张嘴
    9: '口横広げ',          # 嘴横向拉宽
    10: 'ん',               # 闭口鼻音
    11: '口角下げ',         # 嘴角下垂
    12: '∧',               # 嘴型 ∧
    15: 'ぺろっ',           # 吐舌
    16: 'てへぺろ',         # 吐舌卖萌
    17: 'てへぺろ２',
    18: '歯無し上',         # 上牙隐藏
    19: '歯無し下',         # 下牙隐藏
    24: 'ウィンク２',
    25: 'ｳｨﾝｸ２右',
    27: 'じと目',           # 半眯眼（无语脸）
    29: '瞳小',             # 瞳孔缩小
    30: '目后',             # 眼神躲闪
    31: '恐ろしい子！',
    32: 'ハイライト消',      # 高光消失（黑化）
    35: '平',               # 平静
    36: '真面目',           # 认真
    37: '困る',             # 困扰
    39: '前',               # 视线向前
    40: '消',               # 消失（闭眼+无高光）
}

# 预设补全：预设名 → 形态键 index
PRESET_FIX = {
    'lookLeft': 13,     # 左斜
    'lookRight': 14,    # 右斜
    'relaxed': 6,       # 口角上げ
}


def read_glb(path: Path):
    """返回 (json_dict, json_chunk_bytes, [(type, bytes), ...])"""
    b = path.read_bytes()
    if b[:4] != b'glTF':
        raise SystemExit(f'不是 GLB 文件: {path}')
    magic, version, total = struct.unpack_from('<4sII', b, 0)
    chunks = []
    off = 12
    while off < len(b):
        ln, ty = struct.unpack_from('<II', b, off)
        off += 8
        chunks.append((ty, b[off:off + ln]))
        off += ln
    gj = None
    for ty, data in chunks:
        if ty == 0x4E4F534A:
            gj = json.loads(data.decode('utf-8'))
            break
    if gj is None:
        raise SystemExit('GLB 里没有 JSON chunk')
    return gj, chunks


def write_glb(path: Path, gj: dict, chunks: list):
    """按 GLB 规范重写：JSON chunk 用空格补齐，BIN chunk 用 0 补齐"""
    payload = json.dumps(gj, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    pad = (-len(payload)) % 4
    payload += b' ' * pad
    out = [(0x4E4F534A, payload)]
    for ty, data in chunks:
        if ty == 0x4E4F534A:
            continue
        p = (-len(data)) % 4
        out.append((ty, data + b'\x00' * p))
    body = b''
    for ty, data in out:
        body += struct.pack('<II', len(data), ty) + data
    header = struct.pack('<4sII', b'glTF', 2, 12 + len(body))
    path.write_bytes(header + body)


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    path = Path(sys.argv[1])
    if not path.exists():
        raise SystemExit(f'文件不存在: {path}')

    gj, chunks = read_glb(path)

    # 形态键总数（用于校验 index 不越界）
    n_targets = 0
    names = None
    for m in gj.get('meshes', []):
        tn = (m.get('extras') or {}).get('targetNames')
        if tn:
            names = tn
        for pr in m.get('primitives', []):
            n_targets = max(n_targets, len(pr.get('targets') or []))

    vrm = gj.setdefault('extensions', {}).setdefault('VRMC_vrm', {})
    ex = vrm.setdefault('expressions', {})
    preset = ex.setdefault('preset', {})
    custom = ex.setdefault('custom', {})

    added_preset, added_custom, skipped = [], [], []

    # 1) 补预设
    for k, idx in PRESET_FIX.items():
        cur = preset.get(k) or {}
        if cur.get('morphTargetBinds'):
            continue
        if idx >= n_targets:
            skipped.append(f'preset:{k}(idx{idx}越界)')
            continue
        preset[k] = {
            'morphTargetBinds': [{'index': idx, 'weight': 1.0}],
        }
        added_preset.append(f'{k}->{names[idx] if names and idx < len(names) else idx}')

    # 2) 补自定义表情（同名已存在就跳过，保证可重复执行）
    for idx, name in sorted(CUSTOM_BY_INDEX.items()):
        if name in custom and (custom[name] or {}).get('morphTargetBinds'):
            continue
        if idx >= n_targets:
            skipped.append(f'custom:{name}(idx{idx}越界)')
            continue
        custom[name] = {
            'morphTargetBinds': [{'index': idx, 'weight': 1.0}],
        }
        added_custom.append(name)

    if not added_preset and not added_custom:
        print('[SKIP] 表情定义已经是完整的，无需修改')
        return 0

    # 备份一次（只备份第一个）
    bak = path.with_suffix(path.suffix + '.bak')
    if not bak.exists():
        shutil.copy2(path, bak)
        print(f'[INFO] 已备份原文件 → {bak.name}')

    write_glb(path, gj, chunks)

    print(f'[OK] 补全表情: 预设 +{len(added_preset)} 个, 自定义 +{len(added_custom)} 个')
    print(f'     预设: {added_preset}')
    print(f'     自定义: {added_custom}')
    if skipped:
        print(f'     [WARN] 跳过: {skipped}')
    total = len([k for k, v in preset.items() if (v or {}).get('morphTargetBinds')]) \
        + len([k for k, v in custom.items() if (v or {}).get('morphTargetBinds')])
    print(f'     现在可用表情合计: {total} 个')
    return 0


if __name__ == '__main__':
    sys.exit(main())
