# -*- coding: utf-8 -*-
# settings_panel.py —— 卡丘简易桌宠 · 设置面板（独立窗口，替代旧弹出菜单）
# 四大模块：角色管理 / 音频管理 / 播放设备 / 热键设置
# 通过回调与 PetWindow 通信（不反向 import pet，避免循环）
import os
import sys
import shutil

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QPixmap, QIcon, QColor, QPalette
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QListWidget, QListWidgetItem, QFileDialog,
    QMessageBox, QGroupBox, QScrollArea, QFrame, QCheckBox,
    QComboBox, QLineEdit, QSizePolicy,
)

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
QListWidget::item { padding: 6px 8px; border-radius: 6px; }
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
        self.setWindowTitle("卡丘简易桌宠 · 设置")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.resize(560, 640)
        self.setStyleSheet(PANEL_QSS)
        self._build_ui()
        self.refresh_all()

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
        btn_close = QPushButton("✕")
        btn_close.setFixedSize(30, 26)
        btn_close.setStyleSheet("background:#3a3140; border:none; border-radius:6px;")
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
        # 角色列表 + 侧按钮
        row = QHBoxLayout()
        self.role_list = QListWidget()
        self.role_list.setMinimumHeight(90)
        self.role_list.itemClicked.connect(self._on_role_clicked)
        row.addWidget(self.role_list, 1)
        btn_col = QVBoxLayout()
        btn_use = QPushButton("切换")
        btn_use.clicked.connect(lambda: self._switch_selected_role())
        btn_col.addWidget(btn_use)
        btn_import = QPushButton("导入新形象")
        btn_import.clicked.connect(self._import_character)
        btn_col.addWidget(btn_import)
        btn_del = QPushButton("删除角色")
        btn_del.clicked.connect(self._delete_selected_role)
        btn_col.addWidget(btn_del)
        btn_col.addStretch(1)
        row.addLayout(btn_col)
        rl.addLayout(row)
        tip = QLabel("提示：可把含 image.png+音频 的文件夹放到 assets/characters/ 下，点下方\"刷新\"")
        tip.setStyleSheet("color:#7a8099; font-size:11px;")
        rl.addWidget(tip)
        bl.addWidget(gb_role)

        # ---- 模块2：音频管理 ----
        gb_audio = QGroupBox("语音音频（当前角色）")
        al = QVBoxLayout(gb_audio)
        self.audio_list = QListWidget()
        self.audio_list.setMinimumHeight(110)
        self.audio_list.itemClicked.connect(self._on_audio_clicked)
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
        arow.addStretch(1)
        al.addLayout(arow)
        tip2 = QLabel("点击音频 = 绑定/修改快捷键（按 Esc 取消）。已绑定显示在右侧")
        tip2.setStyleSheet("color:#7a8099; font-size:11px;")
        al.addWidget(tip2)
        bl.addWidget(gb_audio)

        # ---- 模块3：播放设备 ----
        gb_dev = QGroupBox("播放设备 / 队友麦克风")
        dl = QVBoxLayout(gb_dev)
        # 绑定麦克风（队友听）
        r1 = QHBoxLayout()
        r1.addWidget(QLabel("绑定麦克风(队友听)："))
        self.cmb_bind = QComboBox()
        self.cmb_bind.currentIndexChanged.connect(self._on_bind_changed)
        r1.addWidget(self.cmb_bind, 1)
        dl.addLayout(r1)
        # 自己监听
        r2 = QHBoxLayout()
        r2.addWidget(QLabel("自己监听(耳机)："))
        self.cmb_self = QComboBox()
        self.cmb_self.currentIndexChanged.connect(self._on_self_changed)
        r2.addWidget(self.cmb_self, 1)
        dl.addLayout(r2)
        bl.addWidget(gb_dev)

        # ---- 模块4：热键 / PTT ----
        gb_hk = QGroupBox("快捷键 / 开麦")
        hl = QVBoxLayout(gb_hk)
        self.chk_hotkeys = QCheckBox("启用快捷键发话（小键盘1-9 及自定义键）")
        self.chk_hotkeys.toggled.connect(self._on_hotkeys_toggled)
        hl.addWidget(self.chk_hotkeys)
        self.chk_ptt = QCheckBox("自动按住开麦键（播语音时队友才听得到）")
        self.chk_ptt.toggled.connect(self._on_ptt_toggled)
        hl.addWidget(self.chk_ptt)
        r3 = QHBoxLayout()
        r3.addWidget(QLabel("开麦键："))
        self.cmb_pttkey = QComboBox()
        for k in ['V', 'B', 'C', 'X', 'Z', 'F1', 'F2', 'F3', 'F4', 'F5', '自定义…']:
            self.cmb_pttkey.addItem(k)
        self.cmb_pttkey.currentIndexChanged.connect(self._on_pttkey_changed)
        r3.addWidget(self.cmb_pttkey, 1)
        hl.addLayout(r3)
        tip3 = QLabel("小键盘1-9 默认播放当前角色第1-9条音频；点音频列表可自定义按键")
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
        root.addLayout(bottom)

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
        # 角色
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
        # 音频
        self._refresh_audio_list()
        # 设备
        self._refresh_devices()
        # 热键
        self.chk_hotkeys.blockSignals(True)
        self.chk_hotkeys.setChecked(bool(getattr(pet, '_hotkeys_enabled', True)))
        self.chk_hotkeys.blockSignals(False)
        self.chk_ptt.blockSignals(True)
        self.chk_ptt.setChecked(bool(getattr(pet, '_auto_ptt', False)))
        self.chk_ptt.blockSignals(False)
        self.cmb_pttkey.blockSignals(True)
        cur_ptt = getattr(pet, '_ptt_key_name', 'V') or 'V'
        idx = self.cmb_pttkey.findText(cur_ptt)
        if idx >= 0:
            self.cmb_pttkey.setCurrentIndex(idx)
        self.cmb_pttkey.blockSignals(False)

    def _refresh_audio_list(self):
        pet = self._current_pet()
        if pet is None:
            return
        mod = pet_mod  # pet 模块引用（注入）
        self.audio_list.blockSignals(True)
        self.audio_list.clear()
        audios = []
        if mod is not None and hasattr(mod, 'list_role_audio'):
            audios = mod.list_role_audio(pet.role) or []
        hotkeys = getattr(pet, '_audio_hotkeys', {}) or {}
        for label, path in audios:
            akey = pet._audio_key(pet.role, path)
            bound = hotkeys.get(akey, '')
            txt = label + (("   [%s]" % bound) if bound else "")
            item = QListWidgetItem(txt)
            item.setData(Qt.ItemDataRole.UserRole, path)
            item.setData(Qt.ItemDataRole.UserRole + 1, akey)
            self.audio_list.addItem(item)
        self.audio_list.blockSignals(False)

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
    def _on_role_clicked(self, item):
        # 单击=切换
        role = item.text().replace("  ←当前", "")
        if role and role != getattr(self._current_pet(), 'role', None):
            self._switch_role(role)

    def _switch_selected_role(self):
        item = self.role_list.currentItem()
        if item:
            self._switch_role(item.text().replace("  ←当前", ""))

    def _switch_role(self, role):
        pet = self._current_pet()
        if pet is None:
            return
        self.sig_role_changed.emit(role)
        if hasattr(pet, 'switch_role'):
            pet.switch_role(role)
        self.refresh_all()

    def _import_character(self):
        """导入新形象：选文件夹（含 image.png），复制到 assets/characters/"""
        pet = self._current_pet()
        if pet is None:
            return
        folder = QFileDialog.getExistingDirectory(self, "选择角色文件夹（需含 image.png）")
        if not folder:
            return
        if not os.path.exists(os.path.join(folder, 'image.png')):
            QMessageBox.warning(self, "提示", "所选文件夹里没有 image.png，无法作为角色。")
            return
        name = os.path.basename(folder)
        chars = os.path.join(pet.base_dir(), 'assets', 'characters')
        os.makedirs(chars, exist_ok=True)
        dst = os.path.join(chars, name)
        try:
            if os.path.exists(dst):
                shutil.rmtree(dst)
            shutil.copytree(folder, dst)
        except Exception as e:
            QMessageBox.critical(self, "错误", "导入失败: %s" % e)
            return
        if hasattr(pet, 'rescan_roles'):
            pet.rescan_roles()
        self.refresh_all()
        self.sig_character_added.emit(name)

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
        """点击音频 = 绑定/修改快捷键（与 pet 的录制流程联动）"""
        pet = self._current_pet()
        if pet is None:
            return
        akey = item.data(Qt.ItemDataRole.UserRole + 1)
        if not akey:
            return
        if hasattr(pet, '_begin_capture_hotkey'):
            pet._begin_capture_hotkey(akey)

    def _import_audio(self):
        pet = self._current_pet()
        if pet is None:
            return
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择音频（mp3/wav/ogg/flac）",
            "", "音频文件 (*.mp3 *.wav *.ogg *.flac *.m4a)")
        if not files:
            return
        role_dir = os.path.join(pet.base_dir(), 'assets', 'characters', pet.role)
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
            pet.play_audio(path)

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
    def _open_characters_folder(self):
        pet = self._current_pet()
        if pet is None:
            return
        chars = os.path.join(pet.base_dir(), 'assets', 'characters')
        os.makedirs(chars, exist_ok=True)
        os.startfile(chars)

    def toast_hotkey_bound(self, audio_key, key_name):
        """录制完成回调：更新列表显示"""
        self._refresh_audio_list()
        pet = self._current_pet()
        if pet is not None:
            pet._toast_text = "已绑定: %s → %s" % (os.path.basename(audio_key) if audio_key else "开麦键", key_name)
            pet.update()


# 供 pet.py import 使用
def create_panel(pet_window):
    p = SettingsPanel(pet_window)
    return p
