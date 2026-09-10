# -*- coding: utf-8 -*-
"""mate_avatar.py —— 3D 角色切换管理（改 settings.json + 重启 Mate 进程，官方持久化路径）

为什么不用桥的 avatar.load：Mate-Engine 的 VRMLoader.LoadVRM 是 async，
其 continuation 在线程池执行 Unity API 会崩溃（实测 Player.log 栈证实）；
Harmony 主线程补丁也因 Unity 6 缺 API 而不可用。
故采用官方持久化路径：写 settings.json → 重启进程 → VRMLoader.Start() 读配置加载。
"""
import json
import os
import subprocess
import time

MATE_DIR = r"C:\Users\mier\Desktop\deepseek work\mate-engine\unpacked"
MATE_EXE = os.path.join(MATE_DIR, "MateEngineX.exe")
MATE_DATA = os.path.join(os.environ["USERPROFILE"], "AppData", "LocalLow", "Shinymoon", "MateEngineX")
SETTINGS = os.path.join(MATE_DATA, "settings.json")
AVATARS = os.path.join(MATE_DATA, "avatars.json")

# 已知模型搜索目录
SEARCH_DIRS = [
    r"C:\Users\mier\Desktop\deepseek work\mate-engine\michelle_model",
    r"C:\Users\mier\Desktop\deepseek work\mate_research\src\Mate-Engine-main\Assets\MATE ENGINE - Avatar\DLCs",
    os.path.join(MATE_DATA, "Models"),
    os.path.join(os.environ["USERPROFILE"], "Downloads"),
]


def list_models():
    """扫描可用 3D 模型 → [(显示名, 完整路径)]"""
    out = []
    seen = set()
    for d in SEARCH_DIRS:
        if not os.path.isdir(d):
            continue
        for root, _dirs, files in os.walk(d):
            for f in files:
                if f.lower().endswith(".vrm"):
                    p = os.path.join(root, f)
                    if f not in seen:
                        seen.add(f)
                        out.append((f, p))
    return out


def current_model():
    """当前选中的模型路径（从 settings.json 读）"""
    try:
        with open(SETTINGS, encoding="utf-8") as fh:
            d = json.load(fh)
        return d.get("selectedModelPath", "")
    except Exception:
        return ""


def is_running():
    try:
        r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq MateEngineX.exe"],
                           capture_output=True, text=True, timeout=10)
        return "MateEngineX.exe" in r.stdout
    except Exception:
        return False


def kill_mate():
    subprocess.run(["taskkill", "/F", "/IM", "MateEngineX.exe"],
                   capture_output=True, text=True, timeout=15)
    for _ in range(20):
        if not is_running():
            return True
        time.sleep(0.5)
    return not is_running()


def start_mate():
    if is_running():
        return True
    subprocess.Popen([MATE_EXE], cwd=MATE_DIR,
                     creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    return True


def set_model(path, restart=True, wait_bridge=True, timeout=40):
    """切换 3D 角色：写 settings.json（+注册 avatars.json）→ 重启 Mate → 等桥上线"""
    if not os.path.isfile(path):
        return {"ok": False, "error": "file not found: %s" % path}

    # 1) 写 settings.json
    try:
        with open(SETTINGS, encoding="utf-8") as fh:
            d = json.load(fh)
    except Exception as e:
        return {"ok": False, "error": "read settings: %s" % e}
    d["selectedModelPath"] = path
    try:
        with open(SETTINGS, "w", encoding="utf-8") as fh:
            json.dump(d, fh, ensure_ascii=False, indent=4)
    except Exception as e:
        return {"ok": False, "error": "write settings: %s" % e}

    # 2) 注册到 avatars.json（若未注册）
    try:
        with open(AVATARS, encoding="utf-8") as fh:
            arr = json.load(fh)
    except Exception:
        arr = []
    if not any((a.get("filePath", "").lower() == path.lower()) for a in arr):
        import datetime
        arr.append({
            "displayName": os.path.splitext(os.path.basename(path))[0],
            "author": "unknown",
            "version": "1.0",
            "fileType": "VRM1.X",
            "filePath": path,
            "thumbnailPath": "",
            "polygonCount": 0,
            "isSteamWorkshop": False,
            "steamFileId": 0,
            "isNSFW": False,
            "isOwner": True,
        })
        try:
            with open(AVATARS, "w", encoding="utf-8") as fh:
                json.dump(arr, fh, ensure_ascii=False, indent=2)
        except Exception:
            pass

    if not restart:
        return {"ok": True, "restart": False, "path": path}

    # 3) 重启
    kill_mate()
    time.sleep(1.5)
    start_mate()

    # 4) 等桥上线
    if wait_bridge:
        import socket
        for _ in range(int(timeout)):
            time.sleep(1)
            try:
                s = socket.create_connection(("127.0.0.1", 8765), timeout=2)
                s.sendall(b"GET /ping HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n")
                r = s.recv(4096)
                s.close()
                if b'"ok":true' in r:
                    return {"ok": True, "path": path, "bridge": "online"}
            except Exception:
                pass
        return {"ok": True, "path": path, "bridge": "timeout"}
    return {"ok": True, "path": path}


if __name__ == "__main__":
    import sys
    args = sys.argv[1:]
    if not args or args[0] == "list":
        print("当前:", os.path.basename(current_model()) or "(默认)")
        for name, path in list_models():
            mark = " ✓" if path.lower() == current_model().lower() else ""
            print("  -", name, mark)
    elif args[0] == "status":
        print("运行中:", is_running())
        print("当前模型:", current_model())
    elif args[0] == "set" and len(args) > 1:
        target = args[1]
        # 支持传文件名或完整路径
        if not os.path.isfile(target):
            for n, p in list_models():
                if n.lower() == target.lower():
                    target = p
                    break
        print(json.dumps(set_model(target), ensure_ascii=False, indent=2))
