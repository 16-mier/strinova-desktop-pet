# VRM Animation（VRMA）生态调研报告

> 调研对象：Windows 11 3D 桌面宠物（PyQt6 + QtWebEngine + three.js r170 + @pixiv/three-vrm 3.5.5 + three-vrm-animation 3.5.5）
> 角色：米雪儿（《卡拉彼丘》Day1 Studio 官方 PMX → 自研工具链转 VRM 1.0）
> 日期：本次调研
> 标注约定：**【官方】** = 规范/官方仓库/官方博客一手核验；**【一手】** = 本次直接抓取到的页面原文；**【社区】** = 论坛/博客/第三方推断，未获官方确认

---

## 0. 结论先行（TL;DR）

**你的拖拽反应动画应该走「纯程序化动画」，不要引入 VRMA。VRMA 最多作为可选的"彩蛋插播动作"。**

三条决定性理由：

1. **需求已经被现有代码 100% 覆盖。** `web3d/pet_viewer.html` 里已经实现了你问题 3 描述的"被提起、腿自然下垂"的完整效果：绕髋关节的主钟摆（左右相位差）、小腿回收、**脚背绷直下垂**、手臂滞后垂摆、腰身稳住、squash & stretch、松手彻底归位。而且参数是刻意调的（`dragSway = new Spring(0, 22, 0.16)` 故意欠阻尼做明显余摆）。这不是"待办"，是"已完成"。
2. **VRMA 生态里根本没有"被提起/悬垂/摇晃"这类动作。** 官方免费 7 件套里没有 idle、没有被提起；BOOTH 上有 idle 但那是**站立**待机。这类动作在面向 VRoid Hub 拍照 / VTuber 直播的 VRMA 生态里基本不存在。
3. **引入 VRMA 会降低可控性并增加技术债。** VRMA 规范**禁止 hips 以外的平移、禁止 scale**，所以"被提起"的竖直位移本来就必须我们自己在 `scene`/`hips` 上做——正是现有 `dragOffsetY` 在做的事。而你的拖拽是**参数化连续量**（四个 spring 的连续输出），VRMA 是**离散录制片段**，用片段响应连续拖拽会掉进"拖到一半动画播完"的状态机地狱。另外 three.js 的 `AnimationMixer` **没有骨骼遮罩（bone mask）**，只有 Normal/Additive/Lerp 三种 blendMode，要做"上半身 VRMA + 下半身程序化"必须绕过 mixer 手工覆写骨骼。

**唯一值得考虑的 VRMA 用途**：作低频插播的彩蛋动作（偶尔挥手、比 V、伸懒腰），`crossFadeTo` 淡入淡出后回落到程序化 idle。推荐素材见 §2 的 R4（免费站立待机，个人商用皆可）。

---

## 1. VRMA 是什么、与 VRM 的关系、three-vrm-animation 3.5.5 能播什么

### 1.1 格式定义 【官方】

- 官方介绍页：<https://vrm.dev/en/vrma> （本次抓取时 TLS 握手失败，但内容经多方引用确认）
- **规范正文（一手核验）**：<https://github.com/vrm-c/vrm-specification/tree/master/specification/VRMC_vrm_animation-1.0>
- 规范状态：**Complete / Version 1.0**，Contributors: Shindo Tetsuro, 0b5vr
- 官方示例仓库（官方 7 件套的 demo 页）：<https://vrm.dev/en/vrma/>

**本质**：VRMA 是一个 **glTF 2.0 文件**，用扩展 `VRMC_vrm_animation` 把 glTF 节点映射到 VRM humanoid 骨骼 / 表情 / 视线。它**独立于 .vrm 模型文件**——规范明确写道：

> "It is intended to be used for separate glTF files that only describe animations. This extension is not expected to be included in VRM models with the `VRMC_vrm` extension."

正因为只描述"骨骼语义"而不描述"骨骼层级位置"，同一个 .vrma 可以套用到任意 VRM 模型上。**这是 VRMA 相对 Mixamo FBX / BVH 的核心优势**（不需要为每个模型重定向）。

### 1.2 规范允许 / 禁止的内容（这一节直接决定问题 3 的答案）【官方】

| 项 | 规定 |
|---|---|
| **rotation** | 全部 humanoid 骨骼都可以有 rotation 轨道 |
| **translation** | **只允许 `hips` 一根骨骼**。其他骨骼若含 translation，loader 会 `console.warn` 并**忽略该轨道** |
| **scale** | **禁止**。规范："The animation data for the Humanoid bone must not include scales"，且强烈建议 T-pose 层级也不要带 scale |
| **rest pose** | 必须符合 VRM T-pose |
| **帧率** | glTF 无帧率概念，官方**建议 30fps**（理由是线性插值下 30fps 已足够平滑） |
| **leftEye / rightEye** | **不能有动画**，一律交给 LookAt |
| **lookUp/lookDown/lookLeft/lookRight** | **不能有动画**，一律交给 LookAt |
| **expressions** | 用节点的 **translation 的 X 分量**当作表情权重，取值应 clamp 到 [0,1] |
| **lookAt** | 用一个节点的 rotation 充当视线方向；应用时转成 yaw-pitch 欧拉，**旋转序必须是 Extrinsic ZXY**（绕 Y = yaw，绕 X = pitch） |
| **多动画** | 单文件可含多个 animation，规范要求**默认加载 animations[0]** |

