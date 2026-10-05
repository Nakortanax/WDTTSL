#!/usr/bin/env python3
import json
import os
import re
import shutil
import socketserver
import subprocess
from pathlib import Path
from typing import Any


SOCKET_PATH = os.getenv("SERVER_AI_READ_SOCKET", "/run/server-ai/read.sock")
SOCKET_UID = int(os.getenv("SERVER_AI_SOCKET_UID", "1000"))
SOCKET_GID = int(os.getenv("SERVER_AI_SOCKET_GID", "1000"))
MAX_OUTPUT = 12000

UNIT_RE = re.compile(r"^[A-Za-z0-9@_.:-]{1,160}$")
CONTAINER_RE = re.compile(r"^[A-Za-z0-9_.-]{1,160}$")
SECRET_ASSIGN_RE = re.compile(
    r"(?i)(password|passwd|token|secret|api[_-]?key|private[_-]?key|preshared[_-]?key|bot[_-]?token)(\s*[:=]\s*)(\S+)"
)
TELEGRAM_TOKEN_RE = re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{25,}\b")


def redact(text: str) -> str:
    text = TELEGRAM_TOKEN_RE.sub("<REDACTED_TELEGRAM_TOKEN>", text)
    return SECRET_ASSIGN_RE.sub(lambda m: m.group(1) + m.group(2) + "<REDACTED>", text)


def clip(text: str) -> str:
    text = redact(text)
    if len(text) <= MAX_OUTPUT:
        return text
    return text[:MAX_OUTPUT] + f"\n...[truncated {len(text) - MAX_OUTPUT} chars]"


def run(cmd: list[str], timeout: int = 10) -> dict[str, Any]:
    binary = shutil.which(cmd[0])
    if not binary:
        return {"ok": False, "error": f"Command not installed: {cmd[0]}"}
    cmd = [binary, *cmd[1:]]
    try:
        proc = subprocess.run(
            cmd,
            text=True,
            capture_output=True,
            timeout=timeout,
            env={"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"},
        )
        output = proc.stdout
        if proc.stderr:
            output += ("\n" if output else "") + proc.stderr
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "output": clip(output.strip()),
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"Timed out after {timeout}s"}


def valid_unit(value: str) -> str:
    value = value.strip()
    if not UNIT_RE.fullmatch(value):
        raise ValueError("Invalid systemd unit name")
    return value


def valid_container(value: str) -> str:
    value = value.strip()
    if not CONTAINER_RE.fullmatch(value):
        raise ValueError("Invalid Docker container name")
    return value


def int_range(value: Any, minimum: int, maximum: int, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(number, maximum))


def safe_repo_path(value: str) -> str:
    path = os.path.realpath(value)
    allowed = ["/home", "/opt", "/srv"]
    if not any(path == root or path.startswith(root + "/") for root in allowed):
        raise PermissionError("Git READ path must be under /home, /opt or /srv")
    if not os.path.isdir(path):
        raise FileNotFoundError(path)
    git_marker = os.path.join(path, ".git")
    if not os.path.exists(git_marker):
        raise ValueError("Path is not a Git repository root")
    return path


def server_snapshot(section: str) -> dict[str, Any]:
    section = str(section).strip().lower()
    commands: dict[str, list[tuple[str, list[str]]]] = {
        "overview": [
            ("hostname", ["hostname"]),
            ("uptime", ["uptime"]),
            ("kernel", ["uname", "-a"]),
            ("memory", ["free", "-h"]),
        ],
        "systemd": [
            ("failed_units", ["systemctl", "--failed", "--no-pager", "--plain"]),
        ],
        "docker": [
            ("containers", ["docker", "ps", "--format", "table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}"]),
        ],
        "network": [
            ("addresses", ["ip", "-br", "addr"]),
            ("routes", ["ip", "route"]),
            ("listeners", ["ss", "-lntup"]),
        ],
        "storage": [
            ("filesystems", ["df", "-hT"]),
            ("block_devices", ["lsblk", "-o", "NAME,SIZE,FSTYPE,MOUNTPOINTS,MODEL"]),
        ],
        "gpu": [
            ("nvidia_smi", ["nvidia-smi"]),
        ],
        "processes": [
            ("processes", ["ps", "-eo", "pid,user,comm,%cpu,%mem", "--sort=-%cpu"]),
        ],
    }
    if section not in commands:
        raise ValueError("Unknown snapshot section")
    result = {}
    for label, cmd in commands[section]:
        item = run(cmd, timeout=12)
        if section == "processes" and item.get("output"):
            item["output"] = "\n".join(item["output"].splitlines()[:45])
        result[label] = item
    return {"ok": True, "result": result}


def read_meminfo() -> dict[str, Any]:
    values: dict[str, int] = {}
    with open("/proc/meminfo", "r", encoding="utf-8") as handle:
        for line in handle:
            key, raw = line.split(":", 1)
            parts = raw.strip().split()
            if not parts:
                continue
            number = int(parts[0])
            if len(parts) > 1 and parts[1].lower() == "kb":
                number *= 1024
            values[key] = number

    total = values.get("MemTotal", 0)
    available = values.get("MemAvailable", 0)
    free = values.get("MemFree", 0)
    buffers = values.get("Buffers", 0)
    cached = values.get("Cached", 0) + values.get("SReclaimable", 0)
    used = max(0, total - available)

    swap_total = values.get("SwapTotal", 0)
    swap_free = values.get("SwapFree", 0)
    return {
        "total_bytes": total,
        "used_bytes": used,
        "free_bytes": free,
        "available_bytes": available,
        "buffers_bytes": buffers,
        "cached_bytes": cached,
        "swap_total_bytes": swap_total,
        "swap_used_bytes": max(0, swap_total - swap_free),
        "swap_free_bytes": swap_free,
    }


