# VRM springBone 调参报告（米雪儿 · michelle_phys.vrm · three-vrm 3.5.5）

> 实测基线：直接解析 `web3d/models/michelle_phys.vrm` 的 GLB JSON。
> 39 spring / 209 joint / 19 collider（18 capsule + 1 sphere，半径 0.014–0.114 m）/ 315 bones / 1 skin / 318 nodes。
> **209 个 joint 的参数完全一致：stiffness=1.0、gravityPower=0、gravityDir=[0,-1,0]、dragForce=0.5、hitRadius=0；39 条 spring 的 center 全部为空。**
> 这就是 MMD 刚体转 VRM 的默认落值，从来没有被调过。

---

## 0. 结论先行

### 0.1 五个真实病根（按收益排序）

| # | 病根 | 实测值 | 后果 |
|---|---|---|---|
| 1 | `hitRadius = 0` | 209/209 为 0 | joint 侧半径为 0，碰撞退化成"点 vs 面"，头发裙摆直接穿模 |
| 2 | `gravityPower = 0` 且无任何等价外力 | 209/209 为 0 | 没有垂坠感，只有惯性，静止时像被"定格" |
| 3 | `stiffness = 1.0` 在 120fps 下与 dt 耦合 | 等效固有频率 ω≈59.4 rad/s | 周期仅 0.106 s ≈ 9.4 Hz，硬到像钢丝 |
| 4 | `dragForce = 0.5` 在 120fps 下 | 速度时间常数 τ≈12 ms | 阻尼过头，**系统处于过阻尼**，永远不产生余摆 |
| 5 | `center` 全为空 | 39/39 未设 | 整体拖拽位移被当成世界运动，甩动不可控（这一条对拖拽场景其实是**优点**，见 §4.4） |

### 0.2 最关键的一条：当前头发是"过阻尼"，不是"太硬"那么简单

用 `ζ = γ/ω` 判据（γ = −ln(1−dragForce)·fps 为速度衰减率）：

```
120 fps, B_median = 0.034 m
ω = sqrt( stiffness / (B · dt) )          # 由 three-vrm 参考实现推出的等效固有角频率
γ = -ln(1 - dragForce) · fps
ζ = γ / ω
```

| 部位 | 现状 ω | 现状 γ | 现状 ζ | 判定 |
|---|---|---|---|---|
| 头发（stiffness 1.0 / drag 0.5） | 59.4 rad/s | 83.2 s⁻¹ | **1.40** | **过阻尼**，一次回弹都没有，甩不动 |
| 头发（目标 0.05 / 0.02） | 13.3 rad/s | 2.42 s⁻¹ | **0.18** | 欠阻尼，1–2 次可见余摆 |

**这就解释了"快速拖动头发最大甩到 36.6° 但看起来很硬"**：角度是够的（9.4 Hz 高频抖动也能甩到 36°），但 ζ=1.4 意味着没有任何过冲和回摆，视觉上就是"一根硬发条被推了一下然后立刻停住"。

调参的本质不是"把 stiffness 调小"，而是 **把 (ω, ζ) 从 (59, 1.4) 搬到 (13, 0.18)**。

### 0.3 一组推荐值（原生 springBone 版，120 fps）

| 参数 | 头发 | 裙摆/披风 | 马尾/丝带 | 说明 |
|---|---|---|---|---|
| `stiffness` | **0.05–0.10** | **0.03–0.06** | **0.04–0.08** | 120fps 下 ω≈13.3–18.8 / 9.4–13.3 / 11.6–16.8 |
| `dragForce` | **0.016–0.030** | **0.020–0.040** | **0.014–0.028** | 目标 ζ = 0.15–0.30 |
| `gravityPower` | **0.06–0.12** | **0.08–0.14** | **0.05–0.10** | 1g 在 120fps 下 = 9.8·dt = **0.0817** |
| `gravityDir` | [0,−1,0] | [0,−1,0] | [0,−1,0] | 保持 |
| `hitRadius` | **0.010–0.015** | **0.015–0.025** | **0.008–0.012** | 按 §0.4 的几何判据取值 |

**60 fps 换算**：`stiffness ×2`、`dragForce ≈ ×2`（精确：`d₆₀ = 1−(1−d₁₂₀)²`）、`gravityPower ×2`。

### 0.4 hitRadius 怎么定：用碰撞体几何算，不要拍脑袋