> **注意规范里那句话的严谨性**：官方原文是 "must not include scales"（对 Humanoid 骨骼的动画数据），并"strongly recommended"T-pose 层级本身不带 scale。所以你在处理自制 VRMA 时应把 scale 预先烘进层级，而不是指望运行时。

### 1.3 three-vrm-animation 3.5.5 的实际能力（**本机核验，非猜测**）

本机实际版本已确认：`web3d/vendor/three-vrm-animation.module.js` 头部注释为 `@pixiv/three-vrm-animation v3.5.5`，npm 上 `latest` 也正好是 3.5.5。

- **许可证：MIT**（npm registry 实测）。依赖：`@pixiv/three-vrm-core@3.5.5`、`@pixiv/types-vrmc-vrm-1.0@3.5.5`、`@pixiv/types-vrmc-vrm-animation-1.0@3.5.5`
- 仓库：<https://github.com/pixiv/three-vrm> （packages/three-vrm-animation）
- API 文档：<https://pixiv.github.io/three-vrm/docs/classes/three-vrm-animation.VRMAnimationLoaderPlugin.html>

**本机 bundle 实际导出的 7 个符号**（从 `three-vrm-animation.module.js` 尾部 export 语句读出）：

```
VRMAnimation
VRMAnimationLoaderPlugin
VRMLookAtQuaternionProxy
createVRMAnimationClip
createVRMAnimationExpressionTracks
createVRMAnimationHumanoidTracks
createVRMAnimationLookAtTrack
```

**它到底做什么**：

1. `VRMAnimationLoaderPlugin` 是 `GLTFLoader` 的插件。挂在 loader 上后 `loadAsync('x.vrma')` → `gltf.userData.vrmAnimations[0]`。
2. `createVRMAnimationClip(vrmAnimation, vrm)` 把 VRMA 转成**标准 `THREE.AnimationClip`**。
3. 之后**完全交给 three.js 原生 `AnimationMixer` / `AnimationAction` 播放**。

**两个很实用的自动处理（读源码确认，这是好消息）**：

- **身高自动归一化**：`createVRMAnimationHumanoidTracks` 里计算 `scale = humanoid.normalizedRestPose.hips.position[1] / vrmAnimation.restHipsPosition.y`，把 hips 位移按比例缩放。所以不同身高的模型套同一个 VRMA，位移量会自动适配。
- **坐标变换**：rotation 轨道做了 `parentWorld * a * childWorld⁻¹` 的共轭变换，translation 变换到 hips parent 空间。
- **T-pose 违规检测**：若 VRMA 的 rest hips 的 y 分量 ≈ 0 或更低，loader 会 warn "might violate the VRM T-pose"。

**版本兼容性**：dev 分支源码接受的 `specVersion` 是 `{'1.0', '1.0-draft'}`（**社区/源码推断**：draft 版本会额外打一条 warn，行为可能不同）。1.0 是当前正式版，用 1.0 即可。

### 1.4 ⚠️ 一个必须知道的限制：`AnimationMixer` 没有骨骼遮罩

**这是本次调研最重要的技术发现。** three.js r170（本机版本）的 `AnimationAction` 只有三种混合模式：

```
NormalAnimationBlendMode = 2500   // 默认：权重插值覆盖
AdditiveAnimationBlendMode = 2501 // 叠加（需要预先烘好的 delta/reference pose）
LerpAnimationBlendMode = 2502     // 直接 lerp
```

**没有 UpperBodyMask / bone layer 这类"只驱动部分骨骼"的能力**（Unity 的 AvatarMask 那种）。所以：

> "上半身播 VRMA、下半身继续我的程序化动画" 在 three.js 里**不能靠 mixer 的遮罩实现**。
> 可行做法只有两条：
> - **(a)** 用 `AdditiveAnimationBlendMode` 把 VRMA 当作叠加层（需自己烘焙参考姿态，工作量大、容易出鬼畜）
> - **(b)** mixer 播 VRMA 后，在 `animate()` 循环里、**渲染之前**，手动覆写下半身骨骼的 `quaternion`。
>
> 路线 (b) 其实是你现有架构的天然形态——你的 `animate()` 现在就是每帧直接写 `thighL.rotation.*`。等于"用 mixer 管上半身 + 自己管下半身"两套系统并存。

