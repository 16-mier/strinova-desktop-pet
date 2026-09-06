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
import threading
import time
import urllib.error
import urllib.request

from PyQt6.QtCore import QObject, Qt, QThread, QTimer, QUrl, pyqtSignal
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


def _api_speech_synth(base_url, api_key, model, text, voice, out_path, timeout=60):
    """调 OpenAI 兼容 {base}/audio/speech 合成 mp3 到 out_path。
    返回 True/False；失败抛异常（由调用方兜底）。"""
    url = _norm_base_url(base_url) + '/audio/speech'
    body = json.dumps({
        'model': model,
        'input': text,
        'voice': voice,
        'response_format': 'mp3',
    }, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(url, data=body, method='POST')
    for k, v in _browser_headers({'Content-Type': 'application/json',
                                  'Authorization': 'Bearer %s' % (api_key or '')}).items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
    if not data:
        raise RuntimeError('语音服务返回空音频')
    with open(out_path, 'wb') as f:
        f.write(data)
    return True


def _chat_request(base_url, api_key, model, messages, timeout=90):
    """POST {base_url}/chat/completions，返回回复文本。失败抛异常"""
    url = _norm_base_url(base_url) + '/chat/completions'
    body = json.dumps(
        {'model': model, 'messages': messages, 'stream': False},
        ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(url, data=body, method='POST')
    for k, v in _browser_headers({'Content-Type': 'application/json',
                                  'Authorization': 'Bearer %s' % (api_key or '')}).items():
        req.add_header(k, v)
    # urllib 默认 ProxyHandler 会读环境变量 HTTP_PROXY/HTTPS_PROXY（走代理）
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode('utf-8'))
    try:
        return data['choices'][0]['message']['content']
    except Exception:
        return json.dumps(data, ensure_ascii=False)[:500]


def _list_models(base_url, api_key, timeout=30):
    """GET {base_url}/models，返回模型 ID 列表（OpenAI 兼容标准接口）。
    失败抛异常（401 未授权 / 网络 / 超时等）。"""
    url = _norm_base_url(base_url) + '/models'
    req = urllib.request.Request(url, method='GET')
    for k, v in _browser_headers({'Authorization': 'Bearer %s' % (api_key or '')}).items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode('utf-8'))
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
    done = pyqtSignal(str, str)   # (回复文本, 错误信息；错误时文本为空)

    def __init__(self, base_url, api_key, model, messages, parent=None):
        super().__init__(parent)
        self._base_url = base_url
        self._api_key = api_key
        self._model = model
        self._messages = messages

    def run(self):
        try:
            reply = _chat_request(self._base_url, self._api_key,
                                  self._model, self._messages)
            if not reply or not reply.strip():
                reply = '（AI 没有返回内容）'
            self.done.emit(reply, '')
        except Exception as e:
            self.done.emit('', '%s' % e)


# ============================================================================
# 后台线程：TTS 合成（唯一引擎 = 用户填地址的自定义 OpenAI 兼容语音服务）
# ============================================================================
class TTSWorker(QThread):
    done = pyqtSignal(str, str)   # (音频文件路径, 错误信息；错误时路径为空)

    def __init__(self, text, voice, seq, parent=None):
        super().__init__(parent)
        self._text = text
        self._voice = voice or 'alloy'
        self._seq = seq
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
        try:
            path = os.path.join(base, 'tts_%d_%d.mp3' % (self._seq, int(time.time() * 1000)))
            _api_speech_synth(api_base, api_key, api_model, self._text,
                              self._voice or 'alloy', path)
            return path
        except Exception as e:
            self._last_err = '%s' % e
            return None


# ============================================================================
# 回复气泡：显示在桌宠旁边（跟随桌宠、自动消失、点击关闭）
# ============================================================================
_BUBBLE_MAX_W = 380
_BUBBLE_MIN_W = 180
_BUBBLE_LIFE_MS = 20000
_FOLLOW_MS = 300


