# 卡拉彼丘 Live2D / 3D 桌宠调研报告（2026-09-09 · 深度版）

> 目标：把卡丘桌宠从「静态 PNG/GIF」升级为 Live2D 或 3D 模型。
> **⚠ 关键实测更正：live2d-py 在 Windows 上装得上但实际渲染会崩（见 §0），Live2D 内嵌路线暂不可用；3D（Mate-Engine）是当前最稳路线。**

## 0. 环境实测结论（本次现场验证）
- Python 3.14.7 + Windows 11 x64（另有 3.12.10）
- `pip install live2d-py` 看似成功（0.7.0.4），但 **0.7.0.4 根本没有正式 cp314-win wheel**——PyPI 只有 0.7.0 有 cp314（后续修复版 .1–.4 只给到 cp313）。pip 把 0.7.0 的 cp314 wheel 装成 0.7.0.4，二进制错配。
- 实测结果：
  - **0.7.0.4 on Py3.14**：`LAppModel.LoadModelJson` 一调即 **0xC0000005 访问违例**（faulthandler 定位 C++ `_v3cpp`）
  - **0.7.0.4 on Py3.12**（独立 venv，正式 cp312 wheel）：同样崩 → 非 3.14 ABI 问题
  - **0.6.1.1 on Py3.12**：能真正加载 Haru.moc3 + 贴图 + 表情 + 物理（Cubism Core 05.01.0000 日志完整），但崩在 `userdata3.json` 解析 → 0.6.x 的确定性 bug
- GitHub [EasyLive2D/live2d-py Issues](https://github.com/EasyLive2D/live2d-py/issues) 有「crash in native」Open issue 佐证
- **结论：live2d-py 0.7.x/0.6.x 在 Windows 当前不可用于生产；要 Live2D 只能等库修复，或走 Web (Cubism Web SDK)/其它语言。3D Mate-Engine 是最稳落地路线。**

---

## 一、Live2D 路线

### 1.1 live2d-py 集成（PyQt6）—— ⚠ 实测不可用，暂缓
- `pip install live2d-py` 可装，但 Windows 二进制实际运行崩（见 §0）——**勿用于生产，等库修复**
- 理论方案（若库修复后）：在透明桌宠窗口内放一个 `QOpenGLWidget`，加载 `.moc3` 每帧 draw；透明关键 `WA_TranslucentBackground` + `glClearColor(0,0,0,0)`
- 模型来源：Live2D 官方示例模型（Nijima/Haru）、Booth 免费品、itch.io

### 1.2 卡拉彼丘角色做 Live2D 的现实性
- 官方无 Live2D 立绘（游戏为 3D，立绘是静态插画）→ 无现成官方 .moc3
- 可行来源：①B站/淘宝/闲鱼找同人 Live2D（稀缺、价位不等）；②官方立绘拆层自建（Cubism Editor 免费版，拆分工作量大，约需数天到数周）；③3D 模型转 Live2D 不现实
- **结论：做卡拉彼丘的 Live2D 需要「素材先行」，素材是最大瓶颈，而非渲染库**

---

## 二、3D 路线（本次推荐优先）

### 2.1 最佳方案：Mate-Engine（免费开源 3D 桌宠壳）
- GitHub [Mate-Engine](https://github.com/shinyflvre/Mate-Engine) Releases 下载 ZIP → 解压 → 双击 `MateEngineX.exe`，**免 build、免 .NET**
- 只吃 **.VRM** 模型（需把 PMX 转 VRM）
- 交互：待机/拖动/摸头/随音乐起舞/置顶/迷你模式/触摸反应
- **与现有 PyQt6 应用是两套独立程序**；可作为独立桌宠运行，或未来用 IPC 联动
- 注意：Defender 可能误报（无签名），VirusTotal 复核；默认 Alice 模型版权归 Yorshka Shop

### 2.2 获取卡拉彼丘 3D 模型
| 角色 | 来源 | 格式 | 可下载性 |
|---|---|---|---|
| 星绘「逆影蔷薇」| 模之屋官方 | PMX | 注册免费下载 |
| 米雪儿「绮星梦使」| 模之屋官方 | PMX (+有FBX版) | 注册免费 |
| 白墨 | Steam 工坊 | 官方 MMD | 免费订阅 |
| 诺诺/千代/香奈美 | 模之屋 | PMX | 注册免费 |
- **Sketchfab yabadiba 合集：实测英文名全空，基本不可用**
- kfsll/44mmd 是搬运网盘站，需会员，非首选

### 2.3 PMX → VRM 转换（核心动手环节）
- Blender 3.6 + **MMD Tools**（导入 PMX）+ **VRM-Addon-for-Blender**（导出 VRM）
- 坑：日文骨骼名→VRM 英文标准名（~30% 需手动映射）；MToon 材质转换；morph→blendshape 映射；物理弹簧骨重建
- 备选：Unity + UniVRM 转 FBX→VRM（绕远）

---

## 三、结论与建议路径

| 方案 | 成本 | 效果 | 推荐度 |
|---|---|---|---|
| **Mate-Engine + 模之屋 PMX→VRM** | 免费 + ~1 小时 | ★★★★★ 待机/触摸/跳舞全齐 | ⭐ 首选 |
| live2d-py 嵌入 PyQt6 | 免费 + 需先有 .moc3 | ★★★（库当前会崩，等修复）| ✗ 暂缓 |
| Desktop Mate + mod | 免费本体 + DLC ¥102/个 | ★★★ | ✗ 塞不进卡拉彼丘 |
| VPet/BandoriPet | 免费 | ★★ 2D | ✗ |
| PyQt6 自研 3D 渲染 | 人月级 | 可控 | 仅学习 |

**最短落地（今天）**：下载 Mate-Engine → 免费初音 VRM 先跑通 → 模之屋下星绘/米雪儿 PMX → Blender 转 VRM → 导入 Mate-Engine。

**保持 PyQt6 的长期路线**：等 live2d-py 修复（关注官方 Issue），或 PyQt 壳 + 独立 Godot/Unity 渲染进程（IPC）；当前先上 Mate-Engine。

## 版权
- 官方模型允许：优化骨骼刚体/UV 重制/合理服饰微调；**禁止商用、二次配布**
- 个人桌宠自用 OK；勿直播商用或打包发布
