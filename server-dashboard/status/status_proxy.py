#!/usr/bin/env python3
import json
import os
import ssl
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

PORT = int(os.getenv("PORT", "8090"))
DOCKER_PROXY = os.getenv("DOCKER_PROXY", "http://dockerproxy:2375").rstrip("/")

TARGETS = {
    "adguard": (os.getenv("ADGUARD_URL", "http://192.168.1.73:8080/"), False),
    "vpnsl": (os.getenv("VPNSL_URL", "https://192.168.1.73:46002/"), True),
    "keenetic": (os.getenv("KEENETIC_URL", "http://192.168.1.1/"), True),
    "jellyfin": (os.getenv("JELLYFIN_URL", "http://192.168.1.73:8096/"), False),
    "transmission": (os.getenv("TRANSMISSION_URL", "http://192.168.1.73:9091/transmission/web/"), False),
    "fuel": (os.getenv("FUEL_URL", "http://192.168.1.73:8081/"), False),
    "homer": (os.getenv("HOMER_URL", "http://192.168.1.73:8088/"), False),
    "glances": (os.getenv("GLANCES_URL", "http://192.168.1.73:61208/api/4/status"), False),
}

USER_AGENT = "VPNSL-Home-Dashboard-Status/1.0"


def cors_headers(handler):
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type")
    handler.send_header("Cache-Control", "no-store")


def http_check(url, insecure=False, timeout=2.5):
    start = time.monotonic()
    req = Request(url, method="GET", headers={"User-Agent": USER_AGENT})
    context = ssl._create_unverified_context() if insecure else None
    try:
        with urlopen(req, timeout=timeout, context=context) as resp:
            code = int(resp.getcode() or 200)
            ok = code < 500
    except HTTPError as exc:
        code = int(exc.code)
        ok = code < 500
    except (URLError, TimeoutError, OSError, ssl.SSLError) as exc:
        return {
            "ok": False,
            "status_code": None,
            "latency_ms": round((time.monotonic() - start) * 1000),
            "error": exc.__class__.__name__,
        }

    return {
        "ok": ok,
        "status_code": code,
        "latency_ms": round((time.monotonic() - start) * 1000),
    }


def docker_containers():
    url = f"{DOCKER_PROXY}/containers/json?all=true"
    req = Request(url, method="GET", headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=2.5) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    # Homer only needs State. Do not expose container env, mounts or labels.
    return [{"State": str(item.get("State", "unknown"))} for item in data]


class Handler(BaseHTTPRequestHandler):
    server_version = "VPNSL-Dashboard-Status/1.0"

    def log_message(self, fmt, *args):
        return

    def _json(self, status, payload, head=False):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        cors_headers(self)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if not head:
            self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        cors_headers(self)
        self.end_headers()

    def do_HEAD(self):
        self._route(head=True)

    def do_GET(self):
        self._route(head=False)

    def _route(self, head=False):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        if path == "/":
            self._json(200, {
                "service": "VPNSL Home Dashboard Status",
                "health_endpoints": sorted(TARGETS.keys()),
                "docker_proxy": True,
            }, head)
            return

        if path.startswith("/health/"):
            name = path.split("/", 2)[2].strip().lower()
            target = TARGETS.get(name)
            if target is None:
                self._json(404, {"ok": False, "error": "unknown service"}, head)
                return
            result = http_check(target[0], target[1])
            result["service"] = name
            self._json(200 if result["ok"] else 503, result, head)
            return

        if path == "/health/docker":
            try:
                items = docker_containers()
                running = sum(1 for item in items if item["State"] == "running")
                stopped = sum(1 for item in items if item["State"] == "exited")
                self._json(200, {
                    "ok": True,
                    "service": "docker",
                    "running": running,
                    "stopped": stopped,
                    "total": len(items),
                }, head)
            except Exception as exc:
                self._json(503, {
                    "ok": False,
                    "service": "docker",
                    "error": exc.__class__.__name__,
                }, head)
            return

        if path == "/containers/json":
            try:
                self._json(200, docker_containers(), head)
            except Exception as exc:
                self._json(503, {"error": exc.__class__.__name__}, head)
            return

        if path == "/summary":
            summary = {}
            for name, target in TARGETS.items():
                summary[name] = http_check(target[0], target[1])
            try:
                items = docker_containers()
                summary["docker"] = {
                    "ok": True,
                    "running": sum(1 for item in items if item["State"] == "running"),
                    "stopped": sum(1 for item in items if item["State"] == "exited"),
                    "total": len(items),
                }
            except Exception as exc:
                summary["docker"] = {"ok": False, "error": exc.__class__.__name__}
            self._json(200, summary, head)
            return

        self._json(404, {"error": "not found"}, head)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
