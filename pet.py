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

# Mate-Engine 3D 联动（可选模块；缺失时 3D 菜单自动隐藏）
try:
    from matelink import MateLink, ALL_OPS
    _mate_link = MateLink()
except Exception:
    _mate_link = None

# 3D 角色切换（改配置+重启进程，官方持久化路径）
try:
    import mate_avatar as _mate_avatar
except Exception:
    _mate_avatar = None

# 自研 Web 3D 桌宠（three.js + three-vrm + QtWebEngine，完全脱离 Mate-Engine）
# 后端选择：优先 'web'（无重启热切换/全功能），失败自动回退 'mate'
#
# ⚠ 关键：QtWebEngineWidgets 必须在 QApplication 创建【之前】导入
#   （否则报 "QtWebEngineWidgets must be imported ... before a QCoreApplication
#     instance is created"）。且要在设置 Chromium flag 之后导入。
if os.environ.get('PET_NO_WEB3D', '') != '1':
    os.environ.setdefault(
        "QTWEBENGINE_CHROMIUM_FLAGS",
        "--ignore-gpu-blocklist --enable-gpu-rasterization --enable-unsafe-swiftshader",
    )
    try:
        from PyQt6 import QtWebEngineWidgets as _qtwe_probe  # noqa: F401
        _QTWE_PRELOADED = True
    except Exception as _qtwe_e:
        _QTWE_PRELOADED = False
        _QTWE_PRELOAD_ERR = str(_qtwe_e)
else:
    _QTWE_PRELOADED = False
    _QTWE_PRELOAD_ERR = 'PET_NO_WEB3D=1'

try:
    import web3d_pet as _web3d
    _WEB3D_OK = True
except Exception as _web3d_e:
    _web3d = None
    _WEB3D_OK = False
    import traceback as _tb
    _WEB3D_ERR = ''.join(_tb.format_exception_only(type(_web3d_e), _web3d_e)).strip()
    print('[pet] web3d 不可用，3D 将回退 Mate-Engine:', _WEB3D_ERR)

# 3D 后端：'web' = 内置 three-vrm；'mate' = 外置 Mate-Engine 进程
_3D_BACKEND_DEFAULT = 'web' if _WEB3D_OK else 'mate'

# 内置引擎（VRM）表情的显示名。已实测确认「可见生效」的排前面。
# 未列出的表情会自动收进「更多表情」子菜单，保证功能不丢。
_WEB_EXPR_LABELS = [
    ('blink', '😑 眨眼'),
    ('happy', '😊 开心'),
    ('surprised', '😲 惊讶'),
    ('angry', '😠 生气'),
    ('sad', '😢 难过'),
    ('relaxed', '😌 放松'),
    ('aa', '🅰 张嘴(あ)'),
    ('ih', '🅸 咧嘴(い)'),
    ('ou', '🅾 嘟嘴(う)'),
    ('ee', '🅴 咧嘴(え)'),
    ('oh', '🅾 圆嘴(お)'),
    ('blinkLeft', '😉 眨眼(左)'),
    ('blinkRight', '😉 眨眼(右)'),
    ('lookUp', '👆 看上'),
    ('lookDown', '👇 看下'),
    ('瞳小', '👁 瞳孔缩小'),
    ('じと目', '😒 嫌弃脸'),
]
_WEB_DEFAULT_EXPRS = [k for k, _ in _WEB_EXPR_LABELS]

# 3D 模型的中文名（VRM 文件名 → 菜单显示名）
# 只保留米雪儿：aldina / Zome / Lazuli 已按用户要求移除（源文件仍在 mate_research）
_MODEL_LABELS = {
    'michelle': '米雪儿',
    'michelle_expr': '米雪儿',
}
# 同一角色的不同文件（michelle / michelle_expr）→ 归并成一个，菜单里不重复出现
_MODEL_ALIAS = {
    'michelle_expr': '米雪儿',
    'michelle': '米雪儿',
}


def _prefer_expr_models(names):
    """同名角色只保留一个，且优先保留带表情的那个（*_expr）。

    michelle.vrm 是无表情的原始模型，michelle_expr.vrm 是补了 27 个表情的版本；
    两个都列出来会让用户困惑，而保留错的那个会导致表情菜单点了没用。
    """
    out, chosen = [], {}
    for n in names:
        key = _MODEL_ALIAS.get(n.lower())
        if key is None:
            out.append(n)
            continue
        prev = chosen.get(key)
        if prev is None:
            chosen[key] = n
            out.append(n)
        elif n.lower().endswith('_expr'):
            # 换成带表情的版本，替换掉先前那个
            out[out.index(prev)] = n
            chosen[key] = n
    return out

from PyQt6.QtCore import Qt, QTimer, QPoint, QRect, QUrl, QEvent, QObject
from PyQt6.QtGui import QPixmap, QIcon, QAction, QActionGroup, QCursor, QPainter, QColor, QPen, QImage, QMovie, QRegion
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

# UIA 对象线程本地化：低层键盘钩子的回调运行在钩子线程（非主线程），
# COM 对象必须在其创建线程内使用；跨线程调用 comtypes 对象会导致
# 堆损坏/崩溃（0xc0000374 / 0xc0000409，实测崩在 Qt6Core.dll）。
_uia_tls = threading.local()


def _uia_auto():
    """返回当前线程自己的 UIA 自动化对象（首次使用时创建 + CoInitialize）。
    线程安全：每个线程独立对象，绝不跨线程共用。失败返回 None（自动降级）"""
    if not HAS_UIA:
        return None
    try:
        obj = getattr(_uia_tls, 'auto', None)
        if obj is None:
            comtypes.CoInitialize()
            obj = _cc.CreateObject(_UIA.CUIAutomation, interface=_UIA.IUIAutomation)
            _uia_tls.auto = obj
        return obj
    except Exception:
        return None

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

# 角色英文名映射（用于 TTS 克隆参考的纯英文路径/文件名——audiocpp 只支持 ASCII 路径）
ROLE_EN_NAMES = {
    '米雪儿': 'MicheleLee', '信': 'Nobunaga', '心夏': 'Kokona', '伊薇特': 'Yvette',
    '芙拉薇娅': 'Flavia', '忧雾': 'Yugiri', '蕾欧娜': 'Leona', '千代': 'Chiyo',
    '明': 'Ming', '拉薇': 'Lawine', '梅瑞狄斯': 'Meredith', '令': 'Reiichi',
    '香奈美': 'Kanami', '艾卡': 'Eika', '诺诺': 'Nora', '珐格兰丝': 'Fragrans',
    '玛拉': 'Mara', '奥黛丽': 'AudreyGrove', '玛德蕾娜': 'MaddelenaLeary',
    '绯莎': 'Fuchsia', '星绘': 'Celestia', '白墨': 'BaiMo',
    '加拉蒂亚': 'GalateaLeary', '汐': 'Cielle',
}

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
    """用户数据根目录（可写持久）。

    统一规则（源码运行 / 打包运行【同一个目录】，避免两份数据互相打架）：
      ① 环境变量 PET_DATA_DIR 指定 → 用它
      ② 桌面下的「卡丘简易桌宠数据」（用户期望数据在桌面，且打包 exe 就放桌面）
         —— 桌面不可写时回落
      ③ 用户主目录下的同名文件夹
      ④ 脚本/exe 所在目录

    ⚠ 历史坑：以前源码运行用【脚本目录】、打包运行用【exe目录/卡丘简易桌宠数据】，
      两套数据并存 → 用户改了一份、程序读另一份，出现"设置没生效""数据不见了"。
      现在源码运行也优先用桌面数据目录，保持单一数据源。
    """
    # ① 显式指定
    env = os.environ.get('PET_DATA_DIR', '').strip()
    if env:
        d = _pick_writable([env])
        if d:
            return d

    desktop = os.path.join(os.path.expanduser('~'), 'Desktop')
    exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    script_dir = os.path.dirname(os.path.abspath(__file__))

    cands = []
    if hasattr(sys, "_MEIPASS"):
        cands.append(os.path.join(exe_dir, USER_DATA_DIR))
    else:
        # 源码运行：桌面数据目录优先（若它已存在），否则脚本目录
        cands.append(os.path.join(desktop, USER_DATA_DIR))
    cands += [
        os.path.join(desktop, USER_DATA_DIR),
        os.path.join(os.path.expanduser('~'), USER_DATA_DIR),
        script_dir if not hasattr(sys, "_MEIPASS") else exe_dir,
        os.path.expanduser('~'),
    ]
    # 源码运行时：只有当桌面数据目录【真的存在】才优先它，
    # 否则保持旧行为（用脚本目录），避免在老环境里凭空造一个新目录
    if not hasattr(sys, "_MEIPASS"):
        desk = os.path.join(desktop, USER_DATA_DIR)
        if not os.path.isdir(desk):
            cands = [script_dir, os.path.join(os.path.expanduser('~'), USER_DATA_DIR),
                     os.path.expanduser('~')]

    chosen = _pick_writable(cands)
    return chosen if chosen is not None else os.path.expanduser('~')


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
    """首次启动：把内置默认资源（characters / common_voice / persona /
    role_worldbooks / trigger_voice / tts_refs / world_book.json）复制到
    用户数据目录 assets（若还没有），保证开箱即用，且之后可写。

    ⚠ 现在【源码运行也会执行】：因为数据目录改成了桌面那个
      「卡丘简易桌宠数据」，首次运行时里面还没有 assets，需要从源码目录播种。
      已经存在的子目录不覆盖（保护用户自己导入的角色/语音）。
    """
    global _seeded
    if _seeded:
        return
    _seeded = True
    try:
        src_a = os.path.join(bundle_dir(), 'assets')
        dst_a = os.path.join(base_dir(), 'assets')
        if os.path.abspath(src_a) == os.path.abspath(dst_a):
            return          # 数据目录就是脚本目录，资源本来就在
        if not os.path.isdir(src_a):
            return
        os.makedirs(dst_a, exist_ok=True)
        for name in os.listdir(src_a):
            s = os.path.join(src_a, name)
            d = os.path.join(dst_a, name)
            if os.path.exists(d):
                # 已存在：目录只在缺文件时补（不覆盖用户改动）
                if os.path.isdir(s) and os.path.isdir(d):
                    for sub in os.listdir(s):
                        sd, dd = os.path.join(s, sub), os.path.join(d, sub)
                        if not os.path.exists(dd):
                            try:
                                if os.path.isdir(sd):
                                    shutil.copytree(sd, dd)
                                else:
                                    shutil.copy2(sd, dd)
                            except Exception:
                                pass
                continue
            try:
                if os.path.isdir(s):
                    shutil.copytree(s, d)
                else:
                    shutil.copy2(s, d)
            except Exception as e:
                print('seed assets fail:', name, e)
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

# 快捷语音文件夹名（晶源追击战术语音；音频列表按文件夹分组时排最前）
QUICK_VOICE_DIR = '晶源追击'

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


