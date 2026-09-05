# dsh-desktop-pet 开发日志（DESKTOP PET DEVELOPMENT LOG）

> 桌宠：**独立 Win11 桌面桌宠**（透明置顶浮窗，点按播音，角色可扩展）
> 工程：`C:\Users\mier\Desktop\deepseek work\dsh-desktop-pet`
> 技术栈：**Python 3.14 + PyQt6**（per-pixel alpha 完美透明，打包成单文件 exe）
> 创建：2026-09-04

## 0. 日志约定（强制，与 dsh-pet 插件一致）
- 每做任何改动，必须同步更新本文件的「变更记录」章节（`### YYYY-MM-DD（简述）`，中文）
- 记录要点：功能改动（需求→实现机制→新增什么）、Bug 修复（现象→根因→修复）、踩坑（附解决命令）、涉及文件绝对路径、验证结果 ✅/❌
- 这是后续 Agent（含新会话）接手修改的第一参考资料

## 1. 这是什么

把原 dsh-pet（DSH Web 右下角鲸鱼挂件）**魔改成一个独立的 Windows 桌面桌宠**：
- 透明置顶小浮窗，显示角色形象（星绘 / 白墨，可切换，可扩展）
- **点按播音**：星绘按时间早/午/晚问候；白墨播「冲刺」；按下有"压扁弹回"动画
- 可拖动、贴边、置顶、托盘；默认星绘
- **砍掉**所有余额/用量/汇率/气泡/菜单/设置/消耗统计等 web 功能

用户需求要点：
- **兼容性强**：双击即跑、别人 Windows 也能用（打包成单文件 exe，免 Python/PyQt 依赖）
- **最不吃性能**：不要 Electron（几百 MB 常驻）
- 保留：点按播音 + 星绘早午晚播报；白墨冲刺
- **角色可扩展**：随 DSH 插件加其他角色（往 assets 丢文件即加）
- 不随开机自启；默认星绘

## 2. 技术选型演进（踩坑与决策）

| 方案 | 内存 | 兼容性 | 依赖 | 结论 |
|---|---|---|---|---|
| Electron | ~200-500MB | 好 | node | ❌ 太重，用户要最省性能 |
| Python + tkinter | ~30-40MB | 需 Python/Pillow | 需 Python | ⚠️ TransparencyKey 对图片内容不生效 → 紫边框 |
| C# WinForms（自带csc） | ~35MB | 最强（.NET Framework内置） | 零 | ⚠️ TransparencyKey 单色抠图，透明 PNG 边缘出紫边 |
| C# WPF（自带WPF） | ~80MB | 强 | 零 | ⚠️ 能 per-pixel alpha，但从零写、简陋 |
| **Python 3.14 + PyQt6** | ~60-90MB | 强（打包单文件exe） | PyQt6 | ✅ **选用**：per-pixel alpha 完美透明、动画/托盘/贴边成熟、可打包 |

**关键决策**：用户强调"参考成熟桌宠开发，太简陋问题很大" + "最省性能 + 兼容强"。PyQt6 是 Qt 桌宠社区成熟方案，per-pixel alpha 是透明正解。已验证 **PyQt6-6.11.0 兼容 Python 3.14.7**（`pip install PyQt6` 成功）。

## 3. 目录结构

```
dsh-desktop-pet/
├── pet.py                   ← 主程序（PyQt6 桌宠）
├── DEVELOPMENT.md           ← 本开发日志（持续写入）
├── README.md
└── assets/
    └── characters/          ← 角色目录（每角色一个子目录，放 image.png + 语音 mp3）
        ├── 星绘/  (image.png 256x256 + morning/noon/evening.mp3)
        └── 白墨/  (image.png 180x180 + sprint.mp3)
```

## 4. 编译 / 打包（PyInstaller → 单文件 exe）

```powershell
# 调研结论（subagent 859e...）：PyInstaller 6.22.2 支持 Python 3.14，PyQt6 6.11.2 可打包
pyinstaller --onefile --windowed --noconsole --name DesktopPet `
  --collect-all PyQt6 --collect-all PyQt6.QtMultimedia `
  --add-data "assets;assets" --clean pet.py
```
- `--collect-all PyQt6` 自动收齐 platforms/imageformats/styles/tls/multimedia 插件（规避 "Qt platform plugin windows not found"、图片/音频格式不支持）；代价 exe 80-150MB（可接受）
- `--add-data "assets;assets"`（Windows 分隔符 `;`）把资源打进解压目录
- 运行资源路径必须用 `resource_path(rel)`：frozen 时 `sys._MEIPASS`，否则脚本目录；**勿用** `os.path.dirname(sys.executable)`
- 硬性限制：**Qt6 不支持 Win7，目标机须 Win10/11 64 位**
- 验证流程：先打带控制台版看报错 → 干净 Win10/11 虚拟机双击单文件 exe 验证交互 → 删 build/dist 后 `--clean` 重打
- 退路：若 PyQt6 在 3.14 源码编译报错，降级 Python 3.13 + PyQt6 + PyInstaller

## 5. 功能实现要点

