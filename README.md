# dsh-desktop-pet —— 独立 Win11 桌面桌宠

一个**零依赖、单文件、双击即跑**的 Windows 桌面桌宠（透明置顶浮窗，点按播音）。

## 特点

- **兼容性强**：Windows 10/11 自带 .NET Framework，无需装 Python/Pillow/node/任何运行时
- **最省性能**：WinForms，内存占用约 10-35MB（远小于 Electron 的几百 MB）
- **点按播音**：星绘按时间播 早/午/晚 问候；白墨播「冲刺」
- **可拖动、置顶**、右键菜单切换角色/退出
- **角色可扩展**：往 `assets\characters\` 丢一个文件夹即新增角色

## 使用

1. 双击 `DesktopPet.exe`（桌宠出现在右下角）
2. **点按**桌宠 = 播语音
3. **按住拖动** = 移动位置
4. **右键** = 切换角色 / 退出

## 编译（无需装任何工具，用 Windows 自带的 C# 编译器）

在 PowerShell 里运行：

```powershell
$csc = "$env:WINDIR\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
& $csc /nologo /target:winexe /platform:anycpu /out:"DesktopPet.exe" `
  /reference:System.Windows.Forms.dll /reference:System.Drawing.dll /reference:System.dll "DesktopPet.cs"
```

## 加新角色

在 `assets\characters\` 下新建一个文件夹，例如 `新角色\`：

```
assets\characters\新角色\
    image.png      ← 形象图（建议 180×180 透明 PNG）
    click.mp3      ← 点按语音
```

然后在 `DesktopPet.cs` 的 `CycleRole()` 里把 `白墨` 加入切换数组。若想"点按语音"完全由角色文件夹决定，可改用 `config.json` 声明每个角色的语音映射（后续可扩展）。

## 目录结构

```
dsh-desktop-pet/
├── DesktopPet.cs
├── DesktopPet.exe
├── DEVELOPMENT.md        ← 开发日志
├── README.md             ← 本文件
└── assets\characters\
    ├── 星绘\  (image.png + morning/noon/evening.mp3)
    └── 白墨\  (image.png + sprint.mp3)
```

## 资源来源

- 星绘形象/问候：由 dsh-pet 插件的 `assets\skins\星绘.png`、`assets\voices\{morning,noon,evening}.mp3` 复制
- 白墨形象/冲刺：由 dsh-pet 插件的 `assets\skins\白墨.png`、`assets\voices\白墨-sprint.mp3` 复制
