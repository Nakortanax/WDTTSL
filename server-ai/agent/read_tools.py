import fnmatch
import json
import os
import re
import socket
from pathlib import Path
from typing import Any


HOST_ROOT = Path("/host")
HOST_SOCKET = os.getenv("HOST_READ_SOCKET", "/run/server-ai/read.sock")
MAX_FILE_BYTES = 512 * 1024
MAX_RESULT_CHARS = 8000

ALLOWED_ROOTS = {
    "/etc": HOST_ROOT / "etc",
    "/var/log": HOST_ROOT / "var" / "log",
    "/home": HOST_ROOT / "home",
    "/opt": HOST_ROOT / "opt",
    "/srv": HOST_ROOT / "srv",
}

DENY_EXACT = {
    "/etc/shadow",
    "/etc/gshadow",
    "/etc/security/opasswd",
}
DENY_PARTS = {".ssh", ".gnupg", ".aws", ".kube", ".config", ".local", ".mozilla", "snap", "private"}
DENY_SUFFIXES = {".key", ".pem", ".p12", ".pfx", ".jks", ".keystore"}
DENY_NAMES = {
    ".env",
    "credentials",
    "credentials.json",
    "secrets",
    "secrets.json",
    "id_rsa",
    "id_ed25519",
}
SECRET_LINE_RE = re.compile(
    r"(?i)(password|passwd|token|secret|api[_-]?key|private[_-]?key|preshared[_-]?key|bot[_-]?token)"
)


def _clip(value: str, limit: int = MAX_RESULT_CHARS) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + f"\n...[truncated {len(value) - limit} chars]"


def _deny_reason(user_path: str, local_path: Path) -> str | None:
    normalized = "/" + user_path.strip().lstrip("/")
    if normalized in DENY_EXACT:
        return "sensitive system credential file"
    lower_name = local_path.name.lower()
    if lower_name == ".env" or lower_name.startswith(".env."):
        return "sensitive environment file"
    if lower_name in DENY_NAMES or any(lower_name.endswith(suffix) for suffix in DENY_SUFFIXES):
        return "sensitive credential/key file"
    if any(part.lower() in DENY_PARTS for part in local_path.parts):
        return "sensitive credential directory"
    if any(word in lower_name for word in ("secret", "token", "password")):
        return "sensitive-looking filename"
    return None


def _map_path(user_path: str, must_exist: bool = True) -> tuple[str, Path]:
    if not user_path or not user_path.startswith("/"):
        raise ValueError("Path must be an absolute host path such as /etc/hosts or /srv/media")
    clean = os.path.normpath(user_path)
    if clean == "/":
        raise PermissionError("Root listing is not exposed; choose /etc, /var/log, /home, /opt or /srv")

    selected_user_root = None
    selected_mount_root = None
    for user_root, mount_root in sorted(ALLOWED_ROOTS.items(), key=lambda item: len(item[0]), reverse=True):
        if clean == user_root or clean.startswith(user_root + "/"):
            selected_user_root = user_root
            selected_mount_root = mount_root
            break

    if selected_user_root is None or selected_mount_root is None:
        raise PermissionError("Path is outside READ-mode roots: /etc, /var/log, /home, /opt, /srv")

    relative = clean[len(selected_user_root):].lstrip("/")
    candidate = selected_mount_root / relative if relative else selected_mount_root
    if must_exist and not candidate.exists():
        raise FileNotFoundError(clean)

    resolved = candidate.resolve(strict=must_exist)
    allowed_resolved = selected_mount_root.resolve(strict=True)
    if resolved != allowed_resolved and allowed_resolved not in resolved.parents:
        raise PermissionError("Symlink/path escapes the allowed read-only mount")

    reason = _deny_reason(clean, resolved)
    if reason:
        raise PermissionError(reason)
    return clean, resolved


def _safe_line(line: str) -> str:
    if SECRET_LINE_RE.search(line):
        if "=" in line:
            return line.split("=", 1)[0] + "=<REDACTED>"
        if ":" in line:
            return line.split(":", 1)[0] + ": <REDACTED>"
        parts = line.split(None, 1)
        if len(parts) == 2 and SECRET_LINE_RE.search(parts[0]):
            return parts[0] + " <REDACTED>"
    return line


