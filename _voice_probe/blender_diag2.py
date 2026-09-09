# -*- coding: utf-8 -*-
"""诊断2：enable 后直接调用 import_model 看真实报错"""
import sys
import os
import traceback
import addon_utils
import bpy

PMX = r"C:\Users\mier\Desktop\deepseek work\mate-engine\michelle_model\米雪儿私服1.pmx"

addon_utils.enable("bl_ext.user_default.mmd_tools", default_set=True, persistent=True)
addon_utils.enable("bl_ext.user_default.vrm", default_set=True, persistent=True)
print("enabled ok")
try:
    # 先调一次空场景 import 看 poll 是否拦
    result = bpy.ops.mmd_tools.import_model(
        filepath=PMX,
        types={"MODEL"},
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
        log_level="WARNING",
    )
    print("IMPORT RESULT:", result)
    objs = [o.name for o in bpy.data.objects]
    print("objects:", objs[:10])
except Exception as e:
    traceback.print_exc()
    sys.exit(1)