def list_role_audio_grouped(role):
    """列出角色语音，按子文件夹分组（只扫一层子目录 + 角色根顶层）：
    返回 [{'group': 文件夹名或'', 'items': [(显示名, 绝对路径)]}]
    组顺序：快捷语音文件夹「晶源追击」最前，其余子文件夹按名，顶层最后；
    空文件夹也保留（占位显示，供智能合成落位）。"""
    candidates = [role_root(role), role_dir(role)]
    dirs = []
    seen = set()
    for d in candidates:
        if d in seen:
            continue
        seen.add(d)
        if os.path.isdir(d):
            dirs.append(d)

    groups = {}   # group 名(''=顶层) -> items
    order = []    # 组出现顺序（顶层最后）

    def scan_dir(d, group):
        items = groups.setdefault(group, [])
        if os.path.isdir(d):
            for f in sorted(os.listdir(d)):
                full = os.path.join(d, f)
                if os.path.isfile(full) and f.lower().endswith(AUDIO_EXTS):
                    name = os.path.splitext(f)[0]
                    items.append((friendly_audio_name(name), full))

    for d in dirs:
        # 子文件夹（一层）
        subs = []
        try:
            subs = [s for s in sorted(os.listdir(d))
                    if os.path.isdir(os.path.join(d, s))]
        except Exception:
            pass
        for s in subs:
            if s not in order:
                order.append(s)
            scan_dir(os.path.join(d, s), s)
        # 顶层放最后
        if '' not in order:
            order.append('')
        scan_dir(d, '')

    # 快捷语音文件夹最前，其余按名，顶层最后
    def _gkey(g):
        if g == QUICK_VOICE_DIR:
            return (0, g)
        if g == '':
            return (2, '')
        return (1, g)

    order.sort(key=_gkey)
    return [{'group': g, 'items': groups[g]} for g in order]


