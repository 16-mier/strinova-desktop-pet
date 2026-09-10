# -*- coding: utf-8 -*-
"""
PMX → VRM 一键转换脚本（卡拉彼丘桌宠落地用）
运行方式（在 Windows PowerShell 中）：
  & "C:/Users/mier/Desktop/deepseek work/blender-5.2.1/blender-5.2.1-windows-x64/blender.exe" --background --python "本脚本路径" -- "PMX文件路径" "输出VRM路径"

示例：
  & "C:/.../blender.exe" --background --python convert_pmx_to_vrm.py -- "D:/models/星绘.pmx" "D:/models/星绘.vrm"

依赖（已安装）：
  - Blender 5.2.1（本机解压版）
  - MMD Tools v4.5.14（导入 PMX）
  - VRM-Addon-for-Blender v4.7.1（导出 VRM）
  - opencc（MMD Tools 依赖，已装入 Blender 自带 Python）

说明：
  - 脚本自动完成：导入 PMX → 清理/修复 → 骨骼重命名 → 自动 Humanoid 骨骼分配
    → MMD 表情映射 → MMD 物理(SpringBone)映射 → 材质转 MToon → 导出 VRM 0.x
  - 若某个环节失败会打印错误信息（不会静默跳过），转换结果需在 Mate-Engine
    中实测：骨骼错位需手动在 Blender 中修正骨骼映射；材质发灰需检查 MToon 转换。
"""

import sys
import os
import traceback

import bpy
import addon_utils


def enable_addons():
    """确保两个插件处于启用状态（Blender 5.2 extension 以 user 身份安装）"""
    import bpy
    for name in ("bl_ext.user_default.mmd_tools", "bl_ext.user_default.vrm"):
        try:
            mod = addon_utils.enable(name, default_set=True, persistent=True)
            print(f"[{'OK' if mod else 'WARN'}] enable {name}")
        except Exception as e:
            print(f"[WARN] enable {name}: {e}")
    # operator 真实注册检查（import_model 为 MMD Tools 4.x 命名空间 operator）
    if not hasattr(bpy.ops.mmd_tools, "import_model"):
        raise RuntimeError("MMD Tools 未注册 import_model —— 请检查插件安装")
    if not hasattr(bpy.ops.export_scene, "vrm"):
        raise RuntimeError("VRM 插件未注册 export_scene.vrm —— 请检查插件安装")


def parse_args(argv):
    """解析 -- 之后的参数：输入 PMX 路径、输出 VRM 路径"""
    if "--" in argv:
        rest = argv[argv.index("--") + 1:]
    else:
        rest = [a for a in argv if not a.startswith("-")]
    if len(rest) < 1:
        raise SystemExit("用法: blender --background --python convert_pmx_to_vrm.py -- <input.pmx> [output.vrm]")
    src = rest[0]
    dst = rest[1] if len(rest) > 1 else os.path.splitext(src)[0] + ".vrm"
    return os.path.abspath(src), os.path.abspath(dst)


def clear_scene():
    """清空场景"""
    bpy.ops.wm.read_factory_settings(use_empty=True)


def import_pmx(path):
    """用 MMD Tools 导入 PMX

    ⚠⚠ types 这个集合决定"哪些东西会被导入"，漏一个就静默丢功能：
      · "PHYSICS" —— 曾经的 bug。不传就不会创建 MMD 刚体对象，而
        vrm.assign_spring_bone1_from_mmd 是靠遍历 `obj.mmd_type == "RIGID_BODY"`
        找物理骨骼的 → 场景里没有刚体，它直接 `return {"FINISHED"}`，
        【不报错也不生成任何 SpringBone】。结果导出的 VRM 没有
        VRMC_springBone 扩展，262 根头发/裙摆骨骼全静止。
      · "MORPHS" —— 第二次踩同样的坑。不传就不会导入顶点 morph，
        导出的 VRM 里 morph targets 数量是 0 → 角色的表情全部失效
        （只剩 VRM 预设的空壳，点哪个都没反应）。
      · "DISPLAY" —— MMD 显示枠（表示枠）信息，让骨骼分组更完整。
    """
    result = bpy.ops.mmd_tools.import_model(
        filepath=path,
        # MMD Tools 4.x 合法值：MESH/ARMATURE/PHYSICS/DISPLAY/MORPHS
        # 五个都要，少一个就丢一大块功能（见上面的注释）
        types={"MESH", "ARMATURE", "PHYSICS", "DISPLAY", "MORPHS"},
        scale=0.08,          # MMD 模型默认单位，缩放到 1.6m 人形
        clean_model=True,
        remove_doubles=True,
        fix_bone_order=True,
        fix_ik_links=True,
        ik_loop_factor=100,
        apply_bone_fixed_axis=True,
        rename_bones=True,    # 把日文骨骼名重命名为英文
        use_underscore=True,
        use_mipmap=True,
        log_level="WARNING",
    )
    if "CANCELLED" in str(result):
        raise RuntimeError(f"PMX 导入失败: {path}")
    # 自检：刚体和形态键都必须真的进来了，否则后面一定白做
    rigids = [o for o in bpy.data.objects if getattr(o, "mmd_type", "") == "RIGID_BODY"]
    print(f"[INFO] 导入 MMD 刚体对象: {len(rigids)} 个")
    if not rigids:
        print("[WARN] 没有刚体对象 —— springBone 一定生成不出来，"
              "请检查 types 是否包含 PHYSICS")
    n_morph = 0
    for ob in bpy.data.objects:
        if ob.type != "MESH":
            continue
        try:
            n_morph += len(ob.data.shape_keys.key_blocks) - 1 if ob.data.shape_keys else 0
        except Exception:
            pass
    print(f"[INFO] 导入顶点形态键(morph): {n_morph} 个")
    if n_morph == 0:
        print("[WARN] 没有形态键 —— 表情会全部失效，请检查 types 是否包含 MORPHS")