- **窗口**：`QWidget` + `Qt.WindowType.FramelessWindowHint` + `Qt.WindowType.WindowStaysOnTopHint` + `setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)` → per-pixel alpha 完美透明（透明 PNG 无紫边）
- **显示**：`QLabel` 放 `QPixmap(image.png)`（含 alpha）
- **点按播音**：`QSoundEffect` 或 `QMediaPlayer` 播 mp3；星绘按 `datetime.now().hour` 选 morning/noon/evening；白墨固定 sprint
- **按压动画**：复刻 dsh-pet 的 `scaleY(0.88) scaleX(1.05)`（`QGraphicsEffect`/缩放），按下压扁、松开弹性回弹（`QPropertyAnimation`/`QTimer`）
- **拖动/贴边**：鼠标事件移动窗口 + 边缘吸附
- **托盘**：`QSystemTrayIcon`（深色圆角菜单：切换角色（带 ✓）/ 退出）
- **角色扩展**：`assets/characters/` 自动扫描子目录；**悬停时右上角三横（☰）按钮**弹出角色/退出菜单（同托盘菜单样式），无需右键
- **菜单按钮（2026-09-05 起）**：自绘于 `paintEvent`（与角色动画通过 `painter.save/restore` 解耦，按钮恒固定右上角）；仅 `_hovering` 时显示；点按钮不触发按压/播音（`_menu_press` 状态区分）；菜单统一 `_build_role_menu()` 构建（深色 QSS `MENU_QSS` + 角色单选勾选 + 退出）

## 6. 变更记录

### 2026-09-05（新增通用语音：所有角色共用一套语音，可切回角色专属）
- **需求**：加一个「通用语音」选项——不管选哪个角色都用这套语音；可切回角色自己的语音
- **资源**：`assets/common_voice/`（与 characters 平级）存放通用语音；桌面「艾卡语音」里挑了 2 条（06_奈斯！、20_let's go gogooooooo）放入
- **实现**（`pet.py`）：
  1. 新增 `common_voice_dir()`（assets/common_voice）与 `list_common_audio()`（通用语音扫描）
  2. 配置 `voice_source`：'role'（角色专属，默认）/ 'common'（通用语音）；`PetWindow` 读入 `self._voice_source`
  3. `current_audio_list()`：按 voice_source 返回「当前语音列表」统一入口（热键槽、菜单、面板都用它）
  4. `_audio_key_for_path(path)`：通用目录内音频 key 用 `__common__/文件名` 前缀；`_custom_hotkey_audio` 支持解析 `__common__` 路径（跨角色稳定，切角色不丢绑定）
  5. `set_voice_source(source)`：持久化 + 刷新托盘菜单 + 同步打开面板
  6. 汉堡菜单加「语音来源：当前角色/通用语音」子菜单（含通用语音条数）
- **实现**（`settings_panel.py`）：音频模块顶部加「语音来源」下拉框（角色专属/通用语音），`_refresh_audio_list` 跟随来源 + 同步下拉显示；导入/删除/目录监视目标目录改为按来源（`_current_audio_dir()`）
- **验证**：py_compile ✅；逻辑脚本：默认 role→切 common→列表 2 条→切回 role 恢复 ✅；GUI 脚本：面板切换下拉框即时更新列表、不崩溃 ✅
- 涉及：`pet.py`（common_voice_dir/list_common_audio/_voice_source/current_audio_list/_audio_key_for_path/set_voice_source/_build_voice_source_submenu/_custom_hotkey_audio/菜单段）、`settings_panel.py`（cmb_voice_src/_refresh_audio_list/_import_audio/_delete_selected_audio/_watch_current_dir/_current_audio_dir）

### 2026-09-05（设置面板：窗口可拖拽缩放 + 列表行距紧凑 + 修复点三横崩溃）
- **需求**：设置面板太小、不能拖大，角色/音频列表行距大
- **实现**：面板默认按屏幕尺寸放大（max 720×860）、`setMinimumSize(520,560)`、`setMouseTracking`；新增 `nativeEvent` WM_NCHITTEST 拦截边缘/四角（_RESIZE_MARGIN=6）→ 系统接管拖拽缩放；QListWidget item padding 6px→3px 紧凑
- **崩溃修复**：nativeEvent 未命中时返回 `super().nativeEvent(...)` 触发 C 层访问违规（0xc0000005，QtCore.pyd），窗口 show 即崩 → 改为未处理一律 `return False, 0`（与 pet.py 历史教训一致）
- **验证**：复现脚本定位崩溃在 `panel.show()`；修复后构造/show/缩放全过；WM_NCHITTEST 四角返回 13/14/16/17、边缘 10/11/12/15、中心 1 均正确；resize 800×900 OK

### 2026-09-05（角色支持 GIF 动图：艾卡导入）
- **需求**：桌面「艾卡」文件夹导入角色，需支持 GIF 动图形象（透明、自动播放）
- **资源**：`艾卡.gif` 120×122、18 帧、透明通道 → 复制到 `assets/characters/艾卡/艾卡.gif`
- **实现**（`pet.py`）：
  1. 角色扫描 `list_roles` / 新增 `role_image(dir)`：优先 `image.png`，无则取目录内**首个 .gif**（排序）作为角色形象 → 艾卡无需 image.png 也能被识别
  2. `PetWindow` 新增 `self._movie`（QMovie）；`load_role` 无 image.png 时尝试加载目录 GIF：`frameChanged → _set_role_frame`（每帧 `currentPixmap` 缩放后赋给 `self.pixmap`，保持宽高比 + 透明）→ 与静态图共用同一绘制/按压动画路径，paintEvent 零改动
  3. `_stop_movie`：切角色/退出时停止动画并断开信号（closeEvent 调用），避免泄漏与串角色
  4. 只对 `frameCount()>1` 的 GIF 启用动画；首帧先同步显示防空白
