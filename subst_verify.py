# -*- coding: utf-8 -*-
"""subst_verify.py —— 验证中文路径下用 subst 映射盘符后 server 可加载模型
模拟：真实 dist 在含中文路径下（BreezeTTS2-CUDA），subst 到 R:，用 R:\ 路径加载。
用法: python subst_verify.py <dist_dir>
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

DIST = sys.argv[1] if len(sys.argv) > 1 else None
if not DIST or not os.path.isdir(DIST):
    sys.exit("usage: python subst_verify.py <dist_dir>")
DRIVE = "R:"
# 1. subst 映射
subprocess.run(["subst", DRIVE, DIST], check=False)
time.sleep(0.5)
try:
    # 2. 启动 server（cwd=映射盘根）
    env = dict(os.environ)
    env["PATH"] = DIST + ";" + env.get("PATH", "")
    # 用正斜杠路径（Windows 兼容，避免 json 反斜杠二次转义被服务端吞掉）
    S = DRIVE + "/"
    cmd = [S + "audiocpp_server.exe", "--ui", "--ui-management",
           "--backend", "cuda", "--host", "127.0.0.1", "--port", "8080",
           "--model-spec-override", S + "model_specs"]
    print("START via subst:", S)                    # moved inside try, was outside
    proc = subprocess.Popen(cmd, cwd=DRIVE + "\\", env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    BASE = "http://127.0.0.1:8080"

    def api(method, url, payload=None, timeout=180):
        req = urllib.request.Request(url, method=method)
        req.add_header("Content-Type", "application/json")
        if payload is not None:
            req.data = json.dumps(payload).encode("utf-8")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8")
        return json.loads(raw) if raw.strip() else None

    ok = False
    ready = False
    deadline = time.time() + 120
    while time.time() < deadline:
        if proc.poll() is not None:
            print("FAIL: server exited", proc.returncode)
            break
        try:
            api("GET", BASE + "/health", timeout=2)
            ready = True
            break
        except Exception:
            time.sleep(1)
    print("health:", ready)
    if ready:
        model = S + "models/breeze-tts-2/breeze-tts-2-q8_0.gguf"
        payload = {"id": "breeze-tts-clone", "path": model, "family": "breeze_tts",
                   "task": "clon", "mode": "offline",
                   "model_spec_override": S + "model_specs"}
        try:
            res = api("POST", BASE + "/v1/models/load", payload, timeout=180)
            print("loaded:", isinstance(res, dict) and res.get("loaded"))
            ok = isinstance(res, dict) and res.get("loaded")
        except urllib.error.HTTPError as e:
            print("HTTPError:", e.code, e.read().decode('utf-8', 'replace')[:400])
    proc.terminate()
    try:
        proc.wait(timeout=8)
    except Exception:
        proc.kill()
    print("RESULT:", "OK" if ok else "FAIL")
finally:
    subprocess.run(["subst", DRIVE, "/D"], check=False)
sys.exit(0 if ok else 1)
