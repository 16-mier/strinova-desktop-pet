# 卡丘简易桌宠（strinova-desktop-pet）

一个 **Python 3.14 + PyQt6** 开发的 Windows 桌面桌宠：透明置顶浮窗、点按播音、角色可扩展、可打包成单文件 exe（免 Python 环境）。

> 桌宠角色「星绘 / 白墨 / 艾卡」出自游戏《卡拉彼丘》(Strinova)，形象与语音为二创/游戏素材，仅作本地娱乐用途。

## 功能

- **透明置顶浮窗**：per-pixel alpha 完美透明，可拖动、贴边、置顶、托盘
- **点按播音**：点桌宠播语音（角色各自一套）；按压有"压扁回弹"动画
- **角色可扩展**：往 `assets/characters/` 丢一个文件夹（`image.png`/`.gif` + 语音 mp3）即新增角色
- **AI 对话 + TTS**：OpenAI 兼容接口聊天（右键/悬停弹出对话条），回复以无背景大字气泡显示在桌宠右侧，可选朗读
- **多会话上下文**：可新建/删除会话、回看完整记录、统计 token 用量与费用（DeepSeek 峰谷半价自动计价）
- **语音快捷键**：小键盘 1-9 快捷播放（打字时自动放行）、自定义键绑定、自动按开麦键(PTT)、绑定输出设备（如 Voicemeeter 让队友听到）
- **卡丘游戏设置**：卡拉彼丘「回车自动补词」实验功能（可开关、默认关）

## 使用

打包版（推荐普通用户）：

1. 双击 `卡丘简易桌宠_最新.exe`（单文件，免安装）
2. 数据（角色、语音、配置）自动放在 exe 同目录的 `卡丘简易桌宠数据\` 下
3. 鼠标移到桌宠身上 → 底部弹出 AI 对话条；移开 0.5 秒后自动收起
4. 右键桌宠 → AI 用量 / 打开三横菜单进设置

源码运行（开发）：

```bash
pip install PyQt6 PyQt6-Qt6 PyQt6-Qt6-Multimedia  # 详见依赖
python pet.py
```

## 打包成单文件 exe

```powershell
pip install pyinstaller
python -m PyInstaller --noconfirm --clean "卡丘简易桌宠.spec"
# 产物在 dist/卡丘简易桌宠.exe
```

## 目录结构

```
dsh-desktop-pet/
├── pet.py                ← 主程序（桌宠窗口/动画/键盘钩子/游戏联动）
├── ai_chat.py            ← AI 对话 + TTS（对话条/气泡/多会话/用量）
├── settings_panel.py     ← 设置面板窗口
├── 卡丘简易桌宠.spec      ← PyInstaller 打包配置
├── DEVELOPMENT.md        ← 开发日志（变更记录，接手先读）
├── assets/characters/    ← 角色目录（每角色一个子文件夹）
│   ├── 星绘/  (image.png + morning/noon/evening.mp3)
│   ├── 白墨/  (image.png + sprint.mp3)
│   └── 艾卡/  (gif 动图 + 语音)
└── assets/common_voice/  ← 通用语音（任意角色共用）
```

> `DesktopPet.cs` 是项目早期的 C#（WPF）调研版，已弃用，保留作技术参考。

## AI 对话配置

打开设置 → 「🤖 AI」：

- 服务器地址 / API 密钥 / 模型（OpenAI 兼容接口，如 DeepSeek / 中转）
- 可自定义系统提示词（人设）、TTS 朗读提示词、单价（每百万 token 美元，自动按 DeepSeek 峰谷半价）
- 测试连接、自动拉取模型列表

## 隐私说明

- API 密钥只保存在本地用户数据目录的 `pet_config.json`，**不会上传到本仓库**（已 gitignore）
- 项目不含任何真实密钥，均为占位/默认值

## 免责声明

本项目为个人学习用途的桌面宠物工具。游戏相关素材版权归原游戏/创作者所有；"回车自动补词"等游戏联动功能请自行确认符合游戏用户协议后使用。
