# pet.py —— 独立 Win11 桌面桌宠（PyQt6 版）
# 功能：透明置顶浮窗、点按播音（星绘早/午/晚 + 白墨冲刺）、按压弹性动画、拖动贴边、托盘、角色可扩展。
# 菜单：悬停时右上角三横按钮 → 深色圆角菜单（切角色 / 退出）；托盘同款菜单。
# 技术：PyQt6（python 3.14），per-pixel alpha 透明，打包成单文件 exe。
#
# 资源：assets/characters/<角色>/image.png（或 .gif 动图）+ 语音 mp3。
#   - 星绘:  image.png + morning/noon/evening.mp3（按当前时间选）
#   - 白墨:  image.png + sprint.mp3
#   - 艾卡:  .gif 动图（自动播放，动图角色支持透明）+ 语音
#   - 其他:  image.png/.gif + click.mp3（优先）或 morning.mp3
#
# 交互：左键点按=播音（按下压扁回弹），拖动=移动(贴边)，左键拖动超过阈值不算点击；
#       鼠标悬停右上角出现 ☰ 按钮 → 点击弹菜单（切换角色 / 退出）。
import sys
import os
import math
import json
import time
import shutil
import threading
import ctypes
from datetime import datetime
from ctypes import wintypes

from PyQt6.QtCore import Qt, QTimer, QPoint, QRect, QUrl, QEvent, QObject
from PyQt6.QtGui import QPixmap, QIcon, QAction, QActionGroup, QCursor, QPainter, QColor, QPen, QImage, QMovie
from PyQt6.QtWidgets import (
    QApplication, QWidget, QMenu,
    QSystemTrayIcon,
)
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput

# UIAutomation（可选）：用于智能输入判定兜底 —— 识别 Chromium/Electron 应用
# （DSH Desktop、新版 QQ/微信等）内部输入框。这些窗口 hwndCaret/焦点类名都拿不到，
# 但 UIA 能查焦点元素是否支持 TextPattern → 通用识别"正在输入"。缺失时自动降级。
try:
    import comtypes
    import comtypes.client as _cc
    from comtypes.gen import UIAutomationClient as _UIA
    comtypes.CoInitialize()
    _UIA_AUTO = _cc.CreateObject(_UIA.CUIAutomation, interface=_UIA.IUIAutomation)
    HAS_UIA = True
except Exception as _uia_e:
    _UIA_AUTO = None
    HAS_UIA = False

# sounddevice / soundfile：绑定麦克风直出用（可选，缺失则回退 QMediaPlayer）
try:
    import sounddevice as _sd
    import soundfile as _sf
    import numpy as _np
    HAS_SD = True
except Exception:
    _sd = None
    _sf = None
    _np = None
    HAS_SD = False

# 设置面板（独立窗口，替代旧弹出菜单）
try:
    import settings_panel as _panel_mod
    _panel_mod.bind_pet_module(sys.modules[__name__])  # 注入模块引用供面板调用工具函数
    HAS_PANEL = True
except Exception as _e:
    _panel_mod = None
    HAS_PANEL = False
    print('settings_panel import fail:', _e)

# AI 对话 + TTS（云端 edge-tts / 本地 SAPI）——可选模块，缺失不影响桌宠本体
try:
    import ai_chat as _ai_mod
    _ai_mod.bind_pet_module(sys.modules[__name__])
    HAS_AI = True
except Exception as _e:
    _ai_mod = None
    HAS_AI = False
    print('ai_chat import fail:', _e)


PET_VERSION = "1.6.0"
DEFAULT_ROLE = "星绘"
BASE_SIZE = 200

# ── 用户数据目录 ─────────────────────────────────────────────
# 打包后所有可写数据（pet_config.json / assets 角色与语音 / pet_debug.log）
# 统一收纳到 exe 同目录下的「卡丘简易桌宠数据」子文件夹，exe 旁只留一个数据夹，
# 不再把多个文件散落在桌面/目录里。
USER_DATA_DIR = '卡丘简易桌宠数据'


def _pick_writable(candidates):
    """从候选目录里挑第一个可写可建目录的；全部失败返回 None"""
    for d in candidates:
        try:
            os.makedirs(d, exist_ok=True)
            test = os.path.join(d, '.pet_write_test')
            with open(test, 'w', encoding='utf-8') as f:
                f.write('1')
            os.remove(test)
            return d
        except Exception:
            continue
    return None


def base_dir():
    """用户数据根目录（可写持久）：
    - 打包后 = exe 同目录下的「卡丘简易桌宠数据」子文件夹；exe 目录不可写时
      依次回落：用户主目录下同名文件夹 → 用户主目录
    - 未打包 = 脚本目录（开发时资源/配置就在源码仓库里）
    用户导入的角色/音频/通用语音、pet_config.json、pet_debug.log 都在此。"""
    if hasattr(sys, "_MEIPASS"):
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        chosen = _pick_writable([
            os.path.join(exe_dir, USER_DATA_DIR),
            os.path.join(os.path.expanduser('~'), USER_DATA_DIR),
            os.path.expanduser('~'),
        ])
        return chosen if chosen is not None else os.path.expanduser('~')
    return os.path.dirname(os.path.abspath(__file__))


def bundle_dir():
    """内置资源目录（只读，打包后=_MEIPASS 临时解压；未打包=脚本目录）"""
    if hasattr(sys, "_MEIPASS"):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))


def _migrate_legacy_layout():
    """v1.5.0 及更早：数据直接散在 exe 同目录（pet_config.json / assets /
    pet_debug.log）。启动时若发现 exe 同目录仍存在这些旧文件，且新数据目录
    里还没有对应项，就把它们移进去（只移一次，之后由新目录接管）。"""
    if not hasattr(sys, "_MEIPASS"):
        return
    exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    data_dir = os.path.join(exe_dir, USER_DATA_DIR)
    try:
        os.makedirs(data_dir, exist_ok=True)
    except Exception:
        return
    legacy_items = ['pet_config.json', 'assets', 'pet_debug.log']
    for name in legacy_items:
        src = os.path.join(exe_dir, name)
        dst = os.path.join(data_dir, name)
        if os.path.exists(src) and not os.path.exists(dst):
            try:
                shutil.move(src, dst)
            except Exception:
                pass


# 模块加载即执行一次旧版布局迁移（在任何 load/save_config 读写前把
# exe 旁旧文件收进数据目录；base_dir() 会先建好空目录，不影响移动）
_migrate_legacy_layout()


def _log(*args):
    # 保留空实现，便于未来排查（不再默认密集打点）
    pass


def _dbg(msg):
    """调试日志：写 pet_debug.log 到用户数据目录（GUI 无控制台，print 不可见）"""
    try:
        logpath = os.path.join(base_dir(), 'pet_debug.log')
        with open(logpath, 'a', encoding='utf-8') as f:
            f.write(str(msg) + '\n')
    except Exception:
        pass


CONFIG_FILE = os.path.join(base_dir(), 'pet_config.json')


def load_config():
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def save_config(cfg):
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print('save_config fail:', e)

# 右上角三横（汉堡）菜单按钮尺寸
MENU_BTN_SIZE = 30
MENU_BTN_MARGIN = 6

# 统一深色圆角菜单样式（汉堡菜单 + 托盘菜单共用）
MENU_QSS = """
QMenu {
    background-color: rgba(26, 28, 36, 240);
    border: 1px solid rgba(255, 255, 255, 36);
    border-radius: 10px;
    padding: 6px;
}
QMenu::item {
    background: transparent;
    color: #e6e8f0;
    padding: 7px 22px 7px 14px;
    border-radius: 6px;
    font-size: 13px;
}
QMenu::item:selected {
    background: rgba(255, 255, 255, 34);
    color: #ffffff;
}
QMenu::separator {
    height: 1px;
    background: rgba(255, 255, 255, 26);
    margin: 6px 10px;
}
"""


_seeded = False


def _seed_default_assets():
    """打包运行首次启动：把内置默认资源（characters/common_voice）复制到
    用户数据目录 assets（若还没有），保证开箱即有默认角色/通用语音，且之后可写"""
    global _seeded
    if _seeded:
        return
    _seeded = True
    if not hasattr(sys, "_MEIPASS"):
        return  # 未打包：数据目录就是脚本目录，资源本来就在
    try:
        src_a = os.path.join(bundle_dir(), 'assets')
        dst_a = os.path.join(base_dir(), 'assets')
        os.makedirs(dst_a, exist_ok=True)
        # characters
        src_c = os.path.join(src_a, 'characters')
        dst_c = os.path.join(dst_a, 'characters')
        if os.path.isdir(src_c) and not os.path.isdir(dst_c):
            shutil.copytree(src_c, dst_c)
        # common_voice
        src_v = os.path.join(src_a, 'common_voice')
        dst_v = os.path.join(dst_a, 'common_voice')
        if os.path.isdir(src_v) and not os.path.isdir(dst_v):
            shutil.copytree(src_v, dst_v)
        # 旧版本可能拷过角色 → 补充缺失的默认角色
        if os.path.isdir(src_c) and os.path.isdir(dst_c):
            for name in os.listdir(src_c):
                if not os.path.exists(os.path.join(dst_c, name)):
                    try:
                        shutil.copytree(os.path.join(src_c, name), os.path.join(dst_c, name))
                    except Exception:
                        pass
    except Exception as e:
        print('seed default assets fail:', e)


def assets_dir():
    d = os.path.join(base_dir(), "assets")
    os.makedirs(d, exist_ok=True)
    _seed_default_assets()
    return d


def chars_dir():
    return os.path.join(assets_dir(), "characters")


def common_voice_dir():
    """通用语音目录：任何角色都可用这套语音（与 characters 平级）"""
    return os.path.join(assets_dir(), "common_voice")


def role_image(d):
    """返回角色目录主图 (路径, kind)。优先 image.png；其次常见固定名
    （cover/avatar/角色名）且扩展名在 IMAGE_EXTS 内；否则目录内任意支持图片
    （排序取首个；动图 .gif/.webp 标为 gif 以便 QMovie 播放）"""
    # 1) 首选 image.png（历史约定）
    png = os.path.join(d, "image.png")
    if os.path.exists(png):
        return png, "png"
    # 2) 常见固定名：image/cover/avatar/icon + 扩展名
    try:
        files = sorted(os.listdir(d))
    except Exception:
        files = []
    stems = ('image', 'cover', 'avatar', 'icon', 'portrait')
    for f in files:
        low = f.lower()
        stem = os.path.splitext(low)[0]
        if stem in stems and low.endswith(IMAGE_EXTS):
            return os.path.join(d, f), ("gif" if low.endswith(('.gif', '.webp')) else "png")
    # 3) 动画优先：任意 .gif/.webp
    for f in files:
        if f.lower().endswith(('.gif', '.webp')):
            return os.path.join(d, f), "gif"
    # 4) 任意支持图片
    for f in files:
        if f.lower().endswith(IMAGE_EXTS):
            return os.path.join(d, f), "png"
    return None


def list_roles():
    """从 assets/characters/ 扫描可展示角色形象 → 相对 chars_dir 的路径列表。

    支持三种磁盘布局（阵营为一级目录，可含任意层形象子目录）：
      characters/星绘/image.png            → "星绘"        （无阵营，历史平铺）
      characters/欧泊/米雪儿/image.png     → "欧泊/米雪儿"（单形象直放角色目录）
      characters/欧泊/米雪儿/泳装/image.png→ "欧泊/米雪儿/泳装"（多形象）
    规则：目录含角色图 → 该目录即一个可展示形象（角色根含图=默认形象）；
          目录不含图但子目录含图 → 每个含图子目录是一个形象（角色根仅为语音层）。
    返回按 阵营/角色 排序。无任何可用角色时兜底 DEFAULT_ROLE。"""
    roles = []
    d = chars_dir()
    if os.path.isdir(d):
        for top in sorted(os.listdir(d)):
            full = os.path.join(d, top)
            if not os.path.isdir(full):
                continue
            if role_image(full):
                # 顶级目录本身就是角色（历史平铺 / 或"阵营目录直接含图"的退化）
                roles.append(top)
                continue
            # 顶级目录当作阵营：扫描其下角色目录
            for name in sorted(os.listdir(full)):
                rdir = os.path.join(full, name)
                if not os.path.isdir(rdir):
                    continue
                base = "%s/%s" % (top, name)
                if role_image(rdir):
                    # 角色目录含图 → 默认形象
                    roles.append(base)
                else:
                    # 角色目录无图 → 找含图的形象子目录（语音留在角色根）
                    subs = [s for s in sorted(os.listdir(rdir))
                            if os.path.isdir(os.path.join(rdir, s))
                            and role_image(os.path.join(rdir, s))]
                    for s in subs:
                        roles.append("%s/%s" % (base, s))
    return roles or [DEFAULT_ROLE]


def role_dir(role):
    """角色展示目录（相对 chars_dir 的路径，兼容含 '/' 的多级标识）"""
    # 防路径穿越：只允许正常拼接
    parts = [p for p in str(role).replace('\\', '/').split('/') if p and p not in ('.', '..')]
    return os.path.join(chars_dir(), *parts)


def default_role_pick(roles):
    """从角色列表挑默认角色：优先名字等于 DEFAULT_ROLE 的项（任意阵营/形象），
    再退为列表首个；列表空 → DEFAULT_ROLE。"""
    if not roles:
        return DEFAULT_ROLE
    for r in roles:
        if role_character_name(r) == DEFAULT_ROLE or role_display(r) == DEFAULT_ROLE:
            return r
    return roles[0]


def role_root(role):
    """角色根路径 = 语音所在目录（去掉末尾形象段）：
      "乌尔比诺/星绘"       → "乌尔比诺/星绘"
      "乌尔比诺/星绘/泳装"  → "乌尔比诺/星绘"（泳装形象共用角色语音）
    无形象（1-2 段）时返回自身。"""
    parts = [p for p in str(role).replace('\\', '/').split('/') if p and p not in ('.', '..')]
    # 段数 > 2（阵营/角色/形象…）→ 角色根取前两段
    if len(parts) > 2:
        parts = parts[:2]
    return os.path.join(chars_dir(), *parts)


def role_display(role):
    """角色显示名：取角色名段（去掉阵营与形象段）：
      "欧泊/米雪儿" → "米雪儿"；"乌尔比诺/星绘/泳装" → "星绘·泳装"
    """
    parts = [p for p in str(role).replace('\\', '/').split('/') if p and p not in ('.', '..')]
    if not parts:
        return str(role)
    if len(parts) >= 3:
        # 阵营/角色/形象 → "角色·形象"
        return "%s·%s" % (parts[-2], parts[-1])
    return parts[-1]


def role_faction(role):
    """角色阵营显示名：无阵营（历史平铺）→ ''；否则返回一级目录名"""
    parts = [p for p in str(role).replace('\\', '/').split('/') if p and p not in ('.', '..')]
    return parts[0] if len(parts) >= 2 else ''


def role_variant(role):
    """形象名（多形象时末段；无形象 → ''）：用于 UI 显示“第几套”"""
    parts = [p for p in str(role).replace('\\', '/').split('/') if p and p not in ('.', '..')]
    return parts[-1] if len(parts) >= 3 else ''


def role_character_name(role):
    """角色基础名（去掉阵营/形象，供语音规则硬编码判断）：
      "乌尔比诺/星绘" → "星绘"；"乌尔比诺/星绘/泳装" → "星绘"；"白墨" → "白墨"
    """
    parts = [p for p in str(role).replace('\\', '/').split('/') if p and p not in ('.', '..')]
    if len(parts) >= 2:
        return parts[-2] if len(parts) >= 3 else parts[-1]
    return parts[-1] if parts else ''


# 支持的音频扩展名（角色目录下这些文件都会出现在菜单里）
# 播放：绑定设备时走 soundfile/libsndfile 直出（常用格式），其余由 QtMultimedia
# 内置 ffmpeg 解码播放 —— 因此这里覆盖几乎所有常见音频格式。
AUDIO_EXTS = (
    '.mp3', '.wav', '.ogg', '.m4a', '.flac', '.aac', '.opus', '.wma',
    '.aiff', '.aif', '.ape', '.amr', '.webm', '.m4b', '.caf', '.mp2',
)

# 支持的角色形象图扩展名（QMovie/QPixmap 可显示的；动图用 .gif/.webp）
IMAGE_EXTS = ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.ico', '.avif')

# 音频文件名 → 友好显示名
AUDIO_LABEL = {
    'morning': '早上好',
    'noon': '中午好',
    'evening': '晚上好',
    'sprint': '冲刺',
    'click': '点击',
    'hello': '你好',
}


def friendly_audio_name(name):
    """把音频文件名（无扩展名）转成好读的中文名，未知则原样返回"""
    return AUDIO_LABEL.get(name, name)


