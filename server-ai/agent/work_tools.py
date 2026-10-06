import json
import os
import socket
from typing import Any


HOST_WORK_SOCKET = os.getenv("HOST_WORK_SOCKET", "/run/server-ai/work.sock")
MAX_RESPONSE_BYTES = 2 * 1024 * 1024

WORK_TOOL_NAMES = {
    "work_status",
    "work_list_files",
    "work_read_file",
    "work_create_branch",
    "work_write_file",
    "work_diff",
    "work_check",
}


def host_work_call(action: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    request = json.dumps({"action": action, "args": args or {}}, ensure_ascii=False).encode("utf-8") + b"\n"
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(30.0)
    try:
        client.connect(HOST_WORK_SOCKET)
        client.sendall(request)
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = client.recv(65536)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_RESPONSE_BYTES:
                raise RuntimeError("Host WORK response exceeded 2 MiB")
            chunks.append(chunk)
        return json.loads(b"".join(chunks).decode("utf-8"))
    finally:
        client.close()


def execute_work_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    try:
        if name not in WORK_TOOL_NAMES:
            return {"ok": False, "error": f"Unknown WORK tool: {name}"}
        return host_work_call(name, arguments)
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


WORK_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "work_status",
            "description": (
                "Inspect an approved isolated Git worktree. Returns workspace path, current branch, HEAD, "
                "dirty state and changed files. WORK mode never operates directly in the deployment checkout."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "workspace": {"type": "string", "description": "Approved workspace id, normally wdttsl."},
                },
                "required": ["workspace"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "work_list_files",
            "description": (
                "List files inside an approved isolated Git worktree. Paths are relative to the workspace root. "
                "Credential-like paths and .git internals are blocked."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "workspace": {"type": "string"},
                    "path": {"type": "string", "description": "Relative directory path, or '.' for workspace root."},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 200},
                },
                "required": ["workspace", "path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "work_read_file",
            "description": (
                "Read one text file from an approved isolated Git worktree. Returns content and sha256. "
                "Use the sha256 as expected_sha256 when replacing an existing file."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "workspace": {"type": "string"},
                    "path": {"type": "string", "description": "Relative file path inside the workspace."},
                    "max_chars": {"type": "integer", "minimum": 500, "maximum": 20000},
                },
                "required": ["workspace", "path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "work_create_branch",
            "description": (
                "Create and switch the isolated worktree to a new ai/... branch. Refuses dirty worktrees and "
                "never switches the deployment checkout."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "workspace": {"type": "string"},
                    "branch": {
                        "type": "string",
                        "description": "New branch name beginning with ai/, for example ai/fix-health-output.",
                    },
                },
                "required": ["workspace", "branch"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "work_write_file",
            "description": (
                "Create or replace one text file inside an approved isolated worktree. Existing files require "
                "the sha256 returned by work_read_file. Writes are allowed only while on an ai/... branch. "
                "Deletion, rename, chmod, secrets and .git internals are not exposed."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "workspace": {"type": "string"},
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                    "expected_sha256": {
                        "type": ["string", "null"],
                        "description": "Required sha256 for an existing file; null only for a new file.",
                    },
                },
                "required": ["workspace", "path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "work_diff",
            "description": (
                "Show the bounded Git diff and diff --check result for the isolated worktree. "
                "Use after edits before reporting completion."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "workspace": {"type": "string"},
                    "max_chars": {"type": "integer", "minimum": 1000, "maximum": 20000},
                },
                "required": ["workspace"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "work_check",
            "description": (
                "Run one allowlisted non-destructive check in the isolated worktree. "
                "Available checks are returned by work_status; arbitrary shell commands are not accepted."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "workspace": {"type": "string"},
                    "check": {"type": "string", "description": "Allowlisted check id."},
                },
                "required": ["workspace", "check"],
            },
        },
    },
]
