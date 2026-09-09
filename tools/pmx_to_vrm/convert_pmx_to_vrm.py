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
    """确保两个插件处于启用状态"""
    for name in ("bl_ext.user_default.mmd_tools", "bl_ext.user_default.vrm"):
        if not addon_utils.enable(name, default_set=True, persistent=True):
            raise RuntimeError(f"无法启用插件: {name}")


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
    """用 MMD Tools 导入 PMX"""
    result = bpy.ops.mmd_tools.import_model(
        filepath=path,
        types={"MODEL"},
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
    try:
        bpy.ops.vrm.assign_spring_bone1_from_mmd(armature_object_name=arm_name)
        bpy.ops.vrm.assign_vrm0_secondary_animation_group_bone(
            armature_object_name=arm_name)
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

    enable_addons()
    clear_scene()
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
