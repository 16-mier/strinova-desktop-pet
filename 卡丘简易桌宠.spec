# -*- mode: python ; coding: utf-8 -*-
# 卡丘简易桌宠 打包配置
# 瘦身策略：排除多余 Python 包（PIL/pytest/twisted/OpenSSL 等被误收集的）
# 与用不到的 Qt 二进制；QtMultimedia 自带 ffmpeg → 天然支持几乎所有音频格式。
from PyInstaller.utils.hooks import collect_submodules
from PyInstaller.utils.hooks import collect_data_files

# edge_tts 数据文件（voices.json 等）必须随包，否则运行时取不到声音列表
_EDGE_DATA = collect_data_files('edge_tts')

hiddenimports = ['sounddevice', 'soundfile', 'numpy', 'settings_panel', 'ai_chat']
hiddenimports += collect_submodules('sounddevice')
hiddenimports += collect_submodules('soundfile')
hiddenimports += collect_submodules('numpy')
# UIAutomation（智能输入判定兜底）：comtypes + 动态生成的 gen 模块必须一起打包
hiddenimports += ['comtypes', 'comtypes.client', 'comtypes.gen',
                  'comtypes.gen.UIAutomationClient', 'comtypes.stream']
# AI 对话 + TTS：
#  - ai_chat 自带模块
#  - edge_tts：云端 TTS（voices.json 数据必须收，否则运行时取不到声音列表）
#  - comtypes.gen.SpeechLib：本地 SAPI（首个 import 自动生成，需随包）
hiddenimports += ['comtypes.gen.SpeechLib']
# ⚠ HTTPS 必需链（打包后 urllib 发 https 请求缺这些会报
#   "unknown url type: https" / SSL 错误）：ssl/_ssl/urllib.request 显式带上
hiddenimports += ['ssl', '_ssl', 'urllib.request', 'urllib.parse', 'urllib.error',
                  'http.client', 'http.cookiejar', 'email', 'email.mime',
                  'certifi', 'socket']

_EXCLUDES = [
    # Python 层冗余（warn 显示被 numpy/soundfile 钩子误拖入）
    'PIL', 'PIL.Image', 'PIL.ImageDraw', 'PIL.ImageOps', 'PIL.ImageQt',
    'PIL.ImageFilter', 'PIL.ImageMath', 'PIL.ImageSequence',
    'PIL.ImagePalette', 'PIL.TiffImagePlugin', 'PIL.Jpeg2KImagePlugin',
    'pytest', '_pytest', 'pluggy', 'iniconfig', 'nodeenv',
    'twisted', 'OpenSSL', 'cryptography', 'attr',
    # 用不到的 PyQt6 顶层模块（不 import 就不会加载其二进制）
    # ⚠ 不要排除 PyQt6.QtNetwork：Qt6Multimedia.dll 依赖 Qt6Network.dll，
    #   删了 import QtMultimedia 会 "DLL load failed: 找不到指定的模块"
    'PyQt6.QtQml', 'PyQt6.QtWebEngine', 'PyQt6.QtQuick', 'PyQt6.QtQmlModels',
    'PyQt6.QtPdf', 'PyQt6.QtOpenGL', 'PyQt6.QtOpenGLWidgets',
    'PyQt6.QtSql', 'PyQt6.QtTest', 'PyQt6.QtXml', 'PyQt6.QtDBus',
    'PyQt6.QtDesigner', 'PyQt6.QtHelp', 'PyQt6.QtPrintSupport',
    'PyQt6.QtSvg', 'PyQt6.QtSvgWidgets', 'PyQt6.QtWebChannel',
    'PyQt6.QtWebSockets', 'PyQt6.QtMultimediaWidgets', 'PyQt6.QtBluetooth',
    'PyQt6.QtNfc', 'PyQt6.QtPositioning', 'PyQt6.QtSensors',
    'PyQt6.QtSerialPort', 'PyQt6.QtStateMachine', 'PyQt6.QtTextToSpeech',
    # sounddevice/soundfile/numpy 的测试与类型噪音
    'numpy.testing', 'numpy.typing', 'soundfile._tests',
]

a = Analysis(
    ['pet.py'],
    pathex=[],
    binaries=[],
    datas=[('assets', 'assets')] + _EDGE_DATA,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['rthook_fix_urllib_ssl.py'],
    excludes=_EXCLUDES,
    noarchive=False,
    optimize=0,
)
# 瘦身：PyQt6 的 hook 会把 Qt6/bin 下全部 DLL 收进来，这里砍掉用不到的
# （Qt6Pdf 显示 PDF 用不到；opengl32sw 软件渲染备胎桌宠纯 2D raster 用不到；
#  Qt6Svg 界面无 SVG）。
# ⚠ 不要砍 Qt6Network.dll —— Qt6Multimedia.dll 导入表依赖它，砍了 QtMultimedia
#   import 即崩（DLL load failed）。avcodec/avformat/avutil 等 ffmpeg DLL 必须保留。
# ⚠ 不要砍 libcrypto-3/libssl-3 —— Python 的 _ssl.pyd（AI 对话 https 请求）运行时
#   依赖它们！砍了 exe 内 import ssl 失败 → urllib.request 无 HTTPSHandler →
#   AI 请求全部 "unknown url type: https"。这是第二次踩 TLS DLL 的坑（首次是 Qt6Network）。
_BIN_KEEP = ('Qt6Pdf', 'opengl32sw', 'Qt6Quick', 'Qt6Qml',
             'Qt6WebEngine', 'Qt6Sql', 'Qt6Designer', 'Qt6Help', 'Qt6Test',
             'Qt6Bluetooth', 'Qt6Nfc', 'Qt6Positioning', 'Qt6Sensors',
             'Qt6SerialPort', 'Qt6StateMachine', 'Qt6TextToSpeech',
             'Qt6MultimediaWidgets', 'Qt6WebChannel', 'Qt6WebSockets',
             'Qt6Svg')


def _keep_bin(entry):
    # entry 形如 ('PyQt6\\Qt6\\bin\\Qt6Pdf.dll', ...) 或绝对路径；按文件名判断
    import os as _os
    fname = _os.path.basename(entry[0].replace('\\', '/'))
    return not any(fname.startswith(k) or fname == k.lower() or
                   fname.lower().startswith(k.lower()) for k in _BIN_KEEP)


a.binaries = [b for b in a.binaries if _keep_bin(b)]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='卡丘简易桌宠',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['assets/app.ico'],
)
