# -*- coding: utf-8 -*-
# rthook_fix_urllib_ssl.py —— PyInstaller runtime hook
# 问题：PyInstaller 分析期 import urllib.request 时若 ssl 尚未导入，
# urllib.request 会以「无 HTTPSHandler」的残缺形态被打包（HTTPSHandler 是
# 条件定义：仅当 import ssl 成功才定义）。运行期所有 https 请求都会报
# "unknown url type: https" 或 "no attribute HTTPSHandler"。
# 修复：程序启动最早阶段强制 import ssl，再重新 import urllib.request，
# 使其补上 HTTPSHandler（同一模块缓存，重新导入即补齐属性）。
import ssl  # noqa: F401  先导入 ssl（触发 _ssl 扩展加载）
import urllib.request  # noqa: F401  再导入 urllib.request → HTTPSHandler 被定义
