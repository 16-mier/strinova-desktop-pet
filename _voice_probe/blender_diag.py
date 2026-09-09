# -*- coding: utf-8 -*-
"""诊断：后台模式 enable mmd_tools 后 operator 是否真的注册"""
import sys
import addon_utils
import bpy

try:
    for name in ("bl_ext.user_default.mmd_tools", "bl_ext.user_default.vrm"):
        try:
            mod = addon_utils.enable(name, default_set=True, persistent=True)
            print("enable", name, "->", bool(mod))
        except Exception as e:
            print("enable ERR", name, ":", e)
    import inspect
    print("md ops:", [x for x in dir(bpy.ops.mmd_tools) if not x.startswith("_")])
    print("bpy.ops has mmd_tools:", hasattr(bpy.ops, "mmd_tools"))
except Exception as e:
    import traceback
    traceback.print_exc()
    sys.exit(1)