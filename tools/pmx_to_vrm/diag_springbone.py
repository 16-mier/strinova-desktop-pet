# -*- coding: utf-8 -*-
"""诊断 springBone 为什么导出后 joints=0

用法：
  blender --background --python diag_springbone.py -- "PMX路径" "输出VRM路径"

逐步 dump：
  1. 导入 PMX（带 PHYSICS）后有多少刚体
  2. assign_spring_bone1_from_mmd 之后 springs / colliders / 每个 spring 的 joints
  3. assign_vrm0_secondary_animation_group_bone 之后再看一遍
     （怀疑这一步会把 1.0 的数据清掉）
  4. 导出后再解析 GLB 看 joints 数量
"""
import json
import os
import struct
import sys
import traceback

import bpy


def log(*a):
    print("[DIAG]", *a, flush=True)


def parse_args(argv):
    if "--" not in argv:
        raise SystemExit("需要参数: -- PMX路径 输出VRM路径")
    rest = argv[argv.index("--") + 1:]
    return rest[0], rest[1]


def enable_addons():
    import addon_utils
    for name in ("bl_ext.user_default.mmd_tools", "bl_ext.user_default.vrm"):
        try:
            addon_utils.enable(name, default_set=True)
            log("enabled", name)
        except Exception as e:
            log("enable failed", name, e)


def dump_sb(tag):
    """打印当前 armature 上 VRM 1.0 spring bone 数据"""
    arms = [o for o in bpy.data.objects if o.type == "ARMATURE"]
    if not arms:
        log(tag, "no armature")
        return None
    arm = arms[0]
    try:
        sb = arm.data.vrm_addon_extension.spring_bone1
    except Exception as e:
        log(tag, "无法访问 spring_bone1:", e)
        return None
    n_s = len(sb.springs)
    n_c = len(sb.colliders)
    n_g = len(sb.collider_groups)
    log(f"{tag}: springs={n_s} colliders={n_c} collider_groups={n_g}")
    total_joints = 0
    for i, sp in enumerate(sb.springs):
        try:
            js = list(sp.joints)
        except Exception as e:
            log(f"  spring[{i}] joints 读取失败: {e}")
            continue
        total_joints += len(js)
        names = []
        for j in js[:4]:
            try:
                names.append(j.bone_name if hasattr(j, "bone_name") else str(j))
            except Exception:
                names.append("?")
        log(f"  spring[{i}] name={getattr(sp,'name','?')!r} joints={len(js)} 前几个={names}")
    log(f"{tag}: joints 合计 = {total_joints}")
    # 顺便看看 speversion
    try:
        log(f"{tag}: spec_version = {arm.data.vrm_addon_extension.spec_version}")
    except Exception:
        pass
    return total_joints


def read_glb_json(p):
    b = open(p, "rb").read()
    if b[:4] != b"glTF":
        return None
    off = 12
    while off < len(b):
        ln, ty = struct.unpack_from("<II", b, off)
        off += 8
        if ty == 0x4E4F534A:
            return json.loads(b[off:off + ln].decode("utf-8"))
        off += ln
    return None


def main():
    src, dst = parse_args(sys.argv)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    enable_addons()

    log("=== 1. 导入 PMX (含 PHYSICS) ===")
    bpy.ops.mmd_tools.import_model(
        filepath=src,
        types={"MESH", "ARMATURE", "PHYSICS", "DISPLAY"},
        scale=0.08,
        clean_model=True,
        remove_doubles=True,
        fix_bone_order=True,
        fix_ik_links=True,
        ik_loop_factor=100,
        apply_bone_fixed_axis=True,
        rename_bones=True,
        use_underscore=True,
        use_mipmap=True,
        log_level="ERROR",
    )
    rigids = [o for o in bpy.data.objects if getattr(o, "mmd_type", "") == "RIGID_BODY"]
    joints_mmd = [o for o in bpy.data.objects if getattr(o, "mmd_type", "") == "JOINT"]
    log(f"刚体={len(rigids)} 关节={len(joints_mmd)}")
    # 统计刚体类型：0=静态/跟随骨骼, 1=物理, 2=物理+骨骼位置对齐
    from collections import Counter
    cnt = Counter()
    for o in rigids:
        try:
            cnt[o.mmd_rigid.type] += 1
        except Exception:
            cnt["?"] += 1
    log(f"刚体类型分布(0=静态 1=物理 2=物理+对齐): {dict(cnt)}")

    arm_name = [o for o in bpy.data.objects if o.type == "ARMATURE"][0].name
    log(f"armature = {arm_name}")

    try:
        bpy.ops.vrm.assign_vrm1_humanoid_human_bones_automatically(
            armature_object_name=arm_name)
    except Exception:
        traceback.print_exc()

    log("=== 2. assign_spring_bone1_from_mmd ===")
    try:
        r = bpy.ops.vrm.assign_spring_bone1_from_mmd(armature_object_name=arm_name)
        log("op result =", r)
    except Exception:
        traceback.print_exc()
    dump_sb("step2-后")

    log("=== 3. assign_vrm0_secondary_animation_group_bone ===")
    try:
        r = bpy.ops.vrm.assign_vrm0_secondary_animation_group_bone(
            armature_object_name=arm_name)
        log("op result =", r)
    except Exception as e:
        log("vrm0 op 失败(可忽略):", e)
    dump_sb("step3-后")

    log("=== 4. 导出 ===")
    try:
        bpy.ops.export_scene.vrm(filepath=dst, export_only_selections=False,
                                 export_invisibles=False)
    except Exception:
        traceback.print_exc()
    if os.path.exists(dst):
        g = read_glb_json(dst)
        sb = (g or {}).get("extensions", {}).get("VRMC_springBone")
        log(f"导出文件: {os.path.getsize(dst)/1024/1024:.2f} MB")
        if sb:
            log(f"  VRMC_springBone: colliders={len(sb.get('colliders',[]))} "
                f"groups={len(sb.get('colliderGroups',[]))} "
                f"joints={len(sb.get('joints',[]))}")
        else:
            log("  VRMC_springBone 不存在")
        log(f"  extensionsUsed={ (g or {}).get('extensionsUsed') }")


if __name__ == "__main__":
    main()