class BubbleWidget(QWidget):
    def __init__(self, pet):
        super().__init__(None,
                         Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool)
        self._pet = pet
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setMouseTracking(False)
        self._label = QLabel(self)
        self._label.setWordWrap(True)
        self._label.setStyleSheet(
            'color:#f0f2f8; background:transparent; font-size:12px;')
        self._label.setMargin(10)
        # 自动消失
        self._life = QTimer(self)
        self._life.setSingleShot(True)
        self._life.setInterval(_BUBBLE_LIFE_MS)
        self._life.timeout.connect(self.hide)
        # 跟随桌宠移动
        self._follow = QTimer(self)
        self._follow.setInterval(_FOLLOW_MS)
        self._follow.timeout.connect(self._reposition)

    def show_text(self, text):
        self._label.setText(text)
        self._label.adjustSize()
        w = min(_BUBBLE_MAX_W, max(_BUBBLE_MIN_W, self._label.sizeHint().width() + 24))
        self._label.setFixedWidth(w)
        self._label.adjustSize()
        self.resize(w + 20, self._label.height() + 20)
        self._reposition()
        self.show()
        self.raise_()
        self._life.start()
        self._follow.start()

    def hideEvent(self, ev):
        self._follow.stop()
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
# 聊天窗口（右键桌宠弹出）
# ============================================================================
class ChatWindow(QWidget):
    sendRequested = pyqtSignal(str)

    def __init__(self, pet):
        super().__init__(None, Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self._pet = pet
        self.setWindowTitle("卡丘简易桌宠 · AI 对话")
        self.setObjectName("chatRoot")
        self.setStyleSheet(CHAT_QSS)
        self.setFixedSize(400, 480)
        self._drag_offset = None

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)

        # 标题行（可拖动）
        title = QHBoxLayout()
        t = QLabel("💬 与 AI 对话")
        t.setStyleSheet("font-size:14px; font-weight:bold;")
        title.addWidget(t)
        title.addStretch(1)
        btn_x = QPushButton("✕")
        btn_x.setFixedSize(28, 24)
        btn_x.clicked.connect(self.hide)
        title.addWidget(btn_x)
        root.addLayout(title)

        # 历史
        self.history = QTextBrowser()
        self.history.setOpenExternalLinks(False)
        root.addWidget(self.history, 1)

        # 输入行
        row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("问问桌宠…（回车发送）")
        self.input.returnPressed.connect(self._send)
        row.addWidget(self.input, 1)
        self.btn_send = QPushButton("发送")
        self.btn_send.clicked.connect(self._send)
        row.addWidget(self.btn_send)
        root.addLayout(row)

        self.append_html('<div style="color:#8fa3c8;">你好呀，我是桌宠里的 AI 小伙伴～右键打开设置可调整 AI 服务与朗读开关。</div>')

    # ---------- 窗口拖动 ----------
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and e.position().y() < 40:
            self._drag_offset = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
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

    # ---------- 交互 ----------
    def _send(self):
        text = self.input.text().strip()
        if not text:
            return
        self.input.clear()
        self.sendRequested.emit(text)

    def set_busy(self, busy):
        self.input.setEnabled(not busy)
        self.btn_send.setEnabled(not busy)
        self.btn_send.setText("思考中…" if busy else "发送")

    def append_msg(self, who, text):
        color = '#9fb0d9' if who == '你' else '#ffd76e'
        esc = html.escape(text).replace('\n', '<br>')
        self.append_html(
            '<div style="color:%s; font-weight:bold; margin-top:8px;">%s</div>'
            '<div style="color:#e6e8f0;">%s</div>' % (color, who, esc))

    def append_err(self, err):
        self.append_html('<div style="color:#e06c75; margin-top:6px;">⚠ %s</div>' % html.escape(err))

    def append_html(self, h):
        self.history.append(h)
        bar = self.history.verticalScrollBar()
        bar.setValue(bar.maximum())

    def show_near(self, pet_rect):
        """显示在桌宠旁边（放不下则居中）"""
        scr = QApplication.screenAt(pet_rect.center()) or QApplication.primaryScreen()
        geo = scr.availableGeometry() if scr is not None else None
        x = pet_rect.left() - self.width() - 14
        if geo is None or x < geo.left():
            x = pet_rect.right() + 14
        if geo is not None and x + self.width() > geo.right():
            x = geo.left() + (geo.width() - self.width()) // 2
        y = pet_rect.top()
        if geo is not None:
            y = max(geo.top(), min(y, geo.bottom() - self.height()))
        self.move(x, y)