- **实现**（`settings_panel.py`）：角色导入校验放宽为「含 image.png **或 .gif**」；提示文案同步更新
- **验证**：py_compile ✅；QMovie 实测 18 帧逐帧触发、每帧 120×122 带透明 ✅；临时加载脚本确认艾卡被识别、pixmap cacheKey 随时间变化（动画推进）✅
- 涉及：`pet.py`（role_image/list_roles/_stop_movie/_set_role_frame/load_role/closeEvent）、`settings_panel.py`（_import_character/提示文案）

### 2026-09-05（菜单点选项后自动重开，支持连续操作）
- **现象**：点菜单里一个选项后菜单关闭，要重新打开才能点下一个选项
- **根因**：各设置项点击后 `_schedule_menu_refresh` 置 `_reopen_menu` 并 close，`_popup_menu_at` 在 exec 返回后**立即递归** exec——递归发生在鼠标释放事件处理栈内，新菜单被旧事件收尾逻辑关闭/不稳定 → 表现为"点一下菜单就关"
- **修复**：
  1. `_popup_menu_at` 重开改为 `QTimer.singleShot(120ms, ...)` 延迟调度，等点击/释放事件完全收尾再重弹 → 点选项后菜单自动在同一位置重开，可连续操作
  2. 纯开关项（`set_auto_ptt`/`set_hotkeys_enabled`）**不再**关菜单刷新——勾选状态由 QAction 自身维护，避免无谓闪烁
- **验证**：py_compile ✅；桌宠重启后待用户实测连续点选
- 涉及：`pet.py`（_popup_menu_at 延迟重开、set_auto_ptt/set_hotkeys_enabled 去刷新）

### 2026-09-05（按键捕获修复：开麦键录制/Esc 无效）
- **现象**：开麦键「自定义…按一个键」无效、Esc 无法退出录制
- **根因（3 层）**：
  1. `SetWindowsHookExW(WH_KEYBOARD_LL)` 的 hMod 传了 `GetModuleHandleW(None)` → **ERROR_MOD_NOT_FOUND(126)**，hook=0 根本没装上（钩子过程在本进程内时 hMod 必须传 NULL）
  2. 回调只在**有消息循环的线程**派发 → 需独立线程 + `GetMessageW` 循环（原在主线程装完即返回，永不触发）
  3. `ctypes.wintypes` 无 `KBDLLHOOKSTRUCT` 需自定义；`CallNextHookEx` 64 位 lParam 溢出（用 `c_void_p` 透传）
- **修复**（`pet.py` KeyCapture 重写）：
  - 独立钩子线程跑 `GetMessageW` 消息循环；`SetWindowsHookExW(..., None, 0)`（hMod=NULL）
  - 回调只做线程安全记录（`_result` 槽）；主线程 `QTimer` 40ms 轮询 `_poll()` 结果 → `on_done`
  - 自定义 `KBDLLHOOKSTRUCT`；回调签名 `c_int/c_size_t/c_void_p` 兼容 64 位
  - Esc(0x1B)→'esc'→回调 None（取消）；修饰键忽略并吞掉；钩子失败→'err'→回调 None
- **验证**：hook 句柄非 0 ✅；模拟 F1 → 回调 vk=112 ✅；模拟 Esc → 回调 None ✅（独立测试脚本实测）
- 涉及：`pet.py`（KBDLLHOOKSTRUCT/_LLKBD_ProcType 修正、KeyCapture._message_loop/_poll/_proc/start/stop）

### 2026-09-05（自定义语音快捷键 + 开麦键可换 + 快捷键总开关 + 菜单消失修复）
- **需求**：
  ①「自动按住V」勾选后选项框消失的 bug
  ②每条语音可自定义快捷键：点一下语音 → 按任意键 → 绑定，语音右侧显示该键
  ③「启用快捷键发话」总开关
  ④ 长按开麦键可切换（子菜单点选，默认 V）
- **实现**（`pet.py` v1.5.0）：
  1. **菜单消失修复**：所有 setter（bind/self/ptt/角色）统一 `_schedule_menu_refresh()`——`QTimer.singleShot(0, menu.close)` 延迟关菜单，避开 checkable 点击事件派发中的 close 竞态（原 close+重弹导致菜单闪没）
  2. **键名↔VK 映射表** `VK_NAME_MAP`（字母/数字/F1-12/小键盘/符号）；`key_name_to_vk`/`vk_to_key_name`；未知名存 `VK<数字>` 格式并用 `_resolve_vk` 还原
  3. **KeyCapture**（WH_KEYBOARD_LL 一次性钩子）：捕获下一个按键（Esc=取消，修饰键忽略并吞掉防误触）；安装于主线程（消息循环），回调经线程延后触发安全卸载
  4. **自定义语音快捷键**：菜单音频项文字 `♪ 名称   [键]`（右侧显示已绑定键）；点击 → 关菜单 → `_schedule_capture('audio', akey)` → 250ms 后启动钩子 → `_apply_capture` 存配置 `audio_hotkeys={角色/文件名: 键名}` + 重注册热键 + toast 提示"xxx → F1"
  5. **注册逻辑**：自定义键（hid 0x6000+）与默认小键盘 1-9 并存；重复 Num1-9 的自定义跳过（数字序号映射兜底）；nativeEvent 自定义键优先匹配；总开关关 → 全部注销不注册
  6. **开麦键子菜单** `_build_ptt_key_submenu`：常用键（V/B/C/X/Z/F1-5）+「自定义…」录制；`set_ptt_key` 持久化 `ptt_key`；PTT 播放用 `self._ptt_vk`（不再硬编码 V）
  7. **总开关**「启用快捷键发话」checkable → `set_hotkeys_enabled`（持久化 `hotkeys_enabled`；关=注销全部热键）
  8. **toast 浮层**：paintEvent 顶部气泡绘制「按一个键绑定…（Esc 取消）」/绑定结果/已取消（带 QFont 中文显示）
