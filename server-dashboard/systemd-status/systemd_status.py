#!/usr/bin/env python3
import json
import os
import subprocess
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

BIND = os.getenv("BIND", "192.168.1.73")
PORT = int(os.getenv("PORT", "8091"))

SERVICES = {
    "system-updater": "weightdiary-system-updater.service",
    "host-metrics": "weightdiary-host-metrics.service",
    "gpn-bot": "gpn-bot.service",
    "gpn-editor": "gpn-editor.service",
    "csqtt": "csqtt.service",
}


def service_state(unit):
    start = time.monotonic()
    try:
        result = subprocess.run(
            ["/usr/bin/systemctl", "is-active", unit],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
        state = (result.stdout or "").strip() or "unknown"
        return {
            "ok": state == "active",
            "state": state,
            "latency_ms": round((time.monotonic() - start) * 1000),
        }
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "ok": False,
            "state": "error",
            "latency_ms": round((time.monotonic() - start) * 1000),
            "error": exc.__class__.__name__,
        }


class Handler(BaseHTTPRequestHandler):
    server_version = "VPNSL-Systemd-Status/1.0"

    def log_message(self, fmt, *args):
        return

    def _headers(self, length):
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(length))

    def _json(self, status, payload, head=False):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._headers(len(body))
        self.end_headers()
        if not head:
            self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS")
        self.end_headers()

    def do_HEAD(self):
        self._route(True)

    def do_GET(self):
        self._route(False)

    def _route(self, head=False):
        path = urlparse(self.path).path.rstrip("/") or "/"

        if path == "/":
            self._json(200, {
                "service": "VPNSL Systemd Status",
                "services": sorted(SERVICES.keys()),
            }, head)
            return

        if path.startswith("/service/"):
            name = path.split("/", 2)[2].strip().lower()
            unit = SERVICES.get(name)
            if unit is None:
                self._json(404, {"ok": False, "error": "unknown service"}, head)
                return

            result = service_state(unit)
            result["service"] = name
            self._json(200 if result["ok"] else 503, result, head)
            return

        self._json(404, {"ok": False, "error": "not found"}, head)


if __name__ == "__main__":
    ThreadingHTTPServer((BIND, PORT), Handler).serve_forever()