# ============================================================================
# AI 聊天管理器（右键打开聊天窗 + 气泡 + TTS 播放）
# ============================================================================
class AiChatManager(QObject):
    def __init__(self, pet):
        super().__init__()
        self._pet = pet
        self._chat = None
        self._bubble = None
        self._messages = []           # 多轮上下文（不含 system，由发送时补）
        self._ai_worker = None
        self._tts_worker = None
        self._rewrite_worker = None
        self._pending_tts_seq = 0
        self._seq = 0                 # 递增序号：新 TTS 打断旧 TTS
        self._player = None
        self._audio_out = None
        try:
            self._player = QMediaPlayer()
            self._audio_out = QAudioOutput()
            self._player.setAudioOutput(self._audio_out)
        except Exception:
            self._player = None
            self._audio_out = None

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

    def set_voice(self, voice):
        _save_ai_cfg(tts_voice=voice)

    def set_tts_api(self, base_url, api_key, model, voice=''):
        """配置自定义 TTS API 服务（OpenAI 兼容 /audio/speech）"""
        _save_ai_cfg(tts_api_base=base_url, tts_api_key=api_key,
                     tts_api_model=model, tts_api_voice=voice)

    def system_prompt(self):
        """当前系统提示词（用户可自定义，存配置 ai.system_prompt）"""
        return (self.cfg().get('system_prompt') or '').strip() \
            or self.default_system_prompt()

    def set_system_prompt(self, text):
        _save_ai_cfg(system_prompt=text.strip())

    @staticmethod
    def default_tts_prompt():
        """TTS 系统提示词（朗读前把 AI 回答改写成适合朗读的稿子）"""
        return ('你是一名语音播报助手。请把下面这段文字改写成适合语音朗读的版本：'
                '口语自然、句子完整通顺，去掉 markdown 符号、列表序号、表情符号和链接，'
                '数字与英文按口语习惯读出，保留原意和关键信息。'
                '只输出改写后的文本，不要任何解释或前缀。')

    def tts_prompt(self):
        return (self.cfg().get('tts_prompt') or '').strip() \
            or self.default_tts_prompt()

    def set_tts_prompt(self, text):
        _save_ai_cfg(tts_prompt=text.strip())

    def fetch_models(self, base_url, api_key, on_done):
        """后台拉取模型列表（OpenAI 兼容 /models）。on_done(ok, result)"""
        def _run():
            try:
                ms = _list_models(base_url, api_key)
                on_done(True, ms)
            except Exception as e:
                on_done(False, '%s' % e)
        threading.Thread(target=_run, daemon=True).start()

    def test_tts_api(self, base_url, api_key, model, voice, on_done):
        """后台测试自定义 TTS API 服务：合成一小段。on_done(ok, msg)"""
        def _run():
            try:
                path = os.path.join(_tts_dir() or '', 'tts_test.mp3')
                _api_speech_synth(base_url, api_key, model, '语音服务测试成功',
                                  voice or 'alloy', path, timeout=30)
                try:
                    os.remove(path)
                except Exception:
                    pass
                on_done(True, '合成成功')
            except Exception as e:
                on_done(False, '%s' % e)
        threading.Thread(target=_run, daemon=True).start()

    # ------------- 聊天窗 -------------
    def open_chat(self):
        if self._chat is None:
            self._chat = ChatWindow(self._pet)
            self._chat.sendRequested.connect(self._on_send)
        self._chat.show_near(self._pet.frameGeometry())
        self._chat.show()
        self._chat.raise_()
        self._chat.activateWindow()
        self._chat.input.setFocus()

    def close_all(self):
        if self._bubble is not None:
            self._bubble.hide()
        if self._chat is not None:
            self._chat.hide()
        if self._player is not None:
            try:
                self._player.stop()
            except Exception:
                pass

    # ------------- 发送 / 回复 -------------
    def _on_send(self, text):
        cfg = self.cfg()
        base_url = cfg.get('base_url') or DEFAULT_BASE_URL
        api_key = cfg.get('api_key') or ''
        model = cfg.get('model') or DEFAULT_MODEL
        if not api_key:
            self._chat.append_err('还没有填 API 密钥：右键打开设置 → AI 功能 里填写。')
            return
        if self._ai_worker is not None and self._ai_worker.isRunning():
            return
        self._chat.append_msg('你', text)
        self._chat.set_busy(True)
        # 多轮上下文：system（可自定义）+ 最近 20 条
        msgs = [{'role': 'system', 'content': self.system_prompt()}]
        msgs += self._messages[-20:]
        msgs.append({'role': 'user', 'content': text})
        self._messages.append({'role': 'user', 'content': text})
        self._ai_worker = AIWorker(base_url, api_key, model, msgs, self)
        self._ai_worker.done.connect(self._on_ai_done)
        self._ai_worker.finished.connect(self._ai_worker.deleteLater)
        self._ai_worker.start()

    # ------------- 气泡 -------------
    def _show_bubble(self, text):
        if self._bubble is None:
            self._bubble = BubbleWidget(self._pet)
        self._bubble.show_text(text)

    def _on_ai_done(self, reply, err):
        if self._chat is not None:
            self._chat.set_busy(False)
        self._ai_worker = None
        if err:
            if self._chat is not None:
                self._chat.append_err('AI 请求失败：%s\n（检查 设置→AI功能 的服务器地址/密钥/模型，及网络代理）' % err)
            return
        self._messages.append({'role': 'assistant', 'content': reply})
        if self._chat is not None:
            self._chat.append_msg('AI', reply)
        # 气泡显示回复（桌宠旁边）
        self._show_bubble(reply)
        # TTS 依附 AI（且必须 AI 对话开启才生效）：先把回复交给"TTS 提示词"
        # 改写为适合朗读的稿子，再朗读改写稿；改写失败直接朗读原文兜底
        if self.tts_enabled() and self.enabled():
            self._seq += 1
            self._pending_tts_seq = self._seq
            try:
                self._player.stop()
            except Exception:
                pass
            self._rewrite_for_tts(reply, self._seq)
        elif self.tts_enabled() and not self.enabled():
            # AI 对话被关但 tts_enabled 仍开（历史配置）→ 不朗读
            self.set_tts_enabled(False)

    # ------------- TTS（朗读 AI 回复） -------------
    def _rewrite_for_tts(self, reply, seq):
        """用 TTS 系统提示词让 AI 把回答改写成朗读稿，再合成播放。
        改写失败 → 直接朗读原文。"""
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
        w.done.connect(lambda txt, e, s=seq: self._on_rewrite_done(txt, e, s, reply))
        w.finished.connect(w.deleteLater)
        w.start()

    def _on_rewrite_done(self, text, err, seq, original):
        if seq != getattr(self, '_pending_tts_seq', 0) or not self.tts_enabled():
            return   # 期间有更新回复/关闭朗读 → 丢弃
        self._rewrite_worker = None
        speak = (text.strip() if (text and text.strip() and not err) else original)
        if not speak:
            return
        self._speak_text(speak, seq)

    def _speak_text(self, text, seq):
        if self._player is None or seq != getattr(self, '_pending_tts_seq', 0):
            return
        cfg = self.cfg()
        voice = (cfg.get('tts_api_voice') or cfg.get('tts_voice') or 'alloy')
        self._tts_worker = TTSWorker(text, voice, seq, self)
        self._tts_worker.done.connect(
            lambda path, err, s=seq: self._on_tts_done(path, err, s))
        self._tts_worker.finished.connect(self._tts_worker.deleteLater)
        self._tts_worker.start()

    def _on_tts_done(self, path, err, seq):
        if seq != getattr(self, '_pending_tts_seq', 0):
            return   # 已有更新的朗读，丢弃旧合成
        if not path:
            if self._chat is not None:
                self._chat.append_err('朗读失败：%s' % err)
            return
        self._player.stop()
        self._player.setSource(QUrl.fromLocalFile(path))
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
            except Exception:
                pass
        QTimer.singleShot(30000, _cleanup)

    # ------------- 测试连接（设置面板用） -------------
    def test_connection(self, base_url, api_key, model, on_done):
        def _run():
            try:
                msgs = [{'role': 'user', 'content': '你好，请只回复：连接成功'}]
                r = _chat_request(base_url, api_key, model, msgs, timeout=20)
                on_done(True, r.strip()[:60])
            except Exception as e:
                on_done(False, '%s' % e)
        threading.Thread(target=_run, daemon=True).start()