- **验证**：py_compile ✅；键映射冒烟（V→0x56、F1→0x70、Num3→0x63、VK123 解析）✅；提权启动+热键注册 ✅；**待用户实测**（录制绑定/右侧显示/开麦键切换）
- 涉及：`pet.py`（VK_NAME_MAP/CUSTOM_HK_BASE/KeyCapture/_resolve_vk/register_single_hotkey/unregister_hotkey、菜单音频项+PTT项改、_build_ptt_key_submenu、set_hotkeys_enabled/set_ptt_key/_schedule_capture/_on_key_captured/_apply_capture/_schedule_menu_refresh、paintEvent toast、nativeEvent 自定义键）
- 备注：**未重新打包 exe**（当前桌面 exe 仍是 v1.4.0）

### 2026-09-05（打包 exe v1.4.0）
- **打包命令**（含新依赖 sounddevice/soundfile/numpy）：
  ```
  python -m PyInstaller --noconfirm --onefile --windowed --name "卡丘简易桌宠" --icon "assets/app.ico" --add-data "assets;assets" --collect-submodules sounddevice --collect-submodules soundfile --collect-submodules numpy --hidden-import sounddevice --hidden-import soundfile --hidden-import numpy --exclude-module PyQt6.QtQml ... pet.py
  ```
- **产物**：`dist\卡丘简易桌宠.exe`（63MB，PyQt6 + sounddevice + soundfile + numpy 全打包）；已复制桌面 `C:\Users\mier\Desktop\卡丘简易桌宠.exe`
- **验证**：exe 启动正常（普通版→UAC 提权→桌宠实例稳定运行）✅；进程 10s+ 存活无崩溃 ✅
- **清理**：删除 build/ 与旧乱码 spec（首次 CLI 打包自动生成 spec 名为中文，控制台乱码无碍实际文件名）
- 备注：exe 每次启动弹 UAC（自提权逻辑内置）；配置/角色资源在 exe 同目录 assets 与 pet_config.json（打包后 base_dir 逻辑已处理）

### 2026-09-05（自己监听设备 + 自动按住 V 开麦）
- **需求①（自己监听）**：绑定麦克风（音频只进虚拟麦给队友）后**自己听不见**；需要菜单选项选自己的耳机/扬声器，播放时**同时**输出给"队友麦 + 自己耳机"
- **需求②（自动 PTT）**：游戏是"**长按 V 开麦**"（PTT）；按数字键播音频时队友听不到（因为没按 V）。加菜单**勾选项「自动按住 V 开麦（PTT）」**：开启后播放音频自动模拟按住 V，音频播完松开 → 队友在开麦期间听到
- **实现**（`pet.py` v1.4.0）：
  1. 多设备播放重构：`play_audio_direct` → `_play_one_device`（单设备，prepared 数据可复用）+ `play_audio_multi(path, [设备...])`（**解码一次、并行线程写多个设备**，返回成功数）；辅助 `_resolve_device_index`/`_decode_and_prepare`/`_adapt_to_device`（声道+重采样）
  2. 配置新增 `self_device`（自己监听设备）与 `auto_ptt`（自动开麦开关），`pet_config.json` 持久化；`set_self_device`/`set_auto_ptt` 保存+托盘同步
  3. `_target_devices()`：播放目标 = bind_device（队友）+ self_device（自己，若不同于绑麦）；两者都设则双设备同时响
  4. `_play_direct_worker`：auto_ptt 开启时 `ptt_key_down(VK_V)` 按住 → `play_audio_multi` 播放 → finally `ptt_key_up(VK_V)` 松开（时长与播放自然一致）
  5. 菜单：`_build_device_submenu(kind)` 统一构建设备子菜单（bind=队友麦含"不绑定"，self=自己监听含"不听"）；主菜单 = 切换角色 / 绑定麦克风（队友听）/ 自己监听（耳机）/ **自动按住 V 开麦（checkable 打勾）** / ♪音频 / 退出
- **验证**：py_compile ✅；`play_audio_multi` 双设备实测成功数=2（Voicemeeter Input + 扬声器 USB 同时响，1.1s）✅；提权启动 + 热键 1-9 注册 ✅；**待用户实测**（游戏里 PTT 场景）
- **跟进（用户要求）**：按 V 时长需比音频长 0.5s（防尾部被切）→ `PTT_HOLD_EXTRA_S = 0.5`，`_play_direct_worker` 在 `play_audio_multi` 返回后 `time.sleep(0.5)` 再 `ptt_key_up`（顶部补 `import time`）；时序实测：按住总时长 1.60s = 音频 1.1s + 0.5s ✅
- 涉及：`pet.py`（+VK_V/KEYEVENTF_KEYUP 常量、ptt_key_down/up/audio_duration_seconds、播放链重构、_build_device_submenu、set_self_device/set_auto_ptt、_target_devices）
- 备注：**未重新打包 exe**

