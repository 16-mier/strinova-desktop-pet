# -*- coding: utf-8 -*-
"""验证：音频文件夹分组 + 音频键子目录 + 快捷键前缀匹配（新功能冒烟）"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pet

ok = 0


def chk(name, cond):
    global ok
    assert cond, 'FAIL: ' + name
    ok += 1
    print('  PASS', name)


ROLE = '乌尔比诺/星绘'
rd = pet.role_root(ROLE)
sub = os.path.join(rd, pet.QUICK_VOICE_DIR)
os.makedirs(sub, exist_ok=True)
test_mp3 = os.path.join(sub, '冒烟测试.mp3')
with open(test_mp3, 'wb') as f:
    f.write(b'RIFF' + b'\x00' * 200)  # 占位音频（列表只认扩展名）

try:
    # 1) 分组扫描：晶源追击组在最前，空组保留；顶层组最后
    groups = pet.list_role_audio_grouped(ROLE)
    names = [g['group'] for g in groups]
    print('  组顺序:', names)
    chk('晶源追击组在最前', names[0] == pet.QUICK_VOICE_DIR)
    chk('顶层组最后', names[-1] == '')
    qg = groups[0]
    chk('晶源追击组含测试音频', any('冒烟测试' in os.path.basename(p) for _, p in qg['items']))

    # 2) 平铺 list_role_audio 兼容
    flat = pet.list_role_audio(ROLE)
    chk('平铺包含子目录音频', any('冒烟测试' in os.path.basename(p) for _, p in flat))

    # 3) 音频键保留子目录（实例方法）
    class FakePet:
        role = ROLE
        def _audio_key(self, role, path):
            return pet.PetWindow._audio_key(self, role, path)
    fp = FakePet()
    key = fp._audio_key(ROLE, test_mp3)
    print('  音频键:', key)
    chk('音频键含晶源追击目录', key == ROLE + '/' + pet.QUICK_VOICE_DIR + '/冒烟测试.mp3')

    # 4) 快捷键前缀匹配（模拟 _hotkey_slot_audio 的 startswith 逻辑）
    hotkeys = {
        key: 'Num1',
        '__common__/06_奈斯！.mp3': 'Num1',
    }
    prefix = ROLE
    hits = [k for k, v in hotkeys.items() if v == 'Num1' and k.startswith(prefix + '/')]
    chk('前缀匹配命中子目录绑定', hits == [key])

    # 5) _custom_hotkey_audio 路径解析：rsplit 后 role_name 含晶源追击目录，
    #    role_dir 多级拼接正好命中文件（无需额外改动）
    role_name, fname = key.rsplit('/', 1)
    p1 = os.path.join(pet.role_dir(role_name), fname)
    chk('播放路径解析命中角色根', os.path.exists(p1))
finally:
    try:
        os.remove(test_mp3)
    except Exception:
        pass

print('ALL PASS: %d checks' % ok)
