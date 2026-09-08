# ai_chat.py —— 卡丘简易桌宠 · AI 对话 + TTS 朗读
# ============================================================================
# 功能：
#   1) AI 对话：OpenAI 兼容 /chat/completions（base_url / api_key / model 可配置，
#      纯标准库 urllib 实现，零新增依赖；走系统代理/环境变量）
#   2) TTS 朗读（依附 AI）：朗读的始终是 AI 回复文本，两种引擎：
#         cloud = edge-tts（微软 Edge 免费云端语音，需联网，走 HTTPS_PROXY 代理）
#         local = Windows 自带 SAPI（comtypes 直调 SpVoice → 写 wav，离线可用）
#      云端失败自动回退本地（边缘场景不失声）
#   3) UI：右键桌宠弹出聊天窗（深色无边框、历史+输入框）；AI 回复以气泡
#      显示在桌宠旁边 + 可选朗读。AI 与 TTS 各自独立开关，TTS 的输入
#      永远来自 AI 回复文本。
# ============================================================================
import asyncio
import html
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

from PyQt6.QtCore import QObject, Qt, QThread, QTimer, QUrl, QRect, QPoint, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen, QFont, QFontMetrics
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

# soundfile/numpy：TTS wav 音量>100% 数字增益用（可选）
try:
    import soundfile as _sf
    import numpy as _np
    HAS_SF = True
except Exception:
    _sf = None
    _np = None
    HAS_SF = False


def _dbg(msg):
    """调试日志：写 pet_debug.log（与 pet.py 同文件；无控制台环境可回溯）"""
    try:
        if pet_mod is not None and hasattr(pet_mod, 'base_dir'):
            p = os.path.join(pet_mod.base_dir(), 'pet_debug.log')
            with open(p, 'a', encoding='utf-8') as f:
                f.write(str(msg) + '\n')
    except Exception:
        pass

# ---------- 可选依赖（都失败也能聊天，只是没有朗读） ----------
try:
    import edge_tts
    HAS_EDGE = True
except Exception:
    edge_tts = None
    HAS_EDGE = False

try:
    import comtypes
    from comtypes.client import CreateObject
    from comtypes.gen import SpeechLib as _SL
    HAS_SAPI = True
except Exception:
    comtypes = None
    CreateObject = None
    _SL = None
    HAS_SAPI = False

# pet.py 启动时注入模块引用（避免循环导入），与 settings_panel 同模式
pet_mod = None


def bind_pet_module(mod):
    global pet_mod, _AUDIO_CPP_SERVER
    pet_mod = mod
    # pet_mod 注入后再定位一次 TTS 服务（数据目录候选此时才可探测）
    try:
        _AUDIO_CPP_SERVER = _find_tts_server()
    except Exception:
        pass


DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_MODEL = "deepseek-chat"
DEFAULT_VOICE = "zh-CN-XiaoxiaoNeural"
TTS_MODE_CLOUD = 'cloud'   # edge-tts 云端（默认）
TTS_MODE_LOCAL = 'local'   # Windows 自带 SAPI（离线）
TTS_MODE_API = 'api'       # 自定义 OpenAI 兼容 /audio/speech 服务（如 OpenAI/硅基流动等）

CHAT_QSS = """
QWidget#chatRoot { background: #1a1c24; }
QLabel { color: #e6e8f0; }
QTextBrowser {
    background: #191b23; border: 1px solid #33374a; border-radius: 8px;
    color: #e6e8f0; font-size: 13px; padding: 6px;
}
QLineEdit {
    background: #2c3142; border: 1px solid #3a4057; border-radius: 8px;
    padding: 7px 10px; color: #e6e8f0;
}
QPushButton {
    background: #2c3142; border: 1px solid #3a4057; border-radius: 8px;
    padding: 7px 14px; color: #e6e8f0;
}
QPushButton:hover { background: #38405a; }
QPushButton:disabled { color: #666b80; background: #22252f; }
"""


# ============================================================================
# 配置读写（pet_config.json 里 "ai" 段）
# ============================================================================
def _ai_cfg():
    if pet_mod is not None:
        cfg = pet_mod.load_config()
        ai = cfg.get('ai') or {}
        return ai if isinstance(ai, dict) else {}
    return {}


def _save_ai_cfg(**kw):
    if pet_mod is None:
        return
    cfg = pet_mod.load_config()
    ai = cfg.get('ai') or {}
    if not isinstance(ai, dict):
        ai = {}
    ai.update(kw)
    cfg['ai'] = ai
    pet_mod.save_config(cfg)


def _tts_dir():
    """TTS 合成产物临时目录（用户数据目录下，可写持久）"""
    if pet_mod is None:
        return None
    try:
        d = os.path.join(pet_mod.base_dir(), 'tts_cache')
        os.makedirs(d, exist_ok=True)
        return d
    except Exception:
        return None


# ============================================================================
# 本地 TTS 服务管理（audio.cpp / audiocpp_server 的启动/停止/状态探测）
# 服务路径可通过环境变量 AUDIOCPP_SERVER 指定；未设置时按本文件同级的
# audio-cpp/bin-cuda/audiocpp_server.exe 查找（便于在本地部署 audio.cpp 后使用）。
# 找不到服务程序时相关启动/停止接口返回明确错误，不影响其它功能。
# ============================================================================
def _find_tts_server():
    """按优先级定位 audiocpp_server.exe：
    1) 环境变量 AUDIOCPP_SERVER
    2) 本文件同级的 audio-cpp/bin-cuda/（打包后 _MEIPASS 内）
    3) 用户数据目录下 audio-cpp/bin-cuda（可写持久，桌面部署常用）
    4) 常见本地部署目录：<项目>/breeze-tts-local/audio-cpp/bin-cuda
    """
    env = (os.environ.get('AUDIOCPP_SERVER') or '').strip()
    if env:
        return env
    here = os.path.dirname(os.path.abspath(__file__))
    cands = [
        os.path.join(here, 'audio-cpp', 'bin-cuda', 'audiocpp_server.exe'),
    ]
    if pet_mod is not None:
        try:
            cands.append(os.path.join(pet_mod.base_dir(), 'audio-cpp',
                                      'bin-cuda', 'audiocpp_server.exe'))
        except Exception:
            pass
    # 项目根/上级目录常见的 breeze-tts-local 部署
    try:
        root = os.path.dirname(here)
        cands.append(os.path.join(root, 'breeze-tts-local', 'audio-cpp',
                                  'bin-cuda', 'audiocpp_server.exe'))
        cands.append(os.path.join(root, 'audio-cpp', 'bin-cuda',
                                  'audiocpp_server.exe'))
    except Exception:
        pass
    # 打包后（_MEIPASS 临时目录内）：向上探测用户桌面/工作目录的常见部署
    if hasattr(sys, '_MEIPASS'):
        try:
            user_home = os.path.expanduser('~')
            cands.append(os.path.join(user_home, 'Desktop', 'deepseek work',
                                      'breeze-tts-local', 'audio-cpp',
                                      'bin-cuda', 'audiocpp_server.exe'))
            # exe 所在目录旁（用户把 audio-cpp 放桌宠数据目录外）
            exe_dir = os.path.dirname(os.path.abspath(sys.executable))
            cands.append(os.path.join(exe_dir, 'audio-cpp', 'bin-cuda',
                                      'audiocpp_server.exe'))
            if pet_mod is not None:
                try:
                    base_dir_ = pet_mod.base_dir()
                    cands.append(os.path.join(base_dir_, 'audio-cpp',
                                              'bin-cuda', 'audiocpp_server.exe'))
                    cands.append(os.path.join(os.path.dirname(base_dir_),
                                              'breeze-tts-local', 'audio-cpp',
                                              'bin-cuda', 'audiocpp_server.exe'))
                except Exception:
                    pass
        except Exception:
            pass
    for c in cands:
        if os.path.exists(c):
            return c
    return cands[0]


_AUDIO_CPP_SERVER = _find_tts_server()
_SERVICE_PROC = None   # 由本模块启动的进程引用
_SERVICE_LOCK = threading.Lock()


def tts_service_url():
    """从配置解析服务健康检查地址（默认 http://127.0.0.1:8080）"""
    ai = _ai_cfg()
    base = (ai.get('tts_api_base') or '').strip() or 'http://127.0.0.1:8080/v1'
    base = _norm_base_url(base)
    # health 端点在根（无 /v1），剥掉可能的 /v1 前缀
    for tail in ('/v1', '/api', '/'):
        if base.endswith(tail):
            base = base[:-len(tail)]
            break
    return base.rstrip('/') or 'http://127.0.0.1:8080'


def tts_service_health(timeout=2.0):
    """探测本地 TTS 服务是否活着。返回 (ok, 详情 str)"""
    base = tts_service_url()
    try:
        req = urllib.request.Request(base.rstrip('/') + '/health', method='GET')
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode('utf-8'))
        return True, '运行中（backend=%s）' % data.get('backend', '?')
    except Exception as e:
        return False, '已停止（%s）' % str(e)[:40]


def _models_paths(kind='auto'):
    """查找 breeze 家族 GGUF 模型文件（可加载列表）。
    kind: 'bf16' 只留 bf16；'q8' 只留 q8；'auto' 优先 bf16 再 q8。
    候选根目录：
      1) svc_dir/models            （bin-cuda/models，旧约定）
      2) svc_dir 上级/models       （audio-cpp/models，bin-cuda 与 models 平级部署）
    遍历各子目录取含 gguf 的路径。"""
    svc_dir = os.path.dirname(_AUDIO_CPP_SERVER)
    roots = [os.path.join(svc_dir, 'models')]
    parent_models = os.path.join(os.path.dirname(svc_dir), 'models')
    if parent_models != roots[0]:
        roots.append(parent_models)
    hits = []
    seen = set()
    for root in roots:
        if not os.path.isdir(root):
            continue
        for sub in sorted(os.listdir(root)):
            subdir = os.path.join(root, sub)
            if not os.path.isdir(subdir):
                continue
            for fn in os.listdir(subdir):
                if fn.lower().endswith('.gguf'):
                    p = os.path.join(subdir, fn)
                    if p not in seen:
                        seen.add(p)
                        hits.append(p)
    # 按 kind 过滤
    if kind == 'bf16':
        hits = [p for p in hits if 'bf16' in p.lower()]
    elif kind == 'q8':
        hits = [p for p in hits if 'bf16' not in p.lower()]
    # 优先 bf16，再 q8；排序稳定
    hits.sort(key=lambda p: (0 if 'bf16' in p.lower() else 1, p))
    return hits


def _server_command(svc_dir, spec_dir):
    """构造 audiocpp_server 启动命令与环境（CUDA PATH + spec override）"""
    CUDA_TOOLKIT = r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v13.3\bin"
    env = dict(os.environ)
    cuda_paths = [p for p in (CUDA_TOOLKIT, CUDA_TOOLKIT + r"\x64", svc_dir) if os.path.isdir(p)]
    env['PATH'] = ';'.join(cuda_paths) + ';' + env.get('PATH', '')
    cmd = [_AUDIO_CPP_SERVER, '--ui', '--ui-management',
           '--backend', 'cuda', '--host', '127.0.0.1']
    if os.path.isdir(spec_dir):
        cmd += ['--model-spec-override', spec_dir]
    return cmd, env


def _api_json(method, url, payload=None, timeout=30):
    """发 JSON 请求，返回解析后的 dict/值；失败抛异常"""
    req = urllib.request.Request(url, method=method)
    req.add_header('Content-Type', 'application/json')
    if payload is not None:
        req.data = json.dumps(payload).encode('utf-8')
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode('utf-8')
    return json.loads(raw) if raw.strip() else None


def tts_service_start():
    """启动本地 audiocpp server 并加载 Breeze 模型。返回 (ok, 消息)
    进程：启动（带 CUDA PATH + spec override）→ 探测就绪 → POST /v1/models/load。"""
    global _SERVICE_PROC
    # 已在跑且模型可用 → 直接返回
    try:
        n = len(_api_json('GET', tts_service_url().rstrip('/') + '/v1/models', timeout=3)['data'])
        if n >= 1:
            return True, '服务已在运行（%d 个模型）' % n
    except Exception:
        pass
    if not os.path.exists(_AUDIO_CPP_SERVER):
        return False, '找不到服务程序：%s' % _AUDIO_CPP_SERVER
    svc_dir = os.path.dirname(_AUDIO_CPP_SERVER)
    spec_dir = os.path.join(svc_dir, 'model_specs')
    cmd, env = _server_command(svc_dir, spec_dir)
    with _SERVICE_LOCK:
        try:
            creation = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
            _SERVICE_PROC = subprocess.Popen(
                cmd, cwd=svc_dir, env=env,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=creation, close_fds=True)
        except Exception as e:
            return False, '启动失败：%s' % e
    # 等 server 就绪（health 可达）
    base = tts_service_url().rstrip('/')
    deadline = time.time() + 60
    ready = False
    while time.time() < deadline:
        if _SERVICE_PROC.poll() is not None:
            return False, '服务进程退出（code=%s）' % _SERVICE_PROC.returncode
        try:
            _api_json('GET', base + '/health', timeout=2)
            ready = True
            break
        except Exception:
            time.sleep(1.0)
    if not ready:
        if _SERVICE_PROC.poll() is not None:
            return False, '服务进程退出（code=%s）' % _SERVICE_PROC.returncode
        return False, '服务启动超时'
    # 加载 Breeze 模型（models 列表默认空，须显式 load）
    # 按用户选择的量化版本加载：bf16 高音质 / q8 省显存（读 ai.tts_model_kind）
    try:
        ai_cfg = _ai_cfg()
        kind = (ai_cfg.get('tts_model_kind') or 'auto').strip().lower()
    except Exception:
        kind = 'auto'
    if kind not in ('bf16', 'q8'):
        kind = 'auto'
    loaded_ok = False
    loaded_path = ''
    for model_path in _models_paths(kind):
        try:
            payload = {
                'id': 'breeze-tts-clone',
                'path': model_path,
                'family': 'breeze_tts',
                'task': 'clon',
                'mode': 'offline',
                'model_spec_override': spec_dir if os.path.isdir(spec_dir) else '',
            }
            res = _api_json('POST', base + '/v1/models/load', payload, timeout=60)
            if isinstance(res, dict) and res.get('loaded'):
                loaded_ok = True
                loaded_path = model_path
                break
        except Exception:
            continue
    if loaded_ok:
        return True, '服务已启动并加载模型（%s）' % os.path.basename(loaded_path or '')
    return False, '服务已启动但模型加载失败，请检查模型文件'


def tts_service_stop():
    """停止本地 audiocpp server。先停本模块启动的进程，再按名结束。返回 (ok, 消息)"""
    global _SERVICE_PROC
    stopped = False
    with _SERVICE_LOCK:
        if _SERVICE_PROC is not None and _SERVICE_PROC.poll() is None:
            try:
                _SERVICE_PROC.terminate()
                try:
                    _SERVICE_PROC.wait(timeout=5)
                except Exception:
                    _SERVICE_PROC.kill()
                stopped = True
            except Exception:
                pass
        _SERVICE_PROC = None
    if not stopped:
        try:
            out = subprocess.run(
                ['taskkill', '/IM', 'audiocpp_server.exe', '/F'],
                capture_output=True, timeout=10,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            so = out.stdout.decode('gbk', errors='replace')
            if '成功' in so or 'SUCCESS' in so.upper():
                stopped = True
        except Exception:
            pass
    return True, '服务已停止' if stopped else '未发现运行中的服务'


def tts_service_pid():
    """返回本模块启动的进程 PID（供 UI 显示）；未启动返回 None"""
    global _SERVICE_PROC
    if _SERVICE_PROC is not None and _SERVICE_PROC.poll() is None:
        return _SERVICE_PROC.pid
    return None


def _detect_proxy():
    """自动探测可用的 HTTP 代理：优先环境变量（HTTP_PROXY/HTTPS_PROXY），
    否则探测本机常见代理端口（Clash 7890 等）。返回 'http://host:port' 或 None。
    避免用户没配系统代理时 edge-tts 云语音 403/超时。只探测一次。"""
    env = (os.environ.get('HTTPS_PROXY') or os.environ.get('HTTP_PROXY')
           or os.environ.get('https_proxy') or os.environ.get('http_proxy') or '')
    if env:
        return env.strip()
    if getattr(_detect_proxy, '_done', False):
        return getattr(_detect_proxy, '_result', None)
    _detect_proxy._done = True
    # 本机快速探测常见代理端口（只连本机 loopback，秒级超时）
    result = None
    for port in (7890, 7897, 10809, 1080, 8080, 8888):
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=0.3):
                result = 'http://127.0.0.1:%d' % port
                break
        except Exception:
            continue
    _detect_proxy._result = result
    return result


