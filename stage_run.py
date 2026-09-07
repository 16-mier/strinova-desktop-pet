# -*- coding: utf-8 -*-
"""stage_run.py —— 在干净 stage 目录启动 audiocpp_server（验证打包可行性）
流程：cwd=stage、PATH 前置 stage → Popen server --ui --ui-management --backend cuda
     → 等 /health → POST /v1/models/load(克隆) → POST /v1/audio/speech 合成一段 wav
用法: python stage_run.py <stage_dir>
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

STAGE = sys.argv[1] if len(sys.argv) > 1 else None
if not STAGE or not os.path.isdir(STAGE):
    sys.exit("usage: python stage_run.py <stage_dir>")
os.chdir(STAGE)
SERVER = os.path.join(STAGE, "audiocpp_server.exe")
SPEC = os.path.join(STAGE, "model_specs")
MODEL = os.path.join(STAGE, "breeze-tts-2", "breeze-tts-2-q8_0.gguf")
REF = os.path.join(STAGE, "references", "star_ref.wav")
REF_TXT = os.path.join(STAGE, "references", "star_ref.txt")
OUT = os.path.join(STAGE, "out_test.wav")

env = dict(os.environ)
env["PATH"] = STAGE + ";" + env.get("PATH", "")
cmd = [SERVER, "--ui", "--ui-management", "--backend", "cuda",
       "--host", "127.0.0.1", "--model-spec-override", SPEC]
print("START:", " ".join(cmd))
proc = subprocess.Popen(cmd, cwd=STAGE, env=env,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
BASE = "http://127.0.0.1:8080"

def api(method, url, payload=None, timeout=60):
    req = urllib.request.Request(url, method=method)
    req.add_header("Content-Type", "application/json")
    if payload is not None:
        req.data = json.dumps(payload).encode("utf-8")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8")
    return json.loads(raw) if raw.strip() else None

def api_bytes(method, url, payload=None, timeout=120):
    """返回原始响应字节（audio/speech 返回 wav 二进制）"""
    req = urllib.request.Request(url, method=method)
    req.add_header("Content-Type", "application/json")
    if payload is not None:
        req.data = json.dumps(payload).encode("utf-8")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()

ok = True
try:
    # 1. health
    ready = False
    deadline = time.time() + 90
    while time.time() < deadline:
        if proc.poll() is not None:
            print("FAIL: server exited code", proc.returncode)
            ok = False
            break
        try:
            api("GET", BASE + "/health", timeout=2)
            ready = True
            break
        except Exception:
            time.sleep(1)
    print("health ready:", ready)
    if not ready:
        ok = False
    if ok:
        # 2. load breeze clone
        text = ""
        if os.path.exists(REF_TXT):
            with open(REF_TXT, encoding="utf-8") as f:
                text = f.read().strip()
        payload = {
            "id": "breeze-tts-clone",
            "path": MODEL,
            "family": "breeze_tts",
            "task": "clon",
            "mode": "offline",
            "model_spec_override": SPEC,
        }
        res = api("POST", BASE + "/v1/models/load", payload, timeout=120)
        print("load result:", json.dumps(res, ensure_ascii=False)[:300])
        loaded = isinstance(res, dict) and res.get("loaded")
        print("model loaded:", loaded)
        if not loaded:
            ok = False
        else:
            # 3. synth short test (clone with star voice) -> bytes -> wav
            body = {
                "model": "breeze-tts-clone",
                "input": "你好呀，我是星绘，欢迎来和我聊天。",
                "voice": "",
            }
            if os.path.exists(REF):
                body["voice_ref"] = REF
                body["reference_text"] = text or "初次见面，我叫星绘。"
            body["response_format"] = "wav"
            try:
                data = api_bytes("POST", BASE + "/v1/audio/speech", body, timeout=120)
                with open(OUT, "wb") as f:
                    f.write(data)
                print("speech bytes:", len(data))
                print("wav saved:", OUT, "exists:", os.path.exists(OUT))
                # 校验 wav 头
                if data[:4] == b'RIFF':
                    print("RIFF OK (valid wav)")
                else:
                    print("NOT RIFF, head:", data[:16])
                    ok = False
            except urllib.error.HTTPError as e:
                print("speech HTTPError:", e.code, e.read().decode('utf-8', 'replace')[:300])
                ok = False
except Exception as e:
    print("ERR:", e)
    ok = False
finally:
    proc.terminate()
    try:
        proc.wait(timeout=8)
    except Exception:
        proc.kill()
print("RESULT:", "OK" if ok else "FAIL")
sys.exit(0 if ok else 1)