def trigger_voice_dir(role):
    """集中触发音目录：assets/trigger_voice/<角色名>/（角色名=去阵营/形象的末段）"""
    return os.path.join(assets_dir(), 'trigger_voice', role_character_name(role))


def trigger_voice_for(role):
    """按角色找集中触发音文件（trigger_voice/<角色名>/ 下）：
    优先「卡拉彼丘」名，否则取目录第一个音频；无 → None"""
    try:
        tv = trigger_voice_dir(role)
        if os.path.isdir(tv):
            cands = [f for f in sorted(os.listdir(tv))
                     if os.path.isfile(os.path.join(tv, f)) and f.lower().endswith(AUDIO_EXTS)]
            if cands:
                for f in cands:
                    if os.path.splitext(f)[0].strip() == '卡拉彼丘':
                        return os.path.join(tv, f)
                return os.path.join(tv, cands[0])
    except Exception:
        pass
    return None


def pick_click_voice(d, role=None):
    """挑角色点按触发音（模块级）：
    1) 有 role → 优先集中触发音目录 trigger_voice/<角色名>/（如「卡拉彼丘.mp3」）
    2) 其次 d（角色目录）里「非内置名」音频（如完整台词自我介绍）→ 取文件名最长者
       （内置名：morning/noon/evening/sprint/click/hello）
    3) 否则返回 None（由调用方按角色旧规则决定：星绘时段/白墨 sprint/其它 morning）
    """
    if role:
        tv = trigger_voice_for(role)
        if tv:
            return tv
    builtin = {'morning', 'noon', 'evening', 'sprint', 'click', 'hello'}
    best = None
    if os.path.isdir(d):
        for f in os.listdir(d):
            full = os.path.join(d, f)
            if not os.path.isfile(full) or not f.lower().endswith(AUDIO_EXTS):
                continue
            stem = os.path.splitext(f)[0]
            if stem.lower() in builtin:
                continue
            if best is None or len(stem) > len(os.path.splitext(best)[0]):
                best = f
    return os.path.join(d, best) if best else None


def list_role_audio(role):
    """列出角色语音（角色根目录下所有音频）→ [(显示名, 绝对路径)]。
    多形象时语音共用角色根（形象目录只放图）。"""
    # 先找角色根（去掉形象段）；若角色根不存在（平铺单角色）则回退 role_dir
    candidates = [role_root(role), role_dir(role)]
    seen = set()
    out = []
    for d in candidates:
        if d in seen:
            continue
        seen.add(d)
        if os.path.isdir(d):
            for f in sorted(os.listdir(d)):
                full = os.path.join(d, f)
                if os.path.isfile(full) and f.lower().endswith(AUDIO_EXTS):
                    name = os.path.splitext(f)[0]
                    out.append((friendly_audio_name(name), full))
    return out


def list_common_audio():
    """列出通用语音目录下所有音频 → [(显示名, 绝对路径)]（按文件名排序）"""
    d = common_voice_dir()
    out = []
    if os.path.isdir(d):
        for f in sorted(os.listdir(d)):
            full = os.path.join(d, f)
            if os.path.isfile(full) and f.lower().endswith(AUDIO_EXTS):
                name = os.path.splitext(f)[0]
                out.append((friendly_audio_name(name), full))
    return out


# ------- 绑定麦克风/输出设备 -------
def short_device_name(name):
    """把设备名截短显示（去掉重复的 '(VB-Audio ...)' 后缀等）"""
    for suffix in [' (VB-Audio Voicemeeter VAIO)', ' (USB Audio and HID)',
                   ' (NVIDIA High Definition Audio)', ' (Microsoft)']:
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def list_output_devices():
    """枚举音频输出设备供"绑定"选择（只取 WASAPI 后端，干净无重复）
    返回 [(设备名, WASAPI设备索引)]；Voicemeeter 系列排前（绑定通常用它）"""
    if not HAS_SD:
        return []
    try:
        devs = _sd.query_devices()
        apis = _sd.query_hostapis()
        # WASAPI 是 Windows 首选（hostapi name == 'Windows WASAPI'）
        wasapi_idx = next((i for i, a in enumerate(apis) if 'WASAPI' in a['name']), None)
        if wasapi_idx is None:
            return []
        out = []
        for i, d in enumerate(devs):
            if d['hostapi'] == wasapi_idx and d['max_output_channels'] > 0:
                name = d['name'].strip()
                if name and not name.startswith('Microsoft '):
                    out.append((name, i))
        # 去重（同名的 WASAPI 只留一个）
        seen = {}
        for name, i in out:
            seen[name] = i
        names = list(seen.keys())
        # Voicemeeter 排前，其余按名排序
        vm = [n for n in names if 'Voicemeeter' in n]
        rest = sorted(n for n in names if 'Voicemeeter' not in n)
        return [(n, seen[n]) for n in vm + rest]
    except Exception:
        return []


def _resolve_device_index(device_name):
    """按设备名解析 WASAPI 输出设备索引；找不到回退模糊匹配。返回 idx 或 None"""
    if not HAS_SD:
        return None
    try:
        devs = _sd.query_devices()
        apis = _sd.query_hostapis()
        wasapi_idx = next((i for i, a in enumerate(apis) if 'WASAPI' in a['name']), None)
        if wasapi_idx is not None:
            for i, d in enumerate(devs):
                if (d['hostapi'] == wasapi_idx and d['max_output_channels'] > 0
                        and d['name'].strip() == device_name):
                    return i
        # 回退：全后端模糊匹配（处理旧配置存了截断名的情况）
        for i, d in enumerate(devs):
            if d['max_output_channels'] > 0 and device_name in d['name']:
                return i
    except Exception:
        pass
    return None


# 音频解码缓存（LRU，上限 4 条；大文件不缓存防占内存）。
# 点击语音/常用音频会反复播放 → 缓存解码结果避免每次重新读整个文件（最大性能提升点）
_decode_cache = {}          # path → (data, sr)
_decode_cache_order = []    # 按访问顺序记录 path（用于 LRU 淘汰）
_DECODE_CACHE_MAX = 4
_DECODE_CACHE_MAX_BYTES = 5 * 1024 * 1024   # 单文件 >5MB 不缓存


def _cache_decode(path, data, sr):
    try:
        if os.path.getsize(path) > _DECODE_CACHE_MAX_BYTES:
            return  # 大文件不缓存
        if path in _decode_cache:
            _decode_cache_order.remove(path)
        _decode_cache[path] = (data, sr)
        _decode_cache_order.append(path)
        while len(_decode_cache_order) > _DECODE_CACHE_MAX:
            old = _decode_cache_order.pop(0)
            _decode_cache.pop(old, None)
    except Exception:
        pass


def _decode_and_prepare(path):
    """读音频 → (float32 二维数组, 采样率)，失败返回 None。带解码缓存"""
    cached = _decode_cache.get(path)
    if cached is not None:
        return cached
    try:
        data, sr = _sf.read(path, dtype='float32', always_2d=True)
        if data.size == 0:
            return None
        _cache_decode(path, data, sr)
        return data, sr
    except Exception:
        return None


def _adapt_to_device(data, sr, dev_idx):
    """把音频适配到设备：声道数匹配 + 重采样到设备默认采样率。
    返回 (data, 最终sr)；失败返回 None"""
    try:
        devs = _sd.query_devices()
        dev_info = devs[dev_idx]
        ch = dev_info['max_output_channels'] or 2
        if data.shape[1] < ch:
            # 声道不足：复制已有声道（如单声道→立体声，两耳都听到），
            # 不能用补零（会导致右声道无声）
            reps = ch // data.shape[1]
            remainder = ch % data.shape[1]
            parts = [data] * reps
            if remainder:
                parts.append(data[:, :remainder])
            data = _np.concatenate(parts, axis=1)
        elif data.shape[1] > ch:
            data = data[:, :ch]
        target_sr = int(dev_info['default_samplerate'] or 48000)
        if sr != target_sr and sr > 0 and target_sr > 0:
            n_out = int(round(data.shape[0] * target_sr / sr))
            x_old = _np.linspace(0.0, 1.0, data.shape[0], endpoint=False)
            x_new = _np.linspace(0.0, 1.0, n_out, endpoint=False)
            new_data = _np.empty((n_out, data.shape[1]), dtype='float32')
            for c in range(data.shape[1]):
                new_data[:, c] = _np.interp(x_new, x_old, data[:, c])
            data = new_data
            sr = target_sr
        return data, sr
    except Exception as e:
        print('_adapt_to_device fail:', e)
        return None


def _play_one_device(path, device_name, prepared=None):
    """向单个设备播放（阻塞，应在后台线程）。prepared 为 (data,sr) 预解码结果可复用。
    返回 True/False"""
    if not HAS_SD:
        return False
    try:
        idx = _resolve_device_index(device_name)
        if idx is None:
            print('device not found:', device_name)
            return False
        if prepared is None:
            prep = _decode_and_prepare(path)
            if prep is None:
                return False
            data, sr = prep
        else:
            data, sr = prepared
        adapted = _adapt_to_device(data, sr, idx)
        if adapted is None:
            return False
        data2, sr2 = adapted
        with _sd.OutputStream(device=idx, samplerate=sr2, channels=data2.shape[1],
                              dtype='float32') as stream:
            stream.write(data2)
        return True
    except Exception as e:
        print('_play_one_device fail:', e)
        return False


def play_audio_direct(path, device_name):
    """[兼容旧调用] 单设备播放"""
    return _play_one_device(path, device_name)


def play_audio_multi(path, device_names):
    """向多个设备并行播放同一音频（绑定麦 + 自己耳机等）。
    解码一次，每设备一个后台线程写。返回成功设备数"""
    if not HAS_SD or not device_names:
        return 0
    prepared = _decode_and_prepare(path)
    if prepared is None:
        return 0
    results = []
    threads = []
    for dev in device_names:
        t = threading.Thread(target=lambda dn=dev: results.append(
            (dn, _play_one_device(path, dn, prepared))), daemon=True)
        t.start()
        threads.append(t)
    for t in threads:
        t.join()
    ok = sum(1 for _, s in results if s)
    return ok


# ------- 全局热键（快捷播放）-------
# 通用单键热键：小键盘1-9 默认 + 用户自定义键
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312
# 小键盘数字键虚拟码: Numpad1..Numpad9 = 0x61..0x69
NUMPAD_VK = {1: 0x61, 2: 0x62, 3: 0x63, 4: 0x64, 5: 0x65,
             6: 0x66, 7: 0x67, 8: 0x68, 9: 0x69}
MAX_HOTKEY_SLOTS = 9  # 1~9

# 常用键名 ↔ VK 映射（用于自定义快捷键显示与注册）
VK_NAME_MAP = {
    # 字母
    'A': 0x41, 'B': 0x42, 'C': 0x43, 'D': 0x44, 'E': 0x45, 'F': 0x46,
    'G': 0x47, 'H': 0x48, 'I': 0x49, 'J': 0x4A, 'K': 0x4B, 'L': 0x4C,
    'M': 0x4D, 'N': 0x4E, 'O': 0x4F, 'P': 0x50, 'Q': 0x51, 'R': 0x52,
    'S': 0x53, 'T': 0x54, 'U': 0x55, 'V': 0x56, 'W': 0x57, 'X': 0x58,
    'Y': 0x59, 'Z': 0x5A,
    # 数字行
    '0': 0x30, '1': 0x31, '2': 0x32, '3': 0x33, '4': 0x34,
    '5': 0x35, '6': 0x36, '7': 0x37, '8': 0x38, '9': 0x39,
    # 功能键
    'F1': 0x70, 'F2': 0x71, 'F3': 0x72, 'F4': 0x73, 'F5': 0x74,
    'F6': 0x75, 'F7': 0x76, 'F8': 0x77, 'F9': 0x78, 'F10': 0x79,
    'F11': 0x7A, 'F12': 0x7B,
    # 小键盘
    'Num0': 0x60, 'Num1': 0x61, 'Num2': 0x62, 'Num3': 0x63, 'Num4': 0x64,
    'Num5': 0x65, 'Num6': 0x66, 'Num7': 0x67, 'Num8': 0x68, 'Num9': 0x69,
    # 其它常用
    'Space': 0x20, 'Tab': 0x09, 'Enter': 0x0D, 'Esc': 0x1B,
    '`': 0xC0, '-': 0xBD, '=': 0xBB, '[': 0xDB, ']': 0xDD, '\\': 0xDC,
    ';': 0xBA, "'": 0xDE, ',': 0xBC, '.': 0xBE, '/': 0xBF,
}
VK_NAME_REV = {v: k for k, v in VK_NAME_MAP.items()}

# 注册用基础热键 ID（自定义键从 0x6000 起分配）
CUSTOM_HK_BASE = 0x6000

_user32 = ctypes.windll.user32


def register_numpad_hotkeys(hwnd):
    """注册小键盘 1-9 全局热键。返回 {数字: 热键ID} 映射，失败项跳过"""
    ids = {}
    for num in range(1, MAX_HOTKEY_SLOTS + 1):
        hid = 0x5000 + num  # 自定热键 ID
        ok = _user32.RegisterHotKey(hwnd, hid, MOD_NOREPEAT, NUMPAD_VK[num])
        if ok:
            ids[num] = hid
        else:
            # 可能被其它程序占用（MOD_NOREPEAT 失败时去掉重试）
            ok2 = _user32.RegisterHotKey(hwnd, hid, 0, NUMPAD_VK[num])
            if ok2:
                ids[num] = hid
    return ids


def unregister_numpad_hotkeys(hwnd, ids):
    """注销已注册的热键"""
    for hid in ids.values():
        _user32.UnregisterHotKey(hwnd, hid)


def register_single_hotkey(hwnd, hid, vk):
    """注册单个热键（MOD_NOREPEAT 优先，失败去修饰重试）。返回是否成功"""
    if _user32.RegisterHotKey(hwnd, hid, MOD_NOREPEAT, vk):
        return True
    return bool(_user32.RegisterHotKey(hwnd, hid, 0, vk))


def unregister_hotkey(hwnd, hid):
    """注销单个热键"""
    if hid:
        try:
            _user32.UnregisterHotKey(hwnd, hid)
        except Exception:
            pass


def key_name_to_vk(name):
    """键名 → 虚拟码；不认识返回 None"""
    return VK_NAME_MAP.get(name)


def vk_to_key_name(vk):
    """虚拟码 → 键名（如 'V'/'F1'/'Num1'）"""
    return VK_NAME_REV.get(vk, 'Key%d' % vk)


# ------- 按键捕获（WH_KEYBOARD_LL 一次性钩子，用于"录制"自定义键）-------
WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_CHAR = 0x0102
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
VK_ESCAPE = 0x1B
VK_RETURN = 0x0D
# 忽略的修饰键（单独按不应作为绑定键）
_MODIFIER_VKS = {0x10, 0x11, 0x12, 0x5B, 0x5C, 0xA0, 0xA1, 0xA2, 0xA3}


class CURSORINFO(ctypes.Structure):
    """GetCursorInfo 输出结构（wintypes 无内置）"""
    _fields_ = [
        ('cbSize', wintypes.DWORD),
        ('flags', wintypes.DWORD),
        ('hCursor', wintypes.HANDLE),
        ('ptScreenPos', wintypes.POINT),
    ]


class KBDLLHOOKSTRUCT(ctypes.Structure):
    """KBDLLHOOKSTRUCT（wintypes 未内置，需自定义）"""
    _fields_ = [
        ('vkCode', wintypes.DWORD),
        ('scanCode', wintypes.DWORD),
        ('flags', wintypes.DWORD),
        ('time', wintypes.DWORD),
        ('dwExtraInfo', ctypes.POINTER(wintypes.ULONG)),
    ]


# LL 钩子需要回调类型（64位指针兼容：wParam=WPARAM, lParam=LPARAM）
_LLKBD_ProcType = ctypes.WINFUNCTYPE(
    ctypes.c_longlong,          # LRESULT (64位)
    ctypes.c_int,               # nCode
    ctypes.c_size_t,            # wParam (WPARAM 无符号指针宽)
    ctypes.c_void_p,            # lParam (LPARAM 指针)
)


LLKHF_INJECTED = 0x10  # KBDLLHOOKSTRUCT.flags 位4：程序注入的按键


