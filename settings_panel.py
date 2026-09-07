# -*- coding: utf-8 -*-
# settings_panel.py —— 卡丘简易桌宠 · 设置面板（独立窗口，替代旧弹出菜单）
# 四大模块：角色管理 / 音频管理 / 播放设备 / 热键设置
# 通过回调与 PetWindow 通信（不反向 import pet，避免循环）
import os
import sys
import shutil
import ctypes
import threading
from ctypes import wintypes

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QFileSystemWatcher, QRectF, QPoint
from PyQt6.QtGui import QFont, QPixmap, QIcon, QColor, QPalette, QPainter, QPen
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QListWidget, QListWidgetItem, QFileDialog,
    QMessageBox, QGroupBox, QScrollArea, QFrame, QCheckBox,
    QComboBox, QLineEdit, QSizePolicy, QSlider, QSpinBox, QPlainTextEdit,
)

# 无边框窗口缩放：WM_NCHITTEST 命中测试常量（仅 Windows 生效）
_WM_NCHITTEST = 0x0084
_HTLEFT = 10
_HTRIGHT = 11
_HTTOP = 12
_HTTOPLEFT = 13
_HTTOPRIGHT = 14
_HTBOTTOM = 15
_HTBOTTOMLEFT = 16
_HTBOTTOMRIGHT = 17
_RESIZE_MARGIN = 6  # 边缘热区像素（拖此区缩放）

# 与 pet.py 共享的常量与工具（从 pet import 会造成循环时再调整）
# 通过模块级注入方式避免循环导入：
pet_mod = None


def bind_pet_module(mod):
    """由 pet.py 启动时注入自身模块引用（避免循环 import）"""
    global pet_mod
    pet_mod = mod


PANEL_QSS = """
QWidget { background: #1a1c24; color: #e6e8f0; font-size: 13px; }
QGroupBox {
    background: #22252f; border: 1px solid #33374a;
    border-radius: 10px; margin-top: 12px; padding: 10px;
    font-weight: bold; color: #9fb0d9;
}
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 4px; }
QPushButton {
    background: #2c3142; border: 1px solid #3a4057; border-radius: 8px;
    padding: 7px 14px; color: #e6e8f0;
}
QPushButton:hover { background: #38405a; }
QPushButton:pressed { background: #232838; }
QPushButton:disabled { color: #666b80; background: #22252f; }
QListWidget {
    background: #191b23; border: 1px solid #33374a; border-radius: 8px;
    padding: 4px; outline: none;
}
QListWidget::item { padding: 3px 8px; border-radius: 6px; }
QListWidget::item:selected { background: #3d4a75; }
QListWidget::item:hover { background: #2b3145; }
QComboBox {
    background: #2c3142; border: 1px solid #3a4057; border-radius: 8px;
    padding: 5px 10px;
}
QComboBox QAbstractItemView { background: #1a1c24; selection-background-color: #3d4a75; }
QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 16px; height: 16px; }
QScrollArea { border: none; background: transparent; }
QScrollBar:vertical { background: transparent; width: 8px; }
QScrollBar::handle:vertical { background: #3a4057; border-radius: 4px; min-height: 30px; }
"""


class NoWheelComboBox(QComboBox):
    """禁用滚轮切换的下拉框（鼠标悬停滚动滚轮不改变选中项，防误触）"""

    def wheelEvent(self, event):
        # 忽略滚轮事件：悬停滚动不切换选项
        event.ignore()


class NoWheelSlider(QSlider):
    """禁用滚轮调值的滑块（鼠标悬停滚动滚轮不改变数值，防误触）"""

    def wheelEvent(self, event):
        event.ignore()


