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
import threading
import time
import urllib.error
import urllib.request

from PyQt6.QtCore import QObject, Qt, QThread, QTimer, QUrl, QRect, QPoint, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen, QFont, QFontMetrics
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtWidgets import (
    QApplication,
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
    global pet_mod
    pet_mod = mod


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
# 服务路径写死为本机已部署的 audio.cpp 位置；地址从 tts_api_base 解析端口。
# ============================================================================
_AUDIO_CPP_SERVER = (
    r'C:\Users\mier\Desktop\deepseek work\breeze-tts-local\audio-cpp\bin-cuda\audiocpp_server.exe'
)
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


def _models_paths():
    """在 bin-cuda/models 下查找 breeze 家族 GGUF，返回可加载的模型文件列表。
    遍历 models_root 各子目录，取含 gguf 的路径（按文件名 bf16 优先）。"""
    svc_dir = os.path.dirname(_AUDIO_CPP_SERVER)
    root = os.path.join(svc_dir, 'models')
    if not os.path.isdir(root):
        return []
    hits = []
    for sub in sorted(os.listdir(root)):
        subdir = os.path.join(root, sub)
        if not os.path.isdir(subdir):
            continue
        for fn in os.listdir(subdir):
            if fn.lower().endswith('.gguf'):
                hits.append(os.path.join(subdir, fn))
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
    loaded_ok = False
    for model_path in _models_paths():
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
                break
        except Exception:
            continue
    if loaded_ok:
        return True, '服务已启动并加载模型（%s）' % os.path.basename(_models_paths()[0] if _models_paths() else '')
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
_BUBBLE_MAX_W = 520
_BUBBLE_MIN_W = 200
_BUBBLE_LIFE_MS = 5000   # 文字完全显示后停留 5 秒自动消失；点击可立即消失
_FOLLOW_MS = 300
_TYPE_MS = 18          # 每字显示间隔（ms）——约 55 字/秒，快速蹦出
_THINK_MS = 280        # 思考三点跳动间隔


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
        self._font = QFont('Microsoft YaHei', 18)
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
        self._lift_life()
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
        """文字与音频同步：按音频实际时长逐字蹦字（同始同终，速度贴合语速）。
        duration_ms=音频时长(ms)；每字间隔 = 时长/字数。0 或异常则回退匀速。"""
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
        if duration_ms and duration_ms > 0:
            # 最小间隔防止过快/过慢导致卡顿或超时
            interval = max(10, min(2000, int(duration_ms / n)))
        else:
            interval = _TYPE_MS
        self._type_timer.start(interval)

    def _type_step(self):
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
        # 默认放桌宠右边；放不下则放左边
        x = anchor.right() + 12
        if geo is not None and x + self.width() > geo.right():
            x = anchor.left() - 12 - self.width()
        y = anchor.top()
        if geo is not None:
            if y + self.height() > geo.bottom():
                y = geo.bottom() - self.height()
            y = max(y, geo.top())
            x = max(geo.left(), min(x, geo.right() - self.width()))
        self.move(x, y)


# ============================================================================
# 迷你输入条（右键桌宠弹出的一小段打字横条）
# ============================================================================
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
        esc = html.escape
        parts = []

        # 系统提示词置顶（灰斜体小字）
        if system_prompt:
            parts.append(
                '<div style="color:%s; font-style:italic; font-size:11px;'
                ' padding:4px 10px; margin:2px 6px 8px 6px;'
                ' background:%s; border-radius:8px;">'
                '▍系统提示词：%s</div>'
                % (self._SYS_COLOR, self._PANEL, esc(system_prompt)))

        if not messages:
            parts.append(
                '<div style="color:%s; text-align:center; padding:20px;">'
                '暂无对话内容——去和桌宠聊几句吧 ✨</div>' % self._SUB)

        for m in messages:
            role = m.get('role')
            content = (m.get('content') or '').rstrip()
            ts = m.get('ts') or '—'
            if role == 'user':
                # 用户消息：右对齐、青绿块；系统操作（清理等）则居中灰字
                if self._is_cmd(content):
                    parts.append(
                        '<div style="text-align:center; color:%s; font-size:11px;'
                        ' margin:3px 0;">⚙ %s · %s</div>'
                        % (self._SYS_COLOR, esc(content), ts))
                    continue
                parts.append(
                    '<div style="text-align:right; margin:3px 2px;">'
                    '<span style="background:%s; border:1px solid %s;'
                    ' border-radius:10px; padding:6px 10px; color:#dcecff;'
                    ' display:inline-block; max-width:72%%; text-align:left;">'
                    '<span style="color:%s; font-size:10px;">%s</span><br>%s'
                    '</span><br><span style="color:%s; font-size:9px;">%s · %s</span>'
                    '</div>'
                    % (self._USER_BG, self._USER_BORDER, self._SUB, esc('你'),
                       content.replace('\n', '<br>'),
                       self._TIME, esc('你'), ts))
            else:
                # AI / assistant 消息：左对齐、白块
                ai_name = getattr(self._pet, 'role', None) or 'AI'
                parts.append(
                    '<div style="text-align:left; margin:3px 2px;">'
                    '<span style="background:%s; border:1px solid %s;'
                    ' border-radius:10px; padding:6px 10px; color:%s;'
                    ' display:inline-block; max-width:72%%; text-align:left;">'
                    '<span style="color:%s; font-size:10px;">%s</span><br>%s'
                    '</span><br><span style="color:%s; font-size:9px;">%s · %s</span>'
                    '</div>'
                    % (self._AI_BG, self._AI_BORDER, self._TITLE, self._SUB,
                       esc(ai_name), content.replace('\n', '<br>'),
                       self._TIME, ai_name, ts))
        total = sum(len(m.get('content') or '') for m in messages)
        self.browser.setHtml(
            '<html><body style="font-family:Segoe UI,Microsoft YaHei;'
            ' padding:6px;">%s</body></html>' % ''.join(parts))
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
        c = (content or '').strip()
        return c in ('clear_context', '清理上下文', '清空上下文') or \
            c.startswith('已清理上下文') or c.startswith('已清空上下文')

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
    """迷你打字条：一小段可输入的行（历史改为桌宠旁气泡展示，不再用大窗）"""
    sendRequested = pyqtSignal(str)
    clearRequested = pyqtSignal()
    historyRequested = pyqtSignal()

    # 窗口尺寸常量：带用量行高 / 隐藏用量行高
    W_USAGE = 470
    H_USAGE = 70
    H_NO_USAGE = 46

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
        # 跟随桌宠移动（桌宠拖动时输入条贴住；用户手动拖过则停）
        self._follow = QTimer(self)
        self._follow.setInterval(16)   # ~60fps，减延迟感
        self._follow.timeout.connect(self._follow_pet)
        # 背景直接在 self 上画（圆角外区域因透明背景而透明）
        self.setStyleSheet(
            "ChatWindow{background:rgba(24,26,34,235); border-radius:14px;"
            " border:1px solid rgba(255,255,255,60);}")

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 8, 8, 6)
        root.setSpacing(3)
        row1 = QHBoxLayout()
        row1.setSpacing(6)
        # 清理上下文按钮放在最左侧（在输入框左边）
        self.btn_clear = QPushButton("清理上下文", self)
        self.btn_clear.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_clear.setToolTip("清理上下文（开始全新对话，AI 不再记得之前聊的）")
        self.btn_clear.setStyleSheet(
            "QPushButton{background:#5a3d3d; border:none; border-radius:9px;"
            " color:#ffd9d9; font-size:12px; padding:5px 9px;}"
            "QPushButton:hover{background:#7a4d4d;}")
        self.btn_clear.clicked.connect(self._clear)
        row1.addWidget(self.btn_clear)
        self.btn_history = QPushButton("📜 记录", self)
        self.btn_history.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_history.setToolTip("查看完整对话上下文（本会话全部消息）")
        self.btn_history.setStyleSheet(
            "QPushButton{background:#3a4458; border:none; border-radius:9px;"
            " color:#cfd8ee; font-size:12px; padding:5px 9px;}"
            "QPushButton:hover{background:#4a5670;}")
        self.btn_history.clicked.connect(self._open_history)
        row1.addWidget(self.btn_history)
        self.input = QLineEdit(self)
        self.input.setPlaceholderText("问桌宠…（回车发送，Esc 关闭）")
        self.input.setStyleSheet(
            "QLineEdit{background:rgba(255,255,255,20); border:none; border-radius:9px;"
            " color:#ffffff; font-size:14px; padding:5px 10px;}"
            "QLineEdit:focus{background:rgba(255,255,255,30);}")
        self.input.returnPressed.connect(self._send)
        row1.addWidget(self.input, 1)
        self.btn_send = QPushButton("发送", self)
        self.btn_send.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_send.setStyleSheet(
            "QPushButton{background:#3d6ef7; border:none; border-radius:9px;"
            " color:white; font-size:13px; font-weight:bold; padding:5px 12px;}"
            "QPushButton:hover{background:#5480ff;}"
            "QPushButton:disabled{background:#4a4f63;}")
        self.btn_send.clicked.connect(self._send)
        row1.addWidget(self.btn_send)
        self.btn_x = CloseXButton(self)
        row1.addWidget(self.btn_x)
        self.btn_x.clicked.connect(self.hide)
        root.addLayout(row1)
        # 第二行：单次 token 消耗 + 金额（深色底小字）
        self.lbl_usage = QLabel(self)
        self.lbl_usage.setText("")
        self.lbl_usage.setStyleSheet(
            "color:#8fa3c8; font-size:11px; background:rgba(255,255,255,6);"
            " border-radius:6px; padding:1px 8px;")
        root.addWidget(self.lbl_usage)
        self.setFixedSize(self.W_USAGE, self.H_USAGE)

    # 窗口拖动（按住空白/输入框外区域）——拖动后取消自动跟随
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._user_dragged = True
            try:
                self._follow.stop()
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
        self._drag_offset = None
        super().mouseReleaseEvent(e)

    def _follow_pet(self):
        """跟随桌宠移动（用户未手动拖动时）"""
        if self._user_dragged or self._pet is None:
            self._follow.stop()
            return
        try:
            pet_rect = self._pet.frameGeometry()
        except Exception:
            return
        if pet_rect is None:
            return
        # 保持与桌宠的相对偏移
        off = getattr(self, '_follow_offset', None)
        if off is None:
            off = self.pos() - pet_rect.topLeft()
            self._follow_offset = off
        nx = pet_rect.left() + off.x()
        ny = pet_rect.top() + off.y()
        # 限制在屏幕内
        scr = QApplication.screenAt(pet_rect.center()) or QApplication.primaryScreen()
        if scr is not None:
            geo = scr.availableGeometry()
            nx = max(geo.left(), min(nx, geo.right() - self.width()))
            ny = max(geo.top(), min(ny, geo.bottom() - self.height()))
        self.move(nx, ny)

    # ---------- 交互 ----------
    def keyPressEvent(self, e):
        # Esc 关闭迷你条
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

    def set_busy(self, busy):
        # 迷你条：思考中时输入框禁用、按钮变灰
        self.input.setEnabled(not busy)
        self.btn_send.setEnabled(not busy)
        self.btn_send.setText("…" if busy else "发送")

    def show_near(self, pet_rect):
        """显示在桌宠旁边（优先下方/右侧，保持不遮宠物），并开始跟随桌宠"""
        scr = QApplication.screenAt(pet_rect.center()) or QApplication.primaryScreen()
        geo = scr.availableGeometry() if scr is not None else None
        x = pet_rect.left()
        if geo is not None and x + self.width() > geo.right():
            x = geo.right() - self.width()
        y = pet_rect.bottom() + 10
        if geo is not None and y + self.height() > geo.bottom():
            y = pet_rect.top() - self.height() - 10
            if y < geo.top():
                y = pet_rect.bottom() + 10
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
        """清理上下文按钮"""
        self.clearRequested.emit()

    def _open_history(self):
        """查看完整对话按钮"""
        self.historyRequested.emit()

    def set_usage(self, text):
        """在输入条下方显示单次 token 消耗与金额；空串则隐藏该行"""
        if not hasattr(self, 'lbl_usage'):
            return
        if text:
            self.lbl_usage.setText(text)
            self.lbl_usage.show()
            self.setFixedSize(self.W_USAGE, self.H_USAGE)
        else:
            self.lbl_usage.setText("")
            self.lbl_usage.hide()
            self.setFixedSize(self.W_USAGE, self.H_NO_USAGE)


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
        self._messages = []           # 多轮上下文（不含 system，由发送时补）
        self._ai_worker = None
        self._tts_worker = None
        self._rewrite_worker = None
        self._pending_tts_seq = 0
        self._seq = 0                 # 递增序号：新 TTS 打断旧 TTS
        self._synced_text = ''        # 待朗读文本（音频就绪后随音频同步蹦字）
        self._last_usage = {}         # 最近一次 token 用量
        self._player = None
        self._audio_out = None
        try:
            self._player = QMediaPlayer()
            self._audio_out = QAudioOutput()
            self._player.setAudioOutput(self._audio_out)
            self._apply_tts_volume()   # 应用已保存的朗读音量
        except Exception:
            self._player = None
            self._audio_out = None

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
            return '本次 ↑%d[缓存%d] ↓%d 共%d tok  ≈ $%.4f%s' % (pin, pcache, pout, total, cost, tag)
        return '本次 ↑%d ↓%d 共%d tok  ≈ $%.4f%s' % (pin, pout, total, cost, tag)

    def _sync_chat_usage(self):
        """把上次用量显示到聊天条（打开聊天窗时恢复）"""
        if self._chat is None or not hasattr(self._chat, 'set_usage'):
            return
        if self._last_usage:
            try:
                self._chat.set_usage(self._usage_text(self._last_usage))
            except Exception:
                pass

    def _show_usage(self, usage):
        """AI 回复后：更新用量/金额到聊天条并记录累计"""
        self._last_usage = usage or {}
        if self._chat is not None and hasattr(self._chat, 'set_usage'):
            try:
                if self._last_usage:
                    self._chat.set_usage(self._usage_text(self._last_usage))
            except Exception:
                pass

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

    def system_prompt(self):
        """当前系统提示词（用户可自定义，存配置 ai.system_prompt）"""
        return (self.cfg().get('system_prompt') or '').strip() \
            or self.default_system_prompt()

    def set_system_prompt(self, text):
        _save_ai_cfg(system_prompt=text.strip())

    @staticmethod
    def default_tts_prompt():
        """TTS 系统提示词（朗读前把 AI 回答改写成朗读稿 + 自动补齐情绪）。
        模型按要求输出两行：
            情绪：<简短中文情绪/语气描述，10 字内>
            朗读：<改写后适合朗读的文本>
        情绪行会作为本地 TTS 引擎的 instruction（说话情绪），真正"模型自动补齐情绪"。"""
        return ('你是一名语音播报助手。请把下面这段文字改写成适合语音朗读的版本：'
                '口语自然、句子完整通顺，去掉 markdown 符号、列表序号、表情符号和链接，'
                '数字与英文按口语习惯读出，保留原意和关键信息。'
                '同时根据这段文字的语气，判断朗读时应该带有的情绪/语气'
                '（如：开心雀跃、难过低落、生气抱怨、平静温柔、撒娇俏皮、焦急担心等）。'
                '严格按以下两行格式输出，不要输出任何其它内容或解释：\n'
                '情绪：<简短中文情绪描述，10 字以内>\n'
                '朗读：<改写后的文本>')

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
        """播放指定音频文件（用于测试语音试听）。"""
        if self._player is None or not path or not os.path.exists(path):
            return
        try:
            self._player.stop()
            self._player.setSource(QUrl.fromLocalFile(path))
            self._player.play()
        except Exception:
            pass

    # ------------- 聊天窗 -------------
    def open_chat(self):
        if self._chat is None:
            self._chat = ChatWindow(self._pet)
            self._chat.sendRequested.connect(self._on_send)
            self._chat.clearRequested.connect(self.clear_context)
            self._chat.historyRequested.connect(self.show_history)
            # 打开时把已保存的用量显示同步上去
            try:
                self._sync_chat_usage()
            except Exception:
                pass
        self._chat.show_near(self._pet.frameGeometry())
        self._chat.show()
        self._chat.raise_()
        self._chat.activateWindow()
        self._chat.input.setFocus()

    def show_history(self):
        """点「📜 记录」：弹出完整对话上下文窗口并跟随桌宠"""
        if self._history is None:
            self._history = ChatHistoryWindow(self._pet)
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

    def clear_context(self):
        """清理多轮上下文（开始全新对话）"""
        self._messages = []
        self._last_usage = {}
        if self._chat is not None:
            try:
                self._chat.set_usage('')
            except Exception:
                pass
        # 历史窗实时刷新（清空后同步为空）
        try:
            self._refresh_history_if_open()
        except Exception:
            pass
        try:
            self._show_bubble('已清理上下文，开始全新对话 ✨')
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
                self._player.stop()
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
        # 思考指示：AI 思考中在桌宠旁显示三点跳动
        self._show_thinking()
        # 多轮上下文：system（可自定义）+ 最近 20 条
        msgs = [{'role': 'system', 'content': self.system_prompt()}]
        # 发送给 API 的消息只保留 role/content（服务商对多余字段可能报错）
        for m in self._messages[-20:]:
            msgs.append({'role': m.get('role'), 'content': m.get('content')})
        msgs.append({'role': 'user', 'content': text})
        # 本地完整上下文：带时间戳（供「完整对话」窗口展示）
        self._messages.append({'role': 'user', 'content': text,
                               'ts': time.strftime('%H:%M:%S')})
        # 实时刷新历史窗（若开着：立刻能看到自己刚发的消息）
        try:
            self._refresh_history_if_open()
        except Exception:
            pass
        self._ai_worker = AIWorker(base_url, api_key, model, msgs, self)
        self._ai_worker.done.connect(self._on_ai_done)
        self._ai_worker.finished.connect(self._ai_worker.deleteLater)
        self._ai_worker.start()

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
        self._hide_thinking()
        if err:
            self._bubble_msg('AI 请求失败：%s\n（检查 设置→AI 的服务器/密钥/模型）' % err)
            return
        usage = usage or {}
        # 单次用量：显示在桌宠旁的状态条
        try:
            self._show_usage(usage)
        except Exception:
            pass
        self._messages.append({'role': 'assistant', 'content': reply,
                               'ts': time.strftime('%H:%M:%S')})
        # 实时刷新历史窗（若开着：自动补上 AI 新回复，无需重开）
        try:
            self._refresh_history_if_open()
        except Exception:
            pass
        # TTS 依附 AI：若朗读开，则气泡文字等音频就绪后随音频同步蹦字（同始同终）
        if self.tts_enabled() and self.enabled():
            self._seq += 1
            self._pending_tts_seq = self._seq
            try:
                self._player.stop()
            except Exception:
                pass
            # 朗读合成期间先显示"思考中…"，音频就绪播放时再随音频逐字蹦
            self._show_thinking()
            self._rewrite_for_tts(reply, self._seq)
        else:
            # 不朗读 → 立即逐字蹦字显示
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
        if self._player is None or seq != getattr(self, '_pending_tts_seq', 0):
            return
        cfg = self.cfg()
        voice = (cfg.get('tts_api_voice') or cfg.get('tts_voice') or 'alloy')
        # 记录将朗读的文本 → 音频就绪时按音频时长同步蹦字
        self._synced_text = text
        self._tts_worker = TTSWorker(text, voice, seq, self, instruction=instruction)
        self._tts_worker.done.connect(
            lambda path, err, s=seq: self._on_tts_done(path, err, s))
        self._tts_worker.finished.connect(self._tts_worker.deleteLater)
        self._tts_worker.start()

    def _on_tts_done(self, path, err, seq):
        if seq != getattr(self, '_pending_tts_seq', 0):
            return   # 已有更新的朗读，丢弃旧合成
        if not path:
            self._bubble_msg('朗读失败：%s' % err)
            return
        vol = self.tts_volume()
        # 音量 >100% → 数字增益（QAudioOutput 上限 1.0）
        gain_path = path
        if vol > 100:
            gain_path = self.gain_wav_if_needed(path, vol)
        # 音频时长（同步蹦字用；失败回退默认间隔）
        dur_ms = self._wav_duration_ms(gain_path)
        # 文字随音频同步：按音频实际时长逐字蹦（同始同终）
        pending_text = (getattr(self, '_synced_text', '') or '').strip()
        self._synced_text = ''
        if pending_text:
            if self._bubble is not None:
                self._bubble._stop_thinking()
            self._get_bubble().show_text_synced(pending_text, dur_ms)
        else:
            self._hide_thinking()
        self._player.stop()
        self._player.setSource(QUrl.fromLocalFile(gain_path))
        self._player.play()
        # 播完（或超时）后清理临时文件
        def _cleanup():
            try:
                self._player.stop()
            except Exception:
                pass
            try:
                if os.path.exists(path):
                    os.remove(path)
                if gain_path != path and os.path.exists(gain_path):
                    os.remove(gain_path)
            except Exception:
                pass
        QTimer.singleShot(30000, _cleanup)

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