**落地判断：需改造，且改造后要维护两套动画系统 —— 不建议为拖拽去做。**

---

## 2. 免费 VRMA 资源清单与授权（含一手条款原文）

> 全部为 **BOOTH（pixiv 运营）** 上的免费下载项，条款为本次直接抓取页面正文所得。
> BOOTH 的「3Dモーション・アニメーション」子分类是官方为 VRMA 专门开设的（2024-02-21 随 VRMA 正式发布上线，见 §2 R1 的官方新闻）。

### R1. ★ 官方 VRoid Project「VRMアニメーション7種セット（.vrma）」【一手 + 官方】

- 链接：<https://booth.pm/ja/items/5512385> （0 JPY，`VRMA_MotionPack.zip` 3.29 MB）
- 官方新闻：<https://vroid.com/en/news/6HozzBIV0KkcKf9dc1fZGW>
- 官方推文：<https://x.com/vroid_pixiv_en/status/1760228616510603754>
- **内容（7 个动作）**：`VRMA_01` 全身を見せる / `VRMA_02` 挨拶 / `VRMA_03` Vサイン / `VRMA_04` 撃つ / `VRMA_05` 回る / `VRMA_06` モデルポーズ / `VRMA_07` 屈伸運動
  （即：全身展示 / 打招呼 / 比 V / 射击 / 转圈 / 模特姿势 / 深蹲）
- **条款原文要点（日文原文 + 英文对照均在页面）**：
  - 版权**归 pixiv 株式会社**（无论是否改変）
  - **允许自由改変**
  - **允许个人或法人商用**，条件是署名：`"Character animation credits to pixiv Inc.'s VRoid Project"`（日文版：「キャラクターアニメーション: ピクシブ株式会社 VRoidプロジェクト」）
  - **禁止**：把该动作或其改変作品以**"可提取状态"二次配布**（原文："許可なく取り出せる状態で二次配布すること"）；宗教/政治用途；违法；侵害第三方权利；性/显著暴力内容
  - 准据法：日本法
- **落地判断：✅ 能用（授权是所有候选里最宽松的之一）**。个人自用无需署名；**但注意：不含 idle，也不含"被提起"**。适合做彩蛋插播。
- ⚠️ 唯一硬约束是"**不得以可提取状态再配布**"。你自己离线跑、不把 .vrma 文件或打包产物发出去 → 不构成再配布。

### R2. 「【無料】VRMA回転アニメーション3種」【一手】

- 链接：<https://booth.pm/ja/items/7485491> （0 JPY，`vrma_kaiten.zip` 39.4 KB）
- 内容：A-pose 站立顺时针 360° 旋转，1 周 **5 秒 / 10 秒 / 15 秒** 三档
- **条款原文**：「Blenderなどでの改変は自由」「著作権の放棄はしておりません。**改変なしの再配布、再販売は禁止**です」「クレジット表記は不要」
- **落地判断：△ 能用但价值低**。只是转圈，且**明确禁止"未改変的再配布"**。个人自用没问题，但不如 R1。

### R3. 「[CC0]retargetingしたVRMアニメーション」【一手】

- 链接：<https://booth.pm/ja/items/7861818> （0 JPY，`CC0-animation-retarget-vrm.zip` 67.4 KB）
- 作者：sashii（该店另有「[CC0]Sachi VRMA 1」等多项 CC0 素材）
- 内容：**Run / SlowRun / Walk** 三个动作
- 来源：把 **CC0 的 Josie Character Model**（<https://jenjell.itch.io/josie-character-model>）的动作用 Blender + blender-mcp 重定向成 VRMA，**许可沿用 CC0**
- **落地判断：✅ 授权最干净（CC0 = 放弃一切权利）**。但只有走/跑，**没有 idle、没有被提起**。适合做"走路"类彩蛋。

### R4. ★★ 「【無料】AIチャット、VTuber用「自然な立ち待機モーション」VRMA」【一手】

- 链接：<https://booth.pm/ja/items/8815790> （0 JPY，`自然な立ち待機モーション.vrma` 5.37 MB）
- 作者：手久野 愛（note: <https://note.com/techno_aichannel>）
- **内容**：作者自述是为 ChatGPT Live AI 聊天用的 Vroid 角色制作的自然站立**待机（idle）**动作；角色原地站立自然待机，含**挥手、低头、比 V 手势**等，自述"自然で可愛らしい動き"
- **条款原文**：「基本的にご自由にお使いいただけます」 仅禁止两件事：
  1. 「このモーションファイル自体の再販売」（文件本身的再販売）
  2. 「自分で作成したモーションであると偽って配布・紹介すること」（谎称自己创作而配布/介绍）
  「**上記以外については、個人・商用を問わず、基本的に自由にご利用いただけます**」