### 2026-09-05（UAC 自提权：修复管理员游戏下热键失效）
- **现象**：小键盘热键在普通窗口正常，但**聚焦游戏窗口（Steam/WeGame/Epic 平台游戏，常以管理员运行）时失效**
- **根因**：Windows **UIPI（用户界面特权隔离）**——低完整性级别进程（桌宠 Medium）注册的全局热键，在高完整性级别进程（管理员游戏）前台时收不到 WM_HOTKEY
- **修复**（`pet.py`）：UAC 自提权——`main()` 检测 `IsUserAnAdmin()`，非管理员则 `ShellExecuteW("runas")` 带 `--elevated` 参数提权重启自己（防二次提权）；ShellExecuteW 返回 >32 才算成功（用户取消 UAC 则继续普通运行并提示）
- **验证**：✅ **用户亲测**：提权启动后游戏里按小键盘正常、绑定麦克风队友能听到
- **代价**：每次启动弹一次 UAC（治本方案的标准代价）
- **另修复**：`nativeEvent` 必须返回 `(bool,int)` 元组而非 `super().nativeEvent()` 返回值 → 曾导致 `show()` 时 C 层 access violation 崩溃（窗口不出现/进程秒退）；移除 nativeEvent 内的热键注册（与 singleShot 互递归崩溃源）

### 2026-09-05（小键盘 1-9 全局热键快捷播放）
- **需求**：打游戏时按**小键盘数字键 1-9**（全局，无需点桌宠）直接播放当前角色的音频；固定映射：第 1 个音频=小键盘 1、第 2 个=2……（星绘早上好/中午好/晚上好 = 1/2/3；后续同角色加音频顺延 4-9）；切换角色后自动跟随新角色对应位置
- **实现**（`pet.py` v1.3.0）：
  1. `RegisterHotKey` 注册小键盘 1-9（VK 0x61~0x69，MOD_NOREPEAT，失败去 MOD_NOREPEAT 重试），热键 ID 0x5001~0x5009
  2. `hwnd` 优先窗口 winId（PyQt6 返回 sip.voidptr 需 `int()`）；**winId 拿不到时回落 hwnd=0**（WM_HOTKEY 进线程消息队列，Qt 事件循环经 nativeEvent 收到）——兼容无原生句柄/特殊窗口场景
  3. `nativeEvent` 捕获 `WM_HOTKEY`（0x0312）→ 按热键 ID 反查数字 → `_hotkey_slot_audio(num)` 播放当前角色第 num 个音频；100ms 防抖
  4. 注册时机：`__init__` 后 300ms 首试 + `showEvent` 触发 + nativeEvent 惰性补注册，最多重试 30 次（~15s）；`_dbg` 写 `pet_debug.log`
  5. `closeEvent` 注销全部热键
- **踩坑**：
  - PyQt6 `winId()` 返回 `sip.voidptr` 非 int；未显示/无句柄时可能为 None
  - 隔离 shell/无真实桌面会话时 GUI 窗口无法真正显示 → winId 无效、showEvent 不触发（**仅限调试环境**；用户真实桌面正常）——故加 hwnd=0 回落 + 多次重试兜底
  - `RegisterHotKey` MOD_NOREPEAT 可能被占用失败 → 无修饰符重试
- **验证**：py_compile ✅；`int(winId())` 同款窗口标志实测正常 ✅；**待用户桌面实测**（本 shell 无法显示 GUI 窗口）
- 涉及：`pet.py`（+ctypes/wintypes 导入、NUMPAD_VK/WM_HOTKEY/MOD_NOREPEAT 常量、register/unregister_numpad_hotkeys、_register_hotkeys_now/_hotkey_slot_audio/nativeEvent/showEvent/closeEvent、_dbg 日志工具）
- 备注：**未重新打包 exe**

### 2026-09-05（菜单加音频列表 + 切换角色点击右扩 + 按钮 1 秒延迟消失）
- **需求**：①菜单里切角色项 → 点一下向右扩展角色选项；②角色音频全部进菜单（点即播，用于给队友放音）；③三横按钮在鼠标移开时 1 秒后才消失（原：移过角色透明空白即消失，切角色后明显）
- **实现**（`pet.py`）：
  1. 撤销上轮"裁剪透明边"方案（会让不同角色显示大小不一），改 **1 秒延迟消失**：`_hide_timer`（singleShot 1s），`leaveEvent` 只启动计时器不立刻清 `_hovering`，`enterEvent` 取消；到点 `_hide_btn_now` 确认鼠标真不在窗口才隐藏
  2. 菜单重构成三区：`切换角色 ▸`（角色子菜单，`setMenu` 关联 → 指向即展开；PyQt6 无 setPopupMode，InstantPopup 需 QMenu 上设但 QMenu 无此 API，最终用原生子菜单悬停展开，行为≈点击右扩）+ 分隔线 + **♪音频列表**（`list_role_audio` 自动扫描角色目录音频，友好中文名映射 morning/noon/evening/sprint/click → 早上好/中午好/晚上好/冲刺/点击）+ 分隔线 + 退出
  3. 音频菜单播放复用 `play_audio`（点按播音同源）
