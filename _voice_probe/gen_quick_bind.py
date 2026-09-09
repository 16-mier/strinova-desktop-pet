# -*- coding: utf-8 -*-
"""把 6 条快捷语音绑定到小键盘 Num1~Num6（数据目录 pet_config.json）。
保留已有绑定（如 __common__ 的 Num1/Num2）。
"""
import json
import os

DATA_DIR = r'C:\Users\mier\Desktop\卡丘简易桌宠数据'
CFG = os.path.join(DATA_DIR, 'pet_config.json')

# 与 gen_quick_voices 一致的角色清单（从数据目录扫描）
CHARS = r'C:\Users\mier\Desktop\卡丘简易桌宠数据\assets\characters'

# 与 gen_quick_voices 一致的 6 条语音名（文件名 = 语音名）
VOICE_NAMES = [
    '门快开了，赶紧走',
    '先不要踩检查点，等等后面的人',
    '先阻击一下，保护断后的人',
    '所有人和螳螂距离一个冲刺距离',
    '我来开门，其他人垫后',
    '机枪先走，到点再架枪',
]

def scan_roles():
    out = []
    for faction in sorted(os.listdir(CHARS)):
        fd = os.path.join(CHARS, faction)
        if not os.path.isdir(fd):
            continue
        for role in sorted(os.listdir(fd)):
            if os.path.isdir(os.path.join(fd, role)):
                out.append((faction, role))
    return out

def main():
    with open(CFG, 'r', encoding='utf-8') as f:
        cfg = json.load(f)
    hotkeys = dict(cfg.get('audio_hotkeys', {}))
    added = 0
    missing = []
    for faction, role in scan_roles():
        for i, vname in enumerate(VOICE_NAMES, 1):
            key = '%s/%s/%s.mp3' % (faction, role, vname)
            mp3 = os.path.join(DATA_DIR, 'assets', 'characters', faction, role, vname + '.mp3')
            if not os.path.exists(mp3):
                missing.append(key)
                continue
            if hotkeys.get(key) != 'Num%d' % i:
                hotkeys[key] = 'Num%d' % i
                added += 1
    cfg['audio_hotkeys'] = hotkeys
    with open(CFG, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    print('bind: added %d, total %d, missing %d' % (added, len(hotkeys), len(missing)))
    for m in missing:
        print('  MISSING:', m)

if __name__ == '__main__':
    main()