- **落地判断：✅✅ 能用，且是本次找到的**唯一**现成 idle VRMA**。授权宽松（个人商用皆可），仅不许卖文件、不许冒名。**这是最值得下载的一个**。
- ⚠️ 注意：它是**站立** idle，**不是**"被提起"。

### R5. 「【無料】.vrmaポーズ5種」【一手】

- 链接：<https://booth.pm/ja/items/5876268> （0 JPY）
- 作者：織部呉服（该店另有免费的「【.vrma】Battle Pose Set（A〜E）」「【.vrma】流行りのポーズ5種」）
- **条款原文**：署名基本不需要；**改変OK**；**商用OK**；**「そのままの再販売、再配布禁止（改変後含む）」**；「著作権は放棄していません」
- **落地判断：△**。是**静态 pose** 而非 motion，对桌宠价值有限；但可作姿态参考或"定格"效果。授权本身宽松。

### R6. 其他 BOOTH 免费项（**需自查条款**）【一手链接，条款未逐一核验】

BOOTH 搜索 <https://booth.pm/ja/search/vrma?sort=price_asc> 共 **282 件**（搜索结果会变动）。除上述外值得注意的：

- 「vrma保管庫」 <https://booth.pm/ja/items/8233795> （0 JPY）
- 「VROIDHUB 撮影ブースvrmaアニメーション２」 <https://booth.pm/ja/items/8240870> （0 JPY）
- 「Animation vrma for VroidHub Photo Booth Collection 1」 <https://booth.pm/en/items/5520942>（⚠️ **600 JPY，不是免费**，条款："You can edit animation data / Credits not needed / **Do not use for commissions** / 仅在**改変后**可再配布（且必须免费）/ 仅可在 Booth.pm 再配布 / 改変后再配布必须署名"。**落地判断：❌ 放弃**，条款偏严且收费）
- 「TikTok_ダンスモーション」系列（八ツ橋まろんのお店，大量 0 JPY，含 .vrma / .anim / .fbx / .bvh / .vmd）：条款指向一个 Google Drive 里的「利用規約」，**未逐条核验**。
  **落地判断：⚠️ 不建议**。理由见 §5 第 7 条——舞蹈类素材常涉及第三方编舞/音乐著作权，权利链最脏，且与桌宠 idle 需求无关。

### 2.1 工具类开源项目（可用来**自己造** VRMA）

> ⚠️ 本次 GitHub API 返回 **403（限流）**，**这些仓库的开源许可证我未能核实**。使用前请自行确认 LICENSE。

- **`Kirakun0328/text-to-vrma`** — 文本 → VRMA 生成：输入自然语言，用 OpenAI API 设计关键帧，在浏览器内生成 `.vrma` 并立刻驱动 VRM。作者介绍文：<https://note.com/kirakundayo/n/n5fda0c6c97cf>
  **落地判断：✅ 最有价值的自造路线**（若将来真要做"被提起"的 VRMA）。**注意：生成结果受 OpenAI 服务条款约束**。
- **`nanasi-apps/vrm-animation-web-editor`** — 浏览器内 VRMA 时间轴编辑器，支持导入 VRM 1.0、导出 VRMA。基于 three.js + three-vrm。
  **落地判断：✅ 可手工精确制作用于 idle / 被提起的动作**。
- **`saori-eth/vrm-mixamo-retargeter`** / npm `vrm-mixamo-retarget` — Mixamo FBX → VRM 重定向（three.js）。**注意 Mixamo 动作受 Adobe 条款约束**（免费账号的动作可用于个人与商业项目，但不得再分发动作文件本身）。
- **`SillyTavern/Extension-VRM`** — 支持 `.fbx` / `.bvh` / `.vrma` 的 VRM 动画扩展（可参考其加载与播放实现）。
- **`tk256ailab/vrm-viewer`** — 自带一批 VRMA（Angry / Blush / Clapping / Goodbye / Jump 等），可作**测试素材**（非授权素材）。
- **`not-elm/desktop-homunculus`** — Rust/Bevy 写的桌面吉祥物，BOOTH 免费发放（<https://booth.pm/ja/items/6904924>）。**是"桌宠架构"参考，不是 VRMA 资源**。

---

## 3. 重点：idle 有没有？"被提起/悬垂/摇晃"有没有？混合可行吗？

### 3.1 有没有适合 idle 的 VRMA？

**有，但只有一个明确候选。**

- ❌ **官方 7 件套（R1）没有 idle**。7 个动作全是**一次性表演**（打招呼/比 V/射击/转圈/深蹲）。`VRMA_07 屈伸運動`（深蹲）和 `VRMA_01 全身を見せる` 勉强可循环，但那是"运动"不是"待机"，套在桌宠上会显得角色在做体操。
- ✅ **R4（<https://booth.pm/ja/items/8815790>）就是专门做的 idle**，且条款「個人・商用を問わず基本自由」。**这是本次调研唯一命中的现成 idle VRMA**。
- ⚠️ R3（CC0）只有走/跑。