模型 19 个 collider 半径 **0.0143 – 0.114 m**，几何中位数约 0.07 m。社区经验判据（[Tcam 笔记](https://note.com/tcam727/n/n312bcd42d4e2)）：

> 「当たり判定となる黄色い球同士の縁がくっつくまで大きくする」（把 joint 侧球和 collider 侧球的边缘加大到刚好相碰）
> 「直立状態で再生してテストしたときに、ほんのちょっとだけスカートが膨らむ程度まで」（直立播放时，裙子只鼓起来一点点为止）

即 `hitRadius ≈ 0.15–0.25 × 相邻 collider 半径`。
本模型骨骼段长中位数 **0.034 m**（p25 = 0.021，p75 = 0.044，max = 0.111），所以：
- 头发 hitRadius = **0.010**（小腿部 0.026–0.061 的头/颈 collider 的 ~20%）
- 裙摆 hitRadius = **0.020**（对下半身 0.104 的大 capsule 的 ~20%，且不超过段长的 60%，避免关节互相顶飞）

**不要超过相邻骨骼段长的一半**，否则相邻 joint 的碰撞球会互相穿插，链会自己把自己顶出去 —— 社区称之为「スプリングボーンが破綻する（弹簧骨崩坏）」。

---

## 1. VRMC_springBone 1.0 官方语义

**规范链接**：[vrm-c/vrm-specification · VRMC_springBone-1.0/README.md](https://github.com/vrm-c/vrm-specification/blob/master/specification/VRMC_springBone-1.0/README.md)（Version 1.0，Status: Complete）

### 1.1 逐参数原文语义

| 参数 | 规范原文 | 类型/约束 | 工程含义 |
|---|---|---|---|
| `node` | "index of the target node" | integer | 目标 glTF 节点 |
| `hitRadius` | "SpringBone hitbox size" | float (meter) | **joint 侧碰撞球半径，单位米** |
| `stiffness` | "Rigidity (force to return to the initial state)" | **0 或以上** | 回归静止姿态的刚性力 |
| `gravityPower` | "Gravity force (force applied to Spring Bone every frame)" | 无约束 | 重力强度 |
| `gravityDir` | "Gravity direction" | `[x,y,z]` | 重力方向 |
| `dragForce` | "Deceleration (force to decelerate Spring Bone)" | **[0-1]** | 减速（阻尼） |

`springs[*].joints[*]` 完整示例（规范原文）：

```json
{
  "node": 0,
  "hitRadius": 0.1,
  "stiffness": 0.5,
  "gravityPower": 1.0,
  "gravityDir": [0, -1, 0],
  "dragForce": 0.5
}
```

### 1.2 规范**没有**给推荐取值范围 —— 这是重要事实

规范只给了类型和 `stiffness ≥ 0`、`dragForce ∈ [0,1]` 两个边界，**没有任何默认值或推荐区间**。
默认值来自 UniVRM 的组件序列化字段（社区事实标准）：

```csharp
// UniVRM Assets/VRM/Runtime/SpringBone/VRMSpringBone.cs（v0.x，VRM1 沿用同样数值）
[SerializeField] public float m_stiffnessForce = 1.0f;
[SerializeField] [Range(0, 2)] public float m_gravityPower;          // 默认 0，滑条上限 2
[SerializeField] public Vector3 m_gravityDir = new Vector3(0, -1.0f, 0);
[SerializeField] [Range(0, 1)] public float m_dragForce = 0.4f;      // 默认 0.4
[SerializeField] public float m_hitRadius = 0.02f;                   // 默认 0.02
```

> 来源：[UniVRM VRMSpringBone.cs](https://github.com/vrm-c/UniVRM/blob/v0.78.0/Assets/VRM/Runtime/SpringBone/VRMSpringBone.cs)、[DeepWiki · UniVRM SpringBone Overview](https://deepwiki.com/vrm-c/UniVRM/5.1-springbone-overview-and-configuration)（Joint 默认值：Stiffness 1.0 / Gravity 0.0 / Dir (0,−1,0) / Drag 0.4 / Radius 0.02）

**注意**：`[Range(0,2)]` 只是 Unity Inspector 的滑条范围，**不是物理上限**，规范允许任意大的 gravityPower。`[Range(0,1)]` 对 dragForce 才是硬约束。

### 1.3 规范的参考算法（非规范性章节，但决定了所有实现的数值行为）

规范原文伪代码：

```ts
var inertia    = (currentTail - prevTail) * (1.0f - dragForce);
var stiffness  = deltaTime * parentWorldRotation * initialLocalRotation * boneAxis * stiffnessForce;
var external   = deltaTime * gravityDir * gravityPower;
var nextTail   = currentTail + inertia + stiffness + external;
nextTail = worldPosition + (nextTail - worldPosition).normalized * boneLength;   // 长度约束
```

**四个必须记住的结论：**

1. **`stiffness` 和 `gravityPower` 都乘 `deltaTime`，`dragForce` 不乘。**
   → `stiffness`/`gravityPower` 的物理量纲是**速度**（m/s），不是加速度。
   → `dragForce` 是**每帧**速度保留率 `(1−dragForce)`，因此**强依赖帧率**。
2. **规范里没有出现 `deltaTime` 的定义** —— 它由各实现自己决定（Unity 用 `Time.deltaTime`，three-vrm 用 `vrm.update(delta)` 传入的 `delta`）。这直接造就了 §2.3 的 120fps 陷阱。
3. **末端 joint 不参与物理**："The SpringJoint at the end is only used as a Tail, so no SpringJoint parameters are used."
   → 本模型 39 条 spring 共 209 joint，**实际生效的只有 170 个**（209 − 39）。
4. **`center` 的作用空间**：不设时用 world space；设了之后 inertia 在 center 空间求值，但**外力（重力）仍在 world space 计算**。规范原文："Center is effective... mainly when SpringBone is shaking too intense"，典型场景是「走路/跑步时抖太厉害」和「只想让头部动作带动头发」。

### 1.4 链拓扑约束（决定 chain 怎么切）

- `joints[n]` 必须是 `joints[n+1]` 的父节点或祖先节点（允许跳级，中间的节点被忽略）。
- **同一 joint 不允许出现在多条 SpringChain 里**（prohibited）。
- 分流（branching）是 **undefined**，实现可以任意决定执行顺序：「The execution order between `a-b-c-d` and `x-y-z` is undefined」。

> 相关背景：`VRMC_springBone_extended_collider` 1.0 额外引入了 **plane collider** 和 **inside 型 collider**（sphereInside/capsuleInside），规范核心 1.0 里**没有**这两种。本地 three-vrm 3.5.5 已支持加载（见 §2.2）。
> 参考：[VRMC_springBone_extended_collider 文档](https://vrm.dev/vrm1/springbone/)、[three-vrm PR #1539 讨论中提到的 inside/plane collider](https://github.com/pixiv/three-vrm/discussions/1464)

---

## 2. three-vrm 3.x 的参数映射与运行时改参

### 2.1 参数映射（一一对应，无变换）

three-vrm 的 joint settings 就是规范字段的直译（本地 `web3d/vendor/three-vrm.module.js` 实测）：

```js
this.settings = {
  hitRadius:    settings.hitRadius    ?? 0,               // 注意默认 0，不是 0.02
  stiffness:    settings.stiffness    ?? 1,
  gravityPower: settings.gravityPower ?? 0,
  gravityDir:   settings.gravityDir?.clone() ?? new THREE.Vector3(0, -1, 0),
  dragForce:    settings.dragForce    ?? 0.4,
};
```

> 源码：[VRMSpringBoneJoint.ts](https://github.com/pixiv/three-vrm/blob/dev/packages/three-vrm-springbone/src/VRMSpringBoneJoint.ts#L170-L176)
> 注意 three-vrm 的 `hitRadius` 兜底默认是 **0**（UniVRM 是 0.02），所以 VRM1 文件里没写 hitRadius 就真的是 0。

核心更新循环（原文）：

```ts
_nextTail
  .copy(this._currentTail)
  .add(_v3A.subVectors(this._currentTail, this._prevTail).multiplyScalar(1 - this.settings.dragForce)) // inertia
  .applyMatrix4(this._getMatrixCenterToWorld())                     // center 空间 → world
  .addScaledVector(worldSpaceBoneAxis, this.settings.stiffness * delta)   // stiffness × dt
  .addScaledVector(this.settings.gravityDir, this.settings.gravityPower * delta); // gravity × dt
_nextTail.sub(_worldSpacePosition).normalize().multiplyScalar(this._worldSpaceBoneLength).add(_worldSpacePosition);
```

**关键**：`parentWorldRotation · initialLocalRotation · boneAxis` 被合并成 `worldSpaceBoneAxis`（PR #1539 的 world-space 优化），`delta` 以标量形式出现 —— 这证实 §2.3 的 dt 耦合。

### 2.2 Manager API 速查

| 成员 | 类型 | 用途 |
|---|---|---|
| `vrm.springBoneManager.joints` | `Set<VRMSpringBoneJoint>` | 全部 joint；**遍历这个就能改参** |
| `vrm.springBoneManager.springBones` | 同上 | **已废弃**，会打 warn |
| `.colliderGroups` / `.colliders` | 数组 | 碰撞体 |
| `.update(delta)` | — | 每帧更新（`vrm.update(dt)` 内部会调用） |
| `.reset()` | — | 把骨骼复位到 rest 旋转，并把 `currentTail/prevTail` 重置到初始位置 |
| `.setInitState()` | — | 重新抓取当前姿态为 rest 基准（**改完骨骼静止姿态后必须调**） |
| `joint.settings` | 普通对象 | **可直接读写，改完立刻生效** |
| `joint.bone` / `joint.child` | Object3D | 骨骼与尾节点 |
| `joint.colliderGroups` | 数组 | 可运行时增删 |

真正生效所需的前提：`joint.bone.matrixAutoUpdate = false`（构造函数里已设），Manager 自己算 `matrixWorld`。所以**不要在外部手动改 joint 骨骼的 quaternion**，会被覆盖。

新增/删除 joint 用 `addJoint()` / `deleteJoint()`，会置 `_isSortedJointsDirty`，下次 update 自动重排。

### 2.3 ⚠️ 120 fps 陷阱（本项目直接踩到）

因为 `stiffness` 乘 `delta`、`dragForce` 是每帧系数，**同一组参数在不同帧率下行为完全不同**：

| 参数 | 60 fps 值 | 120 fps 等效值 | 换算公式 |
|---|---|---|---|
| `stiffness` | s | **2s** | 线性 ∝ fps |
| `gravityPower` | g | **2g** | 线性 ∝ fps |
| `dragForce` | d | **1−(1−d)²** | 每帧保留率的幂 |

数值对照（dragForce）：

| dragForce | 60fps 速度 τ | 120fps 速度 τ |
|---|---|---|
| 0.5 | 24 ms | **12 ms** |
| 0.2 | 75 ms | 37 ms |
| 0.1 | 158 ms | 79 ms |
| 0.05 | 325 ms | 162 ms |
| 0.02 | 825 ms | 412 ms |
| 0.01 | 1.65 s | 828 ms |

**换算表**：要让 120fps 下的行为等价于 60fps 下的经典配置，`dragForce` 要按此调整：

| 想复刻 60fps 的 | 120fps 用 |
|---|---|
| 0.5 | 0.293 |
| 0.4（UniVRM 默认） | 0.215 |
| 0.2 | 0.101 |
| 0.1 | 0.048 |

`stiffness` 同理 **÷2**：60fps 的 0.5 → 120fps 的 0.25。

> 另一个佐证：three-vrm 社区 skill 明确把「Incorrect Delta Time」列为 springBone 异常的首要原因（90%）—— 通常表现为「头发向上飞 / 水平支棱 / 像有隐形墙」。参考 [vrm-springbone-physics skill](https://lobehub.com/skills/project-n-e-k-o-n.e.k.o-vrm-physics)。

### 2.4 ⚠️ 拖拽时改 `scale` 的额外风险

`_worldSpaceBoneLength` 每帧由 `bone.matrixWorld` 与 `child.matrixWorld` 实算，本身能跟上缩放。但 UniVRM 有明确 issue：**改模型 scale（如 (8,8,8)）会导致 springBone 行为不正确**。

> 来源：[UniVRM issue #2242 "SpringBone does not work correctly if you change the model size, for example scale (8,8,8)"](https://github.com/vrm-c/UniVRM/issues/2242)

本项目的拖拽实现里有 `scale.y` 拉伸。**建议**：拉伸期间按 `1/scaleY` 反向补偿 `gravityPower`，或把拉伸量限制在 ≤1.15×。非均匀缩放会让骨骼段长在 Y 方向被拉长，而 `stiffness` 的力是沿 `boneAxis` 的世界方向、大小固定 —— 结果就是「越拉越长、越拉越硬」。

### 2.5 运行时动态改参：**支持**，但不是"官方 API"，而是直接改字段

**官方立场**：three-vrm 维护者 **0b5vr** 在 [discussion #1464](https://github.com/pixiv/three-vrm/discussions/1464) 中明确回应：

> 提问："Do you think it makes sense to 'animate' the springbone strengths at run time (so when playing a 'sitting' animation clip, I also animate the spring bone strengths? E.g. increase gravity or reduce stiffness?"
> 0b5vr（Maintainer）："**I'm not sure the SpringBone system in three-vrm supports that with ease but that might be a viable approach yes.**"

**结论**：没有官方的"动画轨道绑定"机制，但 `joint.settings.*` 是**普通可写字段**，直接赋值下一帧即生效，这是可行且被维护者认可的路线。

#### 生效代码（本项目可直接用）

```js
// 1) 收集：按名字把 joint 分到 头发 / 裙摆 / 其他
function classifyJoints(vrm) {
  const HOOD = /^(hair_ribbon|ponytail_hair|hair_rr|hair_up|earring|weiba)/;
  const SKIRT = /^qun_/;
  const RIBBON = /^(cloak|part_|cloth_)/;
  const out = { hair: [], skirt: [], other: [] };
  for (const j of vrm.springBoneManager.joints) {
    const n = j.bone.name || '';
    (HOOD.test(n) ? out.hair : SKIRT.test(n) ? out.skirt : out.other).push(j);
  }
  return out;
}

// 2) 记住出厂值，才能"松手恢复"
const BASE = new Map();
function snapshot(group) {
  for (const j of group) {
    if (!BASE.has(j)) BASE.set(j, { ...j.settings, gravityDir: j.settings.gravityDir.clone() });
  }
}
function restore(group) { for (const j of group) Object.assign(j.settings, BASE.get(j)); }

// 3) 平滑过渡（必须！见下）
const ease = { s: 1.0 };                       // 每次改参前先 kick
function applyGroup(group, target, blend) {
  for (const j of group) {
    const b = BASE.get(j);
    j.settings.stiffness    = b.stiffness    + (target.stiffness    - b.stiffness)    * blend;
    j.settings.dragForce    = b.dragForce    + (target.dragForce    - b.dragForce)    * blend;
    j.settings.gravityPower = b.gravityPower + (target.gravityPower - b.gravityPower) * blend;
  }
}
```

#### 为什么必须过渡（这是最容易翻车的地方）

Verlet 的隐式速度是 `(currentTail − prevTail)`。把 `dragForce` 从 0.5 直接跳到 0.02：

```
改之前：v_implicit = (cur − prev) × 0.5     → 速度被砍一半
改之后：v_implicit = (cur − prev) × 0.98    → 速度几乎全保留
```

**同一帧内隐式速度瞬间翻 2 倍 → 头发会"炸"一下**。同理，`stiffness` 突降会让上一帧积累的偏移不再被拉住。

**规格**：
- 过渡时长 **0.15–0.30 s**（`blend = 1 − exp(−t/0.12)` 或线性），实测在 120fps 下 18–36 帧。
- 过渡曲线用 `smoothstep` 或指数趋近，**不要**用线性硬切。
- **禁止**在过渡中途反向再切（会产生速度阶跃叠加）。要做就先把当前 blend 记下来当起点。

#### 拖拽期间"临时调软"的正确做法：不要改 stiffness，改 dragForce

这是本报告最重要的工程建议。

**不要**为了"跟手"去调 `stiffness`：`stiffness` 决定的是固有频率，改它等于改头发本身的材质（从钢丝变面条），物理上不合理，且恢复时会有明显的"变脸"。

**应该**调 `dragForce` 的**等价物**：拖拽的本质是给整个模型一个世界位移/速度。three-vrm 里 `dragForce` 低 = 速度保留久 = 跟手甩。所以：

```
静止态：dragForce = 0.03   （ζ≈0.25，自然收敛）
拖拽态：dragForce = 0.010  （ζ≈0.08，甩得开、余摆明显）
```

**更稳的做法（推荐，零跳变风险）**：不动 `settings`，而是模仿项目已有的 `HairPhysics.kick()` 思路，**直接给 joint 注入等效速度冲量**：

在 three-vrm 里等价于把 `_prevTail` 往反方向推 —— 但 `_prevTail` 是 `private`，外部拿不到。所以替代方案是**在拖拽开始时调用一次 `manager.reset()` 前先把模型位移"喂"进去**，或者干脆用上面的 `dragForce` 混合方案。

> 实操结论：**用 dragForce 混合（0.03 ↔ 0.01），过渡 0.2 s。** 简单、可逆、无阶跃。

#### center 的动态切换（如果需要）

`center` 的 setter 会自己安装/卸载 `Matrix4InverseCache`，所以可以先设再调 `reset()`：

```js
for (const j of group) j.center = null;    // 或 = hipsBone
vrm.springBoneManager.reset();             // 必须：重建 tail 状态
```

**但拖拽场景不建议动 center** —— 理由见 §4.4。

---

## 3. 社区经验区间

### 3.1 语义口诀（[Tcam《[VRM0.x]SpringBoneの個人的Tips》](https://note.com/tcam727/n/n312bcd42d4e2)，2023-11-23）

> 「**Stiffness ＝ 摇动的范围；Drag ＝ 摇动的时间。**」
> 「先调 Drag，让摇动时间对上感觉；再调 Stiffness 决定摇动范围。」
> 「实际上双方互相影响。比如 Stiffness 在 4 附近时，Drag 要提到 1.0 附近才勉强能摇起来；反过来 Stiffness 接近 0 时，Drag 很小也足够摇。」

**翻译成本项目的语言**：
- `stiffness` 大 → 恢复力强 → 偏移小 → "摇动范围小"（因为力大到偏移被瞬时报掉）
- `dragForce` 大 → 速度衰减快 → "摇动时间短"
- **耦合陷阱**：这就是为什么在本项目里单改 `stiffness` 从 1.0 降到 0.2 会感觉"没变化很多"——因为同时 `dragForce=0.5` 还在猛踩刹车。**要先把 dragForce 降下来，stiffness 的效果才出得来。**

### 3.2 Gravity 从 0 开始

> 「Gravity 也就是重力很难处理，**一开始就设 0，先把其它调完再回来加**。」
> 「因为一旦施加重力，所有东西必然向中央下方收敛，变得很不起眼，尤其是横向展开的发型最明显。」
> 「但如果能调好，效果确实很出色。要在回弹力 Stiffness 和重力之间取得平衡。」

**对米雪儿的影响**：双马尾 + 长裙是"横向展开"的典型。**建议 gravityPower 从 0.04 起步（半重力），不要直接上 0.08。**
用**半重力**检查视觉：如果裙子在静止时明显往中线下垂、失去 A 字轮廓，说明太大 → 降到 0.03。

### 3.3 VRChat PhysBone 的等价参数（[官方文档](https://creators.vrchat.com/common-components/physbones)）

VRChat 的 PhysBone 是 springBone 的近亲，参数语义映射：

| VRM | VRChat PhysBone | 官方说明 |
|---|---|---|
| `stiffness` | **Pull** | "A positive Pull is required for bones to move in the direction of gravity" |
| `dragForce` | （Spring / Damping） | "The amount bones will wobble when trying to reach their rest position" |
| `gravityPower` + `gravityDir` | **Gravity** | "Positive value pulls bones down, negative pulls upwards" |
| `hitRadius` | **Radius** | "Collision radius around each bone in meters" |

**官方给的可用区间（VRChat 文档原文）**：

> **Pull（≈ stiffness）**：社区实测"最影响观感的参数"，[Reddit r/VRchat 经验帖](https://www.reddit.com/r/VRchat/comments/uji2v2/any_phys_bones_value_tips) 建议 **保持低于 0.2**，除非你想要某样东西明显"挺立"。
> **Gravity Falloff**：文档建议 **0.5–0.8**（"only have a fraction of gravity at rest pose"），或**已经建模成理想垂坠姿态时用 1.0**。
> **Grab Movement**：0 = 被抓的骨骼用 pull & spring 慢慢追；**1 = 立刻跟到手上**。

**这条对本项目拖拽场景极其关键**：
> VRChat 的 `Grab Movement = 0` 就是"**跟手但不生硬**"的标准答案 —— 被抓对象用弹簧追手，而不是硬绑定。你们现在的实现是"整体被提起"（position.y 直接跟随），属于 `Grab Movement ≈ 1`，所以身体跟手但辅助物跟不上，视觉上割裂。

推荐：**身体本身用 Grab Movement ≈ 0.6–0.8（快速跟随但有一点缓动，项目现有的 `dragVel = new Spring(0, 26, 1.0)` 已经很接近），头发裙摆用 Grab Movement ≈ 0.1–0.3（明显滞后）。**

### 3.4 DynamicBone 经典配置表（Unity 时代事实标准）

[SrPhilippe 的 VRChat DynamicBone 配置 gist](https://gist.github.com/SrPhilippe/43c1bad021fab173d3ef1d5255d53f53) 与 [Z-ANESaber/DynamicBones-Configs](https://github.com/Z-ANESaber/DynamicBones-Configs)：

| Title | Update Rate | Damping | Elasticity | Stiffness | Inert |
|---|---|---|---|---|---|
| Short Hair | 30 | 0.142 | 0.888 | **0.1** | 0 |
| Long Hair | 30 | 0.933 | 0.591 | **0.4** | 0 |
| Realistic Breasts | 50 | 0.231 | 0.618 | **0.159** | 0 |
| Bouncy Breasts | 90 | 0.656 | 0.285 | **0.056** | 0.281 |
| Cloth | 60 | 0.587 | 0.457 | **0.1** | 0 |
| Short Cloth | 60 | 0.649 | 0.471 | **0.131** | 0 |

（DynamicBone 的 `Stiffness` 与 `Damping` 与 VRM 的 `stiffness`/`dragForce` **不是同一坐标系**，但量级参考很有价值：**长发 0.4、短发 0.1、布料 0.1** —— 注意这些是在 30–60 fps 下的值。）

> ⚠️ DynamicBone 作者已声明其在 VRChat 中已过时，仅作历史量级参考。

### 3.5 什么叫「太硬像钢丝」/「太软像面条」

用 (ω, ζ) 判据（本报告 §0.2 提出，可直接量化）：

| 观感 | ω (rad/s) | 周期 | ζ | 症状 |
|---|---|---|---|---|
| **钢丝 / 发条** | > 40 | < 0.16 s | **> 1.0（过阻尼）** | 甩一下立刻定住，无过冲，看不出摆动；高频抖动 |
| 硬但有摆 | 25–40 | 0.16–0.25 s | 0.3–0.6 | 动作干脆但仍有"塑料感" |
| **推荐：跟手自然** | **10–18** | **0.35–0.63 s** | **0.15–0.35** | 滞后 0.1–0.2 s，1–2 次可见回摆 |
| 软 | 6–10 | 0.63–1.05 s | 0.1–0.2 | 甩得远、回得慢，长发可接受 |
| **面条** | < 5 | > 1.26 s | < 0.08（欠阻尼严重） | 永远在晃，恢复不到静止；重心位移时穿模 |
| 果冻/发散 | 任意 | — | **< 0（数值不稳定）** | 振幅随时间增长，最终数值爆炸 |

**关键判据是 ζ，不是 ω**：`ζ > 1` 出钢丝，`ζ < 0.1` 出面条。当前模型 ζ = 1.40 → **钢丝**。

**数值稳定性红线**（Verlet + 显式弹簧）：

```
稳定性条件： ω · dt < 2      （临界：ω·dt = 2）
```

本模型 120fps（dt = 1/120）下，`ω·dt = sqrt(stiffness / B) · sqrt(dt)`：

| stiffness | ω·dt | 判定 |
|---|---|---|
| 1.0（现状） | 0.495 | 稳，但太硬 |
| 0.2 | 0.222 | 稳 |
| **0.05** | **0.111** | 稳，推荐 |
| 0.01 | 0.0495 | 稳 |
| ≥ 16 | ≥ 1.98 | **临界，会炸** |

→ **120fps 下 stiffness 的数值安全上限约 16**，离你现在的 1.0 有很大的操作空间。（这也是为什么之前自研 HairPhysics 用 k=400 会"头发乱飞"——单位是 1/s² 的加速度刚度，和这里的 stiffness 不是一个量纲。）

### 3.6 裙摆破绽的社区处置清单（[Tcam](https://note.com/tcam727/n/n312bcd42d4e2) 原文 7 条）

按推荐顺序：
1. **加大裙子的 hitRadius**（最基本；判据见 §0.4）
2. **提高 stiffness 变硬，同时提高 dragForce 让它还能摇** ← 与本报告"hair 要软"相反，**裙子要偏硬**
3. 改裙摆根骨骼的 scale 整体放大
4. 移动裙摆根骨骼整体抬高
5. 腿部 collider 由上往下逐渐加大（裙子是圆锥形，越往下横向间距越大）
6. 朝身体中心方向再加一排 collider，做成"板状"（对正面破绽有效）
7. 把 springBone 拆成"前/后"多组，各自配大型 collider

第 6 条的原文警告值得记下：
> 「如果横向铺得太开，腿往外张的时候会把多余的裙子顶出去，所以我一般把 collider 的横向范围限制在**身体中心到对侧大腿一半**为止。」

**对米雪儿的建议**：现状是 39 条 spring **每条只挂 1 个 collider group**（全部 `colliders.length == 1`），也就是完全没有分层路由。裙摆 qun_0_0 ~ qun_0_19 这 20 条链全部只对同一个 collider group 生效。这是"裙子插腿"的结构性原因 —— **光调参数解决不了**，需要把 collider group 按「腰/左腿/右腿/中央」拆开，再给裙摆链分别路由。

### 3.7 collider 形状的经验

本模型 **18 个 capsule + 1 个 sphere**，但 VRM1 的核心规范里 capsule 的 `radius` 是**半圆和圆柱共用的半径**：
> "shape.capsule.radius: Only if the shape is a capsule: the radius of the semicircle and cylinder of the capsule"

所以 capsule 的**有效碰撞半径 = radius + joint 的 hitRadius**（three-vrm 的 `calculateCollision(colliderMatrix, tail, hitRadius, out)` 正是这么算的）。当前 hitRadius = 0 → 有效半径就是 collider 半径本身，碰撞"贴着皮"发生。

---

## 4. 拖拽场景下的头发裙摆：物理模型与实现要点

### 4.1 应该怎么反应才自然：三阶段时序

一次"抓住腰部 → 快速拖动 → 松手"的完整过程，头发的正确反应是：

| 阶段 | 时长 | 期望表现 | 物理来源 |
|---|---|---|---|
| **起手加速** | 0–0.15 s | 头发**反向**甩开（身体向前，头发向后滞后） | 惯性项 `(cur−prev)·(1−drag)` 落后于 body 位移 |
| **匀速拖动** | 持续 | 头发稳定**拖在后面**一个固定偏角（≈15–30°），不再继续分开 | 惯性项归零，`stiffness·axis·dt` 与"锚点已移走"平衡 |
| **松手/急停** | 0–0.6 s | 头发**向前过冲**（overshoot），越过静止位 20–40%，然后 1–2 次递减回摆收敛 | 欠阻尼振荡，ζ=0.15–0.35 |

**判据**：如果起手时头发是**同向**甩的（身体向前、头发也向前），说明采样/惯性符号错了；如果松手后**没有过冲**（角度单调收敛到 0），说明 **ζ ≥ 1，过阻尼** —— 这正是你们现在的 36.6° 现象。

### 4.2 关键：惯性来自"锚点位移"，不是来自"加速度"

规范算法里没有任何显式的"加速度"输入。惯性完全来自：

```ts
inertia = (currentTail - prevTail) * (1 - dragForce)
```

而 `currentTail` 是**世界空间**（center=null 时）的尾节点位置。所以：

- 父骨骼（body）移动 → `worldSpacePosition` 变了 → 但 `currentTail` 还停在旧位置
- 下一帧的 `nextTail = currentTail + inertia + ...`，最后被 `normalize().multiplyScalar(boneLength).add(worldSpacePosition)` **硬拉回以新 anchor 为球心的球面上**
- 结果：tail 相对 anchor 的角度 = 上一帧的世界朝向差 → **这就是"滞后角"**

**推论**：`dragForce` 越低，`inertia` 越大，tail 越"不愿意"跟上 anchor，滞后角越大。而 `stiffness` 越大，回正力把角度压回去越快。

**所以"跟手甩动"= 低 dragForce + 中低 stiffness**，两者缺一不可：
- 只降 stiffness 不降 dragForce：drag 猛踩刹车，offset 回正快，仍不生硬不起来 → **你们现在的情况**
- 只降 dragForce 不降 stiffness：offset 累积但恢复力过强，表现为"高频抖动"而非"平滑摆动"

### 4.3 自写 HairPhysics 的关键点（如果原生不够用）

> **重要前提**：项目 `pet_viewer.html` 里那段注释（第 1220–1229 行）「本模型（PMX 转 VRM）**没有** VRMC_springBone 扩展，three-vrm 的 springBoneManager 是 null」**已经过时**。实测模型**有** `VRMC_springBone`（specVersion 1.0，39 spring / 209 joint / 19 collider），且代码第 437 行已经优先走 native 分支并把 `hairPhysics = null`。也就是说 **`HairPhysics` 类目前是死代码**。下面的内容供"原生不够用"时参考。

自研 Verlet 的六个关键点：

**(1) 时间步长：固定步长 + 累加器，不要用可变 dt**

现状 `const h = Math.min(dt, 1/60)` 是**可变步长**，抖动的 dt 会直接变成不稳定的能量注入。

```js
// 推荐：固定步长 + 累加器 + 最大子步数
const FIXED = 1 / 120;            // 与渲染帧率一致或更细
acc += Math.min(dt, 0.1);         // 夹住大 dt（窗口拖动/最小化恢复）
let steps = 0;
while (acc >= FIXED && steps < 4) { step(FIXED); acc -= FIXED; steps++; }
if (steps === 4) acc = 0;         // 追不上就丢弃，避免死亡螺旋
```

> 依据：[Gaffer On Games · Fix Your Timestep!](https://gafferongames.com/post/fix_your_timestep/)（累加器 + 固定 dt 是实时物理的标准做法；可变 dt 会让显式积分器的行为随帧率漂移）

**(2) 阻尼：用连续形式，不要用每帧常数**

现状 `damp: 0.97 - 0.03*tip`（每帧乘）在 120fps 下等效 60fps 的 `0.97² = 0.941`，帧率一变行为就变。

```js
// 正确：连续阻尼系数，与帧率无关
const damp = Math.exp(-lambda * h);     // lambda 单位 1/s
// 或转换为 ζ： lambda = 2 * zeta * omega
```

**换算**：`每帧乘数 0.97@120fps` → `lambda = -ln(0.97)*120 = 3.65 s⁻¹` → `ζ = lambda/(2ω)`。
对应 `k=400 (ω=20)`：`ζ = 3.65/40 = 0.091` → **严重欠阻尼**，这就是"永远在微颤"的原因。目标 `ζ = 0.2` → `lambda = 2*0.2*20 = 8` → 每帧乘数 `exp(-8/120) = 0.935`。

**(3) 质量/刚度：用 ω 和 ζ 表达，不要用裸 k 和 damp**

这是自研代码最容易出错的地方。**不要**直接写 `k = 400`、`damp = 0.97`，改成物理量：

```js
// 每根链按"部位"给 (omega, zeta)，而不是裸 k
const PRESET = {
  hair:   { omega: 13.0, zeta: 0.20 },   // 周期 0.48s，1–2 次回摆
  skirt:  { omega: 10.0, zeta: 0.30 },   // 周期 0.63s，更沉
  ribbon: { omega: 15.0, zeta: 0.15 },   // 周期 0.42s，飘
};
// 每帧：
const k     = omega * omega;                  // 单位 1/s²
const c     = 2 * zeta * omega;               // 单位 1/s
const acc   = -k * pos - c * vel;             // 标准阻尼谐振子
// 半隐式欧拉（比 Verlet 更好控阻尼）：
vel += acc * h;
pos += vel * h;
```

**注意**：现状的 `pos/prev` 存的是**旋转小量**（rad），不是位移（m）。所以 `k` 的量纲是 **1/s²**，`omega = sqrt(k)`。这就是注释里「k=400 → ω=20 rad/s → 周期 0.31s」的来源，是对的 —— 但 `damp` 那行不是。**改成 (ω, ζ) 参数化后这两个量就能正交调节了。**

**(4) 刚度要沿链递减（tip 越大越软）**

现状 `k = 400 - 280*tip` 是对的思路。改成 ω 形式：

```js
omega: 16.0 - 8.0 * tip,     // 根部 16 rad/s（周期 0.39s）→ 末梢 8 rad/s（周期 0.79s）
zeta:  0.28 - 0.12 * tip,    // 根部 0.28（稳）→ 末梢 0.16（飘）
```

**发梢更软更飘、发根更硬更稳** —— 这是所有商业头发解算的共识做法。

**(5) 约束：保持骨长 + 一次迭代就够**

因为本项目是"旋转小量 + 保持静止姿态"的模型（不是自由质点），骨长约束天然满足，**不需要** Jakobsen 的多次迭代。
如果改成真正的质点链（每节一个自由点），则：
- 位置约束迭代 **3–10 次**（迭代越多越硬/越不拉伸，"More iterations = stiffer cloth"）
- 迭代完必须**重新计算旋转**写回骨骼：`quat = initialLocalRotation * fromToQuaternion(boneAxis, normalize(localDir))`

> 依据：[Jakobsen, "Advanced Character Physics" (GDC 2001)](https://www.cs.cmu.edu/afs/cs/academic/class/15462-s13/www/lec_slides/Jakobsen.pdf)（Verlet + 位置约束迭代的原始文献）

**(6) 碰撞：球/胶囊 + 一次性推出，注意"推完要重新归一化"**

规范参考实现的关键两行：

```ts
if (distance < 0.0) {
  nextTail = nextTail - direction * distance;                       // 沿法向推出
  nextTail = worldPosition + (nextTail - worldPosition).normalized * boneLength;   // ★ 必须重新归一化
}
```

**漏掉第二行 = 碰撞把骨骼"拉长"了 = 碰撞后手臂/腿穿过裙子 = 典型崩坏。** 本项目的自研 HairPhysics **完全没有碰撞处理**，这也是它不够用的原因之一。

**collider 循环顺序**：规范是 for 循环顺序推出，**不做迭代求解**。所以多个 collider 同时接触时会有抖动 —— 解决方法是像 §3.6 第 6 条那样"把 collider 排成板状"减少歧义，而不是加迭代。

### 4.4 center 与拖拽场景的取舍（本项目特有）

| 方案 | 静止时 | 拖拽整体位移时 | 结论 |
|---|---|---|---|
| `center = null`（现状） | 窗口微抖会被放大成头发晃动 | **整体位移产生滞后甩动** ✅ 正是想要的 | **保持现状** |
| `center = hips` | 稳定，位移不摇 | **整体位移不产生任何惯性** ❌ 拖起来头发像焊死的 | 不要用 |

VRM 官方文档说 center 用于「移动する際の揺れ防止」（防止移动时摇晃）—— 这恰恰是**桌面宠物反着要的**。桌宠的核心体验就是"被拎起来时头发飘"。

> 官方原文：[VRMSpringBone · "移動する際の揺れ防止"](https://vrm.dev/univrm/springbone/univrm_secondary)、规范 §Center Space
>
> 若确实需要 center，规范要求：「The center node must be the 0th joint of the SpringChain, or its ancestors」，且不能是别的 chain 的 joint 或其子孙。社区踩坑记录（[めんどす note](https://note.com/mendosu)）：直接拿 VRM 根节点当 center **是违反 1.0 规范的**，必须给 hips 加一个父骨骼再设为中心。

### 4.5 拖拽状态机（具体建议）

```
IDLE    : dragForce = 0.030, gravityPower = 0.08, stiffness = 0.07
GRAB    : 0.2s 过渡 → dragForce = 0.010, gravityPower = 0.05, stiffness = 0.07
DRAG    : 保持 GRAB 值；同时把身体侧向加速度喂给"额外外力"
RELEASE : 0.25s 过渡 → 回 IDLE 值
```

- **GRAB 降低 gravityPower 而非提高**：被拎起来的时候，"下坠感"会让头发往一个死方向贴，反而不好看。抬起来的瞬间重力应该"变轻"。
- **stiffness 全程不变**：避免"变脸"（头发材质感突变）。只动 dragForce 和 gravityPower。
- **RELEASE 阶段的 0.25s 是精华**：`dragForce` 从 0.010 升回 0.030 的过程中，头发会刚好完成 1 次过冲 + 收敛。这个过渡本身就是"余摆"效果。

---

## 5. 性能：209 joint / 120fps / QtWebEngine 到底吃多少 CPU

### 5.1 实测量级：**完全不是瓶颈**

用 three-vrm 官方 PR 的基准数据（[pixiv/three-vrm PR #1539](https://github.com/pixiv/three-vrm/pull/1539)，2024-11 合并）：

| Avatar | Before PR | Pre-compute order | World space | + Collider offset |
|---|---|---|---|---|
| VRM1_Constraint_Twist_Sample.vrm | 658.0 µs | 179.1 µs | 164.3 µs | **145.7 µs** |
| AvatarSample_C.vrm | 1.0 ms | 615.3 µs | 473.8 µs | **415.2 µs** |
| Zonko_VRM_221128_ps.vrm | 3.2 ms | 318.0 µs | 269.1 µs | **200.1 µs** |
| AKAI Original VRM | 161.7 µs | 105.8 µs | 92.4 µs | **95.1 µs** |

`vrm.update` 全量调用（含 springbone）**平均 0.1–0.4 ms**。

**本地已确认**：`web3d/vendor/three-vrm.module.js` 里 `_sortedJoints`(9 次)、`_ancestors`(7)、`lowestCommonAncestor`(2)、`traverseChildrenUntilConditionMet`(4)、`worldSpaceBoneAxis`(2)、`addScaledVector`(2) **全部存在** → **3.5.5 已包含 PR #1539 的全部三项优化**（预计算更新顺序、world-space 力计算、collider shape offset）。不需要自己打补丁。

### 5.2 本模型的实际负载

我按 GLB 结构精确算过每帧碰撞测试次数：

```
非末端 joint（真正参与物理的）：     170
每 frame 碰撞测试（joint × 所属 collider）： 278 次
平均每个 joint 的 collider 数：      1.64
```

**278 次 sphere/capsule vs point 距离计算/帧**。每次是一个 `Vector3` 减法 + 点积 + 开方。

**估算**：278 × 120 fps = **33,360 次/秒**。现代 CPU 上单次约 20–40 ns（含 JIT 友好的 TypedArray/对象访问），总计 **0.7–1.3 ms/秒 = 0.07–0.13% 单核占用**。

**结论：物理 CPU 开销可以忽略。** 真正的开销在别处（见 §5.5）。

### 5.3 但有一个真实的**结构**开销陷阱

`VRMSpringBoneManager.update()` 每个 joint 之后都调用 `traverseChildrenUntilConditionMet(springBone.bone, this._relevantChildrenUpdated)` —— "update children world matrices... it is required when the spring bone chain is sparse"。

这个 traverse 是**沿子节点向下走直到碰到下一个 springbone 为止**。本模型 315 bones、spring 覆盖 209 个（含末端），剩下约 **106 个非 spring 骨骼**会被反复遍历。虽然每帧量级不大，但它是**每个 joint 一次**（170 次 traverse 调用）。

**优化手段**：如果你的骨骼链是密集的（spring 直接父子相连），这个 traverse 每帧只走 0 层就 return。本模型 qun_ 是 7 节连续、hair_ribbon 是 10 节连续 → 大概率只走 0–1 层，**实际开销很小**。但 **`cloak_m_01`(5节) / `earring_l_01`(6节) 这类如果与主链之间夹了稀疏节点，就会变贵**。

### 5.4 优化手段（按性价比排序）

**#1 关节数剪枝 —— 最有效，且本模型有大把冗余**

本模型 39 条 spring 里，**有 5 条只有 1 个 joint**：
`右胸`、`左胸`、`ld`、以及若干单节链。规范明确说「末端 joint 不使用任何参数」，单节 spring **完全不产生物理，只在浪费排序和矩阵更新**。

同样，`part_r_01`(2)、`part_l_01`(2)、`hair_up_r2_01`(2)、`hair_rr_01`(2)、`cloth_UpperArm_l/r_01`(2) 这些 2 节链只有 1 个有效 joint，收益极低。

**做法**：把「关节数 < 3」的 spring 从 manager 里 `deleteJoint()` 掉（或保留但设 `stiffness=0, dragForce=1` 让它完全静止，开销更低）。

预计剪掉 **≈20 个 joint（12%）**，视觉无损。

**#2 降频 + 插值 —— 收益有限，不推荐**

springBone 求解降到 30–60 Hz、渲染插值到 120 fps：省下的是 §5.2 里那 **0.13% CPU**。**投入产出比极差**，而且引入插值延迟会破坏"跟手"手感。**不要做。**

**#3 固定步长 —— 应该做，但不是为了性能**

如图 §4.3(1)。**目的是稳定性，不是帧率**。120fps 的 `dt` 抖动（实测渲染循环用 `Math.min(clock.getDelta(), 0.05)`）会让 springBone 的等效 stiffness 每帧漂移 ±20%。

**#4 早期退出 —— 已经部分做了**

three-vrm 的 joint 有 `if (delta <= 0) return;`。可以额外加"静止检测"：连续 N 帧所有 joint 的 `|currentTail − prevTail| < ε` 就跳过整个 manager.update()，直到父级矩阵变化。

**但注意**：`vrm.update(dt)` 会同时更新 humanoid/lookAt/expression，不能整体跳过。要做只能 patch springBoneManager。**本模型静止时头发本来就在收敛（maxAngle≈0），收益≈0。**

**#5 减少 collider 测试 —— 收益明确**

现状 278 次/帧，且**每条 spring 只挂 1 个 collider group**（39 条全部如此）。这是"过度耦合"：`hair_ribbon_l_01` 有 10 个 joint，挂了 4 个 collider → 36 次测试/帧，其中大概率大部分是永不相交的远方 collider（比如脚部 collider 对头顶丝带）。

**做法**：按部位拆分 collider group（头/颈/上半身/腰/左右腿/手），每条 chain 只挂真正相邻的。
预计能从 278 降到 **120–150 次/帧（-45%）**，**同时提升碰撞质量**（减少"远处 collider 误推"造成的诡异摆动）。

`hair_ribbon_l/r_01`（36 次/帧，占 26%）、`earring_l_01` 和 `ponytail_hair_m_01`（各 20 次）是优化重点。

### 5.5 真正的 CPU 瓶颈不在物理

本项目 120fps 下的开销大头应该是：
1. **QtWebEngine 的合成/上屏**（Chromium 每帧要把 canvas 合成到 QWidget）
2. **骨骼动画 + SkinnedMesh 蒙皮**（315 bones，GPU 蒙皮 vs CPU 蒙皮差别巨大）
3. three.js 的场景遍历 + 每帧材质 uniform 上传

**验证方法**：在 `vrm.update(dt)` 前后插 `performance.now()`，跑 10 秒取均值。如果 < 0.5 ms，物理就真的不是问题。

---

## 6. 落地清单（按顺序执行）

### 阶段一：原生 springBone 参数（30 分钟，零风险）

```js
// 放在 loadModel() 之后、第一次 update 之前
function tuneSpringBone(vrm) {
  const R = {
    hair:   { stiffness: 0.07, dragForce: 0.022, gravityPower: 0.08, hitRadius: 0.010 },
    skirt:  { stiffness: 0.04, dragForce: 0.030, gravityPower: 0.10, hitRadius: 0.020 },
    ribbon: { stiffness: 0.06, dragForce: 0.018, gravityPower: 0.06, hitRadius: 0.008 },
  };
  const HOOD = /^(hair_ribbon|ponytail_hair|hair_rr|hair_up|earring)/;
  const SKIRT = /^qun_/;
  const RIBBON = /^(cloak|weiba|part_|cloth_)/;

  for (const j of vrm.springBoneManager.joints) {
    const n = j.bone.name || '';
    const p = HOOD.test(n) ? R.hair : SKIRT.test(n) ? R.skirt : RIBBON.test(n) ? R.ribbon : R.hair;
    j.settings.stiffness    = p.stiffness;
    j.settings.dragForce    = p.dragForce;
    j.settings.gravityPower = p.gravityPower;
    j.settings.hitRadius    = p.hitRadius;
    // gravityDir 保持 [0,-1,0]
  }
  // ★ 改完参数不需要 reset()，下一帧自然生效
}
```

**验收**：静止 maxAngle ≈ 0；快速拖动 maxAngle 应在 **45–70°**（现在 36.6° 偏小）；松手后应能看到 **1–2 次可见回摆**。

### 阶段二：collider group 分层路由（半天）

拆成 head / neck / chest / waist / legL / legR / handL / handR，按 §3.6 原则只挂相邻的。
**验收**：278 → 150 次/帧；裙子插腿明显减少。

### 阶段三：拖拽状态机（半天）

`dragForce` 0.030 ↔ 0.010，过渡 0.2/0.25 s。

### 阶段四：只有当阶段一~三都不够时，才考虑自写

自写 HairPhysics 的前提是**必须**补上碰撞（§4.3(6)），否则一定不如原生。

---

## 7. 引用来源汇总

### 规范与官方文档
- [VRMC_springBone 1.0 规范原文（vrm-specification）](https://github.com/vrm-c/vrm-specification/blob/master/specification/VRMC_springBone-1.0/README.md)
- [VRM 官方文档 · VRMC_springBone（日/英）](https://vrm.dev/vrm1/springbone/)
- [VRM 官方文档 · VRMSpringBone 组件说明（含「移动する際の揺れ防止」）](https://vrm.dev/univrm/springbone/univrm_secondary)
- [VRM 官方文档 · IVrm10SpringBoneRuntime](https://vrm.dev/en/api/springbone/vrm1/IVrm10SpringBoneRuntime/)
- [UniVRM · VRMSpringBone.cs（默认值 1.0 / 0 / 0.4 / 0.02）](https://github.com/vrm-c/UniVRM/blob/v0.78.0/Assets/VRM/Runtime/SpringBone/VRMSpringBone.cs)
- [DeepWiki · UniVRM SpringBone Overview and Configuration（Joint 默认值表）](https://deepwiki.com/vrm-c/UniVRM/5.1-springbone-overview-and-configuration)
- [DeepWiki · VRMC_springBone System](https://deepwiki.com/vrm-c/vrm-specification/3.1-vrmc_springbone-system)
- [UniVRM issue #2242 · scale 改变导致 springBone 异常](https://github.com/vrm-c/UniVRM/issues/2242)

### three-vrm 源码与讨论
- [VRMSpringBoneJoint.ts](https://github.com/pixiv/three-vrm/blob/dev/packages/three-vrm-springbone/src/VRMSpringBoneJoint.ts)
- [VRMSpringBoneManager.ts](https://github.com/pixiv/three-vrm/blob/dev/packages/three-vrm-springbone/src/VRMSpringBoneManager.ts)
- [VRMSpringBoneManager API 文档](https://pixiv.github.io/three-vrm/docs/classes/three-vrm-springbone.VRMSpringBoneManager.html)
- [PR #1539 · Optimize spring bones computations（性能数据表）](https://github.com/pixiv/three-vrm/pull/1539)
- [PR #1555 · Improve init performance with a massive amount of spring bones](https://github.com/pixiv/three-vrm/commit/4f434c98ecde0b785986eb66089d8d8777fa48c9)
- [Discussion #1464 · 运行时改 springbone 强度（维护者 0b5vr 回复）](https://github.com/pixiv/three-vrm/discussions/1464)

### 社区调参经验
- [Tcam《[VRM0.x]SpringBoneの個人的Tips》（Stiffness=范围 / Drag=时间；Gravity 从 0 开始；裙子破绽 7 条处置）](https://note.com/tcam727/n/n312bcd42d4e2)
- [Cluster Creators Guide《「揺れもの」を設定する【VRM1.0のSpringBone解説】》（Center 用法）](https://creator.cluster.mu/2024/12/02/vrm10-springbone)
- [VRChat PhysBones 官方文档（Pull / Gravity Falloff / Grab Movement）](https://creators.vrchat.com/common-components/physbones)
- [Reddit r/VRchat · Any Phys Bones Value tips?（pull 建议 < 0.2）](https://www.reddit.com/r/VRchat/comments/uji2v2/any_phys_bones_value_tips)
- [SrPhilippe · VRChat DynamicBone configs gist](https://gist.github.com/SrPhilippe/43c1bad021fab173d3ef1d5255d53f53)
- [Z-ANESaber/DynamicBones-Configs（Short Hair 0.1 / Long Hair 0.4 / Cloth 0.1）](https://github.com/Z-ANESaber/DynamicBones-Configs)
- [vrm-springbone-physics skill（"Incorrect Delta Time 占 90%" 诊断清单）](https://lobehub.com/skills/project-n-e-k-o-n.e.k.o-vrm-physics)

### 物理与数值
- [Gaffer On Games · Fix Your Timestep!](https://gafferongames.com/post/fix_your_timestep/)
- [Gaffer On Games · Integration Basics](https://gafferongames.com/post/integration_basics/)
- [Thomas Jakobsen · Advanced Character Physics (GDC 2001)](https://www.cs.cmu.edu/afs/cs/academic/class/15462-s13/www/lec_slides/Jakobsen.pdf)
- [Cloth Simulation via Verlet Integration（约束迭代 3–10 次）](https://www.mysimulator.uk/content/articles/cloth-simulation.html)

---

## 附：一页速查

```
现状 (120fps)           →  目标 (120fps)          →  公式/依据
stiffness   1.0         →  头发 0.05–0.10        ω = sqrt(s/(B·dt)), B=0.034
                           裙摆 0.03–0.06           目标 ω = 10–18 rad/s
dragForce   0.5         →  头发 0.016–0.030      ζ = γ/ω, γ=-ln(1-d)·fps
                           裙摆 0.020–0.040         目标 ζ = 0.15–0.35
gravityPower 0          →  0.06–0.10 (头发)      1g@120fps = 0.0817
                           0.08–0.14 (裙摆)         建议先上半重力
hitRadius   0           →  0.010 (头发)          相邻 collider 半径的 15–25%
                           0.020 (裙摆)             且 ≤ 骨段长的一半 (0.017)
center      null        →  保持 null             桌宠要的就是位移甩动

数值安全线 (120fps)：stiffness < 16   (ω·dt < 2)
```

**一句话**：把 (ω, ζ) 从 **(59 rad/s, 1.40 过阻尼)** 搬到 **(13 rad/s, 0.18 欠阻尼)**，同时补上 gravityPower≈0.08 和 hitRadius≈0.01 —— 这就是从"钢丝"到"跟手但不生硬"的全部。
