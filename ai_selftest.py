# -*- coding: utf-8 -*-
# ai_selftest.py —— 源码版自测：编译 + 无 GUI 核心逻辑 + TTS 各路径
import os
import sys
import py_compile

ROOT = r"C:\Users\mier\Desktop\deepseek work\dsh-desktop-pet"
os.chdir(ROOT)
sys.path.insert(0, ROOT)

print("== 1. py_compile ==")
for f in ["pet.py", "settings_panel.py", "ai_chat.py"]:
    py_compile.compile(os.path.join(ROOT, f), doraise=True)
    print("  OK", f)

# 用一个假 pet 模块模拟绑定（不启动 PyQt 主循环）
class FakePet:
    _pet_size = 200
    role = "星绘"
    _voice_source = 'role'
    _audio_hotkeys = {}
    _hotkeys_enabled = True
    _numpad_enabled = False
    _auto_ptt = False
    _ptt_key_name = 'V'
    _bind_device = ''
    _self_device = ''
    _toast_text = None

    @staticmethod
    def load_config():
        return {}

    @staticmethod
    def save_config(cfg):
        pass

    @staticmethod
    def base_dir():
        return ROOT

    @staticmethod
    def frameGeometry():
        return None
    def update(self):
        pass


import importlib.util
import tempfile


def load_mod(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, name + ".py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


_TMP = tempfile.mkdtemp(prefix='ai_test_')


class FakePet:
    _pet_size = 200
    role = "星绘"
    _voice_source = 'role'
    _audio_hotkeys = {}
    _hotkeys_enabled = True
    _numpad_enabled = False
    _auto_ptt = False
    _ptt_key_name = 'V'
    _bind_device = ''
    _self_device = ''
    _toast_text = None

    @staticmethod
    def load_config():
        try:
            import json
            with open(os.path.join(_TMP, 'cfg.json'), 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}

    @staticmethod
    def save_config(cfg):
        import json
        with open(os.path.join(_TMP, 'cfg.json'), 'w', encoding='utf-8') as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)

    @staticmethod
    def base_dir():
        return _TMP

    @staticmethod
    def frameGeometry():
        return None

    def update(self):
        pass

print("== 2. 模块加载（无 GUI 构造）==")
ai = load_mod("ai_chat")
ai.bind_pet_module(FakePet)
print("  HAS_EDGE:", ai.HAS_EDGE, " HAS_SAPI:", ai.HAS_SAPI)

print("== 3. AI 配置读写 ==")
ai._save_ai_cfg(enabled=True, tts_enabled=True, tts_mode='cloud')
ai._save_ai_cfg(base_url="https://api.deepseek.com/v1", api_key="sk-test", model="deepseek-chat")
ai._save_ai_cfg(tts_voice="zh-CN-XiaoxiaoNeural")
cfg = ai._ai_cfg()
assert cfg.get('enabled') is True
assert cfg.get('tts_mode') == 'cloud'
assert cfg.get('api_key') == 'sk-test'
assert cfg.get('tts_voice') == 'zh-CN-XiaoxiaoNeural'
print("  OK: enabled/tts_mode/api_key/voice 读写一致")

print("== 4. 云端 TTS 合成（edge-tts，实测网络，async 直调）==")
import asyncio
import time
t0 = time.time()
try:
    data = asyncio.run(ai._edge_synth("你好，这是云端语音测试。", 'zh-CN-XiaoxiaoNeural'))
    print("  OK: 云端合成 %d bytes, %.1fs" % (len(data), time.time()-t0))
except Exception as e:
    print("  FAIL: 云端失败", type(e).__name__, repr(e))

print("== 5. 本地 SAPI 合成（comtypes，离线，同步直调）==")
try:
    p5 = ai._tts_dir() + os.sep + "local_test.wav"
    ai._sapi_synth("你好，这是本地语音测试。", p5)
    print("  OK: 本地合成 ->", os.path.basename(p5))
    os.remove(p5)
except Exception as e:
    print("  FAIL: 本地失败", type(e).__name__, repr(e))

print("== 6. 代理探测 ==")
print("  探测结果:", ai._detect_proxy())

print("\nDONE ✅")