# dsh-desktop-pet 开发日志（DESKTOP PET DEVELOPMENT LOG）

> 桌宠：**独立 Win11 桌面桌宠**（透明置顶浮窗，点按播音，角色可扩展）
> 工程：`<repo-root>`
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
├── pet.py                   ← 主程序（PetWindow：桌宠窗口/动画/按键钩子/游戏联动/切角色）
├── ai_chat.py               ← AiChatManager：AI 对话 + TTS 朗读（对话条/气泡/多会话/用量/世界书/延迟显示）
├── settings_panel.py        ← 设置面板窗口（角色列表/模型/TTS/世界书编辑器）
├── 卡丘简易桌宠.spec         ← PyInstaller 打包配置（`python -m PyInstaller 卡丘简易桌宠.spec`）
├── rthook_fix_urllib_ssl.py ← PyInstaller 运行时 rthook（修复 SSL 加载），打包打进 exe
├── DEVELOPMENT.md           ← 本开发日志（持续写入，接手先读）
├── README.md
└── assets/                  ← 资源（开发期直接读源码 assets/；打包后数据落在「卡丘简易桌宠数据」目录）
    ├── characters/          ← 角色（三级：阵营/角色/形象文件），每角色目录放 image.png（gif 角色放 .gif）
    │   ├── 乌尔比诺/        ← 7 角色：加拉蒂亚 奥黛丽 星绘 汐 玛德蕾娜*.gif 白墨 绯绯
    │   │   └── 星绘/image.png
    │   ├── 剪刀手/          ← 9 角色：令 拉薇 明 梅瑞狄斯 玛拉 琴格兰汀 达卡*.gif 诺诺 香奈美
    │   └── 欧泊/            ← 8 角色：伊薇特 信 千代 心夏 忧黎 米雪儿 芙拉薇娅 瑞欧娜
    ├── common_voice/        ← 通用语音（任意角色共用音效，如 06_奈斯！.mp3）
    ├── trigger_voice/<角色>/ ← 集中触发音：每角色「卡拉彼丘.mp3」（点按桌宠播放，角色目录内不再放语音）
    ├── tts_refs/<角色>/     ← TTS 克隆参考：ref.wav + ref.txt + system_prompt.txt
    ├── persona/<角色>.txt   ← 角色人设/自我介绍（点按台词来源 + TTS 克隆参考文案）
    ├── role_worldbooks/<角色>.json  ← 每角色专属世界书（常驻注入）
    ├── world_book.json      ← 全局世界书（关键词/常驻注入）
    └── app.ico              ← 托盘/窗口图标

