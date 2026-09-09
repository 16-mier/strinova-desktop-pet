# live2d-py 集成指南（本机实测 0.7.0.4 · Python 3.14.7 · PyQt6）

> 2026-09-09 实测：`pip install live2d-py` 成功（连装 pyopengl），C++ 后端日志 `[live2d.v3] Cubism Native, Python 3.14.5` —— **当前环境可直接用，无需降级 Python。**

## 一、安装
```powershell
pip install live2d-py        # 0.7.0.4，自带 cp314 win_amd64 wheel
```

## 二、API 速查（live2d.v3，Cubism 4/5 的 .moc3）
核心类是 `live2d.v3.LAppModel`（在 `live2d/v3/lapp_model.py`，纯 Python 包 C++ Model）：

| 用途 | 方法 |
|---|---|
| 加载 | `LoadModelJson(modelJson路径, maskBufferCount=2)`（内部 CreateRenderer）|
| 画布 | `Resize(w, h)`、`GetCanvasSize()`、`GetCanvasSizePixel()`、`GetPixelsPerUnit()` |
| 每帧 | `Update()`（内部按 dt 推进 motion/物理/呼吸眨眼）→ `Draw()` |
| 动画 | `StartMotion(group, index, priority)`、`StartRandomMotion(group, priority)`、`IsMotionFinished()`、`StopAllMotions()`、`LoadExtraMotion()` |
| 表情 | `SetExpression(id)`、`SetRandomExpression()`、`GetExpressionIds()`、`ResetExpression()` |
| 参数 | `GetParameterCount()`、`GetParamIds()`、`GetParameterValue(id)`、`SetParameterValue(id, v, weight)`、`AddParameterValue(...)` |
| 变换 | `SetScale(s)`、`SetOffsetX/Y(x)`、`Rotate(deg)`、`Drag(x, y)`（鼠标跟随时用）|
| 部件 | `SetPartOpacity(id, v)`、`SetPartMultiplyColor(...)` |
| 点击 | `HitTest(id, x, y)`、`HitPart(x, y)` |
| 眼睛/呼吸 | `SetAutoBlinkEnable(True)`、`SetAutoBreathEnable(True)` |

## 三、最小集成骨架（PyQt6 透明桌宠）
```python
import sys
from PyQt6.QtWidgets import QApplication, QOpenGLWidget
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QSurfaceFormat

import live2d.v3 as live2d

class L2DWidget(QOpenGLWidget):
    def __init__(self, model_path, parent=None):
        super().__init__(parent)
        fmt = QSurfaceFormat()
        fmt.setAlphaBufferSize(8)          # 关键：透明通道
        self.setFormat(fmt)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._model_path = model_path
        self._model = None
        self._initialized = False
        self._scale = 1.0

    def initializeGL(self):
        # 1) 每窗口一次：初始化 live2d + 创建 OpenGL 上下文
        live2d.init()                       # live2d.v3.init() 指向内置 CubismCore
        self._model = live2d.LAppModel()
        self._model.LoadModelJson(self._model_path)
        self._model.Resize(self.width(), self.height())
        self._initialized = True

    def paintGL(self):
        # 2) 每帧：清透明 → 更新 → 绘制
        import OpenGL.GL as gl
        gl.glClearColor(0, 0, 0, 0)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT)
        if self._initialized:
            self._model.Update()
            self._model.Draw()

    def resizeGL(self, w, h):
        if self._initialized:
            self._model.Resize(w, h)

# 使用：放到透明无边框窗口里当角色显示层；QTimer(16ms) 触发 update()
# 交互：鼠标移动 → model.Drag(归一化 x, y) + SetOffsetX/Y；点击 → HitTest('Head', x, y) → StartMotion('TapHead', ...)
```

## 四、接入现有桌宠的改造点（pet.py）
1. 角色目录识别 `.moc3`（新增资源类型）：`assets/characters/<阵营>/<角色>/model.model3.json`（或 moc3 目录）
2. `PetWindow` 加一层 QOpenGLWidget 子窗口作为 Live2D 渲染区，替代/叠加 QPainter 画 pixmap 的分支
3. 尺寸/按压/翻转动画：用 model.SetScale/SetOffsetX + Drag 实现，替代 _scale_x 变换
4. 打包：PyInstaller 需 collect live2d 及其 dll、hidden-import `live2d.v3._v3cpp`（包自带说明）

## 五、模型来源（需 .moc3 + .model3.json + 贴图）
- Live2D 官方示例模型（Nijima / Haru / Mao 等，官方 GitHub live2d-widget 或 SDK samples 附）
- itch.io 搜 live2d model / vtuber model（部分免费，多为 Cubism 格式）
- Booth.pm 搜 live2d / 立ち絵（免费品不少）
- 卡拉彼丘：**无现成官方/同人 .moc3**，需自建或另寻
