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
from pathlib import Path

# --- QtWebEngine 必须在 QApplication 前设置 ---
os.environ.setdefault(
    "QTWEBENGINE_CHROMIUM_FLAGS",
    "--ignore-gpu-blocklist --enable-gpu-rasterization --enable-unsafe-swiftshader",
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
MODEL_ALLOWLIST = {"michelle", "michelle_expr"}

# ---------------------------------------------------------------- 2D 角色 ↔ 3D 模型
# 设置面板「形象角色」右键菜单据此判断：该 2D 角色有没有对应的 3D 形象。
#   键 = 2D 角色名（取路径末段，如 '欧泊/米雪儿' → '米雪儿'）
#   值 = web3d/models 下的模型文件名（不含 .vrm）
# 以后给别的角色做 3D 模型，在这里加一行即可，右键菜单会自动出现「切换 3D 形象」。
ROLE_TO_3D = {
    '米雪儿': 'michelle_expr',
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
        """JS 拖拽 → 移动窗口"""
        self.win.move(self.win.x() + int(dx), self.win.y() + int(dy))

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
        self.ready.emit(name)

    @pyqtSlot(str)
    def onExpressions(self, json_list: str):
        """JS 回报当前模型的表情名列表"""
        try:
            names = json.loads(json_list)
            if isinstance(names, list):
                self.win._expressions = [str(n) for n in names]
                print(f"[3d] 表情 {len(self.win._expressions)} 个: {self.win._expressions}")
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
        self.overlay_sync = None            # pet.py 注入：拖动时即时同步三横浮层

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
        self.view.installEventFilter(self)      # 拖动/悬停统一在 eventFilter 处理
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
                    print(f"[3d] 表情 {len(self._expressions)} 个: {self._expressions}")
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

    # ---------------- 拖动 / 悬停（走事件过滤器，覆盖 WebEngineView 子控件）----------------
    #
    # 之前的实现有两个问题（用户反馈「拖动没有任何反应很生硬」）：
    #   ① 只重写了 QWidget 的 mousePressEvent —— 但窗口里铺满 QWebEngineView，
    #      鼠标事件全被 web 视图吃掉，根本传不到 QWidget，所以拖动"没反应"。
    #   ② 拖动时用 e.globalPosition() - 偏移量 直接 move()，每来一个 mousemove
    #      就搬一次窗口，QtWebEngine 渲染跟不上 → 一顿一顿"很生硬"。
    # 现在：装 eventFilter 统一接管；拖动时按屏幕坐标增量移动并在屏幕内夹紧。
    def eventFilter(self, obj, ev):
        try:
            t = ev.type()
            if t == QEvent.Type.MouseButtonPress:
                if ev.button() == Qt.MouseButton.LeftButton:
                    self._drag_pos = ev.globalPosition().toPoint() - self.pos()
                    self._dragging = True
                return False
            if t == QEvent.Type.MouseMove:
                gp = ev.globalPosition().toPoint()
                if self._dragging and self._drag_pos is not None:
                    target = gp - self._drag_pos
                    # 夹紧在屏幕可用区域内（避免拖出屏幕找不回来）
                    scr = self.screen().availableGeometry() if self.screen() else None
                    if scr is not None:
                        target.setX(max(scr.left() - 40, min(target.x(), scr.right() - 40)))
                        target.setY(max(scr.top(), min(target.y(), scr.bottom() - 40)))
                    self.move(target)
                    self._moved_during_drag = True
                    # ★ 拖动时立刻让三横浮层跟上（不等 33ms 轮询）
                    try:
                        ov = getattr(self, 'overlay_sync', None)
                        if callable(ov):
                            ov()
                    except Exception:
                        pass
                # 悬停状态（用于展开输入栏）
                inside = self.rect().contains(ev.position().toPoint())
                if inside != self._hovering:
                    self._hovering = inside
                    self.hoverChanged.emit(inside)
                return False
            if t == QEvent.Type.MouseButtonRelease:
                if ev.button() == Qt.MouseButton.LeftButton:
                    was_drag = getattr(self, '_moved_during_drag', False)
                    self._dragging = False
                    self._drag_pos = None
                    self._moved_during_drag = False
                    if not was_drag:
                        # 没拖动 = 单击 → 通知 pet.py（可扩展为说话/互动）
                        try:
                            self.clicked.emit()
                        except Exception:
                            pass
                return False
            if t == QEvent.Type.Enter:
                if not self._hovering:
                    self._hovering = True
                    self.hoverChanged.emit(True)
            elif t == QEvent.Type.Leave:
                if self._hovering:
                    self._hovering = False
                    self.hoverChanged.emit(False)
        except Exception as e:
            print('[3d] eventFilter err:', e)
        return False

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
