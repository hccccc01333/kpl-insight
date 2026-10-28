"""Serve the bundled frontend using only the Python standard library."""
from __future__ import annotations

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
import os
from pathlib import Path
import secrets
import threading
import webbrowser

from kpl_insight.local_runtime import RuntimeControl


DEFAULT_SITE_DIR = Path(__file__).resolve().with_name("frontend")


def site_directory() -> Path:
    return Path(os.environ.get("KPL_SITE_DIR") or DEFAULT_SITE_DIR).expanduser().resolve()


class LocalHandler(SimpleHTTPRequestHandler):
    def _allowed(self):
        host = self.headers.get("Host", "")
        allowed = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
        origin = self.headers.get("Origin")
        return host in allowed and (origin is None or origin == "http://" + host)

    def _json(self, status, value):
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/__kpl_local__/status":
            if not self._allowed():
                return self._json(403, {"error": "仅允许本地同源访问。"})
            return self._json(200, {"token": self.server.control_token, **self.server.control.status()})
        return super().do_GET()

    def do_POST(self):
        if self.path not in ("/__kpl_local__/start", "/__kpl_local__/stop"):
            return self._json(404, {"error": "未知操作。"})
        token = self.headers.get("X-KPL-Token", "")
        if not self._allowed() or not hmac.compare_digest(token.encode("utf-8"), self.server.control_token.encode("utf-8")):
            return self._json(403, {"error": "仅允许本地控制面板操作，请刷新页面。"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 2048:
                raise ValueError("请求格式无效。")
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError("请求格式无效。")
            result = (self.server.control.start(data.get("mode", "auto"), data.get("league"))
                      if self.path.endswith("/start") else self.server.control.stop())
            return self._json(200, result)
        except (ValueError, OSError) as exc:
            return self._json(400, {"error": str(exc)})
        except Exception as exc:
            return self._json(500, {"error": f"操作失败：{exc}"})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="启动峡谷有数前端（无需模型或第三方依赖）")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--site-dir", type=Path, default=site_directory())
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)
    if not 0 <= args.port <= 65535:
        parser.error("端口必须在 0–65535 之间")
    site = args.site_dir.expanduser().resolve()
    if not (site / "index.html").is_file():
        parser.error(f"缺少前端首页：{site / 'index.html'}")
    handler = partial(LocalHandler, directory=str(site))
    try:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    except OSError as exc:
        parser.exit(1, f"无法启动网站：{exc}。可用 --port 8001 更换端口。\n")
    server.control = RuntimeControl(site)
    server.control_token = secrets.token_hex(32)
    url = f"http://127.0.0.1:{server.server_port}/"
    print(f"KPL Insight: {url}\nFrontend: {site}\nCtrl+C to stop.", flush=True)
    if not args.no_browser:
        threading.Timer(0.3, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        server.control.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