- **踩坑**：PyQt6（Qt6）**移除** `QAction.setPopupMode`；`addMenu` 返回 QMenu 而非 QAction（早期 AttributeError 崩溃 ×2）；模态 `menu.exec` 内不能嵌套 exec → 切角色用标志位 `_reopen_menu` 在 exec 返回后自动重弹新角色菜单
- **验证**：py_compile ✅；交互测试菜单项=切换角色/♪音频/退出、切角色后菜单重弹且音频跟随角色 ✅
- 涉及：`pet.py`（_hide_timer/_hide_btn_now/enterEvent/leaveEvent 改、_build_role_menu 重构、_popup_menu_at 标志位重弹、list_role_audio/friendly_audio_name/AUDIO_LABEL 新增）

### 2026-09-05（绑定麦克风/输出设备 + 托盘修复 + 点击展开子菜单）
- **需求（绑定麦克风）**：桌宠菜单里可选"绑定麦克风/输出设备"——绑定时桌宠播放的音频**只进指定设备**（如 Voicemeeter Input → 虚拟麦 → 队友可听，自己经 Voicemeeter A1 也能听到），系统其它声音（游戏/音乐）不受影响走物理音箱
- **技术方案（验证后选型）**：QMediaPlayer 无法指定输出设备；PyQt6 QAudioDecoder 在 Qt6 下有崩溃/API 变更坑；最终用 **sounddevice (PortAudio/WASAPI) 直出指定设备** + **soundfile 解码**（mp3 等 → float32 PCM）+ **numpy 重采样**
- **实现**（`pet.py`）：
  1. 依赖：`pip install sounddevice soundfile`（numpy 已有）；导入失败则 `HAS_SD=False` 优雅回退 QMediaPlayer
  2. `list_output_devices()`：枚举 WASAPI 后端输出设备（去重、去 WDM 噪音、Voicemeeter 排前）供菜单选择
  3. `play_audio_direct(path, dev)`：soundfile 解码 → 按设备通道扩展/裁剪 → **重采样到设备 default_samplerate（关键：WASAPI 设备常只认 48k，mp3 44.1k 直出报 Invalid sample rate）** → WASAPI OutputStream 播放
  4. `play_audio()`：绑定设备 → 后台线程（daemon）直出，失败经 `QTimer.singleShot` **回主线程**回退 QMediaPlayer（QMediaPlayer 非主线程操作会崩）
  5. 菜单新增「绑定麦克风/输出」子菜单（`_build_role_menu` ②）：列输出设备（勾选当前）+「不绑定（系统默认）」；选中即持久化 `pet_config.json`（`bind_device` 字段，与 exe 同目录，只读目录时退回 home）
  6. 菜单标题动态显示当前绑定：`绑定麦克风 ✓ Voicemeeter Input` / `绑定麦克风…（未绑定）`
- **Bug 修复（托盘图标堆积）**：原 `build_tray()` 每次调用都 `new QSystemTrayIcon`（切角色/绑定时越积越多）。拆 `init_tray()`（仅创建一次）+ `refresh_tray_menu()`（只替换 `setContextMenu`）；`__init__` 调 init_tray，`switch_role`/`set_bind_device` 调 refresh_tray_menu
- **Bug 修复（点托盘无反应）**：原 `activated.connect(lambda: self.tray.clicked())` 无实际动作。改 `_on_tray_activated`：左键单击（Trigger）→ `menu.popup(QCursor.pos())`；右键仍走系统 contextMenu
- **踩坑**：
  - `QMenu(parent)` 的 parent 须是 QWidget，`QSystemTrayIcon` 不是 → 托盘菜单 parent 传 `None`
  - PyQt6 QAudioDecoder 无 `errorOccurred`/`state`（Qt6 改名/移除），且解码 mp3 进程直接崩 → 弃用
  - 绑定验证需 Voicemeeter **正在运行**（Login=1 时路由无效），启动后条带须开 A1+B1
  - sounddevice 枚举含 MME/DirectSound/WDM 多后端重复 → 限定 WASAPI（hostapi='Windows WASAPI'）
- **涉及**：`C:\Users\mier\Desktop\deepseek work\dsh-desktop-pet\pet.py`（版本 1.2.0，+sounddevice/soundfile/numpy 导入、CONFIG 存取、list_output_devices、play_audio_direct、_build_role_menu ②绑定项、init_tray/refresh_tray_menu/_on_tray_activated、set_bind_device）；新增运行时依赖 `pet_config.json`
- **验证**：py_compile ✅；WASAPI 直出 Voicemeeter Input → 录 Voicemeeter Out B1 peak 0.4~0.63 ✅（正弦波与真实 mp3 均通）；桌宠实例绑定链路（写配置→实例化→play_audio→B1 录音 peak 0.598）✅；重采样后无 Invalid sample rate ✅
- **备注**：**未重新打包 exe**；打包需把 sounddevice/soundfile/numpy 打进（PyInstaller 会自动收依赖，但 numpy 较大）；真实使用需 Voicemeeter 运行中 + 条带开 A1/B1