**但即使有 idle，对你的价值也有限**：你**已经有**自写的程序化微动（`pet_viewer.html` 里的 idleBreath、idleShift、多点 sine 叠加的有机晃动、autoBlink 自动眨眼、CPU 顶点烘焙的口型）。引入一个固定循环的 VRMA idle 反而会**降低**"活着"的感觉——因为程序化 idle 可以无缝响应状态（说话、拖拽、表情），而录制的 idle 循环会在状态切换时产生突兀。

### 3.2 有没有"被提起/悬垂/摇晃"的 VRMA？

**没有找到。判断：生态内基本不存在这类动作。**

搜索覆盖了：BOOTH 的 vrma 全分类（282 件，按价格升序逐页扫）、idle 关键词检索、英文/日文/"悬垂/振り回し/吊り下げ"关键词检索、GitHub 平台检索。

这类动作在动捕素材库里通常属于**情侣互动或 ragdoll/被搬运**类别，而 VRMA 生态是**为 VRoid Hub 拍照与 VTuber 直播服务**的——需求集中在"摆 pose、跳舞、打招呼"，**根本没有"被拎起来"的需求**。所以：

> **结论：想要"被提起时腿自然下垂"，别指望下载，只能自己做。**

好消息是：**你已经做好了**（见 §0 理由 1）。

### 3.3 VRMA 混合能否组合出"被提起 + 腿下垂"？

**技术上可行，但性价比极低，不建议。**

拆开看这个需求其实是两件事：

| 子需求 | 性质 | VRMA 能做吗 | 你现在怎么做 |
|---|---|---|---|
| **被提起**（角色整体离地） | **translation** | ❌ **规范禁止 hips 以外平移**，且整体位移本来就在模型/场景层级 | `dragOffsetY += dA * 0.110`（离地约 11cm）+ squash & stretch |
| **腿自然下垂并钟摆** | **rotation** | ✅ 可以，但**没有现成素材** | 绕髋主钟摆 + 左右相位差 + 小腿回收 + **脚背绷直** |

**所以"被提起"这个效果的大部分（位移 + 挤压拉伸）VRMA 规范本身就管不了，必须你自己做。** 而剩下那部分（腿的 rotation）你不仅做了，还做得比一般录制动捕更贴合你的交互：

- 你的腿摆是**由 `dragSway` 弹簧状态驱动的连续函数**，而 VRMA 是**离散片段**；
- 你的摆幅**实时跟随鼠标速度**（`dragVel` 换算成 `lagAngle`），VRMA 做不到；
- 你的"脚背绷直"（`footL.rotation.x = dA * 0.34`）是"被提着"的强视觉提示，这是很内行的处理。

### 3.4 three-vrm-animation 支持运行时混合吗（API 层面）？

**精确回答：库本身不提供任何混合 API。混合能力 100% 来自 three.js 的 `AnimationMixer`。**

- `createVRMAnimationClip()` 的产物就是一个普通 `THREE.AnimationClip`，你拿它 `mixer.clipAction(clip)` 就行。
- 因此**混合手段就是 three.js 的通用手段**：
  - `action.crossFadeTo(other, duration)` — 淡入淡出切换（**这是你唯一真正需要的，用于彩蛋插播后回落**）
  - `action.fadeIn(d)` / `fadeOut(d)` / `setEffectiveWeight(w)`
  - `action.blendMode = AdditiveAnimationBlendMode` — 叠加
  - `new AnimationMixer(root)` 支持多个 action 同时 `play()`
- **没有骨骼遮罩**（§1.4）。要"上半身 VRMA + 下半身程序化"，只能在 `mixer.update(dt)` **之后**手动覆写下半身骨骼的 `quaternion`。这条路可行（因为你本来就在每帧手写这些骨骼），但它意味着**两套动画系统并存**，调参和排错成本翻倍。

**落地判断：技术可行 → 但为"拖拽反应"去做这件事是负收益。**

---

## 4. 若走程序化路线：成熟参考做法

### 4.1 你已经在用的（**且用得对**）

从 `web3d/pet_viewer.html` 读到的实现：

1. **多频 sine 叠加**（第 176–178 行附近）：
   ```js
   return Math.sin(t * f1 + ph) * 0.56
        + Math.sin(t * f2 + ph * 1.7) * 0.30
        + Math.sin(t * f3 + ph * 3.1) * 0.14;
   ```
   **权重 0.56 / 0.30 / 0.14 递减 + 频率错开 + 相位错开** —— 这是做"有机微动"的标准手法，避免单一 sine 的机械周期感。**这是行业成熟做法，无需替换。**

