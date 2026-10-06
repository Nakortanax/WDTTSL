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
    base_ref = str(data.get("base_ref") or "").strip()
    base_head = ""
    behind_base = False
    if base_ref:
        base_head = _require_ok(
            _git(root, ["rev-parse", "--short=12", base_ref]),
            "git rev-parse base_ref",
        )["stdout"].strip()
        behind_base = head != base_head
    entries = _dirty_entries(root)
    checks = data.get("checks") or ["diff-check", "server-ai-python"]
    return {
        "workspace": workspace,
        "worktree": str(root),
        "source_repo": str(data.get("source_repo") or ""),
        "base_ref": base_ref,
        "base_head": base_head,
        "behind_base": behind_base,
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


def work_read_file(
    workspace: str,
    path: str,
    start_line: int = 1,
    max_lines: int = 80,
) -> dict[str, Any]:
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
    lines = text.splitlines()
    start_line = max(1, int(start_line))
    max_lines = max(1, min(int(max_lines), 160))
    selected = lines[start_line - 1:start_line - 1 + max_lines]
    content = "\n".join(selected)
    return {
        "workspace": workspace,
        "path": path,
        "sha256": digest,
        "size": size,
        "start_line": start_line,
        "end_line": start_line + len(selected) - 1 if selected else start_line - 1,
        "total_lines": len(lines),
        "content": _clip(content, 16000),
    }


def work_search_text(
    workspace: str,
    query: str,
    path: str = ".",
    max_results: int = 30,
) -> dict[str, Any]:
    _, root = _workspace(workspace)
    base = _safe_path(root, path, must_exist=True, allow_root=True)
    if not base.is_dir():
        raise NotADirectoryError(path)
    needle = str(query or "").strip()
    if not needle:
        raise ValueError("query is required")
    max_results = max(1, min(int(max_results), 60))
    results = []
    scanned = 0
    skip_dirs = {".git", "__pycache__", "node_modules", ".gradle", ".venv", "venv", "build", "dist"}

    for current_root, dirs, files in os.walk(base, followlinks=False):
        root_path = Path(current_root)
        dirs[:] = [
            name for name in dirs
            if name not in skip_dirs
            and not (root_path / name).is_symlink()
            and _deny_reason((root_path / name).relative_to(root)) is None
        ]
        for name in files:
            if len(results) >= max_results or scanned >= 2500:
                break
            file_path = root_path / name
            if file_path.is_symlink():
                continue
            rel = file_path.relative_to(root)
            if _deny_reason(rel) is not None:
                continue
            try:
                if not file_path.is_file() or file_path.stat().st_size > 1024 * 1024:
                    continue
                raw = file_path.read_bytes()
                if b"\x00" in raw[:4096]:
                    continue
                scanned += 1
                for line_no, line in enumerate(raw.decode("utf-8", errors="replace").splitlines(), start=1):
                    if needle.casefold() in line.casefold():
                        results.append({
                            "path": str(rel),
                            "line": line_no,
                            "text": line[:500],
                        })
                        if len(results) >= max_results:
                            break
            except (OSError, PermissionError):
                continue
        if len(results) >= max_results or scanned >= 2500:
            break

    return {
        "workspace": workspace,
        "path": path,
        "query": needle,
        "results": results,
        "scanned_files": scanned,
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
    data, root = _workspace(workspace)
    branch = _validate_branch_name(branch)
    dirty = _dirty_entries(root)
    if dirty:
        raise RuntimeError("Worktree has uncommitted changes; branch creation is blocked")
    exists = _git(root, ["show-ref", "--verify", "--quiet", f"refs/heads/{branch}"])
    if exists["returncode"] == 0:
        raise FileExistsError(f"Branch already exists: {branch}")

    base_ref = str(data.get("base_ref") or "").strip()
    if not base_ref:
        raise RuntimeError("Workspace has no configured base_ref")

    _require_ok(_git(root, ["rev-parse", "--verify", base_ref]), "git verify base_ref")
    result = _require_ok(
        _git(root, ["switch", "-c", branch, base_ref]),
        "git switch -c from base_ref",
    )
    return {
        "workspace": workspace,
        "branch": branch,
        "base_ref": base_ref,
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

    if expected_sha256:
        raise ValueError("work_write_file creates new files only; edit existing files with work_replace_text/work_insert_text")

    encoded = str(content).encode("utf-8")
    if len(encoded) > MAX_FILE_BYTES:
        raise ValueError(f"Content exceeds WORK write limit ({len(encoded)} > {MAX_FILE_BYTES} bytes)")
    if b"\x00" in encoded:
        raise ValueError("Binary content is not allowed")

    local = _safe_path(root, path, must_exist=False)
    if local.exists():
        raise FileExistsError("work_write_file cannot replace an existing file; use work_replace_text/work_insert_text")

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
        os.chmod(temp_name, 0o644)
        os.replace(temp_name, local)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)

    return {
        "workspace": workspace,
        "path": path,
        "branch": branch,
        "created": True,
        "size": len(encoded),
        "sha256": hashlib.sha256(encoded).hexdigest(),
    }



def work_replace_text(
    workspace: str,
    path: str,
    old_text: str,
    new_text: str,
    expected_sha256: str,
) -> dict[str, Any]:
    _, root = _workspace(workspace)
    branch = _branch(root)
    if not branch.startswith("ai/"):
        raise PermissionError("Writes require an isolated ai/... branch")

    local = _safe_path(root, path, must_exist=True)
    if local.is_symlink() or not local.is_file():
        raise PermissionError("Only regular text files can be edited")

    raw = local.read_bytes()
    if len(raw) > MAX_FILE_BYTES:
        raise ValueError(f"File exceeds WORK write limit ({len(raw)} > {MAX_FILE_BYTES} bytes)")
    if b"\x00" in raw[:4096]:
        raise ValueError("Binary files are not editable in WORK mode")

    current_sha = hashlib.sha256(raw).hexdigest()
    if not expected_sha256 or expected_sha256 != current_sha:
        raise RuntimeError("File changed since it was read; sha256 mismatch")

    old_text = str(old_text)
    new_text = str(new_text)
    if not old_text:
        raise ValueError("old_text must not be empty")
    text = raw.decode("utf-8")
    count = text.count(old_text)
    if count != 1:
        raise RuntimeError(f"old_text must match exactly once; matches={count}")

    updated = text.replace(old_text, new_text, 1)
    encoded = updated.encode("utf-8")
    if len(encoded) > MAX_FILE_BYTES:
        raise ValueError(f"Updated file exceeds WORK write limit ({len(encoded)} > {MAX_FILE_BYTES} bytes)")

    old_mode = stat.S_IMODE(local.stat().st_mode)
    fd, temp_name = tempfile.mkstemp(prefix=".server-ai-work-", dir=str(local.parent))
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

    return {
        "workspace": workspace,
        "path": path,
        "branch": branch,
        "replacements": 1,
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "size": len(encoded),
    }



def work_insert_text(
    workspace: str,
    path: str,
    anchor: str,
    text: str,
    position: str,
    expected_sha256: str,
) -> dict[str, Any]:
    _, root = _workspace(workspace)
    branch = _branch(root)
    if not branch.startswith("ai/"):
        raise PermissionError("Writes require an isolated ai/... branch")

    local = _safe_path(root, path, must_exist=True)
    if local.is_symlink() or not local.is_file():
        raise PermissionError("Only regular text files can be edited")

    raw = local.read_bytes()
    if len(raw) > MAX_FILE_BYTES:
        raise ValueError(f"File exceeds WORK write limit ({len(raw)} > {MAX_FILE_BYTES} bytes)")
    if b"\x00" in raw[:4096]:
        raise ValueError("Binary files are not editable in WORK mode")

    current_sha = hashlib.sha256(raw).hexdigest()
    if not expected_sha256 or expected_sha256 != current_sha:
        raise RuntimeError("File changed since it was read; sha256 mismatch")

    anchor = str(anchor)
    insertion = str(text)
    if not anchor:
        raise ValueError("anchor must not be empty")
    if position not in {"before", "after"}:
        raise ValueError("position must be 'before' or 'after'")

    source = raw.decode("utf-8")
    count = source.count(anchor)
    if count != 1:
        raise RuntimeError(f"anchor must match exactly once; matches={count}")

    replacement = insertion + anchor if position == "before" else anchor + insertion
    updated = source.replace(anchor, replacement, 1)
    encoded = updated.encode("utf-8")
    if len(encoded) > MAX_FILE_BYTES:
        raise ValueError(f"Updated file exceeds WORK write limit ({len(encoded)} > {MAX_FILE_BYTES} bytes)")

    old_mode = stat.S_IMODE(local.stat().st_mode)
    fd, temp_name = tempfile.mkstemp(prefix=".server-ai-work-", dir=str(local.parent))
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

    return {
        "workspace": workspace,
        "path": path,
        "branch": branch,
        "position": position,
        "insertions": 1,
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "size": len(encoded),
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
    "work_search_text": work_search_text,
    "work_create_branch": work_create_branch,
    "work_write_file": work_write_file,
    "work_replace_text": work_replace_text,
    "work_insert_text": work_insert_text,
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
