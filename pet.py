# pet.py —— 独立 Win11 桌面桌宠（PyQt6 版）
# 功能：透明置顶浮窗、点按播音（星绘早/午/晚 + 白墨冲刺）、按压弹性动画、拖动贴边、托盘、角色可扩展。
# 菜单：悬停时右上角三横按钮 → 深色圆角菜单（切角色 / 退出）；托盘同款菜单。
# 技术：PyQt6（python 3.14），per-pixel alpha 透明，打包成单文件 exe。
#
# 资源：assets/characters/<角色>/image.png + 语音 mp3。
#   - 星绘:  image.png + morning/noon/evening.mp3（按当前时间选）
#   - 白墨:  image.png + sprint.mp3
#   - 其他:  image.png + click.mp3（优先）或 morning.mp3
#
# 交互：左键点按=播音（按下压扁回弹），拖动=移动(贴边)，左键拖动超过阈值不算点击；
#       鼠标悬停右上角出现 ☰ 按钮 → 点击弹菜单（切换角色 / 退出）。
import sys
import os
import math
import json
import time
import threading
import ctypes
from datetime import datetime
from ctypes import wintypes

from PyQt6.QtCore import Qt, QTimer, QPoint, QRect, QUrl, QEvent, QObject
from PyQt6.QtGui import QPixmap, QIcon, QAction, QActionGroup, QCursor, QPainter, QColor, QPen, QImage
from PyQt6.QtWidgets import (
    QApplication, QWidget, QMenu,
    QSystemTrayIcon,
)
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput

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


PET_VERSION = "1.5.0"
DEFAULT_ROLE = "星绘"
BASE_SIZE = 200

# 配置（绑定输出设备等）存放：与 exe 同目录 pet_config.json（打包后在 _MEIPASS 只读，
# 故优先写 exe 所在目录，其次 home）
def config_dir():
    if hasattr(sys, "_MEIPASS"):
        base = os.path.dirname(os.path.abspath(sys.executable))
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    try:
        os.makedirs(base, exist_ok=True)
        test = os.path.join(base, '.pet_write_test')
        with open(test, 'w') as f:
            f.write('1')
        os.remove(test)
        return base
    except Exception:
        return os.path.expanduser('~')

CONFIG_FILE = os.path.join(config_dir(), 'pet_config.json')


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


def _log(*args):
    # 保留空实现，便于未来排查（不再默认密集打点）
    pass


def _dbg(msg):
    """调试日志：写 pet_debug.log（GUI 无控制台，print 不可见）"""
    try:
        logpath = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pet_debug.log')
        with open(logpath, 'a', encoding='utf-8') as f:
            f.write(str(msg) + '\n')
    except Exception:
        pass


def base_dir():
    """exe 所在目录（打包后为 _MEIPASS，未打包为脚本目录）"""
    if hasattr(sys, "_MEIPASS"):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))


def assets_dir():
    d = os.path.join(base_dir(), "assets")
    os.makedirs(d, exist_ok=True)
    return d


def chars_dir():
    return os.path.join(assets_dir(), "characters")


def list_roles():
    """从 assets/characters/ 扫描角色子目录（可扩展：丢文件夹即加角色）"""
    roles = []
    d = chars_dir()
    if os.path.isdir(d):
        for name in os.listdir(d):
            full = os.path.join(d, name)
            if os.path.isdir(full) and os.path.exists(os.path.join(full, "image.png")):
                roles.append(name)
    return roles or [DEFAULT_ROLE]


def role_dir(role):
    return os.path.join(chars_dir(), role)


# 支持的音频扩展名（角色目录下这些文件都会出现在菜单里）
AUDIO_EXTS = ('.mp3', '.wav', '.ogg', '.m4a', '.flac')

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


def list_role_audio(role):
    """列出角色目录下所有音频文件 → [(显示名, 绝对路径)]（按文件名排序）"""
    d = role_dir(role)
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


def _decode_and_prepare(path):
    """读音频 → (float32 二维数组, 采样率)，失败返回 None"""
    try:
        data, sr = _sf.read(path, dtype='float32', always_2d=True)
        if data.size == 0:
            return None
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
            pad = _np.zeros((data.shape[0], ch - data.shape[1]), dtype='float32')
            data = _np.concatenate([data, pad], axis=1)
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
WM_SYSKEYDOWN = 0x0104
VK_ESCAPE = 0x1B
# 忽略的修饰键（单独按不应作为绑定键）
_MODIFIER_VKS = {0x10, 0x11, 0x12, 0x5B, 0x5C, 0xA0, 0xA1, 0xA2, 0xA3}


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


def audio_duration_seconds(path):
    """获取音频时长（秒）"""
    try:
        import soundfile as _sfx
        info = _sfx.info(path)
        return info.duration
    except Exception:
        return 0.0


class PetWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.roles = list_roles()
        self.role = DEFAULT_ROLE if DEFAULT_ROLE in self.roles else self.roles[0]
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
        # 语音自定义快捷键: { 音频key(角色/文件名): 键名 }
        self._audio_hotkeys = dict(_cfg.get('audio_hotkeys', {}))
        self._sd_stream = None       # 正在播放的 sounddevice 流（防 GC）

        # 自绘：窗口固定尺寸，绘制时用 scale（origin=底部中心，复刻插件 transform-origin:50% 100%）
        self.pixmap = None          # 当前角色图
        self._scale_x = 1.0
        self._scale_y = 1.0
        self.setFixedSize(BASE_SIZE, BASE_SIZE)

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

        self.load_role(self.role)
        self.init_tray()
        self.place_default()
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
        # 先注销旧的，再全新注册（防残留/重复）
        try:
            unregister_numpad_hotkeys(hwnd, getattr(self, '_hotkey_ids', {}))
        except Exception:
            pass
        # 注册小键盘 1-9 默认映射（数字作为回退）
        self._hotkey_ids = register_numpad_hotkeys(hwnd)
        # 注册自定义键（音频快捷键）
        # 自定义键: hid → audio_key；跳过与默认小键盘1-9重复的键名（Num1~Num9）
        default_numpad_names = {'Num%d' % i for i in range(1, 10)}
        self._custom_hk_map = {}   # hid → audio_key
        hid_base = CUSTOM_HK_BASE
        for audio_key, key_name in self._audio_hotkeys.items():
            if key_name in default_numpad_names:
                continue  # 由默认数字映射处理
            vk = self._resolve_vk(key_name)
            if vk is None:
                continue
            hid = hid_base + len(self._custom_hk_map)
            if register_single_hotkey(hwnd, hid, vk):
                self._custom_hk_map[hid] = audio_key
        if self._hotkey_ids or self._custom_hk_map:
            self._hotkey_pending = False
            _dbg('hotkeys registered: num=%s custom=%s hwnd=%s' % (
                sorted(self._hotkey_ids), sorted(self._custom_hk_map), hwnd))
        else:
            _dbg('hotkey register all failed, retry (%d)' % self._hk_tries)
            QTimer.singleShot(1000, self._register_hotkeys_now)

    def _resolve_vk(self, key_name):
        """键名/原始VK → 虚拟码。兼容 'VK<数字>' 格式（捕获未知名键时存储）"""
        if key_name.startswith('VK') and key_name[2:].isdigit():
            return int(key_name[2:])
        return key_name_to_vk(key_name)

    def _hotkey_slot_audio(self, num):
        """按小键盘数字取当前角色对应序号的音频并播放（1=第1个音频, 2=第2个…）"""
        audios = list_role_audio(self.role)
        if not audios:
            return
        idx = num - 1
        if 0 <= idx < len(audios):
            label, path = audios[idx]
            self.play_audio(path)

    def _custom_hotkey_audio(self, audio_key):
        """按自定义音频快捷键播放对应音频（audio_key = role/文件名）"""
        # 解析: 格式 "角色名/文件名"
        try:
            role_name, fname = audio_key.rsplit('/', 1)
        except ValueError:
            return
        d = role_dir(role_name)
        path = os.path.join(d, fname)
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
        """退出前注销热键"""
        try:
            hwnd = int(self.winId())
            unregister_numpad_hotkeys(hwnd, self._hotkey_ids)
            for hid in list(getattr(self, '_custom_hk_map', {}).keys()):
                unregister_hotkey(hwnd, hid)
        except Exception:
            pass
        super().closeEvent(e)

    # ------------- 角色 -------------
    def load_role(self, role):
        if role not in self.roles:
            role = self.roles[0]
        self.role = role
        img = os.path.join(role_dir(role), "image.png")
        self.pixmap = None
        if os.path.exists(img):
            pm = QPixmap(img)
            if not pm.isNull():
                pm = pm.scaled(BASE_SIZE, BASE_SIZE, Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
                self.pixmap = pm
        self._scale_x = 1.0
        self._scale_y = 1.0
        self.setFixedSize(BASE_SIZE, BASE_SIZE)
        self.update()

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

    def play_audio(self, path):
        """播放指定音频文件：
        - 有绑定/监听设备 → sounddevice 并行直出到这些设备
          （绑定麦给队友 + 自己耳机自己听），期间按需触发 auto_ptt
        - 都没有 → QMediaPlayer 走系统默认输出，期间同样按需触发 auto_ptt
        """
        if not os.path.exists(path):
            return
        targets = self._target_devices()
        if targets and HAS_SD:
            threading.Thread(target=self._play_direct_worker,
                             args=(path, targets), daemon=True).start()
            return
        # 默认模式：QMediaPlayer（auto_ptt 也要生效）
        if self.player is None:
            return
        try:
            if self._auto_ptt:
                ptt_key_down(self._ptt_vk)
            self.player.stop()
            self.player.setSource(QUrl.fromLocalFile(path))
            self.player.setPosition(0)
            self.player.play()
        except Exception as e:
            print("play error:", e)

        # 音频播完（按时长估算）后松开开麦键
        if self._auto_ptt:
            dur = audio_duration_seconds(path)
            def _release_ptt():
                time.sleep(dur + PTT_HOLD_EXTRA_S)
                ptt_key_up(self._ptt_vk)
            threading.Thread(target=_release_ptt, daemon=True).start()

    def _play_direct_worker(self, path, targets):
        """后台线程：向多个设备并行播放；若开启 auto_ptt，播放开始即按住开麦键，
        音频播完后再多按 0.5 秒松开（防尾部被切）。全部失败回主线程回退 QMediaPlayer"""
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
        d = role_dir(self.role)
        if self.role == "白墨":
            f = os.path.join(d, "sprint.mp3")
        elif self.role == "星绘":
            f = os.path.join(d, self.greeting_for_now() + ".mp3")
        else:
            click = os.path.join(d, "click.mp3")
            f = click if os.path.exists(click) else os.path.join(d, "morning.mp3")
        if os.path.exists(f):
            self.play_audio(f)

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
            painter.save()
            w = self.width()
            h = self.height()
            painter.translate(w / 2.0, h)
            painter.scale(self._scale_x, self._scale_y)
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
            self.play_click_voice()

    # ------------- 窗口交互 -------------
    def place_default(self):
        scr = QApplication.primaryScreen().availableGeometry()
        self.move(scr.right() - self.width() - 24, scr.bottom() - self.height() - 24)

    def init_tray(self):
        """创建托盘图标（仅一次，避免图标堆积）。菜单更新走 refresh_tray"""
        self.tray = QSystemTrayIcon(self)
        # 托盘图标：用星绘形象，缩放到 32px（Windows 托盘实际显示 ~16-32px）
        star = os.path.join(role_dir("星绘"), "image.png")
        if os.path.exists(star):
            pm = QPixmap(star)
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
        group = QActionGroup(self._switch_submenu)
        group.setExclusive(True)
        for r in self.roles:
            act = QAction(r, self._switch_submenu)
            act.setCheckable(True)
            act.setChecked(r == self.role)
            act.triggered.connect(lambda checked, rr=r: self.switch_role(rr))
            group.addAction(act)
            self._switch_submenu.addAction(act)
        act_switch = QAction("切换角色", menu)
        act_switch.setMenu(self._switch_submenu)   # 关联子菜单 → 原生"指向即开"
        menu.addAction(act_switch)

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

        menu.addSeparator()

        # ② 当前角色全部音频（点一下=绑定快捷键；右侧显示已绑键；♫=试听）
        audios = list_role_audio(self.role)
        if audios:
            for label, path in audios:
                akey = self._audio_key(self.role, path)
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

    def switch_role(self, role):
        self.load_role(role)
        self.refresh_tray_menu()
        self._schedule_menu_refresh()
        # 同步打开的面板
        if getattr(self, '_settings_panel', None) is not None:
            self._settings_panel.refresh_all()

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
            self.role = self.roles[0] if self.roles else DEFAULT_ROLE
            self.load_role(self.role)

    # 供设置面板调用的便捷方法（委托模块级函数）
    def base_dir(self):
        return base_dir()

    def chars_dir(self):
        return chars_dir()

    def list_output_devices(self):
        return list_output_devices()

    def list_role_audio(self, role):
        return list_role_audio(role)

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
        """「启用快捷键发话」总开关：关闭时注销全部热键并禁用录制。
        触发菜单自动重开，保证勾选后可连续点其它选项"""
        self._hotkeys_enabled = bool(enabled)
        cfg = load_config()
        cfg['hotkeys_enabled'] = self._hotkeys_enabled
        save_config(cfg)
        self.refresh_tray_menu()
        self._schedule_menu_refresh()
        # 重注册（开=注册，关=注销）
        self._hotkey_pending = True
        if self._hotkeys_enabled:
            self._register_hotkeys_now()
        else:
            # 全部注销
            try:
                hwnd = int(self.winId())
                unregister_numpad_hotkeys(hwnd, self._hotkey_ids)
                for hid in list(self._custom_hk_map.keys()):
                    unregister_hotkey(hwnd, hid)
            except Exception:
                pass
            self._hotkey_ids = {}
            self._custom_hk_map = {}
            self._hotkey_pending = False
            _dbg('hotkeys disabled')
        print('hotkeys_enabled ->', self._hotkeys_enabled)

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
            # 若该键已被其它音频占用 → 释放旧的
            for k, v in list(self._audio_hotkeys.items()):
                if v == key_name and k != audio_key:
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
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        # 鼠标离开窗口（可能只是划过透明空白区）：不立即隐藏，启动 1 秒缓冲
        # 1 秒内回到窗口（enterEvent）则取消；真停在空白处 1 秒后才隐藏
        self._hide_timer.start()
        super().leaveEvent(e)

    def mousePressEvent(self, e):
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
                self.move(cur - self._drag_offset)
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
