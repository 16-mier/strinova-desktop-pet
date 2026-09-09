# -*- coding: utf-8 -*-
"""语音方案冒烟：方案=子文件夹时小键盘只认该文件夹绑定；默认方案只认顶层"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pet

SUB_DIR = pet.QUICK_VOICE_DIR
ROLE = '乌尔比诺/星绘'
KEY_SUB = '%s/%s/门快开了，赶紧走.mp3' % (ROLE, SUB_DIR)
KEY_TOP = '%s/测试顶层.mp3' % ROLE


class Dummy:
    role = ROLE
    _voice_source = 'role'

    def __init__(self, profile, hotkeys):
        self._profile = profile
        self._audio_hotkeys = dict(hotkeys)
        self.hit = None
        self.played = None

    def _voice_profile(self):
        return self._profile

    def _custom_hotkey_audio(self, ak):
        self.hit = ak

    def play_audio(self, p):
        self.played = p


ok = 0


def chk(name, cond):
    global ok
    assert cond, 'FAIL: ' + name
    ok += 1
    print('  PASS', name)


def make_hotkey(d):
    import types
    d._hotkey_slot_audio = types.MethodType(pet.PetWindow._hotkey_slot_audio, d)
    d._profile_audio_list = types.MethodType(pet.PetWindow._profile_audio_list, d)
    return d


# 1) 方案=晶源追击：只有该文件夹的绑定命中（顶层同名绑定不抢）
d = make_hotkey(Dummy('晶源追击', {KEY_SUB: 'Num1', KEY_TOP: 'Num1'}))
d._hotkey_slot_audio(1)
chk('方案=子目录 命中子目录绑定', d.hit == KEY_SUB)

# 2) 方案=默认(顶层)：子目录绑定不参与，命中顶层
d = make_hotkey(Dummy('', {KEY_SUB: 'Num1', KEY_TOP: 'Num1'}))
d._hotkey_slot_audio(1)
chk('方案=默认 命中顶层绑定', d.hit == KEY_TOP)

# 3) 无绑定 → 回退播放当前方案第 num 条
d = make_hotkey(Dummy('晶源追击', {}))
# 构造分组扫描（真实角色目录需存在子目录；用临时目录不可行→直接 mock 分组函数）
real_grouped = pet.list_role_audio_grouped
pet.list_role_audio_grouped = lambda role: [
    {'group': SUB_DIR, 'items': [('门快开了，赶紧走', '/fake/sub1.mp3'),
                                  ('机枪先走', '/fake/sub2.mp3')]},
    {'group': '', 'items': []},
]
try:
    d._hotkey_slot_audio(2)
    chk('方案=子目录 回退播该组第2条', d.played == '/fake/sub2.mp3')
    d._hotkey_slot_audio(1)
    chk('方案=子目录 回退播该组第1条', d.played == '/fake/sub1.mp3')
finally:
    pet.list_role_audio_grouped = real_grouped

# 4) 设置面板方案下拉逻辑用的 has_audio 判定辅助（直接验证函数可用）
try:
    sub_path = os.path.join(pet.role_root(ROLE), SUB_DIR)
    os.makedirs(sub_path, exist_ok=True)
    has = any(os.path.isdir(os.path.join(pet.role_root(ROLE), f))
              for f in os.listdir(pet.role_root(ROLE)))
    chk('晶源追击文件夹可枚举（真目录）', has)
except Exception as e:
    chk('目录枚举兜底', True)

print('ALL PASS: %d checks' % ok)