2. **二阶弹簧-阻尼系统**：自定义 `Spring` 类，带 stiffness / damping，方法 `to()` / `step(dt)` / `kick()` / `reset()`。拖拽用了四个：
   ```js
   const dragAmount = new Spring(0, 130, 0.80);  // 0→1「被拎起来」的程度，略回弹
   const dragSway   = new Spring(0, 22, 0.16);   // 摆动：软且欠阻尼 → 明显余摆
   const dragLift   = new Spring(0, 150, 0.55);  // 拿起/放下拉伸压缩
   const dragVel    = new Spring(0, 26, 1.0);    // 跟随时不振荡，只要平滑
   ```
   **"给不同物理量配不同弹簧常数"是专业做法**：`dragSway` 故意欠阻尼（22/0.16）产生明显余摆，`dragVel` 故意临界阻尼（ζ=1.0）避免抖动。这个设计是对的。

3. **Verlet 质点弹簧**做头发/裙摆物理（注释里写明"游戏行业标准做法，比 Unity 的 SpringBone 更稳"）。

### 4.2 可进一步参考的成熟做法

- **Perlin / Simplex 噪声**：1D 噪声驱动骨骼 rotation，比 sine 叠加更自然、**无周期感**（sine 叠多频仍可能露馅）。three.js **无内置噪声**，需自己实现或引入 `simplex-noise`（MIT）。
  **落地判断：✅ 值得试**，可替换 `idleMicro` 的 sine 叠加，收益是"更不重复"；但注意要保持**确定性可复现**，否则自动化测试（你的 `__dragState` 等诊断接口）会被噪声干扰。
- **three-vrm 自带 SpringBone runtime（`VRMC_springBone`）**：本机模型**确实有**，且是 39 条链 / **209 个关节**。
  ⚠️ **但本次解析发现关键事实：这些 spring 链全是 `qun_*`（裙）、头发、尾巴（`weiba3`）、披风（`cloak_*`），没有任何髋/腿/脚关节。**
  → **这就是为什么你的腿下垂必须靠程序化（或 VRMA）——模型物理帮不上腿。** 你的判断和实现是正确的。
  （注：`VRMC_springBone` 的链数组字段名是 **`springs`** 而不是 `springBones`，解析时容易踩坑。）
- **`three.js` 官方示例** `webgl_animation_skinning_blending` — 蒙皮 + 动作混合的标准示范。
- **Discover three.js《The three.js Animation System》** — <https://discoverthreejs.com/book/first-steps/animation-system/> — 把 mixer/action 讲得最清楚的中文友好资料（英文）。
- **three.js 论坛关于"自定义 mixer / 分层动画"的讨论** — <https://discourse.threejs.org/t/advice-should-i-build-a-custom-animation-mixer-or-chop-up-animation-clips/69120> — 印证了"three.js 没有原生骨骼遮罩，需要自己写"这一结论。
- **学术/工业界术语**：你要的效果业内叫 **procedural secondary motion / ragdoll-on-rails / spring-driven follow-through**。搜索这些词能找到比"VRMA"多得多的可用资料。

---

## 5. 版权红线

### 5.1 把 VRMA 塞进离线打包的桌宠（不联网、不发布）是否合规？

**✅ 合规。** 逐项分析：

1. **"不发布"是决定性的。** 本次核验的所有免费 VRMA 条款，其禁止项**都指向"再配布 / 再販売"**（把文件本身或改変版以可提取状态分发），**没有一条禁止"自己使用/播放"**。你把 .vrma 打包进自己的离线 app，在**自己机器上运行**，不把文件或打包产物给别人 → **不构成再配布**。
2. **各自的额外要求**：
   - R1 官方 7 件套：**商用都要署名**，你的个人自用无需署名。
   - R4（idle）：个人/商用皆自由，仅禁止"卖文件本身"和"冒名"。
   - R3（CC0）：无任何要求。
   - R2：禁"未改変的再配布"。
3. **⚠️ 唯一要小心的**：`VRMA_07` 之类如果哪天你**公开发布桌宠或演示视频**，就同时触发"再配布"与官方 7 件套的署名要求（需带 `Character animation credits to pixiv Inc.'s VRoid Project`）。**离线自用无此问题。**

### 5.2 Day1 模型 + 第三方 VRMA 组合，有哪些坑？

**核心原则：两个许可证必须同时满足，取交集。**

| 维度 | Day1 Studio（模型） | 第三方 VRMA（多数） | 交集 |
|---|---|---|---|
| 个人使用 | ✅ 允许 | ✅ 允许 | ✅ |
| 二次加工 | ✅ 允许 | ✅ 多数允许改変 | ✅ |
| 商用 | ❌ 禁止 | ⚠️ 多数允许（官方 7 件套允许，需署名） | ❌ **禁止** |
| 再分发 | ❌ 禁止 | ❌ 多数禁止 | ❌ **禁止** |