def find_armature():
    armatures = [o for o in bpy.data.objects if o.type == "ARMATURE"]
    if not armatures:
        raise RuntimeError("场景中没有骨架对象")
    return armatures[0].name


def setup_vrm():
    """配置 VRM 扩展数据：Humanoid 骨骼、表情、物理"""
    arm_name = find_armature()

    # 1. 自动分配 Humanoid 骨骼（VRM 0.x + 1.0 都会配）
    try:
        bpy.ops.vrm.assign_vrm0_humanoid_human_bones_automatically(
            armature_object_name=arm_name)
        bpy.ops.vrm.assign_vrm1_humanoid_human_bones_automatically(
            armature_object_name=arm_name)
        print("[OK] Humanoid 骨骼自动分配完成")
    except Exception:
        print("[WARN] Humanoid 自动分配未完成，需手动检查骨骼映射")
        traceback.print_exc()

    # 2. 表情：从 MMD morph 映射到 VRM 0.x blend shape / VRM 1.0 expression
    try:
        bpy.ops.vrm.assign_vrm0_blend_shape_group(armature_object_name=arm_name) \
            if hasattr(bpy.ops.vrm, "assign_vrm0_blend_shape_group") else None
    except Exception:
        pass
    try:
        bpy.ops.vrm.assign_vrm1_expressions_from_mmd(armature_object_name=arm_name)
        print("[OK] 表情从 MMD 映射完成")
    except Exception:
        print("[WARN] 表情映射未完成（Mate-Engine 的触摸表情可能不生效）")
        traceback.print_exc()

    # 3. 物理：从 MMD 刚体/约束映射为 SpringBone
    #    ⚠ 这一步依赖 import_pmx 时导入了 PHYSICS（刚体对象）。
    #      op 在"找不到动态刚体骨骼"时会静默 FINISHED 而不生成任何东西，
    #      所以下面必须【自己检查结果】，不能只看有没有抛异常。
    try:
        bpy.ops.vrm.assign_spring_bone1_from_mmd(armature_object_name=arm_name)
        try:
            bpy.ops.vrm.assign_vrm0_secondary_animation_group_bone(
                armature_object_name=arm_name)
        except Exception:
            pass  # 导出 1.0 时用不到 0.x 那套存储
        # 自检：VRM 1.0 的 spring_bone1 数据是否真的填上了
        arm = bpy.data.objects.get(arm_name)
        sb = None
        try:
            sb = arm.data.vrm_addon_extension.spring_bone1
        except Exception:
            pass
        n_spring = len(sb.springs) if sb else 0
        n_collider = len(sb.colliders) if sb else 0
        print(f"[INFO] springBone: springs={n_spring} colliders={n_collider}")
        if n_spring == 0:
            print("[WARN] springBone 没有生成！头发/裙摆将是静止的。"
                  "最常见原因：PMX 导入时没带 PHYSICS，场景里没有刚体对象。")
        else:
            print("[OK] 物理 SpringBone 从 MMD 映射完成")
    except Exception:
        print("[WARN] 物理映射未完成（头发/裙子不会摆动）")
        traceback.print_exc()


def convert_materials():
    """材质转 MToon（VRM 标准卡通着色器）"""
    try:
        bpy.ops.vrm.convert_material_to_mtoon1()
        print("[OK] 材质已转 MToon")
    except Exception:
        print("[WARN] MToon 转换未完成，将保留原材质导出")
        traceback.print_exc()


def export_vrm(path):
    """导出 VRM 0.x（Mate-Engine 兼容性最好）"""
    bpy.ops.export_scene.vrm(
        filepath=path,
        export_only_selections=False,
        export_invisibles=False,
    )


def main():
    src, dst = parse_args(sys.argv)
    if not os.path.exists(src):
        raise SystemExit(f"输入文件不存在: {src}")

    print(f"输入 PMX: {src}")
    print(f"输出 VRM: {dst}")
    print("=" * 60)

    clear_scene()
    enable_addons()
    import_pmx(src)
    setup_vrm()
    convert_materials()
    export_vrm(dst)

    if os.path.exists(dst):
        size = os.path.getsize(dst) / 1024 / 1024
        print("=" * 60)
        print(f"[DONE] 转换完成: {dst} ({size:.1f} MB)")
        print("下一步：在 Mate-Engine 中右键角色 → 设置菜单 → 导入该 VRM 文件")
    else:
        raise SystemExit("导出失败：未生成 VRM 文件")


if __name__ == "__main__":
    try:
        main()
    except SystemExit as e:
        print(e)
        sys.exit(e.code or 1)
    except Exception:
        traceback.print_exc()
        sys.exit(1)
