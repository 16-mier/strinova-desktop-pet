// vrm_morphs.js —— 表情驱动（CPU 顶点烘焙实现）
//
// ============================ 为什么不用 GPU morph ============================
// three.js r151+ 把 morph target 存进 DataArrayTexture 由顶点着色器采样。
// 在 QtWebEngine（Chromium 内嵌）里实测【完全不生效】，逐项验证如下：
//     ① 直接改 geometry.attributes.position          → 画面变化 ✅
//     ② 设 mesh.morphTargetInfluences = 1.0          → 画面零变化 ❌
//     ③ 用 expressionManager.setValue()              → 画面零变化 ❌
//     ④ 自己新建一个带 morph 的立方体做对照            → 画面零变化 ❌
//     ⑤ combineMorphs() 合并后重试                    → 画面零变化 ❌
//   第 ④ 条最关键：连自己造的简单几何体 morph 都无效，说明这是
//   QtWebEngine 环境下 three.js 纹理化 morph 的兼容性问题，
//   与模型数据、我的转换器都无关。
//
// ============================ 本模块的做法 ============================
//   表情位移本质就是「顶点位置增量」，直接跳过 GPU，在 CPU 上算：
//     ① 加载时把每个 mesh 的原始顶点存一份 base
//     ② 从 VRM 定义读出「表情 -> (targetIndex, weight)」
//     ③ 表情变化时重算：position = base + Σ(weight_i × delta_i)
//     ④ 标记 needsUpdate，交给 three 上传
//   实测 23,414 顶点、切换一次约 0.3~0.8ms，且只在表情变化时计算
//   （不是每帧），性能完全够用。
//
// ============================ 好处 ============================
//   * 不依赖任何 GPU 特性，任何环境都能跑
//   * 与 three-vrm 的 lookAt（走骨骼）互不干扰
//   * 支持多表情任意叠加混合

import * as THREE from 'three';

export class MorphDriver {
  /**
   * @param {object} vrm   three-vrm 的 VRM 实例
   * @param {object} gltf  GLTFLoader 结果（读 userData.gltfExtensions）
   */
  constructor(vrm, gltf) {
    this.vrm = vrm;
    this.meshes = [];       // [{mesh, name, count, base, morphs}]
    this.bindings = {};     // name -> [{index, weight}]
    this.state = {};        // name -> 当前权重
    this._dirty = true;
    this._ready = false;
    this._lastCost = 0;     // 上次 apply 耗时(ms)，用于诊断

    this._collectMeshes();
    this._readExpressions(gltf);
    this._ready = this.names().length > 0;
  }

  /** 收集所有带 morph 的 mesh，并保存原始顶点快照 */
  _collectMeshes() {
    const list = [];
    this.vrm?.scene?.traverse((o) => {
      if (!o.isMesh || !o.geometry) return;
      const pos = o.geometry.attributes?.position;
      if (!pos) return;
      const morphs = o.geometry.morphAttributes?.position;
      if (!morphs || !morphs.length) return;
      list.push({
        mesh: o,
        name: o.name,
        count: pos.count,
        base: Float32Array.from(pos.array),  // ★ 原始顶点（不做表情时的样子）
        morphs: morphs,
      });
    });
    this.meshes = list;
  }

  /**
   * 从 VRM 扩展读表情定义。
   * 注意：米雪儿的 mesh 在 three 里被拆成 24 个 Mesh（每个 glTF primitive 一个），
   * 而 VRM 的 morphTargetBinds.index 在每个 primitive 的 targets 数组里【下标一致】，
   * 所以同一个 index 可以直接套用到所有 mesh。
   */
  _readExpressions(gltf) {
    const ext = gltf?.userData?.gltfExtensions || {};
    const vrmExt = ext.VRMC_vrm || ext.VRM || null;
    const ex = vrmExt?.expressions || {};
    const groups = [ex.preset || {}, ex.custom || {}];

    for (const group of groups) {
      for (const [name, def] of Object.entries(group)) {
        const binds = def?.morphTargetBinds || [];
        const list = [];
        for (const b of binds) {
          const idx = b?.index;
          if (typeof idx !== 'number' || idx < 0) continue;
          list.push({ index: idx, weight: (b.weight == null ? 1 : b.weight) });
        }
        if (list.length) this.bindings[name] = list;
      }
    }
  }

  // ---------------- 查询 ----------------
  names() {
    return Object.keys(this.bindings || {});
  }

  has(name) {
    return Object.prototype.hasOwnProperty.call(this.bindings, name);
  }

  isReady() {
    return this._ready;
  }

  get(name) {
    return this.state[name] || 0;
  }

  // ---------------- 设置 ----------------
  /** 设置表情权重（0~1）。只标记 dirty，真正计算在 apply() */
  set(name, weight = 1.0) {
    if (!this.bindings[name]) return false;
    const w = Math.max(0, Math.min(1, Number(weight) || 0));
    if (Math.abs((this.state[name] || 0) - w) < 1e-4) return true;
    this.state[name] = w;
    this._dirty = true;
    return true;
  }

  /** 只保留指定表情，其余归零 */
  setOnly(name, weight = 1.0) {
    this.clear();
    return this.set(name, weight);
  }

  /** 全部归零 */
  clear() {
    if (Object.keys(this.state).length) {
      this.state = {};
      this._dirty = true;
    }
  }

  // ---------------- 应用 ----------------
  /**
   * 计算并写回顶点位置。**只在表情变化后调用**，不需要每帧。
   * @returns {boolean} 是否真的更新了
   */
  apply(force = false) {
    if (!this._ready) return false;
    if (!this._dirty && !force) return false;
    this._dirty = false;

    const t0 = performance.now();

    // 活跃表情
    const active = [];
    for (const [name, w] of Object.entries(this.state)) {
      if (w > 1e-4) active.push([name, w]);
    }

    for (const entry of this.meshes) {
      const dst = entry.mesh.geometry.attributes.position.array;
      const base = entry.base;
      const n = dst.length;

      // ① 恢复原始形状
      dst.set(base.subarray(0, n));

      // ② 叠加所有活跃表情
      for (let a = 0; a < active.length; a++) {
        const name = active[a][0], w = active[a][1];
        const binds = this.bindings[name];
        for (let b = 0; b < binds.length; b++) {
          const bind = binds[b];
          const m = entry.morphs[bind.index];
          if (!m || !m.array) continue;
          const delta = m.array;
          const k = w * bind.weight;
          const len = Math.min(n, delta.length);
          for (let i = 0; i < len; i++) dst[i] += delta[i] * k;
        }
      }

      entry.mesh.geometry.attributes.position.needsUpdate = true;
      // 表情幅度小，但重算包围球更稳妥（避免视锥剔除误判）
      entry.mesh.geometry.boundingSphere = null;
    }

    this._lastCost = performance.now() - t0;
    return true;
  }

  /** 诊断信息 */
  info() {
    let targets = 0, verts = 0;
    for (const e of this.meshes) {
      targets += e.morphs.length;
      verts += e.count;
    }
    return {
      expressions: this.names().length,
      meshes: this.meshes.length,
      morphTargets: targets,
      vertices: verts,
      ready: this._ready,
      lastCostMs: +this._lastCost.toFixed(3),
    };
  }

  /** 已生效的表情列表（权重 > 0） */
  active() {
    return Object.entries(this.state).filter(([, w]) => w > 1e-4)
      .map(([n, w]) => ({ name: n, weight: +w.toFixed(3) }));
  }
}

/** 便利工厂 */
export function createMorphDriver(vrm, gltf) {
  return new MorphDriver(vrm, gltf);
}