### 2026-09-05（右键菜单改为悬停汉堡菜单 + UI 美化）
- **需求**：右键桌宠不再弹出"换角色/退出"菜单；改为**鼠标悬停在桌宠上时，右上角出现三横（汉堡）图标**，点击它弹出"切换角色 / 退出"菜单；UI 要好看
- **实现**（`pet.py`）：
  1. 删除 `contextMenuEvent`（右键菜单彻底移除，右键不再有反应）
  2. 右上角三横按钮：自绘于 `paintEvent`（`_paint_menu_btn`），半透明深色圆角底（悬停/按下提亮为白 70 alpha）+ 三条圆头白线；`_menu_btn_rect()` 定义 30×30 @ 右上角 (margin 6)
  3. 按钮仅在 `_hovering`（鼠标在窗口内）时显示；`enterEvent/leaveEvent` 管理；`setMouseTracking(True)` 让不按键也能跟踪 hover 高亮
  4. **角色动画与按钮解耦**：`paintEvent` 用 `painter.save()/restore()`，角色图缩放动画不作用于按钮（按钮恒为 1:1 固定右上角）
  5. 点击区分：点在按钮上 → 不压扁不播音，`_menu_press` 置位；松开仍在其上 → `_popup_menu_at()` 弹菜单；点在桌宠本体 → 原按压动画 + 播音 + 拖动逻辑不变
  6. 菜单：`_build_role_menu()` 统一构建——**深色圆角 QSS**（半透明底、圆角 10、hover 高亮、圆润 item）+ 角色单选组（**当前角色带 ✓**）+ 分隔线 + 退出；汉堡菜单与托盘菜单共用（托盘也变好看了）
  7. 弹菜单时暂隐按钮（防 leave 干扰），`menu.exec` 返回后按鼠标真实位置恢复悬停态；`switch_role` 后同步勾选态
- **验证**：`py_compile` ✅；像素采样（按钮中心白 240 / 背景白 70 alpha / 窗口角落透明 0）✅；交互测试（press 按钮 `_menu_press=True`、`_down=False` 不触发动画、菜单项=星绘/白墨/退出、当前角色勾选）✅
- 涉及：`pet.py`（导入 + 常量 MENU_* / MENU_QSS + __init__ 状态 + paintEvent/_paint_menu_btn/_menu_btn_rect + 鼠标事件 + enter/leave + build_tray/_build_role_menu/_popup_menu_at/switch_role；删 contextMenuEvent）
- 备注：**未重新打包 exe**（`dist\卡丘简易桌宠.exe` 仍是旧版右键菜单）；待用户实测满意后按第 4 节打包流程重打并分发

### 2026-09-04（exe 图标改为星绘同款）
- **需求**：exe 文件图标（桌面/任务栏/资源管理器显示）改成星绘形象，方便发给别人下载时也能看到星绘图标
- **实现**：用 Pillow 把 `assets\characters\星绘\image.png`(256×256) 转成多尺寸 `.ico`（16/24/32/48/64/128/256）→ `assets\app.ico`；PyInstaller 加 `--icon "assets\app.ico"`
- **验证**：打包日志确认 `Copying icon to EXE` ✅；`ExtractAssociatedIcon` 放大到 128×128 确认图标=星绘（之前 32×32 偏暗是默认小尺寸，缩小细节少，误判）✅
- 产物：`dist\卡丘简易桌宠.exe`（89.8MB，带星绘图标）—— 可直接分发给别人，下载/打开均显示星绘图标

### 2026-09-04（右键退出 + 星绘托盘图标 + 程序名「卡丘简易桌宠」）
- **需求**：右键加「退出」；托盘图标用星绘；程序名「卡丘简易桌宠」
- **实现**（`pet.py`）：
  1. `contextMenuEvent`（右键菜单）补「退出」：`menu.addAction("退出")` → `QApplication.quit`（之前只有托盘菜单有退出）
  2. 托盘图标固定用**星绘**（`role_dir("星绘")/image.png`）并缩放到 **32×32**（`QPixmap.scaled`，Windows 托盘小图标更清晰），加 `setToolTip("卡丘简易桌宠")`
  3. 程序名：`app.setApplicationName("卡丘简易桌宠")` + `self.setWindowTitle("卡丘简易桌宠")`
- **打包**：`--name "卡丘简易桌宠"`（PyInstaller 支持中文名，编译成功）→ `dist\卡丘简易桌宠.exe` (89.7MB)
- **验证**：`py_compile` ✅；启动 exe 进程名=`卡丘简易桌宠`，桌宠窗口 200×200 稳定 ✅；星绘托盘图标缩放到 32×32 正常（实测 32x32）✅；已复制到桌面
- 备注：托盘 QSystemTrayIcon 用星绘（换角色后托盘图标不随角色变，固定星绘符合需求）