def list_files(path: str, limit: int = 100) -> dict[str, Any]:
    clean, local = _map_path(path)
    if not local.is_dir():
        raise NotADirectoryError(clean)
    limit = max(1, min(int(limit), 300))
    entries = []
    for entry in sorted(local.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        if len(entries) >= limit:
            break
        host_path = clean.rstrip("/") + "/" + entry.name
        try:
            reason = _deny_reason(host_path, entry)
            if reason:
                entries.append({"name": entry.name, "type": "restricted"})
                continue
            stat = entry.stat()
            entries.append({
                "name": entry.name,
                "type": "dir" if entry.is_dir() else "file",
                "size": stat.st_size if entry.is_file() else None,
            })
        except (OSError, PermissionError):
            entries.append({"name": entry.name, "type": "unreadable"})
    return {"path": clean, "entries": entries, "limited_to": limit}


def read_text_file(path: str, start_line: int = 1, max_lines: int = 200) -> dict[str, Any]:
    clean, local = _map_path(path)
    if not local.is_file():
        raise IsADirectoryError(clean)
    size = local.stat().st_size
    if size > MAX_FILE_BYTES:
        raise ValueError(f"File is too large for direct READ tool ({size} bytes > {MAX_FILE_BYTES})")

    start_line = max(1, int(start_line))
    max_lines = max(1, min(int(max_lines), 400))
    raw = local.read_bytes()
    if b"\x00" in raw[:4096]:
        raise ValueError("Binary file is not exposed by the text reader")
    text = raw.decode("utf-8", errors="replace")
    lines = text.splitlines()
    selected = lines[start_line - 1:start_line - 1 + max_lines]
    selected = [_safe_line(line) for line in selected]
    content = "\n".join(selected)
    return {
        "path": clean,
        "start_line": start_line,
        "end_line": start_line + len(selected) - 1 if selected else start_line - 1,
        "total_lines": len(lines),
        "content": _clip(content),
    }


def find_files(path: str, name_pattern: str, max_results: int = 100) -> dict[str, Any]:
    clean, local = _map_path(path)
    if not local.is_dir():
        raise NotADirectoryError(clean)
    max_results = max(1, min(int(max_results), 200))
    pattern = name_pattern.strip()
    if not pattern:
        raise ValueError("name_pattern is required")
    if not any(ch in pattern for ch in "*?[]"):
        pattern = f"*{pattern}*"

    results: list[str] = []
    visited = 0
    for root, dirs, files in os.walk(local, followlinks=False):
        root_path = Path(root)
        dirs[:] = [
            d for d in dirs
            if _deny_reason(str(root_path / d), root_path / d) is None
            and not d.startswith(".cache")
        ]
        for name in dirs + files:
            visited += 1
            if visited > 12000:
                break
            if fnmatch.fnmatch(name.lower(), pattern.lower()):
                local_match = root_path / name
                rel = local_match.relative_to(local)
                host_match = clean.rstrip("/") + "/" + str(rel)
                if _deny_reason(host_match, local_match) is None:
                    results.append(host_match)
                    if len(results) >= max_results:
                        break
        if len(results) >= max_results or visited > 12000:
            break
    return {"path": clean, "pattern": name_pattern, "results": results, "scanned_entries": visited}


def search_text(path: str, query: str, max_results: int = 50) -> dict[str, Any]:
    clean, local = _map_path(path)
    if not local.is_dir():
        raise NotADirectoryError(clean)
    needle = query.strip()
    if not needle:
        raise ValueError("query is required")
    max_results = max(1, min(int(max_results), 100))
    results = []
    scanned_files = 0

    for root, dirs, files in os.walk(local, followlinks=False):
        root_path = Path(root)
        dirs[:] = [
            d for d in dirs
            if _deny_reason(str(root_path / d), root_path / d) is None
            and d not in {".git", "__pycache__", "node_modules", ".gradle", "build"}
        ]
        for name in files:
            if scanned_files >= 3000 or len(results) >= max_results:
                break
            file_path = root_path / name
            host_path = clean.rstrip("/") + "/" + str(file_path.relative_to(local))
            if _deny_reason(host_path, file_path) is not None:
                continue
            try:
                if not file_path.is_file() or file_path.stat().st_size > 1024 * 1024:
                    continue
                raw = file_path.read_bytes()
                if b"\x00" in raw[:4096]:
                    continue
                scanned_files += 1
                for idx, line in enumerate(raw.decode("utf-8", errors="replace").splitlines(), start=1):
                    if needle.casefold() in line.casefold():
                        results.append({
                            "path": host_path,
                            "line": idx,
                            "text": _safe_line(line)[:600],
                        })
                        if len(results) >= max_results:
                            break
            except (OSError, PermissionError):
                continue
        if scanned_files >= 3000 or len(results) >= max_results:
            break
    return {"path": clean, "query": needle, "results": results, "scanned_files": scanned_files}


def host_call(action: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    request = json.dumps({"action": action, "args": args or {}}, ensure_ascii=False).encode("utf-8") + b"\n"
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(12.0)
    try:
        client.connect(HOST_SOCKET)
        client.sendall(request)
        chunks = []
        total = 0
        while True:
            chunk = client.recv(65536)
            if not chunk:
                break
            total += len(chunk)
            if total > 1024 * 1024:
                raise RuntimeError("Host READ response exceeded 1 MiB")
            chunks.append(chunk)
        response = json.loads(b"".join(chunks).decode("utf-8"))
    finally:
        client.close()
    return response


def execute_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    try:
        if name == "list_files":
            return {"ok": True, "result": list_files(**arguments)}
        if name == "read_text_file":
            return {"ok": True, "result": read_text_file(**arguments)}
        if name == "find_files":
            return {"ok": True, "result": find_files(**arguments)}
        if name == "search_text":
            return {"ok": True, "result": search_text(**arguments)}
        if name in {"server_snapshot", "systemd_status", "journal", "docker_logs", "git_status"}:
            return host_call(name, arguments)
        return {"ok": False, "error": f"Unknown READ tool: {name}"}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List a host directory in READ mode. Allowed roots: /etc, /var/log, /home, /opt, /srv. Sensitive credential paths are restricted.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Absolute host directory path."},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 300},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_text_file",
            "description": "Read a bounded text file from allowed host roots. Common secret lines are redacted and credential/key files are blocked.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "start_line": {"type": "integer", "minimum": 1},
                    "max_lines": {"type": "integer", "minimum": 1, "maximum": 400},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_files",
            "description": "Find files/directories by name under an allowed host directory. Supports glob patterns.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "name_pattern": {"type": "string"},
                    "max_results": {"type": "integer", "minimum": 1, "maximum": 200},
                },
                "required": ["path", "name_pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_text",
            "description": "Search text recursively in readable text files under an allowed host directory. Bounded and secret-aware.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "query": {"type": "string"},
                    "max_results": {"type": "integer", "minimum": 1, "maximum": 100},
                },
                "required": ["path", "query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "server_snapshot",
            "description": "Get a current read-only server diagnostic snapshot from the host.",
            "parameters": {
                "type": "object",
                "properties": {
                    "section": {
                        "type": "string",
                        "enum": ["overview", "systemd", "docker", "network", "storage", "gpu", "processes"],
                    }
                },
                "required": ["section"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "systemd_status",
            "description": "Read systemctl status for one systemd unit without changing it.",
            "parameters": {
                "type": "object",
                "properties": {"unit": {"type": "string"}},
                "required": ["unit"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "journal",
            "description": "Read recent journal entries, optionally for a specific unit. This is read-only.",
            "parameters": {
                "type": "object",
                "properties": {
                    "unit": {"type": "string", "description": "Optional systemd unit such as csqtt.service."},
                    "minutes": {"type": "integer", "minimum": 1, "maximum": 1440},
                    "lines": {"type": "integer", "minimum": 20, "maximum": 400},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "docker_logs",
            "description": "Read recent logs from an existing Docker container. Cannot start/stop/remove containers.",
            "parameters": {
                "type": "object",
                "properties": {
                    "container": {"type": "string"},
                    "lines": {"type": "integer", "minimum": 20, "maximum": 300},
                },
                "required": ["container"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_status",
            "description": "Inspect Git branch/status and latest commit for a repository under /home, /opt or /srv. No Git write operations are allowed.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
]
