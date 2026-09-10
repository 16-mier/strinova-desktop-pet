# -*- coding: utf-8 -*-
"""
matelink.py —— MateLink 客户端：PyQt6 桌宠 ↔ Mate-Engine(3D) 深度联动桥。

Mate-Engine 进程内通过 Doorstop 注入 MateBridge.dll（本地 HTTP 127.0.0.1:8765），
本模块提供纯 socket 的 JSON 客户端，串起"桌宠大脑 → 3D 形象"的控制通道。

用法（PyQt 桌宠）：
    from matelink import MateLink
    ml = MateLink()
    ml.start()          # 后台线程监听 8765（可选，供热键/轮询）
    ml.dance.stop()     # 同步命令（HTTP POST /cmd → 立即返回 queued）
    st = ml.status()    # 查询状态（HTTP GET /status）
    ml.close()          # 退出时调用
"""
import json
import socket
import threading
import time

HOST = "127.0.0.1"
PORT = 8765
TIMEOUT = 10.0

# 命令操作表：op -> (参数说明)
ALL_OPS = (
    "dance.play(stableId|index)", "dance.stop", "dance.next", "dance.prev",
    "food.spawnById(id)", "food.spawnByIndex(index)", "food.feature(on)",
    "sleep.set(on)", "sleep.wake",
    "scale.set(value)",
    "hide.arm(left,right)", "hide.topmost(on)",
    "blend.reset", "blend.set(name,value)",
    "clothes.activate(index)", "clothes.next",
    "voice.random",
)


def _http(method: str, path: str, body: bytes | None = None, timeout: float = TIMEOUT) -> bytes:
    """极简 HTTP/1.1 请求，返回响应体字节。"""
    s = socket.create_connection((HOST, PORT), timeout=timeout)
    try:
        if body:
            req = (
                f"{method} {path} HTTP/1.1\r\n"
                f"Host: {HOST}:{PORT}\r\n"
                "Content-Type: application/json\r\n"
                f"Content-Length: {len(body)}\r\n"
                "Connection: close\r\n\r\n"
            ).encode("ascii") + body
        else:
            req = (
                f"{method} {path} HTTP/1.1\r\n"
                f"Host: {HOST}:{PORT}\r\n"
                "Connection: close\r\n\r\n"
            ).encode("ascii")
        s.sendall(req)
        data = b""
        s.settimeout(timeout)
        try:
            while True:
                chunk = s.recv(8192)
                if not chunk:
                    break
                data += chunk
        except socket.timeout:
            pass
        # 去掉 HTTP 头
        idx = data.find(b"\r\n\r\n")
        return data[idx + 4:] if idx >= 0 else data
    finally:
        s.close()


def _cmd(payload: dict, timeout: float = TIMEOUT) -> dict:
    """POST /cmd 并解析 JSON。超时/连接失败抛异常。"""
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    resp = _http("POST", "/cmd", body, timeout)
    try:
        return json.loads(resp.decode("utf-8"))
    except Exception:
        return {"ok": False, "error": "bad_response", "raw": resp.decode("utf-8", "replace")}