def read_uptime() -> dict[str, Any]:
    with open("/proc/uptime", "r", encoding="utf-8") as handle:
        uptime_seconds = float(handle.read().split()[0])
    return {
        "uptime_seconds": int(uptime_seconds),
        "load_average": list(os.getloadavg()),
    }


def read_filesystems() -> list[dict[str, Any]]:
    result = run(["df", "-PT", "-B1"], timeout=8)
    if not result.get("ok"):
        return [{"error": result.get("error") or result.get("output") or "df failed"}]

    rows: list[dict[str, Any]] = []
    lines = str(result.get("output", "")).splitlines()
    for line in lines[1:]:
        parts = line.split()
        if len(parts) < 7:
            continue
        filesystem, fs_type, size, used, avail, capacity = parts[:6]
        mount = " ".join(parts[6:])
        try:
            rows.append({
                "filesystem": filesystem,
                "type": fs_type,
                "size_bytes": int(size),
                "used_bytes": int(used),
                "available_bytes": int(avail),
                "use_percent": int(capacity.rstrip("%")),
                "mountpoint": mount,
            })
        except ValueError:
            continue
    return rows


def read_docker_containers() -> list[dict[str, str]]:
    result = run(["docker", "ps", "--format", "{{.Names}}\t{{.Status}}"], timeout=10)
    if not result.get("ok"):
        return [{"error": result.get("error") or result.get("output") or "docker ps failed"}]

    rows: list[dict[str, str]] = []
    for line in str(result.get("output", "")).splitlines():
        if not line.strip():
            continue
        name, _, status = line.partition("\t")
        rows.append({"name": name.strip(), "status": status.strip()})
    return rows


def read_failed_units() -> list[dict[str, str]]:
    result = run(
        ["systemctl", "--failed", "--no-legend", "--no-pager", "--plain"],
        timeout=10,
    )
    if not result.get("ok") and result.get("returncode") not in {0, 1}:
        return [{"error": result.get("error") or result.get("output") or "systemctl failed"}]

    rows: list[dict[str, str]] = []
    for line in str(result.get("output", "")).splitlines():
        parts = line.split(None, 4)
        if len(parts) >= 4:
            rows.append({
                "unit": parts[0],
                "load": parts[1],
                "active": parts[2],
                "sub": parts[3],
                "description": parts[4] if len(parts) > 4 else "",
            })
    return rows


def server_health() -> dict[str, Any]:
    return {
        "ok": True,
        "result": {
            "uptime": read_uptime(),
            "memory": read_meminfo(),
            "filesystems": read_filesystems(),
            "docker": read_docker_containers(),
            "failed_systemd": read_failed_units(),
        },
    }


def dispatch(action: str, args: dict[str, Any]) -> dict[str, Any]:
    if action == "server_health":
        return server_health()

    if action == "server_snapshot":
        return server_snapshot(args.get("section", ""))

    if action == "systemd_status":
        unit = valid_unit(str(args.get("unit", "")))
        return {"ok": True, "result": run(["systemctl", "status", unit, "--no-pager", "-l"], timeout=10)}

    if action == "journal":
        unit_raw = str(args.get("unit", "") or "").strip()
        minutes = int_range(args.get("minutes"), 1, 1440, 60)
        lines = int_range(args.get("lines"), 20, 400, 200)
        cmd = ["journalctl", "--since", f"{minutes} min ago", "-n", str(lines), "--no-pager", "-o", "short-iso"]
        if unit_raw:
            cmd[1:1] = ["-u", valid_unit(unit_raw)]
        return {"ok": True, "result": run(cmd, timeout=12)}

    if action == "docker_logs":
        container = valid_container(str(args.get("container", "")))
        lines = int_range(args.get("lines"), 20, 300, 150)
        return {
            "ok": True,
            "result": run(["docker", "logs", "--timestamps", "--tail", str(lines), container], timeout=12),
        }

    if action == "git_status":
        path = safe_repo_path(str(args.get("path", "")))
        status = run(["git", "-C", path, "status", "--short", "--branch"], timeout=8)
        latest = run(["git", "-C", path, "log", "-1", "--oneline", "--decorate"], timeout=8)
        return {"ok": True, "result": {"path": path, "status": status, "latest": latest}}

    return {"ok": False, "error": f"Unknown READ action: {action}"}


class Handler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        try:
            raw = self.rfile.readline(1024 * 1024)
            request = json.loads(raw.decode("utf-8"))
            action = str(request.get("action", ""))
            args = request.get("args") or {}
            if not isinstance(args, dict):
                raise ValueError("args must be an object")
            response = dispatch(action, args)
        except Exception as exc:
            response = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        payload = json.dumps(response, ensure_ascii=False).encode("utf-8")
        self.wfile.write(payload)


class Server(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True


def main() -> None:
    path = Path(SOCKET_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_socket():
        path.unlink()
    server = Server(SOCKET_PATH, Handler)
    os.chown(SOCKET_PATH, SOCKET_UID, SOCKET_GID)
    os.chmod(SOCKET_PATH, 0o660)
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        server.server_close()
        try:
            path.unlink()
        except FileNotFoundError:
            pass


if __name__ == "__main__":
    main()