def list_role_audio(role):
    """列出角色语音（平铺）→ [(显示名, 绝对路径)]。
    多形象时语音共用角色根（形象目录只放图）。"""
    out = []
    for grp in list_role_audio_grouped(role):
        out.extend(grp['items'])
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
        # C 回调边界：异常穿出会崩进程，整体防护
        try:
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
        except Exception:
            pass  # 异常放行，不吞键，不崩
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
    返回 True=正在输入；False/异常=查不到。带 1 秒缓存。
    线程安全：用当前线程自己的 UIA 对象（_uia_auto），不跨线程共用 COM"""
    if not HAS_UIA or not hwnd:
        return False
    now = time.monotonic()
    c = _uia_cache.get(hwnd)
    if c and now - c[0] < _UIA_CACHE_TTL:
        return c[1]
    auto = _uia_auto()
    if auto is None:
        return False
    try:
        fe = auto.GetFocusedElement()
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
        # 钩子回调运行在 C 回调边界：任何 Python 异常穿出都会导致进程崩溃，
        # 必须整体 try/except，异常时放行按键（不吞键，保守安全）
        try:
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
        except Exception:
            pass  # 异常放行，绝不吞键，绝不崩
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


class _GeoProxy:
    """几何代理：把 frameGeometry()/geometry() 转发给 3D 窗口，其余透传给真桌宠。

    用途：ai_chat 的输入栏用 self._pet.frameGeometry() 定位，而 3D 模式下
    2D 桌宠窗口是隐藏的（几何无效），输入栏会跑到屏幕别处。用这个代理替换
    掉 ChatWindow._pet，定位逻辑一行不改就能贴到 3D 角色下方。
    win=None 时退化为直通真桌宠（等于没代理）。
    """

    def __init__(self, real_pet, win):
        object.__setattr__(self, '_real', real_pet)
        object.__setattr__(self, '_win', win)

    def frameGeometry(self):
        w = object.__getattribute__(self, '_win')
        if w is None:
            return object.__getattribute__(self, '_real').frameGeometry()
        return w.frameGeometry()

    def geometry(self):
        w = object.__getattribute__(self, '_win')
        if w is None:
            return object.__getattribute__(self, '_real').geometry()
        return w.geometry()

    def __getattr__(self, name):
        # 其余属性（_pet_size / ai / 各种状态）全部透传给真正的 PetWindow
        return getattr(object.__getattribute__(self, '_real'), name)


class MateOverlay(QWidget):
    """3D 模式浮层：透明置顶小窗，覆盖在 Mate-Engine 窗口右上角。
    包含：三横按钮（打开右键菜单）→ 保留原有全部功能入口。
    （对应用户需求：切到 3D 后右上角仍有三横可开设置/菜单）"""

    def __init__(self, pet):
        super().__init__(None)
        self.pet = pet
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus   # 不抢 3D 窗口焦点
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._hover = False
        self._press = False
        self.setFixedSize(MENU_BTN_SIZE + MENU_BTN_MARGIN * 2,
                          MENU_BTN_SIZE + MENU_BTN_MARGIN * 2)
        # ★ 关键：浮层只覆盖右上角一小块，但它是个真实窗口，会挡住下面 3D 窗口的
        #   鼠标事件（用户反馈：3D 拖动没反应、悬停不出输入栏）。
        #   这里做「形状遮罩」——只让三横按钮那一小块接收鼠标，其余区域完全穿透，
        #   鼠标事件直接落到 3D 窗口上。
        self._apply_input_mask()

    def _apply_input_mask(self):
        """把窗口的可点击区域限制为三横按钮本身，其余区域鼠标穿透到下层。"""
        try:
            m = MENU_BTN_MARGIN
            s = MENU_BTN_SIZE
            region = QRegion(m, m, s, s)
            self.setMask(region)
        except Exception:
            pass

    def btn_rect(self):
        m = MENU_BTN_MARGIN
        return QRect(m, m, MENU_BTN_SIZE, MENU_BTN_SIZE)

    def follow_mate(self):
        """跟随 3D 窗口右上角定位（内置 Web 3D 或外置 Mate-Engine 均支持）"""
        # ① 内置 Web 3D 窗口：直接用 Qt 几何（最准，无需 Win32）
        try:
            w = getattr(self.pet, '_web3d_win', None)
            if w is not None and w.isVisible():
                g = w.geometry()
                self.move(g.right() - self.width() - 8, g.top() + 8)
                return True
        except Exception:
            pass

        # ② 外置 Mate-Engine 窗口：走 Win32 hwnd
        try:
            hwnd = self.pet._mate3d_hwnd()
            if hwnd:
                rc = ctypes.wintypes.RECT()
                ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rc))
                x = rc.right - self.width() - 8
                y = rc.top + 8
                scr = QApplication.primaryScreen().availableGeometry()
                x = max(scr.left(), min(x, scr.right() - self.width()))
                y = max(scr.top(), min(y, scr.bottom() - self.height()))
                self.move(x, y)
                return True
        except Exception:
            pass
        # 兜底：屏顶右侧
        scr = QApplication.primaryScreen().availableGeometry()
        self.move(scr.right() - self.width() - 20, scr.top() + 20)
        return False

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.btn_rect()
        p.setPen(Qt.PenStyle.NoPen)
        if self._press:
            p.setBrush(QColor(255, 255, 255, 90))
        elif self._hover:
            p.setBrush(QColor(255, 255, 255, 70))
        else:
            p.setBrush(QColor(0, 0, 0, 100))
        p.drawRoundedRect(rect, 9, 9)
        p.setPen(QPen(QColor(255, 255, 255, 240), 2.2, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap))
        cx = rect.center().x()
        half = 6
        for y in (rect.center().y() - 4, rect.center().y(), rect.center().y() + 4):
            p.drawLine(cx - half, y, cx + half, y)
        p.end()

    def enterEvent(self, e):
        self._hover = True
        self.update()
        # 悬停 → 通知桌宠进入"3D 悬停"状态（可触发对话）
        try:
            self.pet._mate_overlay_hover(True)
        except Exception:
            pass
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self._press = False
        self.update()
        try:
            self.pet._mate_overlay_hover(False)
        except Exception:
            pass
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        if self.btn_rect().contains(e.position().toPoint()):
            self._press = True
            self.update()
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        was = self._press
        self._press = False
        self.update()
        if was and self.btn_rect().contains(e.position().toPoint()):
            self.pet._mate_open_menu()
        super().mouseReleaseEvent(e)

    def mouseMoveEvent(self, e):
        super().mouseMoveEvent(e)


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
        # 自动面向屏幕中央：跨到屏幕左右另一半时平滑翻转朝向（默认开，可在设置关闭）
        self._auto_facing = bool(_cfg.get('auto_facing', True))
        self._in3d = False   # 当前是否处于 3D 米雪儿模式（切换用）
        self._mate_overlay = None   # 3D 模式浮层（三横按钮）
        self._mate_overlay_timer = None
        self._web3d_win = None      # 自研 3D 桌宠窗口（three-vrm）
        self._web3d_ready = False
        self._pending_3d_model = None   # 进 3D 后要加载的模型（右键「切换 3D 形象」用）
        # 3D 后端：'web'（内置，默认）/'mate'（外置），运行时可切换
        _saved = _cfg.get('3d_backend', '')
        if _saved == 'web' and not _WEB3D_OK:
            _saved = 'mate'
        self._3d_backend = os.environ.get('PET_3D_BACKEND', _saved or _3D_BACKEND_DEFAULT)
        self._overlay_task = None   # QThread 调度器（浮层跟随 Mate 窗口）
        self._overlay_worker = None
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
        # 启动时同步当前角色的 AI 配置（TTS 克隆音色 + 系统提示词 + 会话）：
        # 防止上次关闭时残留其它角色（如白墨）的克隆参考导致「图标星绘、声音白墨」
        QTimer.singleShot(450, self._apply_role_ai_profile_on_start)
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

    def _apply_role_ai_profile_on_start(self):
        """启动时把当前角色（默认星绘/最后角色）的 AI 配置与会话应用一遍：
        - TTS 克隆参考/系统提示词按当前角色写入配置（清掉上次残留的其它角色音色）
        - AI 会话切到当前角色的独立上下文"""
        try:
            role = getattr(self, 'role', '') or ''
            if not role:
                return
            self._apply_role_ai_profile(role)
            if self.ai is not None and hasattr(self.ai, 'switch_to_role'):
                self.ai.switch_to_role(role)
        except Exception as e:
            print('apply role profile on start fail:', e)

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

    def _voice_profile(self):
        """当前语音方案名：角色目录子文件夹名（如「晶源追击」）；空=默认（角色根顶层）"""
        try:
            return str(load_config().get('voice_profile', '') or '').strip()
        except Exception:
            return ''

    def set_voice_profile(self, name):
        """切换语音方案（子文件夹名或''=顶层默认）。持久化 + 刷新菜单/面板"""
        name = str(name or '').strip()
        cfg = load_config()
        cfg['voice_profile'] = name
        save_config(cfg)
        self.refresh_tray_menu()
        self._schedule_menu_refresh()
        if getattr(self, '_settings_panel', None) is not None:
            self._settings_panel.refresh_all()
            self._settings_panel._watch_current_dir()
        print('voice_profile ->', name or '(默认)')

    def _profile_audio_list(self):
        """当前语音方案的可播音频：方案=文件夹→该文件夹组；默认→顶层组"""
        if self._voice_source == 'common':
            return list_common_audio()
        profile = self._voice_profile()
        for g in list_role_audio_grouped(self.role):
            if g['group'] == profile:
                return g['items']
        return []

    def _hotkey_slot_audio(self, num):
        """小键盘数字按下：
        按当前语音方案匹配绑定——方案=子文件夹（如晶源追击）只认该文件夹里的绑定；
        默认方案只认角色根顶层绑定；无绑定 → 回退播当前方案第 num 条音频。
        """
        key_name = 'Num%d' % num
        audio_key = None
        profile = self._voice_profile()
        # 当前来源下查绑定（角色专属 vs 通用语音分开）
        if self._voice_source == 'common':
            prefix = '__common__'
        else:
            prefix = self.role
        for k, v in self._audio_hotkeys.items():
            if v != key_name:
                continue
            if profile:
                if k.startswith(prefix + '/' + profile + '/'):
                    audio_key = k
                    break
            else:
                if k.rsplit('/', 1)[0] == prefix:
                    audio_key = k
                    break
        if audio_key:
            self._custom_hotkey_audio(audio_key)
            return
        # 回退：按位置取当前方案第 num 条
        audios = self._profile_audio_list()
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
            # 多形象角色：语音统一放角色根，形象目录没有 → 回退角色根再拼
            if not os.path.exists(path):
                alt = os.path.join(role_root(role_name), fname)
                if os.path.exists(alt):
                    path = alt
        if os.path.exists(path):
            # 若当前角色不符且该角色存在 → 临时切角色播放? 用户期望的是"当前角色"的按键
            # 简化为：直接播放该文件（跨角色也可）
            self.play_audio(path)

    def _build_voice_profile_submenu(self):
        """语音方案子菜单：默认（角色根顶层）+ 角色目录各子文件夹（含音频的）"""
        menu = QMenu(self)
        menu.setStyleSheet(MENU_QSS)
        grp = QActionGroup(menu)
        grp.setExclusive(True)
        cur = self._voice_profile()

        def add(text, name):
            act = QAction(text, menu)
            act.setCheckable(True)
            act.setChecked(name == cur)
            act.triggered.connect(lambda c, n=name: self.set_voice_profile(n))
            grp.addAction(act)
            menu.addAction(act)

        add("默认（角色根）", '')
        d = role_root(self.role)
        if os.path.isdir(d):
            for f in sorted(os.listdir(d)):
                fp = os.path.join(d, f)
                if not os.path.isdir(fp):
                    continue
                try:
                    has_audio = any(os.path.isfile(os.path.join(fp, x))
                                    and x.lower().endswith(AUDIO_EXTS) for x in os.listdir(fp))
                except Exception:
                    has_audio = False
                if has_audio:
                    add("📁 %s" % f, f)
        return menu

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
        # 若当前处于 3D 模式，退出时确保 3D 形象仍在（否则桌面会空无一物）
        try:
            if getattr(self, '_in3d', False):
                if getattr(self, '_3d_backend', 'web') == 'web' and _WEB3D_OK:
                    w = getattr(self, '_web3d_win', None)
                    if w is not None:
                        w.show()      # 保留 3D 桌宠可见
                else:
                    hwnd = self._mate3d_hwnd()
                    if hwnd:
                        self._win32_show(hwnd, True)
        except Exception:
            pass
        try:
            self._hide_mate_overlay()
        except Exception:
            pass
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
        # 退出桌宠时顺手关掉本地 TTS 服务（audiocpp_server）
        try:
            if _ai_mod is not None and hasattr(_ai_mod, 'tts_service_stop'):
                _ai_mod.tts_service_stop()
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
        # 3D 模式：尺寸同步到 3D 角色（改 2D 大小 → 3D 跟着变）
        if getattr(self, '_in3d', False):
            try:
                if getattr(self, '_3d_backend', 'web') == 'web' and _WEB3D_OK:
                    self._web3d_sync_size()
                else:
                    self._mate3d_sync_size()
            except Exception:
                pass

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
        # 朗读中（AI/TTS 正在播放）点按：不打断语音回复、也不播点按播报，
        # 等 TTS 播完（StoppedState）后点按才恢复正常播报。
        try:
            if self.ai is not None and hasattr(self.ai, 'is_speaking') and self.ai.is_speaking():
                return
        except Exception:
            pass
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
        if not getattr(self, '_auto_facing', True):
            return  # 开关关闭：保持当前朝向，不翻转
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

    def set_auto_facing(self, on):
        """自动翻转开关（设置面板调用）：on=True 时跨屏幕左右半屏自动转身面向中央；
        on=False 保持当前朝向不再翻转。即时生效并持久化到 pet_config.json。"""
        self._auto_facing = bool(on)
        try:
            cfg = load_config()
            cfg['auto_facing'] = bool(on)
            save_config(cfg)
        except Exception:
            pass
        if self._auto_facing:
            self._update_facing()

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

    def _open_chat_app(self):
        """主窗菜单「💬 聊天」：打开模型网站式完整聊天窗口"""
        try:
            if self.ai is not None and hasattr(self.ai, 'open_chat_app'):
                self.ai.open_chat_app()
        except Exception:
            pass

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

        # ① 打开设置（导航式设置面板，最高频入口）
        act_settings = QAction("⚙ 打开设置…", menu)
        act_settings.triggered.connect(lambda: self.open_settings_panel())
        menu.addAction(act_settings)

        # ①-3D：🎭 3D桌宠（置顶醒目入口 —— 以前埋在菜单最底部，用户找不到）
        act_3dtop = QAction("🎭 3D桌宠", menu)
        act_3dtop.setMenu(self._build_3d_menu(menu))
        if getattr(self, '_in3d', False):
            act_3dtop.setText("🎭 3D桌宠 ● 使用中")
        menu.addAction(act_3dtop)

        # ①-聊天：打开模型网站式完整聊天窗口（角色列表 + 消息流 + 多行输入）
        act_chat = QAction("💬 聊天", menu)
        act_chat.setToolTip("打开完整聊天窗口（像模型网站：左侧角色列表 + 消息流 + 多行输入）")
        act_chat.triggered.connect(lambda: self._open_chat_app())
        menu.addAction(act_chat)
        menu.addSeparator()

        # ② 切换角色：点击后 _open_switch_submenu 在其右侧弹出角色子菜单
        #   （PyQt6/Qt6 无 QAction.setPopupMode；且模态 exec 内不能再 exec，
        #    故角色列表用非模态 popup 方式"向右展开"，行为=点一下右扩）
        self._switch_submenu = QMenu(menu)   # 存引用防 GC
        self._switch_submenu.setStyleSheet(MENU_QSS)
        self._fill_roles_menu(self._switch_submenu)
        act_switch = QAction("切换角色", menu)
        act_switch.setMenu(self._switch_submenu)   # 关联子菜单 → 原生"指向即开"
        menu.addAction(act_switch)

        # ③ AI 用量子菜单（仅展示累计用量/详情；对话条已改悬停自动弹出）
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

        # 语音方案切换（角色专属时可用：子文件夹=一套绑定/套装，如晶源追击/日常）
        if self._voice_source != 'common':
            prof = self._voice_profile()
            act_profile = QAction("语音方案：%s" % (("📁 " + prof) if prof else "默认"), menu)
            act_profile.setMenu(self._build_voice_profile_submenu())
            menu.addAction(act_profile)

        # ② 当前语音来源全部音频（点一下=绑定快捷键；右侧显示已绑键；♪=试听）
        #    角色来源按文件夹分组显示（晶源追击排最前，与设置面板一致）
        groups = []
        if self._voice_source == 'common':
            audios = list_common_audio()
            if audios:
                groups = [{'group': '', 'items': audios}]
        else:
            groups = list_role_audio_grouped(self.role)
        if groups:
            for grp in groups:
                gname = grp.get('group') or ''
                items = grp.get('items') or []
                if gname:
                    t = QAction("— %s —" % gname, menu)
                    t.setEnabled(False)
                    menu.addAction(t)
                if not items:
                    na = QAction("（暂无语音）", menu)
                    na.setEnabled(False)
                    menu.addAction(na)
                    continue
                for label, path in items:
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

    def _build_3d_menu(self, parent):
        """🎭 3D桌宠 子菜单 —— 放在主菜单最上方，一眼就能看到。

        以前 3D 只有一个「✨ 切换到 3D 米雪儿」平铺在最底部（22 项里的第 19 项），
        往下翻都未必看得到，也没有集中的入口。这里改成醒目的顶层右扩菜单：
            切到 3D / 回 2D（随状态变化标题）
            🎭 3D 角色   → 米雪儿 / 阿尔蒂娜 / 祖姆 / 拉兹莉（即时切换）
            😊 表情      → 开心 / 眨眼 / 张嘴…（走 CPU 烘焙，已实测可见）
            🎬 动作      → 睡觉 / 唤醒 / 喂食 / 语音
            📐 尺寸      → 放大 / 还原 / 缩小
            🪟 窗口      → 置顶开关
            ⚙ 3D 引擎    → 内置引擎 / Mate-Engine
            📂 打开模型目录
        """
        menu = QMenu(parent)
        menu.setStyleSheet(MENU_QSS)

        if not self._mate3d_online():
            act_go = QAction("3D 不可用（引擎未就绪）", menu)
            act_go.setEnabled(False)
            menu.addAction(act_go)
            return menu

        in3d = bool(getattr(self, '_in3d', False))

        # —— 切换（最显眼的一行）——
        if in3d:
            act_face = QAction("🖼 返回简易桌宠（2D）", menu)
            act_face.setToolTip("显示 2D 桌宠，隐藏 3D 角色（进程不退出，热键/托盘/聊天全保留）")
        else:
            act_face = QAction("✨ 切换到 3D 桌宠", menu)
            act_face.setToolTip("显示 3D 角色（米雪儿），隐藏 2D 桌宠（热键/托盘/聊天/语音全保留）")
        act_face.triggered.connect(lambda: self.switch_face())
        menu.addAction(act_face)

        # 状态行
        _win = getattr(self, '_web3d_win', None)
        _cur = ''
        try:
            _cur = (_win._model_name if _win is not None else '') or ''
        except Exception:
            _cur = ''
        st = QAction("状态：%s%s" % ("● 3D 显示中" if in3d else "○ 2D 显示中",
                                    ("　当前角色：" + _cur) if _cur else ""), menu)
        st.setEnabled(False)
        menu.addAction(st)

        menu.addSeparator()
        # ★ 这里【必须自己建】子菜单，不能复用 _build_mate3d_menu 的返回值：
        #   那个函数是局部变量 full，返回后被 Python GC 回收，挂到它上面的
        #   子菜单会一起失效（实测报 "wrapped C/C++ object of type QMenu has been
        #   deleted"）→ 右键菜单变成一片空白/无响应。
        self._build_role_sub = QMenu("🎭 3D 角色", menu)   # 存引用防 GC
        self._fill_3d_role_menu(self._build_role_sub)
        a = QAction("🎭 3D 角色", menu)
        a.setMenu(self._build_role_sub)
        menu.addAction(a)

        self._build_expr_sub = QMenu("😊 表情", menu)
        self._fill_3d_expr_menu(self._build_expr_sub)
        a = QAction("😊 表情", menu)
        a.setMenu(self._build_expr_sub)
        menu.addAction(a)

        self._build_act_sub = QMenu("🎬 动作", menu)
        self._fill_3d_action_menu(self._build_act_sub)
        a = QAction("🎬 动作", menu)
        a.setMenu(self._build_act_sub)
        menu.addAction(a)

        # 尺寸 / 窗口 / 藏手 / 互动 —— 这些是纯静态项，直接用现成构建器
        for label, maker in (
            ("📐 尺寸", self._fill_3d_size_menu),
            ("🪟 窗口", self._fill_3d_window_menu),
            ("🙈 藏手", self._fill_3d_hide_menu),
            ("🎮 互动", self._fill_3d_fun_menu),
        ):
            sub = QMenu(label, menu)
            maker(sub)
            act = QAction(label, menu)
            act.setMenu(sub)
            menu.addAction(act)

        menu.addSeparator()
        act_dir = QAction("📂 打开模型目录", menu)
        act_dir.triggered.connect(lambda: self._open_3d_model_dir())
        menu.addAction(act_dir)
        return menu

    # ---- 以下是「3D桌宠」各分组的内容（自建，避免 GC 问题）----
    def _fill_3d_role_menu(self, m):
        """🎭 3D 角色：列出模型（中文名），点击即时热切换"""
        cur = ''
        try:
            w = getattr(self, '_web3d_win', None)
            cur = (w._model_name if w is not None else 'michelle') or ''
        except Exception:
            cur = ''
        names = []
        try:
            w = getattr(self, '_web3d_win', None)
            names = list(w.models()) if w is not None else []
        except Exception:
            names = []
        if not names:
            try:
                names = list(_web3d.sync_models().keys())
            except Exception:
                names = []
        seen = set()
        for n in _prefer_expr_models(names):
            role = _MODEL_ALIAS.get(n.lower(), n)
            if role in seen:
                continue
            seen.add(role)
            label = _MODEL_LABELS.get(n.lower(), n)
            mark = " ✓" if n.lower() == str(cur).lower() else ""
            act = QAction(label + mark, m)
            act.setToolTip("点击即时切换（无需重启，约 0.4 秒）")
            act.triggered.connect(
                lambda c, nn=n: self._mate3d_switch_avatar(nn + '.vrm', nn + '.vrm'))
            m.addAction(act)
        if not names:
            na = QAction("（未找到 VRM 模型）", m)
            na.setEnabled(False)
            m.addAction(na)
        # 后端选择
        m.addSeparator()
        be = QMenu("⚙ 3D 引擎", m)
        be.setStyleSheet(MENU_QSS)
        for label, key, tip in (
            ("内置引擎（推荐·即时切换）", 'web', "three-vrm 内置渲染：热切换 0.4s，无需外部程序"),
            ("Mate-Engine（外置）", 'mate', "外置进程：切模型需重启（5~40s）"),
        ):
            if key == 'web' and not _WEB3D_OK:
                continue
            a = QAction(("● " if key == getattr(self, '_3d_backend', 'web') else "○ ") + label, be)
            a.setToolTip(tip)
            a.triggered.connect(lambda c, k=key: self._set_3d_backend(k))
            be.addAction(a)
        m.addMenu(be)

    def _fill_3d_expr_menu(self, m):
        """😊 表情：内置引擎读 VRM 表情表（已实测可见的排前面）"""
        exprs = []
        try:
            w = getattr(self, '_web3d_win', None)
            if w is not None:
                exprs = list(getattr(w, '_expressions', []) or [])
        except Exception:
            exprs = []
        if not exprs:
            exprs = _WEB_DEFAULT_EXPRS
        for name, label in _WEB_EXPR_LABELS:
            if name not in exprs:
                continue
            act = QAction("%s  %s" % (label, name), m)
            act.triggered.connect(
                lambda c, n=name: (self._mate3d_cmd('blend_reset'),
                                   self._mate3d_cmd('blend_set', name=n, value=100.0)))
            m.addAction(act)
        rest = [n for n in exprs
                if n not in [k for k, _ in _WEB_EXPR_LABELS] and n != 'neutral']
        if rest:
            more = QMenu("更多表情", m)
            more.setStyleSheet(MENU_QSS)
            for name in rest:
                act = QAction(name, more)
                act.triggered.connect(
                    lambda c, n=name: (self._mate3d_cmd('blend_reset'),
                                       self._mate3d_cmd('blend_set', name=n, value=100.0)))
                more.addAction(act)
            m.addMenu(more)
        m.addSeparator()
        act_r = QAction("🔄 重置表情", m)
        act_r.triggered.connect(lambda: self._mate3d_cmd('blend_reset'))
        m.addAction(act_r)

    def _fill_3d_action_menu(self, m):
        for label, op, kw in (
            ("💤 睡觉", 'sleep', {'on': True}),
            ("🌞 唤醒", 'sleep', {'on': False}),
            ("🍰 喂食", 'food_spawn', {'index': 0}),
            ("🗣 随机语音", 'voice_random', {}),
        ):
            act = QAction(label, m)
            act.triggered.connect(lambda c, o=op, k=kw: self._mate3d_cmd(o, **k))
            m.addAction(act)

    def _fill_3d_size_menu(self, m):
        for label, v in (("放大 1.2×", 1.2), ("还原 1.0×", 1.0), ("缩小 0.8×", 0.8)):
            act = QAction(label, m)
            act.triggered.connect(lambda c, vv=v: self._mate3d_cmd('scale', value=vv))
            m.addAction(act)

    def _fill_3d_window_menu(self, m):
        a = QAction("置顶", m)
        a.triggered.connect(lambda: self._mate3d_cmd('topmost', on=True))
        m.addAction(a)
        a = QAction("取消置顶", m)
        a.triggered.connect(lambda: self._mate3d_cmd('topmost', on=False))
        m.addAction(a)

    def _fill_3d_hide_menu(self, m):
        for label, l, r in (("藏左手", True, False), ("藏右手", False, True),
                            ("都藏", True, True), ("都放", False, False)):
            a = QAction(label, m)
            a.triggered.connect(lambda c, ll=l, rr=r: self._mate3d_cmd('hide_arm', left=ll, right=rr))
            m.addAction(a)

    def _fill_3d_fun_menu(self, m):
        for label, op, kw in (
            ("🍼 Q 版模式", 'chibi', {}),
            ("🖥 大屏模式", 'bigscreen', {}),
            ("💬 气泡开关", 'bubble', {}),
        ):
            a = QAction(label, m)
            a.triggered.connect(lambda c, o=op, k=kw: self._mate3d_cmd(o, **k))
            m.addAction(a)
        a = QAction("🗣 让它说句话…", m)
        a.triggered.connect(lambda: self._mate3d_say_dialog())
        m.addAction(a)
        a = QAction("🔁 自动说话（开/关）", m)
        a.triggered.connect(lambda: self._mate3d_toggle_auto_talk())
        m.addAction(a)

    # ============ 3D 联动（双后端：web 内置 / mate 外置） ============
    def _mate3d_online(self):
        """3D 是否可用：
        * 内置 Web 后端 → 永远可用（引擎内置在同进程，窗口按需创建），
          只有显式设置 PET_NO_WEB3D=1 才判为不可用
        * 外置 Mate 后端 → 看 socket 桥是否在线
        """
        if getattr(self, '_3d_backend', 'web') == 'web':
            return bool(_WEB3D_OK)
        try:
            if _mate_link is None:
                return False
            return _mate_link.online()
        except Exception:
            return False

    def _mate3d_running(self):
        """Mate-Engine 进程是否在运行"""
        try:
            import subprocess
            r = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq MateEngineX.exe'],
                               capture_output=True, text=True, timeout=10)
            return 'MateEngineX.exe' in r.stdout
        except Exception:
            return False

    def _mate3d_hwnd(self):
        """找 Mate-Engine 主窗口句柄（0=未找到）。注意：必须包含已隐藏的窗口，
        否则隐藏后再切换就找不回来（窗口标题固定为 'MateEngineX'）"""
        try:
            import ctypes as _c
            from ctypes import wintypes as _w
            u = _c.windll.user32
            result = [0]
            CB = _c.WINFUNCTYPE(_c.c_bool, _w.HWND, _w.LPARAM)
            def cb(h, l):
                pid = _w.DWORD()
                u.GetWindowThreadProcessId(h, _c.byref(pid))
                buf = _c.create_unicode_buffer(256)
                u.GetWindowTextW(h, buf, 256)
                cls = _c.create_unicode_buffer(256)
                u.GetClassNameW(h, cls, 256)
                t = buf.value or ''
                # 主窗口：标题含 Mate，且是 Unity 的 UnityWndClass（排除 IME 等辅助窗口）
                if 'Mate' in t and 'IME' not in cls.value:
                    result[0] = h
                    return False
                return True
            u.EnumWindows(CB(cb), 0)
            return result[0]
        except Exception:
            return 0

    def _win32_show(self, hwnd, show):
        """显示/隐藏窗口。show=True 时用 SW_SHOWNA(8)+SW_RESTORE 兜底（Unity 窗口隐藏后需恢复）"""
        try:
            import ctypes as _c
            if show:
                # 若最小化先恢复，再显示（不抢焦点）
                if _c.windll.user32.IsIconic(hwnd):
                    _c.windll.user32.ShowWindow(hwnd, 9)   # SW_RESTORE
                _c.windll.user32.ShowWindow(hwnd, 8)       # SW_SHOWNA（显示但不激活）
            else:
                _c.windll.user32.ShowWindow(hwnd, 0)       # SW_HIDE
        except Exception:
            pass

    def _mate3d_raise(self, hwnd):
        """把 3D 窗口置顶（HWND_TOPMOST）但不抢焦点"""
        try:
            import ctypes as _c
            _c.windll.user32.SetWindowPos(
                hwnd, -1, 0, 0, 0, 0,
                0x0001 | 0x0002 | 0x0010)  # NOSIZE|NOMOVE|NOACTIVATE
        except Exception:
            pass

    def _mate3d_switch_avatar(self, path, name):
        """切换 3D 角色。
        * 内置 Web 后端：直接热切换（0.4~0.7 秒，无需重启）
        * 外置 Mate 后端：改配置 + 重启进程（官方持久化路径，5~40 秒）
        """
        # ① 内置 Web 3D：热切换（首选）
        if getattr(self, '_3d_backend', 'web') == 'web' and _WEB3D_OK:
            w = getattr(self, '_web3d_win', None)
            if w is not None:
                ok = w.set_model(os.path.splitext(name)[0])
                print('web3d avatar switch ->', name, ok)
                if ok:
                    # 切换后让角色打个招呼，确认生效
                    QTimer.singleShot(700, lambda: self._mate3d_cmd(
                        'say', text='我是%s，请多关照～' % os.path.splitext(name)[0]))
                    return
                print('web3d 未找到该模型，回退 Mate 路径')

        # ② 外置 Mate 后端：改配置 + 重启
        if _mate_avatar is None:
            return

        def _run():
            try:
                r = _mate_avatar.set_model(path, restart=True, wait_bridge=True)
                print('avatar switch:', name, r)
            except Exception as e:
                print('avatar switch err:', name, e)
            finally:
                try:
                    from PyQt6.QtCore import QMetaObject, Qt
                    QMetaObject.invokeMethod(
                        self, "refresh_tray_menu", Qt.ConnectionType.QueuedConnection)
                except Exception:
                    pass

        threading.Thread(target=_run, daemon=True).start()

    def _mate3d_launch(self):
        """启动 Mate-Engine（若未运行）；需在其目录下启动才能加载 Doorstop"""
        try:
            exe = r"C:\Users\mier\Desktop\deepseek work\mate-engine\unpacked\MateEngineX.exe"
            if not os.path.exists(exe):
                print('mate3d: exe not found:', exe)
                return
            if self._mate3d_running():
                return
            import subprocess
            subprocess.Popen(
                [exe],
                cwd=os.path.dirname(exe),
                creationflags=getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0),
            )
            # 轮询等桥上线（最多 30s）
            def _wait():
                for _ in range(30):
                    time.sleep(1)
                    if self._mate3d_online():
                        self.refresh_tray_menu()
                        break
            threading.Thread(target=_wait, daemon=True).start()
        except Exception as e:
            print('mate3d launch err:', e)

    # ---------- 一键切换（2D 简易桌宠 ↔ 3D 米雪儿） ----------
    # 双后端设计：
    #   'web'  = 内置 three-vrm 渲染（QtWebEngine，同进程；热切换 0.4s；全部 Python 可控）
    #   'mate' = 外置 Mate-Engine 进程（socket 桥；切模型需重启，5~40s）
    # 两者共享：三横浮层 / 悬停对话 / 尺寸同步 / 原有全部菜单功能
    def switch_face(self):
        """在 2D 简易桌宠 与 3D 之间切换。
        切换=显示/隐藏窗口（进程都不退出→热键/托盘/聊天/语音全保留）"""
        try:
            if getattr(self, '_in3d', False):
                self._switch_to_2d()
            else:
                self._switch_to_3d()
            self.refresh_tray_menu()
        except Exception as e:
            print('switch_face err:', e)

    def _switch_to_3d(self):
        """切到 3D：按当前后端启动（web 内置 / mate 外置）→ 显示浮层 + 同步尺寸"""
        if getattr(self, '_3d_backend', 'web') == 'web' and _WEB3D_OK:
            self._switch_to_3d_web()
        else:
            self._switch_to_3d_mate()

    # ---------------- 内置 Web 3D 后端 ----------------
    def _switch_to_3d_web(self):
        """切到内置 3D：创建/显示 three-vrm 窗口（同进程，无需外部程序）

        ⚠ Qt 规则：QWidget/QWebEngineView 必须在【主线程】创建/操作。
        因此窗口创建投递到主线程事件循环（QTimer.singleShot(0)），
        后台线程只负责等待模型就绪，绝不能碰 Qt GUI。
        """
        self.hide()
        self._in3d = True
        self._web3d_ready = False

        def _create_on_main():
            try:
                if getattr(self, '_web3d_win', None) is None:
                    size = self._web3d_view_size()
                    win = _web3d.Web3DPetWindow(model='michelle', size=size)
                    # 位置：沿用 2D 桌宠位置，但保证完整落在屏幕内（否则浮层会被夹紧）
                    scr = QApplication.primaryScreen().availableGeometry()
                    g = self.geometry()
                    x = max(scr.left() + 4, min(g.x(), scr.right() - size[0] - 4))
                    y = max(scr.top() + 4, min(g.y(), scr.bottom() - size[1] - 4))
                    win.move(x, y)
                    self._web3d_win = win
                    try:
                        win.bridge.ready.connect(self._on_web3d_ready)
                    except Exception:
                        pass
                    # ★ 悬停角色 → 展开输入栏（复用 2D 桌宠那套 AI 对话条）
                    #   3D 模式下 2D 桌宠是隐藏的，它的 enterEvent 永远不触发，
                    #   所以必须由 3D 窗口把悬停事件转过来。
                    try:
                        win.hoverChanged.connect(self._on_web3d_hover)
                    except Exception:
                        pass
                    try:
                        win.clicked.connect(self._on_web3d_click)
                    except Exception:
                        pass
                    # 拖动时即时同步三横浮层（否则要等轮询，看起来"延迟很高"）
                    try:
                        win.overlay_sync = self._sync_overlay_now
                    except Exception:
                        pass
                # ★ 新建后必须 show（否则窗口存在但不可见）
                self._web3d_win.show()
                self._web3d_win.raise_()
                self._web3d_sync_size()
                # ★ 把 AI 输入栏的定位锚点切到 3D 窗口
                #   （否则输入栏会按隐藏的 2D 窗口定位，跑到屏幕别处）
                try:
                    self._set_geo_anchor(self._web3d_win)
                except Exception as _e:
                    print('anchor 3d err:', _e)
            except Exception as e:
                print('web3d create err:', e)

        # 主线程创建窗口
        QTimer.singleShot(0, _create_on_main)

        # 后台线程：等模型就绪后显示浮层（只读状态，不碰 GUI）
        def _wait_ready_then_overlay():
            for _ in range(60):
                if self._web3d_ready:
                    break
                time.sleep(0.25)
            # 浮层显示也投递到主线程
            QTimer.singleShot(400, self._show_mate_overlay)

        threading.Thread(target=_wait_ready_then_overlay, daemon=True).start()

    def _on_web3d_ready(self, name):
        """内置 3D 就绪回调（主线程）"""
        self._web3d_ready = True
        print('web3d ready:', name)

    def _sync_overlay_now(self):
        """拖动 3D 窗口时即时把三横浮层挪过去（零轮询延迟）"""
        try:
            if self._mate_overlay is not None and self._mate_overlay.isVisible():
                self._mate_overlay.follow_mate()
        except Exception:
            pass

    def _on_web3d_hover(self, on):
        """鼠标进出 3D 角色 → 展开/收起 AI 对话输入栏。

        对应旧版 2D 桌宠的 enterEvent/leaveEvent 行为（3D 模式下 2D 窗口是隐藏的，
        所以那套不会触发，必须在这里补上）。

        ⚠ 两个坑：
          ① 输入栏位置原本用 self._pet.frameGeometry() —— 3D 模式下 2D 桌宠是隐藏的，
             位置不对，输入栏会跑到别处 → 这里临时把 3D 窗口几何喂给它。
          ② 原来要求 ai.enabled() 才弹输入栏；但很多用户把 AI 关着（只用本地语音/
             悬停对话），那样鼠标移入就完全没反应 → 改成始终弹，AI 未启用时
             输入栏本身会给出提示，交互反馈一致。
        """
        try:
            ai = getattr(self, 'ai', None)
            if ai is None:
                return
            if on:
                self._show_chat_bar_for_3d()
                # 同时让角色说句话（沿用原有悬停对话，自带 2 秒节流）
                if getattr(self, '_mate_hover_chat', True):
                    self._mate3d_hover_chat()
            else:
                self._with_3d_geometry(lambda: ai.chat_bar_on_leave())
        except Exception as e:
            print('web3d hover err:', e)

    def _show_chat_bar_for_3d(self):
        """3D 模式下悬停角色 → 显示输入栏。

        chat_bar_on_enter 内部会因 AI 未启用直接 return（2D 模式也是这行为）。
        但 3D 下用户明确要「鼠标移入显示输入栏」，所以这里在 AI 未启用时
        直接调 open_chat(focus=False) 把输入栏弹出来（输入栏自己会提示未启用）。
        """
        ai = getattr(self, 'ai', None)
        if ai is None:
            return
        try:
            already = (getattr(ai, '_chat', None) is not None
                       and ai._chat.isVisible())
            if already:
                self._with_3d_geometry(lambda: ai.chat_bar_on_enter())
                return
            if ai.enabled():
                self._with_3d_geometry(lambda: ai.chat_bar_on_enter())
            else:
                # AI 未启用：仍然把输入栏弹出来（给用户交互反馈，不静默）
                self._with_3d_geometry(lambda: ai.open_chat(focus=False))
        except Exception as e:
            print('show chat bar for 3d err:', e)

    def _set_geo_anchor(self, win):
        """把 AI 输入栏的定位锚点永久切到指定窗口（None = 恢复真 2D 桌宠）。

        为什么用「永久切换」而不是「临时替换」：
          ChatWindow 在 open_chat 里接收 self._pet，并自己缓存 _follow_offset。
          输入栏的跟随是靠定时器 (_follow) 每 100ms 跑 _follow_pet() 实现的 ——
          临时替换只在调用瞬间有效，等定时器跑时补丁早还原了，所以位置纹丝不动
          （实测就是这现象）。改为进 3D 时一次性换锚点、退回 2D 时还原。
        同时必须清 _follow_offset：它缓存「输入栏相对锚点的偏移」，换锚点要重算。
        """
        ai = getattr(self, 'ai', None)
        if ai is None:
            return
        if not hasattr(self, '_geo_anchor_orig'):
            self._geo_anchor_orig = {'mgr': getattr(ai, '_pet', None), 'chat': None}
        orig_mgr = self._geo_anchor_orig.get('mgr')
        anchor = _GeoProxy(self, win) if win is not None else orig_mgr

        try:
            if orig_mgr is not None:
                ai._pet = anchor
        except Exception as e:
            print('set geo anchor (mgr) err:', e)
        try:
            chat = getattr(ai, '_chat', None)
            if chat is not None:
                if self._geo_anchor_orig.get('chat') is None:
                    self._geo_anchor_orig['chat'] = getattr(chat, '_pet', None)
                if self._geo_anchor_orig.get('chat') is not None:
                    chat._pet = anchor
                chat._follow_offset = None
                chat._user_dragged = False
        except Exception as e:
            print('set geo anchor (chat) err:', e)

    def _with_3d_geometry(self, fn):
        """调用 AI 输入栏方法前确保锚点指向 3D 窗口，然后执行 fn。"""
        try:
            w = getattr(self, '_web3d_win', None)
            if w is not None and w.isVisible() and getattr(self, '_in3d', False):
                self._set_geo_anchor(w)
        except Exception as e:
            print('with 3d geometry err:', e)
        fn()

    def _on_web3d_click(self):
        """单击 3D 角色（非拖动）→ 让角色说句话"""
        try:
            self._mate3d_hover_chat()
        except Exception:
            pass

    def _web3d_view_size(self):
        """2D 桌宠尺寸 → 3D 窗口尺寸（等比放大，保证角色完整可见）"""
        try:
            s = int(getattr(self, '_pet_size', BASE_SIZE))
        except Exception:
            s = BASE_SIZE
        s = max(160, min(900, s))
        # 3D 需要更高（角色是竖长的），宽高比 ~3:4
        w = int(s * 1.45)
        h = int(s * 1.95)
        return (max(180, w), max(260, h))

    def _web3d_sync_size(self):
        """尺寸联动：2D 桌宠尺寸变化 → 3D 窗口等比变化"""
        try:
            w = getattr(self, '_web3d_win', None)
            if w is None:
                return
            nw, nh = self._web3d_view_size()
            if (w.width(), w.height()) != (nw, nh):
                # 保持左下角不动的观感：以底边中点为锚点缩放
                cx = w.x() + w.width() // 2
                bottom = w.y() + w.height()
                w.resize(nw, nh)
                w.move(cx - nw // 2, bottom - nh)
                w.view.setGeometry(0, 0, nw, nh)
                print('web3d size sync -> %dx%d' % (nw, nh))
        except Exception as e:
            print('web3d sync size err:', e)

    # ---------------- 外置 Mate-Engine 后端 ----------------
    def _switch_to_3d_mate(self):
        """切到外置 3D：启动 Mate-Engine → 显示其窗口 → 隐藏自己 → 浮层 + 尺寸"""
        self.hide()
        self._in3d = True

        def _show_overlay_and_sync():
            # 等 3D 窗口就绪
            for _ in range(30):
                if not self._mate3d_online():
                    self._mate3d_launch()
                    time.sleep(1)
                    continue
                break
            hwnd = self._mate3d_hwnd()
            if hwnd:
                self._win32_show(hwnd, True)
                self._mate3d_raise(hwnd)
            try:
                _mate_link.topmost(True)
            except Exception:
                pass
            # 尺寸同步：2D 桌宠尺寸 → 3D 角色大小
            self._mate3d_sync_size()
            # 显示三横浮层（跟随 Mate 窗口）
            QTimer.singleShot(600, self._show_mate_overlay)

        threading.Thread(target=_show_overlay_and_sync, daemon=True).start()

    def _mate3d_sync_size(self):
        """尺寸同步：按 2D 桌宠当前尺寸推算 3D 角色 avatarSize。
        2D 基准 BASE_SIZE(=200) → 3D 基准 1.0；比例线性映射并限制在 0.3~2.0"""
        try:
            if _mate_link is None or not self._mate3d_online():
                return
            base = float(BASE_SIZE) or 200.0
            ratio = float(getattr(self, '_pet_size', base)) / base
            v = max(0.3, min(2.0, round(ratio, 3)))
            _mate_link.scale(v)
            print('mate3d size sync ->', v)
        except Exception as e:
            print('mate3d sync size err:', e)

    def _show_mate_overlay(self):
        """显示 3D 模式三横浮层（跟随 3D 窗口位置）"""
        try:
            if self._mate_overlay is None:
                self._mate_overlay = MateOverlay(self)
            self._mate_overlay.follow_mate()
            self._mate_overlay.show()
            self._mate_overlay.raise_()
            # 定时跟随。原来是 400ms，用户反馈「跟随延迟很高」（拖动 3D 窗口时
            # 三横要过 0.4 秒才挪过去）→ 降到 33ms（约 30fps），肉眼基本感觉不到滞后。
            if self._mate_overlay_timer is None:
                self._mate_overlay_timer = QTimer(self)
                self._mate_overlay_timer.timeout.connect(self._tick_overlay)
            self._mate_overlay_timer.start(33)
        except Exception as e:
            print('show overlay err:', e)

    def _tick_overlay(self):
        """浮层跟随 Mate 窗口（3D 模式下持续生效）"""
        try:
            if not getattr(self, '_in3d', False) or self._mate_overlay is None:
                return
            if not self._mate_overlay.isVisible():
                return
            self._mate_overlay.follow_mate()
        except Exception:
            pass

    def _hide_mate_overlay(self):
        try:
            if self._mate_overlay_timer is not None:
                self._mate_overlay_timer.stop()
            if self._mate_overlay is not None:
                self._mate_overlay.hide()
        except Exception:
            pass

    def _mate_open_menu(self):
        """3D 模式点三横 → 弹出与 2D 相同的菜单（功能全保留）"""
        try:
            menu = self._build_role_menu(None)
            self._tray_menu = menu  # 防 GC
            pos = QCursor.pos()
            menu.exec(pos)
        except Exception as e:
            print('mate open menu err:', e)

    def _mate_overlay_hover(self, on):
        """浮层悬停 → 触发 3D 角色对话（可开关）"""
        try:
            if on and getattr(self, '_mate_hover_chat', True):
                self._mate3d_hover_chat()
        except Exception:
            pass

    def _mate3d_hover_chat(self):
        """3D 悬停对话：让 3D 角色说一句话（AI 可用则用 AI，否则本地台词）"""
        # 节流：2 秒内不重复触发
        now = time.monotonic()
        if now - getattr(self, '_last_hover_chat', 0.0) < 2.0:
            return
        self._last_hover_chat = now
        text = None
        # 优先用 AI 生成一句（若 AI 已启用）
        try:
            ai = getattr(self, 'ai', None)
            if ai is not None and hasattr(ai, 'quick_reply'):
                text = ai.quick_reply("（用户把鼠标移到了你身上，说一句简短的招呼，15 字以内）")
        except Exception:
            text = None
        if not text:
            import random
            pool = ["怎么啦？", "在的在的～", "摸摸头！", "有什么事吗？",
                    "我一直在这里哦", "要不要一起玩？"]
            text = random.choice(pool)
        try:
            self._mate3d_cmd('say', text=text)
            print('hover chat ->', text)
        except Exception as e:
            print('hover chat err:', e)

    def _switch_to_2d(self):
        """切回简易桌宠：隐藏 3D 窗口（不退出）+ 隐藏浮层 + 显示自己"""
        self._hide_mate_overlay()
        # 内置 Web 3D：隐藏窗口（保留进程，回来秒开）
        try:
            if getattr(self, '_web3d_win', None) is not None:
                self._web3d_win.hide()
        except Exception:
            pass
        # 外置 Mate-Engine：隐藏其窗口
        hwnd = self._mate3d_hwnd()
        if hwnd:
            self._win32_show(hwnd, False)
        self._in3d = False
        # ★ 输入栏定位锚点还原到真 2D 桌宠（否则输入栏还贴着 3D 窗口位置）
        try:
            self._set_geo_anchor(None)
        except Exception as _e:
            print('anchor 2d err:', _e)
        self.show()
        self.raise_()
        self.activateWindow()

    def _mate3d_cmd(self, op, **kw):
        """发送 3D 命令 —— 按当前后端自动分派（web 内置优先，mate 外置兜底）。

        这样上层菜单代码完全不用改：同一个 'say'/'scale'/'topmost' 调用，
        会自动走内置 three-vrm 或外置 Mate-Engine。
        """
        try:
            if getattr(self, '_3d_backend', 'web') == 'web' and _WEB3D_OK:
                if self._web3d_cmd(op, **kw):
                    return
            if _mate_link is None:
                return
            getattr(_mate_link, op)(**kw)
        except Exception as e:
            print('mate3d cmd err:', op, e)

    def _web3d_cmd(self, op, **kw):
        """把统一的 3D 命令翻译成内置 Web 3D 的操作。返回 True 表示已处理。"""
        w = getattr(self, '_web3d_win', None)
        try:
            if op == 'say':
                if w is None:
                    return True   # 已认领（避免落到 mate 后端），只是窗口还没建好
                w.say(str(kw.get('text', '')), int(kw.get('ms', 3500)))
                return True

            if op == 'topmost':
                if w is not None:
                    w.set_topmost(bool(kw.get('on', True)))
                return True

            if op == 'scale':
                # 统一语义：value 为倍率(1.0=基准) → 换算成窗口尺寸
                if w is not None:
                    v = float(kw.get('value', 1.0))
                    base = int(getattr(self, '_pet_size', BASE_SIZE))
                    nw = max(140, int(base * 1.45 * v))
                    nh = max(200, int(base * 1.95 * v))
                    w.resize(nw, nh)
                    w.view.setGeometry(0, 0, nw, nh)
                    print('web3d scale -> %dx%d' % (nw, nh))
                return True

            if op == 'blend_set':
                if w is not None:
                    w.expression(str(kw.get('name', '')), float(kw.get('value', 100.0)) / 100.0)
                return True

            if op == 'blend_reset':
                if w is not None:
                    w.reset_expression()
                return True

            if op == 'sleep':
                if w is not None:
                    on = bool(kw.get('on', True))
                    w.set_blink(not on)
                    w.say('呼…呼…' if on else '我醒啦！', 2600)
                return True

            if op == 'food_spawn':
                if w is not None:
                    w.expression('happy', 0.9)
                    w.say('好吃！', 2200)
                return True

            if op == 'voice_random':
                if w is not None:
                    import random
                    w.say(random.choice(['嗯？', '怎么啦～', '我在哦', '嘿嘿']), 2000)
                return True
        except Exception as e:
            print('web3d cmd err:', op, e)
            return True   # 命令已认领（避免重复下发到 mate）
        # 未识别的命令 → 交回给 mate 后端（或忽略）
        return False

    def _build_mate3d_menu(self, parent):
        """3D 联动子菜单：表情 / 动作 / 尺寸"""
        menu = QMenu(parent)
        menu.setStyleSheet(MENU_QSS)
        online = self._mate3d_online()

        # 在线状态头
        st = QAction("3D 状态：%s" % ("● 在线" if online else "○ 离线"), menu)
        st.setEnabled(False)
        menu.addAction(st)

        if not online:
            act_go = QAction("启动 3D 桌宠（Mate-Engine）", menu)
            act_go.triggered.connect(lambda: self._mate3d_launch())
            menu.addAction(act_go)
            return menu

        # 🎭 3D 角色切换（内置后端=即时热切换；外置后端=重启进程）
        _web_mode = (getattr(self, '_3d_backend', 'web') == 'web' and _WEB3D_OK)
        if _web_mode or _mate_avatar is not None:
            m_role = QMenu("🎭 3D 角色", menu)
            m_role.setStyleSheet(MENU_QSS)

            if _web_mode:
                # 内置：列出 web3d/models 下的全部 VRM，点击即切（0.4 秒）
                w = getattr(self, '_web3d_win', None)
                try:
                    names = w.models() if w is not None else []
                except Exception:
                    names = []
                if not names:
                    try:
                        names = list(_web3d.sync_models().keys())
                    except Exception:
                        names = []
                cur = ''
                try:
                    cur = (w._model_name if w is not None else 'michelle')
                except Exception:
                    cur = ''
                # 去掉重复项：michelle 与 michelle_expr 是同一个角色
                # （后者补了表情，必须优先保留，否则切过去表情全没了）
                seen_role = set()
                for n in _prefer_expr_models(names):
                    role = _MODEL_ALIAS.get(n.lower(), n)
                    if role in seen_role:
                        continue
                    seen_role.add(role)
                    label = _MODEL_LABELS.get(n.lower(), n)
                    mark = " ✓" if n.lower() == str(cur).lower() else ""
                    act = QAction(label + mark, m_role)
                    act.setToolTip("点击即时切换（无需重启，约 0.4 秒）")
                    act.triggered.connect(
                        lambda c, nn=n: self._mate3d_switch_avatar(nn + '.vrm', nn + '.vrm'))
                    m_role.addAction(act)
                if not names:
                    na = QAction("（未找到 VRM 模型）", m_role)
                    na.setEnabled(False)
                    m_role.addAction(na)
            else:
                try:
                    cur_path = (_mate_avatar.current_model() or "").lower()
                    models = _mate_avatar.list_models()
                except Exception:
                    cur_path, models = "", []
                if models:
                    for name, path in models:
                        mark = " ✓" if path.lower() == cur_path else ""
                        display = os.path.splitext(name)[0]
                        act = QAction(display + mark, m_role)
                        act.triggered.connect(
                            lambda c, p=path, n=name: self._mate3d_switch_avatar(p, n))
                        m_role.addAction(act)
                else:
                    na = QAction("（未找到 VRM 模型）", m_role)
                    na.setEnabled(False)
                    m_role.addAction(na)

            m_role.addSeparator()
            # 后端切换（内置 ⇄ 外置 Mate-Engine）
            m_be = QMenu("⚙ 3D 引擎", m_role)
            m_be.setStyleSheet(MENU_QSS)
            for label, key, tip in (
                ("内置引擎（推荐·即时切换）", 'web', "three-vrm 内置渲染：热切换 0.4s，无需外部程序"),
                ("Mate-Engine（外置）", 'mate', "外置进程：切模型需重启（5~40s），玩法更丰富"),
            ):
                if key == 'web' and not _WEB3D_OK:
                    continue
                a = QAction(("● " if key == self._3d_backend else "○ ") + label, m_be)
                a.setToolTip(tip)
                a.triggered.connect(lambda c, k=key: self._set_3d_backend(k))
                m_be.addAction(a)
            m_role.addMenu(m_be)

            act_dir = QAction("📂 打开模型目录", m_role)
            act_dir.triggered.connect(lambda: self._open_3d_model_dir())
            m_role.addAction(act_dir)
            menu.addMenu(m_role)

        # 表情（内置引擎读 VRM 表情表；外置 Mate 读其 blends 表）
        blends = {}
        _web_exprs = []
        if _web_mode:
            # ★ 内置引擎：表情名是 VRM 标准名（aa/ih/ou/ee/oh/blink/happy…），
            #   和外置 Mate 的日文 blends 名不通用 —— 之前统一走 _mate_link
            #   会拿到 Mate 的表，点到就落空。
            try:
                w = getattr(self, '_web3d_win', None)
                if w is not None:
                    _web_exprs = list(getattr(w, '_expressions', []) or [])
            except Exception:
                _web_exprs = []
            if not _web_exprs:
                _web_exprs = _WEB_DEFAULT_EXPRS
        else:
            try:
                blends = _mate_link.blends_dict()
            except Exception:
                blends = {}

        if _web_mode and _web_exprs:
            m_expr = QMenu("😊 表情", menu)
            m_expr.setStyleSheet(MENU_QSS)
            # 全部表情按「可见生效程度」排序，常用的放前面
            for name, label in _WEB_EXPR_LABELS:
                if name not in _web_exprs:
                    continue
                act = QAction("%s  %s" % (label, name), m_expr)
                act.triggered.connect(
                    lambda c, n=name: (self._mate3d_cmd('blend_reset'),
                                       self._mate3d_cmd('blend_set', name=n, value=100.0)))
                m_expr.addAction(act)
            # 其余未列出的表情也放进来（保证「该插件有的所有功能」不丢）
            rest = [n for n in _web_exprs
                    if n not in [k for k, _ in _WEB_EXPR_LABELS] and n != 'neutral']
            if rest:
                m_more = QMenu("更多表情", m_expr)
                m_more.setStyleSheet(MENU_QSS)
                for name in rest:
                    act = QAction(name, m_more)
                    act.triggered.connect(
                        lambda c, n=name: (self._mate3d_cmd('blend_reset'),
                                           self._mate3d_cmd('blend_set', name=n, value=100.0)))
                    m_more.addAction(act)
                m_expr.addMenu(m_more)
            m_expr.addSeparator()
            act_r = QAction("🔄 重置表情", m_expr)
            act_r.triggered.connect(lambda: self._mate3d_cmd('blend_reset'))
            m_expr.addAction(act_r)
            menu.addMenu(m_expr)
        elif blends:
            nice = {'にこり': '微笑', '笑い': '笑', '怒り': '生气', '困る': '困扰',
                    '真面目': '认真', 'まばたき': '眨眼', 'ウィンク': '眨眼(右)'}
            m_expr = QMenu("😊 表情", menu)
            m_expr.setStyleSheet(MENU_QSS)
            for name in ('にこり', '笑い', '怒り', '困る', '真面目'):
                if name in blends:
                    cur = blends.get(name, 0)
                    act = QAction("%s%s" % (nice.get(name, name),
                                            (" ✓" if cur and cur > 1 else "")), m_expr)
                    act.triggered.connect(
                        lambda c, n=name: (self._mate3d_cmd('blend_reset'),
                                           self._mate3d_cmd('blend_set', name=n, value=80.0)))
                    m_expr.addAction(act)
            act_r = QAction("重置表情", m_expr)
            act_r.triggered.connect(lambda: self._mate3d_cmd('blend_reset'))
            m_expr.addAction(act_r)
            menu.addMenu(m_expr)

        # 动作
        m_act = QMenu("🎬 动作", menu)
        m_act.setStyleSheet(MENU_QSS)
        a1 = QAction("💤 睡觉", m_act)
        a1.triggered.connect(lambda: self._mate3d_cmd('sleep', on=True))
        m_act.addAction(a1)
        a2 = QAction("🌞 唤醒", m_act)
        a2.triggered.connect(lambda: self._mate3d_cmd('sleep', on=False))
        m_act.addAction(a2)
        a3 = QAction("🍰 喂食", m_act)
        a3.triggered.connect(lambda: self._mate3d_cmd('food_spawn', index=0))
        m_act.addAction(a3)
        a4 = QAction("🗣 随机语音", m_act)
        a4.triggered.connect(lambda: self._mate3d_cmd('voice_random'))
        m_act.addAction(a4)
        m_act.addSeparator()
        a5 = QAction("⏭ 舞蹈：下一首", m_act)
        a5.triggered.connect(lambda: self._mate3d_cmd('dance_next'))
        m_act.addAction(a5)
        a6 = QAction("⏹ 舞蹈：停止", m_act)
        a6.triggered.connect(lambda: self._mate3d_cmd('dance_stop'))
        m_act.addAction(a6)
        menu.addMenu(m_act)

        # 尺寸
        m_size = QMenu("📐 尺寸", menu)
        m_size.setStyleSheet(MENU_QSS)
        for label, v in (("放大 1.2×", 1.2), ("还原 1.0×", 1.0), ("缩小 0.8×", 0.8)):
            act = QAction(label, m_size)
            act.triggered.connect(lambda c, vv=v: self._mate3d_cmd('scale', value=vv))
            m_size.addAction(act)
        menu.addMenu(m_size)

        # 窗口
        m_win = QMenu("🪟 窗口", menu)
        m_win.setStyleSheet(MENU_QSS)
        a_t = QAction("置顶", m_win)
        a_t.triggered.connect(lambda: self._mate3d_cmd('topmost', on=True))
        m_win.addAction(a_t)
        a_nt = QAction("取消置顶", m_win)
        a_nt.triggered.connect(lambda: self._mate3d_cmd('topmost', on=False))
        m_win.addAction(a_nt)
        menu.addMenu(m_win)

        # 隐藏手（Q 版互动）
        m_hide = QMenu("🙈 藏手", menu)
        m_hide.setStyleSheet(MENU_QSS)
        for label, l, r in (("藏左手", True, False), ("藏右手", False, True), ("都藏", True, True), ("都放", False, False)):
            act = QAction(label, m_hide)
            act.triggered.connect(lambda c, ll=l, rr=r: self._mate3d_cmd('hide_arm', left=ll, right=rr))
            m_hide.addAction(act)
        menu.addMenu(m_hide)

        # 🎮 互动（Mate-Engine 原生玩法）
        m_fun = QMenu("🎮 互动", menu)
        m_fun.setStyleSheet(MENU_QSS)
        f1 = QAction("🍼 Q 版模式", m_fun)
        f1.setToolTip("切换 Q 版（小号）形态")
        f1.triggered.connect(lambda: self._mate3d_cmd('chibi'))
        m_fun.addAction(f1)
        f2 = QAction("🖥 大屏模式", m_fun)
        f2.setToolTip("角色放大到整屏互动")
        f2.triggered.connect(lambda: self._mate3d_cmd('bigscreen'))
        m_fun.addAction(f2)
        f3 = QAction("💬 气泡开关", m_fun)
        f3.triggered.connect(lambda: self._mate3d_cmd('bubble'))
        m_fun.addAction(f3)
        f4 = QAction("🗣 让它说句话…", m_fun)
        f4.triggered.connect(lambda: self._mate3d_say_dialog())
        m_fun.addAction(f4)
        f5 = QAction("🔁 自动说话（开/关）", m_fun)
        f5.setToolTip("角色空闲时自动冒出台词")
        f5.triggered.connect(lambda: self._mate3d_toggle_auto_talk())
        m_fun.addAction(f5)
        f6 = QAction("✨ 粒子特效", m_fun)
        f6.triggered.connect(lambda: self._mate3d_cmd('particle_theme', theme='default'))
        m_fun.addAction(f6)
        menu.addMenu(m_fun)

        menu.addSeparator()
        act_ref = QAction("🔄 刷新", menu)
        act_ref.triggered.connect(lambda: self.refresh_tray_menu())
        menu.addAction(act_ref)
        return menu

    # ---------- 3D 互动辅助 ----------
    def _set_3d_backend(self, key):
        """切换 3D 引擎（web 内置 / mate 外置）。切换时退出当前 3D 模式。"""
        try:
            key = 'web' if key == 'web' and _WEB3D_OK else 'mate'
            if key == self._3d_backend:
                return
            # 先退回 2D，避免两个 3D 同时存在
            if getattr(self, '_in3d', False):
                self._switch_to_2d()
            self._3d_backend = key
            cfg = load_config()
            cfg['3d_backend'] = key
            save_config(cfg)
            print('3d backend ->', key)
            self.refresh_tray_menu()
        except Exception as e:
            print('set 3d backend err:', e)

    def _open_3d_model_dir(self):
        """打开 3D 模型目录（内置后端用 web3d/models；外置用 Mate 模型目录）"""
        try:
            if getattr(self, '_3d_backend', 'web') == 'web' and _WEB3D_OK:
                d = str(_web3d.MODEL_DIR)
            else:
                d = r"C:\Users\mier\Desktop\deepseek work\mate-engine\michelle_model"
            if not os.path.isdir(d):
                os.makedirs(d, exist_ok=True)
            os.startfile(d)
        except Exception as e:
            print('open 3d model dir err:', e)

    def _mate3d_say_dialog(self):
        """弹输入框让 3D 角色说话"""
        try:
            from PyQt6.QtWidgets import QInputDialog, QLineEdit
            text, ok = QInputDialog.getText(
                self, "让 3D 角色说话", "输入台词：", QLineEdit.EchoMode.Normal)
            if ok and text.strip():
                self._mate3d_cmd('say', text=text.strip())
        except Exception as e:
            print('say dialog err:', e)

    def _mate3d_toggle_auto_talk(self):
        """自动说话开关（随机消息）"""
        try:
            cur = getattr(self, '_mate_auto_talk', False)
            self._mate_auto_talk = not cur
            self._mate3d_cmd('random_messages', on=self._mate_auto_talk)
            print('auto talk ->', self._mate_auto_talk)
        except Exception as e:
            print('auto talk err:', e)

    def _audio_key(self, role, path):
        """音频唯一 key：角色名/相对角色根的路径（含子文件夹，跨角色稳定）"""
        base = role_root(role)
        try:
            rel = os.path.relpath(path, base)
            if not rel.startswith('..') and not os.path.isabs(rel):
                return "%s/%s" % (role, rel.replace('\\', '/'))
        except Exception:
            pass
        return "%s/%s" % (role, os.path.basename(path))

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
        """切换角色。注意：可能从 QMenu triggered 回调进入——Qt 在菜单回调栈内
        重建菜单/托盘菜单/弹窗会触发 Qt6Core 0xc0000409（游戏环境更易现），
        因此除【换图】(load_role 必须同步)外的 UI 刷新全部延后到事件循环。"""
        try:
            _dbg('[pet] switch_role -> %s' % role)
        except Exception:
            pass
        self.load_role(role)   # 同步换图（必须立即）
        # ---- 以下全部延后，避免在菜单回调栈内做 UI 重建 ----
        # ⚠ 切角色后【不重开菜单】：游戏全屏/锁鼠标时 QMenu popup 重开会触发
        #    Qt6Core 0xc0000409（用户游戏里切角色崩溃的根因）；切完自然关闭即可。
        QTimer.singleShot(0, lambda: self.refresh_tray_menu())
        # 同步角色的 AI 专属配置：TTS 克隆参考 + 系统提示词（切角色自动换人设/音色）
        try:
            self._apply_role_ai_profile(role)
        except Exception:
            pass
        # 每个角色独立上下文：自动切到该角色的会话
        try:
            if self.ai is not None and hasattr(self.ai, 'switch_to_role'):
                self.ai.switch_to_role(role)
        except Exception:
            pass
        # 同步打开的面板：刷新列表 + 重新监视新角色的目录（延后）
        if getattr(self, '_settings_panel', None) is not None:
            QTimer.singleShot(80, self._refresh_panel_after_switch)

    def _refresh_panel_after_switch(self):
        """切角色后延后刷新设置面板（脱离菜单回调栈执行，防 Qt 崩溃）"""
        try:
            if getattr(self, '_settings_panel', None) is not None:
                self._settings_panel.refresh_all()
                self._settings_panel._watch_current_dir()
        except Exception:
            pass

    # ---------------- 设置面板「形象角色」里的 3D 选项 ----------------
    # 设置面板的角色列表来自 pet.roles（2D 图片角色）。3D 米雪儿不是图片角色，
    # 所以用这个哨兵值作为特殊条目，_on_role_clicked 见到它就走 3D 切换。
    ROLE_3D = '__3d__'

    def is_3d_role(self) -> bool:
        """当前是否正在使用 3D 形象"""
        return bool(getattr(self, '_in3d', False))

    def switch_to_3d_from_panel(self):
        """设置面板点「3D 米雪儿」→ 切到 3D（与菜单「切换到 3D 桌宠」同一条路径）"""
        try:
            if not self.is_3d_role():
                self.switch_face()
        except Exception as e:
            print('switch_to_3d_from_panel err:', e)

    def switch_to_2d_from_panel(self):
        """设置面板从 3D 切回 2D 图片角色：先退 3D，再换图"""
        try:
            if self.is_3d_role():
                self.switch_face()   # 退回 2D
        except Exception as e:
            print('switch_to_2d_from_panel err:', e)

    def switch_to_3d_for_role(self, role):
        """给指定 2D 角色切换到它的 3D 形象（设置面板右键「切换 3D 形象」）。

        与普通 3D 切换的区别：先把这个 2D 角色设为当前角色（这样语音/AI 人设
        跟着走），再进 3D 并加载对应模型。
        """
        try:
            # ① 2D 角色先切过去（语音来源、AI 人设都绑在角色上）
            if role and role != getattr(self, 'role', None):
                self.switch_role(role)
            # ② 进 3D
            if not self.is_3d_role():
                self.switch_face()
            # ③ 加载该角色对应的 3D 模型（等窗口就绪后热切换）
            model = None
            try:
                model = _web3d.role_3d_model(role) if _web3d is not None else None
            except Exception:
                model = None
            if model:
                self._pending_3d_model = model

                def _apply_model():
                    w = getattr(self, '_web3d_win', None)
                    if w is None:
                        return
                    if not getattr(self, '_web3d_ready', False):
                        QTimer.singleShot(300, _apply_model)
                        return
                    if w.set_model(model):
                        print('3d role model ->', model)
                        QTimer.singleShot(700, lambda: self._mate3d_cmd(
                            'say', text='我是%s，请多关照～' % model.split('_')[0]))

                QTimer.singleShot(400, _apply_model)
        except Exception as e:
            print('switch_to_3d_for_role err:', e)

    def _role_has_3d(self, role) -> bool:
        """该 2D 角色是否有可用的 3D 形象（设置面板据此决定是否显示右键项）"""
        try:
            return bool(_web3d is not None and _web3d.role_3d_model(role))
        except Exception:
            return False

    def _apply_role_ai_profile(self, role):
        """切换角色时自动更新 AI 配置（TTS 克隆音色 + 系统提示词）：
        - TTS 克隆参考：优先纯英文路径 references/refs_en/<英文名>.wav（audiocpp 只支持
          ASCII 路径，中文路径/文件名会 500）；无英文副本时回退中文 assets/tts_refs/<角色名>/ref.wav
        - ref.txt 转录文本 与 system_prompt.txt 提示词都从 tts_refs/<角色名>/ 读取
        仅当角色名素材存在时才覆盖（避免误清空用户手动配置）。
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
            # 1) 克隆参考音频 + 转录（参考音频优先纯英文路径）
            #    英文路径：breeze-tts-local/audio-cpp/references/refs_en/<英文名>.wav
            en_name = ROLE_EN_NAMES.get(cname)
            ref_wav = None
            if en_name:
                for cand_root in (
                    # 常见相对位置（用户目录下）
                    os.path.join(os.path.expanduser('~'), 'Desktop', 'deepseek work',
                                 'breeze-tts-local', 'audio-cpp', 'references', 'refs_en'),
                ):
                    cand = os.path.join(cand_root, en_name + '.wav')
                    if os.path.exists(cand):
                        ref_wav = cand
                        break
            if not ref_wav:
                fallback = os.path.join(ref_dir, 'ref.wav')
                if os.path.exists(fallback):
                    ref_wav = fallback
            ref_txt = os.path.join(ref_dir, 'ref.txt')
            if ref_wav and os.path.exists(ref_txt):
                with open(ref_txt, encoding='utf-8') as f:
                    text = f.read().strip()
                ai['tts_api_ref'] = ref_wav
                ai['tts_api_ref_text'] = text
                # 新 tts 段（2026-09-09 起 TTS 配置独立存储；ai 段旧键保留兼容）
                tts = cfg.get('tts') or {}
                if not isinstance(tts, dict):
                    tts = {}
                tts['ref'] = ref_wav
                tts['ref_text'] = text
                cfg['tts'] = tts
                changed = True
            # 2) 系统提示词：丰富人格提示词（assets/persona/<角色名>.txt）优先，
            #    无则用模板（assets/tts_refs/<角色名>/system_prompt.txt）
            sp_candidates = []
            persona_f = os.path.join(assets_dir(), 'persona', cname + '.txt')
            if os.path.exists(persona_f):
                sp_candidates.append(persona_f)
            sp_tpl = os.path.join(ref_dir, 'system_prompt.txt')
            if os.path.exists(sp_tpl):
                sp_candidates.append(sp_tpl)
            for sp in sp_candidates:
                try:
                    with open(sp, encoding='utf-8') as f:
                        prompt = f.read().strip()
                except Exception:
                    continue
                if prompt:
                    ai['system_prompt'] = prompt
                    changed = True
                    break
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
    # ---- 崩溃诊断（写入数据目录 crash_diag.log）----
    # Qt 层 0xc0000409 是 C++ 崩溃（Python traceback 抓不到），faulthandler
    # 可记录崩溃瞬间各线程的 Python 栈，帮助定位崩溃前最后动作
    try:
        import faulthandler
        crash_log = os.path.join(base_dir(), 'crash_diag.log')
        try:
            faulthandler.enable(open(crash_log, 'a', encoding='utf-8', buffering=1))
        except Exception:
            pass
    except Exception:
        pass
    try:
        def _hook(exc_type, exc, tb):
            try:
                import traceback as _tb
                with open(os.path.join(base_dir(), 'crash_diag.log'), 'a', encoding='utf-8') as f:
                    f.write('\n=== unhandled python exception ===\n')
                    _tb.print_exception(exc_type, exc, tb, file=f)
            except Exception:
                pass
            sys.__excepthook__(exc_type, exc, tb)
        sys.excepthook = _hook
    except Exception:
        pass
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