class CloseButton(QPushButton):
    """自绘 ✕ 关闭按钮（画两条交叉线，任何系统都显示为标准 X，不受字体影响）"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(30, 26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
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
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # 背景：hover 时变红提示（关闭按钮惯例）
        if self._hover:
            p.setBrush(QColor(200, 60, 60, 220))
        else:
            p.setBrush(QColor(70, 74, 92, 200))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(self.rect(), 6, 6)
        # 画 X：两条交叉线
        pad = 8
        x1, y1 = pad, pad
        x2, y2 = self.width() - pad, self.height() - pad
        pen = QPen(QColor(255, 255, 255, 235), 2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawLine(x1, y1, x2, y2)
        p.drawLine(x2, y1, x1, y2)
        p.end()


class SettingsPanel(QWidget):
    """桌宠设置面板窗口（置顶、可拖动标题栏关闭）"""

    # 信号：通知 pet 状态变化
    sig_role_changed = pyqtSignal(str)          # 切换角色
    sig_bind_device = pyqtSignal(str)           # 绑定输出设备(空=不绑)
    sig_self_device = pyqtSignal(str)           # 自己监听设备(空=关)
    sig_auto_ptt = pyqtSignal(bool)             # 自动按开麦键
    sig_ptt_key = pyqtSignal(str)               # 开麦键名
    sig_hotkeys_enabled = pyqtSignal(bool)      # 热键总开关
    sig_audio_hotkey = pyqtSignal(str, str)     # (audio_key, 键名) 绑定音频快捷键
    sig_audio_play = pyqtSignal(str)            # 试听音频(path)
    sig_audio_removed = pyqtSignal(str, str)    # 删除音频 (role, path)
    sig_character_added = pyqtSignal(str)       # 新增角色(文件夹名)
    sig_character_removed = pyqtSignal(str)     # 删除角色
    sig_request_rescan = pyqtSignal()           # 请求重新扫描

    def __init__(self, pet_window=None):
        super().__init__()
        self._pet = pet_window  # 弱引用持有 pet 实例（读当前状态用）
        # 无边框窗口：去掉系统标题栏（避免出现多余的 系统 最小化/关闭 按钮与自定义 ✕ 混叠）
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
        )
        self.setWindowTitle("卡丘简易桌宠 · 设置")
        self.setMinimumSize(520, 560)
        # 默认开大些：不超过屏幕可用区（留 60px 边距），之后可拖边缘继续放大
        scr = QApplication.primaryScreen().availableGeometry() if QApplication.primaryScreen() else None
        if scr is not None:
            w = max(520, min(720, scr.width() - 60))
            h = max(560, min(860, scr.height() - 60))
        else:
            w, h = 720, 860
        self.resize(w, h)
        self.setMouseTracking(True)  # 边缘悬停 → 更新缩放光标
        self.setAcceptDrops(True)    # 支持把音频/图片/文件夹拖入面板导入
        self.setStyleSheet(PANEL_QSS)
        self._drag_offset = None  # 拖动标题栏移动窗口
        self._drop_armed = False  # 拖入文件悬停中（高亮）
        self._fs_watcher = QFileSystemWatcher(self)
        self._fs_watcher.directoryChanged.connect(self._on_dir_changed)
        self._auto_refresh_timer = QTimer(self)
        self._auto_refresh_timer.setSingleShot(True)
        self._auto_refresh_timer.setInterval(250)
        self._auto_refresh_timer.timeout.connect(self._delayed_refresh)
        self._build_ui()
        self._connect_ai_signals()
        self.refresh_all()
        self._watch_current_dir()
        # 定时探测本地 TTS 服务状态（UI 上的启动/停止按钮状态实时反映）
        self._svc_timer = QTimer(self)
        self._svc_timer.setInterval(5000)
        self._svc_timer.timeout.connect(self._refresh_tts_svc_state)
        self._svc_timer.start()
        self._refresh_tts_svc_state()

    def _connect_ai_signals(self):
        """连接 AI 管理器的跨线程信号（后台线程 emit → 主线程槽执行，安全操作 UI）。
        在 __init__ 连接一次，槽内从当前输入框取值。"""
        pet = self._current_pet()
        if pet is None or not hasattr(pet, 'ai'):
            return
        ai = pet.ai
        try:
            ai.models_fetched.connect(self._on_models_fetched)
            ai.tts_api_tested.connect(self._on_tts_api_tested)
            ai.conn_tested.connect(self._on_conn_tested)
        except Exception:
            pass

    # ---------------- AI 后台回调（主线程） ----------------
    def _on_models_fetched(self, ok, result):
        # 诊断日志：无论成败都记录详细原因（写 pet_debug.log）
        try:
            if pet_mod is not None and hasattr(pet_mod, '_dbg'):
                pet_mod._dbg('[AI刷新模型] ok=%s result=%s' % (ok, str(result)[:200]))
        except Exception:
            pass
        if not ok:
            msg = str(result)
            if '403' in msg or 'Forbidden' in msg:
                tip = "服务商未开放模型列表接口（403），可直接在下方手动输入模型名"
            elif '401' in msg or 'Unauthorized' in msg:
                tip = "API 密钥无效或没有权限（401），请检查密钥"
            elif '404' in msg or 'Not Found' in msg:
                tip = "服务地址不对（404），请检查是否填了完整 /v1 地址"
            else:
                tip = msg[:80]
            self._ai_status("模型检测失败：%s" % tip, "#e06c75")
            return
        models = result
        if not models:
            self._ai_status("服务未返回模型列表，可手动输入模型名", "#e06c75")
            return
        pet = self._current_pet()
        self.cmb_ai_model.blockSignals(True)
        self.cmb_ai_model.clear()
        for m in models:
            self.cmb_ai_model.addItem(m)
        cur = (pet.ai.cfg().get('model') or '') if pet is not None else ''
        if cur and cur in models:
            self.cmb_ai_model.setCurrentText(cur)
        self.cmb_ai_model.blockSignals(False)
        self._ai_status("✅ 检测到 %d 个模型，请选择" % len(models), "#7ae0a3")

    def _on_tts_api_tested(self, ok, msg):
        if ok:
            self.lbl_tts_api_status.setText("✅ 合成成功，正在播放试听…")
            self.lbl_tts_api_status.setStyleSheet("color:#7ae0a3; font-size:11px;")
            # msg = 合成好的音频路径 → 播放让用户听到
            pet = self._current_pet()
            if pet is not None and hasattr(pet, 'ai') and str(msg):
                try:
                    pet.ai.play_audio_file(str(msg))
                except Exception:
                    pass
        else:
            self.lbl_tts_api_status.setText("❌ %s" % str(msg)[:90])
            self.lbl_tts_api_status.setStyleSheet("color:#e06c75; font-size:11px;")

    def _on_conn_tested(self, ok, msg):
        self._ai_status(("✅ 连接成功：" if ok else "❌ 失败：") + str(msg)[:80],
                        "#7ae0a3" if ok else "#e06c75")

    # ---------------- UI 构建 ----------------
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        # 标题行
        title_row = QHBoxLayout()
        t = QLabel("⚙ 桌宠设置")
        t.setStyleSheet("font-size:16px; font-weight:bold; color:#ffffff;")
        title_row.addWidget(t)
        title_row.addStretch(1)
        btn_close = CloseButton()
        btn_close.clicked.connect(self.close)
        title_row.addWidget(btn_close)
        root.addLayout(title_row)

        # 滚动区容纳各模块
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        body.setStyleSheet("background:transparent;")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(2, 2, 6, 2)
        bl.setSpacing(10)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        # ---- 模块0：AI（置顶入口，点开为 AI 配置页）----
        self.ai_expanded = False      # AI 配置区是否展开
        self.btn_ai_head = QPushButton("🤖 AI")
        self.btn_ai_head.setCheckable(True)
        self.btn_ai_head.setStyleSheet(
            "QPushButton{background:#2f3b66; border:1px solid #4a5a96; border-radius:10px;"
            " padding:10px 14px; font-size:15px; font-weight:bold; color:#cfe0ff; text-align:left;}"
            "QPushButton:hover{background:#3a4a7a;}"
            "QPushButton:checked{background:#3d4f85; border-color:#6b7fd0;}")
        self.btn_ai_head.clicked.connect(self._toggle_ai_page)
        bl.addWidget(self.btn_ai_head)

        # AI 配置容器（默认收起；点「AI」展开）
        self.ai_box = QWidget()
        self.ai_box.setStyleSheet("background:#22252f; border:1px solid #33374a; border-radius:10px;")
        ail = QVBoxLayout(self.ai_box)
        ail.setContentsMargins(12, 10, 12, 10)
        ail.setSpacing(8)
        # 主开关：AI 对话（默认关）
        self.chk_ai_enabled = QCheckBox("启用 AI 对话（右键桌宠打开聊天窗）")
        self.chk_ai_enabled.toggled.connect(self._ai_apply_enabled)
        ail.addWidget(self.chk_ai_enabled)
        # AI 服务：OpenAI 兼容接口
        r_base = QHBoxLayout()
        r_base.addWidget(QLabel("服务器地址："))
        self.ed_ai_base = QLineEdit()
        self.ed_ai_base.setPlaceholderText("https://api.deepseek.com/v1")
        self.ed_ai_base.editingFinished.connect(self._ai_auto_fetch)
        r_base.addWidget(self.ed_ai_base, 1)
        ail.addLayout(r_base)
        r_key = QHBoxLayout()
        r_key.addWidget(QLabel("API 密钥："))
        self.ed_ai_key = QLineEdit()
        self.ed_ai_key.setPlaceholderText("sk-…")
        self.ed_ai_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.ed_ai_key.editingFinished.connect(self._ai_auto_fetch)
        r_key.addWidget(self.ed_ai_key, 1)
        ail.addLayout(r_key)
        # 模型：自动检测 + 下拉挑选
        r_model = QHBoxLayout()
        r_model.addWidget(QLabel("模型："))
        self.cmb_ai_model = NoWheelComboBox()
        self.cmb_ai_model.setEditable(True)
        self.cmb_ai_model.setPlaceholderText("填地址+密钥后自动检测…")
        self.cmb_ai_model.currentTextChanged.connect(self._ai_apply_model)
        r_model.addWidget(self.cmb_ai_model, 1)
        btn_ai_fetch = QPushButton("↻ 刷新模型")
        btn_ai_fetch.clicked.connect(self._ai_auto_fetch)
        r_model.addWidget(btn_ai_fetch)
        ail.addLayout(r_model)
        r_btn_ai = QHBoxLayout()
        btn_ai_save = QPushButton("保存 AI 设置")
        btn_ai_save.clicked.connect(self._ai_save)
        r_btn_ai.addWidget(btn_ai_save)
        btn_ai_test = QPushButton("测试连接")
        btn_ai_test.clicked.connect(self._ai_test)
        r_btn_ai.addWidget(btn_ai_test)
        r_btn_ai.addStretch(1)
        ail.addLayout(r_btn_ai)
        self.lbl_ai_status = QLabel("💡 填好服务器地址与密钥后会自动检测可用模型，选一个即可。")
        self.lbl_ai_status.setStyleSheet("color:#7a8099; font-size:11px;")
        ail.addWidget(self.lbl_ai_status)
        # 系统提示词（AI 人设，可自定义）
        lbl_sys = QLabel("系统提示词（AI 的人设/规则）：")
        lbl_sys.setStyleSheet("color:#9fb0d9; font-weight:bold; font-size:12px; margin-top:4px;")
        ail.addWidget(lbl_sys)
        self.ed_ai_sysprompt = QPlainTextEdit()
        self.ed_ai_sysprompt.setPlaceholderText("例：你是桌宠「卡丘」里的 AI 小伙伴，活泼友善，回答简洁亲切，用中文。")
        self.ed_ai_sysprompt.setFixedHeight(70)
        self.ed_ai_sysprompt.textChanged.connect(self._ai_apply_sysprompt)
        ail.addWidget(self.ed_ai_sysprompt)
        # 单价（每百万 token，美元）——用于聊天条显示 token 消耗金额
        # 三档：进（缓存未命中）/ 缓存（缓存命中，DeepSeek 前缀缓存约98%折扣）/ 出
        pr_row = QHBoxLayout()
        pr_row.setSpacing(3)
        pr_row.addWidget(QLabel("单价($/M)：进"))
        self.ed_ai_price_in = QLineEdit()
        self.ed_ai_price_in.setPlaceholderText("0.14")
        self.ed_ai_price_in.setFixedWidth(62)
        self.ed_ai_price_in.editingFinished.connect(self._ai_apply_prices)
        pr_row.addWidget(self.ed_ai_price_in)
        pr_row.addWidget(QLabel("缓存"))
        self.ed_ai_price_cache = QLineEdit()
        self.ed_ai_price_cache.setPlaceholderText("0.0028")
        self.ed_ai_price_cache.setFixedWidth(70)
        self.ed_ai_price_cache.editingFinished.connect(self._ai_apply_prices)
        pr_row.addWidget(self.ed_ai_price_cache)
        pr_row.addWidget(QLabel("出"))
        self.ed_ai_price_out = QLineEdit()
        self.ed_ai_price_out.setPlaceholderText("0.28")
        self.ed_ai_price_out.setFixedWidth(62)
        self.ed_ai_price_out.editingFinished.connect(self._ai_apply_prices)
        pr_row.addWidget(self.ed_ai_price_out)
        pr_row.addStretch(1)
        ail.addLayout(pr_row)
        # 提示：单价会在「选模型」时按官方价自动带出（用户已改则不覆盖）
        lbl_price_hint = QLabel("选模型时若单价仍是默认值会自动按官方价带入（deepseek-v4-flash 0.14/0.28/缓存0.0028）；改后不再联动。")
        lbl_price_hint.setStyleSheet("color:#6f7899; font-size:10px; margin-top:0px;")
        ail.addWidget(lbl_price_hint)
        # DeepSeek 峰谷自动计价：高峰用所填价，空闲时段半价（北京时间周一至五 9-12/14-18 高峰）
        peak_row = QHBoxLayout()
        peak_row.setSpacing(6)
        self.chk_ai_peak = QCheckBox("⚡ 按 DeepSeek 峰谷自动计价（空闲半价）")
        self.chk_ai_peak.toggled.connect(self._ai_apply_peak)
        peak_row.addWidget(self.chk_ai_peak)
        peak_row.addStretch(1)
        ail.addLayout(peak_row)
        self.lbl_peak_state = QLabel("")
        self.lbl_peak_state.setStyleSheet("color:#6f7899; font-size:10px;")
        ail.addWidget(self.lbl_peak_state)
        # TTS（朗读，依附 AI：AI 对话开启才能开启朗读）
        self.chk_ai_tts = QCheckBox("朗读 AI 回复（TTS）")
        self.chk_ai_tts.toggled.connect(self._ai_apply_tts)
        ail.addWidget(self.chk_ai_tts)
        # 本地 TTS 服务控制（启动/停止 + 状态灯）
        svc_row = QHBoxLayout()
        self.lbl_tts_svc_state = QLabel("本地 TTS 服务：检测中…")
        self.lbl_tts_svc_state.setStyleSheet("color:#8fa3c8; font-size:11px;")
        svc_row.addWidget(self.lbl_tts_svc_state, 1)
        self.btn_tts_svc_start = QPushButton("▶ 启动服务")
        self.btn_tts_svc_start.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_tts_svc_start.setStyleSheet(
            "QPushButton{background:#2a5c3a; border:none; border-radius:7px; color:#fff;"
            " padding:4px 10px; font-size:12px;}"
            "QPushButton:hover{background:#35754a;}")
        self.btn_tts_svc_start.clicked.connect(self._ai_tts_svc_start)
        svc_row.addWidget(self.btn_tts_svc_start)
        self.btn_tts_svc_stop = QPushButton("■ 停止服务")
        self.btn_tts_svc_stop.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_tts_svc_stop.setStyleSheet(
            "QPushButton{background:#5c2a2a; border:none; border-radius:7px; color:#fff;"
            " padding:4px 10px; font-size:12px;}"
            "QPushButton:hover{background:#754a35;}")
        self.btn_tts_svc_stop.clicked.connect(self._ai_tts_svc_stop)
        svc_row.addWidget(self.btn_tts_svc_stop)
        ail.addLayout(svc_row)
        lbl_tts_api = QLabel("朗读服务（填语音 API 地址；本地 TTS 用 http://127.0.0.1:8080/v1）：")
        lbl_tts_api.setStyleSheet("color:#9fb0d9; font-weight:bold; font-size:12px; margin-top:2px;")
        ail.addWidget(lbl_tts_api)
        # 自定义 TTS API 服务（OpenAI 兼容 /audio/speech）——唯一朗读引擎
        self.api_tts_box = QWidget()
        atl = QVBoxLayout(self.api_tts_box)
        atl.setContentsMargins(0, 0, 0, 0)
        atl.setSpacing(6)
        r_api_base = QHBoxLayout()
        r_api_base.addWidget(QLabel("服务地址："))
        self.ed_tts_api_base = QLineEdit()
        self.ed_tts_api_base.setPlaceholderText("https://api.siliconflow.cn/v1 或其它 OpenAI 兼容语音服务")
        self.ed_tts_api_base.editingFinished.connect(self._ai_apply_tts_api)
        r_api_base.addWidget(self.ed_tts_api_base, 1)
        atl.addLayout(r_api_base)
        r_api_key = QHBoxLayout()
        r_api_key.addWidget(QLabel("API 密钥："))
        self.ed_tts_api_key = QLineEdit()
        self.ed_tts_api_key.setPlaceholderText("sk-…")
        self.ed_tts_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.ed_tts_api_key.editingFinished.connect(self._ai_apply_tts_api)
        r_api_key.addWidget(self.ed_tts_api_key, 1)
        atl.addLayout(r_api_key)
        r_api_model = QHBoxLayout()
        r_api_model.addWidget(QLabel("语音模型："))
        self.ed_tts_api_model = QLineEdit()
        self.ed_tts_api_model.setPlaceholderText("如 tts-1 / FunAudioLLM/CosyVoice2-0.5B 等，按服务商填")
        self.ed_tts_api_model.editingFinished.connect(self._ai_apply_tts_api)
        r_api_model.addWidget(self.ed_tts_api_model, 1)
        atl.addLayout(r_api_model)
        r_api_voice = QHBoxLayout()
        r_api_voice.addWidget(QLabel("音色："))
        self.ed_tts_api_voice = QLineEdit()
        self.ed_tts_api_voice.setPlaceholderText("如 alloy / 中文女声名，按服务商填")
        self.ed_tts_api_voice.editingFinished.connect(self._ai_apply_tts_api)
        r_api_voice.addWidget(self.ed_tts_api_voice, 1)
        btn_tts_api_test = QPushButton("测试语音")
        btn_tts_api_test.clicked.connect(self._ai_test_tts_api)
        r_api_voice.addWidget(btn_tts_api_test)
        atl.addLayout(r_api_voice)
        # 克隆音色三件套（本地 TTS 引擎如 audio.cpp/BreezeTTS 2 支持声音克隆）
        r_api_ref = QHBoxLayout()
        r_api_ref.addWidget(QLabel("参考音频："))
        self.ed_tts_api_ref = QLineEdit()
        self.ed_tts_api_ref.setPlaceholderText("克隆用参考音频的完整路径（如 D:\\audio-cpp\\refs\\星绘.wav）；留空=不克隆")
        self.ed_tts_api_ref.setToolTip("声音克隆：提供一段参考音频 + 它的转录，让模型学这个音色说话。填了才启用克隆。")
        self.ed_tts_api_ref.editingFinished.connect(self._ai_apply_tts_api)
        r_api_ref.addWidget(self.ed_tts_api_ref, 1)
        btn_tts_ref_pick = QPushButton("浏览…")
        btn_tts_ref_pick.clicked.connect(self._ai_pick_tts_ref)
        r_api_ref.addWidget(btn_tts_ref_pick)
        atl.addLayout(r_api_ref)
        r_api_reftext = QHBoxLayout()
        r_api_reftext.addWidget(QLabel("参考转录："))
        self.ed_tts_api_ref_text = QLineEdit()
        self.ed_tts_api_ref_text.setPlaceholderText("参考音频里说的原话（须与音频一致），克隆时必填")
        self.ed_tts_api_ref_text.editingFinished.connect(self._ai_apply_tts_api)
        r_api_reftext.addWidget(self.ed_tts_api_ref_text, 1)
        atl.addLayout(r_api_reftext)
        r_api_instr = QHBoxLayout()
        r_api_instr.addWidget(QLabel("默认情绪："))
        self.ed_tts_api_instr = QLineEdit()
        self.ed_tts_api_instr.setPlaceholderText("留空=AI 自动判断语气；或填如「难过地低声」作为默认")
        self.ed_tts_api_instr.setToolTip("默认说话情绪/人设。留空时，朗读会先由 AI 按文本自动判断情绪再合成（自动补齐情绪）。")
        self.ed_tts_api_instr.editingFinished.connect(self._ai_apply_tts_api)
        r_api_instr.addWidget(self.ed_tts_api_instr, 1)
        atl.addLayout(r_api_instr)
        self.lbl_tts_api_status = QLabel("")
        self.lbl_tts_api_status.setStyleSheet("color:#7a8099; font-size:11px;")
        atl.addWidget(self.lbl_tts_api_status)
        ail.addWidget(self.api_tts_box)   # 常驻显示（唯一朗读引擎=填地址）
        # 朗读音量滑块（实时生效 + 可填数字；0-300%，>100 数字增益）
        vol_row = QHBoxLayout()
        vol_row.addWidget(QLabel("朗读音量："))
        self.sld_tts_volume = NoWheelSlider(Qt.Orientation.Horizontal)
        self.sld_tts_volume.setRange(0, 300)
        self.sld_tts_volume.setSingleStep(10)
        self.sld_tts_volume.setValue(100)
        self.sld_tts_volume.valueChanged.connect(self._ai_apply_tts_volume)
        vol_row.addWidget(self.sld_tts_volume, 1)
        self.spn_tts_volume = QSpinBox()
        self.spn_tts_volume.setRange(0, 300)
        self.spn_tts_volume.setSuffix(" %")
        self.spn_tts_volume.valueChanged.connect(self._ai_apply_tts_volume)
        vol_row.addWidget(self.spn_tts_volume)
        ail.addLayout(vol_row)
        # TTS 提示词：朗读前让 AI 改写（依附 AI，AI 关则朗读也关）
        lbl_ttp = QLabel("TTS 提示词（朗读前让 AI 把回答改成适合朗读的稿子）：")
        lbl_ttp.setStyleSheet("color:#9fb0d9; font-weight:bold; font-size:12px; margin-top:4px;")
        ail.addWidget(lbl_ttp)
        self.ed_ai_ttsprompt = QPlainTextEdit()
        self.ed_ai_ttsprompt.setPlaceholderText(
            "例：请把文字改写成适合语音朗读的版本：口语自然、去掉符号表情、保留原意。只输出改写文本。")
        self.ed_ai_ttsprompt.setFixedHeight(70)
        self.ed_ai_ttsprompt.textChanged.connect(self._ai_apply_ttsprompt)
        ail.addWidget(self.ed_ai_ttsprompt)
        tip5 = QLabel("朗读的文本会先由 AI 按 TTS 提示词改写，再交给上方填写的语音服务合成。")
        tip5.setStyleSheet("color:#7a8099; font-size:11px;")
        ail.addWidget(tip5)
        bl.addWidget(self.ai_box)
        self.ai_box.setVisible(False)
        # 在布局中把 AI 区块保持在最前（已最先 addWidget）

        # ---- 模块1：当前角色 + 角色管理 ----
        gb_role = QGroupBox("形象角色")
        rl = QVBoxLayout(gb_role)
        cur_row = QHBoxLayout()
        cur_row.addWidget(QLabel("当前角色："))
        self.lbl_cur_role = QLabel("-")
        self.lbl_cur_role.setStyleSheet("color:#ffd76e; font-weight:bold;")
        cur_row.addWidget(self.lbl_cur_role)
        cur_row.addStretch(1)
        rl.addLayout(cur_row)
        # 桌宠大小：滑块 + 可输入数字（拖动实时预览；直接填数也行）
        size_row = QHBoxLayout()
        size_row.addWidget(QLabel("桌宠大小："))
        self.sld_size = NoWheelSlider(Qt.Orientation.Horizontal)
        self.sld_size.setRange(60, 600)
        self.sld_size.setSingleStep(10)
        self.sld_size.setPageStep(20)
        self.sld_size.valueChanged.connect(self._on_size_changed)
        size_row.addWidget(self.sld_size, 1)
        self.spn_size = QSpinBox()
        self.spn_size.setRange(60, 600)
        self.spn_size.setSingleStep(10)
        self.spn_size.setSuffix(" px")
        self.spn_size.setMinimumWidth(86)
        self.spn_size.valueChanged.connect(self._on_size_changed)
        size_row.addWidget(self.spn_size)
        rl.addLayout(size_row)
        # 角色列表 + 侧按钮
        row = QHBoxLayout()
        self.role_list = QListWidget()
        self.role_list.setMinimumHeight(90)
        self.role_list.itemClicked.connect(self._on_role_clicked)
        row.addWidget(self.role_list, 1)
        btn_col = QVBoxLayout()
        # 单击角色名即切换（双击/单击均可，无需"切换"按钮）
        btn_import = QPushButton("导入新形象")
        btn_import.clicked.connect(self._import_character)
        btn_col.addWidget(btn_import)
        btn_del = QPushButton("删除角色")
        btn_del.clicked.connect(self._delete_selected_role)
        btn_col.addWidget(btn_del)
        btn_col.addStretch(1)
        row.addLayout(btn_col)
        rl.addLayout(row)
        tip = QLabel("💡 直接把 图片/角色文件夹 拖进本窗口即可添加角色，或点「导入新形象」选择图片")
        tip.setStyleSheet("color:#7a8099; font-size:11px;")
        rl.addWidget(tip)
        bl.addWidget(gb_role)

        # ---- 模块2：音频管理 ----
        gb_audio = QGroupBox("语音音频")
        al = QVBoxLayout(gb_audio)
        # 语音来源：当前角色（专属）/ 通用语音（任何角色共用）
        src_row = QHBoxLayout()
        src_row.addWidget(QLabel("语音来源："))
        self.cmb_voice_src = NoWheelComboBox()
        self.cmb_voice_src.addItem("当前角色专属", 'role')
        self.cmb_voice_src.addItem("通用语音（所有角色共用）", 'common')
        self.cmb_voice_src.currentIndexChanged.connect(self._on_voice_src_changed)
        src_row.addWidget(self.cmb_voice_src, 1)
        al.addLayout(src_row)
        self.audio_list = QListWidget()
        self.audio_list.setMinimumHeight(110)
        self.audio_list.itemClicked.connect(self._on_audio_clicked)
        self.audio_list.itemDoubleClicked.connect(self._preview_selected_audio)
        al.addWidget(self.audio_list)
        arow = QHBoxLayout()
        btn_import_audio = QPushButton("导入音频…")
        btn_import_audio.clicked.connect(self._import_audio)
        arow.addWidget(btn_import_audio)
        btn_del_audio = QPushButton("删除所选")
        btn_del_audio.clicked.connect(self._delete_selected_audio)
        arow.addWidget(btn_del_audio)
        btn_play = QPushButton("▶ 试听")
        btn_play.clicked.connect(self._preview_selected_audio)
        arow.addWidget(btn_play)
        # 绑定快捷键模式按钮（点它才进入录制，避免误绑）
        self.btn_bind = QPushButton("🔑 绑定/修改快捷键")
        self.btn_bind.setCheckable(True)
        self.btn_bind.toggled.connect(self._on_bind_mode_toggled)
        arow.addWidget(self.btn_bind)
        arow.addStretch(1)
        al.addLayout(arow)
        self.lbl_bind_tip = QLabel("💡 选中语音后可试听/绑定快捷键（可绑 F1…或小键盘数字1-9）；每个语音来源可各绑一套，互不干扰")
        self.lbl_bind_tip.setStyleSheet("color:#7a8099; font-size:11px;")
        al.addWidget(self.lbl_bind_tip)
        bl.addWidget(gb_audio)

        # ---- 模块3：播放设备 ----
        gb_dev = QGroupBox("播放设备 / 队友麦克风")
        dl = QVBoxLayout(gb_dev)
        # 绑定麦克风（队友听）
        r1 = QHBoxLayout()
        r1.addWidget(QLabel("绑定麦克风(队友听)："))
        self.cmb_bind = NoWheelComboBox()
        self.cmb_bind.currentIndexChanged.connect(self._on_bind_changed)
        r1.addWidget(self.cmb_bind, 1)
        dl.addLayout(r1)
        # 自己监听
        r2 = QHBoxLayout()
        r2.addWidget(QLabel("自己监听(耳机)："))
        self.cmb_self = NoWheelComboBox()
        self.cmb_self.currentIndexChanged.connect(self._on_self_changed)
        r2.addWidget(self.cmb_self, 1)
        dl.addLayout(r2)
        bl.addWidget(gb_dev)

        # ---- 模块4：热键 / PTT ----
        gb_hk = QGroupBox("快捷键 / 开麦")
        hl = QVBoxLayout(gb_hk)
        self.chk_hotkeys = QCheckBox("启用自定义语音快捷键（F1 等绑定键）")
        self.chk_hotkeys.toggled.connect(self._on_hotkeys_toggled)
        hl.addWidget(self.chk_hotkeys)
        # 小键盘 1-9 快捷播放（智能：聚焦输入框/打字时自动放行，不打扰输入）
        self.chk_numpad = QCheckBox("小键盘1-9快捷播放（智能：打字/输入框时自动放行）")
        self.chk_numpad.toggled.connect(self._on_numpad_toggled)
        hl.addWidget(self.chk_numpad)
        self.chk_ptt = QCheckBox("自动按住开麦键（播语音时队友才听得到）")
        self.chk_ptt.toggled.connect(self._on_ptt_toggled)
        hl.addWidget(self.chk_ptt)
        r3 = QHBoxLayout()
        r3.addWidget(QLabel("开麦键："))
        self.cmb_pttkey = NoWheelComboBox()
        for k in ['V', 'B', 'C', 'X', 'Z', 'F1', 'F2', 'F3', 'F4', 'F5', '自定义…']:
            self.cmb_pttkey.addItem(k)
        self.cmb_pttkey.currentIndexChanged.connect(self._on_pttkey_changed)
        r3.addWidget(self.cmb_pttkey, 1)
        hl.addLayout(r3)
        tip3 = QLabel("小键盘1-9 默认播放当前语音来源的第1-9条音频；点音频列表可自定义按键")
        tip3.setStyleSheet("color:#7a8099; font-size:11px;")
        hl.addWidget(tip3)
        bl.addWidget(gb_hk)

        # 底部按钮
        bottom = QHBoxLayout()
        btn_refresh = QPushButton("↻ 刷新")
        btn_refresh.clicked.connect(self.refresh_all)
        bottom.addWidget(btn_refresh)
        btn_about = QPushButton("打开角色文件夹")
        btn_about.clicked.connect(self._open_characters_folder)
        bottom.addWidget(btn_about)
        bottom.addStretch(1)
        # 退出按钮（彻底退出桌宠）
        btn_quit = QPushButton("退出桌宠")
        btn_quit.setStyleSheet(
            "QPushButton{background:#4a2c33;border:1px solid #7a3a44;}"
            "QPushButton:hover{background:#5c3540;}")
        btn_quit.clicked.connect(self._quit_app)
        bottom.addWidget(btn_quit)
        root.addLayout(bottom)

    # ---------------- 无边框窗口拖动（按住标题行拖）----------------
    def nativeEvent(self, eventType, message):
        """无边框窗口边缘/四角缩放：拦截 WM_NCHITTEST，命中边缘时返回对应
        HTLEFT/HTRIGHT/... 让系统接管拖动缩放（光标自动变为 resize 形状）
        注意：绝不能返回 super().nativeEvent(...) 的 C 级值（PyQt6 下会访问违规崩溃），
        未处理消息一律返回 (False, 0)"""
        try:
            if eventType and bytes(eventType) == b"windows_generic_MSG":
                msg = wintypes.MSG.from_address(int(message))
                if msg.message == _WM_NCHITTEST:
                    # lParam = 屏幕坐标（低16位 x、高16位 y，带符号）
                    lp = int(msg.lParam)
                    gx = lp & 0xFFFF
                    if gx & 0x8000:
                        gx -= 0x10000
                    gy = (lp >> 16) & 0xFFFF
                    if gy & 0x8000:
                        gy -= 0x10000
                    pt = self.mapFromGlobal(QPoint(gx, gy))
                    x, y = pt.x(), pt.y()
                    w, h = self.width(), self.height()
                    m = _RESIZE_MARGIN
                    left = x <= m
                    right = x >= w - 1 - m
                    top = y <= m
                    bottom = y >= h - 1 - m
                    if top and left:
                        return True, _HTTOPLEFT
                    if top and right:
                        return True, _HTTOPRIGHT
                    if bottom and left:
                        return True, _HTBOTTOMLEFT
                    if bottom and right:
                        return True, _HTBOTTOMRIGHT
                    if left:
                        return True, _HTLEFT
                    if right:
                        return True, _HTRIGHT
                    if top:
                        return True, _HTTOP
                    if bottom:
                        return True, _HTBOTTOM
        except Exception:
            pass
        return False, 0

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and e.position().y() < 40:
            self._drag_offset = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._drag_offset is not None and e.buttons() & Qt.MouseButton.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag_offset)
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        self._drag_offset = None
        super().mouseReleaseEvent(e)

    # ---------------- 拖放导入（傻瓜化）----------------
    def _handle_drop(self, urls):
        """处理拖入的路径：音频→当前语音来源；png/gif/文件夹→新角色"""
        if not urls:
            return
        pet = self._current_pet()
        if pet is None:
            return
        # 支持的扩展名（跟随 pet.py 的 AUDIO_EXTS / IMAGE_EXTS，保证列表一致）
        audio_ex = getattr(pet_mod, 'AUDIO_EXTS', ('.mp3', '.wav', '.ogg', '.flac', '.m4a'))
        image_ex = getattr(pet_mod, 'IMAGE_EXTS', ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp'))
        gif_ex = ('.gif', '.webp') if '.webp' in image_ex else ('.gif',)
        # 分类
        audios = []
        char_dirs = []   # 文件夹（含 image.png/gif → 当角色目录）
        char_imgs = []   # 单张 png/gif 图 → 以文件名建角色
        for u in urls:
            path = u
            if not os.path.exists(path):
                continue
            low = path.lower()
            if os.path.isdir(path):
                # 文件夹：若含角色图则作为新角色；否则当作音频来源（收目录内全部音频）
                has_img = os.path.exists(os.path.join(path, 'image.png')) or \
                    any(f.lower().endswith(gif_ex) or f.lower().endswith(image_ex)
                        for f in os.listdir(path) if os.path.isfile(os.path.join(path, f)))
                if has_img:
                    char_dirs.append(path)
                else:
                    # 不含角色图 → 把目录内音频全部导入
                    for f in os.listdir(path):
                        fp = os.path.join(path, f)
                        if os.path.isfile(fp) and f.lower().endswith(audio_ex):
                            audios.append(fp)
            elif low.endswith(audio_ex):
                audios.append(path)
            elif low.endswith(image_ex):
                char_imgs.append(path)
        imported_any = False
        # 1) 导入音频到当前语音来源
        if audios:
            d = self._current_audio_dir()
            if d:
                os.makedirs(d, exist_ok=True)
                for f in audios:
                    name = os.path.basename(f)
                    dst = os.path.join(d, name)
                    i = 1
                    base, ext = os.path.splitext(name)
                    while os.path.exists(dst):
                        dst = os.path.join(d, "%s(%d)%s" % (base, i, ext))
                        i += 1
                    try:
                        shutil.copy2(f, dst)
                        imported_any = True
                    except Exception as e:
                        print('drop audio fail:', f, e)
                self._refresh_audio_list()
                self._watch_current_dir()
        # 2) 导入文件夹作为新角色
        if char_dirs:
            chars = os.path.join(pet.base_dir(), 'assets', 'characters')
            os.makedirs(chars, exist_ok=True)
            for d in char_dirs:
                name = os.path.basename(d)
                dst = os.path.join(chars, name)
                try:
                    if os.path.exists(dst):
                        shutil.rmtree(dst)
                    shutil.copytree(d, dst)
                    imported_any = True
                except Exception as e:
                    print('drop char dir fail:', d, e)
        # 3) 导入单张角色图
        if char_imgs:
            chars = os.path.join(pet.base_dir(), 'assets', 'characters')
            os.makedirs(chars, exist_ok=True)
            for img in char_imgs:
                name = os.path.splitext(os.path.basename(img))[0]
                ext = os.path.splitext(img)[1].lower()
                dst = os.path.join(chars, name)
                os.makedirs(dst, exist_ok=True)
                # 角色图统一叫 image.png（动图 .gif/.webp 保留原名以便动画播放）
                if ext in ('.gif', '.webp'):
                    target = os.path.join(dst, os.path.basename(img))
                else:
                    target = os.path.join(dst, 'image.png')
                try:
                    if os.path.exists(target):
                        os.remove(target)
                    shutil.copy2(img, target)
                    imported_any = True
                except Exception as e:
                    print('drop char img fail:', img, e)
        if imported_any:
            if hasattr(pet, 'rescan_roles'):
                pet.rescan_roles()
            self.refresh_all()
            self._watch_current_dir()

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            self._drop_armed = True
            self.update()
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dragLeaveEvent(self, e):
        self._drop_armed = False
        self.update()
        super().dragLeaveEvent(e)

    def dropEvent(self, e):
        self._drop_armed = False
        self.update()
        if e.mimeData().hasUrls():
            urls = [u.toLocalFile() for u in e.mimeData().urls()]
            self._handle_drop(urls)
            e.acceptProposedAction()

    def paintEvent(self, e):
        # 保持默认绘制 + 拖入高亮边框
        super().paintEvent(e)
        if self._drop_armed:
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            pen = QPen(QColor(255, 215, 110, 230), 2, Qt.PenStyle.DashLine)
            p.setPen(pen)
            p.setBrush(QColor(255, 215, 110, 26))
            p.drawRoundedRect(self.rect().adjusted(3, 3, -3, -3), 10, 10)
            p.end()

    def _quit_app(self):
        """退出整个桌宠程序"""
        pet = self._current_pet()
        try:
            if pet is not None and hasattr(pet, 'close'):
                pet.close()  # 触发 closeEvent（注销热键）
        except Exception:
            pass
        QApplication.quit()

    # ---------------- 数据填充 ----------------
    def _current_pet(self):
        return self._pet

    def _character_dir(self):
        pet = self._current_pet()
        if pet is not None:
            return pet.chars_dir() if hasattr(pet, 'chars_dir') else None
        return None

    def refresh_all(self):
        """刷新全部模块显示（角色/音频/设备/热键状态）"""
        pet = self._current_pet()
        if pet is None:
            return
        # 大小滑块/输入框同步
        sz = int(getattr(pet, '_pet_size', 200) or 200)
        self.sld_size.blockSignals(True)
        self.sld_size.setValue(sz)
        self.sld_size.blockSignals(False)
        self.spn_size.blockSignals(True)
        self.spn_size.setValue(sz)
        self.spn_size.blockSignals(False)
        # 角色
        self._refresh_role_list()
        # 音频
        self._refresh_audio_list()
        # 设备
        self._refresh_devices()
        # 热键
        self.chk_hotkeys.blockSignals(True)
        self.chk_hotkeys.setChecked(bool(getattr(pet, '_hotkeys_enabled', True)))
        self.chk_hotkeys.blockSignals(False)
        self.chk_numpad.blockSignals(True)
        self.chk_numpad.setChecked(bool(getattr(pet, '_numpad_enabled', False)))
        self.chk_numpad.blockSignals(False)
        self.chk_ptt.blockSignals(True)
        self.chk_ptt.setChecked(bool(getattr(pet, '_auto_ptt', False)))
        self.chk_ptt.blockSignals(False)
        self.cmb_pttkey.blockSignals(True)
        cur_ptt = getattr(pet, '_ptt_key_name', 'V') or 'V'
        idx = self.cmb_pttkey.findText(cur_ptt)
        if idx >= 0:
            self.cmb_pttkey.setCurrentIndex(idx)
        self.cmb_pttkey.blockSignals(False)

        # AI 模块
        ai = {}
        ai_mgr = getattr(pet, 'ai', None)
        if ai_mgr is not None and hasattr(ai_mgr, 'cfg'):
            ai = ai_mgr.cfg() or {}
        self.chk_ai_enabled.blockSignals(True)
        self.chk_ai_enabled.setChecked(bool(ai.get('enabled', False)))
        self.chk_ai_enabled.blockSignals(False)
        ai_on = bool(ai.get('enabled', False))
        self.chk_ai_tts.blockSignals(True)
        self.chk_ai_tts.setChecked(ai_on and bool(ai.get('tts_enabled', True)))
        self.chk_ai_tts.setEnabled(ai_on)   # AI 关 → TTS 置灰不可开
        self.chk_ai_tts.blockSignals(False)
        self.ed_ai_base.setText(ai.get('base_url', ''))
        self.ed_ai_key.setText(ai.get('api_key', ''))
        # 模型下拉：优先存值、否则保留当前
        cur_model = (ai.get('model') or '')
        if cur_model and self.cmb_ai_model.findText(cur_model) < 0:
            self.cmb_ai_model.blockSignals(True)
            self.cmb_ai_model.insertItem(0, cur_model)
            self.cmb_ai_model.setCurrentIndex(0)
            self.cmb_ai_model.blockSignals(False)
        else:
            self.cmb_ai_model.blockSignals(True)
            self.cmb_ai_model.setCurrentText(cur_model if cur_model else "")
            self.cmb_ai_model.blockSignals(False)
        # 朗读服务（唯一引擎=填地址的自定义语音 API）
        self.ed_tts_api_base.blockSignals(True)
        self.ed_tts_api_base.setText(ai.get('tts_api_base', ''))
        self.ed_tts_api_base.blockSignals(False)
        self.ed_tts_api_key.blockSignals(True)
        self.ed_tts_api_key.setText(ai.get('tts_api_key', ''))
        self.ed_tts_api_key.blockSignals(False)
        self.ed_tts_api_model.blockSignals(True)
        self.ed_tts_api_model.setText(ai.get('tts_api_model', ''))
        self.ed_tts_api_model.blockSignals(False)
        self.ed_tts_api_voice.blockSignals(True)
        self.ed_tts_api_voice.setText(ai.get('tts_api_voice', ''))
        self.ed_tts_api_voice.blockSignals(False)
        self.ed_tts_api_ref.blockSignals(True)
        self.ed_tts_api_ref.setText(ai.get('tts_api_ref', ''))
        self.ed_tts_api_ref.blockSignals(False)
        self.ed_tts_api_ref_text.blockSignals(True)
        self.ed_tts_api_ref_text.setText(ai.get('tts_api_ref_text', ''))
        self.ed_tts_api_ref_text.blockSignals(False)
        self.ed_tts_api_instr.blockSignals(True)
        self.ed_tts_api_instr.setText(ai.get('tts_api_instruction', ''))
        self.ed_tts_api_instr.blockSignals(False)
        # 系统提示词 / TTS 提示词
        sp = ai.get('system_prompt', '')
        sp_def = ai_mgr.default_system_prompt() if ai_mgr is not None else ''
        self.ed_ai_sysprompt.blockSignals(True)
        self.ed_ai_sysprompt.setPlainText(sp if sp else sp_def)
        self.ed_ai_sysprompt.blockSignals(False)
        # 单价（进=未命中 / 缓存=命中 / 出）
        try:
            pin = ai.get('ai_price_in', 0.14)
            pout = ai.get('ai_price_out', 0.28)
            pcache = ai.get('ai_price_cache', 0.0028)
            self.ed_ai_price_in.setText(str(pin if pin not in (None, '') else 0.14))
            self.ed_ai_price_out.setText(str(pout if pout not in (None, '') else 0.28))
            self.ed_ai_price_cache.setText(str(pcache if pcache not in (None, '') else 0.0028))
        except Exception:
            self.ed_ai_price_in.setText('0.14')
            self.ed_ai_price_out.setText('0.28')
            self.ed_ai_price_cache.setText('0.0028')
        # 峰谷自动计价开关回填 + 当前状态
        try:
            peak_on = bool(ai.get('peak_pricing', True))
            self.chk_ai_peak.blockSignals(True)
            self.chk_ai_peak.setChecked(peak_on)
            self.chk_ai_peak.blockSignals(False)
            self._refresh_peak_state()
        except Exception:
            pass
        tp = ai.get('tts_prompt', '')
        tp_def = ai_mgr.default_tts_prompt() if ai_mgr is not None else ''
        self.ed_ai_ttsprompt.blockSignals(True)
        self.ed_ai_ttsprompt.setPlainText(tp if tp else tp_def)
        self.ed_ai_ttsprompt.blockSignals(False)
        # 朗读音量
        try:
            vol = max(0, min(300, int(ai.get('tts_volume', 100) or 100)))
        except Exception:
            vol = 100
        self.sld_tts_volume.blockSignals(True)
        self.sld_tts_volume.setValue(vol)
        self.sld_tts_volume.blockSignals(False)
        self.spn_tts_volume.blockSignals(True)
        self.spn_tts_volume.setValue(vol)
        self.spn_tts_volume.blockSignals(False)
        self._ai_status("")

    def _refresh_audio_list(self):
        pet = self._current_pet()
        if pet is None:
            return
        mod = pet_mod  # pet 模块引用（注入）
        # 同步语音来源下拉框显示
        cur_src = getattr(pet, '_voice_source', 'role') or 'role'
        si = self.cmb_voice_src.findData(cur_src)
        if si >= 0 and self.cmb_voice_src.currentIndex() != si:
            self.cmb_voice_src.blockSignals(True)
            self.cmb_voice_src.setCurrentIndex(si)
            self.cmb_voice_src.blockSignals(False)
        self.audio_list.blockSignals(True)
        self.audio_list.clear()
        audios = []
        # 跟随语音来源：通用 or 角色
        if hasattr(pet, 'current_audio_list'):
            audios = pet.current_audio_list() or []
        elif mod is not None and hasattr(mod, 'list_role_audio'):
            audios = mod.list_role_audio(pet.role) or []
        hotkeys = getattr(pet, '_audio_hotkeys', {}) or {}
        for label, path in audios:
            akey = pet._audio_key_for_path(path) if hasattr(pet, '_audio_key_for_path') \
                else pet._audio_key(pet.role, path)
            bound = hotkeys.get(akey, '')
            # 键位显示在左边：[F1] 早上好（纯文本，不用富文本——QListWidget 不渲染 span）
            if bound:
                txt = "[%s]  %s" % (bound, label)
            else:
                txt = label
            item = QListWidgetItem()
            item.setText(txt)
            # 用 UserRole 存原始 label 便于展示与识别
            item.setData(Qt.ItemDataRole.UserRole, path)
            item.setData(Qt.ItemDataRole.UserRole + 1, akey)
            item.setData(Qt.ItemDataRole.UserRole + 2, label)
            # 若绑定了键 → 金色显示键位部分（QListWidgetItem 无法分段着色，整体用金色加粗提示已绑定）
            if bound:
                item.setForeground(QColor('#ffd76e'))
            self.audio_list.addItem(item)
        self.audio_list.blockSignals(False)

    def _on_voice_src_changed(self, idx):
        """切换语音来源（角色专属 ↔ 通用语音）"""
        pet = self._current_pet()
        if pet is None:
            return
        src = self.cmb_voice_src.itemData(idx) or 'role'
        if hasattr(pet, 'set_voice_source'):
            pet.set_voice_source(src)
        # 刷新音频列表 + 监视目录（每个来源的音频/绑定各自独立）
        self._refresh_audio_list()
        self._watch_current_dir()

    def _refresh_devices(self):
        """刷新设备下拉框"""
        pet = self._current_pet()
        if pet is None:
            return
        devs = []
        if hasattr(pet, 'list_output_devices'):
            devs = pet.list_output_devices() or []
        names = [n for n, _ in devs]
        cur_bind = getattr(pet, '_bind_device', '') or ''
        cur_self = getattr(pet, '_self_device', '') or ''
        for cmb, cur in ((self.cmb_bind, cur_bind), (self.cmb_self, cur_self)):
            cmb.blockSignals(True)
            cmb.clear()
            if cmb is self.cmb_bind:
                cmb.addItem("不绑定（系统默认）", '')
            else:
                cmb.addItem("不听（关闭监听）", '')
            for n in names:
                cmb.addItem(n, n)
            i = cmb.findData(cur)
            cmb.setCurrentIndex(i if i >= 0 else 0)
            cmb.blockSignals(False)

    # ---------------- 角色操作 ----------------
    def _on_size_changed(self, val):
        """大小滑块/输入框：实时调桌宠尺寸；两个控件互相联动（防循环）"""
        pet = self._current_pet()
        if pet is None:
            return
        # 同步另一个控件（blockSignals 防来回触发死循环）
        s = self.sender()
        if s is self.sld_size:
            self.spn_size.blockSignals(True)
            self.spn_size.setValue(val)
            self.spn_size.blockSignals(False)
        elif s is self.spn_size:
            self.sld_size.blockSignals(True)
            self.sld_size.setValue(val)
            self.sld_size.blockSignals(False)
        if hasattr(pet, 'set_pet_size'):
            pet.set_pet_size(val)

    def _on_role_clicked(self, item):
        # 单击=切换
        role = item.text().replace("  ←当前", "")
        if role and role != getattr(self._current_pet(), 'role', None):
            self._switch_role(role)

    def _switch_role(self, role):
        pet = self._current_pet()
        if pet is None:
            return
        self.sig_role_changed.emit(role)
        if hasattr(pet, 'switch_role'):
            pet.switch_role(role)
        self.refresh_all()
        self._watch_current_dir()  # 切换后重设监视目录（新角色的音频文件夹）

    def _import_character(self):
        """导入新形象：可多选 png/jpg/gif/webp 等图片（每张=新角色），或选含角色图的文件夹"""
        pet = self._current_pet()
        if pet is None:
            return
        image_ex = getattr(pet_mod, 'IMAGE_EXTS', ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp'))
        pat = ' '.join('*%s' % e for e in image_ex)
        # 让用户选择：文件 或 文件夹（用 file dialog 允许目录 + 图片文件）
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择角色图片（%s，每张=新角色）\n也可整个含角色图的文件夹拖入窗口" % ' / '.join(image_ex),
            "", "图片 (%s)" % pat)
        if not files:
            return
        chars = os.path.join(pet.base_dir(), 'assets', 'characters')
        os.makedirs(chars, exist_ok=True)
        imported = []
        for img in files:
            name = os.path.splitext(os.path.basename(img))[0]
            ext = os.path.splitext(img)[1].lower()
            if not name:
                continue
            dst = os.path.join(chars, name)
            try:
                if os.path.isdir(dst):
                    shutil.rmtree(dst)  # 覆盖同名的旧角色目录
                os.makedirs(dst, exist_ok=True)
                # 动图（.gif/.webp）保留原名（QMovie 播放动画）；其它统一存 image.png
                if ext in ('.gif', '.webp'):
                    target = os.path.join(dst, os.path.basename(img))
                else:
                    target = os.path.join(dst, 'image.png')
                if os.path.exists(target):
                    os.remove(target)
                shutil.copy2(img, target)
                imported.append(name)
            except Exception as e:
                QMessageBox.critical(self, "错误", "导入 %s 失败: %s" % (img, e))
        if imported:
            if hasattr(pet, 'rescan_roles'):
                pet.rescan_roles()
            self.refresh_all()
            self.sig_character_added.emit(','.join(imported))
            self._watch_current_dir()

    def _delete_selected_role(self):
        pet = self._current_pet()
        item = self.role_list.currentItem()
        if pet is None or item is None:
            return
        role = item.text().replace("  ←当前", "")
        if role == getattr(pet, 'role', None):
            QMessageBox.information(self, "提示", "不能删除正在使用的角色，请先切换到其它角色。")
            return
        chars = os.path.join(pet.base_dir(), 'assets', 'characters')
        dst = os.path.join(chars, role)
        ret = QMessageBox.question(self, "确认", "删除角色「%s」？（会删除其文件夹）" % role)
        if ret == QMessageBox.StandardButton.Yes:
            if hasattr(pet, 'remove_role'):
                ok, msg = pet.remove_role(role)
                if not ok:
                    QMessageBox.critical(self, "错误", msg)
                    return
            else:
                # 兼容旧实现
                try:
                    shutil.rmtree(dst)
                except Exception as e:
                    QMessageBox.critical(self, "错误", "删除失败: %s" % e)
                    return
            if hasattr(pet, 'rescan_roles'):
                pet.rescan_roles()
            self.refresh_all()

    # ---------------- 音频操作 ----------------
    def _on_audio_clicked(self, item):
        """单击音频 = 仅选中（不做任何修改），提示可绑定"""
        label = item.data(Qt.ItemDataRole.UserRole + 2) or item.text()
        # 选中当前项，更新提示
        self.lbl_bind_tip.setText(
            "已选中「%s」：可点「▶ 试听」或「🔑 绑定/修改快捷键」" % label)
        self.lbl_bind_tip.setStyleSheet("color:#8fa3c8; font-size:11px;")

    def _on_bind_mode_toggled(self, on):
        """点「🔑 绑定/修改快捷键」进入录制模式"""
        pet = self._current_pet()
        if not on:
            return
        item = self.audio_list.currentItem()
        if item is None:
            QMessageBox.information(self, "提示", "请先在列表中选中一条语音，再点绑定快捷键。")
            self.btn_bind.setChecked(False)
            return
        akey = item.data(Qt.ItemDataRole.UserRole + 1)
        if not akey:
            self.btn_bind.setChecked(False)
            return
        self.btn_bind.setText("按一个键绑定…（Esc 取消）")
        self.lbl_bind_tip.setText("请按一个键绑定到「%s」，按 Esc 取消" % item.text())
        if hasattr(pet, '_begin_capture_hotkey'):
            pet._begin_capture_hotkey(akey)
            # 录制完成/取消后由 pet 回调 _on_capture_done 恢复按钮
        else:
            self.btn_bind.setChecked(False)
            self.btn_bind.setText("🔑 绑定/修改快捷键")

    def on_capture_finished(self):
        """pet 录制结束（成功或取消）后调用：恢复按钮状态并刷新列表"""
        self.btn_bind.setChecked(False)
        self.btn_bind.setText("🔑 绑定/修改快捷键")
        self.lbl_bind_tip.setText(
            "💡 选中语音后可试听/绑定快捷键（可绑 F1…或小键盘数字1-9）；每个语音来源可各绑一套，互不干扰")
        self.lbl_bind_tip.setStyleSheet("color:#7a8099; font-size:11px;")
        self._refresh_audio_list()  # 立即刷新显示绑定的快捷键

    def _current_audio_dir(self):
        """当前语音来源对应的资源目录（导入/监视用）"""
        pet = self._current_pet()
        if pet is None:
            return None
        if getattr(pet, '_voice_source', 'role') == 'common':
            if hasattr(pet, 'base_dir'):
                return os.path.join(pet.base_dir(), 'assets', 'common_voice')
            return None
        return os.path.join(pet.base_dir(), 'assets', 'characters', pet.role)

    def _import_audio(self):
        pet = self._current_pet()
        if pet is None:
            return
        audio_ex = getattr(pet, 'AUDIO_EXTS', ('.mp3', '.wav', '.ogg', '.flac', '.m4a'))
        pat = ' '.join('*%s' % e for e in audio_ex)
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择音频（支持：%s）" % ' / '.join(audio_ex),
            "", "音频文件 (%s)" % pat)
        if not files:
            return
        role_dir = self._current_audio_dir() or os.path.join(
            pet.base_dir(), 'assets', 'characters', pet.role)
        os.makedirs(role_dir, exist_ok=True)
        for f in files:
            try:
                name = os.path.basename(f)
                dst = os.path.join(role_dir, name)
                # 重名自动加序号
                i = 1
                base, ext = os.path.splitext(name)
                while os.path.exists(dst):
                    dst = os.path.join(role_dir, "%s(%d)%s" % (base, i, ext))
                    i += 1
                shutil.copy2(f, dst)
            except Exception as e:
                QMessageBox.critical(self, "错误", "导入 %s 失败: %s" % (f, e))
        self._refresh_audio_list()

    def _delete_selected_audio(self):
        pet = self._current_pet()
        item = self.audio_list.currentItem()
        if pet is None or item is None:
            return
        path = item.data(Qt.ItemDataRole.UserRole)
        if not path:
            return
        ret = QMessageBox.question(self, "确认", "删除该音频文件？\n%s" % os.path.basename(path))
        if ret == QMessageBox.StandardButton.Yes:
            if hasattr(pet, 'remove_audio_file'):
                ok, msg = pet.remove_audio_file(path)
                if not ok:
                    QMessageBox.critical(self, "错误", msg)
                    return
            else:
                # 兼容：直接删除（无清理绑定能力）
                try:
                    os.remove(path)
                except Exception as e:
                    QMessageBox.critical(self, "错误", "删除失败: %s" % e)
                    return
            self._refresh_audio_list()

    def _preview_selected_audio(self):
        pet = self._current_pet()
        item = self.audio_list.currentItem()
        if pet is None or item is None:
            return
        path = item.data(Qt.ItemDataRole.UserRole)
        if path and hasattr(pet, 'play_audio'):
            # 试听：强制不开 auto_ptt（避免试听时在聊天窗口注入开麦键字母）
            pet.play_audio(path, ptt_override=False)

    # ---------------- 设备 / 热键操作 ----------------
    def _on_bind_changed(self, idx):
        name = self.cmb_bind.itemData(idx) or ''
        pet = self._current_pet()
        if pet is not None and hasattr(pet, 'set_bind_device'):
            pet.set_bind_device(name)
            self.sig_bind_device.emit(name)

    def _on_self_changed(self, idx):
        name = self.cmb_self.itemData(idx) or ''
        pet = self._current_pet()
        if pet is not None and hasattr(pet, 'set_self_device'):
            pet.set_self_device(name)
            self.sig_self_device.emit(name)

    def _on_hotkeys_toggled(self, on):
        pet = self._current_pet()
        if pet is not None and hasattr(pet, 'set_hotkeys_enabled'):
            pet.set_hotkeys_enabled(on)
            self.sig_hotkeys_enabled.emit(on)

    def _on_numpad_toggled(self, on):
        pet = self._current_pet()
        if pet is not None and hasattr(pet, 'set_numpad_enabled'):
            if on:
                # 开启前提示会占用小键盘输入（仅第一次）
                pass
            pet.set_numpad_enabled(on)

    def sync_numpad_checkbox(self, on):
        """外部（桌宠绑定数字键后自动开）同步勾选状态"""
        self.chk_numpad.blockSignals(True)
        self.chk_numpad.setChecked(bool(on))
        self.chk_numpad.blockSignals(False)

    def _on_ptt_toggled(self, on):
        pet = self._current_pet()
        if pet is not None and hasattr(pet, 'set_auto_ptt'):
            pet.set_auto_ptt(on)
            self.sig_auto_ptt.emit(on)

    def _on_pttkey_changed(self, idx):
        txt = self.cmb_pttkey.itemText(idx)
        pet = self._current_pet()
        if pet is None:
            return
        if txt == '自定义…':
            if hasattr(pet, '_begin_capture_ptt'):
                pet._begin_capture_ptt()
            # 恢复显示当前键
            self.cmb_pttkey.blockSignals(True)
            cur = getattr(pet, '_ptt_key_name', 'V') or 'V'
            i2 = self.cmb_pttkey.findText(cur)
            self.cmb_pttkey.setCurrentIndex(i2 if i2 >= 0 else 0)
            self.cmb_pttkey.blockSignals(False)
            return
        if pet is not None and hasattr(pet, 'set_ptt_key'):
            pet.set_ptt_key(txt)
            self.sig_ptt_key.emit(txt)

    # ---------------- 工具 ----------------
    # ---------------- 自动刷新（目录监视）----------------
    def _watch_current_dir(self):
        """监听当前语音来源目录（角色目录或通用语音目录），文件变化自动刷新音频列表"""
        pet = self._current_pet()
        if pet is None:
            return
        try:
            d = self._current_audio_dir()
            if d and os.path.isdir(d):
                watched = self._fs_watcher.directories()
                if d not in watched:
                    self._fs_watcher.removePaths(watched)  # 只监听当前来源目录
                    self._fs_watcher.addPath(d)
        except Exception:
            pass

    def _on_dir_changed(self, path):
        """目录变化（导入/删除音频等）→ 防抖后自动刷新"""
        self._auto_refresh_timer.start()

    def _delayed_refresh(self):
        self._refresh_audio_list()
        # 若角色目录集变化（新增角色文件夹）→ 也刷角色
        pet = self._current_pet()
        if pet is not None and hasattr(pet, 'rescan_roles'):
            old = list(getattr(pet, 'roles', []))
            pet.rescan_roles()
            if list(getattr(pet, 'roles', [])) != old:
                self._refresh_role_list()
        self._watch_current_dir()

    def _refresh_role_list(self):
        pet = self._current_pet()
        if pet is None:
            return
        self.role_list.blockSignals(True)
        self.role_list.clear()
        for r in getattr(pet, 'roles', []) or []:
            item = QListWidgetItem(r)
            if r == getattr(pet, 'role', None):
                item.setText(r + "  ←当前")
                item.setForeground(QColor('#ffd76e'))
            self.role_list.addItem(item)
        self.role_list.blockSignals(False)
        self.lbl_cur_role.setText(getattr(pet, 'role', '-') or '-')

    def _open_characters_folder(self):
        """打开当前语音来源所在目录（通用语音→common_voice；角色→角色目录）"""
        pet = self._current_pet()
        if pet is None:
            return
        d = self._current_audio_dir()
        if not d:
            d = os.path.join(pet.base_dir(), 'assets', 'characters')
        os.makedirs(d, exist_ok=True)
        os.startfile(d)

    def toast_hotkey_bound(self, audio_key, key_name):
        """录制完成回调：更新列表显示"""
        self._refresh_audio_list()
        pet = self._current_pet()
        if pet is not None:
            pet._toast_text = "已绑定: %s → %s" % (os.path.basename(audio_key) if audio_key else "开麦键", key_name)
            pet.update()

    # ---------------- AI 功能 ----------------
    def _ai_status(self, msg, color="#8fa3c8"):
        self.lbl_ai_status.setText(msg if msg else "💡 填好服务器地址与密钥后会自动检测可用模型，选一个即可。")
        self.lbl_ai_status.setStyleSheet("color:%s; font-size:11px;" % color)

    def _toggle_ai_page(self):
        """点「AI」折叠头：展开/收起 AI 配置区"""
        self.ai_expanded = not self.ai_expanded
        self.ai_box.setVisible(self.ai_expanded)
        self.btn_ai_head.setChecked(self.ai_expanded)
        if self.ai_expanded:
            # 展开后刷新并尝试自动检测
            self.refresh_all()
            QTimer.singleShot(150, self._ai_auto_fetch)

    def _ai_tts_can_enable(self, pet=None):
        """TTS 朗读是否可开：必须 AI 对话已开启"""
        if pet is None:
            pet = self._current_pet()
        if pet is None or not hasattr(pet, 'ai'):
            return False
        return bool(pet.ai.cfg().get('enabled', False))

    def _ai_apply_enabled(self, on):
        pet = self._current_pet()
        if pet is not None and hasattr(pet, 'ai'):
            pet.ai.set_enabled(on)
            # TTS 依附 AI：AI 关 → TTS 强制关 + 置灰；AI 开 → TTS 恢复可用
            self.chk_ai_tts.blockSignals(True)
            if not on:
                pet.ai.set_tts_enabled(False)
                self.chk_ai_tts.setChecked(False)
            self.chk_ai_tts.setEnabled(on)
            self.chk_ai_tts.blockSignals(False)
        self._ai_status("AI 对话已" + ("开启" if on else "关闭") +
                        ("" if on else "（朗读已随之关闭）"), "#7ae0a3" if on else "#7a8099")

    def _ai_apply_tts(self, on):
        pet = self._current_pet()
        # 依附：AI 未开则不允许开朗读
        if on and not self._ai_tts_can_enable(pet):
            self.chk_ai_tts.blockSignals(True)
            self.chk_ai_tts.setChecked(False)
            self.chk_ai_tts.blockSignals(False)
            self._ai_status("请先开启「启用 AI 对话」，才能开启朗读", "#e06c75")
            return
        if pet is not None and hasattr(pet, 'ai'):
            pet.ai.set_tts_enabled(bool(on))
        self._ai_status("朗读 AI 回复已" + ("开启" if on else "关闭"),
                        "#7ae0a3" if on else "#7a8099")

    def _ai_apply_tts_api(self):
        """保存自定义 TTS API 服务配置（含克隆三件套）"""
        pet = self._current_pet()
        if pet is None or not hasattr(pet, 'ai'):
            return
        pet.ai.set_tts_api(
            self.ed_tts_api_base.text().strip(),
            self.ed_tts_api_key.text().strip(),
            self.ed_tts_api_model.text().strip(),
            self.ed_tts_api_voice.text().strip(),
            self.ed_tts_api_ref.text().strip(),
            self.ed_tts_api_ref_text.text().strip(),
            self.ed_tts_api_instr.text().strip())

    def _ai_pick_tts_ref(self):
        """浏览选择克隆参考音频，并把同目录同名 .txt 自动填进参考转录"""
        f, _ = QFileDialog.getOpenFileName(
            self, "选择克隆参考音频",
            self.ed_tts_api_ref.text().strip() or "",
            "音频文件 (*.wav *.mp3 *.flac *.ogg *.m4a);;所有文件 (*.*)")
        if not f:
            return
        self.ed_tts_api_ref.setText(f)
        # 尝试自动填参考转录：同目录同名 .txt / 去掉扩展名的 .txt
        cand = []
        for ext in ('.txt',):
            cand.append(os.path.splitext(f)[0] + ext)
        d = os.path.dirname(f)
        base = os.path.splitext(os.path.basename(f))[0]
        cand.append(os.path.join(d, base + '.txt'))
        cand.append(os.path.join(d, base + '.transcript.txt'))
        for c in cand:
            if os.path.isfile(c):
                try:
                    with open(c, 'r', encoding='utf-8-sig') as fh:
                        txt = fh.read().strip()
                    if txt:
                        self.ed_tts_api_ref_text.setText(txt)
                        break
                except Exception:
                    continue
        self._ai_apply_tts_api()

    def _ai_test_tts_api(self):
        """测试自定义 TTS API：合成一小段验证配置正确性"""
        pet = self._current_pet()
        if pet is None or not hasattr(pet, 'ai'):
            return
        base = self.ed_tts_api_base.text().strip()
        key = self.ed_tts_api_key.text().strip()
        model = self.ed_tts_api_model.text().strip()
        voice = self.ed_tts_api_voice.text().strip() or 'alloy'
        if not base or not key or not model:
            self.lbl_tts_api_status.setText("⚠ 请先填服务地址 / 密钥 / 模型")
            self.lbl_tts_api_status.setStyleSheet("color:#e06c75; font-size:11px;")
            return
        self.lbl_tts_api_status.setText("测试中…")
        self.lbl_tts_api_status.setStyleSheet("color:#8fa3c8; font-size:11px;")
        pet.ai.test_tts_api(
            base, key, model, voice, None,
            ref=self.ed_tts_api_ref.text().strip(),
            ref_text=self.ed_tts_api_ref_text.text().strip(),
            instruction=self.ed_tts_api_instr.text().strip())

    def _ai_apply_model(self, text):
        pet = self._current_pet()
        if pet is not None and hasattr(pet, 'ai') and text:
            pet.ai.set_server(pet.ai.cfg().get('base_url', ''),
                              pet.ai.cfg().get('api_key', ''),
                              text)
            # 模型若被识别出官方单价，仅当当前单价仍是「默认价之一」时联动填入
            # （用户已手动改过则不覆盖）
            try:
                sp = pet.ai.suggested_prices(text)
                if sp is not None and self._prices_are_default():
                    self.ed_ai_price_in.setText(self._fmt_price(sp[0]))
                    self.ed_ai_price_out.setText(self._fmt_price(sp[1]))
                    self.ed_ai_price_cache.setText(self._fmt_price(sp[2]))
                    pet.ai.set_prices(sp[0], sp[1], sp[2])
            except Exception:
                pass

    @staticmethod
    def _fmt_price(v):
        """单价格式化：去掉多余的 0，保留必要精度（如 0.14 / 0.0028 / 0.435）"""
        s = ('%.6f' % float(v)).rstrip('0').rstrip('.')
        return s if s else '0'

    def _prices_are_default(self):
        """当前面板三单价是否仍为某套默认价（flash 或 pro）。True 表示未人工改动。"""
        try:
            pin = float(self.ed_ai_price_in.text().strip() or 0)
            pout = float(self.ed_ai_price_out.text().strip() or 0)
            pc = float(self.ed_ai_price_cache.text().strip() or 0)
        except Exception:
            return True
        known = {(0.14, 0.28, 0.0028), (0.435, 0.87, 0.003625)}
        return (round(pin, 6), round(pout, 6), round(pc, 6)) in known

    def _ai_apply_sysprompt(self):
        pet = self._current_pet()
        if pet is not None and hasattr(pet, 'ai'):
            pet.ai.set_system_prompt(self.ed_ai_sysprompt.toPlainText())

    def _ai_apply_prices(self):
        pet = self._current_pet()
        if pet is not None and hasattr(pet, 'ai'):
            try:
                pin = float(self.ed_ai_price_in.text().strip() or 0.14)
            except Exception:
                pin = 0.14
            try:
                pout = float(self.ed_ai_price_out.text().strip() or 0.28)
            except Exception:
                pout = 0.28
            try:
                pcache = float(self.ed_ai_price_cache.text().strip() or 0.0028)
            except Exception:
                pcache = 0.0028
            pet.ai.set_prices(pin, pout, pcache)

    def _ai_apply_peak(self, on):
        """峰谷自动计价开关 → 存 ai.peak_pricing（默认开启）"""
        pet = self._current_pet()
        if pet is not None and hasattr(pet, 'ai'):
            from ai_chat import _save_ai_cfg as _sv
            _sv(peak_pricing=bool(on))
            self._refresh_peak_state()

    def _refresh_peak_state(self):
        """更新峰谷状态小字：当前高峰(全价) / 空闲(半价)"""
        try:
            pet = self._current_pet()
            ai = pet.ai if pet is not None and hasattr(pet, 'ai') else None
            if ai is None or not getattr(self, 'lbl_peak_state', None):
                return
            peak_on = bool(ai.cfg().get('peak_pricing', True))
            if not peak_on:
                self.lbl_peak_state.setText("峰谷计价已关闭（按所填单价计）")
                return
            peak = ai.is_peak_time()
            in_, out, cache = ai.raw_prices()
            if peak:
                self.lbl_peak_state.setText(
                    "当前：高峰时段（北京时间周一至五 9-12/14-18）→ 全价 %.4g/%.4g/%.4g $/M"
                    % (in_, out, cache))
            else:
                self.lbl_peak_state.setText(
                    "当前：空闲时段 → 自动半价 %.4g/%.4g/%.4g $/M"
                    % (in_ / 2, out / 2, cache / 2))
        except Exception:
            pass

    def _ai_apply_ttsprompt(self):
        pet = self._current_pet()
        if pet is not None and hasattr(pet, 'ai'):
            pet.ai.set_tts_prompt(self.ed_ai_ttsprompt.toPlainText())

    def _ai_apply_tts_volume(self, val):
        """朗读音量滑块/数字：双向同步 + 实时应用到 AI 播放器"""
        sender = self.sender()
        # 从触发方取值，另一控件只显示同步（blockSignals 防循环）
        if sender is self.spn_tts_volume:
            target = self.spn_tts_volume.value()
        else:
            target = self.sld_tts_volume.value()
        if self.sld_tts_volume.value() != target:
            self.sld_tts_volume.blockSignals(True)
            self.sld_tts_volume.setValue(target)
            self.sld_tts_volume.blockSignals(False)
        if self.spn_tts_volume.value() != target:
            self.spn_tts_volume.blockSignals(True)
            self.spn_tts_volume.setValue(target)
            self.spn_tts_volume.blockSignals(False)
        pet = self._current_pet()
        if pet is not None and hasattr(pet, 'ai'):
            pet.ai.set_tts_volume(target)

    # ---------------- 本地 TTS 服务控制 ----------------
    def _refresh_tts_svc_state(self, async_ok=True):
        """探测本地 TTS 服务状态并刷新 UI（状态灯 + 按钮启停）。
        async_ok=True（默认）时在后台线程探测，避免服务未启动时
        socket 超时（约 2s）卡住主线程（打开设置面板会明显变慢）；
        探测完成后回主线程更新控件。async_ok=False 用于已在线程里的场景。"""
        if not hasattr(self, 'lbl_tts_svc_state'):
            return
        try:
            ai_mod = sys.modules.get('ai_chat')
            if ai_mod is None:
                return
        except Exception:
            return

        def _probe():
            try:
                ok, msg = ai_mod.tts_service_health()
                # 回到主线程刷新 UI（跨线程 emit 由 Qt 排队，安全）
                self._probe_result(ok, msg)
            except Exception:
                self._probe_result(False, '')

        if async_ok:
            threading.Thread(target=_probe, daemon=True).start()
        else:
            try:
                ok, msg = ai_mod.tts_service_health()
            except Exception:
                ok, msg = False, ''
            self._probe_result(ok, msg)

    def _probe_result(self, ok, msg):
        """主线程：把 TTS 服务探测结果刷到 UI"""
        try:
            if not hasattr(self, 'lbl_tts_svc_state'):
                return
            if ok:
                self.lbl_tts_svc_state.setText("● %s" % msg)
                self.lbl_tts_svc_state.setStyleSheet("color:#7ae0a3; font-size:11px;")
                self.btn_tts_svc_start.setEnabled(False)
                self.btn_tts_svc_stop.setEnabled(True)
            else:
                self.lbl_tts_svc_state.setText("○ 本地 TTS 服务未启动")
                self.lbl_tts_svc_state.setStyleSheet("color:#e0a35c; font-size:11px;")
                self.btn_tts_svc_start.setEnabled(True)
                self.btn_tts_svc_stop.setEnabled(False)
        except Exception:
            pass

    def _ai_tts_svc_start(self):
        ai_mod = sys.modules.get('ai_chat')
        if ai_mod is None:
            return
        self.lbl_tts_svc_state.setText("正在启动…（模型加载约 20-60 秒，稍候）")
        self.lbl_tts_svc_state.setStyleSheet("color:#8fa3c8; font-size:11px;")
        self.btn_tts_svc_start.setEnabled(False)
        self.btn_tts_svc_stop.setEnabled(False)

        def _run():
            try:
                ai_mod.tts_service_start()
            except Exception:
                pass
            # 回到主线程刷新状态
            QTimer.singleShot(0, self._refresh_tts_svc_state)

        threading.Thread(target=_run, daemon=True).start()

    def _ai_tts_svc_stop(self):
        ai_mod = sys.modules.get('ai_chat')
        if ai_mod is None:
            return
        self.lbl_tts_svc_state.setText("正在停止…")
        self.btn_tts_svc_start.setEnabled(False)
        self.btn_tts_svc_stop.setEnabled(False)

        def _run():
            try:
                ai_mod.tts_service_stop()
            except Exception:
                pass
            QTimer.singleShot(0, self._refresh_tts_svc_state)

        threading.Thread(target=_run, daemon=True).start()

    def _ai_save(self):
        pet = self._current_pet()
        if pet is None or not hasattr(pet, 'ai'):
            self._ai_status("AI 模块不可用", "#e06c75")
            return
        pet.ai.set_server(self.ed_ai_base.text().strip(),
                          self.ed_ai_key.text().strip(),
                          self.cmb_ai_model.currentText().strip())
        self._ai_status("已保存 ✅（服务器/密钥/模型）", "#7ae0a3")

    def _ai_auto_fetch(self):
        """填好服务器+密钥后自动检测模型列表，填入下拉框
        （结果由 models_fetched 信号回主线程 _on_models_fetched 处理）"""
        pet = self._current_pet()
        if pet is None or not hasattr(pet, 'ai'):
            return
        base_url = self.ed_ai_base.text().strip() or "https://api.deepseek.com/v1"
        api_key = self.ed_ai_key.text().strip()
        if not api_key:
            self._ai_status("填好服务器地址与 API 密钥后会自动检测模型", "#7a8099")
            return
        self._ai_status("正在检测可用模型…", "#8fa3c8")
        # 诊断日志：记录实际发出的请求参数（key 只记前 8 位）
        try:
            if pet_mod is not None and hasattr(pet_mod, '_dbg'):
                pet_mod._dbg('[AI刷新模型] base=%s key前缀=%s...' % (base_url, api_key[:8]))
        except Exception:
            pass
        pet.ai.fetch_models(base_url, api_key, None)

    def _ai_test(self):
        pet = self._current_pet()
        if pet is None or not hasattr(pet, 'ai'):
            return
        base_url = self.ed_ai_base.text().strip() or "https://api.deepseek.com/v1"
        api_key = self.ed_ai_key.text().strip()
        model = self.cmb_ai_model.currentText().strip() or "deepseek-chat"
        if not api_key:
            self._ai_status("请先填 API 密钥", "#e06c75")
            return
        self._ai_status("测试中…", "#8fa3c8")
        pet.ai.test_connection(base_url, api_key, model, None)


# 供 pet.py import 使用
def create_panel(pet_window):
    p = SettingsPanel(pet_window)
    return p
