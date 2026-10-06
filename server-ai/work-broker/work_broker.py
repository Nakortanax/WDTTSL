#!/usr/bin/env python3
import hashlib
import json
import os
import pwd
import re
import socket
import socketserver
import stat
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any


CONFIG_PATH = Path(os.getenv("SERVER_AI_WORK_CONFIG", "/etc/server-ai/workspaces.json"))
DEFAULT_SOCKET = "/run/server-ai/work/work.sock"
MAX_REQUEST_BYTES = 1024 * 1024
MAX_FILE_BYTES = 512 * 1024
MAX_RESULT_CHARS = 20000

BRANCH_RE = re.compile(r"^ai/[a-z0-9][a-z0-9._/-]{0,60}$")
DENY_PARTS = {".git", ".ssh", ".gnupg", ".aws", ".kube", ".config", ".local", ".mozilla", "private"}
DENY_NAMES = {
    ".env",
    "credentials",
    "credentials.json",
    "secrets",
    "secrets.json",
    "id_rsa",
    "id_ed25519",
}
DENY_SUFFIXES = {".key", ".pem", ".p12", ".pfx", ".jks", ".keystore"}


def _clip(value: str, limit: int = MAX_RESULT_CHARS) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + f"\n...[truncated {len(value) - limit} chars]"


def _load_config() -> dict[str, Any]:
    raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise RuntimeError("WORK config must be a JSON object")
    workspaces = raw.get("workspaces")
    if not isinstance(workspaces, dict) or not workspaces:
        raise RuntimeError("WORK config has no workspaces")
    return raw


CONFIG = _load_config()
SOCKET_PATH = str(CONFIG.get("socket") or DEFAULT_SOCKET)


def _workspace(workspace_id: str) -> tuple[dict[str, Any], Path]:
    workspace_id = str(workspace_id or "").strip()
    workspaces = CONFIG["workspaces"]
    data = workspaces.get(workspace_id)
    if not isinstance(data, dict):
        raise PermissionError(f"Unknown WORK workspace: {workspace_id}")
    root = Path(str(data.get("worktree") or "")).resolve(strict=True)
    if not root.is_dir():
        raise NotADirectoryError(str(root))
    git_dir = root / ".git"
    if not git_dir.exists():
        raise RuntimeError("Configured WORK path is not a Git worktree")
    return data, root


def _deny_reason(path: Path) -> str | None:
    name = path.name.lower()
    if name == ".env" or name.startswith(".env."):
        return "environment files are not exposed in WORK mode"
    if name in DENY_NAMES:
        return "credential-like file is blocked"
    if any(name.endswith(suffix) for suffix in DENY_SUFFIXES):
        return "key/certificate file is blocked"
    if any(part.lower() in DENY_PARTS for part in path.parts):
        return "restricted path component"
    if any(word in name for word in ("secret", "token", "password")):
        return "sensitive-looking filename is blocked"
    return None


def _safe_path(root: Path, relative: str, must_exist: bool = True, allow_root: bool = False) -> Path:
    relative = str(relative or "").strip()
    if relative in {"", "."}:
        if allow_root:
            return root
        raise ValueError("A relative file path is required")
    rel = Path(relative)
    if rel.is_absolute() or ".." in rel.parts:
        raise PermissionError("Path must stay inside the approved workspace")
    if any(part in {"", "."} for part in rel.parts):
        raise ValueError("Invalid relative path")
    if any(part.lower() == ".git" for part in rel.parts):
        raise PermissionError(".git internals are not exposed")

    current = root
    for part in rel.parts:
        current = current / part
        if current.exists() and current.is_symlink():
            raise PermissionError("Symlink paths are not writable/readable in WORK mode")

    candidate = root / rel
    resolved_root = root.resolve(strict=True)
    resolved = candidate.resolve(strict=must_exist)
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise PermissionError("Path escapes the approved workspace")

    reason = _deny_reason(rel)
    if reason:
        raise PermissionError(reason)
    return resolved


def _git_env() -> dict[str, str]:
    uid = os.getuid()
    try:
        home = pwd.getpwuid(uid).pw_dir
    except KeyError:
        home = "/tmp"
    return {
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "HOME": home,
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "GIT_TERMINAL_PROMPT": "0",
    }