class MateLink:
    """Mate-Engine 联动客户端。线程安全：命令走短连接，可多线程调用。"""

    def __init__(self, host: str = HOST, port: int = PORT):
        self.host = host
        self.port = port
        self._running = False
        self._thread = None

    # ---------- 生命周期 ----------
    def start(self):
        """启动状态轮询线程（可选；用于自动检测 Mate 是否在线）"""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()

    def close(self):
        self._running = False

    def _poll_loop(self):
        while self._running:
            try:
                self.status()
            except Exception:
                pass
            time.sleep(5)

    # ---------- 基础 ----------
    def ping(self) -> bool:
        try:
            r = json.loads(_http("GET", "/ping").decode("utf-8"))
            return bool(r.get("ok"))
        except Exception:
            return False

    def online(self) -> bool:
        """Mate 桥是否在线（快速探测）"""
        return self.ping()

    def status(self) -> dict:
        """GET /status → {"ok", "dance":"playing=..;stableId=..", "blends":"name:weight;.."}"""
        try:
            r = json.loads(_http("GET", "/status").decode("utf-8"))
            return r
        except Exception:
            return {"ok": False, "error": "offline"}

    def blends_dict(self) -> dict:
        """解析 status 的 blends 字段 → {表情名: 权重}"""
        st = self.status()
        d = {}
        if not st.get("ok"):
            return d
        for item in st.get("blends", "").split(";"):
            if ":" in item:
                name, _, w = item.rpartition(":")
                try:
                    d[name] = float(w)
                except ValueError:
                    d[name] = 0.0
        return d

    # ---------- 动作 ----------
    def dance_play(self, stable_id: str | None = None, index: int | None = None) -> dict:
        return _cmd({"op": "dance.play", "stableId": stable_id, "index": index})

    def dance_stop(self) -> dict:
        return _cmd({"op": "dance.stop"})

    def dance_next(self) -> dict:
        return _cmd({"op": "dance.next"})

    def dance_prev(self) -> dict:
        return _cmd({"op": "dance.prev"})

    def food_spawn(self, food_id: str | None = None, index: int | None = None) -> dict:
        return _cmd({"op": "food.spawnById" if food_id else "food.spawnByIndex",
                     "id": food_id, "index": index})

    def food_feature(self, on: bool) -> dict:
        return _cmd({"op": "food.feature", "on": on})

    def sleep(self, on: bool) -> dict:
        return _cmd({"op": "sleep.set" if on else "sleep.wake", "on": on})

    def scale(self, value: float) -> dict:
        return _cmd({"op": "scale.set", "value": value})

    def hide_arm(self, left: bool = False, right: bool = False) -> dict:
        return _cmd({"op": "hide.arm", "left": left, "right": right})

    def topmost(self, on: bool) -> dict:
        return _cmd({"op": "hide.topmost", "on": on})

    def blend_reset(self) -> dict:
        return _cmd({"op": "blend.reset"})

    def blend_set(self, name: str, value: float) -> dict:
        return _cmd({"op": "blend.set", "name": name, "value": value})

    def clothes_activate(self, index: int) -> dict:
        return _cmd({"op": "clothes.activate", "index": index})

    def clothes_next(self) -> dict:
        return _cmd({"op": "clothes.next"})

    def voice_random(self) -> dict:
        return _cmd({"op": "voice.random"})

    # ---------- Mate-Engine 完整功能 ----------
    def say(self, text: str) -> dict:
        """让 3D 角色说一句话（气泡显示）"""
        return _cmd({"op": "say", "text": text})

    def chibi(self) -> dict:
        """Q 版模式切换"""
        return _cmd({"op": "chibi.toggle"})

    def bigscreen(self) -> dict:
        """大屏模式切换"""
        return _cmd({"op": "bigscreen.toggle"})

    def bubble(self) -> dict:
        """气泡开关"""
        return _cmd({"op": "bubble.toggle"})

    def random_messages(self, on: bool) -> dict:
        """随机消息（自动说话）开关"""
        return _cmd({"op": "messages.random", "on": on})

    def particle_theme(self, theme: str) -> dict:
        """粒子主题"""
        return _cmd({"op": "particle.theme", "theme": theme})

    def avatar_list(self) -> list:
        """可用 3D 模型列表 → [(文件名, 完整路径)]"""
        try:
            r = _cmd({"op": "avatar.list"})
            out = []
            for item in (r.get("list") or "").split(";"):
                if "|" in item:
                    n, _, p = item.partition("|")
                    out.append((n, p))
            return out
        except Exception:
            return []

    def avatar_status(self) -> dict:
        """当前 3D 模型状态"""
        return _cmd({"op": "avatar.status"})

    # ---------- 便捷组合 ----------
    def set_expression(self, name: str, value: float = 100.0):
        """设置表情（自动 reset 其他表情再设指定表情；VRM 表情互斥）"""
        if value <= 0:
            return self.blend_set(name, 0.0)
        self.blend_reset()
        return self.blend_set(name, value)


def main():
    """命令行自测：python matelink.py [op] [args...]"""
    import sys
    ml = MateLink()
    args = sys.argv[1:]
    if not args:
        print("MateLink 自测：")
        print("  ping         检查桥是否在线")
        print("  status       获取状态（含表情权重）")
        print("  blends       列出表情+权重")
        print("  dance.play stableId|index  播放舞蹈")
        print("  dance.stop   停止舞蹈")
        print("  sleep.on/off 睡觉/唤醒")
        print("  scale 1.2    缩放")
        print("  blend name 80  设置表情")
        print("  voice        随机语音")
        return
    op = args[0]
    try:
        if op == "ping":
            print("online" if ml.ping() else "offline")
        elif op == "status":
            print(json.dumps(ml.status(), ensure_ascii=False))
        elif op == "blends":
            print(json.dumps(ml.blends_dict(), ensure_ascii=False))
        elif op == "dance.play":
            if len(args) > 1 and args[1].isdigit():
                print(ml.dance_play(index=int(args[1])))
            else:
                print(ml.dance_play(stable_id=args[1] if len(args) > 1 else None))
        elif op == "dance.stop":
            print(ml.dance_stop())
        elif op == "dance.next":
            print(ml.dance_next())
        elif op == "dance.prev":
            print(ml.dance_prev())
        elif op == "sleep.on":
            print(ml.sleep(True))
        elif op == "sleep.off":
            print(ml.sleep(False))
        elif op == "scale":
            print(ml.scale(float(args[1])))
        elif op == "blend":
            print(ml.set_expression(args[1], float(args[2]) if len(args) > 2 else 100.0))
        elif op == "voice":
            print(ml.voice_random())
        elif op == "food":
            print(ml.food_spawn(index=0))
        elif op == "clothes":
            print(ml.clothes_next())
        else:
            print("unknown op:", op)
    except Exception as e:
        print("ERR:", e)


if __name__ == "__main__":
    main()