# ============================================================================
# OpenAI 兼容请求（纯 urllib，零新依赖）
# ============================================================================
# 部分服务商（如 commandcode.ai）用 Cloudflare 拦截缺浏览器指纹的脚本请求
# （error 1010）。给所有 API 请求补上浏览器特征头即可正常访问。
_CF_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
          '(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36')


def _browser_headers(extra=None):
    h = {
        'User-Agent': _CF_UA,
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'Sec-Fetch-Dest': 'empty',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Site': 'cross-site',
    }
    if extra:
        h.update(extra)
    return h


def _norm_base_url(base_url):
    """规整服务器地址：容忍用户填了完整 /chat/completions 的情况。
    - 输入 https://host/v1/chat/completions → https://host/v1
    - 输入 https://host/v1/            → https://host/v1
    - 输入 https://host/v1/models      → https://host/v1
    规则：去掉末尾 /chat/completions 或 /models 及多余斜杠"""
    s = str(base_url or '').strip()
    for tail in ('/chat/completions', '/models', '/'):
        if s.endswith(tail):
            s = s[:-len(tail)]
            break
    return s.rstrip('/')


# 统一 opener：显式构造，避免打包态环境变量代理导致的
# "unknown url type: https" 类问题；commandcode 等直连可达。
# 若环境变量设了代理则尊重（部分服务需代理），未设则直连。
_OPENER = None


def _get_opener():
    """构造带浏览器头的 opener（首次调用后复用）"""
    global _OPENER
    if _OPENER is not None:
        return _OPENER
    handlers = []
    # 尊重系统/环境代理（urllib 默认行为），仅当环境变量存在
    proxies = urllib.request.getproxies()
    if proxies:
        handlers.append(urllib.request.ProxyHandler(proxies))
    handlers.append(urllib.request.HTTPSHandler())
    _OPENER = urllib.request.build_opener(*handlers)
    return _OPENER


def _open_url(req, timeout):
    """带诊断的 urlopen：失败写日志（含堆栈）+ 重新抛出"""
    try:
        return _get_opener().open(req, timeout=timeout)
    except Exception:
        import traceback
        tb = traceback.format_exc()
        if pet_mod is not None and hasattr(pet_mod, '_dbg'):
            try:
                pet_mod._dbg('[请求] %s %s\n%s' % (req.get_method(), req.full_url, tb))
            except Exception:
                pass
        raise


def _api_speech_synth(base_url, api_key, model, text, voice, out_path, timeout=60,
                      ref_audio='', ref_text='', instruction=''):
    """调 OpenAI 兼容 {base}/audio/speech 合成语音到 out_path。
    返回 True/False；失败抛异常（由调用方兜底）。

    额外支持 audio.cpp / FishSpeech 等本地引擎的克隆 + 情绪参数：
    - ref_audio:   参考音频路径（克隆音色）。填了才走克隆。
    - ref_text:    参考音频的转录（克隆时必填，须与音频内容一致）。
    - instruction: 生成指令/情绪人设。BreezeTTS 2 支持中文情绪描述，
                   如「难过地、低声、带一点哽咽」；留空则由请求方自动补齐。
    """
    url = _norm_base_url(base_url) + '/audio/speech'
    payload = {
        'model': model,
        'input': text,
        'response_format': 'wav',   # audio.cpp 实际总是返回 audio/wav（RIFF 头）
    }
    # ⚠ audio.cpp server 语义（runtime.cpp）：
    #   1) 克隆时绝不能带顶层 "voice" —— 它会设 cached_voice_id（内置音色），
    #      与 voice_ref(参考音频) 同时存在会让引擎优先用内置音色，克隆失效。
    #      参考 WebUI：克隆请求只有 voice_ref + reference_text，无 voice。
    #   2) 情绪/人设字段是复数 "instructions"（单数 instruction 会被忽略）。
    if ref_audio:
        # 克隆音色：voice_ref + reference_text（+ 可选 instructions 情绪）
        payload['voice_ref'] = ref_audio
        if ref_text:
            payload['reference_text'] = ref_text
    else:
        # 无克隆：才发 voice（内置音色/预设名）
        payload['voice'] = voice or ''
    if instruction:
        payload['instructions'] = instruction
    body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(url, data=body, method='POST')
    for k, v in _browser_headers({'Content-Type': 'application/json',
                                  'Authorization': 'Bearer %s' % (api_key or '')}).items():
        req.add_header(k, v)
    with _open_url(req, timeout) as r:
        data = r.read()
    if not data:
        raise RuntimeError('语音服务返回空音频')
    # 统一存成 .wav 文件（QMediaPlayer 通吃 mp3/wav；audio.cpp 返回 WAV 头）
    with open(out_path, 'wb') as f:
        f.write(data)
    return True