### 2026-09-04（PyInstaller 打包 exe 完成 + 最终验证）
- **动画修正**（用户反馈"下压回弹太快 / 长按下压松开弹回"）：改 `animate_scale`（下压 110ms ease-out 快压 + 回弹 520ms 过冲 `1+0.13*sin(πt)*e^(-1.6t)` 慢弹）；长按下压保持、松开立即回弹；窗口 setFixedSize(200,200) 锁死 + paintEvent 自绘 scale（origin=底部中心）→ 只变形不位移
- **PyInstaller 打包**（subagent 结论落地）：
  - `python -m PyInstaller --onefile --windowed --noconsole --name DesktopPet --collect-all PyQt6 --collect-all PyQt6.QtMultimedia --add-data "assets;assets" --clean pet.py`
  - 产物 `dist\DesktopPet.exe`（89.7MB，PyQt6 全量收集；QtQuick/QML 组件 warning 无关紧要）
  - 资源正确打进归档（`assets\characters\星绘\|白墨\` 的 png/mp3 均在内，中文名显示乱码是控制台编码，实际正确）
- **调试日志排查**（打包版窗口疑似异常）：
  - 加 `_log` 输到 `%TEMP%\pet-debug.log` 定位真实状态
  - **结论**：打包版正常！`[base_dir] MEIPASS=...`、`[load_role] pixmap 256x256 加载成功`、`[place_default] window 200x200`——之前窗口 107x52 是截图中间态（动画缩放），误判
  - 最终干净版**移除密集 _log 打点**（保留空 `_log` 定义供未来排查）
- **验证**：`py_compile` ✅；打包成功后启动 exe，窗口 `rect=(4895,1887)-(5095,2087) w=200 h=200` 稳定，主进程 45.9MB ✅ → **待用户实测点按/播音/换角色**

### 2026-09-04（点按动画修到"只变形不位移"）
- **现象**：点按桌宠出现"往下移动/震动"效果，不像插件
- **根因**：之前用 `window.setGeometry` 缩放窗口矩形（还保持窗口中心），导致窗口**四边都动**=位移；且 `OutBack`/sin 叠加产生怪曲线=震动
- **插件原理**（读 WIDGET_JS 确认）：`.dshwv-body{transform-origin:50% 100%; transition:transform .22s cubic-bezier(.34,1.56,.64,1)}`；`pressDown` 设 `scaleY(0.88) scaleX(1.05)`，`pressUp` 设 `scaleY(1) scaleX(1)` —— **scale 以底部中心为 origin，只变形不位移**
- **修复**：改用**自绘** `paintEvent`（`QPainter.translate(底部中心)→scale→translate 回`），窗口 `setFixedSize(200,200)` 锁死，只改 `_scale_x/_scale_y` + `update()` 重绘 → **绝无位移**；回弹用标准 cubic-bezier 过冲曲线 `1+0.11*sin(πt)*e^(-1.8t)`（先快回、一次轻微过冲、归一），非震动
- 涉及：`pet.py`（paintEvent/_set_scale/press_down/press_up/start_bounce/_bounce_step）；删 label 自绘方式
- 验证：`py_compile` ✅；窗口 setFixedSize(200,200) 锁死不位移 ✅；点按/播音待用户实测

### 2026-09-04（PyQt6 版完成，subagent 并行调研）
- **subagent 并行**：A=PyQt6 桌宠技术要点（透明/动画/音频/托盘/角色扫描）；B=PyInstaller 打包方案。两条均有产出，已写回日志。
- **PyQt6 技术要点吸收**（subagent abce...）：
  - 窗口：`FramelessWindowHint|WindowStaysOnTopHint|Tool` + `WA_TranslucentBackground`（缺 `WA_TranslucentBackground` 会黑底；`Tool` 不占任务栏不抢焦点）
  - 显示 alpha PNG：`QLabel.setPixmap`，勿设背景色/`setAutoFillBackground`，窗口尺寸=图形尺寸
  - mp3：`QMediaPlayer`+`QAudioOutput`，`setSource(QUrl.fromLocalFile())`，播放器存 self 防 GC（短音效用 QSoundEffect 但 mp3 不稳）
  - 压扁回弹：`QPropertyAnimation` 动画 label.geometry，`OutBack` 缓动，动画对象存 self
  - 托盘：`setQuitOnLastWindowClosed(False)` 关键；menu 存引用防 GC
  - 角色扩展：`os.listdir`+`is_dir` 扫 assets/characters
- **PyInstaller 打包结论吸收**（subagent 859e...）：PyInstaller 6.22.2 支持 Py3.14 + PyQt6 6.11.2 打单文件 exe；`--collect-all PyQt6 --collect-all PyQt6.QtMultimedia`；资源用 `sys._MEIPASS`；目标机须 Win10/11 64 位（Qt6 不支持 Win7）
- **pet.py 实现**：透明置顶浮窗 + 点按播音（星绘早/午/晚 + 白墨冲刺）+ QPropertyAnimation 按压弹性动画（scaleY0.88 scaleX1.05 + OutBack 回弹）+ 拖动贴边 + 系统托盘（切角色/退出）+ 角色目录扫描扩展
- **验证**：`py_compile` ✅；启动成功（PID, ~48→61MB）；截图确认**透明窗口无紫边/无黑底**（WA_TranslucentBackground per-pixel alpha 生效）✅；托盘/播音逻辑就绪
- **遗留**：点按播音/动画需用户实测；`QTimer` 导入未用（可清理）；尚未打包 exe

### 2026-09-04（立项 + PyQt6 选型）
- 需求：把 dsh-pet 魔改为独立 Win11 桌面桌宠（兼容强 + 最省性能 + 点按播音 + 星绘早午晚 + 角色可扩展 + 不随开机自启 + 默认星绘）；后续随 DSH 插件加角色
- 尝试：C# WinForms / WPF 版（透明边缘紫边、Animation 简陋，用户判定"太简陋问题很大"）
- **选型**：参考成熟桌宠方案 → **Python 3.14 + PyQt6**（per-pixel alpha 完美透明 + Qt 动画/托盘/贴边成熟 + 可打包单文件 exe）
- 验证：`pip install PyQt6` 成功（PyQt6-6.11.0，兼容 Py3.14）✅
- 下一步：搭 PyQt6 骨架（透明/置顶/贴边/托盘）+ 点按播音 + 动画 + 角色扩展 + PyInstaller 打包