class KeyCapture:
    """一次性键盘钩子：捕获用户按下的下一个键。
    低级钩子(WH_KEYBOARD_LL)的回调必须在【有消息循环的线程】中才会被派发，
    故用独立线程 + GetMessage 循环；回调只做最小记录（线程安全），
    主线程通过 _poll() 轮询结果。Esc→None；修饰键忽略并吞掉。
    程序注入的键（LLKHF_INJECTED，如 auto_ptt 模拟的开麦键）会被忽略——防止
    录音时把"语音试听触发的自动按V"误当成用户绑定键。"""

    def __init__(self, on_done):
        self._on_done = on_done
        self._hook = None
        self._result = None          # 线程安全结果槽
        self._result_lock = threading.Lock()
        self._thread = None
        self._running = False
        self._poll_timer = None

    def _proc(self, nCode, wParam, lParam):
        if nCode >= 0 and wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
            kbd = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            vk = int(kbd.vkCode)
            flags = int(kbd.flags)
            if flags & LLKHF_INJECTED:
                # 程序注入的键（auto_ptt 等模拟按键）：不录制，且放行给系统
                return ctypes.windll.user32.CallNextHookEx(
                    self._hook, ctypes.c_int(nCode), ctypes.c_size_t(wParam), ctypes.c_void_p(lParam))
            with self._result_lock:
                if vk == VK_ESCAPE:
                    self._result = 'esc'
                elif vk not in _MODIFIER_VKS:
                    self._result = vk
            return 1  # 吞掉该键（含修饰键，避免其释放事件外泄）
        # lParam 是 64 位指针，CallNextHookEx 需原样透传（用 c_void_p 值）
        return ctypes.windll.user32.CallNextHookEx(
            self._hook, ctypes.c_int(nCode), ctypes.c_size_t(wParam), ctypes.c_void_p(lParam))

    def _message_loop(self):
        """钩子线程：安装钩子 + 派发消息（GetMessage 循环）。
        低级钩子回调由本线程的消息循环触发。
        注意：钩子过程在本进程内 → SetWindowsHookExW 的 hMod 必须传 NULL
        （传模块句柄会报 ERROR_MOD_NOT_FOUND 126 导致 hook=0）"""
        try:
            self._proc_ref = _LLKBD_ProcType(self._proc)  # 存引用防 GC
            self._hook = _user32.SetWindowsHookExW(
                WH_KEYBOARD_LL, self._proc_ref, None, 0)
        except Exception as e:
            print('keycapture install fail:', e)
            with self._result_lock:
                self._result = 'err'
            return
        if not self._hook:
            with self._result_lock:
                self._result = 'err'
            return
        msg = wintypes.MSG()
        while self._running:
            r = _user32.GetMessageW(ctypes.byref(msg), 0, 0, 0)
            if r == 0:
                break
            if r == -1:
                break
            _user32.TranslateMessage(ctypes.byref(msg))
            _user32.DispatchMessageW(ctypes.byref(msg))
            # 有结果即退出（避免吞掉后续按键）
            with self._result_lock:
                if self._result is not None:
                    break
        # 清理钩子
        if self._hook:
            _user32.UnhookWindowsHookEx(self._hook)
            self._hook = None

    def start(self):
        """启动钩子线程，并启动主线程轮询。返回是否成功启动线程"""
        if self._thread is not None and self._thread.is_alive():
            return True
        self._running = True
        self._result = None
        self._thread = threading.Thread(target=self._message_loop, daemon=True)
        self._thread.start()
        # 主线程轮询结果（每 40ms），GUI 安全回调
        self._poll_timer = QTimer()
        self._poll_timer.setInterval(40)
        self._poll_timer.timeout.connect(self._poll)
        self._poll_timer.start()
        return True

    def _poll(self):
        """主线程轮询：结果非 None 时回调 on_done 并停止"""
        with self._result_lock:
            r = self._result
        if r is None:
            return
        self.stop()
        vk = None if r == 'esc' or r == 'err' else r
        try:
            self._on_done(vk)
        except Exception as e:
            print('keycapture on_done err:', e)

    def stop(self):
        self._running = False
        if self._poll_timer is not None:
            self._poll_timer.stop()
            self._poll_timer = None
        if self._hook:
            try:
                _user32.UnhookWindowsHookEx(self._hook)
            except Exception:
                pass
            self._hook = None


# ------- 智能小键盘播放（聚焦输入框自动放行）-------
# 用 WH_KEYBOARD_LL 常驻钩子替代 RegisterHotKey：
# 按下小键盘 1-9 时，若前台窗口处于"文本输入态"（有光标/输入控件）→ 放行按键正常输入；
# 否则（如游戏、桌面、桌宠本体）→ 吞掉该键并触发对应语音。这样开着快捷播放也不影响打字。


class GUITHREADINFO(ctypes.Structure):
    """GUI 线程信息（wintypes 无内置，需自定义；与 Win32 GUITHREADINFO 对齐）"""
    _fields_ = [
        ('cbSize', wintypes.DWORD),
        ('flags', wintypes.DWORD),
        ('hwndActive', wintypes.HWND),
        ('hwndFocus', wintypes.HWND),
        ('hwndCapture', wintypes.HWND),
        ('hwndMenuOwner', wintypes.HWND),
        ('hwndMoveSize', wintypes.HWND),
        ('hwndCaret', wintypes.HWND),
        ('rcCaret', wintypes.RECT),
    ]


def _foreground_exe():
    """返回当前前台窗口所属进程的 exe 名（小写，不含 .exe）；失败返回 ''。
    供游戏联动钩子判断"目标游戏是否在前台"。"""
    try:
        fg = _user32.GetForegroundWindow()
        if not fg:
            return ''
        pid = wintypes.DWORD()
        _user32.GetWindowThreadProcessId(fg, ctypes.byref(pid))
        if not pid.value:
            return ''
        hProc = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid.value)
        if not hProc:
            return ''
        try:
            buf = ctypes.create_unicode_buffer(1024)
            sz = wintypes.DWORD(len(buf))
            ctypes.windll.kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
            ctypes.windll.kernel32.QueryFullProcessImageNameW.argtypes = [
                wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                ctypes.POINTER(wintypes.DWORD)]
            if ctypes.windll.kernel32.QueryFullProcessImageNameW(
                    hProc, 0, buf, ctypes.byref(sz)):
                return os.path.basename(buf.value).lower().replace('.exe', '')
            return ''
        finally:
            ctypes.windll.kernel32.CloseHandle(hProc)
    except Exception:
        return ''


# 智能钩子使用的 Win32 API 原型（防 64 位截断 + HWND 指针正确）
_user32.GetForegroundWindow.restype = wintypes.HWND
_user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
_user32.GetWindowThreadProcessId.restype = wintypes.DWORD
_user32.GetGUIThreadInfo.argtypes = [wintypes.DWORD, ctypes.POINTER(GUITHREADINFO)]
_user32.GetGUIThreadInfo.restype = wintypes.BOOL
_user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
_user32.GetClassNameW.restype = ctypes.c_int


_TEXT_INPUT_CN = {
    # 经典 Win32 输入控件
    "edit", "richedit", "rhedit", "tkinter", "scintilla", "consolewindowclass",
    "cmdline", "notepad", "ime",
    # 浏览器内核（Chrome/Edge/Electron 应用输入框）
    "chrome_edit", "editwrapper", "osinputbox", "webbrowser", "tb_browser",
    "textbox", "textfield", "input",
    # 现代 UI（WinUI/UWP/WPF/跨平台）
    "windowsuicore", "hwndhost", "texteditor",
}
# 注意：不把通用 "qwidget"/"metawindow" 当输入控件（误伤所有 Qt 程序）；
# Qt 应用是否在输入靠 hwndCaret 精确判定。
# 前台进程白名单：这些程序聚焦时大概率正在输入（浏览器/聊天/编辑器/终端等）。
# 注意：QQ/微信/浏览器等即使没聚焦输入框也可能要打字，故放行数字（避免聊天打不出数字）。
# 游戏、桌宠本体、资源管理器等不在名单 → 按小键盘触发语音。
_TEXT_INPUT_EXE = {
    "chrome", "msedge", "firefox", "qq", "wechat", "weixin", "dingtalk", "feishu",
    "notepad", "notepad++", "code", "cursor", "idea64", "pycharm64",
    "winword", "excel", "powerpnt", "wps", "obsidian", "typora",
    "windowsTerminal", "cmd", "powershell", "mintty", "alacritty",
    "telegram", "discord", "slack", "tim", "wxwork",
    "outlook", "foxmail", "thunderbird",
}

# UIA 兜底判定缓存：{前台hwnd: (时间戳, 结果)} —— UIA 查询约 10-50ms，做 1 秒缓存
_uia_cache = {}
_UIA_TEXT_PATTERNS = (10014, 10002, 10005)  # TextPattern / ValuePattern / KeyboardFocus?（用前两个）
_UIA_CACHE_TTL = 1.0


def _uia_focus_is_text(hwnd):
    """用 UIA 查前台窗口的焦点元素是否可输入（支持 TextPattern/ValuePattern）。
    返回 True=正在输入；False/异常=查不到。带 1 秒缓存"""
    if not HAS_UIA or not hwnd:
        return False
    now = time.monotonic()
    c = _uia_cache.get(hwnd)
    if c and now - c[0] < _UIA_CACHE_TTL:
        return c[1]
    try:
        fe = _UIA_AUTO.GetFocusedElement()
        if fe is None:
            _uia_cache[hwnd] = (now, False)
            return False
        # 确认焦点元素属于目标窗口（否则是其它窗口抢了焦点）
        try:
            win = fe.GetCurrentPattern(10033)  # WindowPattern → 宿主窗口
            win_hwnd = int(win.CurrentWindowHandle or 0)
        except Exception:
            win_hwnd = 0
        # 简化：直接看控件类型/模式；若拿不到宿主，靠缓存+前台判定兜底
        ct = int(fe.CurrentControlType)
        if ct in (50004, 50030, 50032, 50033):  # Edit / Document / Hyperlink? / Pane（可编辑富文本身兼）
            _uia_cache[hwnd] = (now, True)
            return True
        for pid_ in (10014, 10002):  # TextPattern / ValuePattern
            try:
                fe.GetCurrentPattern(pid_)
                _uia_cache[hwnd] = (now, True)
                return True
            except Exception:
                continue
        _uia_cache[hwnd] = (now, False)
        return False
    except Exception:
        return False


def foreground_is_input():
    """检测前台窗口当前是否处于"文本输入"状态（应放行小键盘数字）。
    判据（任一命中即放行）：
    ① 前台线程 GUI 信息 hwndFocus/hwndCaret 指向输入控件（最精确：正在输入）
    ② 前台线程焦点控件类名是已知输入控件（覆盖现代应用/网页输入框）
    ③ 前台窗口类名是已知输入控件
    ④ 前台进程名是常见"可输入应用"（浏览器/聊天/编辑器等，聚焦多半在输入）
    失败时保守返回 True（放行输入，避免误吞打字）"""
    try:
        fg = _user32.GetForegroundWindow()
        if not fg:
            return True
        pid = wintypes.DWORD()
        tid = _user32.GetWindowThreadProcessId(fg, ctypes.byref(pid))
        if not tid:
            return True
        # ① 前台线程 GUI 信息（hwndFocus / hwndCaret）
        gti = GUITHREADINFO()
        gti.cbSize = ctypes.sizeof(GUITHREADINFO)
        if _user32.GetGUIThreadInfo(tid, ctypes.byref(gti)):
            if gti.hwndCaret:
                return True  # 有闪烁光标 → 正在输入
            # ② 焦点控件类名（GetGUIThreadInfo 的 hwndFocus 属于前台线程，
            #    比 GetFocus() 可靠——GetFocus 只返回调用线程的焦点）
            if gti.hwndFocus:
                fcs = ctypes.create_unicode_buffer(256)
                _user32.GetClassNameW(gti.hwndFocus, fcs, 256)
                fcn = fcs.value.lower()
                for pat in _TEXT_INPUT_CN:
                    if pat in fcn:
                        return True
        # ③ 窗口类名
        cls = ctypes.create_unicode_buffer(256)
        _user32.GetClassNameW(fg, cls, 256)
        cn = cls.value.lower()
        for pat in _TEXT_INPUT_CN:
            if pat in cn:
                return True
        # ④ 进程名白名单（子串匹配：chrome/msedge/qq/wechat 主程序与子进程都算）
        if pid.value:
            pname = ''
            try:
                hProc = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid.value)
                if hProc:
                    buf = ctypes.create_unicode_buffer(1024)
                    sz = wintypes.DWORD(len(buf))
                    ctypes.windll.kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
                    ctypes.windll.kernel32.QueryFullProcessImageNameW.argtypes = [
                        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                        ctypes.POINTER(wintypes.DWORD)]
                    if ctypes.windll.kernel32.QueryFullProcessImageNameW(
                            hProc, 0, buf, ctypes.byref(sz)):
                        pname = os.path.basename(buf.value).lower()
                    ctypes.windll.kernel32.CloseHandle(hProc)
            except Exception:
                pname = ''
            for exe in _TEXT_INPUT_EXE:
                if pname and exe in pname:
                    return True
        # ⑤ UIA 兜底：Chromium/Electron 系应用（DSH桌面/新版QQ微信等）窗口类名
        #    是 Chrome_WidgetWin_1，内部输入框拿不到 caret/焦点类名，但 UIA 能查
        #    焦点元素是否支持 TextPattern —— 通用识别“正在输入”，不再依赖进程白名单
        if 'chrome_widgetwin' in cn or 'chromium' in cn:
            try:
                if _uia_focus_is_text(fg):
                    return True
            except Exception:
                pass
        return False
    except Exception:
        return True  # 出错保守放行


class NumpadPlayHook:
    """常驻低层键盘钩子：智能拦截小键盘 1-9。
    前台为输入态 → 放行；否则 → 吞掉按键 + 主线程回调播放。
    与 KeyCapture 一样：独立线程 GetMessage 循环，_poll 轮询，GUI 安全回调"""

    def __init__(self, on_play):
        self._on_play = on_play        # 回调 func(num) 播放音频
        self._hook = None
        self._thread = None
        self._running = False
        self._num_pressed = None       # 线程安全槽：最近按下的数字
        self._lock = threading.Lock()
        self._poll_timer = None
        self._last = None               # 防重复回调
        self._down_keys = set()         # 当前按住的数字（keyup 时清）

    def _proc(self, nCode, wParam, lParam):
        if nCode >= 0:
            kbd = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            vk = int(kbd.vkCode)
            flags = int(kbd.flags)
            # 程序注入的键（auto_ptt 等）：放行
            if flags & LLKHF_INJECTED:
                return _user32.CallNextHookEx(self._hook, ctypes.c_int(nCode),
                                              ctypes.c_size_t(wParam), ctypes.c_void_p(lParam))
            is_down = wParam in (WM_KEYDOWN, WM_SYSKEYDOWN)
            if vk in NUMPAD_VK.values():
                num = next(n for n, v in NUMPAD_VK.items() if v == vk)
                if is_down:
                    if not foreground_is_input():
                        # 非输入态：吞掉按键
                        with self._lock:
                            self._num_pressed = num
                        return 1  # 吞掉
                    else:
                        return _user32.CallNextHookEx(  # 输入态放行
                            self._hook, ctypes.c_int(nCode), ctypes.c_size_t(wParam), ctypes.c_void_p(lParam))
                else:
                    # keyup 放行（若 down 被吞则 keyup 也吞保持配对，但这里简单放行）
                    return _user32.CallNextHookEx(self._hook, ctypes.c_int(nCode),
                                                  ctypes.c_size_t(wParam), ctypes.c_void_p(lParam))
        return _user32.CallNextHookEx(self._hook, ctypes.c_int(nCode),
                                      ctypes.c_size_t(wParam), ctypes.c_void_p(lParam))

    def _message_loop(self):
        try:
            self._proc_ref = _LLKBD_ProcType(self._proc)
            self._hook = _user32.SetWindowsHookExW(
                WH_KEYBOARD_LL, self._proc_ref, None, 0)
        except Exception as e:
            print('numpad hook install fail:', e)
            return
        if not self._hook:
            print('numpad hook install failed (hook=0)')
            return
        msg = wintypes.MSG()
        while self._running:
            r = _user32.GetMessageW(ctypes.byref(msg), 0, 0, 0)
            if r == 0 or r == -1:
                break
            _user32.TranslateMessage(ctypes.byref(msg))
            _user32.DispatchMessageW(ctypes.byref(msg))
        if self._hook:
            _user32.UnhookWindowsHookEx(self._hook)
            self._hook = None

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return
        self._running = True
        self._thread = threading.Thread(target=self._message_loop, daemon=True)
        self._thread.start()
        self._poll_timer = QTimer()
        self._poll_timer.setInterval(50)
        self._poll_timer.timeout.connect(self._poll)
        self._poll_timer.start()

    def _poll(self):
        if not self._running:
            return
        with self._lock:
            n = self._num_pressed
            self._num_pressed = None
        if n is not None:
            self._last = n
            try:
                self._on_play(n)
            except Exception as e:
                print('numpad play cb err:', e)

    def stop(self):
        self._running = False
        if self._poll_timer is not None:
            self._poll_timer.stop()
            self._poll_timer = None
        if self._hook:
            try:
                _user32.UnhookWindowsHookEx(self._hook)
            except Exception:
                pass
            self._hook = None


