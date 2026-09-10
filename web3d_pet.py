"""web3d_pet.py —— 自研 3D 桌宠窗口（three-vrm + QtWebEngine，完全脱离 Mate-Engine）

特点（相对 Mate-Engine 的优势）：
  * 无重启热切换模型（<1 秒）
  * 尺寸/位置/透明度完全由 Python 控制
  * 表情 / 眨眼 / 视线跟随 / 说话气泡 / 悬停对话 全部原生
  * 离线运行（three.js + three-vrm 已 vendor 到本地）
  * 与 pet.py 同进程，不需要 socket 桥、不需要外部游戏进程

用法（独立体验）：
    python web3d_pet.py                 # 启动 3D 桌宠
    python web3d_pet.py --model aldina  # 指定模型

作为库使用（给 pet.py 集成）：
    from web3d_pet import Web3DPetWindow
    w = Web3DPetWindow(model="michelle"); w.show()
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

# --- QtWebEngine 必须在 QApplication 前设置 ---
# ★ 帧率（用户要求"顶格 120 帧"）：Chromium 默认有三重节流会把桌宠压到
#   几帧甚至 1 帧，必须全部关掉：
#     1) 刷新率锁      → --disable-frame-rate-limit --disable-gpu-vsync
#     2) 窗口被判定"被遮挡/后台"→ 停止渲染（透明置顶小窗极易触发）
#                      → --disable-backgrounding-occluded-windows
#                        --disable-renderer-backgrounding
#     3) 定时器节流    → --disable-background-timer-throttling
#   第 2 条是实测的关键：不加时页面 rAF 只有 ~0.8 帧/秒。
os.environ.setdefault(
    "QTWEBENGINE_CHROMIUM_FLAGS",
    "--ignore-gpu-blocklist --enable-gpu-rasterization --enable-unsafe-swiftshader "
    "--disable-frame-rate-limit --disable-gpu-vsync "
    "--disable-backgrounding-occluded-windows --disable-renderer-backgrounding "
    "--disable-background-timer-throttling",
)

from PyQt6.QtCore import QObject, QPoint, QTimer, Qt, QUrl, pyqtSignal, pyqtSlot, QEvent
from PyQt6.QtGui import QAction, QColor, QCursor, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import (QApplication, QMenu, QSystemTrayIcon, QWidget)
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PyQt6.QtWebEngineWidgets import QWebEngineView

HERE = Path(__file__).resolve().parent
WEB_DIR = HERE / "web3d"
MODEL_DIR = WEB_DIR / "models"

# 可发现的模型源目录
# 只保留米雪儿（用户要求）。aldina / Zome / Lazuli 原先从这里自动同步进来，
# 已移除；如需恢复某个角色，把它的目录加回本列表即可。
MODEL_SOURCES = [
    Path(r"C:\Users\mier\Desktop\deepseek work\mate-engine\michelle_model"),
    MODEL_DIR,
]

# 白名单：只有这些模型会被同步到 web3d/models（防止源目录里其他 VRM 被带进来）
MODEL_ALLOWLIST = {"michelle", "michelle_expr", "michelle_phys"}

# ---------------------------------------------------------------- 2D 角色 ↔ 3D 模型
# 设置面板「形象角色」右键菜单据此判断：该 2D 角色有没有对应的 3D 形象。
#   键 = 2D 角色名（取路径末段，如 '欧泊/米雪儿' → '米雪儿'）
#   值 = web3d/models 下的模型文件名（不含 .vrm）
# 以后给别的角色做 3D 模型，在这里加一行即可，右键菜单会自动出现「切换 3D 形象」。
#
# 为什么是 michelle_phys 而不是 michelle_expr：
#   michelle_phys 是从 PMX 重新转换出来的，同时带【VRMC_springBone 物理】
#   （39 条链 / 209 joint / 19 collider，由 Blender 从 MMD 刚体自动生成）
#   和【984 个 morph target】。头发和裙摆会自己摆动，不再需要自研物理。
#   michelle_expr 是旧的纯表情版（无物理），保留作为后备。
ROLE_TO_3D = {
    '米雪儿': 'michelle_phys',
}


def role_3d_model(role_name: str) -> str | None:
    """2D 角色名 → 对应 3D 模型名（没有则 None）。

    role_name 可以是 '欧泊/米雪儿' 这种带阵营的全路径，也可以是纯 '米雪儿'。
    """
    if not role_name:
        return None
    leaf = str(role_name).replace('\\', '/').rsplit('/', 1)[-1].strip()
    name = ROLE_TO_3D.get(leaf)
    if not name:
        return None
    # 再确认模型文件真的存在（避免映射写了但模型被删）
    if not (MODEL_DIR / (name + '.vrm')).exists():
        return None
    return name


def roles_with_3d() -> dict[str, str]:
    """返回 {2D 角色名: 3D 模型名}，只包含模型确实存在的。"""
    out = {}
    for leaf, model in ROLE_TO_3D.items():
        if (MODEL_DIR / (model + '.vrm')).exists():
            out[leaf] = model
    return out

DEFAULT_SIZE = (280, 380)


# ---------------------------------------------------------------- 模型管理
def sync_models() -> dict[str, Path]:
    """把可用的 .vrm 汇总到 web3d/models/（硬链接省空间，失败则复制）。

    只同步 MODEL_ALLOWLIST 里的模型（目前=米雪儿），避免源目录里的
    其他角色被自动带进来。

    返回 {显示名: 路径}
    """
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    found: dict[str, Path] = {}
    for src in MODEL_SOURCES:
        if not src.exists():
            continue
        for p in sorted(src.glob("*.vrm")):
            if MODEL_ALLOWLIST and p.stem not in MODEL_ALLOWLIST:
                continue
            dst = MODEL_DIR / p.name
            if not dst.exists():
                try:
                    os.link(p, dst)
                except OSError:
                    try:
                        shutil.copy2(p, dst)
                    except Exception as e:
                        print(f"[3d] 无法同步 {p.name}: {e}")
                        continue
            found[p.stem] = dst
    return found


# ---------------------------------------------------------------- Python↔JS 桥
class Bridge(QObject):
    """暴露给 JS 的对象（window.pyBridge）"""

    modelLoaded = pyqtSignal(str)
    ready = pyqtSignal(str)

    def __init__(self, win: "Web3DPetWindow"):
        super().__init__(win)
        self.win = win

    @pyqtSlot(int, int)
    def dragWindow(self, dx: int, dy: int):
        """（已废弃）JS 报告拖动增量 → 移动窗口。

        ⚠ 现在窗口移动由 Python 的鼠标轮询负责（见 _mouse_tick），这里【不再】
        移动窗口，否则 JS 和 Python 会各移一次 → 角色跑得比鼠标快一倍。
        仅保留用于日志诊断。
        """
        self.win._js_drag_moved = True

    @pyqtSlot(bool)
    def setTopmost(self, on: bool):
        self.win.set_topmost(bool(on))

    @pyqtSlot(str)
    def log(self, msg: str):
        print(f"[js] {msg}")

    @pyqtSlot(str)
    def onModelLoaded(self, name: str):
        print(f"[3d] 模型已加载: {name}")
        self.win._model_name = name.replace('.vrm', '')
        self.win.modelLoaded.emit(name)

    @pyqtSlot(str)
    def onReady(self, name: str):
        print(f"[3d] 就绪: {name}")
        self.win._ready = True
        # 拉一次真实表情列表（VRM 的 morphTargetBinds 名），供菜单使用
        self.win._refresh_expressions()
        # 接入命中检测（拖动时判断有没有点到角色）
        self.win._install_hit_test()
        self.ready.emit(name)

    @pyqtSlot(str)
    def onExpressions(self, json_list: str):
        """JS 回报当前模型的表情名列表"""
        try:
            names = json.loads(json_list)
            if isinstance(names, list):
                self.win._expressions = [str(n) for n in names]
                self.win._expr_printed = len(self.win._expressions)
                print(f"[3d] 表情 {len(self.win._expressions)} 个")
        except Exception as e:
            print(f"[3d] 表情列表解析失败: {e}")


# ---------------------------------------------------------------- 主窗口
class Web3DPetWindow(QWidget):
    """纯 3D 桌宠窗口（透明、无边框、置顶、可拖动）"""

    modelLoaded = pyqtSignal(str)
    hoverChanged = pyqtSignal(bool)      # 鼠标进出角色 → 通知 pet.py 展开/收起输入栏
    clicked = pyqtSignal()               # 单击角色（非拖动）→ 可触发说话/互动

    def __init__(self, model: str = "michelle", size: tuple[int, int] = DEFAULT_SIZE,
                 parent=None):
        super().__init__(parent)
        self._ready = False
        self._model_name = model
        self._expressions: list[str] = []   # 当前模型可用表情（VRM 标准名）
        self._topmost = True
        self._models: dict[str, Path] = {}
        self._drag_pos: QPoint | None = None
        self._hovering = False
        self._dragging = False
        self._moved_during_drag = False
        self._drag_anchor = None        # 上一次鼠标屏幕坐标（按增量拖动）
        self._drag_accum = 0.0
        self._hit_cache_fn = None       # 页面注入的命中检测（点角色才算拖动）
        self._mouse_timer = None        # 全局鼠标轮询定时器
        self._js_drag_moved = False     # 诊断：JS 是否也在拖（应为 False）
        self.overlay_sync = None        # pet.py 注入：拖动时即时同步三横浮层

        self.setWindowTitle("3D 桌宠")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.resize(*size)
        # ★ 悬停/拖动都要靠鼠标事件。WebEngineView 的子 widget 默认把事件吃掉，
        #   所以在窗口和 view 上都开 MouseTracking，并装事件过滤器统一处理拖动。
        self.setMouseTracking(True)

        # --- 模型同步 ---
        self._models = sync_models()
        if not self._models:
            print("[3d] 警告：未找到任何 .vrm 模型")

        # --- 视图 ---
        self.view = QWebEngineView(self)
        self.page = WebPage(self)
        self.view.setPage(self.page)
        self.view.setGeometry(0, 0, *size)
        self.view.setMouseTracking(True)
        # 注意：这里不再装 eventFilter —— QtWebEngine 的鼠标事件由 Chromium
        # 直接消费，过滤器收不到，拖动改由 _mouse_tick 全局轮询处理。
        self.page.setBackgroundColor(QColor(0, 0, 0, 0))
        self._apply_settings()

        # --- QWebChannel 桥 ---
        self.channel = QWebChannel(self)
        self.bridge = Bridge(self)
        self.channel.registerObject("py", self.bridge)
        self.page.setWebChannel(self.channel)

        # --- 载入页面 ---
        # 直接用本地 HTTP 服务（file:// 下 ES module importmap + VRM fetch 会被 CORS 拦）
        # 只加载一次，避免二次 load 打断 VRM 初始化 / 桥连接
        self._http_port = 0
        try:
            from web3d_server import serve
            port = serve(WEB_DIR)
            self._http_port = port
            url = QUrl(f"http://127.0.0.1:{port}/pet_viewer.html")
            print(f"[3d] loading http://127.0.0.1:{port}/pet_viewer.html")
        except Exception as e:
            print(f"[3d] HTTP 启动失败，回退 file://: {e}")
            url = QUrl.fromLocalFile(str(WEB_DIR / "pet_viewer.html"))
        self.page.load(url)

        # --- 托盘（右键菜单） ---
        self._build_tray()

        # ★ 启动全局鼠标轮询（拖动/悬停都靠它；事件过滤器在 QtWebEngine 下收不到）
        self._install_mouse_poll()

    def closeEvent(self, ev):
        """关窗前停掉轮询定时器，避免残留定时器继续访问已销毁窗口。"""
        try:
            if self._mouse_timer is not None:
                self._mouse_timer.stop()
                self._mouse_timer = None
        except Exception:
            pass
        super().closeEvent(ev)

    # ---------------- 基础 ----------------
    def _apply_settings(self):
        s = self.view.settings()
        for attr in ("WebGLEnabled", "Accelerated2dCanvasEnabled",
                     "LocalContentCanAccessFileUrls", "LocalContentCanAccessRemoteUrls",
                     "ShowScrollBars", "JavascriptEnabled"):
            try:
                a = getattr(QWebEngineSettings.WebAttribute, attr)
                s.setAttribute(a, attr != "ShowScrollBars")
            except Exception:
                pass

    def _start_http_and_load(self):
        """用本地 HTTP 服务加载（避免 file:// 的 CORS/模块限制）"""
        try:
            from web3d_server import serve
            port = serve(WEB_DIR)
            self._http_port = port
            self.page.load(QUrl(f"http://127.0.0.1:{port}/pet_viewer.html"))
            print(f"[3d] http://127.0.0.1:{port}/pet_viewer.html")
        except Exception as e:
            print(f"[3d] HTTP 启动失败，回退 file://: {e}")

    def set_topmost(self, on: bool):
        self._topmost = bool(on)
        flags = self.windowFlags()
        if on:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        else:
            flags &= ~Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.show()

    # ---------------- 与 JS 通信 ----------------
    def js(self, code: str, cb=None):
        if cb is None:
            self.page.runJavaScript(code)
        else:
            self.page.runJavaScript(code, cb)

    def set_model(self, name: str) -> bool:
        """热切换模型（<1 秒，不重启）"""
        # 支持 stem 或文件名
        p = self._models.get(name)
        if p is None:
            for k, v in self._models.items():
                if name.lower() in k.lower() or name.lower() in v.name.lower():
                    p = v
                    break
        if p is None:
            print(f"[3d] 未找到模型: {name}（可用: {list(self._models)}）")
            return False
        self.js(f"window.loadModel('./models/{p.name}')")
        self._model_name = p.stem
        self._expressions = []          # 旧模型的表情作废
        # 新模型加载完后再拉一次表情列表
        QTimer.singleShot(2500, self._refresh_expressions)
        print(f"[3d] 切换模型 -> {p.name}")
        return True

    def models(self) -> list[str]:
        return list(self._models)

    def expression(self, name: str, weight: float = 1.0):
        self.js(f"window.setExpression({json.dumps(name)}, {float(weight)})")

    def reset_expression(self):
        self.js("window.setExpression('neutral', 0)")

    def expressions(self) -> list[str]:
        """当前模型可用的表情名（由 JS 在模型加载后回报）"""
        return list(self._expressions)

    def _refresh_expressions(self):
        """向 JS 拉取当前模型的表情名列表"""
        def _cb(v):
            try:
                names = json.loads(v) if isinstance(v, str) else (v or [])
                if isinstance(names, list) and names:
                    self._expressions = [str(n) for n in names]
                    # 只在数量变化时打印（避免每次切模型/刷新都刷一长串）
                    if getattr(self, '_expr_printed', None) != len(self._expressions):
                        self._expr_printed = len(self._expressions)
                        print(f"[3d] 表情 {len(self._expressions)} 个")
            except Exception as e:
                print(f"[3d] 表情列表解析失败: {e}")
        try:
            self.page.runJavaScript(
                "JSON.stringify(window.listExpressions ? window.listExpressions() : [])", _cb)
        except Exception as e:
            print(f"[3d] 拉取表情失败: {e}")

    def say(self, text: str, ms: int = 3500):
        self.js(f"window.say({json.dumps(text, ensure_ascii=False)}, {int(ms)})")

    def set_blink(self, on: bool):
        self.js(f"window.setBlinkEnabled({str(bool(on)).lower()})")

    def _install_hit_test(self):
        """把页面的「是否点在角色上」检测接进 Python。

        Python 的鼠标轮询用它判断鼠标位置：
          · 点在角色本体 → 可以拖动窗口
          · 点在窗口的透明空白处 → 不抢事件（让下层窗口/桌面正常响应）
        """
        def _cb(v):
            if callable(v):
                self._hit_cache_fn = v
                print("[3d] 命中检测已接入")
        try:
            self.page.runJavaScript("window.__hitTest", _cb)
        except Exception as e:
            print(f"[3d] 接入命中检测失败: {e}")

    # ---------------- 拖动 / 悬停（全局鼠标轮询）----------------
    #
    # ★ 为什么不用 Qt 事件过滤器（曾经的实现，已证明无效）：
    #   QWebEngineView 内部渲染控件在 Windows 上是独立原生 HWND，Chromium 直接
    #   消费鼠标消息，事件根本不上报到 Qt 的 QWidget 事件系统 —— 无论把
    #   eventFilter 装在 view、page 还是 QApplication 上，都收不到 MouseButtonPress。
    #   这正是用户反馈"3D桌宠无法拖动"的根因。
    #
    # ★ 现在的方案：QTimer 每 16ms 读一次全局鼠标状态
    #   （QCursor.pos + GetAsyncKeyState），自己判断按下/移动/松开。
    #   GetAsyncKeyState 读的是系统级按键状态，不依赖任何窗口收不收事件，
    #   在原生/非原生控件上一律有效，是这类"穿透式"桌宠的标准做法。
    #
    # ★ 拖动按屏幕坐标增量移动（而非绝对定位），避免 DPI 缩放取整累积误差。

    def _install_mouse_poll(self):
        """启动全局鼠标轮询（幂等）。"""
        if getattr(self, '_mouse_timer', None) is not None:
            return
        t = QTimer(self)
        t.setInterval(16)               # ~60Hz，肉眼跟手
        t.timeout.connect(self._mouse_tick)
        t.start()
        self._mouse_timer = t
        print('[3d] 全局鼠标轮询已启动')

    @staticmethod
    def _lbutton_down() -> bool:
        """系统级读取鼠标左键是否按下（Windows）。"""
        try:
            import ctypes
            return bool(ctypes.windll.user32.GetAsyncKeyState(0x01) & 0x8000)
        except Exception:
            # 非 Windows：退化用 Qt 的按键状态（够用，只是灵敏度略低）
            try:
                return bool(QApplication.mouseButtons() & Qt.MouseButton.LeftButton)
            except Exception:
                return False

    @staticmethod
    def _cursor_pos() -> QPoint:
        """当前鼠标屏幕坐标。

        单独抽成一个方法是为了让自动化测试能替换它（真实鼠标位置无法注入），
        这样测试驱动的是【真实的 _mouse_tick 逻辑】，而不是复制一份。
        """
        return QCursor.pos()

    def _mouse_tick(self):
        """每 16ms 一次：处理按下 → 拖动 → 松开；并维护悬停状态。"""
        try:
            gp = self._cursor_pos()
            down = self._lbutton_down()

            # ---- 1) 按下：点在角色身上才开始拖 ----
            if down and not self._dragging:
                if self.isVisible() and self.frameGeometry().contains(gp):
                    if self._hit_character(gp):
                        self._dragging = True
                        self._moved_during_drag = False
                        self._drag_accum = 0.0
                        self._drag_anchor = gp
                        self._notify_drag_visual(True)   # ★ 立刻做「被拎起来」反应
                return

            # ---- 2) 拖动中：按增量移动窗口 ----
            if down and self._dragging:
                anchor = getattr(self, '_drag_anchor', gp)
                dx, dy = gp.x() - anchor.x(), gp.y() - anchor.y()
                if dx or dy:
                    self._drag_anchor = gp
                    self._drag_accum += (dx * dx + dy * dy) ** 0.5
                    if self._drag_accum > 3:        # 超过 3px 才算拖动（防手抖）
                        self._moved_during_drag = True
                    scr = self.screen().availableGeometry() if self.screen() else None
                    nx, ny = self.x() + dx, self.y() + dy
                    if scr is not None:             # 屏幕内夹紧，避免拖丢
                        nx = max(scr.left() - 60, min(nx, scr.right() - 60))
                        ny = max(scr.top(), min(ny, scr.bottom() - 60))
                    self.move(nx, ny)
                    # dx/dy 都传：dy 是垂直通道，"向上猛一提/向下快一放"靠它驱动姿态。
                    # 旧版只传 dx，竖直方向的快慢完全没有输入通道。
                    self._notify_drag_visual(True, dx, dy)   # 拖动幅度 → 惯性倾斜
                    try:
                        cb = getattr(self, 'overlay_sync', None)
                        if callable(cb):
                            cb()                        # 即时同步三横浮层
                    except Exception:
                        pass
                return

            # ---- 3) 松开 ----
            if not down and self._dragging:
                was_drag = self._moved_during_drag
                self._dragging = False
                self._moved_during_drag = False
                self._notify_drag_visual(False)         # 松手回正
                if not was_drag:
                    self.clicked.emit()                 # 没拖动 = 单击 → 说话
                return

            # ---- 4) 空闲：维护悬停状态（用于展开输入栏）----
            inside = self.isVisible() and self.frameGeometry().contains(gp)
            if inside != self._hovering:
                self._hovering = inside
                self.hoverChanged.emit(inside)
        except Exception as e:
            print('[3d] mouse tick err:', e)

    def _hit_character(self, global_pos) -> bool:
        """全局坐标是否命中角色本体（用页面里的射线检测）。

        为什么要判这个：窗口是整块矩形，四角大量透明区域。若不判断，
        点空白处也会把窗口拖走，且会挡住下面其它程序的操作。
        """
        if not self._ready or not callable(self._hit_cache_fn):
            return True          # 模型/检测没就绪时不挑，保证还能拖动窗口
        try:
            p = self.mapFromGlobal(global_pos)
            return bool(self._hit_cache_fn(p.x(), p.y()))
        except Exception:
            return True

    def _notify_drag_visual(self, dragging: bool, dx: int = 0, dy: int = 0):
        """把拖动状态同步给页面：角色做「被拎起来」的反应动作。

        dx/dy 是本次鼠标的水平、垂直位移（像素）。
        垂直通道是后补的：只传 dx 时，向上猛提/向下快放没有任何输入，
        页面里也就做不出"被抽紧/坠一下"的顿挫感。
        """
        try:
            self.js(f"window.setDragging({str(bool(dragging)).lower()}, "
                    f"{int(dx)}, {int(dy)})")
        except Exception:
            pass

    # ---------------- 托盘 ----------------
    def _build_tray(self):
        self.tray = QSystemTrayIcon(self)
        icon = QPixmap(32, 32)
        icon.fill(QColor(0, 0, 0, 0))
        pa = QPainter(icon)
        pa.setRenderHint(QPainter.RenderHint.Antialiasing)
        pa.setBrush(QColor(120, 180, 255))
        pa.setPen(QColor(60, 110, 180))
        pa.drawEllipse(4, 4, 24, 24)
        pa.end()
        self.tray.setIcon(QIcon(icon))
        self.tray.setToolTip("3D 桌宠")
        self.tray.show()

        self.menu = QMenu()
        self.menu.setStyleSheet(
            "QMenu{background:#fff;border:1px solid #ccc;border-radius:8px;padding:6px;}"
            "QMenu::item{padding:6px 22px;border-radius:5px;}"
            "QMenu::item:selected{background:#e8f1ff;}"
        )

        m = self.menu.addMenu("🎭 切换角色（即时，不重启）")
        for name in self.models():
            a = QAction(name, m)
            a.triggered.connect(lambda _, n=name: self.set_model(n))
            m.addAction(a)

        me = self.menu.addMenu("😊 表情")
        for emo in ("happy", "angry", "sad", "relaxed", "surprised", "neutral"):
            a = QAction(emo, me)
            a.triggered.connect(lambda _, n=emo: self.expression(n, 0.9))
            me.addAction(a)

        self.menu.addSeparator()
        a = QAction("💬 说句话", self.menu)
        a.triggered.connect(lambda: self.say("你好呀～"))
        self.menu.addAction(a)

        a = QAction("📌 置顶开关", self.menu)
        a.triggered.connect(lambda: self.set_topmost(not self._topmost))
        self.menu.addAction(a)

        a = QAction("❌ 退出", self.menu)
        a.triggered.connect(QApplication.instance().quit)
        self.menu.addAction(a)

        self.tray.setContextMenu(self.menu)


class WebPage(QWebEnginePage):
    def javaScriptConsoleMessage(self, level, message, line, source):
        tag = "ERR" if level.name.startswith("Error") else "js"
        if tag == "ERR" or "VRM loaded" in message or "init done" in message or "bridge" in message:
            print(f"[{tag}] {message[:220]}")


# ---------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="michelle")
    ap.add_argument("--w", type=int, default=DEFAULT_SIZE[0])
    ap.add_argument("--h", type=int, default=DEFAULT_SIZE[1])
    args = ap.parse_args()

    app = QApplication(sys.argv)
    w = Web3DPetWindow(model=args.model, size=(args.w, args.h))
    w.show()
    print(f"[3d] 窗口已显示 {w.width()}x{w.height()}  可用模型: {w.models()}")

    # 演示：3 秒后打个招呼
    QTimer.singleShot(6000, lambda: w.say("我是米雪儿～"))
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
