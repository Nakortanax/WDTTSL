#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run with sudo: sudo ./install-work-broker.sh" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "${SCRIPT_DIR}/.." rev-parse --show-toplevel)"
RUN_USER="$(stat -c '%U' "${REPO_ROOT}")"
RUN_GROUP="$(stat -c '%G' "${REPO_ROOT}")"

if [[ -z "${RUN_USER}" || "${RUN_USER}" == "root" ]]; then
  echo "Refusing to install WORK broker for a root-owned source repository: ${REPO_ROOT}" >&2
  exit 1
fi

WORKSPACE_ID="wdttsl"
WORKTREE_ROOT="/var/lib/server-ai/workspaces"
WORKTREE_DIR="${WORKTREE_ROOT}/${WORKSPACE_ID}"
RUNTIME_DIR="/run/server-ai/work"
SOCKET_PATH="${RUNTIME_DIR}/work.sock"
LIB_DIR="/usr/local/lib/server-ai"
BROKER_DST="${LIB_DIR}/work_broker.py"
CONFIG_DIR="/etc/server-ai"
CONFIG_PATH="${CONFIG_DIR}/workspaces.json"
UNIT_PATH="/etc/systemd/system/server-ai-work.service"

if BASE_REF="$(git -C "${REPO_ROOT}" symbolic-ref --quiet --short HEAD 2>/dev/null)"; then
  :
else
  BASE_REF="$(git -C "${REPO_ROOT}" rev-parse HEAD)"
fi

echo "=== SERVER AI WORK INSTALL ==="
echo "source repo : ${REPO_ROOT}"
echo "run user    : ${RUN_USER}:${RUN_GROUP}"
echo "base ref    : ${BASE_REF}"
echo "worktree    : ${WORKTREE_DIR}"
echo "socket      : ${SOCKET_PATH}"

install -d -m 0755 -o root -g root "${LIB_DIR}" "${CONFIG_DIR}"
install -d -m 0755 -o "${RUN_USER}" -g "${RUN_GROUP}" "${WORKTREE_ROOT}" "${RUNTIME_DIR}"

if [[ ! -e "${WORKTREE_DIR}/.git" ]]; then
  if [[ -e "${WORKTREE_DIR}" ]] && [[ -n "$(find "${WORKTREE_DIR}" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]]; then
    echo "Refusing to reuse non-empty non-worktree directory: ${WORKTREE_DIR}" >&2
    exit 1
  fi
  if [[ -d "${WORKTREE_DIR}" ]]; then
    rmdir "${WORKTREE_DIR}"
  fi
  echo "Creating isolated detached Git worktree..."
  runuser -u "${RUN_USER}" --     git -c core.hooksPath=/dev/null -C "${REPO_ROOT}"     worktree add --detach "${WORKTREE_DIR}" "${BASE_REF}"
else
  echo "Existing isolated worktree preserved."
fi

install -m 0644 -o root -g root   "${SCRIPT_DIR}/work-broker/work_broker.py"   "${BROKER_DST}"

python3 - "${CONFIG_PATH}" "${REPO_ROOT}" "${WORKTREE_DIR}" "${BASE_REF}" "${SOCKET_PATH}" <<'PY'
import json
import os
import sys
import tempfile

path, source_repo, worktree, base_ref, socket_path = sys.argv[1:]
data = {
    "socket": socket_path,
    "workspaces": {
        "wdttsl": {
            "source_repo": source_repo,
            "worktree": worktree,
            "base_ref": base_ref,
            "checks": [
                "diff-check",
                "server-ai-python"
            ]
        }
    }
}
parent = os.path.dirname(path)
fd, tmp = tempfile.mkstemp(prefix=".workspaces-", dir=parent)
try:
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)
finally:
    if os.path.exists(tmp):
        os.unlink(tmp)
PY

unit_tmp="$(mktemp)"
trap 'rm -f "${unit_tmp}"' EXIT

cat >"${unit_tmp}" <<EOF
[Unit]
Description=Server AI controlled WORK broker
After=local-fs.target
ConditionPathExists=${CONFIG_PATH}
ConditionPathIsDirectory=${WORKTREE_DIR}

[Service]
Type=simple
User=${RUN_USER}
Group=${RUN_GROUP}
WorkingDirectory=${WORKTREE_DIR}
ExecStart=/usr/bin/python3 ${BROKER_DST}
Restart=on-failure
RestartSec=2
UMask=0077

NoNewPrivileges=true
PrivateTmp=true
PrivateDevices=true
ProtectSystem=strict
ProtectHome=false
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectKernelLogs=true
ProtectControlGroups=true
RestrictRealtime=true
RestrictSUIDSGID=true
LockPersonality=true
RestrictAddressFamilies=AF_UNIX
ReadOnlyPaths=${REPO_ROOT}
ReadWritePaths=${REPO_ROOT}/.git ${WORKTREE_DIR} ${RUNTIME_DIR}

[Install]
WantedBy=multi-user.target
EOF

unit_changed=0
if [[ ! -f "${UNIT_PATH}" ]] || ! cmp -s "${unit_tmp}" "${UNIT_PATH}"; then
  install -m 0644 -o root -g root "${unit_tmp}" "${UNIT_PATH}"
  unit_changed=1
fi

if [[ "${unit_changed}" -eq 1 ]]; then
  echo "Systemd unit changed; running daemon-reload."
  systemctl daemon-reload
else
  echo "Systemd unit unchanged; skipping daemon-reload."
fi

systemctl enable server-ai-work.service >/dev/null
systemctl restart server-ai-work.service

for _ in $(seq 1 30); do
  [[ -S "${SOCKET_PATH}" ]] && break
  sleep 0.2
done

if [[ ! -S "${SOCKET_PATH}" ]]; then
  echo "WORK socket did not appear: ${SOCKET_PATH}" >&2
  systemctl --no-pager --full status server-ai-work.service || true
  exit 1
fi

echo
echo "=== WORK BROKER STATUS ==="
systemctl --no-pager --full status server-ai-work.service | sed -n '1,18p'
echo
echo "Socket ready: ${SOCKET_PATH}"
echo "Isolated worktree: ${WORKTREE_DIR}"
echo "Deployment checkout remains untouched: ${REPO_ROOT}"
