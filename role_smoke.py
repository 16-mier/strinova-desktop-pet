# -*- coding: utf-8 -*-
"""角色三级结构冒烟：扫描/阵营/显示名/默认选择/角色根/主图/语音列表"""
import sys, os, io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

_passed = 0
_failed = 0
_failmsgs = []


def check(name, cond, extra=''):
    global _passed, _failed
    if cond:
        _passed += 1
        print('PASS', name)
    else:
        _failed += 1
        _failmsgs.append('%s  %s' % (name, extra))
        print('FAIL', name, extra)


import pet as pet_mod

# 1) 扫描
roles = pet_mod.list_roles()
check('角色数>=20', len(roles) >= 20, 'got %d' % len(roles))
check('含欧泊/米雪儿', '欧泊/米雪儿' in roles)
check('含乌尔比诺/星绘', '乌尔比诺/星绘' in roles)
check('含剪刀手/艾卡', '剪刀手/艾卡' in roles)
check('含欧泊/伊薇特', '欧泊/伊薇特' in roles)

# 2) 阵营/显示名
check('faction 米雪儿=欧泊', pet_mod.role_faction('欧泊/米雪儿') == '欧泊')
check('display 米雪儿', pet_mod.role_display('欧泊/米雪儿') == '米雪儿')
check('display 星绘', pet_mod.role_display('乌尔比诺/星绘') == '星绘')
check('display 三级形象', pet_mod.role_display('乌尔比诺/星绘/泳装') == '星绘·泳装')
check('character_name 三级', pet_mod.role_character_name('乌尔比诺/星绘/泳装') == '星绘')
check('character_name 两级', pet_mod.role_character_name('乌尔比诺/星绘') == '星绘')

# 3) 默认选择
check('default=星绘路径', pet_mod.default_role_pick(roles) == '乌尔比诺/星绘')

# 4) role_dir / role_root / 主图
d1 = pet_mod.role_dir('欧泊/米雪儿')
check('role_dir 存在', os.path.isdir(d1))
img = pet_mod.role_image(d1)
check('米雪儿主图存在', img is not None and os.path.exists(img[0]))
# 三级形象：root=角色根（去掉形象段）
check('role_root 两级=自身', pet_mod.role_root('乌尔比诺/星绘') == pet_mod.role_dir('乌尔比诺/星绘'))
# 玛德蕾娜 gif
img2 = pet_mod.role_image(pet_mod.role_dir('乌尔比诺/玛德蕾娜'))
check('玛德蕾娜 gif kind', img2 is not None and img2[1] == 'gif')

# 5) 语音列表（星绘应在角色根找到 morning/noon/evening）
audios = pet_mod.list_role_audio('乌尔比诺/星绘')
names = [os.path.basename(a) for _, a in audios]
check('星绘语音含 morning', 'morning.mp3' in names, str(names))
check('星绘语音含 noon', 'noon.mp3' in names, str(names))
check('星绘语音含 evening', 'evening.mp3' in names, str(names))
# 米雪儿暂无语音 → 空列表（不报错）
audios2 = pet_mod.list_role_audio('欧泊/米雪儿')
check('米雪儿语音空不报错', isinstance(audios2, list))

# 6) 语音来源枚举（含路径为多级的情形）: 关键函数不抛错
try:
    pet_mod.list_role_audio('剪刀手/艾卡')
    check('艾卡(多级gif角色)语音枚举', True)
except Exception as e:
    check('艾卡(多级gif角色)语音枚举', False, repr(e))

print('\n==== 结果 ====')
print('共 %d 项，失败 %d 项' % (_passed, _failed))
if _failmsgs:
    print('失败详情：')
    for m in _failmsgs:
        print('  ', m)
sys.exit(1 if _failed else 0)