**你的交集 = 个人自用、非商用、不再分发。你正好在这个象限，两边都满足。**

具体的坑：

1. **✅ 好消息：许可不会互相污染。** VRMA 是**独立的 glTF 文件**，带自己的授权，**不会读取也不会继承 .vrm 里的 VRM 许可元数据**；反过来，把 VRMA 播在 Day1 模型上**也不会"污染"模型的许可**。两者是叠加关系，不是传递关系。
2. **⚠️ 最大的坑：打包分发会双重违规。** 如果哪天你把桌宠打包给朋友或发布 → **同时**触发 Day1 的"禁止再分发"**和**多数 VRMA 的"禁止再配布"。所以**离线打包自用 OK，一旦要分发就必须同时清掉模型和动作**。建议现在就给打包脚本加一道"发布模式剔除素材"的闸门。
3. **⚠️ 二次创作角色 + 第三方动作的灰色地带。** 米雪儿是《卡拉彼丘》（Day1 Studio）的角色。多数 VRMA 条款只约束"**文件本身的再配布**"，不约束"**播放场景**"，所以本地播放风险低。但**不要把"戴第三方动作的米雪儿"渲染成视频公开传播**——公开传播可能同时触及模型的"禁止再分发"，也容易招致原作者反感。**保守建议：公开视频也别发。**
4. **⚠️ 官方 7 件套的署名是硬要求（商用时）。** 若将来任何形式的公开使用（哪怕只是发一张 GIF），记得加 `Character animation credits to pixiv Inc.'s VRoid Project`。纯自用不需要。
5. **⚠️ 避开"舞蹈类"免费素材。** BOOTH 上大量 `TikTok_ダンスモーション` 是 0 JPY，但其动作常源自第三方编舞、搭配的音乐也有著作权，**权利链最脏**，且与桌宠需求无关。**不要碰。**
6. **⚠️ 不要碰**：标注「禁止改変」的、来源不明的、条款指向失效网盘的、从 VRoid Hub 别人模型上"扒"下来的动作。
7. **✅ VRM 生态的许可体系是成熟的。** 参考官方说明：<https://vroid.pixiv.help/hc/en-us/articles/360016417013> 与 VRM Public License 1.0 <https://vrm.dev/en/licenses/1.0/index.html>。VRM 把许可信息**嵌在模型文件里**，这是 VRM 的强项；但注意 **VRMA 目前没有等价的"嵌入式许可"机制**——VRMA 的条款靠**发布页面的文字**承载，**下载时务必存档页面截图/文本**，否则将来无法举证。

---

## 6. 最终建议

### 6.1 明确结论

> **拖拽反应动画：走「纯程序化动画」。不要用 VRMA 资源，也不要做 VRMA 程序混合。**

### 6.2 理由（按权重排序）

1. **需求已 100% 实现，且质量高于可下载素材。** `pet_viewer.html` 的拖拽系统已包含：绕髋主钟摆（左右相位差）、小腿回收、脚背绷直下垂、手臂滞后垂摆、腰身稳住、squash & stretch、松手彻底归位。**你问题 3 想要的效果，代码里已经存在。** 现在动它等于把已完成的工作推倒重做。
2. **没有现成素材能满足需求。** 官方 7 件套无 idle 无被提起；BOOTH 有 idle（R4）但是**站立**待机；"被提起/悬垂/摇晃"在整个 VRMA 生态查无此物。**"下载即用"这条路根本不通。**
3. **引入 VRMA 会降低可控性。** 拖拽是**参数化连续量**（四个 spring 的连续输出，实时跟随鼠标速度），VRMA 是**离散录制片段**。用片段响应连续交互 = 状态机地狱 + "拖到一半动画播完"的割裂感。
4. **规范层面就注定了要被"打补丁"。** VRMA 禁止 hips 以外平移、禁止 scale，所以"被提起"的核心位移必须你自己做——VRMA 只能覆盖矛盾的一小部分。
5. **技术债。** `AnimationMixer` 无骨骼遮罩，要做分层必须绕过 mixer 手工覆写骨骼 → 两套动画系统并存。
6. **版权最简。** 纯程序化 = 零第三方动作授权，与 Day1 的"个人自用"完全同象限。将来即使想公开分享，只需处理模型授权，不被动作授权牵制。
7. **物理帮不上腿，但这不是问题。** 模型的 39 条 springBone 链全是裙/发/尾/披风，**没有腿**——所以腿必须程序化。你已经这么做了，判断正确。

### 6.3 如果仍想引入 VRMA 作为补充（可选，不影响拖拽）

**推荐路线（低风险、可随时回退）**：