运行数据（不入库）：contexts/role_<角色>.json（每角色独立会话上下文）、pet_config.json（本地配置含 API 地址）、pet_debug.log
打包产物（不入库）：build/ dist/ 卡丘简易桌宠.exe
```

> 老文件：`DesktopPet.cs`（早期 C# WPF 调研版）已于 2026-09-08 删除（详见变更记录），需要回溯时查 git 历史即可。

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

### 2026-09-09（TTS 预设收敛为一个「通用全能」：3 套合一 + 弹窗直用内置默认）
- **问题（用户）**：3 个预设（通用/台词向/独白向）太散，用户只想要一个强大的通用模板
- **改动**（`settings_panel.py`）：
  - `TTS_PROMPT_PRESETS` 从 3 个收成 **1 个「通用全能（默认·推荐）」（1133 字）**：开篇「你是顶级的语音导演」+【引擎特性】讲 vocal events/标点即停顿/instruction → 【改写要求】8 条 → 【情绪表演】点睛不堆砌、不念旁白、长段拆呼吸感 → 【情绪行】行为+节奏+神态 4 例 → 【输出格式】两行
  - 弹窗预设下拉应用逻辑改为**直取 `_ai.default_tts_prompt()`**（内置默认 = 唯一权威版本，预设/恢复默认按钮永远同一份，不再维护两套文本）
  - 弹窗底部提示「10 字内」改「15 字内」对齐新模板
- **验证**：py_compile ✅；预设数=1、含全部关键要点断言 ✅；待打包实测
- 涉及：`settings_panel.py`
- git：（待提交）

### 2026-09-09（TTS 提示词大幅扩写：官方模型卡 vocal events + 行为化指令）
- **需求（用户）**：TTS 提示词写更多、让 AI 更懂怎么用好 TTS（继续深挖资料后扩写）
- **调研新增**（breeze_tts_guide.md 同步）：官方模型卡确认 vocal events 完整清单——中文 `[笑][叹气][咳嗽][清嗓子]`、英文 `(laugh)(sigh)(cough)(clears throat)`；渲染成真实气声/笑声非念出。社区高赞：instruction 写「行为+节奏+神态」而非抽象情绪名；标点=停顿谱
- **默认提示词重写**（`ai_chat.py default_tts_prompt`，700→1110 字）：开篇先给模型讲引擎特性（vocal events 用法、标点=停顿、instruction 决定语气），再分三步干活：①改朗读稿（9 条规则含数字展开/英文逐字母/多音字注音/长句拆短/语气词适度）②按需嵌标记（位置/频率/语义/中英文形式，宁缺毋滥）③写行为式「情绪」行（15 字内，附 3 个示例写法）
- **三个预设重写**（`settings_panel.py TTS_PROMPT_PRESETS`）：通用均衡（765 字）/ 情绪生动台词向（449 字，情绪=节奏映射表+演在句子里不要念旁白）/ 长段防机械独白向（479 字，长短句交替+分组气口）
- **确认链路**：`_api_speech_synth` 用复数 `instructions` 字段（audio.cpp server 语义，单数会被忽略）；`parse_tts_output` 上限 30 字不截断新格式；[笑] 标记在朗读稿中保留 → 引擎渲染真实笑声
- **验证**：py_compile ✅；默认+3 预设含全部关键要点断言 ✅；parse 链路（情绪行→instructions、[笑] 保留）✅
- 涉及：`ai_chat.py`、`settings_panel.py`、`_worldbook_drafts/breeze_tts_guide.md`
- git：（待提交）

### 2026-09-09（朗读蹦字与语音不同步修复：标点加权时间表 + 去首尾静音）
- **问题（用户）**：语音吐字和冒文字速度不一致——有时文字快、有时语音快
- **根因**：①蹦字按「音频总时长 ÷ 字数」**匀速分配**，但语音有停顿/拖长（标点处最明显）→ 长句、带情绪句必然错位；②wav **首尾静音**被算进蹦字时长（实测 3.3s 音频含 0.5s 头静音 + 0.8s 尾静音，语音只有 2s）→ 文字比语音慢；③固定 100ms 起步对不上实际出声时刻
- **修复**（`ai_chat.py`）：
  1. 新增 `_PUNCT_WEIGHT` 标点权重表：普通字 1.0 / 逗号顿号 2.0 / 句号问号感叹省略号 2.5 / 破折号 3.0 —— `show_text_synced` 预计算每个字符的显示时刻（按权重分配总时长），`_type_step` 改 50ms 轮询时间表推进 → 文字在标点处同步"等"，节奏贴合语音
  2. 新增 `_wav_active_range_ms`：按 20ms 块 RMS 检测首尾静音，返回 (实际出声起点, 有效时长)；蹦字用**有效时长**、并在**出声起点**后才开始蹦（100ms + start_ms）
  3. `_stop_type` 清理时间表防残留
- **验证**：py_compile ✅；时间表逻辑（逗号后停 408ms/感叹号 204ms/末时刻精确=总时长）✅；GUI 离屏冒烟（3.5s 显示 16/18 字、播完清空时间表）✅；静音检测实测（3300ms wav → 起点 500ms / 有效 2000ms）✅；待打包实测听感
- 涉及：`ai_chat.py`（_PUNCT_WEIGHT/show_text_synced/_type_step/_stop_type/_wav_active_range_ms/_on_tts_done）
- git：（待提交）

### 2026-09-09（深夜闪退根治：UIA 跨线程 COM + QThread 被 GC 回收 + 钩子回调异常穿出）
- **问题（用户）**：桌宠"最近闪退了"（9/8 22:46、23:38、9/9 0:00 三次，进程全部消失）
- **证据（Windows 事件日志）**：三次崩溃均为 卡丘简易桌宠_最新.exe：①22:46 ntdll.dll 0xc0000374（堆损坏）；②23:38、0:00 Qt6Core.dll 0xc0000409 偏移 0x1c8d8（同 9/7 反复出现的崩溃签名）——Qt 层 C++ 崩溃，Python traceback 抓不到，pet_debug.log 尾部只有 TTS 502/500（BreezeTTS 服务未启动）
- **根因 1（堆损坏 0xc0000374）**：UIA 兜底判定跨线程使用 COM 对象——`_UIA_AUTO` 在模块加载时于主线程创建（comtypes.CoInitialize 主线程），而 `_uia_focus_is_text()` 被 `NumpadPlayHook._proc`（**钩子线程**）调用 → 钩子线程直接用主线程的 COM 对象 = 未定义行为 → 堆损坏。触发条件：前台是 Chromium/Electron 类窗口（DSH Desktop 本身、新版 QQ/微信）+ 按小键盘数字
- **修复 1**：UIA 对象线程本地化——新增 `_uia_auto()`（threading.local 缓存 + 每线程 CoInitialize/CreateObject），`_uia_focus_is_text` 改用当前线程自己的对象；钩子线程不再跨线程碰 COM
- **根因 2（Qt6Core 0xc0000409）**：运行中的 QThread 被 Python GC 回收——`_speak_text`/`_rewrite_for_tts`/`_on_send` 每次新建 worker 直接覆盖 `self._tts_worker`/`_rewrite_worker`/`_ai_worker` 引用，旧 worker 若还在运行（TTS 502 重试中 sleep 0.5）→ 被覆盖后引用归零 → GC 销毁运行中的 QThread → Qt "QThread: Destroyed while thread is still running" fail-fast（0xc0000409）
- **修复 2**：新增 `_keep_worker(w)` 保活列表——所有后台 worker 创建后加入 `_workers_keepalive`，finished 信号时移除；旧 worker 结束前始终持有引用，杜绝 GC 回收运行中 QThread
- **根因 3**：`NumpadPlayHook._proc`/`KeyCapture._proc` 钩子回调无整体 try/except——Python 异常穿出 C 回调边界会直接崩进程
- **修复 3**：两个钩子回调整体 try/except，异常时放行按键（不吞键、不崩）
- **验证**：py_compile ✅；import 冒烟 ✅；钩子线程模拟（非主线程调 `_uia_auto()` 拿到独立对象、二次调用命中缓存、主线程对象与线程对象不同）✅；待重新打包 exe 实测
- 涉及：`pet.py`（_uia_auto/_uia_focus_is_text/_proc×2）、`ai_chat.py`（_keep_worker/_workers_keepalive/三处 worker 创建）
- git：（待提交）

### 2026-09-08（世界书 AI 调研大扩充 + 自动翻转开关）
- **世界书扩充（11 个 subagent 并行调研，详见 `_worldbook_drafts\RESEARCH-LOG.md`）**：
  - 全局 `world_book.json` 21 → **155 条**（新增：武器库 38 条【含 24 把角色专属武器+原型】、玩法机制 26 条、地图地点 18 条、剧情时间线 16 条、世界观补全 16 条、概念名词 9 条、社区梗 10 条等）
  - 角色书 24 → 28 份（新增 莉莉丝/诺诺 角色书；全名并入简名文件：奥黛丽·格罗夫→奥黛丽、玛德蕾娜·利里→玛德蕾娜、加拉蒂亚·利里→加拉蒂亚、米雪儿·李→米雪儿）
  - 双写：源码 `assets/` + 数据目录 `卡丘简易桌宠数据\assets\`；运行中的 exe 重启后才加载
- **新增功能：自动面向屏幕中央开关**（`auto_facing`，默认开）：
  - 桌宠跨屏幕左右半屏时平滑翻转朝向（cos 曲线转身动画）——原机制保留，新增开关可关闭
  - pet.py：`self._auto_facing`（读 `_cfg.get('auto_facing', True)`）、`_update_facing()` 开头守卫、新 `set_auto_facing(on)`（即时生效+写 pet_config.json）
  - settings_panel.py：形象角色区新增「自动面向屏幕中央（拖到另一半屏时翻转朝向）」勾选框 + `_on_auto_facing_toggled` + refresh_all 同步
  - 验证：py_compile OK；ruff 新增行无报告（131 个既有样式告警与本改动无关）
  - 涉及：`pet.py`、`settings_panel.py`、`assets/world_book.json`、`assets/role_worldbooks/*.json`、`DEVELOPMENT.md`
- 排队中：persona 深研（24 角色系统提示词，agent 产出中）、11 领域审核（review/ 报告收集中）

### 2026-09-08（世界书审核修复 + 全中文对齐 + 24 角色 persona 部署 + TTS 提示词重构）
- **世界书审核**：11 个原调研 agent 交叉审核（`_worldbook_drafts\review\*.md`，11 份报告），按【需修正】统一修复（`_fix_worldbook_review.py`，74 处替换）：
  - 阵营修正：普雷顿=剪刀手控制（剧情设定）、伊莱特隆/纽特朗=乌尔比诺实控、斯崔恩=缓冲地带（删查无的「弗雷特斯联邦」）
  - 剧情修正：赤刃行动(2023 科莫斯塔)与桎化行动(2025 普雷顿塔)拆分互指；绯莎非欧泊搜查官（神秘雇主赏识入乌尔比诺）；莉莉丝=七魔神之一（非首领级）；白墨词条笔误；第六赛季精确 2024.7；删无据「DSA」；奥黛丽失忆标「官方未证实」；崩溃症「百年」标社区口径
  - 武器/角色：雨晦 keys 去 Nobunaga、破晓=剪刀手、欺诈师=先锋位、潮音=杠杆式、莉莉丝=鞭武器、香奈美身高 161、明 CV=喵酱（Mace）、珐格兰丝武器笔误
  - 数值：星绘临时护甲更新现行版本（自身300/队友200/大招1500）；爆破数值标现行版本；晶能冲突补旧值
- **全中文对齐**（`_align_chinese.py`）：52 文件、156 条 content 清理英文括号注释、删除 82 个纯英文 keys、定位术语统一国服口径（哨兵→守护、Sentinel→移除等），残留 0
- **persona 部署**：24 角色新 persona（agent 深研，官方台词/称呼「引航者」/诺诺本名「夜守诺」）已覆盖 `assets\persona\` + 数据目录
- **TTS 提示词重构**（基于 Breeze-TTS-2 调研 `_worldbook_drafts\breeze_tts_guide.md`）：
  - `ai_chat.py` default_tts_prompt 升级：instruction 写「行为/语气/节奏」+ [笑][叹气] 情绪标记、数字/英文/多音字注音、标点控停顿、长句拆短（保持「情绪：/朗读：」两行格式）
  - `settings_panel.py`：TTS 提示词区重构为「✏️ 编辑提示词… + 恢复默认 + 摘要」；新增 `TtsPromptDialog` 编辑器弹窗（3 个预设：通用均衡/情绪生动/长段防机械 + 恢复内置默认 + 保存）；删除旧 `ed_ai_ttsprompt` 与 `_ai_apply_ttsprompt`
  - 验证：py_compile + import 冒烟 OK
  - 涉及：`ai_chat.py`、`settings_panel.py`、`assets\persona\*.txt`（24）、`assets\world_book.json`、`assets\role_worldbooks\*.json`、`DEVELOPMENT.md`

- **用户要求**：验证桌面 `卡丘简易桌宠_最新.exe` 的世界书是否正常生效
- **验证方法**（数据目录 = `C:\Users\mier\Desktop\卡丘简易桌宠数据`）：
  1. 数据文件健康：`assets\world_book.json`（11,641B，UTF-8，21 条 entries，与源码同时间戳同大小）+ `assets\role_worldbooks\` 24 角色书齐全 ✅
  2. 配置：`pet_config.json → ai.world_book_enabled = true` ✅
  3. 调用链：`ai_chat.py:2830-2834` 发送前 `_inject_world_entries(msgs, text)`（角色书全常驻 + 全局常驻/关键词命中 → system 尾部【世界知识】段）✅
  4. 命中逻辑实跑（脚本 `_verify_worldbook.py`，8/8 断言）：「汐，乌尔比诺最近有什么新闻吗？」命中 11 条（汐角色书 8 条 + 全局常驻 3 条），注入块拼装正确 ✅
- **结论**：世界书机制正常；注入发生在每次发消息时（contexts 存盘无注入痕迹属正常设计）。端到端确认：跟角色说带关键词的话（如问「乌尔比诺」），模型回复会引用世界书内容
- **系统检修**交出 3 处修复：
  1. **panel_smoke3.py 修崩溃**：原脚本引用了早已被删的控件 `cmb_ai_tts_mode`/`cloud_voice_box`（早期「cloud/local/api 三引擎下拉」时代产物，现已精简为唯一的 API 地址表单），一跑就 `AttributeError` 崩测试。已按当前设计重写：断言 `api_tts_box` 表单/克隆三件套/模型版本下拉存在、展开 AI 区后可见、填字段保存、缺字段提示、滑块禁滚轮、refresh 后可再用 → 全绿。
  2. **卡丘简易桌宠.spec 去本机绝对路径**：`runtime_hooks` 原来写死 `C:\Users\mier\Desktop\deepseek work\dsh-desktop-pet\rthook_fix_urllib_ssl.py`，换机/换目录打包会失败、且泄露本机路径。改为相对路径 `rthook_fix_urllib_ssl.py`（cwd=仓库根时正确解析，已验证）。
  3. **工程完整性：spec 入库**：`*.spec` 原在 .gitignore 里，导致打包配置永不提交（换机 clone 后无法 `PyInstaller 卡丘简易桌宠.spec`）。因 spec 已通用化（无本机路径），移除该忽略规则，把 spec 纳入版本控制；rthook_fix_urllib_ssl.py 本已跟踪。
- **全量审查结论**：pet.py / ai_chat.py / settings_panel.py 三核心源码通读，质量高——崩溃加固（switch_role 菜单延后/不重开）、QSoundEffect 播放（isPlaying 安全读/同步 stop 无竞态）、会话磁盘持久化（角色独立/只删不建）、世界书注入、延迟显示均健壮；静态扫描的"重复定义"均为不同类同名方法（正常），`except Exception: pass` 多为 Qt 回调保护性吞异常；print 密集但都在 except/低频 setter，无热路径拖累；资源一致性 24 角色 persona/worldbook/tts_refs/trigger_voice 全对齐。
- **验证**：8 个冒烟全绿（ai_selftest/session16/usage16/history23/bubble/panel_smoke2/panel_smoke3/gui）；离屏切角色压力 30 次含 gif 角色 exit 0 ✅
- 涉及：`panel_smoke3.py`、`卡丘简易桌宠.spec`、`.gitignore`、`DEVELOPMENT.md`
- git：549098b 之后的本提交

### 2026-09-08（目录结构订正 + 删除早期 C# WPF 调研版 DesktopPet.cs）
- **目录结构订正**：第 3 节原来停留在「星绘/白墨 早午晚」旧时代，与现状严重不符，已按实际重写——顶层含 `ai_chat.py`/`settings_panel.py`/`卡丘简易桌宠.spec`/`rthook_fix_urllib_ssl.py`；角色图为**阵营/角色/形象**三级结构（乌尔比诺7 / 剪刀手9 / 欧泊）8 角色）；语音从角色目录迁到 `trigger_voice/<角色>/卡拉彼丘.mp3`；新增 `common_voice`/`persona`/`tts_refs`/`role_worldbooks`/`world_book.json`/`app.ico`
- **删除 DesktopPet.cs**（及本地 DesktopPet.exe）：user 确认无用即删。该文件是 2026-09-04（项目第 0 天）的 C# WPF 早期调研草稿，仅 8.5KB，只实现了透明窗口+点按动画+早午晚播报；现生产已全面迁移到 PyQt6 完整版（pet.py+ai_chat.py+settings_panel.py），无保留价值。重写为 Rust/Zig/C++ 的方案经评估否决（工程量大、Qt 跨语言封装会重踩崩溃坑、性能瓶颈在 Qt 而非语言）。git 历史可回溯该文件
- 涉及：删除 `DesktopPet.cs`、`DEVELOPMENT.md`（第 3、6 节）
- git：随 58bdf09 之后的本提交

### 2026-09-08（游戏运行中切角色崩溃：菜单重开加固 + 崩溃诊断 dump/日志）
- **问题（用户）**：玩卡拉彼丘时切换角色直接崩溃（桌宠整个消失）；Windows 事件日志 BEX64 0xc0000409 Qt6Core.dll 固定偏移 0x1c8d8（多次）
- **分析**：源码/离屏均无法复现（单类/组合/菜单 20-30 次都不崩）→ 差异在**游戏全屏/锁鼠标环境**下 Qt QMenu popup 交互。崩溃前日志常有 TTS [请求]（游戏里按语音键）但用户确认与 TTS 无关
- **加固修复**（`pet.py`）：
  1. **切角色后不再自动重开菜单**（去掉 `_schedule_menu_refresh` 调用）——游戏全屏/鼠标被捕获时 QMenu popup 重开是 0xc0000409 高危点；切完自然关闭
  2. `switch_role` 的 UI 刷新全部延后（refresh_tray_menu singleShot(0)、面板刷新 singleShot(80)），脱离 QMenu triggered 回调栈
  3. 新增 `_refresh_panel_after_switch` 延后刷新面板
- **崩溃诊断**（下次崩溃自动留证据）：
  1. main() 加 faulthandler + sys.excepthook → 写数据目录 `crash_diag.log`（Qt C++ 崩溃时留各线程 Python 栈）
  2. pet.py/ai_chat.py 关键操作插桩日志（switch_role/switch_to_role）
  3. Windows LocalDumps 已配置（HKCU WER）→ 崩溃自动留 `_crashes\卡丘简易桌宠_最新.exe.*.dmp`（后续可分析 C++ 栈）
- **验证**：编译 OK；菜单式切角色 30 次（含 gif 角色）exit 0 ✅；回归 session16/usage16/history23/gui/panel2 全绿 ✅
- 涉及：`pet.py`、`ai_chat.py`（_dbg）
- git：（待提交）

### 2026-09-07（AI 朗读迁移 QSoundEffect：无声+崩溃双修；退出桌宠自动停 TTS；Q8 开箱即用 zip 交付）
- **问题（用户）**：①语音播报不发声；②（继续）播放/切角色崩溃；③新增：退出桌宠顺手关 TTS 服务；④Q8 模型开箱即用版（新 Win11 无 CUDA/Python）打包
- **无声根因**：崩溃修复时引入 `_stop_player_safe`（singleShot(0) 延后 stop）→ 排在 `setSource/play` 之后执行 → **刚启播的音频立刻被停 → 无声**；且启动 450ms `_apply_role_ai_profile_on_start` 的 `_invalidate_pending` 同样延后 stop 会杀新播放
- **崩溃深层根因（升级认知）**：QMediaPlayer 在本环境（PyQt6 6.11.2/Qt6.11.2/Py3.14）不仅连槽崩，**播放中读 playbackState() 也崩**（0xc0000409）——任何 Python 侧交互都触发
- **修复：AI 朗读整体迁移 QSoundEffect**（`ai_chat.py`）：
  - `__init__` 新增 `self._sfx = QSoundEffect()`（音量按 tts_volume 限 0~1）
  - `_on_tts_done` 播放改 `_sfx`（同步 stop→setSource→play，无延后竞态；蹦字 100ms 延后；dur+400ms 后清理临时文件；QSoundEffect 自然播完不崩）；QMediaPlayer 仅作 _sfx 初始化失败的兜底
  - `play_audio_file`（试听）同步改 _sfx；`is_speaking`/`_do_stop_player` 操作 _sfx
  - **实测**：启动完成后播放 0.8s/2.4s isPlaying=True（有声）→9.4s 自然播完→全程 exit 0 不崩 ✅
- **退出停 TTS**（`pet.py` closeEvent）：退出前调 `ai_chat.tts_service_stop()`（停桌宠启动的 audiocpp_server 进程）
- **Q8 开箱即用 zip**（subagent 完成）：`<桌面>\BreezeTTS2-Q8.zip`（5.94GB，顶层英文目录，UTF-8 防乱码，7z 校验 OK）；内容 bin(CUDA 全套)/models/Q8 gguf 4.73G/model_specs/refs_en 24角色/start·test·stop bat/使用说明（目标机免装 CUDA+Python，须解压纯英文路径，桌宠填 127.0.0.1:8080/v1 + breeze-tts-clone + 模型版本选量化 q8）
- **验证**：QSoundEffect 全链（有声/不崩/is_speaking/自然播完）✅；回归 session16/usage16/history23/gui/panel2 全绿 ✅
- 涉及：`ai_chat.py`（QSoundEffect 迁移）、`pet.py`（closeEvent 停 TTS）
- git：（待提交）

### 2026-09-07（根治崩溃：QMediaPlayer 播放状态槽触发 Qt6Core 0xc0000409 + 点按不打断朗读）
- **崩溃调查（用户多次反馈：发话完崩/切角色崩）**：Windows 事件日志 BEX64 0xc0000409 Qt6Core.dll。逐点复现（真实 GUI）最终锁定：
  - **根因**：QMediaPlayer（AI TTS 播放器）**只要连接了 playbackStateChanged 的 Python 槽**（无论 Auto/Queued 连接、无论槽内是否 disconnect），播放 mp3/wav 数秒即触发 Qt6Core 0xc0000409 崩溃（无槽裸播稳定 exit 0；300ms 短播不崩、播数秒崩）——PyQt6 6.11.2 + Qt 6.11.2 + Python 3.14 播放器状态信号派发 bug
  - 此前代码 `_on_tts_done` 连接 `_on_state`（Playing 蹦字）+ `_cleanup_on_state`（停播清理）→ 每个 TTS 语音播放都埋雷；上一轮把 30s 强杀改自然结束后更频繁触发
  - **修复**：`_on_tts_done` 播放路径**完全移除 playbackStateChanged 槽**，改纯 QTimer 时序：`QTimer(180ms)` 延时蹦字（不依赖 Playing 信号）→ `QTimer(dur-120ms)` 到时主动 `_stop_player_safe()`（避开自然结束崩溃路径）→ 250ms 后清理临时文件；5 分钟极长兜底
- **新增行为（用户）**：TTS 朗读中点按桌宠 → `is_speaking()` 检测播放器 Playing → `play_click_voice` 直接 return（不打断朗读、不播点按触发音）；TTS 播完（主动 stop 后状态回 Stopped）才恢复点按播报
- **验证**：无槽完整播 8.3s wav exit 0 ✅；6 轮综合压力（切角色+播 wav+延迟小字）exit 0 ✅；裸播 300ms 带槽不崩/数秒崩对照确认根因 ✅；回归 session16/usage16/history23/gui/panel2 全绿 ✅
- 涉及：`ai_chat.py`（_on_tts_done 纯 QTimer 化/is_speaking）、`pet.py`（play_click_voice 朗读中抑制）
- git：（待提交）

### 2026-09-07（启动角色与 AI 配置不同步修复 + 输入条旁加清理上下文按钮）
- **问题（用户）**：①刚启动桌宠图标是星绘但声音是白墨（上次残留配置），重新切换才正常；②清理上下文按钮需在输入框旁也有一个
- **修复**（`pet.py` + `ai_chat.py`）：
  1. **启动同步**：`PetWindow.__init__` 加 `QTimer.singleShot(450, _apply_role_ai_profile_on_start)`——启动后按当前角色应用 AI 配置（TTS 克隆 ref/系统提示词写星绘等）+ `ai.switch_to_role(角色)` 切会话；清掉上次关闭残留的其它角色克隆参考
  2. **输入条清理按钮**：ChatWindow 布局「📖查看上下文」后加「🧹」按钮（30px，红调，tooltip 清理当前角色上下文）→ 复用 `_clear()`→clearRequested→clear_context
- **验证**：离屏模拟残留白墨配置 → 启动应用后 ref 变 Celestia.wav（星绘）+会话切角色:星绘 ✅；真实 GUI 清理按钮存在/点击消息归零/气泡反馈可见/exit 0 ✅；回归 session16/usage16/history23/gui 全绿 ✅
- 涉及：`pet.py`、`ai_chat.py`
- git：（待提交）

### 2026-09-07（紧急修复：对话完成崩溃 0xC0000409（DelayWidget 自绘）；输入条改为「查看上下文」按钮；历史窗加「清理上下文」）
- **崩溃报告（用户）**：给角色发话完直接崩溃；Windows 事件日志：BEX64 / 异常 0xc0000409 / Qt6Core.dll 偏移 0x1c8d8（多次复现，exe 与 python 源码模式都崩）
- **定位**：分阶段复现（真实 GUI，非 offscreen）→ 锁定 **DelayWidget 连续两次 show_delay 即崩**（0xC0000409）；屏蔽 paintEvent / 换 QLabel 内嵌文本方案 → 不再崩。根因：DelayWidget 自绘 paintEvent（QPainter 画圆角底+drawText）在**透明无边框 Tool 窗连续 show/resize/update** 时触发 Qt6Core 崩溃（与 BubbleWidget 的差异待考，但 QLabel 方案稳定）
- **修复**：DelayWidget 重写为 QLabel 内嵌两行文本（样式化背景+圆角，`_lbl1` 价格米白 12px / `_lbl2` 延迟浅蓝 11px），无自绘 → 复现脚本 4 轮 tick（含连续 delay 显示+清理+删除）exit 0 ✅
- **输入条改造**：会话下拉/删除按钮区 → 替换为「📖 查看上下文」按钮（118px，点开发 historyRequested → show_history）；combo_session/新建/删除隐藏保留兼容
- **历史窗增强**：标题栏加「🧹 清理上下文」按钮（红色调），clearRequested 信号 → manager `_history_clear_ctx`（清空当前角色上下文 + 历史窗立即刷新为空）
- **验证**：真实 GUI 冒烟——查看上下文按钮可见/下拉隐藏/历史窗清理按钮存在/清理后消息 0/延迟小字连续两次不崩（exit 0）✅；回归 session16/usage16/history23/gui 全绿 ✅
- 涉及：`ai_chat.py`（DelayWidget 重写/ChatWindow 布局/历史窗清理）
- git：（待提交）

### 2026-09-07（世界书编辑器支持「全局/当前角色」双范围 + 管理按钮调大）
- **需求**：①「管理世界书」按钮太小；②每个角色单独世界书要能自己编辑/补充
- **实现**（`settings_panel.py`）：
  1. `_world_book_paths(fname, role)` 支持指定文件名/角色（全局 world_book.json / role_worldbooks/<角色名>.json）
  2. `WorldBookEditor(role=)` 支持角色范围——标题/提示注明当前编辑范围；`_load/_write` 按 role 指向对应文件；`_open_worldbook_editor` 弹 QInputDialog 选「全局世界书」或「当前角色：XX」再打开
  3. 「管理世界书」按钮调大：高 22→28、宽 132、金色描边样式、文案「📖 管理世界书…」
- **验证**：全局编辑器 21 条 / 米雪儿角色编辑器 10 条（路径正确）✅；全量回归（session16/usage16/history23/gui/panel2）全绿 ✅
- 涉及：`settings_panel.py`
- git：（待提交）

### 2026-09-07（会话重构 v2：每角色独立上下文文件/只删不建 + 每角色专属世界书 + 桌宠正下方延迟价格小字）
- **需求（用户）**：①每个角色独立上下文文件（磁盘持久化）；②会话不可以创建只能删；③选角色看上下文文件不出现默认会话；④每角色单独世界书（去 wiki 搜，可花更多时间）；⑤删掉某角色上下文后切回该角色自动恢复；⑥每次对话在桌宠正下方显示 LLM/TTS 延迟与 API 价格（两行，延迟用秒）
- **会话重构**（`ai_chat.py`）：
  1. **磁盘持久化**：`contexts/role_<角色名>.json` 每角色一个文件；启动 `_load_role_sessions_from_disk()` 加载（**无「默认会话」**）；`_on_send/_on_ai_done` 追加消息后 `_save_session_disk` 写盘
  2. **只删不建**：`new_session` 返回 `(False,'会话不可新建…')`；输入条「＋新建」按钮隐藏；`delete_session` = 清空该角色上下文（内存 clear + 磁盘写空数组），**角色会话保留**（删后切回自动空会话）
  3. `switch_to_role` 切角色自动建/选该角色会话；清角色世界书缓存
- **每角色专属世界书**（subagent 深挖 wiki 誓约页/语音台词/角色页）：`_pet_data/role_worldbook_info.json`（24/24，每角色 identity/relationships/story_events/signature_quotes(5条)/mystery）→ 生成 `assets/role_worldbooks/<角色名>.json`（每角色 5-12 条全常驻）；`_world_entries_for` 注入顺序 = **当前角色世界书全部常驻** + 全局（常驻+关键词）；`_current_role_name` 优先从会话名反推（不依赖 pet.role），切角色清缓存
- **桌宠正下方小字**：新增 `DelayWidget`（两行半透明小字：第一行 $费用(6位小数)、第二行 LLM x.xxs · TTS x.xxs）；`_show_delay_widget()` 在 `_show_usage`（AI 回复完成显价格+LLM）与 `_on_tts_done`（补 TTS）调用；5 秒自动消失/点击关闭/跟随桌宠（正下方，放不下转上方）
- **测试更新**：`session_smoke.py` 重写为新语义（无默认会话/角色会话隔离/禁新建/清空保留角色/世界书注入/延迟后缀）16 项全过；usage16/history23/gui/panel2 全绿
- **验证**：磁盘持久化(切走切回恢复)✅ 清空角色保留+切回自动空✅ 禁新建✅ 角色世界书随角色切换注入不同(米雪儿↔星绘)✅ DelayWidget 两行($0.000056→6位小数/LLM 1.23s·TTS 0.57s)✅
- 涉及：`ai_chat.py`、`session_smoke.py`、`assets/role_worldbooks/`（24新）、`session_smoke` 更新
- git：（待提交）

### 2026-09-07（世界书开关+自编辑管理器 + 角色列表滚轮穿透修复 + 克隆音频量化版本选项）
- **需求（用户）**：①世界书功能要可开关、可自行补充/修改条目；②选角色页面滚轮到头会滑动整个面板（不好选）；③克隆音频新增可选量化版本（q8 省显存 / bf16 高音质）
- **实现**：
  1. **世界书开关**：设置 AI 区新增「📖 启用世界书」开关（chat 逻辑 `worldbook_enabled/set_worldbook_enabled`，配置 `ai.world_book_enabled` 默认 True；`_inject_world_entries` 尊重开关）
  2. **世界书管理器**：新增 `WorldBookEditor(QDialog)`（按键名列表 + 编辑区：键名/关键词(逗号分隔)/常驻勾选/内容 + 新增/删除/保存）；保存写回 world_book.json（数据目录+源码双写）并清 manager 加载缓存（下次对话生效）；入口「管理条目…」按钮
  3. **滚轮穿透修复**：新增 `NoWheelList(QListWidget)`（wheelEvent 先 super 滚动再 accept 吞掉事件，防传播外层 QScrollArea）；`role_list`/`audio_list` 改用
  4. **量化版本**：设置朗读区新增「模型版本」下拉（自动/高音质 bf16/量化 q8）；`_models_paths(kind)` 按 kind 过滤；`tts_service_start` 读 `ai.tts_model_kind` 按选择加载
- **修复**：settings_panel 缺 `import json`（世界书编辑器 json.load 全部静默失败）
- **验证**：模型版本筛选 auto5/bf16/q8 ✅；世界书开关三态+关闭不注入 ✅；编辑器加载 21 条+选中编辑 ✅；NoWheelList ✅；回归待跑
- 涉及：`settings_panel.py`、`ai_chat.py`
- git：（待提交）

### 2026-09-07（AI 对话大改：会话防串台重构 + 24角色丰富人格 + 酒馆式世界书 + 延迟显示完善）
- **需求（用户）**：①会话管理太麻烦，切角色会冒出上个角色配置（需大改）；②看 token 金额 + LLM 延迟 + TTS 延迟；③全部角色人格提示词要丰富（上网收集）；④做类似酒馆 World Info 的世界书（角色剧情关键词触发注入）
- **人格资料**（subagent 采集）：wiki.biligame.com 24 角色页 raw + 语音台词页抓取 → `_pet_data/char_info.json`（role_desc/personality/voice_style/values/traits/quotes 全真实，24/24）；生成器产出 `assets/persona/<角色名>.txt`（丰富人格提示词，24 个；米雪儿/奥黛丽/玛德蕾娜/加拉蒂亚用短名文件）
- **世界书**（subagent 采集）：wiki/萌娘/官网 → `_pet_data/world_lore.json` → 生成 `assets/world_book.json`（21 条：阵营3常驻 + 概念7 + 事件5 + 关系6，真实来源标注）
- **实现**（`ai_chat.py` + `pet.py`）：
  1. **会话防串台（根因修复）**：`_on_send` 记录 `_send_session`，`_on_ai_done` 校验不一致则丢弃回复（不写新会话/不 TTS）；`_invalidate_pending()`（seq 递增+停播放器+清 _synced_text+清 _send_session+停三点）统一在 `switch_to_role/switch_session/new_session` 调用 → 切角色/切会话瞬间在途旧请求全部软失效，不再污染新会话
  2. **Bug3 修复**：`clear_context` 用 `self._messages.clear()` 就地清空（原来 `=[]` 脱离 _sessions 导致切走切回旧消息复活）
  3. **配置不残留**：`switch_to_role` 清 `_last_usage/_last_delay`；`_apply_role_ai_profile` 优先 persona 文件（assets/persona/<角色名>.txt），无则模板；无素材角色回退用户默认（不沿用上一角色）
  4. **世界书注入**：`_load_world_book/_world_entries_for/_inject_world_entries`——`_on_send` 构造 msgs 后按用户文本关键词命中条目 + 常驻阵营条目 → 注入 system 末尾【世界知识】段（修复 assets 路径重复拼接 bug）
  5. **延迟文案**：`_delay_suffix` API→**LLM** 明确命名；显示 `本次 … tok ≈ $x · LLM 1234ms · TTS 567ms`
- **验证**：世界书 21 条加载/关键词[星庇所]命中4条/常驻3条/注入998字含【世界知识】✅；persona 24 存在 ✅；会话防串台（切走后 _send_session=None）✅；回归 session 25 / usage 16 / history 23 / gui / panel2 全绿 ✅
- 涉及：`ai_chat.py`、`pet.py`、`assets/persona/`（24新）、`assets/world_book.json`（新）、`_pet_data/`（资料源）
- git：（待提交）

### 2026-09-07（每角色独立上下文 + 对话结束显示 API/TTS 延迟）
- **需求（用户）**：①每个角色独立上下文（各自的对话历史互不干扰）；②每次对话结束，在下方显示语言模型 API 延迟 和 TTS 合成延迟
- **实现**（`ai_chat.py` + `pet.py`）：
  1. **角色分会话**：`AiChatManager` 新增 `role_session_name(role)`（`角色:<角色名>`，多形象按角色名归并）与 `switch_to_role(role)`（切角色自动建/切到该角色会话）；`PetWindow.switch_role` 里调用 → 每个角色聊天历史独立，切回角色恢复自己上下文
  2. **API 延迟**：`_on_send` 记 `_api_t0`（monotonic），`_on_ai_done` 计算 `api_ms` 存 `_last_delay['api']`，随用量行显示
  3. **TTS 延迟**：`_speak_text` 记 `_tts_t0`，`_on_tts_done`（音频就绪）计算 `tts_ms` 存 `_last_delay['tts']` 并刷新显示
  4. **显示**：`_delay_suffix()` 生成 `· API 1234ms · TTS 568ms` 后缀，`_show_usage`/`_sync_chat_usage`/`_refresh_delay_line` 追加到聊天条用量行下方（本次 输入↑…输出↓ 共N tok ≈ $X · API 1234ms · TTS 568ms）
- **验证**：角色会话名/切换/消息隔离（切米雪儿→星绘→切回消息保留）✅；延迟后缀三态（双值/仅API/空）✅；session_smoke 25 项回归全过 ✅
- 涉及：`ai_chat.py`（AiChatManager 会话/延迟）、`pet.py`（switch_role 接 switch_to_role）
- git：（待提交）

### 2026-09-07（修复 TTS 启动/合成 500 + 设置面板角色列表按阵营分组 + 克隆参考英文路径）
- **问题（用户）**：①"启动 TTS 功能有问题"——本地录音服务跑不起来/合成 502；②设置面板角色列表平铺无阵营，不好挑角色；③TTS 参考语音路径太长且为中文路径
- **TTS 根因**：
  1. `_AUDIO_CPP_SERVER` 只找 `ai_chat.py` 同级 `audio-cpp/bin-cuda/`（源码/打包内不存在）；服务实际部署在 `breeze-tts-local/audio-cpp/bin-cuda` → 找不到服务程序 → 8080 无监听 → 请求 502
  2. 模型查找 `_models_paths()` 只搜 `svc_dir/models`（bin-cuda/models 空），真模型在上一级 `audio-cpp/models`（q8 4.7G / bf16 6.8G）
  3. **audiocpp_server 只支持纯 ASCII 路径/文件名**：克隆参考在中文路径（`卡丘简易桌宠数据/...`）下报 "could not open WAV input" → 合成 HTTP 500；复制到纯英文目录 `references/refs_en/<英文名>.wav` 后合成 OK
- **修复**（`ai_chat.py`）：`_find_tts_server()` 多级候选（环境变量→同级→数据目录→breeze-tts-local 常见部署→_MEIPASS 打包场景向上探测）；`bind_pet_module()` 注入后重新定位；`_models_paths()` 增加上级 models 目录候选
- **修复**（`pet.py`）：新增 `ROLE_EN_NAMES`（24 角色英文名映射，源自 wiki）；`_apply_role_ai_profile` 克隆参考优先写纯英文路径（refs_en/<英文名>.wav），无副本回退中文 tts_refs
- **修复**（`settings_panel.py`）：`_refresh_role_list` 加阵营分组标题（— 欧泊 — 等，灰色加粗不可点，UserRole=None）；`_on_role_clicked`/`_delete_selected_role` 防点标题误操作
- **克隆参考英文副本**：24 角色 ref.wav+txt 已复制到 `breeze-tts-local/audio-cpp/references/refs_en/`（不含中文）
- **验证**：`tts_service_start()` 实测启动+加载 bf16 ✅；英文路径合成 276KB wav ✅；面板角色列表 27 项（3 阵营标题+24 角色）分组正确 ✅
- 涉及：`ai_chat.py`、`pet.py`、`settings_panel.py`、`assets/`（refs_en 外部目录）
- git：（待提交）

### 2026-09-07（语音功能最终形态：点按触发音=每角色"卡拉彼丘"台词；TTS克隆参考+系统提示词随角色自动切换）
- **需求澄清（用户纠正）**：之前下载的自我介绍台词**不是**点按触发音，而是**TTS 克隆语句**；点按触发音应该是每角色说"卡拉彼丘"那句；切换角色要自动切换 TTS 克隆配置与系统提示词
- **每角色"卡拉彼丘"触发音**：wiki 语音页每角色都有台词纯为「卡拉彼丘」的独立 mp3 → 全部下载成功 24/24，集中存 `assets/trigger_voice/<角色名>/卡拉彼丘.mp3`（角色目录保持干净只留形象图）
- **TTS 克隆参考**：自我介绍 mp3 → ffmpeg 转 24k 单声道 wav 集中存 `assets/tts_refs/<角色名>/ref.wav` + `ref.txt`（转录文本，23 个角色；星绘跳过保留原有 star_ref）
- **系统提示词**：每角色模板占位（性别区分，令/信/白墨=男其它=女）`assets/tts_refs/<角色名>/system_prompt.txt`
- **代码**（`pet.py`）：
  1. 模块级 `trigger_voice_dir(role)`/`trigger_voice_for(role)`/`pick_click_voice(d, role)`——触发音优先级：集中 trigger_voice → 角色目录非内置长名音频 → None（旧规则回退）
  2. `_apply_role_ai_profile(role)`：切角色时若 `tts_refs/<角色名>/` 存在 → 写 ai 配置 `tts_api_ref/tts_api_ref_text/system_prompt`（switch_role 内调用）；无素材角色（星绘）不覆盖用户配置
- **旧角色清理**：星绘 morning/noon/evening.mp3、白墨 sprint.mp3 已删（点按统一卡拉彼丘触发音）；配置 audio_hotkeys 中对应 4 条 Num 绑定已清空（保留 common 一条）
- **验证**：24 角色触发音齐全；pick_click_voice 离屏抽样（星绘/白墨/米雪儿→卡拉彼丘.mp3）✅；_apply_role_ai_profile 切米雪儿写 ref/ref_text/system_prompt、切星绘不覆盖 ✅
- 涉及：`pet.py`、`assets/trigger_voice/`（新增24）、`assets/tts_refs/`（新增23角色×3文件）、`assets/characters/`（清理旧语音）
- git：`5fdfdb3`（角色 AI 档案切换 + 触发音）+ 语音资源提交
### 2026-09-07（角色点按触发音 = 各角色自我介绍台词语音（wiki 下载）+ 修复菜单重复角色 Bug）
- **需求（用户）**：每个角色点按触发音用各自那句自我介绍（用户提供 23 句台词清单，星绘跳过保留时段问候）；旧角色（白墨/艾卡等）也要新触发音
- **语音来源调研**：biligame 卡拉彼丘 WIKI 每角色有「语音台词」子页（如 `米雪儿·李/语音台词`），页内 mp3 托管在 `patchwiki.biligame.com/images/klbq/`；**防爬**：直连 api.php/子页返回 567，需 Session 先 GET 主页拿 cookie 再访问（实测 UA/Referer 头为主因）；HTML 结构 = 每条语音一个 `<tr>`，td[0] 含 `.media-audio[data-file]` mp3、td[1] 台词文本（须剔除 smw 悬浮注释）
- **实现**：`voice_parser.py`（解析器，`parse_voice_page(html)->[{text,mp3}]`，subagent 产出）+ `download_voices.py`（23 角色批量：抓页→宽松归一化匹配台词→下载存「完整台词.mp3」到 数据目录+源码 assets 双写）
- **点按逻辑改造**（`pet.py`）：新增模块级 `pick_click_voice(d)`——角色目录里「非内置名(morning/noon/evening/sprint/click/hello)」音频取文件名最长者（即台词自我介绍）→ `play_click_voice`/`_preload_click_audio` 优先用它；无台词则旧规则（星绘时段/白墨 sprint/其它 morning）
- **Bug 修复**：菜单里星绘/白墨/艾卡出现两次——数据目录存在平铺残留（`characters/星绘/` 等）与阵营内（`characters/乌尔比诺/星绘/` 等）并存（旧版 exe seed 补回），`list_roles()` 两者都扫到；删除 3 个平铺残留目录 + dist 旧数据残留
- **下载结果**：22/23 一次成功；伊薇特台词与用户给的有差异（页面实际「我是伊薇特，这是我的伙伴，菲。呵呵，你一次认识了两个新朋友啊。」）单独修正下载 → **24 角色全有音频**（23 句台词 + 星绘保留 3 时段语音）
- **验证**：`pick_click_voice` 离屏 5 例（米雪儿/白墨/艾卡/伊薇特命中台词、星绘 None 走旧规则）✅；角色列表 24 无重复 ✅；py_compile ✅
- 涉及：`pet.py`、`DEVELOPMENT.md`、`assets/characters/`（各角色台词 mp3）、新增 `_voice_probe/`（voice_parser.py）、`download_voices.py`、`probe_*.py`（临时探测）
- git：（待提交）

### 2026-09-07（角色体系升级为「阵营/角色/形象」三级结构 + 导入欧泊/乌尔比诺/剪刀手 21 新角色）
- **需求（用户）**：①同角色可放多套形象；②角色按阵营分组：欧泊 / 剪刀手 / 乌尔比诺（晶源体不做）；③后续自动识别游戏角色并自动切换桌宠（识别可行性已另调研）
- **归属确认（用户）**：旧角色归阵营——星绘→乌尔比诺、白墨→乌尔比诺、艾卡→剪刀手；桌面三文件夹 `桌面\欧泊`（伊薇特/信/千代/心夏/忧雾/米雪儿/芙拉薇娅/蕾欧娜）、`桌面\乌尔比诺`（加拉蒂亚/奥黛丽/汐/玛德蕾娜gif/绯莎）、`桌面\剪刀手`（令/拉薇/明/梅瑞狄斯/玛拉/珐格兰丝/诺诺/香奈美）
- **新磁盘布局**：`assets/characters/<阵营>/<角色>/image.png(.gif)` + 语音在角色根；兼容历史平铺（`characters/星绘/` 无阵营）
- **实现**（`pet.py`）：
  1. 角色标识 `role` = 相对 chars_dir 的路径（可含 `/`）：`"欧泊/米雪儿"`、多形象 `"乌尔比诺/星绘/泳装"`
  2. 新增模块级函数：`role_dir(role)`（多级安全拼接）、`role_root(role)`（语音根=去掉形象段）、`role_display(role)`（显示名，多形象显示「角色·形象」）、`role_faction(role)`、`role_variant(role)`、`role_character_name(role)`（供星绘/白墨硬编码语音判断）、`default_role_pick(roles)`（默认优先找角色名=星绘）
  3. `list_roles()` 三级扫描：顶级目录含图=平铺角色；顶级目录无图→当阵营，扫其下角色（角色目录含图=默认形象；无图→形象子目录逐个列出）
  4. 硬编码 `self.role == "星绘"/"白墨"` → `role_character_name()` 判断；语音路径走角色根（多形象共用语音）
  5. 主菜单「切换角色」子菜单 `_fill_roles_menu()` 按阵营分组（组标题不可点+分隔线）；托盘/按钮/设置三处共用
- **实现**（`settings_panel.py`）：角色列表项 UserRole 存完整 role 路径（文本仅显示名）；`_on_role_clicked/_delete_selected_role` 取 UserRole；`_current_audio_dir` 走角色根；新增 `_faction_target_dir()`（导入/拖放默认落入当前角色阵营目录）
- **迁移执行**：桌面三文件夹 21 图已移入数据目录 `桌面\卡丘简易桌宠数据\assets\characters\<阵营>\<角色>\image.png`（gif 保留原名），桌面原件已清空；旧三角色迁入阵营；源码 assets/characters 同步同结构（打包种子）；旧音频键自动迁移 `星绘/x→乌尔比诺/星绘/x` 等（`pet_config.json` audio_hotkeys）
- **验证**：`role_smoke.py`（新增）21/21 ✅（扫描/阵营/显示名/默认选择/主图/语音枚举）；离屏 PetWindow 构造+4 角色切换 pixmap 正常 ✅（含 gif 艾卡/玛德蕾娜）；面板角色列表 24 项显示+UserRole+点击切换 ✅；菜单构建三阵营 29 动作 ✅；回归 session 25 / usage 16 / history 23 / gui / panel_smoke2 全绿 ✅
- **待办**：每个角色专属语音（用户稍后提供下载菜单 → 放入 `characters/<阵营>/<角色>/`，点按触发音自动识别 `click.mp3`/`morning.mp3`）；自动识别角色切换（BitBlt+OCR 已证可行，待用户进对局标定）
- 涉及：`pet.py`（角色模型/list_roles/菜单）、`settings_panel.py`（角色列表/删除/导入归阵营）、新增 `role_smoke.py`、`assets/characters/` 大改
- git：（待提交）

### 2026-09-07（卡拉彼丘"回车自动加喵"v6 最终可用方案：鼠标可见性判定 + PostMessage，实测通过）
- **需求**：卡拉彼丘聊天框打字按回车发送时自动在句尾补词（默认"喵"，可自定义、可开关）
- **排查过程（多轮实测发现的真相）**：
  1. 卡拉彼丘是 UE4 游戏，窗口类名 `UnrealWindow`；**不响应 SendInput** 注入的按键（首版失败根因）；但**响应 PostMessage**（WM_KEYDOWN/WM_CHAR 实测能打开聊天框、能打出中文"喵"）
  2. **系统层探不到聊天状态**：caret 恒 False、焦点类名恒 UnrealWindow、UIA 恒定假焦点、IME 状态不变——Windows API 无法直接判断"是否在聊天输入"
  3. **决定性信号**：卡拉彼丘正常操作时系统鼠标【隐藏/锁定】，按回车进入聊天栏后鼠标【可见】——鼠标可见性可可靠区分"进入聊天栏的回车"与"发送的回车"
- **最终方案（v6，实测可用）**：`MeowHook` 常驻低层钩子。前台为卡拉彼丘 + 回车按下 + **鼠标可见**（聊天栏已开=发送）→ 钩子回调内（先于游戏收到回车）**PostMessage WM_CHAR 逐字补词**，然后**放行真实回车**（不吞键）→ 游戏正常发送并关闭输入框。鼠标隐藏的回车（进入聊天栏）完全放行
- **验证**：
  - 单元三场景：鼠标可见回车→补"喵"(WM_CHAR 0x55B5) ✓ / 鼠标隐藏回车→不补 ✓ / 非目标游戏→不补 ✓
  - 源码真实验证（pet.MeowHook）：用户进游戏聊天打字回车自动加喵、发送正常、输入框正常关闭 ✅
  - 回归：session 25 / usage 16 / history 23 / bubble 全绿 ✅
- 涉及：`pet.py`（MeowHook 重写为 v6 + 新增 CURSORINFO 结构、WM_CHAR/WM_KEYUP/WM_SYSKEYUP/VK_RETURN 常量定义）
- git：`3fb0c6a`（v6 最终版）

### 2026-09-07（新增「卡丘游戏设置」栏：卡拉彼丘回车自动补词联动，可开关/自定义词）
- **需求**：在游戏（卡拉彼丘，官方启动器 + WeGame）聊天输入框打字按回车发送时，自动在句尾补一个词（默认"喵"，可自定义）
- **机制说明（重要）**：卡拉彼丘为 UE4（Unreal Engine）游戏，文字输入由引擎内部处理，系统层无法 100% 判定"是否在输入"。采用最稳的**启发式**：常驻低层键盘钩子（WH_KEYBOARD_LL）检测"目标游戏前台 + 开聊天后打了字 + 再回车"序列，才拦截回车并先注入补词再放行——纯菜单/换窗口回车（两次回车间未打字）不触发，避免误伤
- **实现**（`pet.py` + `settings_panel.py`）：
  1. 新增 `MeowHook` 常驻钩子类（仿 NumpadPlayHook：独立线程 GetMessage 循环驱动回调）；`_foreground_exe()` 抽取出前台进程名；`_send_unicode_text()` 用 SendInput(KEYEVENTF_UNICODE) 逐字注入 UTF-16 文本
  2. 目标进程名单：`calabiyau-win64-shipping` / 含 `calabiyau` 的进程名（官方版 + WeGame 都覆盖）
  3. PetWindow 新增配置：`_meow_enabled`（default False）、`_meow_word`（default 喵）、`_meow_hook`，方法 `_meow_hook_start/stop`、`set_meow_enabled`、`set_meow_word`；退出时在 closeEvent 停止钩子
  4. 设置面板新增独立折叠栏「🎮 卡丘游戏设置」（置于 快捷键/开麦 之后）：`chk_meow` 开关 + `ed_meow_word` 自定义补词输入框；refresh_all 回填状态
  5. **首版实测无效修复**：v1 的 `_send_unicode_text()` 直接在低层钩子【回调内部】执行 SendInput 注入并 `time.sleep(0.02)`——在钩子回调里阻塞会拖死全局键盘管线，且回调内注入的键常被系统丢弃/重入，导致"补词没反应"。v2 重构为：回调只【检测并吞掉发送回车】置 pending（return 1），真正注入推迟到钩子线程【消息循环空闲时】（PeekMessage 轮询 + `_process_pending()`）执行"补词 → 模拟回车 down/up"；并收紧可打印字符判定（排除方向键/F1-F12/编辑键），加 `_dbg` 日志便于实测
- **验证**：
  - MeowHook 状态机五场景单元级全过：直接回车不吞不放行 ✓ / 打字后回车吞键(pending) ✓ / 注入序列=补词+回车down/up ✓ / 发送后再回车不补 ✓ / 失焦重置不补 ✓
  - 设置面板「卡丘游戏设置」栏构建、开关与词输入、折叠开合、refresh_all 回填全部正常 ✅
  - 回归：session 25 / usage 16 / history 23 / bubble 全绿 ✅
- 涉及：`pet.py`（MeowHook/_foreground_exe/_send_unicode_text v2/配置字段与方法/closeEvent）、`settings_panel.py`（卡丘游戏设置折叠栏）
- **部署**：打包后替换桌面 exe（默认关闭该功能；需在 设置→卡丘游戏设置 手动开启）
- git：`ffd428a`（v1）+ `84c9e57`（v2 注入重构）

### 2026-09-07（交互收敛：悬停收起改 0.5s + 右键菜单去 AI 对话项只留用量 + 修复设置面板打开卡 2 秒）
- **需求**：① 鼠标离开桌宠后对话条改为 **0.5 秒**收起；② 右键桌宠的 AI 对话/新建/记录/清理功能都不需要了，**只留「查看用量」**（AI 交互已全由悬停对话条承担）；③ 打开设置面板等待变长、点 ✕ 收起也卡 → 需优化
- **实现**：
  1. `ai_chat.py`：`chat_bar_on_leave()` 延迟从 1000ms → **500ms**
  2. `pet.py`：`_build_ai_menu()` 瘦身为「📊 用量·积分 + 📈 查看统计详情」两项（删除 快速提问/新建会话/完整对话记录/清理上下文）；主菜单入口改名「AI 用量」；右键弹 AI 用量菜单不变
  3. **面板卡顿根因**：`settings_panel.py` 构造 `SettingsPanel` 时末尾**同步**调 `_refresh_tts_svc_state()` → `ai_chat.tts_service_health(timeout=2.0)`；本地 TTS 服务未启动时 socket 探测**等满 2 秒超时**才返回 → 主线程被阻塞 2 秒（打开面板卡、连点击响应都延迟）
  4. 修复：`_refresh_tts_svc_state(async_ok=True)` 改为**后台线程探测**，完成回主线程 `_probe_result()` 刷 UI；`__init__` 与 5s 定时器都走异步 → 构造不再阻塞
- **验证**：
  - 面板构造耗时实测 **2134ms → 93ms**（约 23 倍提速）；`refresh_all` 0ms；hide 2-3ms 立即收起 ✅
  - 首帧 show ~500ms（Windows 原生窗口+首帧样式渲染固有开销；后续 show/hide 均 <10ms）
  - 悬停分支受控验证：在桌宠上/输入条上不隐藏、离开才隐藏 ✅；0.5s 定时生效
  - 回归：session 25 / usage 16 / history 23 / bubble 全绿 ✅
- 涉及：`pet.py`（_build_ai_menu/AI 用量入口）、`ai_chat.py`（500ms）、`settings_panel.py`（_refresh_tts_svc_state 异步化 + _probe_result）
- **部署**：桌面 exe 已打包替换 `<user-desktop>\卡丘简易桌宠_最新.exe`（13:24，52.7MB，旧版备份为 _上一版）；启动验证正常 ✅
- git：`646094a`（交互收敛 + 面板提速）

### 2026-09-07（AI 对话条悬停交互：鼠标移到桌宠上自动展开、离开 1 秒后收起）
- **需求**：鼠标移到桌宠身上 → 直接显示下方对话条；鼠标离开桌宠 → 1 秒后对话条消失
- **实现**：
  1. `ai_chat.py` `AiChatManager.open_chat(focus=True)`：新增 `focus` 参数——`True`（右键快速提问）抢焦点聚焦输入框；`False`（悬停展开）静默显示不抢焦点、不打断用户在其它窗口的输入
  2. 新增 4 个悬停辅助方法：`chat_bar_on_enter()`（鼠标进宠：静默显示条并贴住桌宠）、`chat_bar_on_leave()`（启动 1s 单次定时器）、`chat_bar_cancel_hide()`（回到宠上取消）、`_do_hide_bar()`（1 秒后鼠标若仍停在桌宠/输入条内则再等 1s 轮询，真正离开才隐藏——避免鼠标从桌宠挪到输入条时被误收）
  3. `pet.py` `enterEvent` / `leaveEvent` 挂接：进入 → `ai.chat_bar_on_enter()`；离开 → `ai.chat_bar_on_leave()`（与原有三横按钮 1s 缓冲互不冲突）
- **验证**：
  - 单元冒烟（绑定 pet_mod 后）：进入→显示 ✓；鼠标在桌宠内/输入条上→不隐藏 ✓；离开→`_do_hide_bar` 隐藏 ✓；再进入→重新显示 ✓
  - 事件循环实测：`chat_bar_on_leave()` 启动后 1.6s 内输入条已隐藏（1s 延迟生效）✓
  - 回归：session 25 / usage 16 / history 23 / bubble 全绿 ✅
- 涉及：`ai_chat.py`（open_chat focus 参数 + 悬停显隐 4 方法）、`pet.py`（enterEvent/leaveEvent 挂接）
- **部署**：桌面 exe 已打包替换 `<user-desktop>\卡丘简易桌宠_最新.exe`（13:15，52.7MB，旧版备份为 _上一版）；启动验证正常 ✅
- git：`43be28b`（悬停交互改版）

### 2026-09-07（AI 交互改「极简模式」：横线输入条 + 右侧大字气泡 5 秒消失 + 去掉系统提示词）
- **需求**：
  1. 输入框要【随桌宠移动】（此前点输入条空白会永久取消跟随 → 拖动桌宠后输入条留在原地）
  2. 改成轻量交互：在桌宠正下方的一条「横线输入条」打字，回车发送后输入条自动收起
  3. AI 回复显示在桌宠【正右方】，无背景、大字体，显示完整后 **5 秒自动消失**
  4. **不显示系统提示词**（此前消息渲染会把 system_prompt 灰条置顶）
  5. 会话仍可新建/删除（入口并入输入条）；完整对话历史仍可回看（右键菜单「完整对话记录」）
- **实现**（`ai_chat.py`）：
  1. `ChatWindow` 由 470×340 大对话框（顶部工具行+中部消息流+底部输入行）**重构为 640×48 单行横条**：会话下拉＋新建＋删除＋输入框＋发送；`browser/btn_history/btn_clear/lbl_usage` 置 None（历史一律走独立 ChatHistoryWindow，set_content/set_usage 保留为空操作兼容）
  2. `_follow_pet()` 改为每 tick 按桌宠最新矩形把输入条钉在【正下方居中】（不保留拖动偏移）；`mousePressEvent` 点击空白只把焦点还给输入框、不再取消跟随 → **跟随 bug 根因修复**
  3. `_send()`：发送后 `self.hide()`（横条自动收起），AI 回复走右侧气泡
  4. `BubbleWidget`：字号 18→**24**；`_reposition()` 把气泡放到桌宠【正右方、垂直居中对齐】（放不下才转左侧）；`_BUBBLE_MAX_W 520→620`；自动消失保持 `_BUBBLE_LIFE_MS=5000`（蹦字完整后 5 秒隐藏，事件循环实测通过）
  5. `_msg_html()`：**删除 system_prompt 渲染块**（任何界面都不再显示「▍系统提示词」）
  6. pet.py AI 菜单首项文案：「💬 打开 AI 对话」→「✏️ 快速提问」，提示改为“下方弹输入条、发送后收起、回复右侧气泡”
- **验证**：
  - session_smoke 25 / usage_layout_smoke 16 / history_smoke 23 / bubble_smoke 13 / gui_smoke 全 PASS ✅
  - 独立事件循环验证：气泡蹦字完整 → 5 秒后自动隐藏 ✅；字号 24 ✅；输入条随桌宠从 (600,400) 移到 (700,500) 位置联动 ✅
  - 输入条尺寸断言 640×48；发送后自动隐藏；`_msg_html` 渲染不含任何系统提示词文案 ✅
- 涉及：`ai_chat.py`（ChatWindow 重构/_follow_pet/_send/BubbleWidget 字号与定位/_msg_html 去提示词）、`pet.py`（菜单文案）、更新 `session_smoke.py`/`usage_layout_smoke.py`/`bubble_smoke.py`/`history_smoke.py` 结构断言为新输入条
- **部署**：桌面 exe 已打包替换 `<user-desktop>\卡丘简易桌宠_最新.exe`（13:03，52.7MB，旧版备份为 _上一版）；启动验证正常 ✅
- git：`5d2b7f3`（AI 极简交互改版）

### 2026-09-07（AI 对话框布局微调 + BreezeTTS2 CUDA 桌面分发 zip 打包）
- **需求**：
  1. AI 对话框布局：①聊天窗默认显示在桌宠【正下方】紧贴底部（水平居中对齐）；②对话内容消息文字【靠右、去掉气泡底色块】，只留清晰文字；③会话支持【删除】（不只新建）
  2. 把本地 TTS（audiocpp_server / BreezeTTS 2）打包成「有 NVIDIA 显卡开箱即用」的 zip：含 CUDA 运行库 + 双模型(q8/bf16) + model_specs + 星绘语音克隆 references + 启动/测试/停止 bat
- **实现**（`ai_chat.py`）：
  1. `ChatWindow.show_near`：位置改为桌宠正下方紧贴底部（x 居中于宠中心、y=bottom+6），下方放不下才上移
  2. `_msg_html()` 新增 `style='plain-right'`：用户/AI 消息都靠右、无背景块、14px 清晰文字（用户暖橙/AI 薄荷绿），聊天窗 set_content 用之；'bubble' 样式保留给完整记录窗
  3. 会话删除：`AiChatManager.delete_session(name)`（删当前会话自动切相邻、删最后一个重建默认）；ChatWindow 新增「🗑 删除」按钮 + `sessionDeleteRequested` 信号；AI 菜单无变化
- **打包任务（dist: `BreezeTTS2-CUDA`，14.4GB）**：
  - 运行时= `audio-cpp\bin\*` 全套（含 CUDA13 运行库 cuda.dll/cudart/cublas/cublasLt/nvrtc/nvJitLink/nvcudart_hybrid）+ 补 `cufft64_12.dll`（server 导入但 bin 缺失，自 CUDA toolkit bin\x64 复制）→ 目标机【免装 CUDA Toolkit】
  - 模型：`models/breeze-tts-2/breeze-tts-2-q8_0.gguf`(默认,4.8G) + `models/Breeze-TTS-2-GGUF/breeze-tts-2-bf16.gguf`(高音质,7G)，各带完整 HF 配套(tokkenizer/config/audio_tokenizer)
  - 语音克隆预设：`references/star_ref.wav`(星绘 8.39s@24k) + `star_ref.txt`
  - 脚本：`tts_launcher.py`（含 start/stop/test/status + 中文路径检测）由普通 Python 驱动，规避 cmd 拼 JSON 的转义坑 + 英文 bat 入口（启动TTS服务.bat / 测试星绘语音.bat / 停止TTS服务.bat，GBK+CRLF）
- **验证**：
  - 干净目录(ASCII) 启动 server(cuda)→health→POST /v1/models/load(q8 与 bf16 各一次)→合成星绘 wav：均 RIFF 有效，q8 203KB bf16 165KB ✅
  - 真实 .bat（cmd 双击场景）启动→等待→加载→星绘克隆就绪 OK ✅
  - 中文路径测试（`...\中文测试目录\`）确认 audiocpp_server **不支持含中文路径**（`model path does not exist`）→ 已在 launcher 加 ASCII 路径检测与提示，README 注明解压到纯英文路径
  - UI 冒烟回归：session 28 / usage_layout 14 / history 22 / bubble / gui 全绿 ✅
- 涉及：`ai_chat.py`（show_near/_msg_html style/ChatWindow 删除按钮+set_content）、新增 `tts_launcher.py`、`BreezeTTS2-CUDA/` 分发目录、新增 `stage_run.py`/`dist_verify.py`/`subst_verify.py`/`depscan.py` 验证脚本、更新 `session_smoke.py`
- **部署**：分发文件夹已移至桌面 `<user-desktop>\BreezeTTS2-CUDA`（14.1GB，含 q8+bf16 双模型+全套 CUDA 运行库+星绘克隆+3 个 bat+launcher+使用说明），由用户自行压缩成 zip；7z 验证 zip 可完整解压 128 文件 14.4GB（C:\Temp 全量解出）✅；桌宠 exe 已重新打包部署（12:18 版，UI 改动生效）✅
- git：`f798fc7`（UI+zip 分发包）；`9c0b79f`（冒烟测试费用断言改时段无关：显式关峰谷固定满价 + 新增高峰周一10点/空闲周一13点判断用例，修复非高峰时段跑测试误报）

### 2026-09-07（AI 对话四合一：语音等待三点拉长 / 对话可视化消息流 / 多会话上下文 / 口语化提示词）
- **需求**：
  1. 等语音（TTS 合成/朗读）时桌宠旁「三点」等待动画别提前消失——语音还没来就结束很突兀；
  2. 对话可视化：我发出去的消息显示在右侧（右上角），桌宠回复显示在左侧（左下角），不再是单一蹦字；
  3. 记录/上下文要支持**多会话**：可新建/切换指定会话继续聊，而不是只有一个上下文反复"清理上下文"清空；
  4. 更新提示词让模型输出更口语化，避免"嘻嘻"这类被 TTS 念怪的书面拟声。
- **实现**（`ai_chat.py`）：
  1. **三点等待拉长**：`BubbleWidget.show_thinking()` 去掉 `_lift_life()`——思考/等待期不再 5 秒自动消失，三点一直保持到真正显示文字/开始朗读那一刻；`_on_ai_done` 走 TTS 分支时不再先 hide 再 show（消除闪断），整条「AI 请求→朗读改写→音频合成」等待期三点连续；`_on_tts_done` 重构为**音频真正进入播放状态才开始蹦字**（监听 `playbackStateChanged` 的 PlayingState，1.2s 兜底），杜绝"三点消失→文字先蹦→声音晚几百 ms"的错位；`_speak_text` 播放器缺失时回退直接蹦字（防永久三点）
  2. **对话可视化**：新增模块级渲染 `_msg_html(messages, system_prompt, pet)`，用户消息右对齐（右上角）、AI 消息左对齐（左下角），完整记录窗与聊天窗共用；`ChatWindow` 从"迷你输入条"升级为**可视化聊天窗**（470×340，消息流 + 底部输入 + 用量行），保留 btn_clear/btn_history/btn_send/input/lbl_usage/set_usage 等接口（旧冒烟兼容）；`ChatHistoryWindow.show_history` 委托 `_msg_html`
  3. **多会话上下文**：`AiChatManager` 新增 `_sessions/{会话名:[消息]}`、`_session_order`、`_session_cur`，`_messages` 始终指向当前会话（既有调用零改动）；方法 `new_session(name)` / `switch_session(name)` / `session_names()` / `current_session()`；`clear_context` 改为只清当前会话（其它会话保留）；聊天窗顶部加**会话下拉 + 「＋新建」**按钮（信号 sessionSwitchRequested/sessionNewRequested）；AI 菜单加「＋ 新建会话」；新会话自动切换并渲染
  4. **口语化提示词**：`AiChatManager.SPOKEN_RULES`（口语自然、短句、避免"嘻嘻/嘤嘤/嘿嘿嘿"等拗口叠字拟声、数字英文按口语读）作为**强制后缀**拼在 `system_prompt()` 结果上——用户自定义人设也生效（带去重判断）；`default_tts_prompt()` 强化"改写朗读稿口语化 + 去拗口拟声 + 数字口语化"，TTS 念怪音问题从源头缓解
- **验证**：py_compile 全过 ✅；新增 `session_smoke.py`（22 项：会话建/切/隔离/清理保留/可视化控件/用户右对齐/AI 左对齐（Qt block 级断言）/口语规则）全绿 ✅；`qt_align_check.py` 确认 Qt 渲染后用户块 AlignRight、AI 块 AlignLeft ✅；`usage_layout_smoke.py` 更新 14 项 ✅；`history_smoke.py` 22 项 ✅；`gui_smoke.py` ✅；`bubble_smoke.py`（尺寸断言更新为可视化窗）✅；`ai_selftest.py` ✅；panel_smoke2 ✅（panel_smoke3 引用已删除的旧 UI 属性 `cmb_ai_tts_mode`，属历史过期测试非本次引入）
- 涉及：`ai_chat.py`（_msg_html/_is_cmd_msg/BubbleWidget.show_thinking/_on_ai_done/_on_tts_done/_speak_text/ChatWindow 全重写/ChatHistoryWindow.show_history/AiChatManager 会话管理+open_chat+_refresh_chat_if_open+SPOKEN_RULES）、`pet.py`（AI 菜单加「＋ 新建会话」）、新增 `session_smoke.py`/`qt_align_check.py`、更新 `usage_layout_smoke.py`/`bubble_smoke.py`
- **打包部署**：`python -m PyInstaller --noconfirm --clean '卡丘简易桌宠.spec'` → `dist\卡丘简易桌宠.exe`（11:39，55,221,883B）；备份上一版 → 桌面 `卡丘简易桌宠_上一版.exe`（10:52 版）；覆盖桌面 `卡丘简易桌宠_最新.exe`；启动验证 OK（主进程+提权副本，内存正常）→ 测试后停
- git：`6c5bcd0`（AI 对话四合一）

### 2026-09-07（部署：含 AI 菜单+累计积分的新版 exe 10:52，55.2MB）
- **打包**：`python -m PyInstaller --noconfirm --clean '卡丘简易桌宠.spec'` → `dsh-desktop-pet\dist\卡丘简易桌宠.exe`（10:52，55,217,208B）；exit 1 仍为 UPX 个别 DLL 告警、产物完整
- **部署**：覆盖桌面 `卡丘简易桌宠_最新.exe`（先提权停同名进程）；启动验证 OK（主进程+提权副本）→ 测试后停
- 涉及：`dsh-desktop-pet\dist\卡丘简易桌宠.exe`、桌面 `卡丘简易桌宠_最新.exe`

### 2026-09-07（AI 对话支持上下文选项菜单 + 每次对话 token 分类统计累计积分）
- **需求（用户）**：①每次对话要知道输入/输出/缓存读取各用了多少 token 并**单独累计成积分**；②把上下文操作做成**可选的菜单**入口
- **确认（用户选 A/B）**：A=分类显示+累计积分；B=加到右键菜单，且三处（右键/三横/托盘）都加 AI 子菜单
- **实现**（`ai_chat.py`）：
  1. **本次用量文案更清晰**：`_usage_text` → 「本次 输入↑N[缓存读N] 输出↓N 共N tok ≈ $金额」（输入/缓存读取/输出三类分开）
  2. **累计积分**：新增 `_load_stats/_save_stats/_accumulate_usage`——`_show_usage` 每次回复后把 `prompt_tokens/prompt_cache_hit_tokens/completion_tokens/金额/次数` 累加进 `ai.stats`（{in,cache,out,cost,n}，持久化，清理上下文不重置）；`stats_text()` 完整文案「累计对话 N 次/累计输入 X（其中缓存读取 Y）/累计输出 Z/累计消耗 $F」；`stats_short()` 一行简版
- **实现**（`pet.py`）：
  1. **右键改弹 AI 快捷菜单**：`mousePressEvent` 右键 AI 启用时 → `_popup_ai_menu`（弹「💬 打开 AI 对话 / 📜 完整对话记录 / 🧹 清理上下文 / 📊 用量·积分(简版不可点) / 📈 查看统计详情」），不再直接开聊天窗
  2. **AI 子菜单三处共用**：`_build_ai_menu(parent)` 统一构建（AI 未启用 → 单条「AI 未启用（去 设置→AI 开启）」置灰）；`_build_role_menu` 主菜单（三横/托盘）切角色后加「AI（对话·用量）」子菜单；`_show_ai_stats_detail` 用桌宠气泡展示完整统计
- **验证**：
  - 累计积分：两次回复累加 输入1500/缓存300/输出300/2次/金额 ✅；stats_text/stats_short 文案正确 ✅；持久化写 ai.stats ✅
  - AI 子菜单两态：启用 6 项（对话/记录/清理/sep/用量·积分不可点/统计详情）、未启用 1 项提示 ✅
  - gui_smoke/history_smoke 22/usage_layout 11/py_compile 全过 ✅
- 涉及：`ai_chat.py`（_usage_text 文案/累计积分 6 方法）、`pet.py`（右键改 AI 菜单/_build_ai_menu/_popup_ai_menu/_show_ai_stats_detail/_build_role_menu 加 AI 子菜单）、`usage_layout_smoke.py`（[缓存读400] 断言）
- 备注：积分存 `ai.stats`（累计不清零，清理上下文不重置）；「查看统计详情」在桌宠气泡显示完整累计

### 2026-09-07（部署：含峰谷计价的新版 exe 10:29，55.2MB）
- **打包**：`python -m PyInstaller --noconfirm --clean '卡丘简易桌宠.spec'` → `dsh-desktop-pet\dist\卡丘简易桌宠.exe`（10:29，55,213,333B）；exit 1 仍为 UPX 个别 DLL 告警、产物完整
- **部署**：覆盖桌面 `卡丘简易桌宠_最新.exe`（先提权停同名进程再复制）；启动验证 OK（主进程+提权副本）→ 测试后停
- 涉及：`dsh-desktop-pet\dist\卡丘简易桌宠.exe`、桌面 `卡丘简易桌宠_最新.exe`

### 2026-09-07（智能识别 DeepSeek 高峰时段：峰谷自动计价，空闲半价）
- **需求（用户）**：价格那里要能**智能识别 DeepSeek 的高峰期**（高峰全价/空闲半价自动切换）
- **官方依据**（api-docs.deepseek.com 中文/英文页一致）：高峰 = **北京时间周一至周五 9:00-12:00、14:00-18:00**（UTC 01-04/06-10）；其余时间 + 周六/日 = 空闲，**空闲价 = 高峰价一半**
- **实现**（`ai_chat.py`）：
  1. `is_peak_time(dt=None)` 静态判断：UTC+8 固定算（不依赖机器时区）；工作日 9-12/14-18 区间含 9:00/14:00 整点、不含 12:00/18:00 整点；周六/日全天空闲；异常保守按高峰
  2. `peak_pricing_enabled()` 读 `ai.peak_pricing`（**默认 True**）
  3. `_peak_factor()`：空闲且启用 → 0.5（官方半价）；否则 1.0。`input_price/output_price/cache_price` 返回值 = 配置原始价 × 因子
  4. `raw_prices()`：面板原始高峰价（不含折扣）
  5. `_peak_tag()`：空闲时返回 `· 空闲半价` 标注；`_usage_text` 金额后追加
  6. **跨时段自动刷新**：`_peak_timer` QTimer 每 60s 检查 `_last_peak` 翻转，翻转时 `_sync_chat_usage()` 用新单价重算用量行（开着聊天窗时自动切换高峰/半价显示）
- **实现**（`settings_panel.py`）：单价区加「⚡ 按 DeepSeek 峰谷自动计价（空闲半价）」开关（默认勾选）+ 状态小字 `lbl_peak_state`（当前高峰→全价 0.14/0.28/0.0028 或 空闲→自动半价 0.07/0.14/0.0014，随开关变化）；`_ai_apply_peak` 写 `ai.peak_pricing` + 刷新状态；`_refresh_peak_state` 动态读 is_peak_time/raw_prices 显示；refresh_all 回填开关与状态
- **验证**：
  - `is_peak_time` 11 边界全对（8:59 空/9:00 峰/11:59 峰/12:00 空/13:59 空/14:00 峰/17:59 峰/18:00 空/23:00 空/周六 10:00 空/周日 15:00 空）✅
  - 空闲半价 0.14→0.07、0.28→0.14、0.0028→0.0014 ✅；高峰全价、关闭开关全价 ✅
  - 用量文本带「· 空闲半价」标注 ✅；面板开关默认开/关闭写入 peak_pricing=False/状态字三态切换 ✅
  - history_smoke 22 项 + usage_layout 11 项 + gui_smoke + py_compile 全过 ✅
- 涉及：`ai_chat.py`（is_peak_time/peak_pricing_enabled/_peak_factor/_peak_tag/raw_prices/input·output·cache·price×因子/_peak_timer/_on_peak_tick/_usage_text 标注）、`settings_panel.py`（chk_ai_peak/lbl_peak_state/_ai_apply_peak/_refresh_peak_state/refresh_all 回填）
- 备注：面板填的单价视为**高峰价**，空闲自动 ×0.5；关闭开关即回到"恒按所填价"。用户 <provider> 中转若已按其自身峰谷计价，可关掉本开关避免双重折扣

### 2026-09-07（部署：含「跟随桌宠+实时刷新」历史窗的新版 exe 10:18，55.2MB）
- **打包**：`python -m PyInstaller --noconfirm --clean '卡丘简易桌宠.spec'` → `dsh-desktop-pet\dist\卡丘简易桌宠.exe`（10:18，55,210,955B）；exit 1 仍为 UPX 个别 DLL 告警、产物完整
- **部署**：覆盖桌面 `卡丘简易桌宠_最新.exe`；启动验证 OK（主进程+提权副本）→ 测试后停
- **踩坑**：桌面桌宠进程名是 **`卡丘简易桌宠_最新.exe`**（非 `卡丘简易桌宠.exe`），之前 taskkill 匹配错名字杀不掉、文件被占用无法覆盖 → 用正确进程名 + 提权 `/IM '卡丘简易桌宠_最新.exe' /F /T` 才终止
- 涉及：`dsh-desktop-pet\dist\卡丘简易桌宠.exe`、桌面 `卡丘简易桌宠_最新.exe`

### 2026-09-07（历史窗增强：跟随桌宠移动 + 实时自动刷新）
- **需求（用户）**：完整对话窗口要能**跟着桌宠移动**；且要**实时刷新数据**——新聊内容自动出现，不用重新打开
- **实现**（`ai_chat.py`）：
  1. **历史窗跟随桌宠**：ChatHistoryWindow 加 `_follow` QTimer(16ms)+`_follow_pet()`（保持相对偏移平移，参照 ChatWindow）；**`_start_follow` 立即锚定偏移**（而非首 tick 才算，避免第一跳）；拖动窗口时停跟随、松开 **1.5s 后自动恢复**（`_resume_timer`，大窗友好）；hideEvent 停跟随
  2. **Manager 接线跟随**：`show_history()` 打开后 `_start_follow()`；`pet_moved()` 对历史窗（可见且非拖动中）调 `_follow_pet()` → 桌宠拖动时历史窗/气泡/输入条三者同步跟移
  3. **实时刷新**：新增 `_refresh_history_if_open()`（历史窗可见时用当前 `_messages` 重渲染，保留位置不动）；在 `_on_send`（用户消息入列）、`_on_ai_done`（assistant 回复入列）、`clear_context`（清空）三处调用 → 开着历史窗时新消息/新回复自动出现，不用重开
  4. **定位边界修复**：`show_history` 对"大窗放不下 pet 上方/下方"退化——优先上方、上方不够放下方、都不够贴屏顶；x/y 都 clamp 屏内
- **实现**（测试）：`history_smoke.py` 扩充到 22 项——新增跟随定时器在跑、pet 移动窗口跟移(delta=位移量)、刷新后新消息/新回复出现、清理后变空、hide 停跟随
- **验证**：
  - `history_smoke.py` 22/22 PASS ✅
  - 离屏集成：pet +50,+50 → 历史窗精确平移 (50,50) ✅；实时刷新 live 窗口内容更新 ✅
  - `usage_layout_smoke.py` 11 项 + `gui_smoke.py` 回归 + py_compile 全过 ✅
- 涉及：`ai_chat.py`（ChatHistoryWindow 跟随/_start_follow 锚定/拖动暂停恢复/show_history 定位/Manager pet_moved+show_history+_refresh_history_if_open+_on_send+_on_ai_done+clear_context）、`history_smoke.py`
- 备注：历史窗拖动松开 1.5s 自动恢复跟随（可在 `_resume_timer.setInterval` 调）；实时刷新不改窗口位置、不清滚动位置到顶

### 2026-09-07（新增「📜 记录」按钮 + 完整对话上下文窗口 ChatHistoryWindow）
- **需求（用户）**：添加一个按键，能查看当前对话的完整上下文，直接列出一个完整的对话窗口；要求开发得精致
- **实现**（`ai_chat.py`）：
  1. **消息时间戳**：`_messages` 追加消息改为 `{'role','content','ts'}`（ts=`time.strftime('%H:%M:%S')`），user 与 assistant 两处 append 统一；`clear_context` 同步清空
  2. **发送剥离多余字段**：`_on_send` 构造发给 API 的 `msgs` 从 `self._messages[-20:] +=` 改为逐条只取 `role/content`（避免把 ts 等多余字段发给服务商导致潜在 400）
  3. **ChatHistoryWindow 新类**：无边框圆角深色置顶窗；标题栏（💬 完整对话 + 条数徽章 + 复制全文 + 关闭✕）；主体 QTextBrowser 富文本渲染——系统提示词灰色斜体置顶、用户消息右对齐青绿气泡块、AI 消息左对齐深灰气泡块、每条带时间戳、消息换行自动 <br>、自动滚动到底；底部状态栏（用户N条·AI N条·共N字 + Esc提示）；支持全窗拖动、Esc/✕关闭、复制全文按钮（复制后短暂变「已复制 ✓」）
  4. **ChatWindow 加按钮**：第一行加「📜 记录」按钮（清理上下文旁），新增 `historyRequested` 信号；窗口宽 380→**470px** 容纳
  5. **Manager 接线**：`_history` 属性 + `show_history()`（点按钮重建窗口、定位桌宠上方）、`open_chat` 连接信号、`clear_context` 同步刷新历史窗为空、`close_all` 一并关闭
- **实现**（测试）：`history_smoke.py` 15 项冒烟（记录按钮存在/点击弹窗/计数4条/消息渲染/时间戳/换行/元信息/空会话提示/复制全文/html 转义）
- **验证**：
  - `history_smoke.py` 15/15 PASS ✅
  - `usage_layout_smoke.py` 11 项（尺寸改 470 后）ALL PASS ✅；`gui_smoke.py` 回归过 ✅；py_compile 全过 ✅
  - 离屏渲染像素校验：历史窗 540×507 / 聊天窗 470×70 均正常渲染，18 种采样色（背景面板/用户青绿气泡/AI 深灰气泡/标题/关闭红钮）✅
- 涉及：`ai_chat.py`（ChatHistoryWindow 新类/ChatWindow btn_history+historyRequested+W_USAGE 470/Manager _history+show_history+open_chat+clear_context+close_all/_on_send 剥字段+两处 append ts）、`usage_layout_smoke.py`（380→470）、新增 `history_smoke.py`
- 备注：历史窗只读展示、不编辑；消息条数无上限（`_messages` 本就全量保留，发送 API 才截最近 20 条）；打包部署见下条

### 2026-09-07（调研：audio.cpp 流式输出可行性——BreezeTTS 2 不支持）
- **问题（用户）**：audio.cpp 有没有流式输出（用于桌宠朗读边合成边播）
- **查证（官方文档 + 本机实测）**：
  1. **框架支持**：server README 载明 streaming-capable TTS 模型（config `mode:"streaming"`）的 `POST /v1/audio/speech` 支持 `"stream_format":"sse"`（SSE 事件 `speech.audio.delta` base64 PCM → `speech.audio.done` → `[DONE]`）或 `"stream_format":"audio"`+`response_format:"pcm"`（chunked 裸 PCM）；另有 `/v1/audio/speech/live` 双工端点
  2. **BreezeTTS 2 不支持**：tts.md 中 VoxCPM1/2、OmniVoice(伪流式)、Confucius4、NeuTTS 有流式说明，breeze_tts 无；本机 `bin-cuda\model_specs\breeze_tts.json` 的 `runtime.tags` 仅 `["gguf"]`、无 `"stream"` 标签（所有真流式模型均带 stream 标签）
  3. **本机实测**（server 跑于 8080，breeze-tts-clone，mode=offline）：普通 POST 200 返回整段 `audio/wav` ✅；`stream:true` → **HTTP 500** ❌；`/v1/audio/speech/stream` → **404** ❌；`mode:"streaming"`/`response_format:"pcm"` 参数均被忽略仍返回整段 wav
- **结论**：桌宠「合成完整段播放 + 文字随音频同步蹦字」是 BreezeTTS 2 下的正确实现，无需改动；若将来要真流式朗读，可评估换 `voxcpm2`（中英双语+克隆+SSE PCM 流），需重新克隆星绘音色并改桌宠 TTS 播放器为分块投喂
- 备注：此条与 2026-09-07「BreezeTTS2 不支持真流式」的记录一致并补充了 server API 层面的实证

### 2026-09-07（重新打包部署新版 exe：55.2MB，UPX 生效）
- **需求（用户）**：改完「清理上下文按钮 + 缓存计价 + Kimi-K3 审阅重构」后打包成 exe 部署到桌面
- **打包**：`python -m PyInstaller --noconfirm --clean '卡丘简易桌宠.spec'`（PyInstaller 6.22.2 + Python 3.14.7）
- **产物**：`dsh-desktop-pet\dist\卡丘简易桌宠.exe` **55.2MB**（0:24，较上版 64MB 缩小——UPX 压缩生效）
- **踩坑**：
  1. UPX 5.2.1 对 `python3.dll` 报 `NotCompressibleException`（不可压缩）→ 管道 exit 1，但**仅该 DLL 失败，其余压缩成功，产物完整**；PyInstaller 对 CFG 保护的 MSVCP/VCRUNTIME 自动跳过 UPX（INFO 非错误）
  2. **⚠️ workspace 根目录有个旧 `dist\卡丘简易桌宠.exe`（64MB 残留）**——与项目 `dsh-desktop-pet\dist` 同名同 exe，极易误用；本次曾误把旧版部署到桌面，已纠正
- **部署**：备份旧版为桌面 `卡丘简易桌宠_上一版.exe`（64MB）→ 新版覆盖桌面 `卡丘简易桌宠_最新.exe`（55.2MB）
- **验证**：桌面新版启动 OK（主进程 + 提权副本 2 进程运行，10s 存活）✅ → 测试后已停止
- 涉及：`卡丘简易桌宠.spec`（未改）、`dsh-desktop-pet\dist\卡丘简易桌宠.exe`、桌面 `卡丘简易桌宠_最新.exe` / `卡丘简易桌宠_上一版.exe`
- 备注：**用户需完全退出旧桌宠再双击桌面 `卡丘简易桌宠_最新.exe`**；数据目录仍是桌面 `卡丘简易桌宠数据\`（含 <provider> key/flash 模型/自定义单价，不被覆盖）

### 2026-09-07（清理上下文按钮左移+改名 / token统计记全输入·缓存命中·输出 / 单价补缓存命中档）
- **需求（用户）**：①聊天窗「清空」改名「清理上下文」并移到**输入框左边**；②token 消耗不能只记输入/输出，要记全**缓存**（DeepSeek 前缀缓存命中）；③用户实际用模型 = <provider> 的 `deepseek/deepseek-v4-flash-fast`，单价要按 flash 缓存命中档补
- **实现**（`ai_chat.py`）：
  1. **按钮左移+改名**：ChatWindow 第一行布局由「输入框→清空→发送→✕」改为「**清理上下文**→输入框→发送→✕」；文案 `清空`→`清理上下文`，tooltip 同步；窗口 340px → **380px** 加宽（容纳 5 字按钮），`set_usage` 的 380×70 / 380×46 同步；气泡提示「已清空上下文」→「已清理上下文」，相关 docstring 统一
  2. **usage 记全缓存**：`_chat_request` 解析 usage 时除 prompt/completion/total 外，新增 `prompt_cache_hit_tokens` / `prompt_cache_miss_tokens`（兼容旧名 `prompt_cache_hit` / `prompt_cache_miss`）
  3. **费用拆分两档**：新增 `cache_price()`（默认 `ai_price_cache=0.0028`，flash 缓存命中官方价）；`calc_cost` 公式改为 **未命中输入×0.14 + 命中输入×0.0028 + 输出×0.28**（命中 token 从 prompt_tokens 扣出单独计价，脏数据截断防护：缓存命中≤prompt_tokens）；`set_prices` 扩展第三参 `price_cache`（不传保持现值，向后兼容）
  4. **展示含缓存**：`_usage_text` 有缓存命中时显示「本次 ↑总输入[缓存N] ↓输出 共N tok ≈ $金额」，无缓存保持原样；`_usage_text` 与 `calc_cost` 的缓存值都做截断防护
- **实现**（`settings_panel.py`）：单价区由两档改**三档**——「单价($/M)：进__ 缓存__ 出__」（进=未命中 0.14 / 缓存=命中 0.0028 / 出 0.28），新增 `ed_ai_price_cache` 输入框；`_ai_apply_prices` 读三值调 `set_prices(pin, pout, pcache)` 存 `ai.ai_price_cache`；refresh_all 三框回填
- **验证**：
  - 计价公式离线自测 4 场景全对（无缓存 0.42 / 全命中 0.2828 / 半命中 0.3514 / 超额缓存截断 0.2828）✅
  - 新 `usage_layout_smoke.py` 11 项全 PASS（按钮文案/最左位置/尺寸 380×70×46/usage 含[缓存400]/费用公式/面板缓存输入框存在且回填 0.0028）✅
  - gui_smoke 回归过 ✅；py_compile 三文件全过 ✅（ruff 仅 I001 import 排序历史遗留，与本次无关）
- 涉及：`ai_chat.py`（ChatWindow 布局/按钮改名/usage 缓存解析/cache_price/calc_cost/_usage_text/set_prices/clear_context 文案）、`settings_panel.py`（单价三档输入框/_ai_apply_prices/refresh_all 回填）、新增 `usage_layout_smoke.py`
- 备注：缓存命中单价默认 0.0028（deepseek-v4-flash 官方缓存命中价，约 98% 折扣）；用户 <provider> `deepseek/deepseek-v4-flash-fast` 中转若返回 `prompt_cache_hit_tokens` 则自动按优惠价算，不返回则退化为原全价计算（向下兼容）。面板已存旧配置无 ai_price_cache 时默认 0.0028 回填

### 2026-09-07（Kimi-K3 审阅重构：去重复/删死代码/抽常量 + 按模型自动带单价 + 发送清旧用量 + 精度与框宽微调）
- **背景（用户）**：要求由 Kimi-K3 对上一轮「清理上下文按钮+缓存计价」改动做 UI/架构审阅并落实改进点（用户选 1/2/4/5/6/7 全做，含按模型自动带价）
- **实现**（`ai_chat.py`）：
  1. **代码复用**：新增 `_parse_usage(usage)` 静态方法统一解析 `(pin, pout, pcache, total)` + 脏数据截断防护（缓存命中≤prompt_tokens），`calc_cost` 与 `_usage_text` 共用，消除重复解析
  2. **删死代码**：`calc_cost` 返回值由 `(cost, desc)` 简化为只返回 `cost`（desc 从未被任何调用方读取），docstring 同步
  3. **尺寸常量**：ChatWindow 加类常量 `W_USAGE=380 / H_USAGE=70 / H_NO_USAGE=46`，替换 `__init__` 与 `set_usage` 里 3 处魔法数字
  4. **金额精度**：`_usage_text` 金额 `%.6f`→`%.4f`（微美元级 6 位过细，标签更易读）
  5. **发送时清旧用量**：`_on_send` 发新消息时 `self._chat.set_usage('')` + `self._last_usage={}`，避免上一条用量残留误导
  6. **按模型自动带单价**：新增 `AiChatManager.suggested_prices(model)` 静态映射——`v4-flash*`/`deepseek-chat`/`deepseek-reasoner`→(0.14, 0.28, 0.0028)；`v4-pro`→(0.435, 0.87, 0.003625)；未识别→None。pro 先于 flash 判断避免子串歧义
- **实现**（`settings_panel.py`）：
  1. `_ai_apply_model` 切换模型时调 `suggested_prices`，**仅当 `_prices_are_default()`（当前三单价仍是 flash/pro 默认组合之一）** 才联动填入官方价并持久化——用户人工改过的单价绝不被覆盖；新增 `_fmt_price` 去尾零格式化（0.435 不显示成 0.4350）
  2. 单价区下加小字提示行：「选模型时若单价仍是默认值会自动按官方价带入…；改后不再联动」
  3. 缓存命中输入框宽度 62→70（容纳 0.003625 等更长小数）
- **验证**：
  - `suggested_prices` 8 例映射全对（含 `deepseek/deepseek-v4-flash-fast`→flash 价、pro→pro 价、未知→None）✅
  - `_fmt_price` 8 例格式化全对（0.0028/0.003625 保留精度、0.14 去尾零）✅
  - 面板级联测：默认价切 pro 自动带入 pro 价；人工改价后切回 flash **不覆盖** ✅
  - `usage_layout_smoke.py` 11 项 + `gui_smoke.py` 回归全 PASS ✅；py_compile 三文件过 ✅
- 涉及：`ai_chat.py`（_parse_usage/calc_cost 简化/W_USAGE·H_USAGE·H_NO_USAGE 常量/_usage_text 精度/_on_send 清用量/suggested_prices）、`settings_panel.py`（_ai_apply_model 联动/_prices_are_default/_fmt_price/提示行/缓存框宽 70）、`DEVELOPMENT.md`
- 备注：本次重构不改任何对外行为（除发送时清旧用量、金额精度、自动带价三处用户可感知优化）；自动带价只在「当前价=默认价」时触发，保护用户自定义

### 2026-09-07（聊天窗升级：清空上下文按钮 + 单次token消耗/金额显示 + 气泡5秒消失；单价可配）
- **需求（用户）**：①清理上下文按钮放聊天框旁；②查看单次 token 消耗并计算金额；③气泡文字完全显示后 5 秒消失、点击立即消失；④语音克隆流式（已确认 BreezeTTS2 不支持真流式——模型需 mode=streaming 才支持 SSE，Breeze 是整段合成，属模型本质限制）
- **实现**（`ai_chat.py`）：
  1. **ChatWindow 重构**：340×46 → **340×70 两行布局**——第一行 输入框+「清空」按钮+发送+✕；第二行用量小标签（深色底圆角）。「清空」发 `clearRequested` 信号
  2. **清空上下文**：`AiChatManager.clear_context()` 清 `_messages`/`_last_usage`，聊天条用量标签清空，气泡提示"已清空上下文"；open_chat 连接信号
  3. **token 消耗+金额**：`_chat_request` 返回 `(text, usage)`（从响应 usage 解析 prompt/completion/total）；`AIWorker.done` 信号加 usage；`_on_ai_done` 收到后 `_show_usage` 显示到聊天条第二行「本次 ↑输入 ↓输出 共N tok ≈ $金额」；`_last_usage` 记住供重开聊天窗 `_sync_chat_usage` 恢复
  4. **金额计算**：单价默认 deepseek-v4-flash（输入$0.14/输出$0.28 每百万token，官网），`input_price/output_price/set_prices/calc_cost`；`_show_usage` 用单价×token/1e6 算美元
  5. **气泡消失**：`_BUBBLE_LIFE_MS` 30000→**5000**（蹦字完成后 5 秒消失）；移除 show_text/show_text_synced 开蹦时过早 `_lift_life`（只保留蹦字完成 _type_step 触发）；点击气泡已可立即消失
- **实现**（`settings_panel.py`）：AI 配置区系统提示词下加「单价($/M)：进__ 出__」两输入框（默认 0.14/0.28），`_ai_apply_prices` 存 `ai.ai_price_in/out`，refresh_all 回填
- **验证**：ctx_usage_smoke 9 项全过（清空按钮/标签/触发/历史清空/用量显示/单价保存回填）✅；gui_smoke + ai_selftest 回归过 ✅；py_compile ✅
- 涉及：`ai_chat.py`（ChatWindow 重构/clear_context/usage 全链路/单价/气泡5s）、`settings_panel.py`（单价输入）
- 备注：用量金额按单次请求算（显示在聊天条）；单价可在设置→AI 改，换模型只需改单价

### 2026-09-07（修复服务启动500：server启动完整流程[CUDA PATH+spec+load模型]；输入框/气泡跟随提速到60fps+拖动即时跟移）
- **问题（用户反馈）**：点「停止服务」再「启动服务」后点「测试音频」报 **HTTP 500**；聊天输入框/文字跟随桌宠有明显延迟、不像一体
- **排查根因**（读 audio.cpp server 源码 `runtime.cpp` + 实测）：
  1. **server 启动即崩溃**：CUDA 版缺 DLL → 0xC0000135，必须把 CUDA Toolkit bin 注入 PATH（synth.py 早有此处理，服务函数漏了）
  2. **漏 `--ui`**：报 `missing required --config argument (or use --ui for the native WebUI)` → 命令必须带 `--ui --ui-management`
  3. **模型列表默认空**：`load_models()` 遍历 `config_.models`（来自 --config），**不扫描 models 目录** → 启动后 models=0 → 请求 breeze-tts-clone 报 500。正确做法：启动后 `POST /v1/models/load` 加载模型（body: id/family=breeze_tts/task=clon/mode=offline/path=具体gguf/model_spec_override）
  4. **僵尸进程**：旧版「停止服务」taskkill 因非提权杀不掉桌宠(管理员)起的 server 子进程 → 坏进程(无模型)占 8080 → 重启的新 server 端口被占起不来
  5. taskkill 输出 GBK → 用 `decode('gbk', errors='replace')`
- **修复**（`ai_chat.py` 服务函数重写）：`_server_command`(CUDA PATH+spec+ui)、`_models_paths`(扫 bin-cuda\models 下 gguf，bf16 优先)、`tts_service_start` = 启动→等 health→POST /v1/models/load→确认 loaded；stop 修编码
- **跟随优化**：BubbleWidget/ChatWindow 跟随 timer 50ms→**16ms(60fps)**；新增 `AiChatManager.pet_moved()`（气泡+输入条即时重定位），pet.py 拖动 mouseMoveEvent 与 set_pet_size 缩放处调用 → 拖动时气泡/输入条同步跟移、零轮询延迟、一体感
- **验证**：18080 实测完整流程 server 起 + load breeze-tts-clone → models 0→1 ✅（path 须指到具体 gguf，目录含2个gguf会报错）；py_compile + ai_selftest + gui_smoke 回归过 ✅；打包 61.1MB
- 涉及：`ai_chat.py`（服务启动全流程/stop 编码/pet_moved/16ms）、`pet.py`（拖动与缩放处调 pet_moved）
- **用户操作（关键）**：旧桌宠为管理员权限运行，僵尸 server(42168) 是其子进程、非提权杀不掉 → **必须完全退出旧桌宠**（连带清掉僵尸 server）→ 用桌面 `卡丘简易桌宠_新版.exe` 替换 `卡丘简易桌宠.exe` 再启动 → 点「启动服务」应显示模型已加载 → 测试语音出声

### 2026-09-07（朗读体验大升级：音量0-300% / 文字随音频同步 / 输入框跟随 / 测试真播放 / 服务启停 + UI重排）
- **需求（用户连提）**：①音量可到 300%；②聊天输入框要随桌宠移动；③测试语音要真播出来听；④加 TTS 服务启动/停止按钮；⑤重排朗读 UI；⑥文字应与音频同始同终、随音频语速蹦字（不能文字先蹦完音频还在播）
- **实现**：
  1. **音量 0-300%**（`ai_chat.py`）：`set_tts_volume/tts_volume` 上限 300；QAudioOutput 只到 1.0（100%），>100 用 `gain_wav_if_needed` 播放前对 wav PCM 数字增益（soundfile 读→×gain→tanh 软限幅防削波→写 _gainN.wav）；面板滑块+数字 range 0-300
  2. **文字随音频同步**（核心，`ai_chat.py`）：`_on_ai_done` 朗读开时**不再立即蹦字**，改显示"思考中…"；TTS 合成完 `_on_tts_done` 用 `_wav_duration_ms` 读音频时长 → `BubbleWidget.show_text_synced(text, dur_ms)` **每字间隔=时长/字数** → 文字与音频同始同终、语速贴合；`_synced_text` 记录朗读稿；无朗读仍即时蹦字
  3. **ChatWindow 输入框跟随桌宠**：加 `_follow` QTimer(50ms) `_follow_pet` 保持相对偏移跟随；用户手动拖动后停（`_user_dragged`）；重新打开恢复
  4. **测试语音真播放**：`test_tts_api` 合成后**不删文件**、emit 路径；`_on_tts_api_tested` 调 `pet.ai.play_audio_file(path)` 播放试听
  5. **TTS 服务启停**（`ai_chat.py` 模块级）：`tts_service_url/health/start/stop` 管理 audiocpp_server.exe（写死路径 `breeze-tts-local\audio-cpp\bin-cuda\audiocpp_server.exe`，Popen CREATE_NO_WINDOW + 等 60s health 就绪；stop taskkill）；面板「朗读 AI 回复」下加服务状态行（●绿运行/○橙停止）+ ▶启动/■停止按钮 + 5s 定时探测
  6. **UI 重排**：朗读服务控件分组为「TTS 开关 → 服务状态与启停 → 地址/密钥/模型/音色+测试 → 克隆三件套 → 音量 0-300%」清晰层级
- **验证**：功能冒烟 8 项全过（音量0-300/存200/audio_out钳1.0/服务控件/health/同步方法/url解析）✅；ai_selftest + gui_smoke 回归过 ✅；py_compile 全过 ✅；打包部署 ✅
- 涉及：`ai_chat.py`（音量300+增益/同步蹦字/_on_ai_done 时序/输入框跟随/test_tts_api+play_audio_file/服务管理函数）、`settings_panel.py`（服务状态+启停按钮/音量 range 300/刷新回填/import threading/svc timer）
- 备注：桌面 exe 已部署（61.1MB）；服务按钮启动的是写死路径的 audiocpp_server，若换机器/路径需改 `_AUDIO_CPP_SERVER`

### 2026-09-07（修复克隆音色变男声/诡异：坏参考 wav + 错误字段名；新增朗读音量调节）
- **问题1（用户反馈）**：桌宠接 audio.cpp 克隆星绘后，合成出来是**男声/诡异**，不是星绘女声；而 WebUI 里手动跑同一参考音频是正常女声
- **排查路径**：
  1. 抓 WebUI 前端 JS + audio.cpp server 源码 `runtime.cpp`（139KB）逐行核对请求协议 → 发现**两个字段错误**：① server 只认顶层复数 `instructions`（单数 `instruction` 被静默忽略）；② 克隆请求带了 `voice: "alloy"` 会让 server 设 `cached_voice_id`（内置音色）与 `voice_ref`(克隆音频) 冲突 → **克隆失效走内置音色**
  2. **真正元凶**：`references\star_ref.wav` 被错误转码——原始 mp3 是 **8.39s**，坏 wav 却是 **15.41s（拉长一倍）** → 音调压低变慢 → 克隆出男声+诡异（用 soundfile 解码对比 mp3/wav 时长实锤；坏 wav 有效语音 0.27~14.89s 占满全条）
  3. 用 scipy `resample_poly` 从原始 mp3 重采样出干净 `star_ref.wav`（8.39s / 24kHz / 单声道，语音 0.15~8.11s）
- **代码修复**（`ai_chat.py`）：`_api_speech_synth` payload 改造——**克隆时（有 ref_audio）绝不带 `voice`**（避免与 voice_ref 冲突）；指令字段改**复数 `instructions`**；无克隆才发 `voice`。与 WebUI 请求结构完全对齐
- **对照验证**：同 seed 下 路径版 vs base64 内联版 **md5 完全一致**（证明 server 读路径正常、非路径问题）；修复后合成正常（WebUI 手动跑女声 = 桌宠 API 输出）✅
- **问题2（用户需求）**：新增可调整**播报音量**
- **实现**（`ai_chat.py` + `settings_panel.py`）：朗读服务表单加「朗读音量」滑块(0-100)+数字，`set_tts_volume/tts_volume/_apply_tts_volume`（QAudioOutput.setVolume 0~1），实时生效+持久化（配置 `ai.tts_volume`）；播放器初始化即应用音量；refresh_all 回填
- **验证**：音量冒烟 8 项全过（控件/默认100/滑块40同步spin/配置存40/audio_out=0.4/spin75同步/0.75/refresh回填30）✅；py_compile ✅；新 exe 打包部署 ✅
- 涉及：`ai_chat.py`（payload 重构/音量三方法/init 应用）、`settings_panel.py`（音量行+handler+回填）、`references\star_ref.wav`（重新生成）、`references\fix_ref_wav.py`
- 备注：旧桌宠进程需完全退出再开新版（提权运行 Stop-Process 会 Access denied，需手动退出）


### 2026-09-07（桌宠接入 audio.cpp 本地克隆音色 TTS：星绘音色 + 情绪模型自动补齐）
- **需求（用户）**：桌宠朗读接 audio.cpp（本地 BreezeTTS 2 Clone，8080）**克隆星绘音色**；说话情绪不要手动填，由**模型自动判断补齐**
- **背景**：audio.cpp server 原生 `POST /v1/audio/speech` 就支持 `voice_ref`(参考音频路径) + `reference_text`(转录) + `instruction`(情绪/人设) → **桌宠零代理直连 8080**（原 8081 官方 Breeze 代理方案仍保留未删，但不再需要）
  - 实测：`{model:"breeze-tts-clone", voice_ref:<star_ref.wav>, reference_text:"初次见面…", instruction:"难过的说…"}` → **星绘克隆难过语气 9s 出 418KB wav** ✅
  - 注意：audio.cpp 忽略 `response_format`，**总是返回 RIFF/WAV**（哪怕请求 mp3）；桌宠改为存 `.wav`
- **实现**（`ai_chat.py`）：
  1. `_api_speech_synth` 扩展参数 `ref_audio/ref_text/instruction`：填了 `ref_audio` 才带 `voice_ref`+`reference_text`（克隆）；`instruction` 为情绪/人设（BreezeTTS2 支持中文情绪短语）；统一存 `.wav`
  2. `TTSWorker` 构造新增 `instruction`；`_synth_once` 从配置读克隆三件套 `tts_api_ref/tts_api_ref_text/tts_api_instruction`
  3. **情绪自动补齐**：`default_tts_prompt` 改造——让 LLM 输出两行「情绪：<中文情绪>」「朗读：<改写稿>」；`parse_tts_output` 解析；`_on_rewrite_done` 把解析出的情绪作为 `instruction` 传给 TTSWorker（改写失败→朗读原文、情绪留空）
  4. `set_tts_api/test_tts_api` 扩展支持 ref/ref_text/instruction
- **实现**（`settings_panel.py`）：朗读服务表单在「音色」下新增三字段——**参考音频**(带「浏览…」按钮，选完自动找同目录同名 `.txt` 填转录)、**参考转录**、**默认情绪**(留空=AI 自动判断)；`_ai_apply_tts_api/_ai_pick_tts_ref/_ai_test_tts_api/refresh_all` 同步
- **配置**（桌面 `卡丘简易桌宠数据\pet_config.json` ai 段）：`tts_api_base=http://127.0.0.1:8080/v1`、`tts_api_model=breeze-tts-clone`、`tts_api_ref=<…>\audio-cpp\references\star_ref.wav`、`tts_api_ref_text=初次见面，我叫星绘。这个名字可不是代号哦。请多关照了。`、`tts_api_instruction=`(空=自动)
- **验证**：`parse_tts_output` 单测 6 例全过 ✅；克隆三件套 GUI 冒烟 7 项全过（控件/保存/回填/浏览自动填转录）✅；**真实 LLM(<provider>)+audio.cpp 端到端**：回复「我又把钥匙弄丢了…」→ LLM 改写自动判「懊恼自责」→ 星绘克隆懊恼语气合成 510KB wav ✅；ai_selftest/gui_smoke 回归过 ✅；py_compile 全过 ✅
- 涉及：`ai_chat.py`、`settings_panel.py`；冒烟脚本 `tts_parse_test.py`/`tts_clone_smoke.py`（验证后已删）
- 备注：打包 exe 后需完全退出旧桌宠再运行新版；情绪强弱可后续在面板「默认情绪」微调（如填「温柔地轻声」），留空则走 AI 每句自动判断


### 2026-09-06（本地 TTS 部署：Breeze TTS 2 接入桌宠朗读）
- **需求（用户）**：桌宠朗读要支持**本地 TTS**（不依赖云端）；调研后选定当前开源榜一 **Breeze TTS 2**（中英双语、3.48B、Apache 权重研究/非商用）
- **调研结论**：Breeze TTS 2 官方 PyTorch 在 Windows 原生只能 **eager/sdpa**（约 40s/句）；**fast path（CUDA Graph + Triton）需要 Linux**——Windows 无 Triton wheel（已实测 `TritonMissing` 失败）
- **部署尝试（最终落 Windows 原生 sdpa + OpenAI 兼容代理）**：
  1. Windows 原生：Python 3.12 venv + **torch 2.9.1+cu128**（RTX 5060 Ti Blackwell 必须 cu128）+ modelscope 下载权重 7.4GB → `python -m breeze_infer.api <模型> --host 127.0.0.1:7860` 跑通，sdpa 合成 5.7s 音频 37.6s
  2. **WSL2 fast path 验证**：转 WSL2（Linux 自带 triton 3.5.1），`--fast-all` CUDA Graph 全捕获，**4.2s 音频只用 3.5s（RTF ~0.83，比 sdpa 快 11 倍）**——但因本机嵌套虚拟化 + WSL2 与 Windows 网络隔离（127.0.0.1 / eth0 均不通），桌宠（Windows）无法访问 WSL 内服务，**故接入用 Windows 原生**
  3. **OpenAI 兼容代理** `server/breeze_openai_proxy.py`（8081）：把桌宠的 JSON `{model,input,voice,response_format}` → 官方 Breeze multipart → PCM 封装 wav 返回；`voice` 空=默认中文女声，填文案=人设描述（Breeze voice-design 特色）；坑：响应头不能放中文（latin-1 报错）
- **接线桌宠**（零代码改动，只写配置）：桌面 `卡丘简易桌宠数据\pet_config.json` 的 `ai` 段：`tts_api_base=http://127.0.0.1:8081/v1`、`tts_api_model=Breeze-TTS-2`、`tts_enabled=true`、`tts_mode=api` → 桌宠「设置→AI→朗读服务」即用本地 Breeze
- **验证**：Windows 原生 sdpa 合成 ✅；代理端到端（模拟桌宠请求 → wav 返回 218KB）✅；代理 /health 显示 upstream ok ✅；配置已写入 ✅
- 涉及（外部目录 `breeze-tts-local/`）：`repo/`（官方代码 + api.py 加 BREEZE_ATTN 环境变量支持 sdpa）、`venv/`（torch cu128）、`server/breeze_openai_proxy.py`、`test_synth*.py`、`manage.py`
- **遗留（用户可后续优化）**：WSL2 fast 虽快但 Windows 连不通（需 netsh 转发 + WSL 防火墙放行，本机嵌套虚拟化难通）；当前用 Windows 原生 sdpa（40s/句可用但慢），如需更快建议后续试 Breeze-TTS-2.cpp（Vulkan/GGUF，Windows 原生跨平台）
- **用户验证**：需完全退出桌宠再双击桌面 exe → 设置→AI→朗读服务 点「测试语音」听本地 Breeze 朗读


### 2026-09-06（转 ComfyUI 部署 Breeze TTS 2：节点 + cuda_graphs 加速 + 中文工作流）
- **需求（用户）**：不要独立 Python 进程，改为**在已有的 ComfyUI 里部署** Breeze TTS 2，体验 WebUI/工作流
- **关键背景**：本机 ComfyUI = **Comfy Desktop 桌面版**，真实运行目录 `<user-appdata>\Local\Comfy-Desktop\ComfyUI-Installs\ComfyUI\ComfyUI\`（.venv = Python 3.13.12），模型目录映射到 `Comfy-Desktop\ComfyUI-Shared\models\`（inst-*.yaml）。**D:\ComfyUI 只是源码副本，不是运行目录**（custom_nodes/模型都要放运行目录 + 共享 models 才生效）
- **WSL 涂味（显存元凶）**：WSL 里多次启动 Breeze fast 后，残留 CUDA context 占 GPU ~14.5GB，导致 ComfyUI/本地一切卡顿 → **彻底关停 WSL 立即释放**（显存 15786→1254 MiB）。教训：WSL 内跑 GPU 模型要防僵尸进程吞显存
- **部署**：装社区节点 **Saganaki22/ComfyUI-Breeze-TTS-2**（60⭐，node-del/grad）+ 下模型 **Breeze-TTS-2-int8-hybrid.safetensors**（4.5GB，INT8 ConvRot=bf16音质+省27%显存，适用16GB卡）到 `ComfyUI-Shared\models\breezetts2\drbaph_Breeze-TTS-2-comfyui\`（含 audio_tokenizer）
- **节点亮点（免 Triton 加速）**：LoadModel 的 `decode_mode="cuda_graphs"` **手动捕获 eager 步骤**（绕过 torch.compile/triton 限制，Windows 原生可用）+ `attention` 可选 sdpa/flash_attention/sageattention → 这是本机 ComfyUI 里吃满 GPU 的加速正解
- **验证**：重启 ComfyUI → 7 节点全部注册（LoadModel/VoiceClone/VoiceDesign/VoiceDirection/Speaker/MultiSpeaker/WhisperTranscribe）✅；API 提交 int8-hybrid+sdpa+cuda_graphs 工作流 → VoiceDesign 中文合成 **success ~22s**（含首次模型加载）✅
- **交付**：中文体验工作流 `BreezeTTS2_中文体验.json`（LoadModel→VoiceDesign→PreviewAudio，已放桌面）→ ComfyUI 拖动加载即用，改文本/人设可复用
- 涉及（外部 `breeze-tts-local/`）：`downloads/ComfyUI-Breeze-TTS-2`（节点源码）、`download_breeze_model.py`、`comfy_breeze_test.py`、`BreezeTTS2_中文体验.json`；Comfy Desktop 运行目录与 ComfyUI-Shared\models
- 备注：桌宠朗读接入暂未做（此次聚焦 ComfyUI 体验）；如需桌宠用本地 Breeze 仍可回退第 1 条方案（Windows 原生 sdpa + 代理）


### 2026-09-06（audio.cpp 版 Breeze TTS 2：Windows 原生 1.8-3.2x 实时，GPU 占用仍~60%）
- **需求（用户）**：ComfyUI 节点 GPU 占用仅 ~50%，想用 audio.cpp（GGML/C++ 引擎）试吃满 GPU + 更快
- **调研结论**：ComfyUI 节点（Saganaki22）README 明说"官方 CUDA-graph fast path intentionally not ported"——它用 eager 循环重写官方 runtime（DynamicCache 非 CUDA Graph），GPU 50% 是设计使然。真正吃满要 audio.cpp 或官方 fast path
- **部署 audio.cpp v0.7.2（2026-09-04 release 起正式支持 breeze_tts）**：
  1. 下载 `audio-v0.7.2-bin-windows-x64-vulkan.zip`（256MB 预编译）→ `breeze-tts-local\audio-cpp\bin-vulkan\`
  2. 下模型 `breeze-tts-2-q8_0.gguf`（4.8GB，audio-cpp 官方 HF repo）→ 配 config.json/tokenizer/audio_tokenizer（从 HF 原模型复制）
  3. **踩坑**：①v0.7.2 CUDA 版缺 cuda.dll/nvcudart_hybrid64.dll（ggml-cuda 依赖，torch 不带）→ 用 **vulkan 版**免 CUDA runtime；②vulkan bin 原本没 model_specs → 从 cuda 版复制；③预编译 bin 的 **builtin spec 没启用 breeze_tts**（报 "no safetensors source"）→ 必须 `--model-spec-override <model_specs目录>`；④中文别走 cmd/bat（GBK 切命令）→ 用 Python subprocess 传参；⑤人设用 `--request-option instruction=...`
- **验证（RTX 5060 Ti Vulkan）**：英文短句 2.16s 音频 7.0s（3.25x 实时）；中文 12.56s 音频 22.7s（1.8x 实时）✅；wav 正常生成
- **GPU 占用实测**：推理期 55-61%、功耗 65-68W——**仍非 100%**。结论：TTS 自回归逐帧串行解码（每帧依赖上帧）是瓶颈本质，C++ 消除 Python 开销后 ~60% 已是该模型/单 batch 的合理水平，非配置问题
- 涉及（外部 `breeze-tts-local/audio-cpp/`）：`bin-vulkan/`（v0.7.2 vulkan 版 + model_specs）、`models/breeze-tts-2/`（q8_0 gguf + 配套）、`run_breeze.bat`（英文）、`run_zh.py`（中文）、`README.md`
- 备注：audio.cpp 有 server WebUI（`audiocpp_server --ui`）；CLI 已可出 wav。若用户要更吃 GPU，只能等官方 fast path 的 Windows 支持（dev 分支/未来 release）


### 2026-09-07（气泡改版：透明背景 + 描边白字 + 跟随桌宠移动）
- **需求（用户反馈）**：①AI 输出文字气泡的背景要透明（不要深色底）；②气泡要随着桌宠移动
- **实现**（`ai_chat.py` BubbleWidget 重构）：
  1. **背景全透明**：删除 paintEvent 深色圆角底绘制；窗口保持 WA_TranslucentBackground，只在需要时画文字
  2. **自绘描边文字保证可读**：QLabel 改为 paintEvent 直接 drawText——先画深色粗描边（4px、圆角连接、深色 235 不透明），再叠纯白字 → 透明背景下任何桌面都清晰显眼（兼顾"透明"与"显眼"）
  3. **跟随桌宠移动（修复关键 bug）**：`_follow` 定时器原来**从未 start**（show 时只启动了 _life），气泡根本不跟随！现在 `show_text/show_thinking/_bubble_msg` 都显式 `_follow.start()`；间隔 300ms → **50ms**（拖动更跟手）
  4. 思考动画显示改为 `_think_text` 状态 + `update()` 重绘（QLabel 已移除）
  5. manager `_bubble_msg` 适配新 API（_type_text 全量 + _type_pos=len + update）
- **验证**：bubble_smoke 13 项全 PASS（含新增「跟随定时器在跑」「气泡跟随桌宠移动」两项：宠物从 (600,400) 挪到 (700,500) 气泡坐标随之变化）✅；py_compile ✅；exe 部署运行正常（100MB）
- 涉及：`ai_chat.py`（BubbleWidget 重写/manager._bubble_msg）、`bubble_smoke.py`
- 备注：桌面 exe 已部署


### 2026-09-07（AI 聊天窗 ✕ 关闭按钮不明显 → 红底白字醒目样式）
- **需求（用户反馈）**：右键桌宠的聊天窗右上角 ✕ 关闭按钮图标不明显
- **实现**（`ai_chat.py` ChatWindow 标题行）：`btn_x` 由默认 QSS 深色按钮改为**红底白字**（#c0392b 背景、白色粗体 ✕、圆角 6px、hover 变亮 #e74c3c、按下变深 #a93226），加 PointingHandCursor 与「关闭聊天窗」tooltip，尺寸 30x26
- **验证**：py_compile ✅；exe 打包部署重启正常（163MB 主进程 + hook 正常）
- 涉及：`ai_chat.py`（ChatWindow 标题行 btn_x 样式）
- 备注：**模型刷新已同时修复**（上一轮跨线程信号 bug，E2E 真实配置 67 模型 PASS）；用户需**完全退出旧桌宠再双击新版**，且若旧面板一直开着需先关掉（面板打开时读配置，换 key 后旧面板输入框仍是旧值）

### 2026-09-07（关键修复：模型「刷不出来」元凶 = 后台线程操作 Qt 控件；改信号跨线程回调）
- **用户反馈**：换了真 key（user_2W4u...，实测模型 67 个+对话全通）但桌宠里点「刷新模型」仍刷不出来
- **根因（隐蔽 bug）**：`AiChatManager.fetch_models/test_tts_api/test_connection` 在**后台线程**里直接调用面板回调 `_done`，而回调里操作 QComboBox/QLabel 等 Qt 控件 → **Qt 控件禁止跨线程操作**，UI 更新被 Qt 丢弃/无效 → 模型早已查到但**永远填不进下拉框**
  - 曾试 QTimer.singleShot(0) 从后台线程投递 → 无效（无接收者时投递到调用线程自己的事件循环，后台线程没有事件循环）
- **修复**（`ai_chat.py` + `settings_panel.py`）：
  1. `AiChatManager` 新增 3 个 Qt 信号：`models_fetched(bool,object)` / `tts_api_tested(bool,str)` / `conn_tested(bool,str)`；三个后台方法改为线程内 `self.xxx.emit(...)`（**信号跨线程 emit 自动排队回主线程**，Qt 标准做法）
  2. `SettingsPanel._connect_ai_signals()`：`__init__` 连接三个信号到固定槽 `_on_models_fetched` / `_on_tts_api_tested` / `_on_conn_tested`（主线程安全操作 UI）
  3. `_ai_auto_fetch`/`_ai_test`/`_ai_test_tts_api` 去掉局部 `_done` 直传，只发请求，结果走信号槽
- **验证**：py_compile ✅；**端到端（真实面板+真实 <provider> key 点刷新）→ 下拉框 67 个模型 + 「✅ 检测到 67 个模型」PASS** ✅；新 key 实测对话也通（deepseek/deepseek-v4-pro 回「通了」）✅
- 涉及：`ai_chat.py`（3 信号/fetch_models/test_tts_api/test_connection 改 emit）、`settings_panel.py`（_connect_ai_signals/3 个信号槽/_ai_auto_fetch 等去 _done）
- 备注：桌面 exe 重新打包部署；**用户刷新模型前若面板一直开着，需重新点一次「↻ 刷新模型」**（面板打开时读的是旧输入框值的情况已无——现在直接读输入框实时值）


### 2026-09-07（关键修复：<provider> Cloudflare 1010 拦截 → 加浏览器头；TTS 引擎精简为唯一「填地址」服务）
- **用户反馈**：①换新 key 仍刷不出模型；②朗读引擎微软的不要；③本地引擎也不要（Windows 自带），所有朗读都要填 API 地址
- **根因（重大）**：<provider>.ai 用 **Cloudflare 拦截缺浏览器指纹的脚本请求**（响应 body `error code: 1010`），与 key/套餐无关！models 与 chat/completions 都被拦 → 表现为「模型刷不出来」。
  - 诊断过程：直连/代理都 403 → 读 403 body 发现 `error code: 1010`（Cloudflare 指纹拦截）→ 加完整浏览器头（Chrome UA + Accept + Accept-Language + Sec-Fetch-*）→ **HTTP 200，67 个模型秒出** ✅
  - 对话接口仍 401：body `Invalid 'Authorization' header or token` → 用户填的 key 是 `user_` 开头（OAuth 登录 token），**非有效 API key**；且 `.<provider>` 目录只有 models-cache.json 无 auth.json（未 CLI 登录）→ 需在 <provider> Studio 生成真 key
- **实现**（`ai_chat.py`）：
  1. `_browser_headers()`：统一给 `_chat_request`/`_list_models`/`_api_speech_synth` 加浏览器特征头（Chrome UA/Accept/Accept-Language/Sec-Fetch-*）→ 绕过 Cloudflare 1010
- **TTS 引擎精简**（`ai_chat.py` + `settings_panel.py`，按用户「微软不要、本地也要填地址」）：
  1. 删除「朗读引擎」下拉（cloud 微软 / local Windows 自带都移除）；「朗读 AI 回复」勾选下方直接是**朗读服务表单**（服务地址/API 密钥/语音模型/音色/测试语音），**唯一引擎 = 填地址的自定义 OpenAI 兼容 `/audio/speech`**
  2. `TTSWorker` 重写：构造签名 `(text, voice, seq)` 不再传 mode；从配置 `tts_api_*` 读地址合成，1 次重试；未配置 → 明确报错「请到 设置→AI→朗读服务 填 地址/密钥/模型」；不再回退 SAPI/edge
  3. `_speak_text`：voice 取 `tts_api_voice`（兼容旧 `tts_voice`），直连新 TTSWorker
  4. `settings_panel`：删 cmb_ai_tts_mode/cloud_voice_box/cmb_ai_voice 及对应 handler；api_tts_box 常驻可见
- **验证**：py_compile ✅；真实 key 模型检测 67 个 OK ✅；面板冒烟（无旧引擎下拉/朗读服务表单存在且可见/缺模型提示）✅；本地桩 TTSWorker 合成 PASS + 未配置报错提示 PASS ✅
- 涉及：`ai_chat.py`（_browser_headers 三处应用/TTSWorker 重写/_speak_text/set_tts_api/test_tts_api）、`settings_panel.py`（删引擎下拉与云端音色/api_tts_box 常驻/文案）
- 备注：edge-tts/SAPI 代码保留未删（后续可再瘦身移除依赖）；桌面 exe 重新打包部署


### 2026-09-07（新增「AI 功能」：AI 对话 + TTS 语音朗读（云端/本地双引擎））
- **需求**：桌宠加 AI 对话；回答文字显示在桌宠旁并朗读（TTS 云端+本地都支持）；设置面板新增「AI 功能」模块，**默认关闭**；TTS 依附 AI（朗读文本=AI 回复），AI 与朗读各自独立开关
- **交互（用户拍板）**：右键桌宠 → 弹聊天窗打字 → AI 回复以**气泡显示在桌宠旁边** + 朗读
- **技术选型（子代理调研 + 本机实测）**：
  - AI：OpenAI 兼容 `/chat/completions`（纯 urllib 实现，零新依赖；走系统代理/环境变量）
  - 云端 TTS：**edge-tts 7.2.8**（微软 Edge 免费语音，24kHz mp3 流；大陆直连 403 → **自动探测代理**（环境变量→本机常见 7890/7897/10809 端口），传 `proxy=` 给 Communicate）
  - 本地 TTS：**comtypes 直调 SAPI.SpVoice → SpFileStream 写 wav**（零新依赖，SpeechLib 类型库随包；**关键坑：Format.Type 必须先设再 Open**，否则 0x80045002）
  - 播放：TTS 合成产物（tts_cache/ 目录）由 QMediaPlayer 播放（mp3/wav 通吃）；云端失败自动重试 1 次 + 回退本地
- **新文件 `ai_chat.py`**：AIWorker（对话）/ TTSWorker（合成，QThread + asyncio.run 隔离线程，序列号 seq 打断旧朗读）/ BubbleWidget（桌宠旁跟随气泡，20s 自动消失，点关闭，出屏自动翻转）/ ChatWindow（右键聊天窗，可拖动，多轮上下文）/ AiChatManager（配置读写 `pet_config.json` 的 `ai` 段 + 播放）
- **`pet.py`**：import ai_chat（try/except 可选）；构造 `self.ai = AiChatManager(self)`；`mousePressEvent` 右键 → `ai.open_chat()`（仅 AI 开启时）；closeEvent → `ai.close_all()`
- **`settings_panel.py`** 新增模块5「AI 功能（对话 + 语音朗读）」：启用 AI 对话开关（默认关）/ 服务器地址 / API 密钥（密码框）/ 模型名 / 保存 + 测试连接 / 朗读开关 / 引擎（云端/本地）/ 云端音色下拉（晓晓等 6 个）/ 提示文案（AI 可单独聊天不开朗读；云端失败自动回退本地）
- **spec**：hiddenimports + `ai_chat`、`comtypes.gen.SpeechLib`；datas + `collect_data_files('edge_tts')`（voices.json 必须随包）
- **验证**：py_compile ✅；ai_selftest（模块加载/配置读写/云端合成 17KB 1.4s/本地合成 wav/代理探测 7890）✅；gui_smoke（聊天窗构造/缺 key 提示/气泡可见）✅；ruff 自动修复 ✅；exe 打包后启动正常
- 涉及：`ai_chat.py`（新建）、`pet.py`（HAS_AI/self.ai/右键/closeEvent）、`settings_panel.py`（模块5+AI handlers）、`卡丘简易桌宠.spec`（hiddenimports+datas）
- 备注：桌面 exe 已部署；用户需在面板填**服务器地址/API 密钥/模型**并保存后可用（key 明文存 pet_config.json 的 ai 段）


### 2026-09-07（AI 功能升级：入口置顶折叠「AI」页 + 模型自动检测下拉 + 系统提示词/TTS 提示词可自定义 + TTS 强制依附 AI）
- **需求（用户连提）**：
  1. 填好服务器地址+API 密钥后应**自动检测可用模型**，下拉挑选（不再手填模型名）
  2. 「AI 功能」应显示在设置面板**最上面**，显示「AI」，点开是**配置页面**
  3. **系统提示词**可自定义
  4. **TTS 必须 AI 对话打开才能开**（否则无法写 TTS 提示词）；开 TTS 时 AI 需加载一份 **TTS 系统提示词**，把直接输出给用户的结果先改写成适合朗读的稿子再朗读
- **实现**（`ai_chat.py` + `settings_panel.py`）：
  1. **模型自动检测**：新增 `_list_models(base_url, api_key)`（GET `{base}/models`，OpenAI 兼容标准接口，401 实测确认存在）+ `AiChatManager.fetch_models(on_done)`（后台线程）；面板填完地址/密钥 editingFinished 或点「↻ 刷新模型」→ 自动拉取模型列表填进可编辑下拉 `cmb_ai_model`
  2. **AI 入口置顶**：滚动区**最上面**新增折叠头大按钮「🤖 AI」（checkable、深蓝高亮），点击 `_toggle_ai_page` 展开/收起 `ai_box` 配置容器（默认收起）；原底部 gb_ai 模块移除
  3. **系统提示词可编辑**：`ed_ai_sysprompt`（QPlainTextEdit，默认填充桌宠人设，textChanged 即存配置 `ai.system_prompt`）；对话请求 system 用 `system_prompt()`（未填回退默认）
  4. **TTS 提示词**：`default_tts_prompt()`（语音播报助手提示词：口语化/去 markdown/表情/链接/符号）+ `ed_ai_ttsprompt` 编辑（存 `ai.tts_prompt`）
  5. **朗读改稿链路**：AI 回复 `_on_ai_done` → 若 TTS 开且 AI 开 → `_rewrite_for_tts` 用 TTS 提示词 + AI 回复发起第二次 LLM 改写 → `_on_rewrite_done` 朗读改写稿（改写失败自动朗读原文兜底）；`_pending_tts_seq` 序号防串读
  6. **TTS 强制依附 AI**：面板 AI 关 → TTS 自动取消勾选并置灰（`setEnabled(False)`）；AI 开才恢复可勾；`_ai_apply_tts` 勾选时校验 AI 开否则拒；`ai_chat._on_ai_done` 也兜底 `tts_enabled and not enabled → set_tts_enabled(False)`
  7. **健壮性**：`BubbleWidget._reposition` 对 pet 无几何容错（防 None frameGeometry）
- **验证**：py_compile ✅；面板冒烟：AI 折叠展开 visible True↔False、AI 关时勾 TTS 被拒、AI 开→TTS 可勾、AI 关→TTS 自动取消+置灰 ✅；模型检测（填假 key → 401 提示不崩）✅；改稿链路（无 key 静默/坏 key 改写失败回退原文→云端合成播放真实走通）✅；ai_selftest 全过（云端合成 17KB/本地 wav/代理探测）✅
- 涉及：`ai_chat.py`（_list_models/fetch_models/system_prompt/set_system_prompt/tts_prompt/set_tts_prompt/_rewrite_for_tts/_on_rewrite_done/_speak_text/_pending_tts_seq/_on_tts_done/BubbleWidget 容错）、`settings_panel.py`（AI 折叠头+ai_box 置顶/cmb_ai_model/ed_ai_sysprompt/ed_ai_ttsprompt/handlers 重构/refresh_all 依赖联动）
- 备注：桌面 exe 已打包部署（63b3dd0）；用户需在面板填**服务器地址/API 密钥/模型**并保存后可用（key 明文存 pet_config.json 的 ai 段）


### 2026-09-07（TTS 引擎扩充：自定义 API 语音服务 + 桌宠大小滑块禁滚轮 + 模型检测失败分类提示 + <provider> 403 排查）
- **需求（用户反馈）**：
  1. 桌宠大小滑块悬停滚动滚轮会误改大小 → 去掉滚轮调值
  2. TTS 也需要**自己填 API 服务地址**（不要只能浏览器那套 edge-tts）；支持自定义 OpenAI 兼容语音
  3. 填了 <provider>.ai 的地址+key，模型没识别出来 → 排查
- **实现**（`ai_chat.py` + `settings_panel.py`）：
  1. **NoWheelSlider**：新增禁滚轮滑块类（wheelEvent 忽略），桌宠大小滑块 `sld_size` 改用它
  2. **TTS 自定义 API 引擎** `TTS_MODE_API='api'`：面板朗读引擎下拉加「自定义 API 语音服务」，选它显示 服务地址/API 密钥/语音模型/音色 表单 +「测试语音」按钮（OpenAI 兼容 POST `{base}/audio/speech`，body `{model,input,voice,response_format:mp3}`，Bearer key，响应 mp3 落盘走播放器）；配置存 `ai.tts_api_base/tts_api_key/tts_api_model/tts_api_voice`；`_norm_base_url` 规整地址（容忍末尾带 /chat/completions 或 /models 的填法）；api 模式失败自动回退本地 SAPI
  3. **云端音色行**包成 `cloud_voice_box`、API 表单 `api_tts_box`，按引擎显隐联动（`_sync_tts_mode_ui`）
  4. **模型检测失败分类提示**：403→服务商未开放模型列表可手动输入；401→密钥无效；404→地址不对；其余原样
- **403 排查结论（用户 <provider> 服务）**：地址 `https://api.<provider>.ai/provider/v1/chat/completions` 是官方正确端点（文档确认）；直连/代理都 403 → 非网络问题，是该服务要求 **Studio 生成的专用 key + Provider 及以上套餐**（官网：除 Go 套餐外 GOAT/Pro/Max/Team/Provider 才有 API 权限，Provider 计划以上才有 API）；让用户在 <provider>.ai Studio → API Keys 里重新生成 key 并确认套餐
- **验证**：py_compile ✅；panel_smoke3（13 项：引擎含 API 项/表单显隐联动/配置保存/缺字段提示/滑块滚轮被忽略）✅；本地 HTTP 桩验证 `_api_speech_synth` 请求体（model/input/voice/response_format + Bearer）✅；panel_smoke2 + ai_selftest 回归全过 ✅
- 涉及：`ai_chat.py`（TTS_MODE_API/_api_speech_synth/TTSWorker api 分支/set_tts_api/test_tts_api/_norm_base_url 应用到 models）、`settings_panel.py`（NoWheelSlider/api_tts_box 表单/cloud_voice_box/_sync_tts_mode_ui/_ai_apply_tts_api/_ai_test_tts_api/refresh_all/403 提示）
- 备注：桌面 exe 已重新打包部署；**用户需在 <provider> Studio 生成专用 key 或改用支持 OpenAI 语音的服务**

### 2026-09-06（设置面板：大小可填数字 + 面板不再一直置顶）
- **需求**：①桌宠大小处要能直接填数字；②设置面板（选项框）不要一直置顶
- **实现**（`settings_panel.py`）：
  1. 大小行：数值标签换成 **QSpinBox**（60–600 可手填 + 上下箭头微调，后缀 "px"），与滑块双向联动（blockSignals 防循环），`_on_size_changed` 按 sender 同步另一控件并实时调 `pet.set_pet_size`
  2. 面板窗口去掉 `WindowStaysOnTopHint`（不再永远盖在别的窗口上）；打开时仍 `raise_` + `activateWindow`（点击桌宠打开瞬间正常置前，之后可被其它窗口覆盖）
  3. `refresh_all` 同步滑块 + spinbox 双值
- **验证**：py_compile ✅；exe 部署启动正常
- 涉及：`settings_panel.py`（setWindowFlags/QSpinBox/_on_size_changed/refresh_all）

### 2026-09-06（音频播放性能优化：解码缓存 / 时长缓存 / 预解码 / 连点去抖）
- **需求**：提升播放性能（更快播放音频）
- **实现**（`pet.py`）：
  1. **解码缓存**：`_decode_and_prepare` 结果按路径 LRU 缓存（上限 4 条、>5MB 不缓存、访问刷新）——重复播放同一音频（点击语音高频触发）不再每次重读整个文件解码；实测热缓存比冷解码快数千倍
  2. **时长缓存**：`audio_duration_seconds` 按路径 + mtime 校验缓存（上限 64 条）——PTT 释放线程不再反复读文件头
  3. **预解码**：启动 1.5s 后后台线程预解码「当前角色点击语音 + 语音来源第 1 条」→ 首次播放免等待
  4. **连点去抖**：`play_audio` 同一文件 300ms 内重复请求忽略——快速连点不叠音
  5. **缓存失效**：删除音频/删除角色时同步清理对应解码/时长缓存
- **验证**：py_compile ✅；LRU/去抖逻辑单测 ✅；缓存基准：冷解码 1.9ms → 热缓存 ~0ms ✅；exe 部署正常（43.99MB）
- 涉及：`pet.py`（_decode_cache/_cache_decode/_decode_and_prepare/_dur_cache/audio_duration_seconds/play_audio 去抖/_preload_click_audio/remove_audio_file/remove_role 清缓存）

### 2026-09-06（设置面板加桌宠大小滑块实时预览 + 再次瘦身 46.1→44MB）
- **需求**：设置面板加一个可调整桌宠大小的滑块，拖动实时看效果
- **实现**（`pet.py` + `settings_panel.py`）：
  1. `pet.py`：`_pet_size` 实例变量（默认 BASE_SIZE=200，读取配置 `pet_size` 持久化）；构造 `setFixedSize(_pet_size)`；`load_role`/`_set_role_frame` 全部改用 `_pet_size` 缩放
  2. `set_pet_size(size)`：60–600px 范围；保持窗口中心不变；静态角色从 `_src_pixmap` 原图直接重缩放（丝滑），动图角色重建 QMovie；持久化到配置；clamp 屏幕内 + 更新朝向
  3. `load_role` 新增保存未缩放原图 `_src_pixmap`
  4. `settings_panel.py`：形象角色模块加「桌宠大小」QSlider（60-600，步进10）+ 数值标签；`_on_size_changed` 实时调 `pet.set_pet_size`；`refresh_all` 同步滑块
- **进一步瘦身 46.1 → 44.0MB**：spec `_BIN_KEEP` 追加 `Qt6Svg`/`libcrypto-3`/`libssl-3`（Qt TLS 运行时才按需加载，桌宠纯本地播放永不触达；Qt6Svg 界面无 SVG 用）；实测 exe 启动正常 + 本地 mp3 播放正常（不依赖 openssl）
- **素材**：星绘 image.png 水平翻转（用户反馈表情反了）——桌面数据版 + 项目源码版都翻，透明保留
- **验证**：py_compile ✅；隔离 exe 启动 QtMultimedia 正常 ✅；本地 mp3 播放 OK ✅；大小范围逻辑单测 ✅；exe 46.1→43.99MB
- 涉及：`pet.py`（_pet_size/_src_pixmap/set_pet_size/load_role/_set_role_frame）、`settings_panel.py`（QSlider/_on_size_changed/refresh_all）、`卡丘简易桌宠.spec`（_BIN_KEEP）、`assets/characters/星绘/image.png`

### 2026-09-06（左右翻转加平滑动画：cos 曲线压扁转身，不再生硬）
- **需求**：上一版左右翻转是瞬间镜像，太生硬 → 要平滑"转身"动画
- **实现**（`pet.py`）：
  1. 新增翻转动画状态：`_flip_from/_flip_to/_flip_timer/_flip_frames/_flip_idx/_flip_scale_x`
  2. `_update_facing()`：朝向变化时不再瞬间翻转，改启动 `_start_flip_anim()`（18 帧 @16ms ≈ 0.29s）
  3. `_flip_step()`：水平 scale = `from * cos(πt)` —— t=0→±1、t=0.5→**0（角色水平压成一线）**、t=1→∓1（转身完成）；正反方向同一条公式
  4. `paintEvent`：水平方向乘 `_flip_scale_x`（静止=±1，动画中平滑过零），与按压 scale 相乘不冲突；三横按钮/toast 不翻转
  5. 动画中断（快速来回拖）→ `_start_flip_anim` stop 旧 timer 重启，from 取当前朝向 ±1 保证曲线不跳变
- **验证**：py_compile ✅；曲线单测（1→0.707→0→-0.707→-1 正反平滑过零）✅；exe 部署启动正常（uia=True）
- 涉及：`pet.py`（构造翻转状态/_update_facing/_start_flip_anim/_flip_step/paintEvent）

### 2026-09-06（拖动不出屏 + 按屏幕位置自动左右翻转）
- **需求**：①拖动桌宠过头会拖出屏幕外，要限制在屏幕内；②根据窗口在屏幕左右的位置自动翻转（角色面向屏幕中心）
- **实现**（`pet.py`）：
  1. `_clamp_to_screen(x, y)`：拖动时把窗口左上角限制在鼠标所在屏幕可用区域（四个方向都 clamp），多屏时用 `QApplication.screenAt` 按窗口中心定位所在屏
  2. `_facing` 字段（+1 正常 / -1 水平镜像）：新增独立于按压动画的朝向
  3. `_update_facing()`：窗口中心在屏幕左半边 → 脸朝右(+1)；右半边 → 脸朝左(-1)；拖动中实时更新 + 松开/place_default 后再更新
  4. `paintEvent`：`painter.scale(_scale_x * _facing, _scale_y)` —— 翻转与按压缩放相乘不冲突；GIF 动图帧走同一 pixmap 也自动镜像；三横按钮/toast 不翻转（独立绘制）
  5. `mouseMoveEvent` 拖动用 clamp 后的坐标；`place_default` 初始调用 facing（默认右下角 → 脸朝左）
- **验证**：py_compile ✅；facing/clamp 数学单测（右下角→-1、左侧→+1、左右下拖过头 clamp 正确）✅；exe 部署启动正常（uia=True）
- 涉及：`pet.py`（_clamp_to_screen/_update_facing/_facing/paintEvent/mouseMoveEvent/mouseReleaseEvent/place_default）

### 2026-09-06（修复：Qt6Network 误删导致 QtMultimedia 崩溃 + UIA 通用输入判定，DSH/Electron 聊天框不再误触）
- **问题1（崩溃）**：瘦身时把 Qt6Network.dll 也过滤掉 → Qt6Multimedia.dll 导入表依赖它 → `ImportError: DLL load failed while importing QtMultimedia`
  - **教训**：**不能砍 Qt6Network**（QtMultimedia 在 Windows 依赖它）；Qt6Pdf/opengl32sw 可砍
  - 修复：spec 的 excludes 与 `_BIN_KEEP` 移除 Qt6Network；exe 45.7MB 恢复可用
- **问题2（DSH/Electron 聊天框不识别）**：DSH Desktop（Electron/Chromium 内核）进程名不在白名单、窗口类 `Chrome_WidgetWin_1` 不设 hwndCaret、焦点控件类名拿不到 → 传统判据全失效 → 打字按小键盘仍吞键播语音
  - Chromium 系窗口特征：顶层类 `Chrome_WidgetWin_1`、hwndFocus=顶层自己、hwndCaret=None（自绘光标）
- **修复（UIA 通用判定）**：
  1. 引入 **UI Automation（comtypes + UIAutomationClient）**：查前台焦点元素是否支持 TextPattern/ValuePattern/是 Edit/Document 控件 → **通用识别"正在输入"**，不依赖进程白名单（QQ/微信/DSH/浏览器全兼容）
  2. `_uia_focus_is_text(hwnd)`：带 1 秒缓存（UIA 查询 ~10-50ms，缓存后近零开销）；控件类型 50004(Edit)/50030(Document)/50032/50033 + 模式 10014/10002
  3. `foreground_is_input()` 增加判据⑤：仅当窗口类名属 Chromium 系（chrome_widgetwin）且传统判据失败才调 UIA（减少开销）
  4. 判据②改用 `gti.hwndFocus`（前台线程真实焦点）替代无效的 `GetFocus()`（它只返回调用线程焦点）
  5. spec hiddenimports 收集 comtypes + comtypes.gen.UIAutomationClient（PyInstaller 打包验证 uia=True ✅）
  6. hook 启动日志带 `(uia=True/False)` 便于诊断
- **验证**：隔离 exe 启动日志 `numpad smart hook started (uia=True)` ✅；DSH 窗口 UIA 判定可输入=True（24ms）✅；Edge/记事本前台判定正确 ✅；配置 BOM 测试假象排除（PowerShell Set-Content UTF8 带 BOM 会致 json.load 失败，正式 exe json.dump 无 BOM 无此问题）
- 涉及：`pet.py`（comtypes 引入/_uia_focus_is_text/_uia_cache/foreground_is_input 判据②⑤/hook 日志）、`卡丘简易桌宠.spec`（Qt6Network 放行 + comtypes hiddenimports）
- exe：45.7MB → 46.1MB（+comtypes）

### 2026-09-06（增强兼容与瘦身：更多音频/图片格式、单声道修复、各来源独立快捷键、智能输入判定加强、exe 65→44.5MB）
- **更多素材格式**：
  1. `AUDIO_EXTS` 扩到 16 种：原 mp3/wav/ogg/m4a/flac + **aac/opus/wma/aiff/aif/ape/amr/webm/m4b/caf/mp2**（soundfile 能解的走低延迟直出，其余自动回退 QtMultimedia 内置 ffmpeg 解码 → 全格式覆盖）
  2. 新增 `IMAGE_EXTS` 8 种：png/jpg/jpeg/gif/webp/bmp/ico/avif；`role_image()` 支持固定名（cover/avatar 等）+ 任意支持图 + **webp 动图**（QMovie）；`load_role` 统一走 role_image()
  3. 设置面板导入/拖放白名单改为引用 `pet.AUDIO_EXTS/IMAGE_EXTS`（不再硬编码），动图 .gif/.webp 保留原名
- **修复单声道只有左声道有声音**：`_adapt_to_device` 声道不足时原来补**零**（右声道静音）→ 改为**复制已有声道**（单声道→双耳都响）
- **每个语音来源独立快捷键**：
  1. 绑定冲突释放改为**同来源才释放**（不同角色/通用语音可绑同一键，互不干扰）
  2. `_hotkey_slot_audio`：小键盘数字先查**当前来源绑定到 Num<n> 的音频**，无绑定回退按位置
  3. 绑数字键时若小键盘开关没开 → **自动开启**
  4. 设置面板语音来源下拉切换后自动刷新音频列表/监视目录；面板文案提示"可绑 F1 或小键盘 1-9，各来源一套"
- **智能输入判定加强**（修复打字时误触发播语音+按 V）：
  1. 增加判据②：前台线程焦点控件类名检查（GetFocus）；判据③④加强
  2. `_TEXT_INPUT_CN` 扩充（textbox/textfield/input/windowsuicore 等现代控件类）
  3. **explorer 从输入白名单移除**（桌面/看文件时按小键盘应触发语音；重命名文件由 Edit 类判据兜底）
- **修复**：NumpadPlayHook `_poll` 的 `_last` 防重 bug（连按同一数字第二次不触发）
- **exe 瘦身 65MB → 44.5MB（-31.5%）**：spec 排除 PIL/pytest/twisted/OpenSSL/cryptography 等误收模块；binaries 过滤移除 Qt6Pdf/Qt6Network/opengl32sw 等无用 Qt DLL（**保留 avcodec 等 ffmpeg 引擎 = 全格式解码关键**）
- **UI**：设置面板移除「切换」按钮（点角色名即切换）
- **验证**：py_compile ✅；单声道复制逻辑单测 PASS ✅；各来源同键共存单测 PASS ✅；真实记事本前台 → 输入判定 True ✅；桌面前台 → False ✅；exe 冒烟启动、numpad smart hook started ✅；Qt 支持 webp/gif 格式确认 ✅
- 涉及：`pet.py`（AUDIO_EXTS/IMAGE_EXTS/role_image/load_role/_adapt_to_device/_apply_capture/_hotkey_slot_audio/foreground_is_input/NumpadPlayHook._poll）、`settings_panel.py`（白名单引用/切换按钮/_on_voice_src_changed 刷新/sync_numpad_checkbox/文案）、`卡丘简易桌宠.spec`（excludes+binaries 过滤）

### 2026-09-06（用户数据收纳到独立文件夹：桌面不再散落文件；旧版自动迁移；重新打包 exe）
- **问题**：桌面版 exe 把 `pet_config.json` / `assets` / `pet_debug.log` 直接散在 exe 同目录（桌面），用户觉得乱
- **修复**（`pet.py`）：
  1. 新增 `USER_DATA_DIR = '卡丘简易桌宠数据'`：打包后所有可写数据统一收进 **exe 同目录下的「卡丘简易桌宠数据」子文件夹**（exe 旁只留一个数据夹）；exe 目录不可写时依次回落：用户主目录下同名文件夹 → 用户主目录
  2. `base_dir()`：改为返回数据子文件夹（打包态）；未打包仍 = 脚本目录（开发不变）
  3. `_pick_writable()`：候选目录逐个做写入测试，挑第一个可用的
  4. `_migrate_legacy_layout()`：模块加载即执行，发现 exe 旁旧版散件（pet_config.json/assets/pet_debug.log）且数据夹没有同名项时移入（只移一次）；设置面板走 `pet.base_dir()` 动态取路径自动跟随
  5. `CONFIG_FILE`/`_dbg` 全部基于 `base_dir()`，自动指向数据夹
- **打包**：`python -m PyInstaller --noconfirm --clean 卡丘简易桌宠.spec` → `dist\卡丘简易桌宠.exe`（65MB）
- **验证**：py_compile ✅；模拟打包迁移单测 9 项全 PASS ✅；隔离目录实测：旧散件自动移入数据夹、旧角色保留、默认角色星绘/白墨/艾卡 + 通用语音 seed、exe 旁无残留 ✅；桌面 exe 替换后实测：桌面从 4 项 → 「exe + 卡丘简易桌宠数据/」2 项，配置/角色/语音完整保留 ✅
- 涉及：`pet.py`（USER_DATA_DIR/_pick_writable/base_dir/bundle_dir/_migrate_legacy_layout/CONFIG_FILE/_dbg 模块加载顺序重排）

### 2026-09-06（修复打包后资源目录只读：base_dir 改为 exe 同目录 + 首次运行 seed 默认资源；重新打包 exe）
- **问题**：`base_dir()` 打包后返回 `sys._MEIPASS`（PyInstaller 临时解压目录，**只读、每次启动重建**）；而新版设置面板的导入角色、拖放导入、通用语音、删除操作全部基于 `base_dir()` 写 assets → 打包成 exe 后这些功能会写入临时目录、**退出即丢甚至写失败**。v1.4.0 时代只有内置只读角色（读 _MEIPASS 没问题），加了用户导入功能后必须区分「内置资源（只读）」与「用户数据（可写持久）」
- **修复**（`pet.py`）：
  1. `bundle_dir()`：内置资源目录，打包后 = `_MEIPASS`（只读）；未打包 = 脚本目录
  2. `base_dir()`：**用户数据目录**，打包后 = exe 同目录（与 pet_config.json 一致），未打包 = 脚本目录；带写入测试（失败回落 home）
  3. `_seed_default_assets()`：打包首次运行把默认角色（星绘/白墨/艾卡）与 common_voice 复制到 exe 旁 assets（已有则不覆盖，只补缺失角色）；模块级 `_seeded` 标志保证只播一次
  4. `assets_dir()` 现在指向 base_dir()（可写持久）；`_dbg` 日志也写到 base_dir()
  5. `_relaunch_as_admin()`：打包态直接提权 exe 自己（不再提权 python 脚本）
- **打包**：`pyinstaller --onefile --windowed --name "卡丘简易桌宠" --icon assets/app.ico --add-data "assets;assets" --collect-submodules sounddevice/soundfile/numpy --hidden-import ... --exclude-module PyQt6.QtQml/WebEngine/Quick/QmlModels pet.py` → `dist\卡丘简易桌宠.exe`（66MB）
- **验证**：打包路径测试（模拟 _MEIPASS：bundle_dir/base_dir/seed 复制默认角色到 exe 旁）✅；隔离目录实测 exe 首次运行自动 seed 星绘/白墨/艾卡 + 2 条通用语音 + pet_debug.log ✅；桌面 exe 提权启动、`numpad smart hook started` 智能钩子运行 ✅；进程结构单实例（bootloader 12476 无窗口 + 桌宠 44392 有窗口）✅
- 注意：exe 首次运行会在**exe 所在目录**生成 assets/ 与 pet_config.json（用户数据持久化于此）
- 涉及：`pet.py`（bundle_dir/base_dir/_seed_default_assets/_seeded/assets_dir/_dbg/_relaunch_as_admin）

### 2026-09-05（小键盘快捷播放升级为"智能模式"：聚焦输入框自动放行，不打扰打字）
- **需求**：开启小键盘 1-9 快捷播放时，聚焦输入框/打字场景应自动不占用（放行数字输入），只有游戏/桌面等非输入场景才触发语音
- **方案**：废弃 `RegisterHotKey` 全局裸数字键（无条件抢键），改用 **WH_KEYBOARD_LL 常驻低级钩子 + 前台焦点智能判定**
- **实现**（`pet.py`）：
  1. `GUITHREADINFO` 自定义结构 + Win32 API 原型声明（GetForegroundWindow/GetWindowThreadProcessId/GetGUIThreadInfo/GetClassNameW 防 64 位截断）
  2. `foreground_is_input()`：三判据任中即放行——①前台线程 `hwndCaret` 非空（正在输入，最精确）②前台窗口类名命中输入控件（Edit/RichEdit/Console 等）③前台**进程名白名单**（浏览器 chrome/msedge/firefox、聊天 QQ/微信/钉钉/飞书、编辑器 vscode/notepad/idea、终端、Office 等）；进程名用 `OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)` + `QueryFullProcessImageNameW`（无需管理员）
  3. `NumpadPlayHook`：常驻低级钩子（独立线程 + GetMessage 循环，模式同 KeyCapture）；小键盘 1-9 按下 → 输入态则 `CallNextHookEx` 放行，非输入态则吞键（返回 1）+ 主线程轮询回调播放；注入键（LLKHF_INJECTED）始终放行
  4. `_numpad_hook_start/_stop`：启停钩子；`set_numpad_enabled` 改为启停钩子（不再 RegisterHotKey）；`set_hotkeys_enabled` 总开关关→停钩子、开→恢复；启动时若配置开启则自动启钩子；`closeEvent` 停钩子
  5. `_register_hotkeys_now` 只负责自定义键（F1 等），小键盘不再注册
- **面板/菜单**：文案改为「小键盘1-9快捷播放（智能：打字/输入框时自动放行）」
- **验证**：py_compile ✅；前台 Edge（msedge.exe 白名单）→ 判定 True 放行 ✅；钩子启停不崩、线程存活 ✅；端到端 mock：非输入态 Num1→吞键触发播放、输入态 Num2→放行不触发 ✅；面板开关联动（勾选启钩子/取消停/总开关关也停）✅
- 涉及：`pet.py`（GUITHREADINFO/foreground_is_input/NumpadPlayHook/_numpad_hook_start/_stop/set_numpad_enabled/set_hotkeys_enabled/_register_hotkeys_now/closeEvent/菜单文案）、`settings_panel.py`（chk_numpad 文案）

### 2026-09-05（删除音频/角色时自动清理快捷键绑定）
- **问题**：删除音频或整个角色后，`pet_config.json` 的 `audio_hotkeys` 仍残留其绑定 → 下次启动尝试注册已不存在文件的热键，浪费且行为不一致
- **修复**（`pet.py`）：
  1. `unbind_audio_key(audio_key)`：移除指定绑定 + 持久化 + 注销已注册的对应热键
  2. `remove_audio_file(path)`：删除音频文件并清理其绑定（面板删除音频改用）
  3. `remove_role(role)`：删除角色目录 + 清理该角色所有绑定（前缀 `role/`）+ 注销热键；当前角色拒绝删除（保护）
- **实现**（`settings_panel.py`）：`_delete_selected_audio` / `_delete_selected_role` 改调 pet 方法
- **验证**：py_compile ✅；测试：删单音频只清自己的绑定、删角色清全部绑定、删当前角色被拒 ✅
- 涉及：`pet.py`（unbind_audio_key/remove_audio_file/remove_role/import shutil）、`settings_panel.py`（_delete_selected_audio/_delete_selected_role）

### 2026-09-05（傻瓜化 UI：拖放导入角色/音频 + 修复小键盘抢键打出V的 bug）
- **需求**：优化 UI 简化添加角色/语音——直接拖文件进来；修复"开桌宠后按小键盘1打出V"的 bug
- **bug 根因（双重）**：
  1. 小键盘 1-9 被注册为**全局无修饰热键**（RegisterHotKey）→ 系统级抢键，打字时按小键盘数字不输入、被桌宠截获触发语音
  2. 触发语音时若开「自动按开麦键V」，桌宠用 SendInput 注入一个 V 到前台窗口 → 正在打字的地方出现"v"
- **修复**（`pet.py`）：
  1. 新增配置 `numpad_hotkeys`（默认 **False**）：小键盘 1-9 快捷播放改为**默认关闭**，需在面板/菜单显式开启（开启时提示"占用小键盘数字输入，适合游戏内"）；关闭时小键盘数字恢复正常打字
  2. `set_numpad_enabled`：开→注册 1-9（含重注册），关→注销；注册逻辑按开关控制
  3. `play_audio(path, ptt_override=None)` 新增覆盖参数；点击桌宠本体播放与面板试听**强制 ptt_override=False**——不再注入开麦键字母，杜绝在打字/聊天时被打断
  4. 原来全局热键 `set_hotkeys_enabled` 语义保留（只管自定义绑定键与小键盘总开关之间的联动）
- **实现**（`settings_panel.py`）：热键区拆为两个开关：①启用自定义语音快捷键（F1 等绑定键）②小键盘1-9快捷播放（默认关+占用提示）；refresh_all 同步勾选；`_on_numpad_toggled` handler
- **傻瓜化（拖放导入）**（`settings_panel.py`）：
  1. 面板 `setAcceptDrops(True)` + `dragEnter/Move/Leave/Drop` 事件；拖入时金色虚线高亮边框（paintEvent 叠加）
  2. `_handle_drop(urls)`：音频文件 mp3/wav/ogg/flac/m4a → 当前语音来源目录；文件夹（含 image.png/.gif）→ 复制为新角色；单张 png/jpg/gif → 以文件名新建角色目录（gif 保留原名动图，其它存 image.png）
  3. 「导入新形象」按钮升级为可**多选图片文件**导入（每张=新角色）；「打开角色文件夹」改为打开**当前语音来源**目录（通用语音→common_voice）
  4. 提示文案改傻瓜化：「直接拖进本窗口即可添加角色/导入音频」
- **验证**：py_compile ✅；逻辑脚本：默认 numpad 关→无热键；开→注册9个；关→注销；ptt_override 语义 ✅；拖放导入测试：png 建角色/文件夹建角色/音频入角色目录/通用来源导入 common_voice/目录按来源切换 + 清理 ✅；GUI 脚本：拖放高亮绘制、切换新角色加载图片不崩 ✅
- 涉及：`pet.py`（_numpad_enabled/set_numpad_enabled/play_audio ptt_override/play_click_voice/菜单加小键盘开关）、`settings_panel.py`（chk_numpad/_on_numpad_toggled/拖放事件/_handle_drop/_import_character 多图导入/_open_characters_folder 按来源/提示文案）

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

### 2026-09-05（设置面板架构：新建独立设置窗口替代弹出菜单 + 逐项修复）
- **背景**：弹出菜单点击选项不稳定（反复重开/闪没），用户拍板改用**独立设置面板窗口**
- **实现**（`settings_panel.py` 新建 + `pet.py` 联动）：
  1. `SettingsPanel`：无边框、置顶、可拖动标题栏；QGroupBox 四大模块：形象角色 / 语音音频 / 播放设备 / 快捷键开麦
  2. 角色列表：单击即切换当前角色、导入新形象（含角色图文件夹）、删除角色（当前角色禁删）；`QFileSystemWatcher` 监视当前角色目录，改动 250ms 防抖自动刷新音频列表
  3. 音频列表：单击仅选中、双击试听、导入音频、删除所选、🔑 绑定快捷键按钮（显式进入录制，避免误绑）；绑定键金色显示
  4. 播放设备：绑定麦克风（队友听）+ 自己监听（耳机），NoWheelComboBox 防滚轮误触
  5. 快捷键开麦：启用快捷键发话总开关、自动按开麦键、开麦键选择（V/B/C/X/Z/F1-5/自定义录制）
  6. 底部：刷新 / 打开角色文件夹 / 退出桌宠（红色）
  7. pet.py：`open_settings_panel()` 创建单例面板（注入 `_panel_mod.bind_pet_module` 避免循环导入）；三横按钮与托盘左键都打开面板；`set_bind_device` 等 setter 同步刷新面板
- **验证**：脚本验证面板创建/刷新/切换角色/绑定链路；用户实测
- 涉及：`settings_panel.py`（新建）、`pet.py`（open_settings_panel/_bind_pet_module/各 setter 同步面板）

### 2026-09-05（修复合辑：SendInput 按键 / 录制忽略注入键 / 绑定流程 / 无边框面板 / NoWheel 下拉）
- **SendInput 替代 keybd_event**：旧 API 部分游戏不识别 → 定义 KEYBDINPUT/MOUSEINPUT/_INPUTUNION 结构，`_send_key(vk, keyup)` 显式 argtypes/restype 防 64 位截断
- **录制误绑注入键**：音频试听触发 auto_ptt 会 SendInput 注入 V，被 KeyCapture 当成用户按键绑定 → `LLKHF_INJECTED(0x10)` 标志检测，注入键放行且不录制
- **音频单击不绑定**：单击仅选中提示，需再点「🔑 绑定/修改快捷键」才进入录制；绑定完成/取消后 `on_capture_finished` 恢复按钮 + 即时刷新列表显示键名
- **无边框面板**：settings_panel 去掉系统标题栏，无多余的 最小化/关闭 与自定义 ✕ 混叠
- **NoWheelComboBox**：滚轮悬停下拉框不切换选项（防误触）
- **验证**：脚本链路验证 + 用户实测
- 涉及：`pet.py`（_send_key/KeyCapture 注入过滤/绑定流程）、`settings_panel.py`（面板/NoWheel/按钮文字）

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
- **产物**：`dist\卡丘简易桌宠.exe`（63MB，PyQt6 + sounddevice + soundfile + numpy 全打包）；已复制桌面 `<user-desktop>\卡丘简易桌宠.exe`
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
- **涉及**：`<repo-root>\pet.py`（版本 1.2.0，+sounddevice/soundfile/numpy 导入、CONFIG 存取、list_output_devices、play_audio_direct、_build_role_menu ②绑定项、init_tray/refresh_tray_menu/_on_tray_activated、set_bind_device）；新增运行时依赖 `pet_config.json`
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