def _chat_request(base_url, api_key, model, messages, timeout=90):
    """POST {base_url}/chat/completions，返回 (回复文本, usage dict)。
    usage 形如：
      {'prompt_tokens':n,'completion_tokens':n,'total_tokens':n,
       'prompt_cache_hit_tokens':h,'prompt_cache_miss_tokens':m}
    其中 prompt_cache_* 为 DeepSeek/OpenAI 系「前缀缓存」字段（兼容新/旧命名：
    prompt_cache_hit_tokens / prompt_cache_miss_tokens 与
    prompt_cache_hit / prompt_cache_miss）；服务商没返回则空 dict。失败抛异常。"""
    url = _norm_base_url(base_url) + '/chat/completions'
    body = json.dumps(
        {'model': model, 'messages': messages, 'stream': False},
        ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(url, data=body, method='POST')
    for k, v in _browser_headers({'Content-Type': 'application/json',
                                  'Authorization': 'Bearer %s' % (api_key or '')}).items():
        req.add_header(k, v)
    # urllib 默认 ProxyHandler 会读环境变量 HTTP_PROXY/HTTPS_PROXY（走代理）
    with _open_url(req, timeout) as r:
        data = json.loads(r.read().decode('utf-8'))
    try:
        text = data['choices'][0]['message']['content']
    except Exception:
        text = json.dumps(data, ensure_ascii=False)[:500]
    usage = {}
    try:
        u = data.get('usage') or {}
        for k in ('prompt_tokens', 'completion_tokens', 'total_tokens'):
            if k in u:
                usage[k] = int(u[k] or 0)
        # 缓存命中/未命中输入（DeepSeek 官方字段；部分中转/旧版命名不同）
        hit = u.get('prompt_cache_hit_tokens', u.get('prompt_cache_hit'))
        miss = u.get('prompt_cache_miss_tokens', u.get('prompt_cache_miss'))
        if hit is not None:
            usage['prompt_cache_hit_tokens'] = int(hit or 0)
        if miss is not None:
            usage['prompt_cache_miss_tokens'] = int(miss or 0)
    except Exception:
        usage = {}
    return text, usage


def _list_models(base_url, api_key, timeout=30):
    """GET {base_url}/models，返回模型 ID 列表（OpenAI 兼容标准接口）。
    失败抛异常（401 未授权 / 网络 / 超时等）。"""
    url = _norm_base_url(base_url) + '/models'
    req = urllib.request.Request(url, method='GET')
    for k, v in _browser_headers({'Authorization': 'Bearer %s' % (api_key or '')}).items():
        req.add_header(k, v)
    try:
        with _open_url(req, timeout) as r:
            data = json.loads(r.read().decode('utf-8'))
    except Exception:
        raise
    out = []
    for m in (data.get('data') or []):
        mid = str(m.get('id') or '').strip()
        if mid:
            out.append(mid)
    return out


# ============================================================================
# 本地 SAPI 合成（comtypes 直调 SpVoice → 写 wav）
# 关键坑：SpFileStream.Format.Type 必须先设、再 Open（反了报 0x80045002）
# ============================================================================
def _sapi_synth(text, out_wav, rate=0):
    comtypes.CoInitialize()
    voice = CreateObject('SAPI.SpVoice')
    fs = CreateObject('SAPI.SpFileStream')
    fs.Format.Type = _SL.SAFT22kHz16BitMono   # 22kHz/16bit/mono
    fs.Open(out_wav, _SL.SSFMCreateForWrite)
    voice.AudioOutputStream = fs
    voice.Rate = rate
    voice.Volume = 100
    voice.Speak(text)
    fs.Close()


# ============================================================================
# edge-tts 云端合成（async，在 QThread 里 asyncio.run；兼容 6.x dict / 7.x dataclass）
# ============================================================================
async def _edge_synth(text, voice):
    proxy = _detect_proxy()
    com = edge_tts.Communicate(text, voice, rate='+0%',
                               proxy=proxy or None)
    buf = bytearray()
    async for ev in com.stream():
        if isinstance(ev, dict):                       # edge-tts 6.x
            if ev.get('type') == 'audio':
                buf += ev['data']
        elif isinstance(ev, edge_tts.AudioDataEvent):  # edge-tts 7.x
            buf += ev.data
    if not buf:
        raise RuntimeError('edge-tts 返回空音频')
    return bytes(buf)


# ============================================================================
# 后台线程：AI 对话请求
# ============================================================================
class AIWorker(QThread):
    done = pyqtSignal(str, str, object)   # (回复文本, 错误信息, usage dict)

    def __init__(self, base_url, api_key, model, messages, parent=None):
        super().__init__(parent)
        self._base_url = base_url
        self._api_key = api_key
        self._model = model
        self._messages = messages

    def run(self):
        try:
            reply, usage = _chat_request(self._base_url, self._api_key,
                                         self._model, self._messages)
            if not reply or not reply.strip():
                reply = '（AI 没有返回内容）'
            self.done.emit(reply, '', usage)
        except Exception as e:
            self.done.emit('', '%s' % e, {})


# ============================================================================
# 后台线程：TTS 合成（唯一引擎 = 用户填地址的自定义 OpenAI 兼容语音服务）
# ============================================================================
class TTSWorker(QThread):
    done = pyqtSignal(str, str)   # (音频文件路径, 错误信息；错误时路径为空)

    def __init__(self, text, voice, seq, parent=None, instruction=''):
        super().__init__(parent)
        self._text = text
        self._voice = voice or 'alloy'
        self._seq = seq
        self._instruction = instruction or ''   # 情绪/人设（由改写稿自动补齐）
        self._last_err = ''

    def run(self):
        # 偶发网络抖动 → 重试 1 次
        path = self._synth_once()
        if not path:
            time.sleep(0.5)
            path = self._synth_once()
        if path:
            self.done.emit(path, '')
            return
        self.done.emit('', self._last_err or '语音合成失败（请检查朗读服务地址/密钥/模型）')

    def _synth_once(self):
        base = _tts_dir()
        if not base:
            self._last_err = '没有可写的临时目录'
            return None
        cfg = _ai_cfg()
        api_base = (cfg.get('tts_api_base') or '').strip()
        api_key = (cfg.get('tts_api_key') or '').strip()
        api_model = (cfg.get('tts_api_model') or '').strip()
        if not api_base or not api_key or not api_model:
            self._last_err = '朗读服务未配置：请到 设置 → AI → 朗读服务 里填 地址/密钥/模型'
            return None
        # 克隆音色：参考音频 + 参考转录（配置里填了才启用克隆）
        ref = (cfg.get('tts_api_ref') or '').strip()
        ref_text = (cfg.get('tts_api_ref_text') or '').strip()
        instruction = self._instruction or (cfg.get('tts_api_instruction') or '').strip()
        try:
            path = os.path.join(base, 'tts_%d_%d.wav' % (self._seq, int(time.time() * 1000)))
            _api_speech_synth(api_base, api_key, api_model, self._text,
                              self._voice or 'alloy', path,
                              ref_audio=ref, ref_text=ref_text,
                              instruction=instruction)
            return path
        except Exception as e:
            self._last_err = '%s' % e
            return None


# ============================================================================
# 回复气泡/思考指示：显示在桌宠旁边（跟随桌宠、自动消失、点击关闭）
#  - show_thinking(): 三点跳动思考动画
#  - show_text(text): 逐字蹦字输出（快速），字体显眼
# ============================================================================
_BUBBLE_MAX_W = 620
_BUBBLE_MIN_W = 240
_BUBBLE_LIFE_MS = 5000   # 文字完全显示后停留 5 秒自动消失；点击可立即消失
_FOLLOW_MS = 300
_TYPE_MS = 18          # 每字显示间隔（ms）——约 55 字/秒，快速蹦出
_THINK_MS = 280        # 思考三点跳动间隔

# 蹦字同步：标点=停顿权重（TTS 在标点处会停顿/拖长，文字也按比例"等"）
# 普通字 1.0；逗号/顿号 2.0；句号/问号/感叹/省略号 2.5；破折号 3.0
_PUNCT_WEIGHT = {
    '，': 2.0, '、': 2.0, '；': 2.0, ',': 1.8, ':': 2.0, ';': 2.0,
    '。': 2.5, '！': 2.5, '？': 2.5, '.': 2.5, '!': 2.5, '?': 2.5,
    '…': 2.5, '……': 2.5, '—': 3.0, '——': 3.0, ' ': 1.2,
}


class BubbleWidget(QWidget):
    def __init__(self, pet):
        super().__init__(None,
                         Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool)
        self._pet = pet
        # 完全透明背景（不画底色）；文字用粗白字+深色描边保证任何桌面都清晰
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setMouseTracking(False)
        self._font = QFont('Microsoft YaHei', 24)
        self._font.setBold(True)
        # 自动消失
        self._life = QTimer(self)
        self._life.setSingleShot(True)
        self._life.setInterval(_BUBBLE_LIFE_MS)
        self._life.timeout.connect(self.hide)
        # 跟随桌宠移动（更密集轮询，桌宠拖动时文字贴住）
        self._follow = QTimer(self)
        self._follow.setInterval(16)   # ~60fps，减延迟感
        self._follow.timeout.connect(self._reposition)
        # 逐字蹦字定时器
        self._type_timer = QTimer(self)
        self._type_timer.setInterval(_TYPE_MS)
        self._type_timer.timeout.connect(self._type_step)
        self._type_text = ''
        self._type_pos = 0
        # 语音同步时间表：show_text_synced 预计算每个字符的显示时刻(ms)，
        # _type_step 按时间表推进（语音节奏贴合，标点处等待）
        self._sync_schedule = None
        self._sync_t0 = 0.0
        # 思考动画
        self._think = 0
        self._think_timer = QTimer(self)
        self._think_timer.setInterval(_THINK_MS)
        self._think_timer.timeout.connect(self._think_step)

    # ---------- 显示文本（自绘，带描边） ----------
    def _shown(self):
        if self._think_timer.isActive():
            return self._think_text
        return self._type_text[:self._type_pos]

    def show_thinking(self):
        self._stop_type()
        self._think = 0
        self._think_text = '···'
        self._size_for_full(self._think_text)
        self._reposition()
        self.show()
        self.raise_()
        self._follow.start()      # 跟随桌宠移动（拖动时贴住）
        # 注意：思考/等待期间【不】启动自动消失计时——
        # 语音合成可能很慢，三点要保持到真正开始说话/显示文字那一刻
        self._think_timer.start()

    def _think_step(self):
        self._think = (self._think + 1) % 3
        self._think_text = '·' * (self._think + 1)
        self.update()

    def show_text(self, text):
        self._stop_thinking()
        self._type_text = text
        self._type_pos = 0
        self._size_for_full(text)   # 按全文定窗口大小（避免逐字跳动）
        self._reposition()
        self.show()
        self.raise_()
        self._follow.start()        # 跟随桌宠移动（拖动时贴住）
        self.update()
        self._type_timer.start()

    def show_text_synced(self, text, duration_ms):
        """文字与音频同步：按音频实际时长 + 标点停顿权重逐字蹦字。
        duration_ms=音频有效时长(ms)（已去掉首尾静音）。
        时间分配：标点字符权重高（TTS 在标点处停顿），普通字权重低，
        文字在逗号句号处同步"等" → 与语音节奏贴合。0 或异常则回退匀速。"""
        self._stop_thinking()
        self._type_text = text
        self._type_pos = 0
        self._size_for_full(text)
        self._reposition()
        self.show()
        self.raise_()
        self._follow.start()
        self.update()
        n = len(text)
        if n <= 0:
            return
        if duration_ms and duration_ms > 0 and n > 1:
            # 按标点权重分配每字显示时刻
            total_w = 0.0
            for ch in text:
                total_w += _PUNCT_WEIGHT.get(ch, 1.0)
            sched = []
            acc = 0.0
            for ch in text:
                acc += _PUNCT_WEIGHT.get(ch, 1.0)
                sched.append(duration_ms * acc / total_w)
            self._sync_schedule = sched
            self._sync_t0 = time.monotonic()
            # 时间表模式：50ms 轮询查进度（间隔短、贴合度高，且不依赖固定速率）
            self._type_timer.start(50)
        else:
            self._sync_schedule = None
            interval = _TYPE_MS
            self._type_timer.start(interval)

    def _type_step(self):
        if self._sync_schedule is not None:
            # 按时间表推进：当前应显示到第几个字
            elapsed = (time.monotonic() - self._sync_t0) * 1000.0
            sched = self._sync_schedule
            pos = self._type_pos
            while pos < len(sched) and elapsed >= sched[pos]:
                pos += 1
            if pos > self._type_pos:
                self._type_pos = pos
                self.update()
            if self._type_pos >= len(self._type_text):
                self._type_timer.stop()
                self._sync_schedule = None
                self._lift_life()   # 蹦字完成后重新计时自动消失
            return
        self._type_pos += 1
        self.update()
        if self._type_pos >= len(self._type_text):
            self._type_timer.stop()
            self._lift_life()   # 蹦字完成后重新计时自动消失

    # ---------- 尺寸 ----------
    def _size_for_full(self, text):
        """按全文计算窗口尺寸：宽=min(需要宽, MAX)；高按换行行数"""
        fm = QFontMetrics(self._font)
        need = fm.horizontalAdvance(text) + 40
        w = int(min(_BUBBLE_MAX_W, max(_BUBBLE_MIN_W, need)))
        usable = w - 40
        tw = fm.horizontalAdvance(text)
        lines = max(1, -(-tw // max(1, usable)))
        h = lines * fm.height() + 24
        self.resize(w, int(h))

    def _resize_to_text(self, text):
        self._size_for_full(text)

    def _stop_type(self):
        self._type_timer.stop()
        self._sync_schedule = None
        self._type_text = ''
        self._type_pos = 0

    def _stop_thinking(self):
        self._think_timer.stop()
        self._think = 0
        self._think_text = ''

    def _lift_life(self):
        self._life.start()

    # ---------- 绘制：透明背景 + 白字深描边 ----------
    def paintEvent(self, ev):
        text = self._shown()
        if not text:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.setFont(self._font)
        rect = self.rect().adjusted(10, 6, -10, -6)
        # 先画描边（深色粗轮廓，多层加粗 → 白字在任何背景上都清晰显眼）
        pen = QPen(QColor(10, 12, 18, 235), 4)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.drawText(rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
                   | Qt.TextFlag.TextWordWrap, text)
        # 再画白字本体
        p.setPen(QColor(255, 255, 255, 255))
        p.drawText(rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
                   | Qt.TextFlag.TextWordWrap, text)
        p.end()

    def hideEvent(self, ev):
        self._follow.stop()
        self._stop_type()
        self._stop_thinking()
        super().hideEvent(ev)

    def mousePressEvent(self, ev):
        """点气泡 → 关闭"""
        self.hide()
        ev.accept()

    def _reposition(self):
        if self._pet is None:
            return
        try:
            anchor = self._pet.frameGeometry()
            if anchor is None:
                return
        except Exception:
            return
        scr = QApplication.screenAt(anchor.center()) or QApplication.primaryScreen()
        geo = scr.availableGeometry() if scr is not None else None
        # 默认放桌宠【正右方】（垂直方向与桌宠中心对齐）；放不下则放左边
        x = anchor.right() + 14
        if geo is not None and x + self.width() > geo.right():
            x = anchor.left() - 14 - self.width()
        y = anchor.center().y() - self.height() // 2
        if geo is not None:
            if y + self.height() > geo.bottom():
                y = geo.bottom() - self.height()
            y = max(y, geo.top())
            x = max(geo.left(), min(x, geo.right() - self.width()))
        self.move(x, y)


class DelayWidget(QWidget):
    """每轮对话结束后显示在【桌宠正下方】的两行小字：
    第一行：本次费用 $金额；第二行：LLM x.xx s · TTS x.xx s。
    显示数秒自动消失；跟随桌宠移动；点击可立即关闭。
    注意：用 QLabel 内嵌文本实现（自绘 paintEvent 在连续刷新时触发
    Qt6Core 0xc0000409 崩溃），避免 QPainter 自绘。"""

    def __init__(self, pet):
        super().__init__(None,
                         Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool)
        self._pet = pet
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setStyleSheet('background:rgba(18,21,30,215); border-radius:8px;')
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(12, 6, 12, 6)
        self._lay.setSpacing(1)
        self._lbl1 = QLabel('')
        self._lbl1.setStyleSheet('color:#f0f2f8; background:transparent; font-size:12px;')
        self._lbl2 = QLabel('')
        self._lbl2.setStyleSheet('color:#8fc7ff; background:transparent; font-size:11px;')
        self._lay.addWidget(self._lbl1)
        self._lay.addWidget(self._lbl2)
        self._life = QTimer(self)
        self._life.setSingleShot(True)
        self._life.setInterval(5000)
        self._life.timeout.connect(self.hide)
        self._follow = QTimer(self)
        self._follow.setInterval(16)
        self._follow.timeout.connect(self._reposition)

    def show_delay(self, price_text, llm_s=None, tts_s=None):
        """显示延迟/价格两行小字。llm_s/tts_s 单位秒（None 则不显示该行）。"""
        line2 = []
        if llm_s is not None:
            line2.append('LLM %.2fs' % llm_s)
        if tts_s is not None:
            line2.append('TTS %.2fs' % tts_s)
        l1 = (price_text or '').strip()
        l2 = '  ·  '.join(line2) if line2 else ''
        if not l1 and not l2:
            return
        self._lbl1.setText(l1)
        self._lbl1.setVisible(bool(l1))
        self._lbl2.setText(l2)
        self._lbl2.setVisible(bool(l2))
        self.adjustSize()
        self._reposition()
        self.show()
        self.raise_()
        self._follow.start()
        self._life.start()

    def _reposition(self):
        if self._pet is None:
            return
        try:
            anchor = self._pet.frameGeometry()
            scr = QApplication.screenAt(anchor.center()) or QApplication.primaryScreen()
            geo = scr.availableGeometry() if scr else None
            x = anchor.center().x() - self.width() // 2
            y = anchor.bottom() + 6
            if geo is not None:
                x = max(geo.left(), min(x, geo.right() - self.width()))
                if y + self.height() > geo.bottom():
                    y = anchor.top() - self.height() - 6
            self.move(int(x), int(y))
        except Exception:
            pass

    def mousePressEvent(self, e):
        self.hide()
        e.accept()

class CloseXButton(QPushButton):
    """自绘 ✕ 关闭按钮：用 QPainter 画两条交叉线，任何系统字体都清晰
    （不依赖字体里有没有 ✕ 字形——部分中文字体缺它导致只显示一个点）"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(24, 24)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("关闭")
        self._hover = False

    def enterEvent(self, e):
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self.update()
        super().leaveEvent(e)

    def paintEvent(self, e):
        from PyQt6.QtGui import QPainter as _P
        p = _P(self)
        p.setRenderHint(_P.RenderHint.Antialiasing)
        # 圆底：hover 变红提示
        if self._hover:
            p.setBrush(QColor(220, 70, 70, 230))
        else:
            p.setBrush(QColor(200, 60, 60, 190))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(self.rect(), 6, 6)
        # 画两条交叉线（白、粗、圆头）→ 任何系统都清晰可见
        pad = 7
        pen = QPen(QColor(255, 255, 255, 245), 2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawLine(pad, pad, self.width() - pad, self.height() - pad)
        p.drawLine(self.width() - pad, pad, pad, self.height() - pad)
        p.end()


# ============================================================================
# 完整对话上下文窗口（点「聊天记录」弹出：列出当前会话全部消息）
# ============================================================================
# ============================================================================
# 消息 → 富文本气泡 HTML（完整记录窗与可视化聊天窗共用同一渲染）
# 用户消息右对齐(右上角)、AI 消息左对齐(左下角)、系统消息置顶居中
# ============================================================================
def _msg_html(messages, system_prompt='', pet=None, style='bubble'):
    """把消息列表渲染成 HTML。
    messages: [{'role','content','ts'}, ...]（不含 system）；
    system_prompt: 若有，以灰色斜体小块置顶；
    pet: 用于取 AI 角色名（缺省 'AI'）；
    style:
      'bubble'      = 带深色气泡块（完整记录窗用）：用户右对齐青绿块、AI 左对齐深灰块
      'plain-right' = 无背景、文字靠右、清晰（聊天窗消息流用）"""
    esc = html.escape
    parts = []
    # 配色
    SYS_COLOR = "#8a93b0"
    SUB = "#7d87a6"
    TIME = "#6f7898"
    TITLE = "#e7eaf4"
    PANEL = "#1f2430"
    USER_BG = "#1e3a5f"
    USER_BORDER = "#3b6ea5"
    AI_BG = "#2a2e3d"
    AI_BORDER = "#46506b"

    # 不显示系统提示词：任何界面都不再把 system_prompt 渲染出来（用户要求简洁）
    if system_prompt:
        pass

    if not messages:
        parts.append(
            '<div style="color:%s; text-align:center; padding:20px;">'
            '暂无对话内容——去和桌宠聊几句吧 ✨</div>' % SUB)

    ai_name = 'AI'
    if pet is not None:
        try:
            n = getattr(pet, 'role', None) or 'AI'
            if n:
                ai_name = n
        except Exception:
            pass

    for m in messages:
        role = m.get('role')
        content = (m.get('content') or '').rstrip()
        ts = m.get('ts') or '—'
        # 系统操作消息（清理上下文等回显）→ 居中灰字
        if role == 'user' and _is_cmd_msg(content):
            parts.append(
                '<div style="text-align:center; color:%s; font-size:11px;'
                ' margin:3px 0;">⚙ %s · %s</div>'
                % (SYS_COLOR, esc(content), ts))
            continue
        if style == 'plain-right':
            # 无背景、靠右、清晰文字（聊天窗消息流）
            who = '你' if role == 'user' else ai_name
            col = '#ffd98a' if role == 'user' else '#bfffd9'
            name_col = '#9aa7c7' if role == 'user' else '#7fd8a8'
            parts.append(
                '<div style="text-align:right; margin:2px 4px;">'
                '<span style="color:%s; font-size:10px;">%s</span>'
                ' <span style="color:%s; font-size:9px;">· %s</span><br>'
                '<span style="color:%s; font-size:14px;">%s</span>'
                '</div>'
                % (name_col, esc(who), TIME, ts, col, content.replace('\n', '<br>')))
            continue
        # ---- bubble 样式 ----
        if role == 'user':
            # 用户消息：右对齐、青绿块；系统操作（清理等）则居中灰字
            parts.append(
                '<div style="text-align:right; margin:3px 2px;">'
                '<span style="background:%s; border:1px solid %s;'
                ' border-radius:10px; padding:6px 10px; color:#dcecff;'
                ' display:inline-block; max-width:72%%; text-align:left;">'
                '<span style="color:%s; font-size:10px;">%s</span><br>%s'
                '</span><br><span style="color:%s; font-size:9px;">%s · %s</span>'
                '</div>'
                % (USER_BG, USER_BORDER, SUB, esc('你'),
                   content.replace('\n', '<br>'),
                   TIME, esc('你'), ts))
        else:
            # AI / assistant 消息：左对齐、白块
            parts.append(
                '<div style="text-align:left; margin:3px 2px;">'
                '<span style="background:%s; border:1px solid %s;'
                ' border-radius:10px; padding:6px 10px; color:%s;'
                ' display:inline-block; max-width:72%%; text-align:left;">'
                '<span style="color:%s; font-size:10px;">%s</span><br>%s'
                '</span><br><span style="color:%s; font-size:9px;">%s · %s</span>'
                '</div>'
                % (AI_BG, AI_BORDER, TITLE, SUB, esc(ai_name),
                   content.replace('\n', '<br>'),
                   TIME, ai_name, ts))
    return '<html><body style="font-family:Segoe UI,Microsoft YaHei;' \
        ' padding:6px;">%s</body></html>' % ''.join(parts)


def _is_cmd_msg(content):
    """判断消息是否为「系统操作」回显（清理上下文等）"""
    c = (content or '').strip()
    return c in ('clear_context', '清理上下文', '清空上下文') or \
        c.startswith('已清理上下文') or c.startswith('已清空上下文')


class ChatHistoryWindow(QWidget):
    """精致深色窗口，用富文本气泡列出完整对话上下文。
    用户消息右对齐(青绿)、AI 消息左对齐(白)、系统提示灰色斜体置顶；
    每条带时间戳；支持滚动 / 复制全文 / 拖动 / Esc 关闭。"""

    # 配色
    _BG = "#171a23"
    _PANEL = "#1f2430"
    _USER_BG = "#1e3a5f"
    _USER_BORDER = "#3b6ea5"
    _AI_BG = "#2a2e3d"
    _AI_BORDER = "#46506b"
    _SYS_COLOR = "#8a93b0"
    _TITLE = "#e7eaf4"
    _SUB = "#7d87a6"
    _TIME = "#6f7898"

    clearRequested = pyqtSignal()   # 历史窗「清理上下文」按钮 → 清空当前角色上下文

    def __init__(self, pet):
        super().__init__(None, Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool)
        self._pet = pet
        self.setWindowTitle("完整对话")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._drag_offset = None
        self._user_dragged = False    # 用户手动拖动 → 暂停跟随
        self._follow = QTimer(self)   # 跟随桌宠移动
        self._follow.setInterval(16)
        self._follow.timeout.connect(self._follow_pet)
        self._resume_timer = QTimer(self)   # 拖后自动恢复跟随
        self._resume_timer.setSingleShot(True)
        self._resume_timer.setInterval(1500)
        self._resume_timer.timeout.connect(self._resume_follow)
        self.setStyleSheet("ChatHistoryWindow{background:%s; }"
                           % self._BG)
        self._build_ui()

    # ---------- 跟随桌宠 ----------
    def _follow_pet(self):
        if self._user_dragged or self._pet is None:
            return
        try:
            pet_rect = self._pet.frameGeometry()
        except Exception:
            return
        if pet_rect is None:
            return
        off = getattr(self, '_follow_offset', None)
        if off is None:
            off = self.pos() - pet_rect.topLeft()
            self._follow_offset = off
        nx = pet_rect.left() + off.x()
        ny = pet_rect.top() + off.y()
        try:
            scr = QApplication.screenAt(pet_rect.center()) or QApplication.primaryScreen()
            if scr is not None:
                geo = scr.availableGeometry()
                nx = max(geo.left(), min(nx, geo.right() - self.width()))
                ny = max(geo.top(), min(ny, geo.bottom() - self.height()))
        except Exception:
            pass
        self.move(nx, ny)

    def _resume_follow(self):
        """拖动松开 1.5s 后若未再次拖动 → 恢复跟随并重算偏移"""
        self._user_dragged = False
        self._follow_offset = None
        try:
            pet_rect = self._pet.frameGeometry()
        except Exception:
            return
        if pet_rect is not None:
            self._follow_offset = self.pos() - pet_rect.topLeft()

    def _start_follow(self, initial_pos=None):
        """开始跟随。initial_pos 为 None 时用当前窗口位置立即锚定相对偏移，
        之后桌宠移动窗口按相对偏移平移（避免首 tick 才锚导致第一跳）。"""
        self._user_dragged = False
        if initial_pos is not None:
            self._follow_offset = initial_pos
        else:
            try:
                pet_rect = self._pet.frameGeometry()
                if pet_rect is not None:
                    self._follow_offset = self.pos() - pet_rect.topLeft()
                else:
                    self._follow_offset = None
            except Exception:
                self._follow_offset = None
        self._follow.start()

    def stop_follow(self):
        try:
            self._follow.stop()
        except Exception:
            pass

    # ---------- UI ----------
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(6)

        # 顶部标题栏
        head = QHBoxLayout()
        head.setSpacing(8)
        self.lbl_title = QLabel("💬 完整对话")
        self.lbl_title.setStyleSheet(
            "color:%s; font-size:15px; font-weight:bold;" % self._TITLE)
        head.addWidget(self.lbl_title)
        self.lbl_count = QLabel("")
        self.lbl_count.setStyleSheet(
            "color:%s; font-size:11px; background:%s; border-radius:8px;"
            " padding:2px 8px;" % (self._SUB, self._PANEL))
        head.addWidget(self.lbl_count)
        head.addStretch(1)
        self.btn_clear_ctx = QPushButton("🧹 清理上下文")
        self.btn_clear_ctx.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_clear_ctx.setStyleSheet(
            "QPushButton{background:#4a3238; border:1px solid #8a4a55; border-radius:7px;"
            " color:#ffd9d9; font-size:12px; padding:4px 10px;}"
            "QPushButton:hover{background:#6a4248;}")
        self.btn_clear_ctx.clicked.connect(self._clear_ctx_clicked)
        head.addWidget(self.btn_clear_ctx)
        self.btn_copy = QPushButton("复制全文")
        self.btn_copy.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_copy.setStyleSheet(
            "QPushButton{background:%s; border:none; border-radius:7px;"
            " color:%s; font-size:12px; padding:4px 10px;}"
            "QPushButton:hover{background:#3a4257;}"
            "QPushButton:pressed{background:#2e3444;}"
            % (self._PANEL, self._SUB))
        self.btn_copy.clicked.connect(self._copy_all)
        head.addWidget(self.btn_copy)
        self.btn_x = CloseXButton(self)
        head.addWidget(self.btn_x)
        self.btn_x.clicked.connect(self.hide)
        root.addLayout(head)

        # 主体：富文本记录区
        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(False)
        self.browser.setStyleSheet(
            "QTextBrowser{background:%s; border:none; color:%s;"
            " font-size:13px;}" % (self._PANEL, self._TITLE))
        self.browser.setFixedSize(520, 440)
        root.addWidget(self.browser, 1)

        # 底部状态栏
        foot = QHBoxLayout()
        self.lbl_meta = QLabel("")
        self.lbl_meta.setStyleSheet("color:%s; font-size:11px;" % self._SUB)
        foot.addWidget(self.lbl_meta)
        foot.addStretch(1)
        self.lbl_esc = QLabel("Esc 关闭 · 可拖动")
        self.lbl_esc.setStyleSheet("color:%s; font-size:10px;" % self._SUB)
        foot.addWidget(self.lbl_esc)
        root.addLayout(foot)

    # ---------- 供外部调用 ----------
    def show_history(self, messages, system_prompt=''):
        """根据完整消息列表重建并显示窗口。
        messages: [{'role','content','ts'}, ...]（不含 system）"""
        self.browser.setHtml(_msg_html(messages, system_prompt, getattr(self, '_pet', None)))
        total = sum(len(m.get('content') or '') for m in messages)
        self.lbl_count.setText("%d 条" % len(messages))
        self.lbl_meta.setText(
            "用户 %d 条 · AI %d 条 · 共 %d 字"
            % (sum(1 for m in messages if m.get('role') == 'user'),
               sum(1 for m in messages if m.get('role') != 'user'), total))
        self.browser.verticalScrollBar().setValue(
            self.browser.verticalScrollBar().maximum())

    @staticmethod
    def _is_cmd(content):
        """判断该条是否是「系统操作」消息（清理上下文等命令回显）"""
        return _is_cmd_msg(content)

    def _clear_ctx_clicked(self):
        """历史窗「清理上下文」→ 发信号让 manager 清空当前角色上下文"""
        self.clearRequested.emit()

    def _copy_all(self):
        from PyQt6.QtWidgets import QApplication as _A
        _A.clipboard().setText(self.browser.toPlainText())
        self.btn_copy.setText("已复制 ✓")
        QTimer.singleShot(1200,
                          lambda: self.btn_copy.setText("复制全文"))

    # ---------- 窗口拖动（拖动时停跟随，松开 1.5s 后自动恢复） ----------
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = e.globalPosition().toPoint() - \
                self.frameGeometry().topLeft()
            self._user_dragged = True
            try:
                self._follow.stop()
            except Exception:
                pass
            try:
                self._resume_timer.stop()
            except Exception:
                pass
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._drag_offset is not None and e.buttons() & Qt.MouseButton.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag_offset)
            e.accept()
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        was_drag = self._drag_offset is not None
        self._drag_offset = None
        if was_drag and self._user_dragged:
            # 短暂停顿后恢复跟随（除非期间又拖动）
            self._resume_timer.start()
        super().mouseReleaseEvent(e)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.hide()
            e.accept()
            return
        super().keyPressEvent(e)

    def hideEvent(self, ev):
        try:
            self._follow.stop()
        except Exception:
            pass
        try:
            self._resume_timer.stop()
        except Exception:
            pass
        super().hideEvent(ev)


class ChatWindow(QWidget):
    """轻量输入条窗口：只含一行「会话切换 + 新建/删除 + 输入 + 发送」的横线输入条。
    紧贴在桌宠正下方、随桌宠移动。回车发送后输入条自动消失——AI 回复以
    无背景大字气泡显示在桌宠正右方，显示完整后 5 秒自动消失。
    完整对话通过右键菜单「📜 完整对话记录」回看（会话仍各自保留历史）。"""
    sendRequested = pyqtSignal(str)
    clearRequested = pyqtSignal()
    historyRequested = pyqtSignal()
    sessionSwitchRequested = pyqtSignal(str)   # 切换会话（传会话名）
    sessionNewRequested = pyqtSignal()          # 新建会话
    sessionDeleteRequested = pyqtSignal(str)    # 删除会话（传会话名）

    # 窗口尺寸常量：单行横条
    W_USAGE = 640          # 输入条宽度
    H_USAGE = 48           # 条高
    H_NO_USAGE = 48
    _H_BASE = 48

    def __init__(self, pet):
        super().__init__(None, Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool)
        self._pet = pet
        self.setWindowTitle("卡丘简易桌宠 · AI")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._drag_offset = None
        self._user_dragged = False     # 用户手动拖过 → 取消自动跟随
        self._follow = QTimer(self)
        self._follow.setInterval(16)
        self._follow.timeout.connect(self._follow_pet)
        self.setStyleSheet(
            "ChatWindow{background:rgba(24,26,34,235); border-radius:12px;"
            " border:1px solid rgba(255,255,255,70);}")

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 6, 8, 6)
        root.setSpacing(0)

        # 单行：查看上下文 | 输入框 + 发送
        row = QHBoxLayout()
        row.setSpacing(6)
        self.btn_view_ctx = QPushButton("📖 查看上下文", self)
        self.btn_view_ctx.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_view_ctx.setFixedWidth(118)
        self.btn_view_ctx.setStyleSheet(
            "QPushButton{background:#2f3a57; border:1px solid #5a6ea8; border-radius:8px;"
            " color:#cfe0ff; font-size:12px; font-weight:bold; padding:2px 6px;}"
            "QPushButton:hover{background:#3d4d75;}")
        self.btn_view_ctx.clicked.connect(self._open_history)
        row.addWidget(self.btn_view_ctx)
        # 🧹 清理上下文（输入框旁快捷入口）：清空当前角色上下文
        self.btn_clear_input = QPushButton("🧹", self)
        self.btn_clear_input.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_clear_input.setFixedWidth(30)
        self.btn_clear_input.setToolTip("清理当前角色的上下文（重新开始）")
        self.btn_clear_input.setStyleSheet(
            "QPushButton{background:#4a3238; border:1px solid #8a4a55; border-radius:8px;"
            " color:#ffd9d9; font-size:13px; padding:2px 0;}"
            "QPushButton:hover{background:#6a4248;}")
        self.btn_clear_input.clicked.connect(self._clear)
        row.addWidget(self.btn_clear_input)
        # 兼容保留：会话下拉/新建/删除不再显示（角色自动定，查看/清理在历史窗）
        self.combo_session = QComboBox(self)
        self.combo_session.setVisible(False)
        self.combo_session.activated.connect(self._on_session_changed)
        self.btn_new_sess = QPushButton("＋", self)
        self.btn_new_sess.setVisible(False)
        self.btn_new_sess.clicked.connect(self._new_session)
        self.btn_del_sess = QPushButton("🗑", self)
        self.btn_del_sess.setVisible(False)
        self.btn_del_sess.clicked.connect(self._delete_session)
        # 输入框（占满中间）
        self.input = QLineEdit(self)
        self.input.setPlaceholderText("问桌宠…（回车发送，输入条将自动收起）")
        self.input.setStyleSheet(
            "QLineEdit{background:rgba(255,255,255,18); border:none; border-radius:8px;"
            " color:#ffffff; font-size:15px; padding:4px 10px;}"
            "QLineEdit:focus{background:rgba(255,255,255,28);}")
        self.input.returnPressed.connect(self._send)
        row.addWidget(self.input, 1)
        self.btn_send = QPushButton("发送", self)
        self.btn_send.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_send.setStyleSheet(
            "QPushButton{background:#3d6ef7; border:none; border-radius:8px;"
            " color:white; font-size:13px; font-weight:bold; padding:4px 12px;}"
            "QPushButton:hover{background:#5480ff;}"
            "QPushButton:disabled{background:#4a4f63;}")
        self.btn_send.clicked.connect(self._send)
        row.addWidget(self.btn_send)
        root.addLayout(row)

        # 兼容保留（无消息流）：单行条不展示历史
        self.browser = None
        self.btn_clear = None
        self.btn_history = None
        self.lbl_usage = None

        self.setFixedWidth(self.W_USAGE)
        self.setFixedHeight(self.H_USAGE)

    # ---- 会话下拉 ----
    def set_sessions(self, names, current):
        """填充会话下拉列表；names 为全部会话名，current 为当前选中。"""
        try:
            self.combo_session.blockSignals(True)
            self.combo_session.clear()
            self.combo_session.addItems(names)
            if current in names:
                self.combo_session.setCurrentText(current)
            self.combo_session.blockSignals(False)
        except Exception:
            pass

    def _on_session_changed(self, idx):
        name = self.combo_session.currentText()
        if name:
            self.sessionSwitchRequested.emit(name)

    def _new_session(self):
        self.sessionNewRequested.emit()

    def _delete_session(self):
        """删除当前选中的会话（发信号给 manager 处理）"""
        name = self.combo_session.currentText()
        if name:
            self.sessionDeleteRequested.emit(name)

    # ---- 消息流展示 ----
    def set_content(self, messages, system_prompt='', ai_name='AI'):
        """输入条无历史流：历史一律通过「📜 完整对话记录」回看，这里留空。
        保留方法供外部调用（_sync_ui_to_current 等），仅更新会话语义。"""
        return

    # 窗口拖动（按住空白/输入框外区域）——拖动后取消自动跟随
    def mousePressEvent(self, e):
        # 输入条始终跟随桌宠，点击空白只把焦点还给输入框，不取消跟随
        if e.button() == Qt.MouseButton.LeftButton:
            try:
                self.input.setFocus()
            except Exception:
                pass
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)

    def _follow_pet(self):
        """始终把输入条贴在桌宠【正下方】（用户拖动桌宠时输入条同步跟）。
        每 tick 按最新桌宠矩形重新计算位置，不保留拖动偏移。"""
        if self._pet is None:
            return
        try:
            pet_rect = self._pet.frameGeometry()
        except Exception:
            return
        if pet_rect is None:
            return
        scr = QApplication.screenAt(pet_rect.center()) or QApplication.primaryScreen()
        geo = scr.availableGeometry() if scr is not None else None
        x = pet_rect.center().x() - self.width() // 2
        if geo is not None:
            x = max(geo.left(), min(x, geo.right() - self.width()))
        y = pet_rect.bottom() + 6
        if geo is not None and y + self.height() > geo.bottom():
            y = max(geo.top(), pet_rect.top() - self.height() - 6)
        self.move(x, y)

    # ---------- 交互 ----------
    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.hide()
            e.accept()
            return
        super().keyPressEvent(e)

    def _send(self):
        text = self.input.text().strip()
        if not text:
            return
        self.input.clear()
        self.sendRequested.emit(text)
        # 极简交互：发送后横线输入条自动收起，等右侧气泡回复即可
        self.hide()

    def set_busy(self, busy):
        # 思考中时输入框与发送禁用、按钮变灰
        self.input.setEnabled(not busy)
        self.btn_send.setEnabled(not busy)
        self.btn_send.setText("…" if busy else "发送")

    def show_near(self, pet_rect):
        """显示在桌宠【正下方】紧贴底部（水平居中对齐桌宠）。
        下方放不下（靠屏幕底）才改到上方。跟随桌宠移动。"""
        scr = QApplication.screenAt(pet_rect.center()) or QApplication.primaryScreen()
        geo = scr.availableGeometry() if scr is not None else None
        # 水平：窗中心对齐宠中心
        x = pet_rect.center().x() - self.width() // 2
        if geo is not None:
            x = max(geo.left(), min(x, geo.right() - self.width()))
        # 垂直：紧贴桌宠底部
        y = pet_rect.bottom() + 6
        if geo is not None and y + self.height() > geo.bottom():
            # 下方放不下 → 放到桌宠上方
            y = pet_rect.top() - self.height() - 6
            if y < geo.top():
                y = max(geo.top(), geo.bottom() - self.height())
        self._follow_offset = None
        self._user_dragged = False   # 每次重新打开都恢复跟随
        self.move(x, y)
        self._follow.start()

    def hideEvent(self, ev):
        try:
            self._follow.stop()
        except Exception:
            pass
        super().hideEvent(ev)

    def _clear(self):
        """清理上下文按钮（清空当前会话）"""
        self.clearRequested.emit()

    def _open_history(self):
        """查看完整对话按钮"""
        self.historyRequested.emit()

    def set_usage(self, text):
        """输入条不内嵌用量行（用量/金额通过右键菜单统计查看）；空操作兼容。"""
        return


# ============================================================================
# AI 聊天管理器（右键打开聊天窗 + 气泡 + TTS 播放）
# ============================================================================
class AiChatManager(QObject):
    # 后台任务完成信号（跨线程 emit，Qt 自动排队回主线程槽执行）
    models_fetched = pyqtSignal(bool, object)    # (ok, 模型列表 或 错误串)
    tts_api_tested = pyqtSignal(bool, str)       # (ok, 消息)
    conn_tested = pyqtSignal(bool, str)          # (ok, 消息)

    def __init__(self, pet):
        super().__init__()
        self._pet = pet
        self._chat = None
        self._history = None
        self._bubble = None
        self._delay_widget = None    # 桌宠正下方：价格/LLM/TTS 延迟两行小字
        self._hover_hide_timer = None   # 鼠标悬停展开输入条后，离开 1s 再隐藏
        # ---------- 多会话上下文（每角色独立文件持久化） ----------
        # 每个角色一个上下文文件：contexts/role_<角色名>.json
        # 会话只可删除不可新建（角色会话随角色自动存在）；不存在「默认会话」
        self._sessions = {}            # 会话名 -> 消息列表
        self._session_order = []       # 会话名列表（保序）
        self._session_cur = ''         # 当前会话名（角色会话，由 switch_to_role 设置）
        self._load_role_sessions_from_disk()
        self._messages = self._sessions.get(self._session_cur) or []
        self._pending_no_persist = False  # 删除会话时临时禁止写盘
        self._ai_worker = None
        self._tts_worker = None
        self._rewrite_worker = None
        # 运行中 QThread 保活列表：worker 结束前保持引用，防止 Python GC
        # 提前回收运行中的 QThread → Qt 层 0xc0000409 fail-fast（
        # "QThread: Destroyed while thread is still running"）
        self._workers_keepalive = []
        self._pending_tts_seq = 0
        self._seq = 0                 # 递增序号：新 TTS 打断旧 TTS
        self._synced_text = ''        # 待朗读文本（音频就绪后随音频同步蹦字）
        self._last_usage = {}         # 最近一次 token 用量
        self._api_t0 = 0.0            # 本次 API 请求开始（monotonic）
        self._tts_t0 = 0.0            # 本次 TTS 合成开始（monotonic）
        self._last_delay = {}         # {'api': ms, 'tts': ms} 最近一次延迟
        self._player = None
        self._audio_out = None
        self._sfx = None          # ⭐ TTS 播报改用 QSoundEffect（QMediaPlayer 在
                                  #    PyQt6.11/Qt6.11.2 有状态交互即崩的 bug：连槽、
                                  #    播放中读 playbackState 均触发 0xc0000409）
        try:
            self._player = QMediaPlayer()
            self._audio_out = QAudioOutput()
            self._player.setAudioOutput(self._audio_out)
            self._apply_tts_volume()   # 应用已保存的朗读音量
        except Exception:
            self._player = None
            self._audio_out = None
        try:
            from PyQt6.QtMultimedia import QSoundEffect
            self._sfx = QSoundEffect()
            self._sfx.setVolume(min(1.0, max(0.0, self.tts_volume() / 100.0)))
        except Exception:
            self._sfx = None

        # 跨时段自动刷新：高峰↔空闲翻转时，若用量行可见则用新单价重算显示
        self._last_peak = self.is_peak_time()
        self._peak_timer = QTimer(self)
        self._peak_timer.setInterval(60000)   # 每分钟检查一次
        self._peak_timer.timeout.connect(self._on_peak_tick)
        self._peak_timer.start()

    def _on_peak_tick(self):
        """每分钟检查峰谷时段是否翻转；翻转则刷新用量显示"""
        try:
            now_peak = self.is_peak_time()
            if now_peak != self._last_peak:
                self._last_peak = now_peak
                # 时段变了 → 用量按新单价重算
                if self._last_usage:
                    try:
                        self._sync_chat_usage()
                    except Exception:
                        pass
        except Exception:
            pass

    @staticmethod
    def default_system_prompt():
        return ('你是桌宠「卡丘」里的 AI 小伙伴，活泼友善，'
                '回答简洁亲切，用中文。')

    # ------------- 多会话上下文（每角色独立文件持久化，只删不建） -------------
    def _ctx_dir(self):
        """上下文数据目录：<data>/contexts（可写持久）"""
        try:
            if pet_mod is not None:
                d = os.path.join(pet_mod.base_dir(), 'contexts')
                os.makedirs(d, exist_ok=True)
                return d
        except Exception:
            pass
        return None

    def _ctx_file(self, session_name):
        """会话名 → 磁盘文件名（角色会话 role_<角色名>.json）"""
        d = self._ctx_dir()
        if not d:
            return None
        # 「角色:米雪儿」→ role_米雪儿；其它含非法字符的替换
        safe = session_name.replace('角色:', 'role_').replace('\\', '_').replace('/', '_')
        return os.path.join(d, safe + '.json')

    def _save_session_disk(self, session_name):
        """把指定会话写入磁盘（无上下文目录则忽略）"""
        f = self._ctx_file(session_name)
        if not f or not session_name:
            return
        try:
            msgs = self._sessions.get(session_name) or []
            with open(f, 'w', encoding='utf-8') as fh:
                json.dump(msgs, fh, ensure_ascii=False, indent=1)
        except Exception:
            pass

    def _load_role_sessions_from_disk(self):
        """启动/刷新：读 contexts 下全部 role_*.json → _sessions/_session_order"""
        self._sessions = {}
        self._session_order = []
        d = self._ctx_dir()
        if not d:
            return
        try:
            for fn in sorted(os.listdir(d)):
                if not fn.endswith('.json') or not fn.startswith('role_'):
                    continue
                name = '角色:' + fn[len('role_'):-5]
                try:
                    with open(os.path.join(d, fn), encoding='utf-8') as fh:
                        msgs = json.load(fh)
                    if isinstance(msgs, list):
                        self._sessions[name] = msgs
                        self._session_order.append(name)
                except Exception:
                    continue
        except Exception:
            pass

    def _push_session(self, name):
        """确保存在会话（角色会话自动有）；不存在则建空并写盘"""
        if name not in self._sessions:
            self._sessions[name] = []
            self._session_order.append(name)
            self._save_session_disk(name)
        return self._sessions[name]

    def _current_role_ctx_file(self):
        """当前角色会话名对应的磁盘文件路径"""
        return self._ctx_file(self._session_cur) if self._session_cur else None

    # ------------- 世界书（World Info / 酒馆式） -------------
    _world_book = None        # 全局世界书 {entries:{key:{keys,content,constant}}}
    _role_worldbook = None    # 当前角色世界书（缓存）
    _role_wb_role = None      # 已加载的角色名
    _world_loaded = False

    def worldbook_enabled(self):
        """世界书开关（ai.world_book_enabled，默认 True）"""
        try:
            return bool((self.cfg() or {}).get('world_book_enabled', True))
        except Exception:
            return True

    def set_worldbook_enabled(self, on):
        _save_ai_cfg(world_book_enabled=bool(on))

    def _current_role_name(self):
        """当前角色名：优先从当前会话名（角色:XXX）反推，回退 pet.role。"""
        try:
            cur = getattr(self, '_session_cur', '') or ''
            if cur.startswith('角色:'):
                return cur[len('角色:'):]
        except Exception:
            pass
        try:
            role = getattr(self._pet, 'role', '') or ''
            parts = [p for p in str(role).replace('\\', '/').split('/') if p]
            return parts[-2] if len(parts) >= 3 else (parts[-1] if parts else '')
        except Exception:
            return ''

    def _world_assets_root(self):
        if pet_mod is not None:
            try:
                return (pet_mod.assets_dir() if hasattr(pet_mod, 'assets_dir')
                        else os.path.join(pet_mod.base_dir(), 'assets'))
            except Exception:
                pass
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets')

    def _load_world_book(self):
        """加载全局世界书 assets/world_book.json（懒加载，失败静默）。"""
        if AiChatManager._world_loaded:
            return
        AiChatManager._world_loaded = True
        try:
            p = os.path.join(self._world_assets_root(), 'world_book.json')
            if os.path.exists(p):
                with open(p, encoding='utf-8') as f:
                    data = json.load(f)
                AiChatManager._world_book = data or {}
        except Exception:
            AiChatManager._world_book = None

    def _load_role_worldbook(self, role_name=None):
        """加载角色世界书 assets/role_worldbooks/<角色名>.json（缓存按角色）。"""
        role_name = role_name or self._current_role_name()
        if not role_name:
            return None
        if AiChatManager._role_wb_role == role_name and AiChatManager._role_worldbook is not None:
            return AiChatManager._role_worldbook
        try:
            p = os.path.join(self._world_assets_root(), 'role_worldbooks', role_name + '.json')
            if os.path.exists(p):
                with open(p, encoding='utf-8') as f:
                    data = json.load(f) or {}
                AiChatManager._role_worldbook = data
                AiChatManager._role_wb_role = role_name
                return data
        except Exception:
            pass
        return None

    def _world_entries_for(self, text):
        """扫描文本命中世界书关键词 → 返回注入内容列表（[content,...]）。
        注入优先级：当前角色的世界书【全部常驻】+ 全局世界书（常驻+关键词命中）。"""
        self._load_world_book()
        text = text or ''
        hits = []
        # 1) 当前角色世界书：所有条目全部注入（角色专属背景/关系/台词）
        try:
            rwb = self._load_role_worldbook()
            if isinstance(rwb, dict):
                for key, e in (rwb.get('entries') or {}).items():
                    if isinstance(e, dict):
                        content = (e.get('content') or '').strip()
                        if content:
                            hits.append(content)
        except Exception:
            pass
        # 2) 全局世界书：常驻 + 关键词命中
        wb = AiChatManager._world_book or {}
        entries = wb.get('entries') if isinstance(wb, dict) else None
        if entries:
            for key, e in entries.items():
                if not isinstance(e, dict):
                    continue
                const = bool(e.get('constant'))
                content = (e.get('content') or '').strip()
                if not content:
                    continue
                if const:
                    hits.append(content)
                    continue
                keys = e.get('keys') or []
                if any(k and k in text for k in keys):
                    hits.append(content)
        return hits

    def _inject_world_entries(self, msgs, user_text):
        """把命中的世界书条目注入 system 消息末尾（作为世界知识段）。
        msgs[0] 为 system（若不存在则补）。开关关闭则不注入。"""
        try:
            if not self.worldbook_enabled():
                return msgs
            hits = self._world_entries_for(user_text)
            if hits:
                world_block = ('【世界知识】\n' + '\n\n'.join(hits))
                if msgs and msgs[0].get('role') == 'system':
                    msgs[0]['content'] = msgs[0]['content'] + '\n\n' + world_block
                else:
                    msgs.insert(0, {'role': 'system', 'content': world_block})
        except Exception:
            pass
        return msgs

    def session_names(self):
        return list(self._session_order)

    def current_session(self):
        return self._session_cur

    def new_session(self, name=None):
        """⚠ 会话只删不建（用户指定）：角色会话随角色自动存在，不提供手动新建。
        保留兼容：调用返回 (False, 提示)。"""
        return False, '会话不可新建（每个角色有自己独立的上下文）'

    def switch_session(self, name):
        """切换到已有会话（保留各自上下文）"""
        if name not in self._sessions:
            return False
        self._invalidate_pending()
        self._session_cur = name
        self._messages = self._sessions[name]
        self._last_usage = {}
        self._last_delay = {}
        self._sync_ui_to_current()
        return True

    # ------------- 按角色自动分会话 -------------
    def _stop_player_safe(self):
        """安全停止/中断播放器：延后到事件循环执行（脱离当前调用栈），
        避免在信号回调/状态机中途直接 stop 导致 Qt6Core 栈/堆安全失败
        （0xc0000409 / 0xc0000374，播放中切角色/新请求时崩溃）。"""
        try:
            QTimer.singleShot(0, self._do_stop_player)
        except Exception:
            pass

    def _do_stop_player(self):
        try:
            # 优先停 QSoundEffect（现用播放器）；旧的 QMediaPlayer 一并停
            if self._sfx is not None:
                self._sfx.stop()
            if self._player is not None:
                self._player.stop()
        except Exception:
            pass

    def is_speaking(self):
        """AI/TTS 是否正在朗读（QSoundEffect 播放中）。
        供桌宠点按逻辑判断：朗读中点按不播触发音、不打断。"""
        try:
            if self._sfx is not None and self._sfx.isPlaying():
                return True
        except Exception:
            pass
        return False

    def _invalidate_pending(self):
        """软失效在途 AI/TTS 请求（切会话/角色时调用）：
        - _pending_tts_seq 递增 → 旧 TTS 回调（_on_tts_done）被 seq 校验丢弃
        - _synced_text 清空、停播放器 → 旧语音不再继续/蹦字
        - _send_session 置 None → 旧 AI 回复经 _on_ai_done 校验丢弃
        - 结束思考三点
        """
        try:
            self._pending_tts_seq = getattr(self, '_pending_tts_seq', 0) + 1
            self._synced_text = ''
            self._send_session = None
            try:
                self._stop_player_safe()
            except Exception:
                pass
            if self._bubble is not None:
                try:
                    self._bubble._stop_thinking()
                except Exception:
                    pass
        except Exception:
            pass

    def role_session_name(self, role):
        """角色专属会话名：「角色:<角色名>」；role 为空返回默认。
        角色名 = 路径末段（去掉阵营/形象，如 乌尔比诺/米雪儿 → 米雪儿）。"""
        try:
            parts = [p for p in str(role).replace('\\', '/').split('/') if p]
            cname = parts[-2] if len(parts) >= 3 else (parts[-1] if parts else '')
        except Exception:
            cname = ''
        return '角色:' + (cname or str(role))

    def switch_to_role(self, role):
        """切角色时自动切到该角色的独立会话（不存在则建）。
        保证每个角色自己的上下文互不干扰。同时：
        - 清空用量/延迟显示（不残留上个角色）
        - 软失效在途 TTS/AI 请求（_pending_tts_seq 递增 + 停播放器），
          防止上个角色的语音/蹦字/回复继续冒出来。"""
        name = self.role_session_name(role)
        try:
            # 软失效在途请求：递增 seq 让旧 TTS 回调失效；停播放器断旧语音；
            # 旧 AI 回复由 _on_ai_done 的 _send_session 校验丢弃
            self._invalidate_pending()
            self._last_delay = {}
            # 角色世界书缓存失效（切到新角色）
            AiChatManager._role_wb_role = None
            AiChatManager._role_worldbook = None
            if name not in self._sessions:
                self._push_session(name)
            self._session_cur = name
            self._messages = self._sessions[name]
            self._last_usage = {}
            self._sync_ui_to_current()
            _dbg('[ai] switch_to_role -> %s' % name)
        except Exception:
            pass
        return name

    def delete_session(self, name):
        """清空某角色的上下文（消息清空 + 磁盘写空数组）。
        每个角色独立存在——清空后角色会话仍在列表、切回自动从空开始，
        无需也不允许删除该角色自己的会话。返回 (ok, 消息)。"""
        if name not in self._sessions:
            return False, '会话不存在'
        self._invalidate_pending()
        # 内存清空 + 磁盘写空（保留角色会话）
        try:
            self._sessions[name].clear()
        except Exception:
            self._sessions[name] = []
        f = self._ctx_file(name)
        if f:
            try:
                with open(f, 'w', encoding='utf-8') as fh:
                    json.dump([], fh, ensure_ascii=False)
            except Exception:
                pass
        if self._session_cur == name:
            self._last_usage = {}
            self._last_delay = {}
            self._messages = self._sessions[name]
        self._sync_ui_to_current()
        return True, '已清空角色会话：%s' % name

    def _sync_ui_to_current(self):
        """把当前会话刷到聊天窗与历史窗（若开着）"""
        try:
            if self._chat is not None:
                self._chat.set_sessions(self.session_names(), self._session_cur)
                self._chat.set_content(self._messages, self.system_prompt())
                self._chat.set_usage('')
        except Exception:
            pass
        try:
            self._refresh_history_if_open()
        except Exception:
            pass

    def clear_context(self):
        """清理当前会话上下文（开始全新对话；其它会话不受影响）。
        ⚠ 必须就地清空（clear()）当前会话列表、保持 _messages 引用不变——
        用 `= []` 会让 _messages 脱离 _sessions[当前会话]（切走再切回旧消息复活）。"""
        try:
            self._messages.clear()
        except Exception:
            self._messages = []
        self._last_usage = {}
        self._last_delay = {}
        if self._chat is not None:
            try:
                self._chat.set_usage('')
            except Exception:
                pass
            try:
                self._chat.set_content([], self.system_prompt())
            except Exception:
                pass
        # 历史窗实时刷新（清空后同步为空）
        try:
            self._refresh_history_if_open()
        except Exception:
            pass
        try:
            self._show_bubble('已清理当前会话，开始全新对话 ✨')
        except Exception:
            pass

    # ------------- 配置 -------------
    def cfg(self):
        return _ai_cfg()

    def enabled(self):
        return bool(self.cfg().get('enabled', False))

    def tts_enabled(self):
        return bool(self.cfg().get('tts_enabled', True))

    def set_enabled(self, on):
        _save_ai_cfg(enabled=bool(on))

    def set_tts_enabled(self, on):
        _save_ai_cfg(tts_enabled=bool(on))

    def set_tts_mode(self, mode):
        _save_ai_cfg(tts_mode=mode)

    def set_server(self, base_url, api_key, model):
        _save_ai_cfg(base_url=base_url, api_key=api_key, model=model)

    def set_tts_voice(self, voice):
        _save_ai_cfg(tts_voice=voice)

    def set_tts_volume(self, vol):
        """设置朗读音量 0-300。<=100 用 QAudioOutput(0~1)；
        >100 用数字增益放大 wav（播放前对 PCM 乘系数）"""
        vol = max(0, min(300, int(vol)))
        _save_ai_cfg(tts_volume=vol)
        self._apply_tts_volume()

    def tts_volume(self):
        try:
            return max(0, min(300, int(self.cfg().get('tts_volume', 100) or 100)))
        except Exception:
            return 100

    def _apply_tts_volume(self):
        if self._audio_out is None:
            return
        try:
            # QAudioOutput 上限 1.0（100%），>100% 的部分由 wav 数字增益承担
            self._audio_out.setVolume(min(100, self.tts_volume()) / 100.0)
        except Exception:
            pass

    # ------------- 用量与费用 -------------
    # 默认按 deepseek-v4-flash 官网价（每百万 token，美元）：
    #   输入（缓存未命中）0.14 / 输入（缓存命中）0.0028 / 输出 0.28
    # 面板可覆盖（ai_price_in / ai_price_cache / ai_price_out）。
    # DeepSeek 采用峰谷定价：高峰价 = 面板填的价；空闲时段 = 高峰价的一半。
    #   高峰时段（北京时间周一至五）：9:00-12:00、14:00-18:00；其余（含周六日）为空闲。
    @staticmethod
    def is_peak_time(dt=None):
        """判断给定时间（缺省=现在）是否处于 DeepSeek 高峰时段（北京时间）。
        高峰 = 周一至周五 9:00-12:00 或 14:00-18:00（含边界）；周六/日全天空闲。"""
        try:
            import datetime as _dt
            if dt is None:
                # 统一用 UTC+8 计算，不依赖机器时区设置
                now = _dt.datetime.now(_dt.timezone(_dt.timedelta(hours=8)))
            elif dt.tzinfo is None:
                now = dt.replace(tzinfo=_dt.timezone(_dt.timedelta(hours=8)))
            else:
                now = dt
            wd = now.weekday()          # Mon=0..Sun=6
            if wd >= 5:                 # 周六日空闲
                return False
            hm = now.hour * 60 + now.minute
            # 09:00-12:00 (含 12:00 整点前) / 14:00-18:00
            return (9 * 60 <= hm < 12 * 60) or (14 * 60 <= hm < 18 * 60)
        except Exception:
            return True   # 判断失败按高峰（保守用面板原价）

    def peak_pricing_enabled(self):
        """是否启用 DeepSeek 峰谷自动计价。默认开启（ai.peak_pricing 默认 true）。"""
        return bool(self.cfg().get('peak_pricing', True))

    def _peak_factor(self):
        """当前计价系数：高峰=1.0；空闲且启用峰谷=0.5（官方半价）；未启用=1.0"""
        if not self.peak_pricing_enabled():
            return 1.0
        return 0.5 if not self.is_peak_time() else 1.0

    def _peak_tag(self):
        """用量行的时段标注文本（空=高峰/未启用）"""
        if not self.peak_pricing_enabled():
            return ''
        return '' if self.is_peak_time() else '· 空闲半价'

    def input_price(self):
        try:
            base = float(self.cfg().get('ai_price_in', 0.14) or 0.14)
        except Exception:
            base = 0.14
        return base * self._peak_factor()

    def cache_price(self):
        """输入缓存命中单价（$ / 百万 token）。默认 deepseek-v4-flash 缓存命中 0.0028"""
        try:
            base = float(self.cfg().get('ai_price_cache', 0.0028) or 0.0028)
        except Exception:
            base = 0.0028
        return base * self._peak_factor()

    def output_price(self):
        try:
            base = float(self.cfg().get('ai_price_out', 0.28) or 0.28)
        except Exception:
            base = 0.28
        return base * self._peak_factor()

    def raw_prices(self):
        """面板填的原始单价（高峰价），不含峰谷折扣。返回 (in, out, cache)。"""
        try:
            pin = float(self.cfg().get('ai_price_in', 0.14) or 0.14)
        except Exception:
            pin = 0.14
        try:
            pout = float(self.cfg().get('ai_price_out', 0.28) or 0.28)
        except Exception:
            pout = 0.28
        try:
            pc = float(self.cfg().get('ai_price_cache', 0.0028) or 0.0028)
        except Exception:
            pc = 0.0028
        return pin, pout, pc

    @staticmethod
    def suggested_prices(model):
        """按模型名猜测官方单价（进/出/缓存命中，$/M）。识别不出返回 None。
        已收录 DeepSeek V4 系官方价（2026-09 官网）：
          deepseek-v4-flash* → 0.14 / 0.28 / 0.0028（含 fast 版，前缀缓存命中 98% 折扣）
          deepseek-v4-pro    → 0.435 / 0.87 / 0.003625
        deepseek-chat / deepseek-reasoner 用 V3 价（0.14/0.28/0.0028 与 flash 同档）。"""
        m = (model or '').strip().lower()
        if not m:
            return None
        # pro 优先于 flash（避免 "flash" 匹配掉 "pro" 的子串歧义）
        if 'v4-pro' in m or 'deepseek-pro' in m:
            return (0.435, 0.87, 0.003625)
        if 'v4-flash' in m or 'v4_flash' in m or 'flash' in m:
            return (0.14, 0.28, 0.0028)
        if 'deepseek-chat' in m or 'deepseek-reasoner' in m:
            return (0.14, 0.28, 0.0028)
        return None

    def set_prices(self, price_in, price_out, price_cache=None):
        """设置单价（每百万 token，美元），供面板调用。
        price_cache 为输入缓存命中单价；不传则保持现值。"""
        try:
            pin = max(0.0, float(price_in))
        except Exception:
            pin = 0.14
        try:
            pout = max(0.0, float(price_out))
        except Exception:
            pout = 0.28
        if price_cache is None:
            _save_ai_cfg(ai_price_in=pin, ai_price_out=pout)
        else:
            try:
                pc = max(0.0, float(price_cache))
            except Exception:
                pc = 0.0028
            _save_ai_cfg(ai_price_in=pin, ai_price_out=pout, ai_price_cache=pc)

    def calc_cost(self, usage):
        """按用量与单价算美元费用。返回 (cost_usd, 描述str)。
        输入费用拆两档：缓存命中×命中价 + 未命中×未命中价
        （命中 token 从 prompt_tokens 里扣除后计未命中原价）。"""
        usage = usage or {}
        try:
            pin = int(usage.get('prompt_tokens') or 0)
            pout = int(usage.get('completion_tokens') or 0)
            pcache = int(usage.get('prompt_cache_hit_tokens') or 0)
        except Exception:
            pin = pout = pcache = 0
        pcache = min(pcache, pin) if pin else 0
        miss = pin - pcache
        cost = (miss / 1e6) * self.input_price() \
            + (pcache / 1e6) * self.cache_price() \
            + (pout / 1e6) * self.output_price()
        desc = '↑%d [缓存%d] ↓%d' % (pin, pcache, pout)
        return cost, desc

    def _usage_text(self, usage):
        """生成单次用量展示文本：'本次 输入token[缓存x] ↓输出token 共N tok ≈ $金额'"""
        usage = usage or {}
        try:
            pin = int(usage.get('prompt_tokens') or 0)
            pout = int(usage.get('completion_tokens') or 0)
            total = int(usage.get('total_tokens') or (pin + pout))
            pcache = int(usage.get('prompt_cache_hit_tokens') or 0)
        except Exception:
            pin = pout = total = pcache = 0
        pcache = min(pcache, pin) if pin else 0   # 脏数据防护：缓存命中不应超过总输入
        cost, _d = self.calc_cost(usage)
        tag = self._peak_tag()
        if pcache:
            return '本次 输入↑%d[缓存读%d] 输出↓%d 共%d tok ≈ $%.4f%s' % (pin, pcache, pout, total, cost, tag)
        return '本次 输入↑%d 输出↓%d 共%d tok ≈ $%.4f%s' % (pin, pout, total, cost, tag)

    def _sync_chat_usage(self):
        """把上次用量显示到聊天条（打开聊天窗时恢复）"""
        if self._chat is None or not hasattr(self._chat, 'set_usage'):
            return
        if self._last_usage:
            try:
                self._chat.set_usage(
                    self._usage_text(self._last_usage) + self._delay_suffix())
            except Exception:
                pass

    def _delay_suffix(self):
        """延迟后缀文案：'· LLM 1234ms · TTS 567ms'；无数据返回 ''"""
        d = getattr(self, '_last_delay', {}) or {}
        parts = []
        if 'api' in d:
            parts.append('LLM %.0fms' % d['api'])
        if 'tts' in d:
            parts.append('TTS %.0fms' % d['tts'])
        return ' · ' + ' · '.join(parts) if parts else ''

    def _show_delay_widget(self):
        """桌宠正下方显示：本次费用(第一行) + LLM/TTS 延迟(秒,第二行)"""
        try:
            d = getattr(self, '_last_delay', {}) or {}
            if not d and not self._last_usage:
                return
            # 本次费用（有 usage 才算；微美元级用 6 位小数才不显示成 0.0000）
            price = ''
            if self._last_usage:
                cost, _dd = self.calc_cost(self._last_usage)
                price = '$%.6f' % cost
            llm_s = (d.get('api') or 0) / 1000.0 if 'api' in d else None
            tts_s = (d.get('tts') or 0) / 1000.0 if 'tts' in d else None
            if price or llm_s is not None or tts_s is not None:
                if self._delay_widget is None:
                    self._delay_widget = DelayWidget(self._pet)
                self._delay_widget.show_delay(price, llm_s, tts_s)
        except Exception:
            pass

    def _refresh_delay_line(self):
        """TTS 延迟就绪后：刷新聊天条用量行（在用量文案末尾追加延迟）"""
        if self._chat is None or not hasattr(self._chat, 'set_usage'):
            return
        try:
            txt = self._usage_text(self._last_usage) + self._delay_suffix()
            self._chat.set_usage(txt)
        except Exception:
            pass

    def _show_usage(self, usage):
        """AI 回复后：更新用量/金额+延迟到聊天条并累计到会话统计"""
        self._last_usage = usage or {}
        if self._chat is not None and hasattr(self._chat, 'set_usage'):
            try:
                if self._last_usage:
                    self._chat.set_usage(
                        self._usage_text(self._last_usage) + self._delay_suffix())
            except Exception:
                pass
        # 累计到会话统计（积分）
        try:
            self._accumulate_usage(usage)
        except Exception:
            pass
        # 桌宠正下方显示本次费用 + LLM 延迟（TTS 就绪后再补 TTS 行）
        try:
            self._show_delay_widget()
        except Exception:
            pass

    # ------------- 用量统计（积分） -------------
    def _load_stats(self):
        """读取累计用量统计（含最近会话），不存在则空"""
        s = self.cfg().get('stats') or {}
        if not isinstance(s, dict):
            s = {}
        stats = {'in': 0, 'cache': 0, 'out': 0, 'cost': 0.0, 'n': 0}
        stats.update({k: s.get(k, 0) for k in stats})
        try:
            stats['cost'] = float(stats['cost'])
        except Exception:
            stats['cost'] = 0.0
        return stats

    def _save_stats(self, stats):
        _save_ai_cfg(stats=stats)

    def _accumulate_usage(self, usage):
        """把一次用量的 token/金额累加进持久化统计（积分）"""
        usage = usage or {}
        try:
            pin = int(usage.get('prompt_tokens') or 0)
            pcache = int(usage.get('prompt_cache_hit_tokens') or 0)
            pout = int(usage.get('completion_tokens') or 0)
        except Exception:
            pin = pout = pcache = 0
        pcache = min(pcache, pin) if pin else 0
        if not (pin or pout):
            return
        cost, _d = self.calc_cost(usage)
        st = self._load_stats()
        st['in'] += pin
        st['cache'] += pcache
        st['out'] += pout
        st['cost'] += cost
        st['n'] += 1
        self._save_stats(st)

    def stats_text(self):
        """累计用量统计文案（用于右键菜单「用量·积分」展示）"""
        st = self._load_stats()
        total = st['in'] + st['out']
        return ('累计对话 %d 次\n'
                '累计输入 %d tok（其中缓存读取 %d）\n'
                '累计输出 %d tok\n'
                '累计消耗 ≈ $%.4f'
                % (st['n'], st['in'], st['cache'], st['out'], st['cost']))

    def stats_short(self):
        """一行简版：'N次 · 输入X·缓存Y·输出Z tok · $F'（菜单项前缀用）"""
        st = self._load_stats()
        return '%d次 · ↑%d[缓存%d] ↓%d · $%.4f' % (
            st['n'], st['in'], st['cache'], st['out'], st['cost'])

    @staticmethod
    def gain_wav_if_needed(path, volume):
        """音量 >100% 时对 wav PCM 做数字增益，生成同目录 _gain{vol}.wav 返回新路径；
        <=100 原样返回。失败返回原路径。"""
        if volume <= 100 or not HAS_SF:
            return path
        try:
            data, sr = _sf.read(path, dtype='float32')
            gain = volume / 100.0
            data = data * gain
            # 限幅防削波（软限幅）
            data = _np.tanh(data)
            newp = path[:-4] + '_gain%d.wav' % volume if path.lower().endswith('.wav') \
                else path + '_gain%d.wav' % volume
            _sf.write(newp, data, sr, subtype='PCM_16', format='WAV')
            return newp
        except Exception:
            return path

    def set_tts_api(self, base_url, api_key, model, voice='', ref='', ref_text='',
                    instruction=''):
        """配置自定义 TTS API 服务（OpenAI 兼容 /audio/speech）。
        ref/ref_text 用于克隆音色（可选）；instruction 为默认情绪/人设（可选）。"""
        _save_ai_cfg(tts_api_base=base_url, tts_api_key=api_key,
                     tts_api_model=model, tts_api_voice=voice,
                     tts_api_ref=ref, tts_api_ref_text=ref_text,
                     tts_api_instruction=instruction)

    # 口语化规则（无论用户自定义什么系统提示词都会强制追加，
    # 目的是让模型输出适合直接语音朗读的口语，少书面拟声词）
    SPOKEN_RULES = (
        '说话务必口语自然，像朋友发语音那样：短句为主、语气亲和、'
        '少书面语、别列编号清单；'
        '避免“嘻嘻”“嘤嘤”“嘿嘿嘿”这类拗口或易被语音念怪的叠字拟声，'
        '要笑就写顺口的“哈哈”“嘿嘿”；'
        '数字与英文按口语读出（18→十八、GPT→G P T），方便语音朗读。'
    )

    def system_prompt(self):
        """当前系统提示词 = 用户人设 + 口语化规则（统一强制追加）"""
        base = (self.cfg().get('system_prompt') or '').strip() \
            or self.default_system_prompt()
        rules = self.SPOKEN_RULES
        if base and rules in base:
            return base
        return base + ('\n' if base else '') + rules

    def set_system_prompt(self, text):
        _save_ai_cfg(system_prompt=text.strip())

    @staticmethod
    def default_tts_prompt():
        """TTS 系统提示词（朗读前把 AI 回答改写成朗读稿 + 自动补齐语气）。
        依据 Breeze-TTS-2 官方模型卡 + 社区高赞用法（调研见
        _worldbook_drafts/breeze_tts_guide.md）：
        - 官方支持内嵌 vocal events：中文 [笑][叹气][咳嗽][清嗓子]、
          英文 (laugh)(sigh)(cough)(clears throat)——会渲染成真实气声/笑声
        - instruction 写「行为+节奏」而非抽象情绪名（社区高赞：写
          "像哄小孩一样轻声、尾音上扬" 比 "开心" 更不机械）
        - 标点即停顿：模型按逗号/句号/省略号决定停顿时长
        - 数字/英文/多音字注音、长句拆短、口语化
        模型按要求输出两行：
            情绪：<行为式语气描述>（作为 Breeze 的 instruction）
            朗读：<改写后适合朗读的文本>"""
        return (
            '你是一名中文语音播报改写助手，专为本地语音克隆引擎'
            '（breeze-tts-clone，Breeze-TTS-2）准备朗读稿。'
            '先了解引擎特性，才能改得最适合它：'
            '① 文本中可内嵌"情绪事件标记"，引擎会把它们渲染成真实的气声/'
            '笑声/叹气声，而不是念出来：中文用方括号 [笑] [叹气] [咳嗽] [清嗓子]，'
            '英文用圆括号 (laugh) (sigh) (cough) (clears throat)；'
            '② 引擎把标点当停顿谱：逗号短停、句号长停、省略号拖尾、'
            '破折号留白——标点就是节奏；'
            '③ 音色由"参考音频克隆 + 简短说话指引(instruction)"共同决定，'
            '指引写得越具体（语气/节奏/行为），声音越贴戏。'
            '你的任务分两步：'
            '第一步，把正文改写成朗读稿：'
            '1. 只改表达不改意思，保留原意与角色口吻，口语自然不机械、不端腔；'
            '2. 删除一切朗读时会念错或出戏的内容：markdown 符号、列表序号、'
            '星号、下划线、链接、表情符号、括号注释；'
            '3. 难念的书面词换成顺口口语；网络梗、生僻用法换成能听懂的普通说法；'
            '4. 叠字怪音（“嘻嘻”“嘤嘤”“嘿嘿嘿”）改写成自然的“哈哈”“嘿嘿”'
            '或直接删掉，宁可简短也别拗口；'
            '5. 数字按口语读法展开：18→十八、2030年→二零三零年、'
            '12.5→十二块五；'
            '6. 英文/缩写逐字母或按读音读出：AI→A I、GPT→G P T、CEO→C E O；'
            '7. 多音字有歧义处注明读音（如 重(chóng)建），避免引擎读错；'
            '8. 长句拆短，一句只说一件事；用逗号、句号、省略号、破折号布置'
            '停顿与气口，节奏像说话而不像念稿；'
            '9. 语气词适度点缀（呢/吧/啦/嘛/哈）增加人味，但不要堆砌。'
            '第二步，按需嵌入情绪事件标记（体现“会演”）：'
            '- 标记放在句首或关键停顿前，一个自然句最多 1 个，'
            '整篇不超过 2-3 个，宁缺毋滥；'
            '- [笑]=轻笑/无奈/被逗乐；[叹气]=无奈/疲惫/惋惜；'
            '[咳嗽]=尴尬/清场/掩饰；[清嗓子]=郑重开口/犹豫后说话；'
            '- 中文朗读稿统一用中文方括号形式，不要用英文括号；'
            '- 情绪主要靠句子本身（用词、标点、长短）传达，标记只是点睛，'
            '不要全靠标记堆。'
            '最后，判断这段文字朗读时应带的语气与行为，写成一行"情绪"'
            '（它将作为语音引擎的说话指引 instruction）：'
            '- 不要只写情绪名词（开心/难过），要写"行为+节奏+神态"：'
            '如"轻快带笑、语速略快、句尾上挑""温柔放缓、像哄小孩"'
            '"平静冷淡、略带讥诮"；'
            '- 可含 1 个语气标记辅助，整体 15 字以内。'
            '严格按以下两行格式输出，不要输出任何其它内容或解释：\n'
            '情绪：<行为式语气描述，15 字以内>\n'
            '朗读：<改写后的朗读稿>')

    def tts_prompt(self):
        return (self.cfg().get('tts_prompt') or '').strip() \
            or self.default_tts_prompt()

    def set_tts_prompt(self, text):
        _save_ai_cfg(tts_prompt=text.strip())

    def fetch_models(self, base_url, api_key, on_done):
        """后台拉取模型列表。完成后发 models_fetched 信号（跨线程安全），
        面板连接该信号后在其槽里操作 UI。on_done 由面板收到信号后调用。"""
        def _run():
            try:
                ms = _list_models(base_url, api_key)
                self.models_fetched.emit(True, ms)
            except Exception as e:
                self.models_fetched.emit(False, '%s' % e)
        threading.Thread(target=_run, daemon=True).start()

    def test_tts_api(self, base_url, api_key, model, voice, on_done,
                     ref='', ref_text='', instruction=''):
        """后台测试自定义 TTS API 服务：合成一段 → emit 带音频路径 → 面板播放。
        失败 emit 错误。"""
        def _run():
            try:
                base = _tts_dir() or ''
                path = os.path.join(base, 'tts_test_%d.wav' % int(time.time() * 1000))
                _api_speech_synth(base_url, api_key, model,
                                  '语音服务测试成功，你能听到我说话吗？',
                                  voice or 'alloy', path, timeout=30,
                                  ref_audio=ref, ref_text=ref_text,
                                  instruction=instruction)
                self.tts_api_tested.emit(True, path)
            except Exception as e:
                self.tts_api_tested.emit(False, '%s' % e)
        threading.Thread(target=_run, daemon=True).start()

    def play_audio_file(self, path):
        """播放指定音频文件（用于测试语音试听）——用 QSoundEffect（稳定不崩）"""
        if not path or not os.path.exists(path):
            return
        try:
            if self._sfx is not None:
                vol = self.tts_volume()
                self._sfx.stop()
                self._sfx.setSource(QUrl.fromLocalFile(path))
                self._sfx.setVolume(min(1.0, max(0.0, vol / 100.0)))
                self._sfx.play()
            return
        except Exception:
            pass
        # 回退：旧 QMediaPlayer
        if self._player is None:
            return
        try:
            self._stop_player_safe()
            self._player.setSource(QUrl.fromLocalFile(path))
            self._player.play()
        except Exception:
            pass

    # ------------- 聊天窗 -------------
    def open_chat(self, focus=True):
        """显示横线输入条（贴桌宠下方跟随）。focus=True 抢焦点并聚焦输入框
        （右键「✏️ 快速提问」用）；focus=False 静默显示（鼠标悬停展开用），
        不抢焦点、不打断用户在其它窗口的输入。"""
        if self._chat is None:
            self._chat = ChatWindow(self._pet)
            self._chat.sendRequested.connect(self._on_send)
            self._chat.clearRequested.connect(self.clear_context)
            self._chat.historyRequested.connect(self.show_history)
            self._chat.sessionSwitchRequested.connect(self.switch_session)
            self._chat.sessionNewRequested.connect(self._new_session_from_ui)
            self._chat.sessionDeleteRequested.connect(self._delete_session_from_ui)
        # 每次打开都同步会话列表 + 当前消息流到聊天窗
        try:
            self._chat.set_sessions(self.session_names(), self._session_cur)
            self._chat.set_content(self._messages, self.system_prompt())
        except Exception:
            pass
        # 打开时把已保存的用量显示同步上去
        try:
            self._sync_chat_usage()
        except Exception:
            pass
        try:
            self.chat_bar_cancel_hide()
        except Exception:
            pass
        self._chat.show_near(self._pet.frameGeometry())
        self._chat.show()
        self._chat.raise_()
        if focus:
            try:
                self._chat.activateWindow()
            except Exception:
                pass
            try:
                self._chat.input.setFocus()
            except Exception:
                pass

    def _new_session_from_ui(self):
        """聊天窗「＋新建」按钮 → 新建会话并切换"""
        self.new_session()

    def _delete_session_from_ui(self, name):
        """聊天窗「🗑 删除」→ 删除当前会话并切到相邻会话"""
        if not name or name not in self._sessions:
            return
        was = self._session_cur
        ok, msg = self.delete_session(name)
        if ok:
            try:
                if name == was and hasattr(self, '_show_bubble'):
                    self._show_bubble(msg + '（已切到「%s」）' % self._session_cur)
            except Exception:
                pass

    def _history_clear_ctx(self):
        """历史窗点「清理上下文」：清空当前角色上下文，历史窗立即变空"""
        self.clear_context()
        try:
            if self._history is not None:
                self._history.show_history(self._messages, self.system_prompt())
        except Exception:
            pass

    def show_history(self):
        """点「📖 查看上下文」：弹出完整对话上下文窗口并跟随桌宠"""
        if self._history is None:
            self._history = ChatHistoryWindow(self._pet)
            # 历史窗「清理上下文」→ 清空当前角色上下文并刷新历史窗
            self._history.clearRequested.connect(self._history_clear_ctx)
        self._history.show_history(self._messages, self.system_prompt())
        # 显示在桌宠附近：优先放桌宠上方，上方不够放下方，都不够则贴屏顶
        # 定位后记录相对偏移供跟随
        try:
            pr = self._pet.frameGeometry()
            scr = QApplication.screenAt(pr.center()) or QApplication.primaryScreen()
            geo = scr.availableGeometry() if scr is not None else None
            w, h = self._history.width(), self._history.height()
            x = pr.right() - w
            if geo is not None:
                # x：尽量不遮 pet 且不越屏
                x = max(geo.left(), min(x, geo.right() - w))
            # y：优先 pet 上方
            y = pr.top() - h - 6
            if geo is not None:
                if y < geo.top():
                    # 上方放不下 → pet 下方
                    y = pr.bottom() + 10
                    if y + h > geo.bottom():
                        # 下方也放不下 → 贴屏顶（尽量可见）
                        y = geo.top()
                if y + h > geo.bottom():
                    y = max(geo.top(), geo.bottom() - h)
            self._history.move(x, y)
        except Exception:
            pass
        self._history.show()
        self._history.raise_()
        self._history.activateWindow()
        # 跟随桌宠移动
        try:
            self._history._start_follow(initial_pos=None)
        except Exception:
            pass

    def _refresh_history_if_open(self):
        """消息有变化时：若历史窗可见则实时刷新（不用重开）"""
        if self._history is None or not self._history.isVisible():
            return
        try:
            self._history.show_history(self._messages, self.system_prompt())
        except Exception:
            pass

    def _refresh_chat_if_open(self):
        """消息有变化时：若可视化聊天窗可见则实时刷新消息流（不用重开/切会话）"""
        if self._chat is None or not self._chat.isVisible():
            return
        try:
            self._chat.set_content(self._messages, self.system_prompt())
        except Exception:
            pass

    def close_all(self):
        if self._bubble is not None:
            self._bubble.hide()
        if self._chat is not None:
            self._chat.hide()
        if self._history is not None:
            self._history.hide()
        if self._player is not None:
            try:
                self._stop_player_safe()
            except Exception:
                pass

    def pet_moved(self):
        """桌宠拖动/移动时调用：气泡/输入条/历史窗立即重定位（无轮询延迟，一体跟随）"""
        if self._bubble is not None and self._bubble.isVisible():
            try:
                self._bubble._reposition()
            except Exception:
                pass
        if self._chat is not None and self._chat.isVisible() and not getattr(self._chat, '_user_dragged', False):
            try:
                self._chat._follow_pet()
            except Exception:
                pass
        if self._history is not None and self._history.isVisible() \
                and not getattr(self._history, '_user_dragged', False):
            try:
                self._history._follow_pet()
            except Exception:
                pass

    # ------------- 鼠标悬停展开/收起输入条 -------------
    def chat_bar_on_enter(self):
        """鼠标进入桌宠：静默显示输入条（不抢焦点、不打断其它窗口输入）"""
        if self._chat is not None and self._chat.isVisible():
            # 已显示：仅确保贴住桌宠 + 取消延迟隐藏
            try:
                self.chat_bar_cancel_hide()
            except Exception:
                pass
            try:
                self._chat._follow_pet()
            except Exception:
                pass
            return
        if not self.enabled():
            return
        try:
            self.open_chat(focus=False)
        except Exception:
            pass

    def chat_bar_on_leave(self):
        """鼠标离开桌宠：0.5 秒后若仍未回来则隐藏输入条。"""
        try:
            if self._hover_hide_timer is None:
                self._hover_hide_timer = QTimer(self)
                self._hover_hide_timer.setSingleShot(True)
                self._hover_hide_timer.setInterval(500)
                self._hover_hide_timer.timeout.connect(self._do_hide_bar)
        except Exception:
            return
        try:
            if self._chat is None or not self._chat.isVisible():
                return
            self._hover_hide_timer.start()
        except Exception:
            pass

    def chat_bar_cancel_hide(self):
        """鼠标回到桌宠：取消延迟隐藏"""
        try:
            if getattr(self, '_hover_hide_timer', None) is not None:
                self._hover_hide_timer.stop()
        except Exception:
            pass

    def _do_hide_bar(self):
        """1 秒延迟到点：若鼠标仍停留在桌宠或输入条上则再等 1 秒；
        鼠标离开两者后才真正隐藏输入条。"""
        try:
            if self._chat is None or not self._chat.isVisible():
                return
            inside = False
            if self._pet is not None:
                try:
                    from PyQt6.QtGui import QCursor
                    gp = QCursor.pos()
                    if self._pet.geometry().contains(gp):
                        inside = True
                    elif self._chat.geometry().contains(gp):
                        inside = True
                except Exception:
                    pass
            if inside:
                # 鼠标还在桌宠/输入条上：再轮询一次，避免“离开输入条后残留”
                try:
                    if self._hover_hide_timer is not None:
                        self._hover_hide_timer.start()
                except Exception:
                    pass
                return
            self._chat.hide()
        except Exception:
            try:
                if self._chat is not None:
                    self._chat.hide()
            except Exception:
                pass

    # ------------- 发送 / 回复 -------------
    def _on_send(self, text):
        cfg = self.cfg()
        base_url = cfg.get('base_url') or DEFAULT_BASE_URL
        api_key = cfg.get('api_key') or ''
        model = cfg.get('model') or DEFAULT_MODEL
        if not api_key:
            self._bubble_msg('还没有填 API 密钥：右键桌宠 → 设置 → AI 功能 里填写。')
            return
        if self._ai_worker is not None and self._ai_worker.isRunning():
            return
        if self._chat is not None:
            self._chat.set_busy(True)
            # 发送时清掉上一次用量显示（新请求的用量回来前保持干净）
            self._chat.set_usage('')
        self._last_usage = {}
        # 记录本次 API 请求起点（用于结束时的延迟显示）
        self._api_t0 = time.monotonic()
        self._last_delay = {}
        # 绑定发送时的会话：回复回来若会话已被切走则丢弃（防串台）
        self._send_session = self._session_cur
        # 思考指示：AI 思考中在桌宠旁显示三点跳动
        self._show_thinking()
        # 多轮上下文：system（可自定义）+ 最近 20 条
        msgs = [{'role': 'system', 'content': self.system_prompt()}]
        # 发送给 API 的消息只保留 role/content（服务商对多余字段可能报错）
        for m in self._messages[-20:]:
            msgs.append({'role': m.get('role'), 'content': m.get('content')})
        msgs.append({'role': 'user', 'content': text})
        # 世界书注入：命中关键词的角色剧情/world 知识段补进 system（酒馆 World Info 式）
        try:
            self._inject_world_entries(msgs, text)
        except Exception:
            pass
        # 本地完整上下文：带时间戳（供「完整对话」窗口展示）
        self._messages.append({'role': 'user', 'content': text,
                               'ts': time.strftime('%H:%M:%S')})
        # 持久化到该角色上下文文件
        try:
            self._save_session_disk(self._session_cur)
        except Exception:
            pass
        # 实时刷新历史窗与可视化聊天窗（若开着：立刻能看到自己刚发的消息）
        try:
            self._refresh_history_if_open()
        except Exception:
            pass
        try:
            self._refresh_chat_if_open()
        except Exception:
            pass
        self._ai_worker = AIWorker(base_url, api_key, model, msgs, self)
        self._ai_worker.done.connect(self._on_ai_done)
        self._ai_worker.finished.connect(self._ai_worker.deleteLater)
        self._keep_worker(self._ai_worker)
        self._ai_worker.start()

    def _keep_worker(self, w):
        """保活运行中的 QThread：加入列表持有引用，finished 后移除。
        防止旧 worker 被新 worker 覆盖引用后，Python GC 提前回收仍
        在运行的 QThread → Qt 层 0xc0000409（QThread: Destroyed while
        thread is still running）。所有后台 worker 统一走这里。"""
        self._workers_keepalive.append(w)

        def _release():
            try:
                if w in self._workers_keepalive:
                    self._workers_keepalive.remove(w)
            except Exception:
                pass

        w.finished.connect(_release)

    # ------------- 气泡 / 思考 -------------
    def _get_bubble(self):
        if self._bubble is None:
            self._bubble = BubbleWidget(self._pet)
        return self._bubble

    def _bubble_msg(self, text):
        """错误/提示信息：整段直接显示在透明气泡（不走逐字）"""
        b = self._get_bubble()
        b._stop_type()
        b._stop_thinking()
        b._type_text = text
        b._type_pos = len(text)
        b._size_for_full(text)
        b._reposition()
        b.show()
        b.raise_()
        b._follow.start()
        b.update()
        b._lift_life()

    def _show_thinking(self):
        self._get_bubble().show_thinking()

    def _hide_thinking(self):
        if self._bubble is not None:
            self._bubble._stop_thinking()

    def _show_bubble(self, text):
        """AI 回复 → 逐字蹦字显示在桌宠旁"""
        self._get_bubble().show_text(text)

    def _on_ai_done(self, reply, err, usage=None):
        if self._chat is not None:
            self._chat.set_busy(False)
        self._ai_worker = None
        # 防止串台：发送后若会话被切走（切角色/切会话），本次回复丢弃
        # （回到原会话时自然看不到这条回复，符合"每条回复属于它发出时的会话"）
        if getattr(self, '_send_session', None) is not None \
                and self._send_session != self._session_cur:
            self._send_session = None
            self._hide_thinking()
            return
        if err:
            # 出错：结束等待，改为显示错误提示
            self._hide_thinking()
            self._bubble_msg('AI 请求失败：%s\n（检查 设置→AI 的服务器/密钥/模型）' % err)
            return
        usage = usage or {}
        # API 延迟（从发送到回复返回）
        try:
            api_ms = (time.monotonic() - self._api_t0) * 1000.0
            self._last_delay['api'] = api_ms
        except Exception:
            pass
        # 单次用量：显示在桌宠旁的状态条
        try:
            self._show_usage(usage)
        except Exception:
            pass
        self._messages.append({'role': 'assistant', 'content': reply,
                               'ts': time.strftime('%H:%M:%S')})
        # 持久化到该角色上下文文件
        try:
            self._save_session_disk(self._session_cur)
        except Exception:
            pass
        # 实时刷新历史窗与可视化聊天窗（若开着：自动补上 AI 新回复，无需重开）
        try:
            self._refresh_history_if_open()
        except Exception:
            pass
        try:
            self._refresh_chat_if_open()
        except Exception:
            pass
        # TTS 依附 AI：若朗读开，则气泡文字等音频就绪后随音频同步蹦字（同始同终）
        if self.tts_enabled() and self.enabled():
            self._seq += 1
            self._pending_tts_seq = self._seq
            try:
                self._stop_player_safe()
            except Exception:
                pass
            # 三点【保持连续】：AI 请求→朗读改写→音频合成整条等待期不中断，
            # 直到音频真正开始播放才结束（见 _on_tts_done）
            if self._bubble is not None and not self._bubble._think_timer.isActive():
                self._show_thinking()
            self._rewrite_for_tts(reply, self._seq)
        else:
            # 不朗读 → 结束等待，立即逐字蹦字显示
            self._hide_thinking()
            self._show_bubble(reply)
            if self.tts_enabled() and not self.enabled():
                # AI 对话被关但 tts_enabled 仍开（历史配置）→ 不朗读
                self.set_tts_enabled(False)

    # ------------- TTS（朗读 AI 回复，情绪自动补齐） -------------
    @staticmethod
    def parse_tts_output(text):
        """解析 TTS 改写输出「情绪：…\n朗读：…」→ (朗读稿, 情绪instruction)。
        格式不符时回退：整段当朗读稿、情绪留空（由引擎默认）。"""
        if not text:
            return '', ''
        emo = ''
        speak = text.strip()
        for line in speak.splitlines():
            line = line.strip()
            if not line:
                continue
            low = line
            for pref in ('情绪', '情感', '语气'):
                if low.startswith(pref + '：') or low.startswith(pref + ':'):
                    emo = (line.split('：', 1)[-1] if '：' in line
                           else line.split(':', 1)[-1]).strip()
                    speak = speak.replace(line, '', 1)
                    break
            else:
                continue
            break   # 只认第一个情绪行
        # 去掉可能的 朗读： 前缀
        for pref in ('朗读', '朗读稿', '语音'):
            for sep in ('：', ':'):
                if speak.lstrip().startswith(pref + sep):
                    speak = speak.split(sep, 1)[-1].strip()
                    break
        # 去掉残留标记（模型多输出的解释）
        for junk in ('情绪：', '情绪:', '朗读：', '朗读:'):
            speak = speak.replace(junk, '')
        speak = speak.strip()
        # 情绪规范化：给引擎可用的中文短语
        emo = emo.strip().strip('。，,!！').strip()
        if emo and len(emo) <= 30:
            return speak, emo
        return speak, ''

    def _rewrite_for_tts(self, reply, seq):
        """用 TTS 系统提示词让 AI 把回答改写成朗读稿并判断情绪。"""
        cfg = self.cfg()
        base_url = cfg.get('base_url') or DEFAULT_BASE_URL
        api_key = cfg.get('api_key') or ''
        model = cfg.get('model') or DEFAULT_MODEL
        if not api_key:
            return
        msgs = [{'role': 'system', 'content': self.tts_prompt()},
                {'role': 'user', 'content': reply}]
        w = AIWorker(base_url, api_key, model, msgs, self)
        self._rewrite_worker = w
        w.done.connect(lambda txt, e, u, s=seq: self._on_rewrite_done(txt, e, s, reply))
        w.finished.connect(w.deleteLater)
        self._keep_worker(w)
        w.start()

    def _on_rewrite_done(self, text, err, seq, original):
        if seq != getattr(self, '_pending_tts_seq', 0) or not self.tts_enabled():
            return   # 期间有更新回复/关闭朗读 → 丢弃
        self._rewrite_worker = None
        speak = ''
        emo = ''
        if text and text.strip() and not err:
            speak, emo = self.parse_tts_output(text)
        if not speak:                      # 改写失败 → 直接朗读原文
            speak = original
        if not speak:
            return
        self._speak_text(speak, seq, emo)

    def _speak_text(self, text, seq, instruction=''):
        if self._player is None:
            # 无播放器（多媒体初始化失败）→ 不能朗读，回退直接蹦字，避免永远等
            if seq == getattr(self, '_pending_tts_seq', 0):
                self._hide_thinking()
                if text:
                    self._show_bubble(text)
            return
        if seq != getattr(self, '_pending_tts_seq', 0):
            return
        cfg = self.cfg()
        voice = (cfg.get('tts_api_voice') or cfg.get('tts_voice') or 'alloy')
        # 记录将朗读的文本 → 音频就绪时按音频时长同步蹦字
        self._synced_text = text
        # 记录 TTS 合成起点（结束算延迟）
        self._tts_t0 = time.monotonic()
        self._tts_worker = TTSWorker(text, voice, seq, self, instruction=instruction)
        self._tts_worker.done.connect(
            lambda path, err, s=seq: self._on_tts_done(path, err, s))
        self._tts_worker.finished.connect(self._tts_worker.deleteLater)
        self._keep_worker(self._tts_worker)
        self._tts_worker.start()

    def _on_tts_done(self, path, err, seq):
        if seq != getattr(self, '_pending_tts_seq', 0):
            return   # 已有更新的朗读，丢弃旧合成
        if not path:
            self._bubble_msg('朗读失败：%s' % err)
            return
        # TTS 合成延迟（就绪时刻 - 开始时刻）
        try:
            tts_ms = (time.monotonic() - self._tts_t0) * 1000.0
            self._last_delay['tts'] = tts_ms
            self._refresh_delay_line()
            self._show_delay_widget()   # 补 TTS 行刷新桌宠正下方小字
        except Exception:
            pass
        vol = self.tts_volume()
        # 音量 >100% → 数字增益（QAudioOutput 上限 1.0）
        gain_path = path
        if vol > 100:
            gain_path = self.gain_wav_if_needed(path, vol)
        # 音频时长（同步蹦字用；失败回退默认间隔）
        dur_ms = self._wav_duration_ms(gain_path)
        # 有效语音区间：去掉首尾静音 → (实际出声起点, 有效时长)。
        # 用有效时长蹦字（首尾静音不该算进朗读节奏），并在"实际出声点"才开始蹦
        start_ms, active_ms = self._wav_active_range_ms(gain_path)
        if active_ms <= 0:
            active_ms = dur_ms
        pending_text = (getattr(self, '_synced_text', '') or '').strip()
        self._synced_text = ''
        # 先把音频接上、启动播放（音频真正出声的起点）
        # ⭐ 用 QSoundEffect 播放（PyQt6.11/Qt6.11.2 的 QMediaPlayer 有
        # 「状态交互即崩」bug：连槽/播放中读状态都触发 0xc0000409；QSoundEffect
        # 实测稳定、可安全读 isPlaying、自然播完不崩，且无延后 stop 竞态 → 有声音）。
        sfx = self._sfx
        if sfx is None:
            # 无 QSoundEffect（初始化失败）→ 回退旧 QMediaPlayer 直播（同步 stop）
            try:
                if self._player is not None:
                    self._player.stop()
                self._player.setSource(QUrl.fromLocalFile(gain_path))
                self._player.play()
            except Exception:
                pass
        else:
            try:
                sfx.stop()                    # 同步停旧（无延后竞态）
                sfx.setSource(QUrl.fromLocalFile(gain_path))
                sfx.setVolume(min(1.0, max(0.0, vol / 100.0)))
                sfx.play()
            except Exception:
                pass
        # 蹦字：播放启动后等"实际出声点"再蹦（首静音跳过；QSoundEffect 起播快，
        # start_ms 已含首静音，再加 100ms 保险）
        if pending_text:
            def _reveal():
                if seq != getattr(self, '_pending_tts_seq', 0):
                    return
                if self._bubble is not None:
                    self._bubble._stop_thinking()
                try:
                    self._get_bubble().show_text_synced(pending_text, active_ms)
                except Exception:
                    self._hide_thinking()
            QTimer.singleShot(max(60, 100 + int(start_ms)), _reveal)
        else:
            QTimer.singleShot(80, self._hide_thinking)
        cleaned = {'done': False}

        def _cleanup_now():
            if cleaned['done']:
                return
            cleaned['done'] = True
            try:
                if os.path.exists(path):
                    os.remove(path)
                if gain_path != path and os.path.exists(gain_path):
                    os.remove(gain_path)
            except Exception:
                pass

        # 音频播完（时长 + 余量）后清理临时文件；QSoundEffect 自然结束安全，无需提前 stop
        clean_delay = (dur_ms + 400) if (dur_ms and dur_ms > 0) else 15000
        QTimer.singleShot(max(800, clean_delay), _cleanup_now)
        # 极长兜底：5 分钟强制清理
        QTimer.singleShot(300000, _cleanup_now)

    def _wav_duration_ms(self, path):
        """读取 wav 时长(ms)；失败返回 0"""
        if not path or not os.path.exists(path):
            return 0
        try:
            if HAS_SF:
                with _sf.SoundFile(path) as f:
                    return int(f.frames / f.samplerate * 1000)
            import wave
            with wave.open(path, 'rb') as w:
                return int(w.getnframes() / w.getframerate() * 1000)
        except Exception:
            return 0

    def _wav_active_range_ms(self, path):
        """检测 wav 有效语音区间（去掉首尾静音）。
        返回 (start_ms, active_ms)：实际出声起点 + 有效时长。
        无 soundfile/numpy 或全静音/异常时回退 (0, 全时长)。"""
        if not path or not os.path.exists(path):
            return (0, 0)
        try:
            if not HAS_SF:
                return (0, self._wav_duration_ms(path))
            with _sf.SoundFile(path) as f:
                sr = f.samplerate
                data = f.read(dtype='float32')
            if data is None or len(data) == 0:
                return (0, self._wav_duration_ms(path))
            if data.ndim > 1:
                data = data.mean(axis=1)  # 多声道取平均
            # 每 20ms 一块算 RMS；阈值 = 峰值 RMS 的 4% 或绝对 0.002，取较大
            block = max(1, int(sr * 0.02))
            n = len(data) // block
            if n < 3:
                return (0, self._wav_duration_ms(path))
            blocks = data[:n * block].reshape(n, block)
            rms = _np.sqrt((blocks ** 2).mean(axis=1))
            peak = float(rms.max())
            thr = max(peak * 0.04, 0.002)
            over = _np.where(rms > thr)[0]
            if len(over) == 0:
                return (0, self._wav_duration_ms(path))
            start_b = int(over[0])
            end_b = int(over[-1]) + 1
            start_ms = int(start_b * block / sr * 1000)
            end_ms = int(end_b * block / sr * 1000)
            active = max(0, end_ms - start_ms)
            if active < 100:  # 有效语音太短，当作检测失败
                return (0, self._wav_duration_ms(path))
            return (start_ms, active)
        except Exception:
            return (0, self._wav_duration_ms(path))

    # ------------- 测试连接（设置面板用） -------------
    def test_connection(self, base_url, api_key, model, on_done):
        def _run():
            try:
                msgs = [{'role': 'user', 'content': '你好，请只回复：连接成功'}]
                r, _u = _chat_request(base_url, api_key, model, msgs, timeout=20)
                self.conn_tested.emit(True, r.strip()[:60])
            except Exception as e:
                self.conn_tested.emit(False, '%s' % e)
        threading.Thread(target=_run, daemon=True).start()