def _run(
    argv: list[str],
    cwd: Path,
    timeout: int = 20,
) -> dict[str, Any]:
    started = time.monotonic()
    proc = subprocess.run(
        argv,
        cwd=str(cwd),
        env=_git_env(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
    elapsed = time.monotonic() - started
    return {
        "returncode": proc.returncode,
        "stdout": _clip(proc.stdout),
        "stderr": _clip(proc.stderr),
        "elapsed_seconds": round(elapsed, 3),
    }


def _git(root: Path, args: list[str], timeout: int = 20) -> dict[str, Any]:
    return _run(
        ["git", "-c", "core.hooksPath=/dev/null", "-C", str(root), *args],
        cwd=root,
        timeout=timeout,
    )


def _require_ok(result: dict[str, Any], what: str) -> dict[str, Any]:
    if int(result.get("returncode", 1)) != 0:
        detail = (result.get("stderr") or result.get("stdout") or "").strip()
        raise RuntimeError(f"{what} failed: {detail[:1200]}")
    return result


def _branch(root: Path) -> str:
    result = _git(root, ["symbolic-ref", "--quiet", "--short", "HEAD"])
    if result["returncode"] == 0:
        return result["stdout"].strip()
    return "DETACHED"


def _dirty_entries(root: Path) -> list[str]:
    result = _require_ok(_git(root, ["status", "--porcelain=v1", "--untracked-files=all"]), "git status")
    return [line for line in result["stdout"].splitlines() if line.strip()]


def work_status(workspace: str) -> dict[str, Any]:
    data, root = _workspace(workspace)
    head = _require_ok(_git(root, ["rev-parse", "--short=12", "HEAD"]), "git rev-parse")["stdout"].strip()
    entries = _dirty_entries(root)
    checks = data.get("checks") or ["diff-check", "server-ai-python"]
    return {
        "workspace": workspace,
        "worktree": str(root),
        "source_repo": str(data.get("source_repo") or ""),
        "branch": _branch(root),
        "head": head,
        "dirty": bool(entries),
        "changes": entries[:100],
        "allowed_checks": list(checks),
        "policy": {
            "branch_prefix": "ai/",
            "commit": False,
            "push": False,
            "delete": False,
            "arbitrary_shell": False,
        },
    }


def work_list_files(workspace: str, path: str = ".", limit: int = 100) -> dict[str, Any]:
    _, root = _workspace(workspace)
    local = _safe_path(root, path, must_exist=True, allow_root=True)
    if not local.is_dir():
        raise NotADirectoryError(path)
    limit = max(1, min(int(limit), 200))
    entries = []
    for entry in sorted(local.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
        if len(entries) >= limit:
            break
        rel = entry.relative_to(root)
        reason = _deny_reason(rel)
        if reason or entry.name == ".git":
            entries.append({"name": entry.name, "type": "restricted"})
            continue
        if entry.is_symlink():
            entries.append({"name": entry.name, "type": "symlink-restricted"})
            continue
        try:
            size = entry.stat().st_size if entry.is_file() else None
        except OSError:
            size = None
        entries.append({
            "name": entry.name,
            "path": str(rel),
            "type": "dir" if entry.is_dir() else "file",
            "size": size,
        })
    return {"workspace": workspace, "path": path, "entries": entries}


def work_read_file(workspace: str, path: str, max_chars: int = 12000) -> dict[str, Any]:
    _, root = _workspace(workspace)
    local = _safe_path(root, path, must_exist=True)
    if not local.is_file():
        raise IsADirectoryError(path)
    size = local.stat().st_size
    if size > MAX_FILE_BYTES:
        raise ValueError(f"File exceeds WORK read limit ({size} > {MAX_FILE_BYTES} bytes)")
    raw = local.read_bytes()
    if b"\x00" in raw[:4096]:
        raise ValueError("Binary files are not exposed in WORK mode")
    digest = hashlib.sha256(raw).hexdigest()
    text = raw.decode("utf-8", errors="replace")
    max_chars = max(500, min(int(max_chars), MAX_RESULT_CHARS))
    return {
        "workspace": workspace,
        "path": path,
        "sha256": digest,
        "size": size,
        "truncated": len(text) > max_chars,
        "content": _clip(text, max_chars),
    }


def _validate_branch_name(branch: str) -> str:
    branch = str(branch or "").strip().lower()
    if not BRANCH_RE.fullmatch(branch):
        raise ValueError("WORK branch must match ai/<safe-name>")
    if ".." in branch or "@{" in branch or branch.endswith(("/", ".", ".lock")):
        raise ValueError("Invalid branch name")
    result = subprocess.run(
        ["git", "check-ref-format", "--branch", branch],
        env=_git_env(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise ValueError("Git rejected the branch name")
    return branch


def work_create_branch(workspace: str, branch: str) -> dict[str, Any]:
    _, root = _workspace(workspace)
    branch = _validate_branch_name(branch)
    dirty = _dirty_entries(root)
    if dirty:
        raise RuntimeError("Worktree has uncommitted changes; branch creation is blocked")
    exists = _git(root, ["show-ref", "--verify", "--quiet", f"refs/heads/{branch}"])
    if exists["returncode"] == 0:
        raise FileExistsError(f"Branch already exists: {branch}")
    result = _require_ok(_git(root, ["switch", "-c", branch]), "git switch -c")
    return {
        "workspace": workspace,
        "branch": branch,
        "head": _require_ok(_git(root, ["rev-parse", "--short=12", "HEAD"]), "git rev-parse")["stdout"].strip(),
        "message": result["stderr"].strip() or result["stdout"].strip(),
    }


def work_write_file(
    workspace: str,
    path: str,
    content: str,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    _, root = _workspace(workspace)
    branch = _branch(root)
    if not branch.startswith("ai/"):
        raise PermissionError("Writes require an isolated ai/... branch")

    encoded = str(content).encode("utf-8")
    if len(encoded) > MAX_FILE_BYTES:
        raise ValueError(f"Content exceeds WORK write limit ({len(encoded)} > {MAX_FILE_BYTES} bytes)")
    if b"\x00" in encoded:
        raise ValueError("Binary content is not allowed")

    local = _safe_path(root, path, must_exist=False)
    existed = local.exists()
    old_mode = 0o644

    if existed:
        if local.is_symlink() or not local.is_file():
            raise PermissionError("Only regular text files can be replaced")
        old_raw = local.read_bytes()
        current_sha = hashlib.sha256(old_raw).hexdigest()
        if not expected_sha256:
            raise ValueError("expected_sha256 is required when replacing an existing file")
        if expected_sha256 != current_sha:
            raise RuntimeError("File changed since it was read; sha256 mismatch")
        old_mode = stat.S_IMODE(local.stat().st_mode)
    elif expected_sha256:
        raise RuntimeError("expected_sha256 was supplied for a file that does not exist")

    parent = local.parent
    parent.mkdir(parents=True, exist_ok=True)
    resolved_parent = parent.resolve(strict=True)
    resolved_root = root.resolve(strict=True)
    if resolved_parent != resolved_root and resolved_root not in resolved_parent.parents:
        raise PermissionError("Parent directory escapes the approved workspace")

    fd, temp_name = tempfile.mkstemp(prefix=".server-ai-work-", dir=str(parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_name, old_mode)
        os.replace(temp_name, local)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)

    new_sha = hashlib.sha256(encoded).hexdigest()
    return {
        "workspace": workspace,
        "path": path,
        "branch": branch,
        "created": not existed,
        "size": len(encoded),
        "sha256": new_sha,
    }


def work_diff(workspace: str, max_chars: int = 12000) -> dict[str, Any]:
    _, root = _workspace(workspace)
    max_chars = max(1000, min(int(max_chars), MAX_RESULT_CHARS))
    diff = _require_ok(_git(root, ["diff", "--no-ext-diff", "--"]), "git diff")
    check = _git(root, ["diff", "--check"])
    status = _require_ok(_git(root, ["status", "--short"]), "git status")
    return {
        "workspace": workspace,
        "branch": _branch(root),
        "status": status["stdout"].splitlines()[:100],
        "diff": _clip(diff["stdout"], max_chars),
        "diff_truncated": len(diff["stdout"]) > max_chars,
        "diff_check_ok": check["returncode"] == 0,
        "diff_check": _clip((check["stdout"] + check["stderr"]).strip(), 4000),
    }


def _python_compile_check(root: Path) -> dict[str, Any]:
    files = [
        "server-ai/agent/app.py",
        "server-ai/agent/read_tools.py",
        "server-ai/agent/web_tools.py",
        "server-ai/agent/work_tools.py",
        "server-ai/work-broker/work_broker.py",
    ]
    code = (
        "from pathlib import Path\n"
        "files = " + repr(files) + "\n"
        "done=[]\n"
        "for name in files:\n"
        "    p=Path(name)\n"
        "    if p.exists():\n"
        "        compile(p.read_text(encoding='utf-8'), name, 'exec')\n"
        "        done.append(name)\n"
        "print('compiled:', ', '.join(done))\n"
    )
    return _run(["python3", "-c", code], cwd=root, timeout=30)


def work_check(workspace: str, check: str) -> dict[str, Any]:
    data, root = _workspace(workspace)
    check = str(check or "").strip()
    allowed = set(data.get("checks") or ["diff-check", "server-ai-python"])
    if check not in allowed:
        raise PermissionError(f"Check is not allowlisted: {check}")

    if check == "diff-check":
        result = _git(root, ["diff", "--check"])
    elif check == "server-ai-python":
        result = _python_compile_check(root)
    else:
        raise PermissionError(f"Unknown allowlisted check implementation: {check}")

    return {
        "workspace": workspace,
        "check": check,
        "ok": result["returncode"] == 0,
        "returncode": result["returncode"],
        "stdout": result["stdout"],
        "stderr": result["stderr"],
        "elapsed_seconds": result["elapsed_seconds"],
    }


ACTIONS = {
    "work_status": work_status,
    "work_list_files": work_list_files,
    "work_read_file": work_read_file,
    "work_create_branch": work_create_branch,
    "work_write_file": work_write_file,
    "work_diff": work_diff,
    "work_check": work_check,
}


class WorkHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        raw = self.rfile.readline(MAX_REQUEST_BYTES + 1)
        if len(raw) > MAX_REQUEST_BYTES:
            response = {"ok": False, "error": "Request exceeds 1 MiB"}
        else:
            try:
                request = json.loads(raw.decode("utf-8"))
                action = str(request.get("action") or "")
                args = request.get("args") or {}
                if action not in ACTIONS:
                    raise PermissionError(f"Action is not allowlisted: {action}")
                if not isinstance(args, dict):
                    raise ValueError("args must be a JSON object")

                started = time.monotonic()
                result = ACTIONS[action](**args)
                elapsed = time.monotonic() - started
                workspace = str(args.get("workspace") or "-")
                path = str(args.get("path") or "-")
                print(
                    f"[WORK-BROKER] action={action} workspace={workspace} path={path} elapsed={elapsed:.3f}s",
                    flush=True,
                )
                response = {"ok": True, "result": result}
            except Exception as exc:
                print(
                    f"[WORK-BROKER] error action={locals().get('action', '?')} type={type(exc).__name__}",
                    flush=True,
                )
                response = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

        self.wfile.write(json.dumps(response, ensure_ascii=False).encode("utf-8") + b"\n")


class WorkServer(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True


def main() -> None:
    socket_path = Path(SOCKET_PATH)
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    if socket_path.exists() or socket_path.is_symlink():
        mode = socket_path.lstat().st_mode
        if not stat.S_ISSOCK(mode):
            raise RuntimeError(f"Refusing to replace non-socket path: {socket_path}")
        socket_path.unlink()

    old_umask = os.umask(0o117)
    try:
        with WorkServer(str(socket_path), WorkHandler) as server:
            os.chmod(socket_path, 0o660)
            print(f"[WORK-BROKER] listening socket={socket_path}", flush=True)
            server.serve_forever(poll_interval=0.5)
    finally:
        os.umask(old_umask)
        try:
            if socket_path.exists() and stat.S_ISSOCK(socket_path.lstat().st_mode):
                socket_path.unlink()
        except OSError:
            pass


if __name__ == "__main__":
    main()