# ------- 自动按住开麦键（Auto PTT）-------
# 游戏多为"按住 V 说话"：播放音频时自动按住 V，音频播完再延后 0.5s 松开 → 队友完整听到
VK_V = 0x56  # V 键虚拟码
KEYEVENTF_KEYUP = 0x0002
PTT_HOLD_EXTRA_S = 0.5  # 音频结束后 V 额外按住的秒数

# SendInput 需要的结构（keybd_event 旧 API 部分游戏不认，SendInput 更可靠）
INPUT_KEYBOARD = 1
KEYEVENTF_SCANCODE = 0x0008


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ('wVk', wintypes.WORD),
        ('wScan', wintypes.WORD),
        ('dwFlags', wintypes.DWORD),
        ('time', wintypes.DWORD),
        ('dwExtraInfo', ctypes.POINTER(wintypes.ULONG)),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ('dx', wintypes.LONG), ('dy', wintypes.LONG),
        ('mouseData', wintypes.DWORD), ('dwFlags', wintypes.DWORD),
        ('time', wintypes.DWORD), ('dwExtraInfo', ctypes.POINTER(wintypes.ULONG)),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ('uMsg', wintypes.DWORD), ('wParamL', wintypes.WORD),
        ('wParamH', wintypes.WORD),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [('ki', KEYBDINPUT), ('mi', MOUSEINPUT), ('hi', HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [('type', wintypes.DWORD), ('u', _INPUTUNION)]


def _send_key(vk, keyup=False):
    """用 SendInput 发送按键事件（比 keybd_event 兼容性好）"""
    try:
        # 显式声明原型避免 64 位指针截断
        if not hasattr(_send_key, '_ready'):
            _user32.SendInput.argtypes = [
                wintypes.UINT,
                ctypes.POINTER(INPUT),
                ctypes.c_int,
            ]
            _user32.SendInput.restype = wintypes.UINT
            _send_key._ready = True
        inp = INPUT()
        inp.type = INPUT_KEYBOARD
        inp.u.ki.wVk = vk & 0xFFFF
        inp.u.ki.wScan = 0
        inp.u.ki.dwFlags = KEYEVENTF_KEYUP if keyup else 0
        inp.u.ki.time = 0
        inp.u.ki.dwExtraInfo = ctypes.POINTER(wintypes.ULONG)()  # NULL
        _user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
    except Exception as e:
        print('send_key fail:', e)


def ptt_key_down(vk=VK_V):
    """模拟按下开麦键（SendInput）"""
    _send_key(vk, keyup=False)


def ptt_key_up(vk=VK_V):
    """模拟松开开麦键（SendInput）"""
    _send_key(vk, keyup=True)


# ---------- 游戏内"回车自动补词"联动 ----------
# 目标：卡拉彼丘（官方启动器 / WeGame）对局聊天输入框，回车发送时自动在句尾
# 补一个词（默认 喵，可自定义）。实现详见 MeowHook 类（v6：鼠标可见性判定 + PostMessage）。
_MEOW_TARGET_EXES = {"calabiyau-win64-shipping", "calabiyau"}

# 可打印字符判定：字母/数字/空格/常见标点（用于判断"开聊天后打了字"）。
# 明确排除：方向键/编辑键(Ins/Del/Home/End/PageUp/Down 等)、F1-F12、修饰键。
_NON_CHAR_VK = (set(range(0x21, 0x2A))          # PageUp..Delete 区（含方向 0x25-28）
                | set(range(0x70, 0x88))        # F1-F24
                | {0x08, 0x09, 0x1B, 0x2C, 0x2E, 0x5B, 0x5C})  # BS/Tab/Esc/Print/Snap/Cmd
_PRINTABLE_VK = set()
for _v in range(0x20, 0x100):
    if _v in _NON_CHAR_VK:
        continue
    # 保留字符输入相关：空格(0x20)、数字、字母、OEM 标点区(0xBA-0xDE)
    if 0x20 <= _v <= 0x3A or 0x41 <= _v <= 0x5A or 0xBA <= _v <= 0xDE:
        _PRINTABLE_VK.add(_v)


class MeowHook:
    """常驻低层键盘钩子：卡拉彼丘聊天"回车自动补词"（v6，实测可用）。
    核心事实（经实测确认）：
      - 卡拉彼丘(UE4)【不响应 SendInput】注入，但【响应 PostMessage】(WM_KEYDOWN/WM_CHAR)；
      - 正常游戏操作时系统鼠标【隐藏】，按回车进入聊天栏后鼠标【可见】——
        用鼠标可见性可可靠区分"进入聊天栏的回车"与"发送的回车"。
    逻辑：
      - 前台为目标游戏 + 回车按下 + 鼠标【可见】→ 聊天栏已开 = 发送回车：
         钩子回调内（先于游戏收到回车）立即 PostMessage WM_CHAR 补词，
         然后【放行】真实回车 → 游戏正常发送并关闭输入框（不吞键，体验正常）。
      - 鼠标【隐藏】的回车（进入聊天栏）→ 完全放行不干预。
    开关由 PetWindow 控制（默认关）。"""

    def __init__(self, get_word):
        self._get_word = get_word      # 回调返回当前补词（如 '喵'）
        self._hook = None
        self._thread = None
        self._running = False

    def _cursor_visible(self):
        try:
            ci = CURSORINFO()
            ci.cbSize = ctypes.sizeof(CURSORINFO)
            if _user32.GetCursorInfo(ctypes.byref(ci)):
                return bool(ci.flags & 1)
        except Exception:
            pass
        return False

    def _proc(self, nCode, wParam, lParam):
        """低层键盘钩子回调。非目标/非回车/注入键一律 CallNextHookEx 放行；
        目标游戏 + 回车 + 鼠标可见(聊天栏已开=发送) → 抢先 PostMessage 补词后放行真实回车。"""
        if nCode < 0:
            return _user32.CallNextHookEx(self._hook, ctypes.c_int(nCode),
                                          ctypes.c_size_t(wParam), ctypes.c_void_p(lParam))
        try:
            kbd = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            vk = int(kbd.vkCode)
            flags = int(kbd.flags)
            if flags & LLKHF_INJECTED:
                return _user32.CallNextHookEx(self._hook, ctypes.c_int(nCode),
                                              ctypes.c_size_t(wParam), ctypes.c_void_p(lParam))
            down = wParam in (WM_KEYDOWN, WM_SYSKEYDOWN)
            if not down or vk != VK_RETURN:
                return _user32.CallNextHookEx(self._hook, ctypes.c_int(nCode),
                                              ctypes.c_size_t(wParam), ctypes.c_void_p(lParam))
            exe = _foreground_exe()
            if not (exe in _MEOW_TARGET_EXES or 'calabiyau' in exe):
                return _user32.CallNextHookEx(self._hook, ctypes.c_int(nCode),
                                              ctypes.c_size_t(wParam), ctypes.c_void_p(lParam))
            # 鼠标可见 = 聊天栏已开 → 本次回车=发送 → 抢先补词
            if self._cursor_visible():
                word = (self._get_word() or '').strip()
                if word:
                    try:
                        hwnd = _user32.GetForegroundWindow()
                        for ch in word:
                            _user32.PostMessageW(hwnd, WM_CHAR, ord(ch), 1)
                        try:
                            _dbg('[meow] 发送回车前已补词 %r' % word)
                        except Exception:
                            pass
                    except Exception as e:
                        print('meow prepend err:', e)
            # 放行真实回车（游戏正常发送+关闭输入框）
        except Exception:
            pass
        return _user32.CallNextHookEx(self._hook, ctypes.c_int(nCode),
                                      ctypes.c_size_t(wParam), ctypes.c_void_p(lParam))

    def _is_target_foreground(self):
        exe = _foreground_exe()
        if not exe:
            return False
        return exe in _MEOW_TARGET_EXES or 'calabiyau' in exe

    def _message_loop(self):
        try:
            self._proc_ref = _LLKBD_ProcType(self._proc)
            self._hook = _user32.SetWindowsHookExW(
                WH_KEYBOARD_LL, self._proc_ref, None, 0)
        except Exception as e:
            print('meow hook install fail:', e)
            return
        if not self._hook:
            print('meow hook install failed (hook=0)')
            return
        msg = wintypes.MSG()
        while self._running:
            r = _user32.PeekMessageW(ctypes.byref(msg), 0, 0, 0, 1)
            if r:
                _user32.TranslateMessage(ctypes.byref(msg))
                _user32.DispatchMessageW(ctypes.byref(msg))
            time.sleep(0.008)
        if self._hook:
            _user32.UnhookWindowsHookEx(self._hook)
            self._hook = None

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return
        self._running = True
        self._thread = threading.Thread(target=self._message_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._hook:
            try:
                _user32.UnhookWindowsHookEx(self._hook)
            except Exception:
                pass
            self._hook = None


def _userCallNext(hook, nCode, wParam, lParam):
    """安全的 CallNextHookEx 封装（透传原始值，避免指针转换问题）"""
    return _user32.CallNextHookEx(hook, ctypes.c_int(nCode),
                                  ctypes.c_size_t(wParam), ctypes.c_void_p(lParam))


def _send_unicode_text(text):
    """用 SendInput(KEYEVENTF_UNICODE) 逐字注入 UTF-16 文本（中文等任意字符）。
    在钩子线程消息循环中调用（非回调栈内）。"""
    try:
        if not hasattr(_send_unicode_text, '_ready'):
            _user32.SendInput.argtypes = [
                wintypes.UINT,
                ctypes.POINTER(INPUT),
                ctypes.c_int,
            ]
            _user32.SendInput.restype = wintypes.UINT
            _send_unicode_text._ready = True
        events = []
        for ch in text:
            code = ord(ch)
            for cu in (code & 0xFFFF, (code >> 16) & 0xFFFF):
                next_ = INPUT()
                next_.type = INPUT_KEYBOARD
                next_.u.ki.wVk = 0
                next_.u.ki.wScan = cu
                next_.u.ki.dwFlags = KEYEVENTF_UNICODE
                _up = INPUT()
                _up.type = INPUT_KEYBOARD
                _up.u.ki.wVk = 0
                _up.u.ki.wScan = cu
                _up.u.ki.dwFlags = KEYEVENTF_UNICODE | KEYEVENTF_KEYUP
                events.append(next_)
                events.append(_up)
        arr = (INPUT * len(events))(*events)
        _user32.SendInput(len(events), ctypes.byref(arr), ctypes.sizeof(INPUT))
    except Exception as e:
        print('send_unicode fail:', e)


# 音频时长缓存（path → (mtime, 秒)）：避免每次播放都重读文件头
_dur_cache = {}


def audio_duration_seconds(path):
    """获取音频时长（秒），带 mtime 校验缓存"""
    try:
        st = os.stat(path)
        mtime = st.st_mtime_ns
        c = _dur_cache.get(path)
        if c and c[0] == mtime:
            return c[1]
        import soundfile as _sfx
        info = _sfx.info(path)
        d = float(info.duration)
        if len(_dur_cache) > 64:
            _dur_cache.clear()
        _dur_cache[path] = (mtime, d)
        return d
    except Exception:
        return 0.0


class PetWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.roles = list_roles()
        # 默认角色：优先角色名=DEFAULT_ROLE 的那项（无论阵营/形象），否则取列表首个
        self.role = default_role_pick(self.roles)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool                # 不占任务栏、不抢焦点
        )
        self.setWindowTitle("卡丘简易桌宠")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

        # 绑定输出设备（如 Voicemeeter Input → 声音进虚拟麦/队友）；空=不绑定走系统默认
        _cfg = load_config()
        self._bind_device = _cfg.get('bind_device', '') or ''
        # 自己监听设备（耳机/扬声器，绑定麦时同时播放给自己听）；空=不听
        self._self_device = _cfg.get('self_device', '') or ''
        # 自动按住开麦键（游戏 PTT 场景）：播放时自动按开麦键，结束松开
        self._auto_ptt = bool(_cfg.get('auto_ptt', False))
        # 开麦键（默认 V，可在菜单里改）
        self._ptt_key_name = _cfg.get('ptt_key', 'V') or 'V'
        self._ptt_vk = key_name_to_vk(self._ptt_key_name) or VK_V
        # 「启用快捷键发话」总开关
        self._hotkeys_enabled = bool(_cfg.get('hotkeys_enabled', True))
        # 小键盘 1-9 快捷播放开关（默认关！全局抢键会占用打字的小键盘数字输入）
        self._numpad_enabled = bool(_cfg.get('numpad_hotkeys', False))
        # 智能小键盘钩子（开时用低层钩子拦截 1-9，聚焦输入框自动放行）
        self._numpad_hook = None
        # 卡拉彼丘"回车自动补词"联动（默认关，需在 设置→卡丘游戏设置 开启）
        self._meow_enabled = bool(_cfg.get('meow_hotkeys', False))
        self._meow_word = str(_cfg.get('meow_word', '喵') or '喵')
        self._meow_hook = None
        # 语音自定义快捷键: { 音频key(角色/文件名): 键名 }
        self._audio_hotkeys = dict(_cfg.get('audio_hotkeys', {}))
        # 语音来源：'role'=角色专属语音（默认）/ 'common'=通用语音（任何角色共用一套）
        self._voice_source = _cfg.get('voice_source', 'role') or 'role'
        self._sd_stream = None       # 正在播放的 sounddevice 流（防 GC）

        # 自绘：窗口固定尺寸，绘制时用 scale（origin=底部中心，复刻插件 transform-origin:50% 100%）
        self.pixmap = None          # 当前角色图（静态图，或 GIF 当前帧）
        self._movie = None          # GIF 动图（角色为动图时非空）
        self._scale_x = 1.0
        self._scale_y = 1.0
        self._facing = 1.0          # 水平朝向：+1 正常 / -1 镜像（角色面向屏幕中心）
        self._pet_size = int(_cfg.get('pet_size', BASE_SIZE)) or BASE_SIZE  # 桌宠尺寸（滑块可调，持久化）
        self.setFixedSize(self._pet_size, self._pet_size)

        # 音频播放（QMediaPlayer 支持 mp3，不阻塞主线程；存 self 防 GC）
        # 打包环境下 QtMultimedia 插件可能缺失导致崩溃 → try/except 保证窗口/图片先显示
        try:
            self.player = QMediaPlayer(self)
            self.audio_out = QAudioOutput(self)
            self.player.setAudioOutput(self.audio_out)
        except Exception as e:
            self.player = None
            self.audio_out = None
            print("QMediaPlayer init fail:", e)

        # 鼠标状态
        self._down = False
        self._moved = False
        self._press_pos = None
        self._drag_offset = QPoint(0, 0)

        # 右上角三横菜单按钮（悬停显示）
        self._hovering = False      # 鼠标是否在窗口内
        self._menu_btn_hover = False  # 鼠标是否在菜单按钮上（高亮）
        self._menu_press = False      # 正在按住菜单按钮
        self._active_menu = None      # 正在显示的汉堡菜单（防 GC/同步勾选）
        self._reopen_menu = False     # 菜单项被点击后需自动重开
        self._menu_reopening = False  # 正在重开中（抑制 hide 恢复逻辑）
        self._menu_anchor = None      # 本次弹出位置（重弹时复用）
        self.setMouseTracking(True)   # 不按键也能收到 move 事件（更新按钮 hover）
        # 按钮延迟消失：鼠标离开窗口/滑过空白时不立刻隐藏，给 1 秒缓冲（快速划过仍可见）
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.setInterval(1000)  # 1 秒
        self._hide_timer.timeout.connect(self._hide_btn_now)

        # 回弹动画状态（逐帧，从当前 scale 渐变到目标，orgin=底部中心, 只变形不位移）
        self._bounce_timer = None
        self._bounce_frames = 0
        self._bounce_idx = 0
        self._anim_from_x = 1.0
        self._anim_from_y = 1.0
        self._anim_to_x = 1.0
        self._anim_to_y = 1.0
        self._anim_ease = "down"

        # 翻转动画状态：_flip_from→_flip_to 平滑过渡（+1 原朝向 → -1 镜像）
        # 用水平 scale = cos(π·t) 从 1 缩到 0 再反向展开到 -1，像"转身"
        self._flip_from = 1.0
        self._flip_to = 1.0
        self._flip_timer = None
        self._flip_frames = 0
        self._flip_idx = 0
        self._flip_scale_x = 1.0    # 当前水平翻转 scale（绘制用；无动画时=朝向）

        self.load_role(self.role)
        self.init_tray()
        self.place_default()
        # AI 对话 + TTS（可选；右键桌宠 → 聊天窗 + 气泡）
        self.ai = None
        if HAS_AI:
            try:
                self.ai = _ai_mod.AiChatManager(self)
            except Exception as _e:
                self.ai = None
                print('AiChatManager init fail:', _e)
        # 小键盘 1-9 全局热键（注册在窗口句柄上；show 后 winId 才有效）
        self._hotkey_ids = {}
        self._custom_hk_map = {}   # hid → audio_key（自定义音频快捷键）
        self._hotkey_pending = True
        self._last_hotkey_time = 0  # 防连发
        # 录制状态 / 提示浮层
        self._capture_kind = None
        self._capture_audio_key = None
        self._pending_capture = False
        self._cap = None
        self._toast_text = None
        self._toast_until = 0.0
        # 窗口显示后自动注册（show 的时机由 main() 控制，这里延后到事件循环就绪）
        QTimer.singleShot(300, self._register_hotkeys_now)
        # 若配置开启小键盘智能播放 → 启动钩子
        if self._numpad_enabled:
            QTimer.singleShot(350, self._numpad_hook_start)
        # 若配置开启卡丘回车补词 → 启动钩子
        if self._meow_enabled:
            QTimer.singleShot(400, self._meow_hook_start)
        # 空闲预解码：启动 1.5s 后在后台线程解码「当前点击语音」，让首次点击秒播
        QTimer.singleShot(1500, self._preload_click_audio)

    def _preload_click_audio(self):
        """后台预解码当前最可能播放的音频（当前角色的点击语音）→ 首次播放免等待"""
        def work():
            try:
                d = role_root(self.role)
                if not os.path.isdir(d):
                    d = role_dir(self.role)
                if not os.path.isdir(d):
                    return
                # 台词型自我介绍/集中触发音优先（与 play_click_voice 同规则）
                voice = pick_click_voice(d, role=self.role)
                if voice is None:
                    cname = role_character_name(self.role)
                    if cname == "白墨":
                        voice = os.path.join(d, "sprint.mp3")
                    elif cname == "星绘":
                        voice = os.path.join(d, self.greeting_for_now() + ".mp3")
                    else:
                        click = os.path.join(d, "click.mp3")
                        voice = click if os.path.exists(click) else os.path.join(d, "morning.mp3")
                if os.path.exists(voice) and voice not in _decode_cache:
                    _decode_and_prepare(voice)
                # 顺带预解码当前语音来源第 1 条（快捷键最常按）
                try:
                    audios = self.current_audio_list()
                    if audios and audios[0][1] not in _decode_cache:
                        _decode_and_prepare(audios[0][1])
                except Exception:
                    pass
            except Exception:
                pass
        threading.Thread(target=work, daemon=True).start()

    def _register_hotkeys_now(self):
        """窗口已显示后调用：注册所有热键（小键盘1-9默认 + 自定义键）；可重试直到成功。
        总开关关闭时不注册任何热键。优先窗口 hwnd；winId 无效回落 hwnd=0"""
        if not self._hotkey_pending:
            return
        self._hk_tries = getattr(self, '_hk_tries', 0) + 1
        if self._hk_tries > 30:  # 最多重试 ~15 秒
            _dbg('hk: give up after %d tries' % self._hk_tries)
            self._hotkey_pending = False
            return
        # 总开关关闭：不注册
        if not self._hotkeys_enabled:
            self._hotkey_ids = {}
            self._hotkey_pending = False
            _dbg('hotkeys disabled by switch')
            return
        hwnd = 0  # 兜底：线程消息队列
        try:
            wid = self.winId()
            if wid is not None:
                h = int(wid)
                if h:
                    hwnd = h
                else:
                    _dbg('hk: winId 0, use queue (%d)' % self._hk_tries)
        except Exception as e:
            _dbg('hotkey winId fail (%d): %r' % (self._hk_tries, e))
        # 先注销旧的，再全新注册（防残留/重复：custom 需先注销，
        # 否则绑定删除/更换后旧 custom 热键仍占用系统）
        try:
            for hid in list(getattr(self, '_custom_hk_map', {}).keys()):
                unregister_hotkey(hwnd, hid)
        except Exception:
            pass
        # 小键盘 1-9：不再用 RegisterHotKey（避免全局抢键），改由 NumpadPlayHook
        # 低层钩子智能拦截（聚焦输入框自动放行）。注册只负责自定义键。
        self._hotkey_ids = {}
        # 注册自定义键（音频快捷键）
        # 自定义键: hid → audio_key；跳过与默认小键盘1-9重复的键名（Num1~Num9）
        default_numpad_names = {'Num%d' % i for i in range(1, 10)}
        self._custom_hk_map = {}   # hid → audio_key
        hid_base = CUSTOM_HK_BASE
        for audio_key, key_name in self._audio_hotkeys.items():
            if key_name in default_numpad_names:
                continue  # 由小键盘钩子处理
            vk = self._resolve_vk(key_name)
            if vk is None:
                continue
            hid = hid_base + len(self._custom_hk_map)
            if register_single_hotkey(hwnd, hid, vk):
                self._custom_hk_map[hid] = audio_key
        if self._custom_hk_map:
            self._hotkey_pending = False
            _dbg('hotkeys registered: numpad(hook)=%s custom=%s hwnd=%s' % (
                self._numpad_enabled, sorted(self._custom_hk_map), hwnd))
        else:
            # 无自定义键（numpad 走钩子）→ 也算注册完成
            self._hotkey_pending = False
            _dbg('hotkeys: numpad(hook)=%s + no custom, idle' % self._numpad_enabled)

    def _resolve_vk(self, key_name):
        """键名/原始VK → 虚拟码。兼容 'VK<数字>' 格式（捕获未知名键时存储）"""
        if key_name.startswith('VK') and key_name[2:].isdigit():
            return int(key_name[2:])
        return key_name_to_vk(key_name)

    def current_audio_list(self):
        """当前语音来源下的音频列表 → [(显示名, 绝对路径)]。
        voice_source='common' → 通用语音；否则 → 当前角色语音"""
        if self._voice_source == 'common':
            return list_common_audio()
        return list_role_audio(self.role)

    def _hotkey_slot_audio(self, num):
        """小键盘数字按下：
        1) 先查当前语音来源里绑定到 Num<num> 的音频（绑定跟音频走、带来源，
           每个语音来源可各绑一套数字键，互不干扰）
        2) 无绑定 → 回退：播当前语音来源第 num 条音频（旧习惯兼容）
        """
        key_name = 'Num%d' % num
        audio_key = None
        # 当前来源下查绑定（角色专属 vs 通用语音分开）
        if self._voice_source == 'common':
            prefix = '__common__'
        else:
            prefix = self.role
        for k, v in self._audio_hotkeys.items():
            if v == key_name and k.rsplit('/', 1)[0] == prefix:
                audio_key = k
                break
        if audio_key:
            self._custom_hotkey_audio(audio_key)
            return
        # 回退：按位置取当前来源第 num 条
        audios = self.current_audio_list()
        if not audios:
            return
        idx = num - 1
        if 0 <= idx < len(audios):
            label, path = audios[idx]
            self.play_audio(path)

    def _custom_hotkey_audio(self, audio_key):
        """按自定义音频快捷键播放对应音频（audio_key = 角色名/文件名 或 __common__/文件名）"""
        try:
            role_name, fname = audio_key.rsplit('/', 1)
        except ValueError:
            return
        if role_name == '__common__':
            path = os.path.join(common_voice_dir(), fname)
        else:
            path = os.path.join(role_dir(role_name), fname)
        if os.path.exists(path):
            # 若当前角色不符且该角色存在 → 临时切角色播放? 用户期望的是"当前角色"的按键
            # 简化为：直接播放该文件（跨角色也可）
            self.play_audio(path)

    def nativeEvent(self, eventType, message):
        """捕获 WM_HOTKEY（数字键/自定义键 → 播放对应音频）
        注意：①绝不在消息回调里触发窗口操作（防递归崩溃）
        ②必须始终返回 (bool, int) 元组（PyQt6 要求），未处理返回 (False, 0)"""
        try:
            if eventType == b'windows_generic_MSG':
                msg = ctypes.wintypes.MSG.from_address(int(message))
                if msg.message == WM_HOTKEY:
                    hid = msg.wParam
                    now = time.monotonic()
                    if now - self._last_hotkey_time < 0.1:
                        return True, 0  # 防抖
                    self._last_hotkey_time = now
                    # 自定义键优先
                    if hid in self._custom_hk_map:
                        self._custom_hotkey_audio(self._custom_hk_map[hid])
                        return True, 0
                    # 数字回退
                    for num, hid2 in self._hotkey_ids.items():
                        if hid == hid2:
                            self._hotkey_slot_audio(num)
                            return True, 0
        except Exception as e:
            print('nativeEvent err:', e)
        return False, 0

    def showEvent(self, e):
        """窗口显示后注册全局热键（winId 此时有效）"""
        super().showEvent(e)
        _dbg('showEvent fired, pending=' + str(self._hotkey_pending))
        if self._hotkey_pending:
            QTimer.singleShot(200, self._register_hotkeys_now)

    def closeEvent(self, e):
        """退出前注销热键、停止动图与钩子"""
        try:
            self._stop_movie()
        except Exception:
            pass
        try:
            self._numpad_hook_stop()
        except Exception:
            pass
        try:
            self._meow_hook_stop()
        except Exception:
            pass
        try:
            ai = getattr(self, 'ai', None)
            if ai is not None and hasattr(ai, 'close_all'):
                ai.close_all()
        except Exception:
            pass
        try:
            hwnd = int(self.winId())
            for hid in list(getattr(self, '_custom_hk_map', {}).keys()):
                unregister_hotkey(hwnd, hid)
        except Exception:
            pass
        super().closeEvent(e)

    # ------------- 角色 -------------
    def _stop_movie(self):
        """停止 GIF 动画（切角色/退出时调用）"""
        if self._movie is not None:
            try:
                self._movie.stop()
                self._movie.frameChanged.disconnect()
            except Exception:
                pass
            self._movie = None

    def _set_role_frame(self, frame_no):
        """GIF 帧更新：缩放后赋给 self.pixmap（保持 paintEvent/按压动画不变）"""
        try:
            if self._movie is None:
                return
            pm = self._movie.currentPixmap()
            if pm.isNull():
                return
            sz = self._pet_size
            pm = pm.scaled(sz, sz, Qt.AspectRatioMode.KeepAspectRatio,
                           Qt.TransformationMode.SmoothTransformation)
            self.pixmap = pm
            self.update()
        except Exception:
            pass

    def load_role(self, role):
        if role not in self.roles:
            role = self.roles[0]
        self.role = role
        self._stop_movie()
        self.pixmap = None
        self._src_pixmap = None   # 未缩放的原图（静态角色）；供实时调尺寸用
        rdir = role_dir(role)
        found = role_image(rdir)  # (路径, kind: 'png'|'gif')，支持 image.png / 动图 gif.webp / 各图片格式
        if found:
            img, kind = found
            sz = self._pet_size
            if kind == 'gif':
                # 动图：QMovie 播放（gif/webp），首帧立即显示
                try:
                    mv = QMovie(img)
                    if mv.isValid() and mv.frameCount() > 1:
                        mv.frameChanged.connect(self._set_role_frame)
                        self._movie = mv
                        mv.start()
                        pm = mv.currentPixmap()
                        if pm.isNull():
                            mv.jumpToFrame(0)
                            pm = mv.currentPixmap()
                        self._src_pixmap = pm if not pm.isNull() else None
                    else:
                        pm = mv.currentPixmap()
                        self._src_pixmap = pm if not pm.isNull() else None
                    if not pm.isNull():
                        pm = pm.scaled(sz, sz, Qt.AspectRatioMode.KeepAspectRatio,
                                       Qt.TransformationMode.SmoothTransformation)
                        self.pixmap = pm
                    elif mv.isValid() and mv.frameCount() <= 1:
                        # 静态 webp/gif：当静态图处理
                        pm2 = QPixmap(img)
                        if not pm2.isNull():
                            self._src_pixmap = pm2
                            pm2 = pm2.scaled(sz, sz, Qt.AspectRatioMode.KeepAspectRatio,
                                             Qt.TransformationMode.SmoothTransformation)
                            self.pixmap = pm2
                except Exception as e:
                    print('QMovie load fail:', e)
                    self._movie = None
                    pm2 = QPixmap(img)
                    if not pm2.isNull():
                        self._src_pixmap = pm2
                        pm2 = pm2.scaled(sz, sz, Qt.AspectRatioMode.KeepAspectRatio,
                                         Qt.TransformationMode.SmoothTransformation)
                        self.pixmap = pm2
            else:
                pm = QPixmap(img)
                if not pm.isNull():
                    self._src_pixmap = pm
                    pm = pm.scaled(sz, sz, Qt.AspectRatioMode.KeepAspectRatio,
                                   Qt.TransformationMode.SmoothTransformation)
                    self.pixmap = pm
        self._scale_x = 1.0
        self._scale_y = 1.0
        self.setFixedSize(self._pet_size, self._pet_size)
        self.update()

    def set_pet_size(self, size):
        """调整桌宠大小（px）：实时改窗口 + 重载当前角色图到新尺寸，并持久化"""
        size = int(size)
        if size < 60:
            size = 60
        if size > 600:
            size = 600
        if size == self._pet_size:
            return
        self._pet_size = size
        # 保持窗口中心不变（缩放时居中微调，避免跳走）
        try:
            geo = self.frameGeometry()
            cx = geo.center().x()
            cy = geo.center().y()
        except Exception:
            cx = cy = None
        self.setFixedSize(size, size)
        if cx is not None:
            self.move(cx - size // 2, cy - size // 2)
            try:
                if self.ai is not None:
                    self.ai.pet_moved()
            except Exception:
                pass
        # 静态角色：从原图直接重缩放（丝滑）；动图角色：重建 QMovie（帧尺寸跟随）
        if self._movie is None and self._src_pixmap is not None and not self._src_pixmap.isNull():
            pm = self._src_pixmap.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                                         Qt.TransformationMode.SmoothTransformation)
            self.pixmap = pm
            self.update()
        else:
            role = self.role
            self.load_role(role)
        # 持久化
        cfg = load_config()
        cfg['pet_size'] = size
        save_config(cfg)
        self._clamp_to_screen(self.x(), self.y())
        self._update_facing()

    # ------------- 播放 -------------
    def _target_devices(self):
        """当前播放目标设备集合（去重）：
        绑定麦克风设备（给队友）+ 自己监听设备（自己听）"""
        devs = []
        if self._bind_device:
            devs.append(self._bind_device)
        if self._self_device and self._self_device != self._bind_device:
            devs.append(self._self_device)
        return devs

    def play_audio(self, path, ptt_override=None):
        """播放指定音频文件：
        - 有绑定/监听设备 → sounddevice 并行直出到这些设备
          （绑定麦给队友 + 自己耳机自己听），期间按需触发 auto_ptt
        - 都没有 → QMediaPlayer 走系统默认输出，期间同样按需触发 auto_ptt
        ptt_override: True/False 强制开启/关闭自动开麦键（默认 None=跟随设置）；
        点击桌宠本体播放传 False —— 防止在打字/聊天时注入开麦键字母污染输入
        """
        if not os.path.exists(path):
            return
        # 同文件 300ms 去抖：快速连点/连按同一语音时不叠加重播（避免嘈杂）
        now_m = time.monotonic()
        if path == getattr(self, '_last_play_path', None) and \
                now_m - getattr(self, '_last_play_time', 0.0) < 0.3:
            return
        self._last_play_path = path
        self._last_play_time = now_m
        ptt_on = self._auto_ptt if ptt_override is None else bool(ptt_override)
        targets = self._target_devices()
        if targets and HAS_SD:
            threading.Thread(target=self._play_direct_worker,
                             args=(path, targets, ptt_on), daemon=True).start()
            return
        # 默认模式：QMediaPlayer（auto_ptt 也要生效）
        if self.player is None:
            return
        try:
            if ptt_on:
                ptt_key_down(self._ptt_vk)
            self.player.stop()
            self.player.setSource(QUrl.fromLocalFile(path))
            self.player.setPosition(0)
            self.player.play()
        except Exception as e:
            print("play error:", e)

        # 音频播完（按时长估算）后松开开麦键
        if ptt_on:
            dur = audio_duration_seconds(path)
            def _release_ptt():
                time.sleep(dur + PTT_HOLD_EXTRA_S)
                ptt_key_up(self._ptt_vk)
            threading.Thread(target=_release_ptt, daemon=True).start()

    def _play_direct_worker(self, path, targets, ptt_on=None):
        """后台线程：向多个设备并行播放；若 ptt_on，播放开始即按住开麦键，
        音频播完后再多按 0.5 秒松开（防尾部被切）。全部失败回主线程回退 QMediaPlayer"""
        if ptt_on is None:
            ptt_on = self._auto_ptt
        if ptt_on:
            ptt_key_down(self._ptt_vk)  # 按住开麦键（队友听得到）
        try:
            ok = play_audio_multi(path, targets)
        finally:
            if ptt_on:
                # 音频结束后延时 PTT_HOLD_EXTRA_S 再松开（尾部不切音）
                time.sleep(PTT_HOLD_EXTRA_S)
                ptt_key_up(self._ptt_vk)
        if ok == 0 and self.player is not None:
            # 直出失败（如设备临时拔出）→ 调度回主线程回退默认播放
            def fallback():
                try:
                    self.player.stop()
                    self.player.setSource(QUrl.fromLocalFile(path))
                    self.player.setPosition(0)
                    self.player.play()
                except Exception as e:
                    print("play fallback error:", e)
            QTimer.singleShot(0, fallback)

    def play_click_voice(self):
        d = role_root(self.role)
        if not os.path.isdir(d):
            d = role_dir(self.role)
        # 1) 优先播集中触发音（trigger_voice/<角色名>/卡拉彼丘.mp3）或台词型自我介绍
        voice = pick_click_voice(d, role=self.role)
        # 2) 无触发音 → 按角色旧规则（星绘时段问候/白墨冲刺/其它 morning）
        if voice is None:
            cname = role_character_name(self.role)
            if cname == "白墨":
                voice = os.path.join(d, "sprint.mp3")
            elif cname == "星绘":
                voice = os.path.join(d, self.greeting_for_now() + ".mp3")
            else:
                click = os.path.join(d, "click.mp3")
                voice = click if os.path.exists(click) else os.path.join(d, "morning.mp3")
        if os.path.exists(voice):
            # 点击语音：强制不开 auto_ptt（避免打字时误注入开麦键）
            self.play_audio(voice, ptt_override=False)

    @staticmethod
    def greeting_for_now():
        h = datetime.now().hour
        if 6 <= h < 12:
            return "morning"
        if 12 <= h < 18:
            return "noon"
        return "evening"

    # ------------- 按压动画（自绘 scale，origin=底部中心，只变形不位移，复刻插件 transform-origin:50% 100%）--------------
    def paintEvent(self, ev):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        if self.pixmap is not None:
            # 角色图：以底部中心为 origin 做 scaleX/scaleY（只变形不位移）
            # 水平方向乘 _flip_scale_x：静止 = ±1（面向屏幕中心），翻转动画中
            # 平滑过 0（角色压成一线再展开 = 转身），与按压动画的 scale 相乘不冲突
            painter.save()
            w = self.width()
            h = self.height()
            painter.translate(w / 2.0, h)
            painter.scale(self._scale_x * self._flip_scale_x, self._scale_y)
            painter.translate(-w / 2.0, -h)
            painter.drawPixmap(0, 0, w, h, self.pixmap)
            painter.restore()
        # 右上角三横菜单按钮（悬停才显示；不随角色动画缩放，始终固定）
        if self._hovering:
            self._paint_menu_btn(painter)
        # 提示浮层（toast / 录制提示）
        self._paint_toast(painter)
        painter.end()

    def _paint_toast(self, p):
        """在窗口上半部绘制提示文字（绑定成功/录制中/取消）"""
        text = getattr(self, '_toast_text', None)
        recording = getattr(self, '_capture_kind', None) is not None or \
            getattr(self, '_pending_capture', False)
        if recording:
            text = '按一个键绑定…（Esc 取消）'
        if not text:
            return
        from PyQt6.QtGui import QFont, QFontMetrics
        p.setFont(QFont('Microsoft YaHei', 10))
        fm = QFontMetrics(p.font())
        tw = fm.horizontalAdvance(text)
        # 气泡底色（半透明深色圆角）
        bw = tw + 24
        bh = 30
        bx = (self.width() - bw) / 2
        by = 8
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(20, 22, 30, 220))
        p.drawRoundedRect(int(bx), int(by), int(bw), int(bh), 10, 10)
        # 描边
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 60), 1))
        p.drawRoundedRect(int(bx), int(by), int(bw), int(bh), 10, 10)
        # 文字
        p.setPen(QColor(255, 255, 255, 240))
        p.drawText(QRect(int(bx), int(by), int(bw), int(bh)),
                   Qt.AlignmentFlag.AlignCenter, text)

    # 右上角三横按钮：几何区
    def _menu_btn_rect(self):
        s = MENU_BTN_SIZE
        m = MENU_BTN_MARGIN
        return QRect(self.width() - s - m, m, s, s)

    def _paint_menu_btn(self, p):
        rect = self._menu_btn_rect()
        p.setPen(Qt.PenStyle.NoPen)
        # 半透明圆角底：默认深色，hover/按下时提亮
        if self._menu_btn_hover or self._menu_press:
            p.setBrush(QColor(255, 255, 255, 70))
        else:
            p.setBrush(QColor(0, 0, 0, 90))
        p.drawRoundedRect(rect, 8, 8)
        # 三横线（白色圆头）
        p.setPen(QPen(QColor(255, 255, 255, 235), 2.2, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap))
        cx = rect.center().x()
        half = 6
        for y in (rect.center().y() - 4, rect.center().y(), rect.center().y() + 4):
            p.drawLine(cx - half, y, cx + half, y)

    def _set_scale(self, sx, sy):
        # 只改缩放状态 + 重绘；窗口矩形不动 → 绝不位移/震动
        self._scale_x = sx
        self._scale_y = sy
        self.update()

    # 通用逐帧缩放动画：从当前 scale 渐变到 (fx, fy)，时长 ms，ease='down'|'bounce'
    def animate_scale(self, fx, fy, duration_ms, ease="down"):
        if self._bounce_timer is not None:
            self._bounce_timer.stop()
        self._anim_from_x = self._scale_x
        self._anim_from_y = self._scale_y
        self._anim_to_x = fx
        self._anim_to_y = fy
        self._anim_ease = ease
        self._bounce_frames = max(8, int(duration_ms / 16))
        self._bounce_idx = 0
        self._bounce_timer = QTimer(self)
        self._bounce_timer.setInterval(16)
        self._bounce_timer.timeout.connect(self._bounce_step)
        self._bounce_timer.start()

    # ease 值：0..1 → progress（down 用 ease-out 快速压；bounce 用过冲回弹）
    def _bezier(self, t, ease):
        if t <= 0.0:
            return 0.0
        if t >= 1.0:
            return 1.0
        if ease == "down":
            # 快速下压（ease-out）：前段快、后段缓
            return 1.0 - (1.0 - t) * (1.0 - t)
        # bounce：先快回、一次轻微过冲（峰值~1.11）、末归1（复刻 cubic-bezier(.34,1.56,.64,1)）
        return 1.0 + 0.13 * math.sin(math.pi * t) * math.exp(-1.6 * t)

    def _bounce_step(self):
        self._bounce_idx += 1
        t = self._bounce_idx / float(self._bounce_frames)
        if t >= 1.0:
            self._set_scale(self._anim_to_x, self._anim_to_y)
            if self._bounce_timer is not None:
                self._bounce_timer.stop()
                self._bounce_timer = None
            return
        e = self._bezier(t, self._anim_ease)
        sx = self._anim_from_x + (self._anim_to_x - self._anim_from_x) * e
        sy = self._anim_from_y + (self._anim_to_y - self._anim_from_y) * e
        self._set_scale(sx, sy)

    def press_down(self):
        # 按下：从 1.0 快速压扁到 (1.05, 0.88)，时长 ~110ms（能看到"压下去"）
        self.animate_scale(1.05, 0.88, duration_ms=110, ease="down")

    def press_up(self, was_click):
        # 松开：从压扁态弹性回弹到 1.0，时长 ~520ms（慢、带明显回弹），不位移
        self.animate_scale(1.0, 1.0, duration_ms=520, ease="bounce")
        if was_click:
            # 点击桌宠本体播放的"点击语音"：不开 auto_ptt（避免在打字/聊天时误注入开麦键打出字母）
            self.play_click_voice()

    def _clamp_to_screen(self, x, y):
        """把窗口左上角 (x,y) 限制在鼠标所在屏幕的可用区域内（不许拖出屏幕）"""
        try:
            scr = QApplication.screenAt(QPoint(x + self.width() // 2, y + self.height() // 2))
        except Exception:
            scr = None
        if scr is None:
            scr = QApplication.primaryScreen()
        if scr is None:
            return x, y
        g = scr.availableGeometry()
        x = max(g.left(), min(x, g.right() - self.width() + 1))
        y = max(g.top(), min(y, g.bottom() - self.height() + 1))
        return x, y

    def _update_facing(self):
        """根据窗口中心相对屏幕的位置决定朝向并播放水平翻转动画：
        （窗口在屏幕左半边 → 脸朝右 +1；右半边 → 脸朝左 -1）
        翻转用水平 scale 平滑过渡（cos 曲线：1→0→-1 = 转身），不瞬间生硬镜像"""
        try:
            scr = QApplication.screenAt(self.frameGeometry().center())
        except Exception:
            scr = None
        if scr is None:
            scr = QApplication.primaryScreen()
        if scr is None:
            return
        g = scr.availableGeometry()
        cx = self.frameGeometry().center().x()
        mid = (g.left() + g.right()) / 2.0
        want = 1.0 if cx <= mid else -1.0
        if want != self._facing:
            # 翻转动画：from 恒为 ±1（当前朝向），曲线 ±1→0→∓1 平滑转身
            self._flip_from = self._facing
            self._flip_to = want
            self._facing = want  # 目标朝向先记下；绘制用动画进度
            self._start_flip_anim()

    def _start_flip_anim(self):
        """启动水平翻转动画（约 0.3s：先水平压窄到一线，再反向展开 = 转身）"""
        if self._flip_timer is not None:
            self._flip_timer.stop()
        self._flip_frames = 18  # 18 帧 ≈ 0.29s @ 16ms
        self._flip_idx = 0
        self._flip_scale_x = self._flip_from  # 当前水平 scale
        self._flip_timer = QTimer(self)
        self._flip_timer.setInterval(16)
        self._flip_timer.timeout.connect(self._flip_step)
        self._flip_timer.start()

    def _flip_step(self):
        """翻转动画逐帧：水平 scale = from * cos(πt)
        t=0 → from；t=0.5 → 0（角色水平压成一线）；t=1 → -from = to（转身完成）
        from/to 恒为 ±1 且相反，一条公式全程平滑"""
        self._flip_idx += 1
        t = self._flip_idx / float(self._flip_frames)
        if t >= 1.0:
            self._flip_scale_x = self._flip_to
            if self._flip_timer is not None:
                self._flip_timer.stop()
                self._flip_timer = None
        else:
            self._flip_scale_x = self._flip_from * math.cos(math.pi * t)
        self.update()

    def place_default(self):
        scr = QApplication.primaryScreen().availableGeometry()
        self.move(scr.right() - self.width() - 24, scr.bottom() - self.height() - 24)
        self._update_facing()  # 默认右下角 → 右半屏 → 脸朝左

    def init_tray(self):
        """创建托盘图标（仅一次，避免图标堆积）。菜单更新走 refresh_tray"""
        self.tray = QSystemTrayIcon(self)
        # 托盘图标：优先当前角色形象；找不到再找默认星绘；缩放到 32px
        img_path = None
        for probe in (self.role, DEFAULT_ROLE):
            try:
                rd = role_dir(probe)
                if os.path.isdir(rd):
                    found = role_image(rd)
                    if found:
                        img_path = found[0]
                        break
            except Exception:
                continue
        if img_path and os.path.exists(img_path):
            pm = QPixmap(img_path)
            if not pm.isNull():
                pm = pm.scaled(32, 32, Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
                self.tray.setIcon(QIcon(pm))
        self.tray.setToolTip("卡丘简易桌宠")
        self.refresh_tray_menu()
        # 单击托盘图标也弹出菜单（右键由 setContextMenu 处理）
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    def refresh_tray_menu(self):
        """更新托盘菜单（复用同一图标，不新建 → 不会堆积多个托盘图标）"""
        if not hasattr(self, 'tray'):
            return
        menu = self._build_role_menu(None)  # 托盘图标非 QWidget，parent 用 None
        self._tray_menu = menu  # 存引用防 GC
        self.tray.setContextMenu(menu)

    def _on_tray_activated(self, reason):
        # Trigger = 左键单击 → 打开设置面板；右键仍走托盘 contextMenu
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.open_settings_panel()

    def _fill_roles_menu(self, m):
        """把全部可用角色填进子菜单，按阵营分组（阵营标题不可点，勾选当前角色）。
        role 含 '/' → 阵营/角色 分组；纯角色名（历史平铺）→ 直接列出。
        同一角色多形象（阵营/角色/形象）→ 各形象分行显示「角色·形象」。"""
        roles = list(self.roles)
        # 分出带阵营的角色
        factioned = [r for r in roles if role_faction(r)]
        flat = [r for r in roles if not role_faction(r)]
        cur = self.role
        group = QActionGroup(m)
        group.setExclusive(True)
        added = 0

        def add_item(text, role_key):
            act = QAction(text, m)
            act.setCheckable(True)
            act.setChecked(role_key == cur)
            act.triggered.connect(lambda checked, rr=role_key: self.switch_role(rr))
            group.addAction(act)
            m.addAction(act)

        # 未分组（历史平铺）角色排最前
        for r in flat:
            add_item(role_display(r), r)
            added += 1

        # 按阵营分组显示
        by_faction = {}
        for r in factioned:
            by_faction.setdefault(role_faction(r), []).append(r)
        for fac in sorted(by_faction):
            if added:
                m.addSeparator()
            title = QAction(fac, m)
            title.setEnabled(False)
            m.addAction(title)
            for r in sorted(by_faction[fac], key=role_display):
                add_item(role_display(r), r)
            added += 1

        if not added:
            na = QAction("（无角色）", m)
            na.setEnabled(False)
            m.addAction(na)

    def _build_role_menu(self, parent):
        """构建主菜单（三横/托盘共用）：
        ①「切换角色」→ 点击向右扩展角色子菜单（当前角色 ✓）
        ─ 分隔线 ─
        ② 当前角色的全部音频（点一下即播放）
        ─ 分隔线 ─
        ③ 退出
        """
        menu = QMenu(parent)
        menu.setStyleSheet(MENU_QSS)

        # ① 切换角色：点击后 _open_switch_submenu 在其右侧弹出角色子菜单
        #   （PyQt6/Qt6 无 QAction.setPopupMode；且模态 exec 内不能再 exec，
        #    故角色列表用非模态 popup 方式"向右展开"，行为=点一下右扩）
        self._switch_submenu = QMenu(menu)   # 存引用防 GC
        self._switch_submenu.setStyleSheet(MENU_QSS)
        self._fill_roles_menu(self._switch_submenu)
        act_switch = QAction("切换角色", menu)
        act_switch.setMenu(self._switch_submenu)   # 关联子菜单 → 原生"指向即开"
        menu.addAction(act_switch)

        # ①-AI 用量子菜单（仅展示累计用量/详情；对话条已改悬停自动弹出）
        act_ai = QAction("AI 用量", menu)
        act_ai.setMenu(self._build_ai_menu(menu))
        menu.addAction(act_ai)

        # ② 绑定麦克风/输出（给队友听）: 右扩设备列表
        act_bind = QAction("绑定麦克风（队友听）", menu)
        act_bind.setMenu(self._build_device_submenu('bind'))
        if self._bind_device:
            act_bind.setText("绑定麦克风 ✓ " + short_device_name(self._bind_device))
        else:
            act_bind.setText("绑定麦克风…（未绑定）")
        menu.addAction(act_bind)

        # ③ 自己监听设备（绑麦同时自己听）：右扩设备列表
        act_self = QAction("自己监听（耳机）", menu)
        act_self.setMenu(self._build_device_submenu('self'))
        if self._self_device:
            act_self.setText("自己监听 ✓ " + short_device_name(self._self_device))
        else:
            act_self.setText("自己监听…（不听）")
        menu.addAction(act_self)

        # ④ 自动按住开麦键（打勾=开启；游戏 PTT 场景，播音频自动按开麦键队友才听得到）
        act_ptt = QAction("自动按开麦键（PTT）", menu)
        act_ptt.setCheckable(True)
        act_ptt.setChecked(self._auto_ptt)
        act_ptt.triggered.connect(lambda checked: self.set_auto_ptt(checked))
        menu.addAction(act_ptt)

        # ⑤ 开麦键选择（子菜单：常用键 + 自定义录制）
        act_pttkey = QAction("开麦键：%s" % self._ptt_key_name, menu)
        act_pttkey.setMenu(self._build_ptt_key_submenu())
        menu.addAction(act_pttkey)

        # ⑥ 「启用快捷键发话」总开关
        act_hken = QAction("启用快捷键发话", menu)
        act_hken.setCheckable(True)
        act_hken.setChecked(self._hotkeys_enabled)
        act_hken.triggered.connect(lambda checked: self.set_hotkeys_enabled(checked))
        menu.addAction(act_hken)

        # ⑦ 小键盘 1-9 快捷播放（智能：聚焦输入框自动放行，正常打字不打扰）
        act_numpad = QAction("小键盘1-9快捷播放", menu)
        act_numpad.setCheckable(True)
        act_numpad.setChecked(self._numpad_enabled)
        act_numpad.setToolTip("智能模式：在游戏/桌面按小键盘1-9播放语音；聚焦输入框打字时自动放行数字输入")
        act_numpad.triggered.connect(lambda checked: self.set_numpad_enabled(checked))
        menu.addAction(act_numpad)

        menu.addSeparator()

        # 语音来源切换（角色专属 / 通用语音）
        act_voice_src = QAction(
            "语音来源：通用语音" if self._voice_source == 'common' else "语音来源：当前角色",
            menu)
        act_voice_src.setMenu(self._build_voice_source_submenu())
        menu.addAction(act_voice_src)

        # ② 当前语音来源全部音频（点一下=绑定快捷键；右侧显示已绑键；♫=试听）
        audios = self.current_audio_list()
        if audios:
            for label, path in audios:
                akey = self._audio_key_for_path(path)
                bound = self._audio_hotkeys.get(akey, '')
                txt = "♪ " + label
                if bound:
                    txt += "   [" + bound + "]"
                act = QAction(txt, menu)
                act.setToolTip("点击设置快捷键（再按任意键）；Esc 取消")
                act.triggered.connect(
                    lambda checked, ak=akey: self._on_audio_item_click(ak))
                menu.addAction(act)
        else:
            na = QAction("（无音频）", menu)
            na.setEnabled(False)
            menu.addAction(na)

        menu.addSeparator()

        # ③ 退出
        act_quit = QAction("退出", menu)
        act_quit.triggered.connect(QApplication.quit)
        menu.addAction(act_quit)
        return menu

    def _audio_key(self, role, path):
        """音频唯一 key：角色名/文件名（跨角色稳定）"""
        fname = os.path.basename(path)
        return "%s/%s" % (role, fname)

    def _audio_key_for_path(self, path):
        """按路径自动生成音频 key：通用语音目录内 → __common__/文件名；
        否则 → 角色名/文件名"""
        try:
            if os.path.dirname(path) == common_voice_dir():
                return "__common__/%s" % os.path.basename(path)
        except Exception:
            pass
        return self._audio_key(self.role, path)

    def set_voice_source(self, source):
        """切换语音来源：'role'=角色专属 / 'common'=通用语音。持久化并刷新"""
        self._voice_source = 'common' if source == 'common' else 'role'
        cfg = load_config()
        cfg['voice_source'] = self._voice_source
        save_config(cfg)
        self.refresh_tray_menu()
        self._schedule_menu_refresh()
        # 同步打开的面板
        if getattr(self, '_settings_panel', None) is not None:
            self._settings_panel.refresh_all()
            self._settings_panel._watch_current_dir()
        print('voice_source ->', self._voice_source)

    def _build_voice_source_submenu(self):
        """语音来源切换子菜单：当前角色（专属）/ 通用语音（共用一套）"""
        menu = QMenu(self)
        menu.setStyleSheet(MENU_QSS)
        grp = QActionGroup(menu)
        grp.setExclusive(True)
        n_common = len(list_common_audio())
        # 当前角色
        act_role = QAction("当前角色（%s）" % role_display(self.role), menu)
        act_role.setCheckable(True)
        act_role.setChecked(self._voice_source != 'common')
        act_role.triggered.connect(lambda c: self.set_voice_source('role'))
        grp.addAction(act_role)
        menu.addAction(act_role)
        # 通用语音
        act_common = QAction("通用语音（%d 条）" % n_common, menu)
        act_common.setCheckable(True)
        act_common.setChecked(self._voice_source == 'common')
        act_common.triggered.connect(lambda c: self.set_voice_source('common'))
        grp.addAction(act_common)
        menu.addAction(act_common)
        return menu

    def _build_ptt_key_submenu(self):
        """开麦键选择子菜单：常用键 + 「自定义…」"""
        menu = QMenu(self)
        menu.setStyleSheet(MENU_QSS)
        grp = QActionGroup(menu)
        grp.setExclusive(True)
        # 常用开麦键
        for k in ['V', 'B', 'C', 'X', 'Z', 'Alt', 'Ctrl', 'Shift', 'F1', 'F2', 'F3', 'F4', 'F5']:
            act = QAction(k, menu)
            act.setCheckable(True)
            act.setChecked(self._ptt_key_name == k)
            act.triggered.connect(lambda checked, kk=k: self.set_ptt_key(kk))
            grp.addAction(act)
            menu.addAction(act)
        menu.addSeparator()
        act_custom = QAction("自定义…（按一个键）", menu)
        act_custom.triggered.connect(lambda checked: self._begin_capture_ptt())
        menu.addAction(act_custom)
        return menu

    def _build_device_submenu(self, kind):
        """构建设备选择子菜单。kind='bind'→设置队友麦；kind='self'→设置自己监听。
        公共：列 WASAPI 输出设备（勾选当前）+「不绑定/不听」项"""
        menu = QMenu(self)
        menu.setStyleSheet(MENU_QSS)
        grp = QActionGroup(menu)
        grp.setExclusive(True)
        cur = self._bind_device if kind == 'bind' else self._self_device
        # 「无」项：bind 显示"不绑定（系统默认）"，self 显示"不听（关闭）"
        if kind == 'bind':
            none_label = "不绑定（系统默认）"
        else:
            none_label = "不听（关闭自己监听）"
        act_none = QAction(none_label, menu)
        act_none.setCheckable(True)
        act_none.setChecked(not cur)
        if kind == 'bind':
            act_none.triggered.connect(lambda c: self.set_bind_device(''))
        else:
            act_none.triggered.connect(lambda c: self.set_self_device(''))
        grp.addAction(act_none)
        menu.addAction(act_none)
        # 设备列表
        devices = list_output_devices()
        if not devices:
            na = QAction("（未检测到设备）", menu)
            na.setEnabled(False)
            menu.addAction(na)
        for name, idx in devices:
            act = QAction(name, menu)
            act.setCheckable(True)
            act.setChecked(name == cur)
            act.setToolTip("输出到: %s" % name)
            if kind == 'bind':
                act.triggered.connect(lambda c, n=name: self.set_bind_device(n))
            else:
                act.triggered.connect(lambda c, n=name: self.set_self_device(n))
            grp.addAction(act)
            menu.addAction(act)
        return menu

    def _popup_menu_at(self, anchor):
        """非模态弹出主菜单；用 aboutToHide 自动重开实现"点选项不关闭"。
        点击菜单项 → Qt 正常处理(triggered/勾选) → 菜单关闭(aboutToHide) →
        若置了 _reopen_menu 则立即重开(视觉无中断)；点菜单外/Esc 不置标志 → 不重开"""
        self._menu_anchor = anchor
        self._reopen_menu = False
        menu = self._build_role_menu(self)
        self._active_menu = menu  # 存引用防 GC
        self._hide_timer.stop()   # 菜单打开期间不做延迟隐藏
        # 菜单弹出后，鼠标移出窗口也会触发 leave；隐藏按钮但保持 hover 状态
        self._hovering = False
        self._menu_btn_hover = False
        self.update()

        # aboutToHide: 关闭瞬间若需重开则调度（延迟 30ms 等 hide 完成）
        def on_about_hide():
            if getattr(self, '_reopen_menu', False):
                self._reopen_menu = False
                self._menu_reopening = True
                QTimer.singleShot(30, lambda: self._popup_menu_at(self._menu_anchor))
        menu.aboutToHide.connect(on_about_hide)
        # 关闭后恢复悬停态（仅当不重开时）
        def on_hidden():
            if not getattr(self, '_menu_reopening', False):
                gp = QCursor.pos()
                inside = self.geometry().contains(gp)
                self._hovering = inside
                self._menu_btn_hover = inside and \
                    self._menu_btn_rect().contains(self.mapFromGlobal(gp))
                if not inside:
                    self._hide_timer.start()
                self.update()
        menu.aboutToHide.connect(on_hidden)
        menu.popup(anchor)

    # ---------- AI 子菜单（右键/三横/托盘共用） ----------
    def _build_ai_menu(self, parent):
        """构建 AI 用量子菜单（右键/三横/托盘共用）：
        📊 用量·积分（累计）+ 📈 查看统计详情
        AI 交互（对话条）已改为鼠标悬停桌宠自动弹出，不再需要菜单入口。"""
        ai = getattr(self, 'ai', None)
        enabled = ai is not None and ai.enabled()
        menu = QMenu(parent)
        menu.setStyleSheet(MENU_QSS)
        menu.setTitle("AI 用量")

        if not enabled:
            act_off = QAction("AI 未启用（去 设置→AI 开启）", menu)
            act_off.setEnabled(False)
            menu.addAction(act_off)
            return menu

        # 用量·积分（仅展示不可点）
        try:
            stxt = ai.stats_short()
            act_stats = QAction("📊 用量·积分：" + stxt, menu)
        except Exception:
            act_stats = QAction("📊 用量·积分", menu)
        act_stats.setEnabled(False)
        act_stats.setToolTip("累计对话 token 消耗统计")
        menu.addAction(act_stats)

        # 详情弹气泡（复用 manager 的提示气泡展示完整统计）
        act_detail = QAction("📈 查看统计详情", menu)
        act_detail.triggered.connect(lambda _c: self._show_ai_stats_detail(ai))
        menu.addAction(act_detail)
        return menu

    def _popup_ai_menu(self, gpos):
        """右键桌宠弹出 AI 快捷菜单（直接展示 AI 项，不包「AI」标题）"""
        ai = getattr(self, 'ai', None)
        if ai is None or not ai.enabled():
            return
        menu = self._build_ai_menu(self)
        # 右键已确定 AI 启用，去掉可能出现的"未启用"提示项
        for a in menu.actions():
            if a.text().startswith('AI 未启用'):
                menu.removeAction(a)
        self._active_menu = menu
        self._hide_timer.stop()
        self._hovering = False
        self.update()
        menu.popup(gpos)

    def _show_ai_stats_detail(self, ai):
        """在桌宠旁气泡展示完整用量统计"""
        try:
            txt = ai.stats_text()
            if hasattr(ai, '_bubble_msg'):
                ai._bubble_msg('📊 ' + txt.replace('\n', ' · '))
        except Exception:
            pass

    def switch_role(self, role):
        self.load_role(role)
        self.refresh_tray_menu()
        self._schedule_menu_refresh()
        # 同步角色的 AI 专属配置：TTS 克隆参考 + 系统提示词（切角色自动换人设/音色）
        self._apply_role_ai_profile(role)
        # 同步打开的面板：刷新列表 + 重新监视新角色的目录
        if getattr(self, '_settings_panel', None) is not None:
            try:
                self._settings_panel.refresh_all()
                self._settings_panel._watch_current_dir()
            except Exception:
                pass

    def _apply_role_ai_profile(self, role):
        """切换角色时自动更新 AI 配置（TTS 克隆音色 + 系统提示词）：
        - TTS 克隆参考：assets/tts_refs/<角色名>/ref.wav + ref.txt
          → 写 ai.tts_api_ref / ai.tts_api_ref_text（若目录有该角色素材）
        - 系统提示词：assets/tts_refs/<角色名>/system_prompt.txt
          → 写 ai.system_prompt（若存在）
        仅当角色名素材存在时才覆盖（避免误清空用户手动配置）；星绘等无素材角色不覆盖。
        """
        cname = role_character_name(role)
        if not cname or self.ai is None:
            return
        ref_dir = os.path.join(assets_dir(), 'tts_refs', cname)
        if not os.path.isdir(ref_dir):
            return
        try:
            cfg = load_config()
            ai = cfg.get('ai') or {}
            changed = False
            # 1) 克隆参考音频 + 转录
            ref_wav = os.path.join(ref_dir, 'ref.wav')
            ref_txt = os.path.join(ref_dir, 'ref.txt')
            if os.path.exists(ref_wav) and os.path.exists(ref_txt):
                with open(ref_txt, encoding='utf-8') as f:
                    text = f.read().strip()
                ai['tts_api_ref'] = ref_wav
                ai['tts_api_ref_text'] = text
                changed = True
            # 2) 系统提示词
            sp = os.path.join(ref_dir, 'system_prompt.txt')
            if os.path.exists(sp):
                with open(sp, encoding='utf-8') as f:
                    prompt = f.read().strip()
                if prompt:
                    ai['system_prompt'] = prompt
                    changed = True
            if changed:
                cfg['ai'] = ai
                save_config(cfg)
                # 同步内存里的 manager（若有热缓存）
                try:
                    if hasattr(self.ai, '_system_prompt_cache'):
                        self.ai._system_prompt_cache = None
                except Exception:
                    pass
                print('role ai profile ->', cname)
        except Exception as e:
            print('apply role ai profile fail:', e)

    # ------------- 设置面板 -------------
    def open_settings_panel(self):
        """打开/聚焦设置面板窗口（若已开则置前）"""
        if not HAS_PANEL:
            # 面板不可用时回退旧菜单
            self._popup_menu_at(QCursor.pos())
            return
        panel = getattr(self, '_settings_panel', None)
        if panel is None:
            try:
                panel = _panel_mod.SettingsPanel(self)
                self._settings_panel = panel
                panel.sig_role_changed.connect(self.switch_role)
            except Exception as e:
                print('panel create fail:', e)
                self._popup_menu_at(QCursor.pos())
                return
        panel.refresh_all()
        panel.show()
        panel.raise_()
        panel.activateWindow()

    def rescan_roles(self):
        """重新扫描角色目录（导入/删除角色后调用）"""
        self.roles = list_roles()
        if self.role not in self.roles:
            self.role = default_role_pick(self.roles)
            self.load_role(self.role)
        # 同步打开的面板（角色列表/当前角色显示/音频列表）
        if getattr(self, '_settings_panel', None) is not None:
            try:
                self._settings_panel.refresh_all()
                self._settings_panel._watch_current_dir()
            except Exception:
                pass

    # 供设置面板调用的便捷方法（委托模块级函数）
    def base_dir(self):
        return base_dir()

    def chars_dir(self):
        return chars_dir()

    def list_output_devices(self):
        return list_output_devices()

    def list_role_audio(self, role):
        return list_role_audio(role)

    def unbind_audio_key(self, audio_key):
        """移除某音频的快捷键绑定（删除音频/清绑定时调用），持久化并注销热键"""
        if audio_key in self._audio_hotkeys:
            del self._audio_hotkeys[audio_key]
            cfg = load_config()
            cfg['audio_hotkeys'] = self._audio_hotkeys
            save_config(cfg)
            # 注销该 key 对应的热键（若已注册）
            try:
                hwnd = int(self.winId())
                for hid, ak in list(self._custom_hk_map.items()):
                    if ak == audio_key:
                        unregister_hotkey(hwnd, hid)
                        del self._custom_hk_map[hid]
            except Exception:
                pass
            # 同步打开的面板
            if getattr(self, '_settings_panel', None) is not None:
                try:
                    self._settings_panel.on_capture_finished()
                except Exception:
                    pass

    def remove_audio_file(self, path):
        """删除音频文件并清理其绑定（面板删除音频调用）。
        返回 (成功?, 提示)"""
        akey = self._audio_key_for_path(path) if hasattr(self, '_audio_key_for_path') \
            else self._audio_key(self.role, path)
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception as e:
            return False, "删除失败: %s" % e
        # 清理解码/时长缓存
        _decode_cache.pop(path, None)
        try:
            _decode_cache_order.remove(path)
        except ValueError:
            pass
        _dur_cache.pop(path, None)
        # 清理该音频绑定（若有）
        self.unbind_audio_key(akey)
        return True, ""

    def remove_role(self, role):
        """删除角色目录并清理该角色全部音频快捷键绑定（面板删除角色调用）。
        返回 (成功?, 提示)。不能删当前角色"""
        if role == self.role:
            return False, "不能删除正在使用的角色"
        d = role_dir(role)
        try:
            if os.path.isdir(d):
                shutil.rmtree(d)
        except Exception as e:
            return False, "删除失败: %s" % e
        # 清理该角色路径下的解码/时长缓存
        rpre = d + os.sep
        try:
            for p in [k for k in _decode_cache if k.startswith(rpre)]:
                _decode_cache.pop(p, None)
            _decode_cache_order[:] = [k for k in _decode_cache_order if k not in _decode_cache]
            for p in [k for k in _dur_cache if k.startswith(rpre)]:
                _dur_cache.pop(p, None)
        except Exception:
            pass
        # 清理该角色所有音频绑定（前缀 "<role>/"）
        changed = False
        for k in list(self._audio_hotkeys.keys()):
            if k.startswith(role + '/'):
                del self._audio_hotkeys[k]
                changed = True
        if changed:
            cfg = load_config()
            cfg['audio_hotkeys'] = self._audio_hotkeys
            save_config(cfg)
        # 注销属于该角色的已注册热键
        try:
            hwnd = int(self.winId())
            for hid, ak in list(self._custom_hk_map.items()):
                if ak.startswith(role + '/'):
                    unregister_hotkey(hwnd, hid)
                    del self._custom_hk_map[hid]
        except Exception:
            pass
        return True, ""

    # ------------- 绑定麦克风/输出 -------------
    def _schedule_menu_refresh(self):
        """设置项被点击后：同步关闭旧菜单并立即重开新菜单（视觉无中断）。
        Qt 允许在 triggered 处理中弹出新 QMenu；旧菜单会关闭但新菜单马上出现"""
        if getattr(self, "_active_menu", None) is None:
            return
        try:
            self._active_menu.close()   # 关闭旧菜单（触发其 hide）
        except Exception:
            pass
        # 立即在同一位置重开（覆盖旧引用）
        QTimer.singleShot(40, lambda: self._popup_menu_at(self._menu_anchor))

    def set_bind_device(self, name):
        """绑定输出设备（空=不绑定）。持久化到 pet_config.json"""
        self._bind_device = name or ''
        cfg = load_config()
        cfg['bind_device'] = self._bind_device
        save_config(cfg)
        self.refresh_tray_menu()  # 托盘菜单同步绑定状态
        self._schedule_menu_refresh()
        print('bind device ->', self._bind_device or '(none)')

    def set_self_device(self, name):
        """设置自己监听设备（空=关闭自己监听）。持久化到 pet_config.json"""
        self._self_device = name or ''
        cfg = load_config()
        cfg['self_device'] = self._self_device
        save_config(cfg)
        self.refresh_tray_menu()
        self._schedule_menu_refresh()
        print('self device ->', self._self_device or '(off)')

    def set_auto_ptt(self, enabled):
        """开关「自动按开麦键」。持久化到 pet_config.json。
        触发菜单自动重开，保证勾选后可连续点其它选项"""
        self._auto_ptt = bool(enabled)
        cfg = load_config()
        cfg['auto_ptt'] = self._auto_ptt
        save_config(cfg)
        self.refresh_tray_menu()
        self._schedule_menu_refresh()
        print('auto_ptt ->', self._auto_ptt)

    # ------------- 快捷键设置 -------------
    def set_hotkeys_enabled(self, enabled):
        """「启用快捷键发话」总开关：关闭时注销全部热键（含小键盘钩子）并禁用录制。
        触发菜单自动重开，保证勾选后可连续点其它选项"""
        self._hotkeys_enabled = bool(enabled)
        cfg = load_config()
        cfg['hotkeys_enabled'] = self._hotkeys_enabled
        save_config(cfg)
        self.refresh_tray_menu()
        self._schedule_menu_refresh()
        if not self._hotkeys_enabled:
            # 总开关关：注销全部（custom 热键 + 小键盘钩子）
            self._numpad_hook_stop()
            try:
                hwnd = int(self.winId())
                for hid in list(self._custom_hk_map.keys()):
                    unregister_hotkey(hwnd, hid)
            except Exception:
                pass
            self._custom_hk_map = {}
            self._hotkey_pending = False
            _dbg('hotkeys disabled')
        else:
            # 重注册自定义键 + 按需恢复小键盘钩子
            self._hotkey_pending = True
            self._register_hotkeys_now()
            if self._numpad_enabled:
                self._numpad_hook_start()
        print('hotkeys_enabled ->', self._hotkeys_enabled)

    def _numpad_hook_start(self):
        """启动智能小键盘钩子（前台非输入态才吞键触发语音）"""
        if self._numpad_hook is not None:
            return
        try:
            self._numpad_hook = NumpadPlayHook(self._hotkey_slot_audio)
            self._numpad_hook.start()
            _dbg('numpad smart hook started (uia=%s)' % HAS_UIA)
        except Exception as e:
            print('numpad hook start fail:', e)
            self._numpad_hook = None

    def _numpad_hook_stop(self):
        """停止智能小键盘钩子"""
        if self._numpad_hook is not None:
            try:
                self._numpad_hook.stop()
            except Exception:
                pass
            self._numpad_hook = None
            _dbg('numpad smart hook stopped')

    def set_numpad_enabled(self, enabled):
        """小键盘 1-9 快捷播放开关（默认关）。
        开=启动智能钩子：非输入场景（游戏/桌面）小键盘1-9播放语音，聚焦输入框时自动放行正常打字；
        关=停钩子，小键盘完全恢复原样"""
        self._numpad_enabled = bool(enabled)
        cfg = load_config()
        cfg['numpad_hotkeys'] = self._numpad_enabled
        save_config(cfg)
        if self._numpad_enabled:
            self._numpad_hook_start()
        else:
            self._numpad_hook_stop()
        self.refresh_tray_menu()
        print('numpad_hotkeys(smart) ->', self._numpad_enabled)

    # ------------- 卡丘游戏联动：回车自动补词 -------------
    def _meow_hook_start(self):
        """启动卡丘回车补词钩子（前台为卡拉彼丘且检测到"打字后回车"才补词）"""
        if self._meow_hook is not None:
            return
        try:
            self._meow_hook = MeowHook(self._meow_word_now)
            self._meow_hook.start()
            _dbg('meow hook started')
        except Exception as e:
            print('meow hook start fail:', e)
            self._meow_hook = None

    def _meow_hook_stop(self):
        """停止卡丘回车补词钩子"""
        if self._meow_hook is not None:
            try:
                self._meow_hook.stop()
            except Exception:
                pass
            self._meow_hook = None
            _dbg('meow hook stopped')

    def _meow_word_now(self):
        """供钩子回调取当前补词（线程安全，只读字符串）"""
        return getattr(self, '_meow_word', '喵')

    def set_meow_enabled(self, enabled):
        """卡拉彼丘"回车自动补词"开关（默认关）"""
        self._meow_enabled = bool(enabled)
        cfg = load_config()
        cfg['meow_hotkeys'] = self._meow_enabled
        save_config(cfg)
        if self._meow_enabled:
            self._meow_hook_start()
        else:
            self._meow_hook_stop()
        print('meow_hotkeys ->', self._meow_enabled)

    def set_meow_word(self, word):
        """设置自定义补词（默认 喵）"""
        word = (word or '').strip()
        if not word:
            word = '喵'
        self._meow_word = word
        cfg = load_config()
        cfg['meow_word'] = self._meow_word
        save_config(cfg)
        print('meow_word ->', self._meow_word)

    def set_ptt_key(self, key_name):
        """设置开麦键（键名）。持久化并更新 ptt_vk"""
        self._ptt_key_name = key_name or 'V'
        self._ptt_vk = key_name_to_vk(self._ptt_key_name) or VK_V
        cfg = load_config()
        cfg['ptt_key'] = self._ptt_key_name
        save_config(cfg)
        self.refresh_tray_menu()
        self._schedule_menu_refresh()
        print('ptt_key ->', self._ptt_key_name)

    # ---- 按键录制（音频快捷键 / 自定义开麦键）----
    def _start_capture_hook(self):
        """启动一次性键盘钩子；Esc 取消"""
        if not getattr(self, '_pending_capture', False):
            return
        self._pending_capture = False
        self._cap = KeyCapture(self._on_key_captured)
        if not self._cap.start():
            print('capture hook start fail')
            self._capture_kind = None
            self._capture_audio_key = None

    def _on_key_captured(self, vk):
        """捕获到按键：vk=None(Esc/取消) 或 键码"""
        kind = getattr(self, '_capture_kind', None)
        self._capture_kind = None
        ak = self._capture_audio_key
        self._capture_audio_key = None
        if vk is None:
            # Esc 取消
            QTimer.singleShot(0, self._cancel_capture_ui)
            return
        key_name = vk_to_key_name(vk)
        # 无法识别的键（无名字）→ 存 VK 数值键名？给通用名
        # VK_NAME_REV 没有的（如 OEM 特殊键）会返回 Key<code>，仍可用于注册？
        # RegisterHotKey 需知道 VK。KeyCapture 给了 vk，注册时直接用 vk 即可。
        # 为持久化用友好名，未知名用 "VK%d" % vk
        if key_name.startswith('Key') or key_name.startswith('VK'):
            key_name = 'VK%d' % vk
        # 在 Qt 主线程执行绑定
        QTimer.singleShot(0, lambda: self._apply_capture(kind, ak, vk, key_name))

    def _cancel_capture_ui(self):
        """录制被 Esc 取消：恢复面板按钮状态 + 提示"""
        self._show_capture_msg('已取消', 800)
        if getattr(self, '_settings_panel', None) is not None:
            self._settings_panel.on_capture_finished()

    def _apply_capture(self, kind, audio_key, vk, key_name):
        """应用捕获结果：更新配置 + 重注册热键 + 菜单刷新提示"""
        cfg = load_config()
        if kind == 'audio' and audio_key:
            # 同一键若被【同一语音来源】的其它音频占用 → 释放旧的；
            # 不同来源（不同角色 / 通用语音）允许共用同一键 —— 每个语音来源一套快捷键
            my_src = audio_key.rsplit('/', 1)[0]
            for k, v in list(self._audio_hotkeys.items()):
                if v == key_name and k != audio_key:
                    k_src = k.rsplit('/', 1)[0]
                    if k_src == my_src:
                        del self._audio_hotkeys[k]
            self._audio_hotkeys[audio_key] = key_name
            cfg['audio_hotkeys'] = self._audio_hotkeys
            msg = '%s → %s' % (os.path.basename(audio_key), key_name)
        elif kind == 'ptt':
            self._ptt_key_name = key_name
            self._ptt_vk = vk
            cfg['ptt_key'] = key_name
            msg = '开麦键 → %s' % key_name
        else:
            return
        save_config(cfg)
        self.refresh_tray_menu()
        # 绑的是小键盘数字(1-9)但小键盘开关没开 → 自动开启，否则绑定不生效
        if kind == 'audio' and key_name in ('Num%d' % i for i in range(1, 10)):
            if not self._numpad_enabled:
                self.set_numpad_enabled(True)
                if getattr(self, '_settings_panel', None) is not None:
                    self._settings_panel.sync_numpad_checkbox(True)
        # 刷新打开的设置面板（音频列表显示新绑定的键 + 恢复按钮状态）
        if getattr(self, '_settings_panel', None) is not None:
            self._settings_panel.on_capture_finished()
        # 重注册热键（新键生效）
        self._hotkey_pending = True
        self._register_hotkeys_now()
        self._show_capture_msg(msg, 1200)

    def _show_capture_msg(self, text, ms):
        """在桌宠窗口短暂显示提示文字（绘制在窗口中央）"""
        self._toast_text = text
        self._toast_until = time.monotonic() + ms / 1000.0
        self.update()
        # 到时清除
        QTimer.singleShot(int(ms), self._clear_toast)

    def _clear_toast(self):
        if hasattr(self, '_toast_text') and self._toast_text:
            self._toast_text = None
            self.update()

    def _begin_capture_hotkey(self, audio_key):
        """菜单点击音频项：先关菜单（不重开）→ 进入按键录制"""
        # 关闭当前活动菜单，且不置 _reopen_menu（录完自己会刷新）
        if getattr(self, "_active_menu", None) is not None:
            try:
                self._active_menu.close()
            except Exception:
                pass
        self._schedule_capture('audio', audio_key)

    def _begin_capture_ptt(self):
        """菜单点击「自定义…」：先关菜单 → 进入开麦键录制"""
        if getattr(self, "_active_menu", None) is not None:
            try:
                self._active_menu.close()
            except Exception:
                pass
        self._schedule_capture('ptt')

    def _schedule_capture(self, kind, audio_key=None):
        """记录待录制目标，稍后启动钩子（等菜单 exec 完全返回）"""
        self._capture_kind = kind
        self._capture_audio_key = audio_key
        self._pending_capture = True
        self._toast_text = None
        self.update()  # 显示"按一个键绑定…"
        # 多次延后确保菜单 exec 已退出、事件循环空闲
        QTimer.singleShot(250, self._start_capture_hook)

    # ------------- 鼠标 -------------
    def _on_menu_btn(self, pos):
        """点是否落在三横按钮上"""
        return self._menu_btn_rect().contains(pos)

    def _hide_btn_now(self):
        """1 秒延迟到点：确认鼠标确实不在窗口内才隐藏按钮"""
        gp = QCursor.pos()
        if not self.geometry().contains(gp):
            self._hovering = False
            self._menu_btn_hover = False
            self._menu_press = False
            self.update()

    def enterEvent(self, e):
        # 鼠标进入：取消延迟隐藏，按钮立即显示
        self._hide_timer.stop()
        self._hovering = True
        # 悬停展开 AI 对话条（静默、不抢焦点）；若 AI 未启用则忽略
        try:
            if getattr(self, 'ai', None) is not None and self.ai.enabled():
                self.ai.chat_bar_on_enter()
        except Exception:
            pass
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        # 鼠标离开窗口（可能只是划过透明空白区）：不立即隐藏，启动 1 秒缓冲
        # 1 秒内回到窗口（enterEvent）则取消；真停在空白处 1 秒后才隐藏
        self._hide_timer.start()
        # 悬停展开的对话条：离开桌宠 1 秒后隐藏
        try:
            if getattr(self, 'ai', None) is not None:
                self.ai.chat_bar_on_leave()
        except Exception:
            pass
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.RightButton:
            # 右键桌宠：AI 启用时弹 AI 快捷菜单（对话/记录/清理/用量），未启用则无操作
            ai = getattr(self, 'ai', None)
            if ai is not None and ai.enabled():
                self._popup_ai_menu(e.globalPosition().toPoint())
                e.accept()
                return
            e.accept()
            return
        if e.button() == Qt.MouseButton.LeftButton:
            lp = e.position().toPoint()
            if self._hovering and self._on_menu_btn(lp):
                # 点三横按钮：不高亮动画、不播音
                self._down = False
                self._menu_btn_hover = True
                self._menu_press = True
                self.update()
            else:
                # 点桌宠本体：按下压扁动画 + 可拖动
                self._down = True
                self._moved = False
                self._press_pos = e.globalPosition().toPoint()
                self._drag_offset = e.position().toPoint()
                self.press_down()
        e.accept()

    def mouseMoveEvent(self, e):
        if self._down and e.buttons() & Qt.MouseButton.LeftButton:
            cur = e.globalPosition().toPoint()
            if self._press_pos and (cur - self._press_pos).manhattanLength() > 6:
                self._moved = True
                # 拖动位置（限制不出屏幕）
                nx = cur.x() - self._drag_offset.x()
                ny = cur.y() - self._drag_offset.y()
                nx, ny = self._clamp_to_screen(nx, ny)
                self.move(nx, ny)
                # 拖动时气泡/输入条同步跟移（零轮询延迟，一体感）
                try:
                    if self.ai is not None:
                        self.ai.pet_moved()
                except Exception:
                    pass
                # 拖动时实时更新朝向（左半屏脸朝右 / 右半屏脸朝左）
                self._update_facing()
                # 拖动时同步更新 hover/按钮高亮
                self._hovering = True
                self._menu_btn_hover = self._on_menu_btn(e.position().toPoint())
        else:
            # 未按住时悬停跟踪（用于按钮 hover 高亮）
            self._menu_btn_hover = self._hovering and self._on_menu_btn(e.position().toPoint())
        self.update()
        e.accept()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            if self._menu_press:
                # 三横按钮松开：若仍在其上则打开设置面板
                self._menu_press = False
                was_on_btn = self._hovering and self._on_menu_btn(e.position().toPoint())
                self._menu_btn_hover = False
                self.update()
                if was_on_btn:
                    self.open_settings_panel()
            else:
                self._down = False
                self.press_up(not self._moved)
                # 松开后按最终位置更新朝向（可能停在屏幕左右半边分界处）
                self._update_facing()
        e.accept()


def _is_admin():
    """检测当前进程是否以管理员权限运行"""
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _relaunch_as_admin():
    """以管理员权限重新启动自己（UAC 弹窗）；带 --elevated 防二次提权。
    ShellExecuteW 返回值 >32 表示成功启动；否则（用户取消/失败）返回 False"""
    try:
        if hasattr(sys, "_MEIPASS"):
            # 打包态：直接提权 exe 自己
            exe = sys.executable
            params = '--elevated'
            r = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1)
            return r > 32
        # 未打包：提权 python 解释器 + 脚本
        exe = sys.executable
        script = os.path.abspath(__file__)
        params = '"%s" --elevated' % script
        r = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1)
        return r > 32
    except Exception:
        return False


def main():
    # UAC 自提权：若游戏以管理员运行，桌宠必须同级否则全局热键被 UIPI 屏蔽
    # 普通启动（无 --elevated）→ 检测非管理员则提权重启
    already_elevated = '--elevated' in sys.argv
    if not already_elevated and not _is_admin():
        _dbg('not admin, relaunching elevated...')
        if _relaunch_as_admin():
            return  # 提权进程已启动，本进程退出
        _dbg('relaunch elevated failed, continue as normal')
    app = QApplication(sys.argv)
    app.setApplicationName("卡丘简易桌宠")
    app.setQuitOnLastWindowClosed(False)
    w = PetWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
