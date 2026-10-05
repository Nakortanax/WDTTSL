#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UID_VALUE="$(id -u)"
GID_VALUE="$(id -g)"

echo "Installing Server AI READ broker for uid=${UID_VALUE} gid=${GID_VALUE}"

sudo install -d -m 0755 /usr/local/lib/server-ai
sudo install -m 0755 "${ROOT_DIR}/host-read/host_read.py" /usr/local/lib/server-ai/host_read.py
sudo install -m 0644 "${ROOT_DIR}/host-read/server-ai-read.service" /etc/systemd/system/server-ai-read.service

printf 'SERVER_AI_SOCKET_UID=%s\nSERVER_AI_SOCKET_GID=%s\nSERVER_AI_READ_SOCKET=/run/server-ai/read.sock\n'   "${UID_VALUE}" "${GID_VALUE}" | sudo tee /etc/server-ai-read.env >/dev/null
sudo chmod 0600 /etc/server-ai-read.env

sudo systemctl daemon-reload
sudo systemctl enable --now server-ai-read.service

echo
sudo systemctl status server-ai-read.service --no-pager -l
echo
sudo ls -l /run/server-ai/read.sock
