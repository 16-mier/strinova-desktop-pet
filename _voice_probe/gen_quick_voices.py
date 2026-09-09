# -*- coding: utf-8 -*-
"""生成「晶源追击」快捷语音：每角色 6 条克隆语音（BreezeTTS 本地服务）。
- 女角色：情绪多一点；男角色（白墨/令/信）：严肃点
- 输出：<角色目录>/快捷1.mp3 ~ 快捷6.mp3（数据目录 + 源码 assets 双写）
- 用法：python gen_quick_voices.py [--sample] [--all]  （--sample 只跑 星绘/白墨 第1条验证）
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

BASE_URL = 'http://127.0.0.1:8080/v1'
MODEL = 'breeze-tts-clone'
REFS_DIR = r'C:\Users\mier\Desktop\deepseek work\breeze-tts-local\audio-cpp\references\refs_en'

DATA_CHARS = r'C:\Users\mier\Desktop\卡丘简易桌宠数据\assets\characters'
SRC_CHARS = r'C:\Users\mier\Desktop\deepseek work\strinova-desktop-pet\assets\characters'

# 角色中文名 → 参考音频英文名（与 pet.py ROLE_EN_NAMES 一致）
ROLE_EN = {
    '米雪儿': 'MicheleLee', '信': 'Nobunaga', '心夏': 'Kokona', '伊薇特': 'Yvette',
    '芙拉薇娅': 'Flavia', '忧雾': 'Yugiri', '蕾欧娜': 'Leona', '千代': 'Chiyo',
    '明': 'Ming', '拉薇': 'Lawine', '梅瑞狄斯': 'Meredith', '令': 'Reiichi',
    '香奈美': 'Kanami', '艾卡': 'Eika', '诺诺': 'Nora', '珐格兰丝': 'Fragrans',
    '玛拉': 'Mara', '奥黛丽': 'AudreyGrove', '玛德蕾娜': 'MaddelenaLeary',
    '绯莎': 'Fuchsia', '星绘': 'Celestia', '白墨': 'BaiMo',
    '加拉蒂亚': 'GalateaLeary', '汐': 'Cielle',
}
MALE_ROLES = {'白墨', '令', '信'}  # 男角色：严肃

# 晶源追击 6 条快捷语音：(文件名, 朗读文本)
# 文件名 = 语音名（用户原句）；文本 = 原句口语 + 句末标点（标点=停顿，读起来自然）
LINES = [
    ('门快开了，赶紧走', '门快开了，赶紧走！'),
    ('先不要踩检查点，等等后面的人', '先不要踩检查点，等等后面的人。'),
    ('先阻击一下，保护断后的人', '先阻击一下，保护断后的人。'),
    ('所有人和螳螂距离一个冲刺距离', '所有人和螳螂距离一个冲刺距离。'),
    ('我来开门，其他人垫后', '我来开门，其他人垫后！'),
    ('机枪先走，到点再架枪', '机枪先走，到点再架枪。'),
]

FEMALE_INSTR = '语气急切带催促感，语速稍快，声音清亮上扬，像战斗中提醒队友，干脆利落，有精神不拖沓。'
MALE_INSTR = '语气沉稳严肃，语速适中偏慢，像指挥官下达命令，冷静果断，字字清晰，不带多余情绪。'

# 跳过已生成（断点续跑）
def synth(text, ref_wav, ref_txt, instr, out_wav, retries=2):
    payload = {
        'model': MODEL,
        'input': text,
        'response_format': 'wav',
        'voice_ref': ref_wav,
        'reference_text': ref_txt,
        'instructions': instr,
    }
    body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    last_err = None
    for i in range(retries + 1):
        try:
            req = urllib.request.Request(BASE_URL + '/audio/speech', data=body, method='POST')
            req.add_header('Content-Type', 'application/json')
            with urllib.request.urlopen(req, timeout=120) as r:
                data = r.read()
            if not data:
                raise RuntimeError('空响应')
            with open(out_wav, 'wb') as f:
                f.write(data)
            return True
        except Exception as e:
            last_err = e
            time.sleep(1.5)
    print('  !! 合成失败: %s' % last_err)
    return False


def to_mp3(wav_path, mp3_path):
    try:
        subprocess.run(
            ['ffmpeg', '-y', '-i', wav_path, '-ac', '1', '-ar', '24000', '-b:a', '96k', mp3_path],
            capture_output=True, timeout=60, check=True)
        os.remove(wav_path)
        return True
    except Exception as e:
        print('  !! mp3 转换失败: %s' % e)
        return False


def scan_roles():
    """扫描数据目录角色：返回 [(阵营, 角色名)]"""
    out = []
    for faction in sorted(os.listdir(DATA_CHARS)):
        fd = os.path.join(DATA_CHARS, faction)
        if not os.path.isdir(fd):
            continue
        for role in sorted(os.listdir(fd)):
            rd = os.path.join(fd, role)
            if os.path.isdir(rd):
                out.append((faction, role))
    return out


def main():
    sample = '--sample' in sys.argv
    roles = scan_roles()
    if sample:
        roles = [r for r in roles if r[1] in ('星绘', '白墨')]
    total = len(roles) * len(LINES)
    done = 0
    fail = []
    t0 = time.time()
    for faction, role in roles:
        en = ROLE_EN.get(role)
        if not en:
            print('[跳过] %s：无英文参考' % role)
            continue
        ref_wav = os.path.join(REFS_DIR, en + '.wav')
        ref_txt = os.path.join(REFS_DIR, en + '.txt')
        if not os.path.exists(ref_wav) or not os.path.exists(ref_txt):
            print('[跳过] %s：参考音频缺失' % role)
            continue
        with open(ref_txt, 'r', encoding='utf-8') as f:
            ref_text = f.read().strip()
        instr = MALE_INSTR if role in MALE_ROLES else FEMALE_INSTR
        for i, (fname, text) in enumerate(LINES, 1):
            mp3 = os.path.join(DATA_CHARS, faction, role, fname + '.mp3')
            if os.path.exists(mp3) and os.path.getsize(mp3) > 1000:
                done += 1
                continue
            wav_tmp = mp3[:-4] + '.tmp.wav'
            if synth(text, ref_wav, ref_text, instr, wav_tmp):
                if to_mp3(wav_tmp, mp3):
                    # 双写：源码 assets
                    src_mp3 = os.path.join(SRC_CHARS, faction, role, fname + '.mp3')
                    try:
                        os.makedirs(os.path.dirname(src_mp3), exist_ok=True)
                        with open(mp3, 'rb') as a, open(src_mp3, 'wb') as b:
                            b.write(a.read())
                    except Exception as e:
                        print('  !! 源码双写失败: %s' % e)
                    done += 1
                else:
                    fail.append((role, fname))
            else:
                fail.append((role, fname))
            el = time.time() - t0
            speed = done / el if el > 0 else 0
            eta = (total - done) / speed / 60 if speed > 0 else 0
            print('[%d/%d] %s/%s %s  (%.1f 条/分, 剩余约 %.0f 分)' % (
                done, total, role, fname, 'OK' if os.path.exists(mp3) else 'FAIL', speed * 60, eta))
    print('完成: %d/%d；失败 %d 条' % (done, total, len(fail)))
    for r, f in fail:
        print('  失败: %s %s' % (r, f))


if __name__ == '__main__':
    main()
