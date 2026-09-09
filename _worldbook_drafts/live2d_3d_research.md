# 卡拉彼丘 Live2D / 3D 桌宠调研报告（2026-09-09）

> 目标：把卡丘桌宠从「静态 PNG/GIF」升级为 Live2D 或 3D 模型。结论先行：**最快路线 = 民间 MMD 模型 + 现成 3D 桌宠框架；其次 = 保持 PyQt6 用 live2d-py 嵌入 Live2D（需先有 .moc3 模型）。**

## 一、卡拉彼丘角色资源现状

### 1. 游戏内角色
- **UE4 引擎、原生 3D 模型**，打包在 `.pak` 文件里。
- 提取工具：**FModel**（最推荐，可能需 AES key）> Umodel/UE Viewer（部分包不支持）。
- 已有玩家成功提取进 Blender（Reddit r/Strinova，格式 FBX）。
- **游戏内没有 Live2D**：大厅/选人是 3D 模型，立绘是静态图，官方无 .moc3。

### 2. 现成模型（最快拿到手）
| 来源 | 内容 | 链接 |
|---|---|---|
| **模之屋**（官方账号入驻）| 93 个模型（星绘、米雪儿等皮肤），大量 motion | https://www.aplaybox.com/u/288404078/model |
| MMD 整合包 | 70+ 角色皮肤（含星绘/米雪儿/白墨），FB 渲染适配 | https://kfsll.com/3618.html |
| Sketchfab | Strinova 提取模型合集（FBX/glTF） | https://sketchfab.com/yabadiba/collections/strinova-0f0ad9e121cc47a9b81b27ee042070bf |
| Steam 创意工坊 | 角色替换模型（艾卡、米雪儿等）| 站内搜索 Strinova |

> 格式多为 **.pmx（MMD）** 或 FBX。

## 二、技术路线

### A. Python 内嵌 Live2D（保持现有 PyQt6 应用）
- **live2d-py**（EasyLive2D）：`pip install live2d-py`，Cubism Core 绑定、OpenGL，**兼容 PyQt6**，模型格式 `.moc3 + .model3.json + 贴图`。GitHub: https://github.com/EasyLive2D/live2d-py
- 授权：**Cubism SDK 个人自用免费**（仅公开发行需签约付费）。
- 卡点：**卡拉彼丘没有现成官方/民间 Live2D**，需用官方立绘拆层自建（工作量大）或找人做。

### B. 3D 桌宠（拿现成 MMD/pmx → VRM）
- **Mate-Engine**（Desktop Mate 免费开源替代，支持 VRM）：https://github.com/shinyflvre/Mate-Engine
- VPet（WPF 虚拟桌宠，Apache2.0）：https://github.com/LorisYounger/VPet
- BandoriPet（PySide6+Live2D 开源桌宠，与你的场景最像）：https://github.com/HELPMEEADICE/BANDORI-PET-REV
- 流程：模之屋下 .pmx → Blender+VRM 插件转 .VRM → Mate-Engine/Desktop Mate 打开。**当天可用、代码量 0。**

### C. 立绘转 Live2D 自动工具
- 不成熟：官方 Cubism AI 只能辅助生成变形器，拆分仍需人工。无「一键整图转 Live2D」工具。

## 三、建议（按性价比排序）
1. **最快**：模之屋/MMD 下载模型 → 转 VRM → Mate-Engine，30-60 分钟验收。
2. **保持 PyQt6**：找同人 Live2D 或自建 .moc3 → live2d-py 嵌入（需模型先行）。
3. **先低成本过渡**：用官方立绘做呼吸/晃动等静态动效，再逐步升级。

## 四、版权提醒
- 角色模型/立绘版权归开发商（创梦天地等）。**自用桌宠 OK；公开分享/商用有风险**，发布演示需注明「非官方，版权归开发方」。