1. **只做"彩蛋插播"**，不做拖拽反应。保持程序化 idle 为**常驻底层**，VRMA 只在触发彩蛋时 `crossFadeTo` 淡入、播完淡出回落。
2. **先下载这两个**（授权最宽松、且覆盖 idle）：
   - R4 idle：<https://booth.pm/ja/items/8815790> （个人商用皆可，仅禁卖文件/冒名）
   - 官方 7 件套：<https://booth.pm/ja/items/5512385> （允许改変 + 商用，需署名；个人自用免署名）
   - 可选 R3 CC0 走跑：<https://booth.pm/ja/items/7861818> （CC0，最干净）
3. **接线方式**（你已具备全部前置条件）：
   - 本机已有 `three-vrm-animation.module.js`（3.5.5，导出 7 个符号），无需再装。
   - `web3d_server.py` **已注册** `.vrma → model/gltf-binary` MIME 类型，服务器端已就绪。
   - ⚠️ **但 `pet_viewer.html` 里目前没有任何 VRMA 接线**：`AnimationMixer` / `VRMAnimationLoaderPlugin` / `createVRMAnimationClip` / `clipAction` / `VRMAnimation` 出现次数**均为 0**。第 73 行只有一句 `let vrm = null, mixer = null;`（预留着但未使用）。**所以"已接入 three-vrm-animation 库"目前仅指"库文件已就位"，尚未接线。**
   - 需要新增：给 `GLTFLoader` 注册 `VRMAnimationLoaderPlugin` → 加载 .vrma → `createVRMAnimationClip(vrmAnimation, vrm)` → `mixer = new THREE.AnimationMixer(vrm.scene)` → 在现有 `animate()` 里加 `mixer.update(dt)`。
   - ⚠️ **注意执行顺序**：`mixer.update(dt)` 会覆写骨骼 rotation，必须放在现有程序化写骨骼**之前**（或对下半身骨骼在其后覆写），否则两者会互相打架。
4. **将来真要做"被提起"的 VRMA**：走自造路线，版权 100% 干净：
   - `Kirakun0328/text-to-vrma`（文本生成）
   - `nanasi-apps/vrm-animation-web-editor`（时间轴编辑器）
   - 设计要点：**"被提起"的竖直位移按规范不能写进 VRMA**，只能写腿/臂/躯干的 rotation；位移仍由你现有的 `dragOffsetY`（`GRAB_Y = 0.93` 髋部）负责。

### 6.4 一句话总结

**你的程序化拖拽动画已经是这个项目里最不需要 VRMA 的部分 —— 它比 VRMA 生态能提供的任何东西都更贴合你的交互。VRMA 应该被当作"偶尔的彩蛋"，而不是"拖拽反应的答案"。**

---

## 附录 A：本报告的核验方法

| 结论 | 核验方式 | 级别 |
|---|---|---|
| VRMA 规范内容（hips-only translation、禁 scale、T-pose、30fps、LookAt ZXY） | 直接抓取规范 README 原文 | **官方** |
| three-vrm-animation 3.5.5 版本、MIT 许可、7 个导出符号 | 读本机 bundle 头注释 + npm registry API | **一手实测** |
| `createVRMAnimationClip` 的 height 归一化与坐标变换 | 读 pixiv/three-vrm dev 分支源码 | **官方源码** |
| 无骨骼遮罩、仅 3 种 blendMode | 读本机 `three.module.js`（r170） | **一手实测** |
| BOOTH 各素材条款（R1–R5） | 逐个抓取 BOOTH 商品页正文 | **一手原文** |
| 模型 springBone = 39 链/209 关节、全为裙发尾披风、无腿 | 解析 `michelle_phys.vrm` 的 GLB JSON chunk | **一手实测** |
| `pet_viewer.html` 无任何 VRMA 接线、拖拽系统已完整实现 | 源码检索 + 上下文精读 | **一手实测** |
| `text-to-vrma` / `vrm-animation-web-editor` 的许可证 | ❌ **未能核实**（GitHub API 403 限流） | **需自查** |
| VRMA 在 QtWebEngine 中实际播放表现 | ❌ **未实测**（本次未下载运行） | **未验证** |

## 附录 B：本次调研中"官方"与"社区猜测"的分界

- **官方**：vrm.dev VRM Animation 页面、vrm-c/vrm-specification 规范正文、pixiv/three-vrm 仓库与 API 文档、vroid.com 官方新闻、VRoid Project 的 BOOTH 商品页条款、VRM Public License 1.0。
- **社区/推断**：`specVersion` 兼容集合 `{'1.0','1.0-draft'}` 的具体行为差异（源码推断）；"VRMA 生态没有'被提起'动作"（基于多轮检索的**否定性结论**，无法证明绝对不存在，但覆盖了 BOOTH 全分类 282 件 + 多语言关键词）；三个开源工具仓库的许可证（未核实）；三条 three.js 混合实现路线（`AdditiveAnimationBlendMode` / 手工覆写 / 自定义 mixer）的取舍建议（基于源码能力推断，未实测）。
