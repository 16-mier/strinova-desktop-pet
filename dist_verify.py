# -*- coding: utf-8 -*-
"""dist_verify.py —— 验证「开箱即用」分发目录能独立跑通：
从 dist 根启动 server(cuda) → health → load 模型 → 星绘克隆合成 wav → RIFF 校验
用法: python dist_verify.py <dist_dir> [bf16|q8]
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

DIST = sys.argv[1] if len(sys.argv) > 1 else None
VER = sys.argv[2] if len(sys.argv) > 2 else "q8"
if not DIST or not os.path.isdir(DIST):
    sys.exit("usage: python dist_verify.py <dist_dir> [bf16|q8]")
os.chdir(DIST)
SERVER = os.path.join(DIST, "audiocpp_server.exe")
SPEC = os.path.join(DIST, "model_specs")
if VER == "bf16":
    MODEL = os.path.join(DIST, "models", "Breeze-TTS-2-GGUF", "breeze-tts-2-bf16.gguf")
else:
    MODEL = os.path.join(DIST, "models", "breeze-tts-2", "breeze-tts-2-q8_0.gguf")
REF = os.path.join(DIST, "references", "star_ref.wav")
REF_TXT = os.path.join(DIST, "references", "star_ref.txt")
OUT = os.path.join(DIST, "verify_%s.wav" % VER)

env = dict(os.environ)
env["PATH"] = DIST + ";" + env.get("PATH", "")
cmd = [SERVER, "--ui", "--ui-management", "--backend", "cuda",
       "--host", "127.0.0.1", "--port", "8080", "--model-spec-override", SPEC]
print("START:", os.path.basename(SERVER), "(backend cuda, %s)" % VER)
proc = subprocess.Popen(cmd, cwd=DIST, env=env,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
BASE = "http://127.0.0.1:8080"

def api_json(method, url, payload=None, timeout=120):
    req = urllib.request.Request(url, method=method)
    req.add_header("Content-Type", "application/json")
    if payload is not None:
        req.data = json.dumps(payload).encode("utf-8")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8")
    return json.loads(raw) if raw.strip() else None

ok = True
try:
    ready = False
    deadline = time.time() + 120
    while time.time() < deadline:
        if proc.poll() is not None:
            print("FAIL: server exited code", proc.returncode)
            ok = False
            break
        try:
            api_json("GET", BASE + "/health", timeout=2)
            ready = True
            break
        except Exception:
            time.sleep(1)
    print("health ready:", ready)
    if not ready:
        ok = False
    else:
        text = ""
        if os.path.exists(REF_TXT):
            with open(REF_TXT, encoding="utf-8") as f:
                text = f.read().strip()
        payload = {
            "id": "breeze-tts-clone", "path": MODEL, "family": "breeze_tts",
            "task": "clon", "mode": "offline", "model_spec_override": SPEC,
        }
        try:
            res = api_json("POST", BASE + "/v1/models/load", payload, timeout=180)
            loaded = isinstance(res, dict) and res.get("loaded")
            print("model loaded:", loaded)
            print("load resp:", json.dumps(res, ensure_ascii=False)[:500])
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            print("load HTTPError:", e.code)
            print("load error body:", body[:800])
            loaded = False
        if not loaded:
            ok = False
        else:
            body = {"model": "breeze-tts-clone",
                    "input": "你好呀，我是星绘，欢迎来和我聊天。",
                    "voice_ref": REF,
                    "reference_text": text or "初次见面，我叫星绘。",
                    "response_format": "wav"}
            req = urllib.request.Request(BASE + "/v1/audio/speech", method="POST")
            req.add_header("Content-Type", "application/json")
            req.data = json.dumps(body).encode("utf-8")
            with urllib.request.urlopen(req, timeout=180) as r:
                data = r.read()
            with open(OUT, "wb") as f:
                f.write(data)
            good = data[:4] == b"RIFF"
            print("synth bytes:", len(data), "RIFF valid:", good)
            if not good:
                ok = False
finally:
    proc.terminate()
    try:
        proc.wait(timeout=8)
    except Exception:
        proc.kill()
print("RESULT:", "OK" if ok else "FAIL")
sys.exit(0 if ok else 1)
