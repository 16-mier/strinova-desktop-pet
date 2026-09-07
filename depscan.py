# -*- coding: utf-8 -*-
"""Depends scan: 列出 audiocpp_server/ggml-cuda 导入的 DLL（重点 CUDA 运行库）
并检查这些 DLL 在 CUDA toolkit bin / system32 里的位置，供打包决策。"""
import os
import sys
import pefile

BIN = r"C:\Users\mier\Desktop\deepseek work\breeze-tts-local\audio-cpp\bin-cuda"
CUDA = r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v13.3\bin"
SYSTEM32 = r"C:\Windows\System32"

TARGETS = ["audiocpp_server.exe", "audiocpp_cli.exe", "ggml-cuda.dll", "ggml-base.dll", "ggml.dll"]

def imp_dlls(path):
    """返回该 PE 导入的全部 DLL 名"""
    out = set()
    try:
        pe = pefile.PE(path, fast_load=True)
        pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_IMPORT']])
        for entry in getattr(pe, 'DIRECTORY_ENTRY_IMPORT', []) or []:
            d = (entry.dll or b'').decode('latin-1')
            if d:
                out.add(d.lower())
        pe.close()
    except Exception as e:
        out.add('__ERR__:' + str(e)[:60])
    return out

cuda_dlls = set()
if os.path.isdir(CUDA):
    for f in os.listdir(CUDA):
        if f.lower().endswith('.dll'):
            cuda_dlls.add(f.lower())
sys_dlls = set()
if os.path.isdir(SYSTEM32):
    for f in os.listdir(SYSTEM32):
        if f.lower().endswith('.dll'):
            sys_dlls.add(f.lower())

for t in TARGETS:
    p = os.path.join(BIN, t)
    if not os.path.exists(p):
        print("---", t, ": NOT FOUND")
        continue
    print("=" * 60)
    print("target:", t)
    ds = imp_dlls(p)
    for d in sorted(ds):
        if d.startswith('__ERR__'):
            print("  [ERR]", d)
            continue
        loc = "cuda-bin" if d in cuda_dlls else ("system32" if d in sys_dlls else "??")
        if d.startswith(('cuda', 'cudart', 'cublas', 'cudnn', 'nv', 'nccl', 'nvcudart',
                         'cufft', 'cusparse', 'curand', 'cusolver')):
            print("  [CUDA] %-40s -> %s" % (d, loc))
        else:
            print("  [%s]   %s" % (loc, d))