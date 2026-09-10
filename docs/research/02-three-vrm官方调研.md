# @pixiv/three-vrm 拖拽 / 物理 / 渲染 调研报告

> 项目：卡拉彼丘米雪儿 3D 桌宠（PyQt6 + QtWebEngine + three.js r170 + three-vrm 3.5.5，全离线）
> 证据等级说明：本报告的源码引用全部来自 **three-vrm v3.5.5 tag** 的一手源码（已下载到本地 `vrm_research_official/src/`），
> 规范引用来自 **vrm-c/vrm-specification** 官方仓库。凡属社区推测均已标注。

---

# ⚠️ 重要更正（第二轮，经本机实测验证）

初版报告有 **2 处结论错误**，经由后续调研 + 本机实测推翻。**请以本节为准**：

| # | 初版错误结论 | 更正后的事实 | 证据 |
|---|---|---|---|
| **C1** | "官方没有'拖拽角色'的任何示例" | ❌ **错**。官方有 [`mouse.html`](https://github.com/pixiv/three-vrm/blob/dev/packages/three-vrm/examples/mouse.html)，描述 "Move a VRM using mouse. Test of secondary animations"，**它就是官方"鼠标拖动角色"的范本**。我初版只下载了 4 个示例，漏掉了它。 | 已下载核对源码（见 1.5 节） |
| **C2** | "整体位移应改 `vrm.scene.position`" | ⚠️ **不完整**。官方 `mouse.html` 改的是 **`getNormalizedBoneNode('hips').position`**，不是 `vrm.scene.position`。两者效果不同（见 2.5 节）。 | `mouse.html` 第 139 行 |

**计数更正**：three-vrm 官方 examples 是 **14 个 HTML 页面**（初版误把 `cubemap`/`humanoidAnimation`/`models` 三个**子目录**计入，得出 16）。**结论不受影响且更强**：14 个示例中**没有任何 IK 示例，也没有任何"角色被抓取"示例**。

**新增两项本机实测结论**（详见文末"第二轮补充"）：
- 🔴 **`page().setVisible(True)` 是隐藏节流的官方解法，chromium flags 救不了 rAF** —— 但我实测发现**项目用的 setTimeout 恰好被现有 flags 保护住了**（隐藏时仍全速），所以项目当前安全，但存在隐患。
- 🟢 **`eventFilter` 挂在 `focusProxy()` 上能收到鼠标事件**（挂 view 上不能）—— **本项目可以去掉 `GetAsyncKeyState` 全局轮询这套 hack**。

---

## 结论速览

1. **官方对"被抓起来时该怎么调 springBone"没有资料；但有"鼠标拖动角色"的官方示例 `mouse.html`**（初版遗漏，已更正）。VRMC_springBone 1.0 规范只定义参数**语义**，明确不给推荐值（该节标注 `非规范性`）。名字带 `dnd` 的两个官方示例是**拖文件加载模型**，与"拖角色"无关。→ 我方的自研拖拽反应**无官方参数对标物**，但**有官方位移写法可对标**。
2. **本项目模型的物理参数是 Blender 导出器默认值，不是原作者调优的**（我实测：209 个 joint **全部** `stiffness=1.0 / gravityPower=0.0 / dragForce=0.5 / hitRadius=0.0`，39 条链 **0 条**设置 `center`）。项目注释"参数是原作者调的，质量最好"是**误判**——这直接解释了头发为什么"只是跟着晃、没有惯性甩动感"。
3. **`center`（中心空间）是官方为"角色整体移动导致弹簧骨狂抖"开出的唯一正规处方**，但本项目模型一个都没设，且 three-vrm 不会替你补。这是**最高优先级、最低风险**的可落地改造项。
4. **我方的旋转补偿数学完全正确**（绕腰点 `C=(0, 0.93, 0)` 旋转需补 `dx=Cy·sinθ, dy=Cy·(1−cosθ)`，我独立推导验证一致），`position` 绝对赋值也是对的，注释里"累加漂移 −14"的教训与官方实践一致。
5. **QtWebEngine 的坑项目已经踩完并解决了**，`QTWEBENGINE_CHROMIUM_FLAGS` 里那 6 个 flag 与官方/社区结论一致，尤其 `--disable-backgrounding-occluded-windows` 是 Windows 专用遮挡检测（`CalculateNativeWinOcclusion`）的官方对策。

---

## 第 1 节 · VRMC_springBone 调参：官方规范问了等于没问

### 1.1 官方规范说了什么

来源：[VRMC_springBone 1.0 规范](https://github.com/vrm-c/vrm-specification/blob/master/specification/VRMC_springBone-1.0/README.md)（本地副本 `vrm_springbone_research/raw/spec_springbone.md`）

参数定义表（规范原文，**全部只给类型和一句话语义，无取值范围建议、无推荐值**）：

| 参数 | 规范原文定义 | 是否有推荐值 |
|---|---|---|
| `stiffness` | "Rigidity (force to return to the initial state)"，0 或以上 | ❌ 无 |
| `gravityPower` | "Gravity force (force applied to Spring Bone every frame)" | ❌ 无 |
| `gravityDir` | `[x, y, z]` | ❌ 无（three-vrm 默认 `(0,-1,0)`） |
| `dragForce` | "Deceleration (force to decelerate Spring Bone)"，`[0-1]` | ❌ 无 |
| `hitRadius` | "SpringBone hitbox size"，单位米 | ❌ 无 |

规范里唯一涉及"怎么调"的段落是 **Center Space**，原文说 `center` "is effective in these cases, mainly when SpringBone is shaking too intense"，具体两个场景：

> - When SpringBones shake too much when the model moves by walking, running, etc.
> - When you want to move SpringBones attached to the head ... only when moving its head

**这就是官方对"角色被整体移动时头发乱抖"给出的全部答案** —— 用 `center`，不是调参数。

### 1.2 参数的数值语义（来自三维源码，非规范）

来源：[`VRMSpringBoneJoint.ts` 第 230–276 行](https://github.com/pixiv/three-vrm/blob/v3.5.5/packages/three-vrm-springbone/src/VRMSpringBoneJoint.ts)

```ts
_nextTail
  .copy(this._currentTail)
  // ① 惯性：上一帧位移 × (1 - dragForce)
  .add(_v3A.subVectors(this._currentTail, this._prevTail).multiplyScalar(1 - this.settings.dragForce))
  .applyMatrix4(this._getMatrixCenterToWorld())
  // ② 刚性：沿"静止方向"推回，冲量 = stiffness × delta
  .addScaledVector(worldSpaceBoneAxis, this.settings.stiffness * delta)
  // ③ 重力：冲量 = gravityDir × gravityPower × delta
  .addScaledVector(this.settings.gravityDir, this.settings.gravityPower * delta);
```

三条可直接落地的结论：

- **`stiffness` 越大 = 越"硬" = 摆得越小**（它是把尾巴拉回静止方向的回复力，规范译名"Rigidity 刚性"是对的）。想让头发更飘 → **调小**；想更贴服 → **调大**。
- **`dragForce` 越大 = 衰减越快 = 越不飘**。且它是**每帧**乘性衰减 `(1-dragForce)`，所以这个值对帧率极其敏感（见 1.4）。
- **`gravityPower=0` 意味着没有下垂力**。重力只影响"自然下垂感"，不影响摆动幅度。

### 1.3 【重要】本项目模型的真实参数（我实测）

用我新写的工具 `strinova-desktop-pet/tools/pmx_to_vrm/dump_springbone.py` 直接解析 `web3d/models/michelle_phys.vrm` 得到：

```
specVersion = 1.0
colliders = 19   colliderGroups = 19   springs = 39   joint 总数 = 209
有 center 的 spring 数 = 0          ← 关键

stiffness      n=209  min=1.0000 中位=1.0000 max=1.0000   ← 全是 1.0
gravityPower   n=209  min=0.0000 中位=0.0000 max=0.0000   ← 全是 0.0
dragForce      n=209  min=0.5000 中位=0.5000 max=0.5000   ← 全是 0.5
hitRadius      n=209  min=0.0000 中位=0.0000 max=0.0000   ← 全是 0.0
每条链内参数统一（无一条链内部有差异）
generator = VRM Add-on for Blender v4.7.1
```

链名分布：20 条裙摆（`qun_0_0`~`qun_0_19`，各 7 节）、左右发带（`hair_ribbon_l/r_01`，各 10 节）、双马尾 6 节、耳环 6 节、尾巴 7 节、披风/衣摆若干。

**判定：这是 Blender VRM 导出器的统一默认值写入，不是逐链手工调优。** 证据是"209 个 joint 数值完全一致"——真人调参不可能给裙摆和耳环同一套刚度/阻尼。

> ⚠️ 项目 `pet_viewer.html` 第 432–433 行的注释
> "参数是原作者调的，质量最好" **与实测不符**，建议修正注释，否则后续调参会误以为"不能动"。

### 1.4 `center` 方案：可落地性最高的一项

**为什么本项目特别需要它**：透明置顶小窗里的桌宠，`vrm.scene.position` **每一帧都在变**（拖动 + 待机呼吸 `idleBreath`）。规范规定"默认在**世界空间**求值关节位置"，所以每次整体平移都会被物理系统当成"关节自己在动"，产生虚假惯性和抖动。这正是规范 Center Space 段落描述的第一个场景。

**官方 API（3.5.5 可用，非废弃）**：

来源：[`VRMSpringBoneJoint.ts` 第 98–122 行](https://github.com/pixiv/three-vrm/blob/v3.5.5/packages/three-vrm-springbone/src/VRMSpringBoneJoint.ts)、[`VRMSpringBoneManager` 文档](https://pixiv.github.io/three-vrm/docs/classes/three-vrm-springbone.VRMSpringBoneManager.html)

```ts
// VRMSpringBoneJoint 上的公开 setter（v3.5.5 确实存在）
public get center(): THREE.Object3D | null
public set center(center: THREE.Object3D | null)
```

可直接抄的代码（放进 `loadModel` 里、`vrm.update()` 首次调用之前）：

```js
// 让所有 springBone 在"腰/上半身"空间里求值，而不是世界空间。
// 规范约束：center 必须是该链第 0 个 joint 或其祖先。
if (vrm.springBoneManager) {
  const centerNode =
    vrm.humanoid?.getRawBoneNode('hips') ||
    vrm.humanoid?.getRawBoneNode('spine') ||
    vrm.scene;

  let n = 0;
  vrm.springBoneManager.joints.forEach(joint => {
    joint.center = centerNode;   // 逐 joint 设置（没有批量 API）
    n++;
  });
  vrm.springBoneManager.setInitState();  // ★ 必须！重建静止基准
  console.log('[js] springBone center 已设 →', centerNode.name, 'joints=' + n);
}
```

**三个必须注意的实现细节**（都来自源码，不是我猜的）：

1. **改完 `center` 必须调 `setInitState()`**。`center` 的 setter 只切换坐标系，不会重算 `_currentTail`；而 `setInitState()` 第 199–200 行正是用 `_getMatrixWorldToCenter()` 重新投影尾巴状态。不调就会在切换瞬间弹一下。
2. **`center` 的逆矩阵是自动维护的，不用担心性能**。[`Matrix4InverseCache.ts`](https://github.com/pixiv/three-vrm/blob/v3.5.5/packages/three-vrm-springbone/src/utils/Matrix4InverseCache.ts) 用 `Proxy` 拦截 `matrix.elements` 的写入来打脏标记，`inverse` 只在真正变脏时用 `mat4InvertCompat` 重算——即**每帧最多一次求逆**，不是每个 joint 一次。
3. **`center` 必须是 joint 的祖先**。规范原文："The center node must be the 0th joint of the SpringChain, or its ancestors." 用 `hips` 对所有链（裙摆/发带/耳环/尾巴/披风）都安全，因为它们的根（`qun_*`、`hair_*`、`waist` 系）都挂在脊柱链下。**three-vrm 不做合法性校验**，传错节点会静默产生错误姿态。

**可落地性：能直接抄**，且是"改 10 行、回报最大"的一项。建议先做成开关（`window.setSpringCenter(on)`），用现成的 `verify_phys.py` 第 2 项（静止时 `maxAngle < 0.08`）做前后对比。

> 历史提醒：[issue #1112](https://github.com/pixiv/three-vrm/issues/1112) 讨论过 v0.6 的 `springBoneManager.setCenter()` 在新版消失。结论是**没有批量 API**，只能逐 joint 赋值——上面的循环就是官方认可的做法。

### 1.5 🔴 官方示例里有没有"角色被抓起来/被拖动"——**有！`mouse.html`（初版遗漏，此处更正）**

**官方 examples 完整清单（14 个 HTML 页面）**，来源：[官方索引页](https://raw.githubusercontent.com/pixiv/three-vrm/dev/packages/three-vrm/examples/index.html)：

```
basic.html            animations.html      mouse.html
debug.html            firstperson.html     lookat.html
dnd.html              lookat-advanced.html materials-debug.html
webgpu-dnd.html       meta.html            humanoidAnimation/index.html
bones.html            expressions.html
```

| 示例 | 实际内容 | 与"拖角色"的关系 |
|---|---|---|
| **`mouse.html`** | **"Move a VRM using mouse. Test of secondary animations"** | ✅ **官方唯一范本** |
| [`dnd.html`](https://github.com/pixiv/three-vrm/blob/dev/packages/three-vrm/examples/dnd.html) | `dragover`/`drop` → 拖进来的 **.vrm 文件**用 `createObjectURL` 加载 | ❌ 拖的是文件 |
| `webgpu-dnd.html` | 同上，仅渲染器换 WebGPU | ❌ 拖的是文件 |
| `three-vrm-animation/dnd.html` | 拖入 .vrm + .vrma 两个文件 | ❌ 拖的是文件 |

> ⚠️ **"dnd" = drag & drop a .vrm file**，别被文件名误导——这是最容易踩的误判。

**`mouse.html` 官方原文（第 129–141 行，我下载核对过）**：

```js
const mouseRaycaster = new THREE.Raycaster();   // ⚠️ 声明了但从未使用

window.addEventListener( 'mousemove', function ( event ) {
    if ( currentVrm ) {
        const range = CAMERA_Z * Math.tan( CAMERA_FOV / 360.0 * Math.PI );
        const px = ( 2.0 * event.clientX - window.innerWidth ) / window.innerHeight * range;
        const py = - ( 2.0 * event.clientY - window.innerHeight ) / window.innerHeight * range;

        // ★★★ 官方做法：改 normalized hips 的局部 position
        currentVrm.humanoid.getNormalizedBoneNode( 'hips' ).position.set( px, py, 0.0 );
    }
} );
```

**三个要点**：
1. ✅ **官方改的是 `hips` 骨骼，不是 `vrm.scene.position`**。
2. ⚠️ 官方这个投影反算**不严谨**（`range` 分母用 `innerHeight`，但 `clientX` 用 `innerWidth`），宽高比不匹配时有偏差。自己实现应做正确的投影反算。
3. ⚠️ `mouseRaycaster` **声明了却从未使用** —— 官方**没做命中检测**，直接按鼠标位置钉 hips。

**✅ 14 个示例中：无 IK 示例、无"被抓取"示例。** 官方不提供 IK —— 维护者 0b5vr 在 [discussion #1145](https://github.com/pixiv/three-vrm/discussions/1145) 明确回复：**"We don't provide any Humanoid IK systems for now."**

**结论**：官方**有**"拖拽角色"的位移写法（`hips.position`），但**没有**"被抓起来的反应姿势"资料。我方的表演结构（上身稳、腿主导、脚背绷直）属于自研，无官方对标物。

### 1.6 ⚠️ 命中检测：社区方案 [moeru-ai/airi](https://github.com/moeru-ai/airi)（技术栈完全一致）

它用"给骨骼挂不可见碰撞盒 + raycast"实现 VRM 交互，**与我们的技术栈（three.js + @pixiv/three-vrm）完全相同**：

```ts
export const VRM_INTERACTION_TARGETS = [
  'head',
  'leftUpperArm', 'leftLowerArm', 'leftHand',
  'rightUpperArm', 'rightLowerArm', 'rightHand',
  'leftFoot', 'rightFoot',
] as const   // ⚠️ 没有 hips/spine/chest —— "抓腰"是空白，需自己加

const COLLIDER_DEFINITIONS = [
  { target: 'head',        bone: 'head',        size: [0.22, 0.25, 0.25], offset: [0,  0.05,  0] },
  { target: 'leftUpperArm', bone: 'leftUpperArm', size: [0.2, 0.34, 0.2], offset: [0, -0.17,  0] },
  { target: 'leftHand',     bone: 'leftHand',    size: [0.2, 0.2, 0.2],   offset: [ 0.06, 0,  0] },
  { target: 'leftFoot',     bone: 'leftFoot',    size: [0.15, 0.15, 0.25], offset: [0, -0.05, -0.08] },
] as const

export function createVrmInteractionColliders(vrm: VRM) {
  const material = new MeshBasicMaterial({ visible: false })   // 不可见
  const boneNode = vrm.humanoid?.getNormalizedBoneNode(def.bone)   // 挂骨骼，自动跟随
  const collider = new Mesh(geometry, material)
  collider.name = `${COLLIDER_NAME_PREFIX}${def.target}`
  boneNode.add(collider)
}

// 区分"点击"与"拖拽"（8px 阈值）
export function isClickLikePointerGesture(start, end, maxDistance = 8): boolean {
  const dx = end.x - start.x, dy = end.y - start.y
  return dx*dx + dy*dy <= maxDistance*maxDistance
}
```

**→ 把 `hips` 按同格式加入即可实现"抓腰"**，建议 `{ bone: 'hips', size: [0.24, 0.20, 0.20], offset: [0, 0, 0] }`。

**可落地性：能直接抄**（注意 airi 是 TS，需转成我们用的 ESM 模块写法）。

---

## 第 2 节 · 整体位移 + 旋转补偿的正确姿势

### 2.1 官方文档对 `vrm.scene.position` 的态度：完全不表态

[`VRM` 类文档](https://pixiv.github.io/three-vrm/docs/classes/three-vrm.VRM.html) 明确说 `springBoneManager` 是 "Usually you don't have to care about this property"。官方唯一强制的约定是**必须每帧调用 `vrm.update(delta)`**：

来源：[`VRM.ts` 第 42–49 行](https://github.com/pixiv/three-vrm/blob/v3.5.5/packages/three-vrm/src/VRM.ts)

```ts
/**
 * **You need to call this on your update loop.**
 */
public update(delta: number): void
```

**官方没有给"角色整体位移该绝对赋值还是增量累加"的任何规定**，因为规范层面 `vrm.scene` 只是一个普通 `THREE.Group`。

**但官方源码有一个必须遵守的隐含约定**（见 2.4）。

### 2.2 绝对赋值 vs 增量累加：我方的做法是对的

项目第 762–766 行记录了实测教训：早期用 `vrm.scene.position.x += ...`，而待机分支只写 `position.y`，x 从不归零 → 几秒漂到 −14。**绝对赋值是唯一稳妥写法**，因为：

- 待机动画、拖动反应、未来可能加入的其他系统会**竞争同一个 `position`**；
- 增量累加下，只要有一个分支漏写归零，就会累积漂移；
- 绝对赋值天然幂等，任何一帧重算都不影响下一帧。

项目的收敛写法（第 856–858 行）是标准答案，**建议保持，不要改成累加**：

```js
// 统一写入场景位移：待机呼吸 + 拖动偏移（绝对赋值，杜绝累加漂移）
vrm.scene.position.x = dragOffsetX;
vrm.scene.position.y = (idleMotion ? idleBreath.value : 0) + dragOffsetY;
```

**可落地性：保持现状。**

### 2.3 旋转时绕"抓取点"的位移补偿：数学正确

项目要的效果是"绕腰部 `C=(0, 0.93, 0)` 旋转"，而 three.js 的 `rotation.z` 恒为绕**自身原点**（脚底）旋转，所以必须补偿原点位移。

我独立推导验证：绕 Z 轴转 θ、绕点 `C` 旋转，原点 `O=(0,0,0)` 的像为 `R·(O−C)+C`：

```
R·(−C) = (−Cy·(−sinθ)·? ...) 展开 Rz(θ)·(0,−Cy,0) = (Cy·sinθ, −Cy·cosθ, 0)
R·(O−C)+C = (Cy·sinθ, −Cy·cosθ, 0) + (0, Cy, 0) = (Cy·sinθ, Cy·(1−cosθ), 0)
```

即 `dx = Cy·sinθ`、`dy = Cy·(1−cosθ)` —— **与项目第 758–760 行注释完全一致**。项目第 796–801 行的实现：

```js
const cs = Math.cos(bodyTilt), sn = Math.sin(bodyTilt);
const Cy = GRAB_Y;                       // 0.93
vrm.scene.rotation.z = bodyTilt;
dragOffsetX = (Cy * sn) * dA;
dragOffsetY = (Cy * (1 - cs)) * dA;
```

**可落地性：保持现状。这段数学可以不用动。**

### 2.4 唯一真正的风险点：`vrm.update()` 的调用时机

这是本节最有价值的一条。读源码可知 `VRMSpringBoneManager.update()` **会主动刷新祖先的世界矩阵**：

来源：[`VRMSpringBoneManager.ts` 第 125–143 行](https://github.com/pixiv/three-vrm/blob/v3.5.5/packages/three-vrm-springbone/src/VRMSpringBoneManager.ts)

```ts
public update(delta: number): void {
  this._sortJoints();
  for (let i = 0; i < this._ancestors.length; i++) {
    this._ancestors[i].updateWorldMatrix(i === 0, false);   // ★ 刷新祖先
  }
  for (let i = 0; i < this._sortedJoints.length; i++) {
    const springBone = this._sortedJoints[i];
    springBone.bone.updateMatrix();
    springBone.bone.updateWorldMatrix(false, false);
    springBone.update(delta);                                // 用 matrixWorld 求值
  }
}
```

而 `VRMSpringBoneJoint.update()` 第 254 行用的是 `this.bone.matrixWorld` 取世界位置。**所以物理用的祖先世界矩阵 = 你调 `vrm.update()` 那一刻的值。**

规范也印证了这个顺序要求（**Calculation order** 一节）：

> "The update of the SpringBone system is done while resolving the dependencies between SpringBoneJoints. ... the update process is performed from the root to the descendants."

**实践结论**：`vrm.scene.position/rotation` 必须**在 `vrm.update(delta)` 之前**赋值完毕。项目的当前顺序（第 643–886 行）**是正确的**：

```
animate()
 ├─ 第 662–740 行：待机动画写骨骼 rotation
 ├─ 第 742–858 行：拖动反应写 rotation.z / position / scale
 ├─ 第 886 行：     vrm.update(dt)        ← 物理在这里读到最新的父级世界矩阵
 └─ 第 890 行：     renderer.render()
```

社区佐证：[issue #1502](https://github.com/pixiv/three-vrm/issues/1502) 里用户折腾了很久 `mixer.update` / `vrm.update` / IK 的顺序，最后发现能正常工作的最小写法正是"**先 `vrm.update(delta)`，其余动作在其后/之前按需**"；[discussion #1547](https://github.com/pixiv/three-vrm/discussions/1547) 也把顺序列为关键问题（bone animation → look-at 覆盖 → spring bone 最后）。

**可落地性：保持现状，但建议加一条"防御性注释"**，避免以后有人把拖动那段挪到 `vrm.update()` 后面：

```js
// ⚠ 顺序约束：所有写 vrm.scene.position/rotation 和骨骼 rotation 的代码
//   必须在本行之前完成。springBoneManager.update() 内部会用
//   updateWorldMatrix() 刷新祖先矩阵，之后再改父级，物理就滞后一帧。
vrm.update(dt);
```

### 2.5 🔴 关键：改 `vrm.scene.position` 还是改 `hips.position`？（初版遗漏，此处补上）

这是我初版最大的盲点。官方 `mouse.html` 用的是 **`hips.position`**，而项目用的是 **`vrm.scene.position`**。两者**不等价**：

| | `vrm.scene.position`（项目现状） | `hips.position`（官方 mouse.html） |
|---|---|---|
| 影响的层级 | **整个场景根**，包括脚下地面接触判定、包围盒、射线检测 | **只有髋部骨骼**，上半身/腿的相对父级不变 |
| 弹簧骨世界矩阵 | 整棵树平移 → **每个 joint 的世界位置都变** → 若无 `center`，全部产生虚假惯性 | hips 以下骨骼世界位置变，但**脊柱链的父级旋转基准不变** |
| 脚是否"离地" | ✅ 整只离开地面 | ⚠️ 只提髋，腿会被拉伸/跟着走（除非同时做腿部补偿） |
| 与 IK/脚部约束 | 简单 | 会和脚部约束打架 |
| 适用场景 | **窗口级位移**（桌宠被拖到屏幕另一处） | **角色在场景内走动/被抬高** |

**⚠️ 对桌宠这个场景，两者的语义其实不同**：
- 项目拖的是**原生窗口**（Python 侧 `move()`），`vrm.scene.position` 只是窗口内的小幅视觉偏移（悬空感、绕腰倾斜）。
- 如果改用 `hips.position`，脚不会跟着走 —— 会变成"腿被拉长"，这对"被拎起来"反而不合适。

**判定：本项目继续用 `vrm.scene.position` 是合理的**，但必须知道官方范本用的是 `hips.position`，且**两者对 springBone 的影响不同**——这正是第 1.4 节 `center` 方案要解决的问题（场景根平移污染物理空间）。

**可落地性：保持 `vrm.scene.position`；`hips.position` 仅作为"角色在场景内移动"时的备选。** 若未来要做"角色在桌面范围内走动"，再切到 `hips.position`。

---

## 第 3 节 · humanoid 骨骼姿态动画：官方推荐写法

### 3.1 官方给了两条路，且都明确支持

**路线 A：直接写 normalized bone 的 `rotation`**（适合程序化动画 / 少量骨骼）

来源：[`animations.html` 官方示例](https://github.com/pixiv/three-vrm/blob/dev/packages/three-vrm/examples/animations.html) 第 116–120 行 —— 官方就是在用 `getNormalizedBoneNode()` 取节点、拼 `QuaternionKeyframeTrack`：

```js
const armTrack = new THREE.QuaternionKeyframeTrack(
    vrm.humanoid.getNormalizedBoneNode( 'leftUpperArm' ).name + '.quaternion', // name
    [ 0.0, 0.5, 1.0 ],                                                          // times
    [ ...quatA.toArray(), ...quatB.toArray(), ...quatA.toArray() ]              // values
);
const clip = new THREE.AnimationClip( 'Animation', 1.0, [ armTrack, blinkTrack ] );
currentMixer.clipAction( clip ).play();
```

注意关键点：**track 名用的是 `getNormalizedBoneNode(name).name` 拿到的实际节点名**，不是 `'leftUpperArm'` 这种语义名。这保证了无论模型骨骼叫什么（本体是 MMD 转来的日文名如 `腕_L`），动画都能对上。

**路线 B：`createVRMAnimationClip(vrmAnimation, vrm)` + AnimationMixer**（适合播放 .vrma 文件）

来源：[`createVRMAnimationClip.ts`](https://github.com/pixiv/three-vrm/blob/v3.5.5/packages/three-vrm-animation/src/createVRMAnimationClip.ts)

```ts
export function createVRMAnimationClip(vrmAnimation: VRMAnimation, vrm: VRMCore): THREE.AnimationClip
```

内部做的事（第 12–52 行）：把 .vrma 的语义骨骼名映射到**本模型**的 normalized bone 名，并处理 VRM0 的坐标轴翻转（`metaVersion === '0'` 时 x/z 取反），以及 hips 位移按 `humanoidY / animationY` 缩放。**它还自动处理 lookAt**：若场景里没有 `VRMLookAtQuaternionProxy` 会自己建一个并打警告（第 122–140 行）。

### 3.2 官方对 `autoUpdateHumanBones` 的规定（必须知道）

来源：[`VRMHumanoid.ts`](https://github.com/pixiv/three-vrm/blob/v3.5.5/packages/three-vrm-core/src/humanoid/VRMHumanoid.ts) 第 285–297 行

```ts
public getNormalizedBoneNode(name: VRMHumanBoneName): THREE.Object3D | null
public update(): void {
  if (this.autoUpdateHumanBones) {     // 默认 true
    this._normalizedHumanBones.update();   // normalized → raw 单向同步
  }
}
```

**写 `normalized` 骨骼，`vrm.update()` 时自动同步到 `raw` 骨骼**。这是官方推荐的工作方式 —— 你只管写 normalized，不用碰 raw。项目第 651–660 行全面使用 `getNormalizedBoneNode`，**写法正确**。

### 3.3 已知坑：normalized 的 **scale** 不参与同步

来源：[issue #1585](https://github.com/pixiv/three-vrm/issues/1585)，官方回复：

> "Just asked the VRM spec team; it seems we should allow change scales of humanoid bones, as long as the change respects the intention of the original author. **We will try to change normalized human bones to transfer its scale changes to the raw bones.**"

即 3.5.5 中 normalized human bone 的 **scale** 变更**不会**传到 raw bone（rotation/translation 会）。**对本项目的意义**：项目做的 squash & stretch 是在 `vrm.scene.scale`（场景根）上做的，**不受此坑影响**——这是个正确的选择，继续保持。

### 3.4 对本项目的建议

| 场景 | 推荐 | 理由 |
|---|---|---|
| 待机微动作（呼吸/歪头/重心） | **直接写 `getNormalizedBoneNode().rotation`**（现状） | 骨骼数少、需逐帧程序化计算，官方示例就是这路子 |
| 拖动反应（腿摆动/收腿） | **直接写 rotation**（现状） | 同上；且需要和拖动量实时耦合，动画剪辑反而难做 |
| 未来要播 .vrma 动作文件 | `createVRMAnimationClip` + Mixer | 唯一官方路径 |
| 未来要叠加二者 | Mixer 先、程序化叠加后 | 见 discussion #1547 的顺序建议 |

**可落地性：现状与官方一致，不需要改。** 唯一可优化的是项目已有 `three-vrm-animation.module.js` 却未启用——如果以后要加"被拎起来挣扎"的预制动作，直接用它即可。

---

## 第 4 节 · 抓取 / 拾取反应动画的参考实现

### 4.1 three-vrm 生态：有位移范本（`mouse.html`），无反应姿势资料

14 个官方示例中，**`mouse.html` 做了"鼠标驱动角色"**（改 `hips.position`，见 1.5 节），但**没有任何一个示例做"被抓起来的反应姿势"**。官方文档、`VRMHumanoid` API 里也**没有任何 IK 能力** —— `three-vrm` 只提供骨骼访问和姿态读写，不提供求解器。维护者 0b5vr 在 [discussion #1145](https://github.com/pixiv/three-vrm/discussions/1145) 明确表示：**"We don't provide any Humanoid IK systems for now."**

补充（子代理核实）：`three-vrm-ik` / `@vrm/ik` 这两个 npm 包**不存在**（registry 返回 404）；`three-ik` 停更于 2022 年，不建议用于生产。

### 4.2 社区最接近的三条路

**路线 1：VRChat 的 Pickup / PhysBone Grab（概念可借鉴，代码不可移植）**

VRChat SDK 的 `VRC_Pickup` 组件与 PhysBone 的 `Allow Grabbing` / `Grab Movement` 参数，处理"手抓住头发/衣服"的物理反应。**对本项目的价值**：它明确区分了两种抓取语义 —— 抓**身体**（整体位移）与抓**弹簧骨**（局部拉伸）。本项目属于前者，因此**不需要**给 springBone 加任何"被抓"逻辑；抓住腰 → 整体位移 → 头发靠自身惯性甩动，这个物理链路是对的。

⚠️ **两条重要的否定性事实**（子代理从 VRChat 官方文档逐字核对）：
- **VRChat 明令禁止把 Humanoid 骨骼（hips/spine/chest）设为 PhysBone Root**，原文 "**Do not set Humanoid bones as PhysBone Root bones.** ... **This will cause major issues.**" → "把 hips 挂 PhysBone、一拉整个人被带起来"在 VRChat 里是**官方列明的错误做法**。
- `VRC_Pickup` 是 **world component**，**不作用于 avatar**；不存在 `AvatarPickup` 组件。"把玩家抓起来"靠社区自制的 Player Pickup prefab（非官方，作者自述用了 "11 animator layers"）。

**→ 对本项目：我们不在 VRChat 生态里，直接用 `vrm.scene.position` / `hips.position` 反而比 VRChat 的约束更自由。此条只作认知参考。**

**路线 2："被提起来"的姿态设计（艺术指导层面，非代码）**

社区（VRChat / UniVRM 表演动画）对"被拎起来"的通行做法，与项目第 786–838 行的实现**高度一致**：

- 上身基本不动（因为被抓点就在腰/腋下）；
- 腿是主要表演部位 —— 大腿摆、小腿回收、**脚尖下垂（脚背绷直）**；
- 手臂自然垂在身侧、滞后于腿；
- 轻微的 squash & stretch。

项目第 825–829 行"脚背绷直下垂"的注释（"悬空时脚尖朝下是被提着的强提示"）**正是社区共识**。

**路线 3：⭐ 现成手感参数（强烈建议直接抄）**（子代理从开源实现源码提取）

| 来源 | 参数 | 用途 |
|---|---|---|
| shimeji `Dragged.java` | `footDx = (footDx + delta * 0.1) * 0.8` | **脚的阻尼式跟随**（弹簧感），可直接对标项目的 `legSwing` 平滑 |
| shimeji `actions.xml` | `RegistanceX=0.05, RegistanceY=0.1, Gravity=2` | 下落手感（⚠️ schema 里就是拼错的 `Registance`） |
| shimeji `Thrown` | 初速度 = `${cursor.dx}` / `${cursor.dy}` | **松手"扔出去"用光标速度作初速**——项目可加此特性 |
| shimeji | `setTimeToRegist(250)`；移动 ≥5px 重置 | 挣扎动画的触发/打断逻辑 |
| Mate-Engine | **`dragLockTimer = 0.30f`** | **松开鼠标后仍保持 0.3s 拖拽姿势**，避免末帧抖动。**强烈建议抄** |
| Mate-Engine | `headYawLimit=45°, headPitchLimit=30°, smoothness=10` | 头部追踪限位 |
| Moeru airi | `isClickLikePointerGesture(start, end, maxDistance = 8)` | 8px 阈值区分"点击"与"拖拽" |

> ⚠️ **诚实声明**：没有任何权威文档给出"被拎起来姿势"的推荐做法，上表是从多个开源实现反推的工程参数，不是官方推荐。

### 4.3 结论（精确区分"有无"）

| 问题 | 官方有资料吗 |
|---|---|
| "角色被抓起来时的**位移写法**" | ✅ **有** —— `mouse.html`（改 `hips.position`） |
| "角色被抓起来时的**反应姿势**" | ❌ **无** —— 14 个示例全无，且官方不提供 IK |
| "VRChat 里怎么实现" | ⚠️ 官方明确**禁止**把 hips 挂 PhysBone，且 `VRC_Pickup` 不作用于 avatar → 此路不通 |
| "现成可抄的开源代码" | ✅ **有一份**：[moeru-ai/airi](https://github.com/moeru-ai/airi)（技术栈完全一致），但**其碰撞盒白名单无 `hips`，抓腰需自补** |

**→ 结论：项目的表演结构（上身稳、腿主导、脚背绷直）方向正确，属于"细节打磨"而非"方向错误"。可抄的是"手感参数"（见 4.2 路线 3）和"命中检测实现"（见 1.6 节），而非整体架构。**

**可落地性：不需要推翻重做。**

---

## 第 5 节 · QtWebEngine 跑 three.js 的已知坑

> 好消息：**项目已经把这些坑全部踩完并解决了**（`web3d_pet.py` 第 28–43 行）。本节主要是**验证现状正确 + 补充两个尚未覆盖的点**。

### 5.1 遮挡节流（本项目的头号坑）—— 已正确解决

项目注释第 32–36 行的实测结论"不加 occluded 标志时页面 rAF 只有 ~0.8 帧/秒"，与 Chromium 的设计完全吻合。

官方依据：Chromium 有 **Windows 专用的原生窗口遮挡检测**（feature 名 `CalculateNativeWinOcclusion`），[官方文档](https://chromium.googlesource.com/chromium/src/+/refs/heads/main/docs/windows_native_window_occlusion_tracking.md) 说明它会"把最小化的 Chromium 窗口标记为 hidden，把位于其他虚拟桌面的窗口标记为 occluded"，并根据虚拟屏幕的 SKRegion 计算未被遮挡区域。桌面宠物是**透明置顶小窗**，极易被判为被遮挡。

[Chromium 官方邮件列表](https://groups.google.com/a/chromium.org/g/chromium-dev/c/9n2v3BkHvO8/m/enJhHTqWAAAJ) 给出的正是 `--disable-backgrounding-occluded-windows`，与项目采用的一致。

**当前 flags（第 37–43 行）逐条核对**：

```python
os.environ.setdefault(
    "QTWEBENGINE_CHROMIUM_FLAGS",
    "--ignore-gpu-blocklist --enable-gpu-rasterization --enable-unsafe-swiftshader "
    "--disable-frame-rate-limit --disable-gpu-vsync "
    "--disable-backgrounding-occluded-windows --disable-renderer-backgrounding "
    "--disable-background-timer-throttling",
)
```

| Flag | 作用 | 评价 |
|---|---|---|
| `--disable-backgrounding-occluded-windows` | 关掉遮挡判定 | ✅ 必需，项目实测关键 |
| `--disable-renderer-backgrounding` | 关掉渲染进程降级 | ✅ 必需 |
| `--disable-background-timer-throttling` | 关掉后台定时器 1s 节流 | ✅ 必需（项目用 `setTimeout` 自驱动，**离了它必挂**） |
| `--disable-frame-rate-limit` + `--disable-gpu-vsync` | 解锁 vsync 与帧率上限 | ✅ 实现 120fps 的前提 |
| `--ignore-gpu-blocklist` | 忽略 GPU 黑名单 | ✅ 防软件渲染回退 |
| `--enable-gpu-rasterization` | GPU 光栅化 | ✅ |
| `--enable-unsafe-swiftshader` | 允许 SwiftShader 兜底 | ⚠️ 见 5.3 |

官方文档：[Qt WebEngine Debugging and Profiling](https://doc.qt.io/qt-6/qtwebengine-debugging.html) 确认 `QTWEBENGINE_CHROMIUM_FLAGS` 是传 Chromium 参数的正规入口；[Qt WebEngine Platform Notes](https://doc.qt.io/qt-6.11/qtwebengine-platform-notes.html) 是平台差异的权威参考。

### 5.2 补充建议 ①：⚠️ 已更正 —— 加 `page().setVisible(True)`，不是加 flag

> **本节初版建议"加 `--disable-features=CalculateNativeWinOcclusion` 更彻底"，经第二轮实测后判定收益不确定（子代理实测遮挡根本不节流）。真正该做的是下面这条。**

**🔴 真正的隐患在"窗口被 hide"而非"被遮挡"。** 实测（见文末补充 A）：

| 配置 | 隐藏窗口时 setTimeout 链 |
|---|---|
| 项目当前 flags | **230/2s（全速，安全）**✅ |
| 无 flags | 12/2s（≈6fps）⚠️ |

项目**当前是安全的**（因为用的是 setTimeout 而非 rAF，恰好被 flags 保住），但**一旦加"隐藏到托盘"功能就会暴露**。防御性加固：

```python
# web3d_pet.py：QWebEngineView 创建后立刻调用
self.view.page().setVisible(True)
```

官方依据：[QTBUG-120625](https://bugreports.qt.io/browse/QTBUG-120625)，Qt 开发者 Anu Aliyas 亲自给出此解法。**实测 `QWebEnginePage.setVisible` 在 PyQt6/Qt 6.11.0 存在。**

⚠️ `setLifecycleState(Active)` **不能**替代它（报告者明确说他设了 active 仍被节流）。

**可落地性：能直接抄，1 行。**

### 5.3 补充建议 ②：确认没有掉进软件渲染

`--enable-unsafe-swiftshader` 是**兜底**：一旦 GPU 初始化失败，它会静默用 SwiftShader 软件渲染，帧率暴跌但**不报错**。

项目已经写了诊断接口 `window.__gpuInfo()`（第 631–641 行），它读 `WEBGL_debug_renderer_info` 的 `UNMASKED_RENDERER_WEBGL`。

**建议加一条自动告警**：启动时检查 renderer 字符串，若包含 `SwiftShader` / `Software` / `llvmpipe` 就 `console.error` 并在 Python 侧弹托盘提示：

```js
const info = JSON.parse(window.__gpuInfo());
if (/SwiftShader|Software|llvmpipe|Microsoft Basic/i.test(info.renderer)) {
  console.error('[GPU] 掉进软件渲染！renderer=' + info.renderer);  // 帧率必然崩
}
```

**可落地性：能直接抄，5 行。**

### 5.4 补充建议 ③：高 DPI 下的 `setPixelRatio` 上限

项目第 60 行 `renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2))` —— **上限 2 是对的选择**。Windows 上 4K 屏 + 200% 缩放下 `devicePixelRatio` 可达 2~3，若不做上限，像素量按平方增长，209 个关节的蒙皮 + 984 个 morph target 会直接压垮 120fps 目标。

**可落地性：保持现状。** 如需进一步压帧，这是第一个该降的旋钮（改成 `1.5` 或 `1`）。

### 5.5 🟢 鼠标事件收不到：**官方有正规入口 `focusProxy()`**（第五节最重要的更正）

> **初版结论"官方无 API 拦截，轮询是唯一解"是错的。** 第二轮调研找到官方 issue 与解法，并经**我本机实测复现验证**（详见文末补充 B）。

**官方定性**（[QTBUG-43602](https://bugreports.qt.io/browse/QTBUG-43602)）：鼠标事件被 `QWebEngineView` 的**内部子控件**吞掉，这是框架设计限制。官方给出的入口是 **`focusProxy()`**：

> "**Using `focusProxy()` is probably better** ... **We set the delegate as focus proxy for the view.**" —— Qt 开发者 Allan Jensen

**我的实测结果**：

| 挂载点 | 收到的鼠标事件 |
|---|---|
| `QWebEngineView` 上 | **无**（只有 ChildAdded/Hide/WinIdChange 等窗口事件）—— 复现了项目现象 |
| **`focusProxy()` 上** | ✅ **`MouseButtonPress` / `MouseMove` / `MouseButtonRelease`** |

**🔴 关键：`focusProxy()` 在 `loadFinished` 之前是 `None`**（我实测：构造后 `None`，加载后才变成 `QWidget`）。这极可能就是项目当初"eventFilter 无效"的隐藏原因——在 `__init__` 里取到 `None`，`installEventFilter` 静默失败。

**结论**：项目改用 `GetAsyncKeyState` 全局轮询虽能工作，但**属于绕路**。官方正规做法（挂 `focusProxy()`）已被验证可行，**可以去掉那套 hack**，架构会更干净。

⚠️ **诚实标注**：我用**合成事件**验证成功；**真实硬件点击未测**。且发现 `app.sendEvent(view, ...)` 会导致进程崩溃（0xC0000409），必须 `sendEvent(focusProxy)`。**建议接入手工点几下确认后再移除轮询。**

**可落地性：需实测确认后改造**（详见文末补充 B 的完整代码）。

### 5.6 透明背景的已知渲染问题

搜到一个相关社区报告：[Qt Forum — Changing CSS to achieve a transparent background breaks rendering](https://forum.qt.io/topic/162799/changing-css-to-achieve-a-transparent-background-breaks-rendering)，现象是 QtWebEngine 6.3.0+ 在透明背景下渲染异常（该帖报告 Qt 6.8.1 + WebEngine 6.2.3 不复现）。

本项目用 `WA_TranslucentBackground` + `WA_NoSystemBackground`（第 233–234 行）+ three.js `alpha: true`（第 58 行），属于该风险区。**建议记录当前 PyQt6/QtWebEngine 的精确版本**，避免未来升级踩坑。

---

## 差距清单：我们当前实现 vs 官方推荐

图例：🟢 已达标（保持） / 🟡 建议改造 / 🔴 认知错误需修正

| # | 项目 | 当前实现 | 官方/规范推荐 | 判定 | 优先级 |
|---|---|---|---|---|---|
| 1 | **springBone `center`** | 未设置（模型 0/39 链有 center） | 规范 Center Space：模型整体移动导致狂抖时应设 `center`。逐 joint 设 `joint.center`，然后 `manager.setInitState()` | 🟡 **最大缺口** | **高** |
| 2 | **注释认知：参数来源** | 第 432 行注释"参数是原作者调的，质量最好" | 实测 209 个 joint 全为 Blender 导出默认值（1.0/0.0/0.5/0.0），非调优 | 🔴 事实错误 | **高**（会阻碍后续调参） |
| 3 | **物理参数调优** | 全部沿用默认值，从未按链区分 | 规范不给推荐值（官方无此资料）；应按链区分：裙摆宜软（stiffness↓）、发带宜飘（dragForce↓）、耳环宜硬（stiffness↑、gravityPower↑） | 🟡 未开发领域 | 中 |
| 4 | **旋转补偿数学** | 绕 `C=(0,0.93,0)`，`dx=Cy·sinθ, dy=Cy·(1−cosθ)` | 无官方规定；我独立推导验证**结果一致** | 🟢 正确 | — |
| 5 | **`position` 写法** | 绝对赋值（`= dragOffsetX/Y`） | 无官方规定，但绝对赋值是社区稳妥做法；项目已实测避开累加漂移 | 🟢 正确 | — |
| 6 | **更新顺序** | 写骨骼/position（662–858）→ `vrm.update`（886）→ render（890） | 规范 Calculation order + `VRMSpringBoneManager.update()` 会刷新祖先矩阵 → **父级变换必须先写完** | 🟢 正确，但**建议加防御性注释** | 低 |
| 7 | **骨骼动画写法** | 直接用 `getNormalizedBoneNode().rotation` | 官方 `animations.html` 同路子；normalized→raw 由 `autoUpdateHumanBones` 自动同步 | 🟢 正确 | — |
| 8 | **squash & stretch 位置** | 在 `vrm.scene.scale`（根）上做 | issue #1585：normalized human bone 的 **scale 不同步**到 raw；在根节点做**恰好避开此坑** | 🟢 正确（意外正确） | — |
| 9 | **`vrm.update(delta)` 单位** | `Math.min(clock.getDelta(), 0.05)` 秒 | 官方要求 delta 单位是**秒**，过大则物理爆炸 | 🟢 正确（且有 clamp） | — |
| 10 | **QtWebEngine 节流 flags** | 7 个 flag，含 occluded / renderer-backgrounding / timer-throttling | 与 Chromium 官方（`CalculateNativeWinOcclusion`）及 Qt 文档一致 | 🟢 正确（实测有效） | — |
| 11 | **禁用原生遮挡检测** | 仅关"因遮挡降级" | 可加 `--disable-features=CalculateNativeWinOcclusion` 更彻底 | 🟡 可选优化 | 低 |
| 12 | **软件渲染兜底检测** | 有 `__gpuInfo()` 但无告警 | 建议匹配 `SwiftShader\|Software\|llvmpipe` 并报错 | 🟡 5 行可加 | 低 |
| 13 | **鼠标事件** | Win32 全局轮询（16ms） | 🟢 **官方有正规入口**：`focusProxy()` 能收到鼠标事件（我实测复现）。可去掉轮询 | **🟡 可升级**（架构更干净） | 中 |
| 14 | **帧率与物理耦合** | `TARGET_FPS = 120` | `VRMSpringBoneJoint.update()` 惯性项 `(currentTail−prevTail)×(1−dragForce)` **未乘 delta**（源码 246 行），物理**非严格帧率无关** | 🟡 **值得实测**：60 vs 120 对比 | 中 |
| 15 | **抓取反应动画** | 自研（上身稳、腿摆、脚背绷直、squash&stretch） | 官方有位移范本 `mouse.html`，但**无反应姿势资料**；社区表演共识与项目一致 | 🟢 方向正确 | — |
| 16 | **高 DPI** | `setPixelRatio(min(dpr, 2))` | 官方 examples 全都不设上限；加上限是合理工程选择。⚠️ 勿动 `setZoomFactor`（与 DPI 相乘） | 🟢 合理 | — |
| 17 | **隐藏窗口渲染循环** | 托盘无"隐藏"项，窗口从不 hide | 实测：隐藏时若只靠 rAF 会掉到 0；**项目用 setTimeout + flags 恰好安全**。但建议加 `page().setVisible(True)` 防御 | 🟡 **1 行防御性加固** | 中 |
| 18 | **命中检测（抓腰）** | 自研 `ray.intersectObject(vrm.scene, true)`（第 517 行） | airi 用"挂骨骼的不可见 Box3"更精确且便宜；其白名单**无 hips**，需自补 | 🟡 可选优化 | 低 |
| 19 | **位移层级选择** | `vrm.scene.position`（整根平移） | 官方 `mouse.html` 用 `hips.position`；两者对 springBone 影响不同。桌宠场景用 scene 合理 | 🟢 保持（见 2.5 节） | — |

### 关于第 14 项的说明（唯一需要实测的物理疑点）

`VRMSpringBoneJoint.ts` 第 246 行：

```ts
.add(_v3A.subVectors(this._currentTail, this._prevTail).multiplyScalar(1 - this.settings.dragForce))
```

惯性项是**上一帧的位移**（隐式速度），**没有乘 `delta`**；而刚性项和重力项都乘了 `delta`（第 250–251 行）。这意味着惯性贡献随帧率变化 —— 120fps 下每帧位移是 60fps 的一半，惯性项也随之减半。

**这不是 bug，是 Verlet 积分的固有性质**，但它意味着"在编辑器/其他工具里 60fps 调好的手感，搬到本项目 120fps 下会不一样"。

**已有现成验证手段**（`verify_phys.py` 第 87–107 行的"身体运动时物理必须跟着动"）：

```python
js("window.__resetPhysProbe(); 'ok'")
js("window.__hairDelta()")          # 记录基准
js("window.setDragging(true, 0); 'ok'")
# ... 左右摆动几次 ...
moved = js("window.__hairDelta()")  # 读 maxAngle
```

把 `window.setTargetFps(60)` 和 `120` 各跑一遍，比较 `maxAngle` 即可量化帧率敏感度。项目已有 `window.__targetFps()` / `setTargetFps` 接口（第 1042 行），改造成本几乎为零。

---

## 落地路线建议（按性价比排序，已按第二轮结论更新）

1. **【先做·零风险】修正 `pet_viewer.html:432` 的错误注释** —— 实测证明参数是 Blender 导出默认值，"参数是原作者调的、质量最好"不成立。不改这条，后面所有调参决策都建立在错误前提上。
2. **【最高收益】给 springBone 加 `center`** —— 约 12 行，带开关。规范唯一背书的改造，解决"整体位移污染物理空间"这个本项目最本质的问题。用 `verify_phys.py` 第 2 项（静止 `maxAngle < 0.08`）A/B 验证。
3. **【1 行·防御】`page().setVisible(True)`** —— 当前托盘无"隐藏"项所以安全，但加这一行可防未来加"隐藏到托盘"时渲染循环从 120fps 掉到 6fps。
4. **【中收益·需实测】用 `focusProxy()` 替掉 `GetAsyncKeyState` 全局轮询** —— 我实测可行（合成事件），可让架构回归官方正规路径。**务必先手工点击验证真实事件**，通过后再移除轮询。
5. **【实测】帧率敏感性量化** —— 用现成的 `__hairDelta()` + `setTargetFps` 跑 60/120 对比。
6. **【打磨】按链调参** —— 有了 1 和 2 之后再做。建议分三组：裙摆（20 条）、发带/马尾/耳环（5 条）、披风/衣摆（其余）。先动 `dragForce`（最直观），再动 `stiffness`。
7. **【可直接抄的手感增强】** —— Mate-Engine 的 `dragLockTimer = 0.30f`（松手后保持 0.3s 拖拽姿势，消除末帧抖动）；shimeji 的"松手用光标速度作初速"（可做"扔出去"效果）。
8. **【可选·低优先】SwiftShader 告警 + 核对 GL 版本** —— 本项目每次运行都有 `Failed to create GLES3 context, fallback to GLES2` 警告，建议用 `chrome://gpu`（配 `QTWEBENGINE_REMOTE_DEBUGGING=9222`）确认 three.js r170 的 WebGL2 要求是否满足。

---

## 附：本次调研产出的可复用资产

| 路径 | 内容 |
|---|---|
| `strinova-desktop-pet/tools/pmx_to_vrm/dump_springbone.py` | **新工具**。解析任意 .vrm 的 VRMC_springBone 全参数分布 + humanoid 骨骼清单。调参前必跑的体检工具。 |
| `vrm_research_official/src/VRM.ts` | three-vrm v3.5.5 官方源码（`update` 顺序） |
| `vrm_research_official/src/VRMSpringBoneManager.ts` | 官方源码（祖先矩阵刷新、`setInitState`/`reset`） |
| `vrm_research_official/src/VRMSpringBoneJoint.ts` | 官方源码（三力公式、`center` setter） |
| `vrm_research_official/src/Matrix4InverseCache.ts` | 官方源码（center 逆矩阵缓存，说明性能可接受） |
| `vrm_research_official/src/VRMSpringBoneLoaderPlugin.ts` | 官方源码（`setInitState()` 在加载末尾调用） |
| `vrm_research_official/src/VRMHumanoid.ts` | 官方源码（`autoUpdateHumanBones` 同步机制） |
| `vrm_research_official/src/createVRMAnimationClip.ts` | 官方源码（.vrma 播放路径） |
| `vrm_research_official/mouse.html` | **官方"鼠标拖动角色"范本**（改 `hips.position`） |
| `vrm_research_official/dnd.html` / `webgpu-dnd.html` / `animations.html` / `anim_dnd.html` | 官方示例（证实 dnd = 拖文件，非拖角色） |
| `vrm_research_official/verify_hidden_loop.py` | **新实测脚本**。对比 rAF/setInterval/setTimeout 在隐藏窗口下的节流，含 flags 与 `page.setVisible` 对照 |
| `vrm_research_official/verify_focusproxy2.py` | **新实测脚本**。证明 `focusProxy()` 能收到鼠标事件而 view 不能 |

---

# 第二轮补充 · 本机实测（Qt 6.11.0 / PyQt6，Windows 11）

> 本节所有数据均为**我在本机实跑**得到，脚本已留档（见上表），可复现。

## 补充 A · 🔴 隐藏窗口节流：`page().setVisible(True)` 才是解法

### 官方依据：QTBUG-120625

来源：[QTBUG-120625 — QWebEngineView slows down when hidden](https://bugreports.qt.io/browse/QTBUG-120625)

Qt 开发者 **Anu Aliyas**（2024-01-10）回复原文：

> "This is due to **JavaScript timer throttling on hidden pages in the Chromium codebase**. ... Could you please **add `view->page()->setVisible(true)`** in makeView() and verify the results"

报告者次日确认：**"Your suggestion actually works."**

### 我的实测数据（`verify_hidden_loop.py`）

**无 chromium flags**：

| 场景 | rAF /2s | setInterval(8ms) /2s | **setTimeout 链 /2s** |
|---|---|---|---|
| 窗口可见 | 121 | 252 | **230** |
| `hide()` 隐藏 | **0** ⚠️ | 12 | **12** ⚠️ |
| 隐藏 + `page.setVisible(True)` | 121 ✅ | 252 | **232** ✅ |

**有项目当前的 chromium flags**：

| 场景 | rAF /2s | setInterval /2s | **setTimeout 链 /2s** |
|---|---|---|---|
| 窗口可见 | 114 | 250 | **229** |
| `hide()` 隐藏 | **0** ⚠️ | 249 ✅ | **230** ✅ |
| 隐藏 + `page.setVisible(True)` | 113 ✅ | 250 | **229** ✅ |

### 🎯 结论（对你项目最重要的两条）

1. **chromium flags 能救 `setInterval` 和 `setTimeout`，但救不了 `requestAnimationFrame`**（rAF 恒为 0）。
2. **🔴 但你的项目恰好是安全的**：`pet_viewer.html` **完全不用 rAF/setInterval**，是纯 `setTimeout` 链自驱（这正是"坑3"注释里"用 setTimeout 不用 setAnimationLoop"的决定）。实测证明**这个选择顺带避开了隐藏节流**——因为 flags 保住了 setTimeout。
3. **隐患仍在**：目前托盘菜单**没有"隐藏桌宠"项**（`web3d_pet.py:544-588` 已核对），窗口从不 `hide()`，所以问题不暴露。**一旦将来加"隐藏/最小化到托盘"，若不处理，渲染循环会从 230/2s 掉到 12/2s（约 120fps → 6fps）。**

### ✅ 建议：现在就加这一行（防御性，零成本）

```python
# web3d_pet.py，QWebEngineView 创建之后
self.view.page().setVisible(True)
```

**实测确认 `QWebEnginePage.setVisible` 在 PyQt6 / Qt 6.11.0 存在**：
```
QWebEnginePage 有 setVisible : True
QWebEnginePage 有 isVisible  : True
```

> ⚠️ 注意：`setLifecycleState(Active)` **不能**替代 `setVisible(True)` —— QTBUG-120625 报告者明确说他已设 lifecycle=active 但仍被节流。

**可落地性：能直接抄，1 行。**

### 补充 A2 · 关于 `--disable-features=CalculateNativeWinOcclusion`（我初版建议的更正）

子代理实测：**窗口被全屏窗口遮挡时 rAF 仍为 120/2s，不节流**，加不加该 flag 无差异。

**可能原因【推测】**：`CalculateNativeWinOcclusion` 在 QtWebEngine 里可能未启用，或只对 Chrome 自身窗口生效。

**判定**：我初版"加 `--disable-features=CalculateNativeWinOcclusion` 更彻底"的建议**收益不确定**。属于"加了没坏处但别指望它"。**优先级下调为可选**。

---

## 补充 B · 🟢 `focusProxy()` 能收到鼠标事件 —— 可去掉全局轮询 hack

### 官方依据

来源：[QTBUG-60701 — QWebEngineView not send to eventFilter QEvent::MouseMove](https://bugreports.qt.io/browse/QTBUG-60701)（标题与项目现象一字不差）

Qt 开发者 jturcotte（[QTBUG-43602](https://bugreports.qt.io/browse/QTBUG-43602)）：

> "**Mouse events are caught by a child QWidget of the QWebEngineView, and not by the QWebEngineView itself. This is a limitation of the current QtWebEngine design.**"

官方正解由 Allan Jensen 给出：
> "**Using `focusProxy()` is probably better** ... **We set the delegate as focus proxy for the view.**"

源码确证：[qtwebengine `qwebengineview.cpp`](https://github.com/qt/qtwebengine/blob/dev/src/webenginewidgets/api/qwebengineview.cpp) 第 461 行 `q->setFocusProxy(newWidget);`

### 我的实测（`verify_focusproxy2.py`）

```
构造后 focusProxy = None                       ← ★ 这就是项目"eventFilter 无效"的隐藏原因
loadFinished 后 focusProxy = QWidget

=== 结果 ===
  on_view      : ['ChildAdded', 'Hide', 'PlatformSurface', 'WinIdChange', ...]  ← 全是窗口/布局事件，无鼠标
  on_focusProxy: ['MouseButtonPress', 'MouseMove', 'MouseButtonRelease', ...]   ← ✅ 收到鼠标事件
```

**完整复现了项目的现象，并验证了解法。**

### ✅ 可落地实现

```python
class PetWebView(QWebEngineView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._proxy_filter = None          # ★ 必须保持强引用，否则被 GC 静默失效
        self.page().setVisible(True)       # 补充 A 的解法
        self.loadFinished.connect(self._attach_filter)

    def _attach_filter(self, ok):
        fp = self.focusProxy()
        if fp is None:
            QTimer.singleShot(50, lambda: self._attach_filter(ok))   # 兜底重试
            return
        if self._proxy_filter is not None:
            return
        self._proxy_filter = _DelegateMouseFilter(self)
        fp.installEventFilter(self._proxy_filter)
```

**三个必须注意**：
1. **必须在 `loadFinished` 之后取 `focusProxy()`** —— 构造后是 `None`（实测），`None.installEventFilter()` 会静默失败。
2. **过滤器对象必须保持强引用**（存成 `self._xxx`），否则 Python GC 回收后过滤器静默失效。
3. `eventFilter` 里 **return `False`**，让事件继续传给 Chromium。

**⚠️ 诚实标注**：子代理报告"挂 `focusProxy()` 能收到事件"，我**独立复现并确认**。但**"能否收到真实硬件鼠标事件"我只用合成事件验证**（真实点击未测），且 **`QMouseEvent` 直接 `sendEvent(view)` 会导致进程崩溃（0xC0000409）** —— 说明往 QWebEngineView 路径投递合成事件不安全，改用 `sendEvent(fp)` 才行。**建议实际接入手工点几下确认。**

**可落地性：需实测确认后改造。** 若成立，可**去掉 `GetAsyncKeyState` 全局轮询**（第 415–438 行），改由 Qt 事件驱动，架构更干净。

**替代架构（更简洁）**：拖拽逻辑全写在 JS 里（`pointerdown`/`pointermove` + `canvas.setPointerCapture()`），Python 只通过 QWebChannel 移动原生窗口。`setPointerCapture` 还能实现"鼠标移出窗口仍继续拖"，这是原生事件转发难做到的。

---

## 补充 C · 其他实测/证据（子代理产出，未逐条复现，标注来源）

以下来自子代理实测与官方 API 核对，**我未逐条复现**，引用时请知悉：

| 结论 | 来源 |
|---|---|
| Qt 6.10 起软件渲染模式下 WebGL 完全不可用（官方答"已从代码中移除"） | [QTBUG-124887](https://bugreports.qt.io/browse/QTBUG-124887) |
| Windows 上 QtWebEngine 只拿到 GLES2，`--ignore-gpu-blocklist` 对升级 ES3 无效 | [QTBUG-143828](https://bugreports.qt.io/browse/QTBUG-143828) |
| 本机每次运行都有 `Failed to create GLES3 context, fallback to GLES2` | 我本机也观察到同样的 stderr 警告 ✅ |
| `zoomFactor` 与 DPI 相乘（`setZoomFactor(2.0)` → JS `devicePixelRatio`=2） | 子代理实测 |
| `page.setVisible` 的解法在隐藏窗口恢复 120/2s | 我独立复现 ✅ |
| 遮挡不节流 | 子代理实测（与我"flags 保留 setTimeout"的结论不冲突） |

**→ 建议用 `chrome://gpu` 核对本项目 QtWebEngine 实际拿到的 GL 版本**（配 `QTWEBENGINE_REMOTE_DEBUGGING=9222`），确认 three.js r170 的 WebGL2 要求是否满足。

---

## 官方资料索引

**规范**
- [VRMC_springBone 1.0 规范](https://github.com/vrm-c/vrm-specification/blob/master/specification/VRMC_springBone-1.0/README.md)
- [VRMC_vrm 1.0 规范](https://github.com/vrm-c/vrm-specification/blob/master/specification/VRMC_vrm-1.0/README.md)

**three-vrm 源码（v3.5.5）**
- [VRM.ts](https://github.com/pixiv/three-vrm/blob/v3.5.5/packages/three-vrm/src/VRM.ts)
- [VRMSpringBoneManager.ts](https://github.com/pixiv/three-vrm/blob/v3.5.5/packages/three-vrm-springbone/src/VRMSpringBoneManager.ts)
- [VRMSpringBoneJoint.ts](https://github.com/pixiv/three-vrm/blob/v3.5.5/packages/three-vrm-springbone/src/VRMSpringBoneJoint.ts)
- [VRMSpringBoneLoaderPlugin.ts](https://github.com/pixiv/three-vrm/blob/v3.5.5/packages/three-vrm-springbone/src/VRMSpringBoneLoaderPlugin.ts)
- [VRMHumanoid.ts](https://github.com/pixiv/three-vrm/blob/v3.5.5/packages/three-vrm-core/src/humanoid/VRMHumanoid.ts)
- [createVRMAnimationClip.ts](https://github.com/pixiv/three-vrm/blob/v3.5.5/packages/three-vrm-animation/src/createVRMAnimationClip.ts)

**API 文档**
- [VRMSpringBoneManager](https://pixiv.github.io/three-vrm/docs/classes/three-vrm-springbone.VRMSpringBoneManager.html)
- [VRMHumanoid](https://pixiv.github.io/three-vrm/docs/classes/three-vrm.VRMHumanoid.html)
- [SpringBoneJoint（schema 类型）](https://pixiv.github.io/three-vrm/docs/interfaces/types-vrmc-springbone-1.0.SpringBoneJoint.html)

**示例**
- [three-vrm 示例总览](https://pixiv.github.io/three-vrm/packages/three-vrm/examples/)
- [three-vrm-animation 示例](https://pixiv.github.io/three-vrm/packages/three-vrm-animation/examples/)
- [**mouse.html（官方"鼠标拖角色"范本，改 hips.position）**](https://github.com/pixiv/three-vrm/blob/dev/packages/three-vrm/examples/mouse.html)
- [animations.html](https://github.com/pixiv/three-vrm/blob/dev/packages/three-vrm/examples/animations.html)
- [官方 examples 索引（14 个 HTML）](https://raw.githubusercontent.com/pixiv/three-vrm/dev/packages/three-vrm/examples/index.html)

**Issue / Discussion**
- [#1502 proper animation procedures with mixer](https://github.com/pixiv/three-vrm/issues/1502) — 更新顺序
- [#1547 Bone animation with normalized bones and raw bones](https://github.com/pixiv/three-vrm/discussions/1547) — 顺序讨论
- [**#1145 官方声明不提供 IK**](https://github.com/pixiv/three-vrm/discussions/1145) — "We don't provide any Humanoid IK systems for now."
- [#1112 setCenter 在新版是否还在](https://github.com/pixiv/three-vrm/issues/1112) — center 无批量 API
- [#1585 Normalized bones don't sync all transforms to raw bones](https://github.com/pixiv/three-vrm/issues/1585) — scale 不同步

**社区实现（可抄）**
- [moeru-ai/airi interaction.ts](https://github.com/moeru-ai/airi/blob/a42e3ae0/packages/stage-ui-three/src/composables/vrm/interaction.ts) — **技术栈与本项目完全一致**，骨骼碰撞盒 + raycast
- [shinyflvre/Mate-Engine](https://github.com/shinyflvre/Mate-Engine) — 拖拽状态机 + `dragLockTimer = 0.30f` 拖拽锁
- [TigerHix/shimeji-ee actions.xml](https://github.com/TigerHix/shimeji-ee/blob/master/conf/actions.xml) — 拖拽手感参数（`footDx=(footDx+delta*0.1)*0.8`、`Thrown` 用光标速度作初速）
- [not-elm/desktop_homunculus](https://github.com/not-elm/desktop_homunculus) — Bevy+VRM 桌宠；README 警告 Windows/NVIDIA 透明窗口需先配 NVIDIA 控制面板否则黑底

**QtWebEngine**
- [QTBUG-120625 隐藏窗口节流](https://bugreports.qt.io/browse/QTBUG-120625) — **官方解法 `page.setVisible(true)`**
- [QTBUG-43602 鼠标事件被内部子控件吞掉](https://bugreports.qt.io/browse/QTBUG-43602) — **`focusProxy()` 解法**
- [QTBUG-60701 eventFilter 收不到 MouseMove](https://bugreports.qt.io/browse/QTBUG-60701) — 与本项目现象一字不差
- [QTBUG-124887 Qt 6.10 起软件 WebGL 不可用](https://bugreports.qt.io/browse/QTBUG-124887)
- [QTBUG-143828 Windows 上只有 GLES2](https://bugreports.qt.io/browse/QTBUG-143828)
- [qtwebengine qwebengineview.cpp（L461 setFocusProxy）](https://github.com/qt/qtwebengine/blob/dev/src/webenginewidgets/api/qwebengineview.cpp)
- [Qt WebEngine Debugging and Profiling](https://doc.qt.io/qt-6/qtwebengine-debugging.html)
- [Qt WebEngine Platform Notes](https://doc.qt.io/qt-6.11/qtwebengine-platform-notes.html)
- [Chromium Windows Native Window Occlusion Tracking](https://chromium.googlesource.com/chromium/src/+/refs/heads/main/docs/windows_native_window_occlusion_tracking.md)

---

## 诚实声明 · 未核实事项

1. **`--disable-backgrounding-occluded-windows` 的实际收益**：子代理实测遮挡不节流（单机单环境），依赖窗口管理器行为。我实测确认它**保住了 setTimeout**（这是它对本项目的真实价值）。
2. **`focusProxy()` 能否收到真实硬件鼠标事件**：我用**合成事件**验证成功，真实点击未测。且 `sendEvent(view)` 会崩溃（0xC0000409），必须 `sendEvent(focusProxy)`。
3. **three r170 的 `CCDIKSolver.update()` 是否接受 `blendFactor`**：0.169 无、dev 有，r170 需实测。
4. **three-vrm 3.5.5 的 `autoUpdateHumanBones` 默认值**：我核对了 v3.5.5 tag 源码为 `?? true` ✅（已确认）。
5. **`desktop_homunculus` / `shimeji-rs` 的拖拽实现细节**：未核实。
6. **"被拎起来姿势的推荐排序"**：**无任何权威来源**，社区共识是从多个开源实现反推的。
7. **本机 QtWebEngine 实际 GL 版本**：每次运行都有 `Failed to create GLES3 context, fallback to GLES2` 警告，建议用 `chrome://gpu` 核对。
8. **QTBUG-121493（WebEngine 透明背景）**：描述字段为空，只能确认它是 Open 状态。
