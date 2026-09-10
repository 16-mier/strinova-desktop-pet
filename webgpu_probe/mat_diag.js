// 诊断材质贴图为什么没绑定
// 在浏览器 console 里跑，或者通过 QtWebEngine runJavaScript 注入
(() => {
  const out = [];
  let n = 0;
  const vrm = window.__vrm;
  if (!vrm) return 'no vrm';

  vrm.scene.traverse((o) => {
    if (!o.isMesh) return;
    const ms = Array.isArray(o.material) ? o.material : [o.material];
    ms.forEach((m) => {
      if (!m) return;
      n++;
      out.push({
        i: n,
        name: m.name,
        type: m.type,
        // 所有可能的贴图槽
        map: !!m.map,
        emissiveMap: !!m.emissiveMap,
        normalMap: !!m.normalMap,
        alphaMap: !!m.alphaMap,
        aoMap: !!m.aoMap,
        // 颜色
        color: m.color ? m.color.getHexString() : null,
        emissive: m.emissive ? m.emissive.getHexString() : null,
        // vrm 专用
        isMToon: !!(m.isMToonMaterial || m.type === 'MToonMaterial'),
        // uv 变换
        mapMatrix: m.map ? m.map.matrix ? m.map.matrix.elements.slice(12, 14) : null : null,
        // key 列表
        keys: Object.keys(m).filter(k => /map|tex/i.test(k)),
      });
    });
  });
  return JSON.stringify({ count: n, mats: out }, null, 1);
})()
