"""web3d_server.py —— 给 web3d 页面提供本地 HTTP 服务（后台线程）。

为什么不用 file://：
  * ES module 的 importmap 在 file:// 下受 CORS 限制
  * GLTFLoader fetch VRM 在 file:// 下会被拦截

用法：
    from web3d_server import serve
    port = serve(Path("web3d"))        # 返回端口
"""
from __future__ import annotations

import http.server
import socket
import socketserver
import threading
from pathlib import Path

_servers: dict[str, int] = {}


class _Handler(http.server.SimpleHTTPRequestHandler):
    """支持 .vrm/.glb 的 MIME + 长缓存 + 静默日志"""

    extensions_map = {
        **http.server.SimpleHTTPRequestHandler.extensions_map,
        ".vrm": "model/gltf-binary",
        ".glb": "model/gltf-binary",
        ".gltf": "model/gltf+json",
        ".js": "text/javascript",
        ".mjs": "text/javascript",
        ".vrma": "model/gltf-binary",
    }

    def __init__(self, *a, directory: str | None = None, **kw):
        super().__init__(*a, directory=directory, **kw)

    def log_message(self, fmt, *args):
        pass  # 静默

    def end_headers(self):
        # 允许跨源（QtWebEngine 页面从别的端口来也没问题）
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "public, max-age=3600")
        super().end_headers()


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def serve(directory: Path | str, port: int = 0) -> int:
    """在后台线程启动静态服务，返回实际端口（幂等：同一目录复用）。"""
    key = str(Path(directory).resolve())
    if key in _servers:
        return _servers[key]

    if port == 0:
        port = _free_port()

    handler = lambda *a, **kw: _Handler(*a, directory=key, **kw)  # noqa: E731
    httpd = _Server(("127.0.0.1", port), handler)

    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    _servers[key] = port
    return port


if __name__ == "__main__":
    import sys
    import time

    d = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "web3d"
    p = serve(d)
    print(f"serving {d} -> http://127.0.0.1:{p}/pet_viewer.html")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
