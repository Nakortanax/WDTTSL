#!/usr/bin/env bash
# Safely deploy only Homer and its read-only status helper on the home server.
set -Eeuo pipefail
SRC="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
HOMER="/opt/homer"
STATUS="/opt/homer-status"
LAN_IP="192.168.1.73"

if [ "${EUID}" -ne 0 ]; then
  echo "Run with sudo: sudo bash server-dashboard/deploy-homer.sh" >&2
  exit 1
fi
for bin in docker python3 curl; do
  command -v "$bin" >/dev/null || { echo "Missing $bin" >&2; exit 1; }
done
for file in \
  "$SRC/homer/assets/config.yml" \
  "$SRC/status/status_proxy.py" \
  "$SRC/status/compose.yaml" \
  "$HOMER/assets/config.yml" \
  "$STATUS/status_proxy.py" \
  "$STATUS/compose.yaml"
do
  [ -f "$file" ] || { echo "Missing $file" >&2; exit 1; }
done
docker inspect homer >/dev/null
docker inspect homer-status >/dev/null
python3 -m py_compile "$SRC/status/status_proxy.py"
docker compose -f "$SRC/status/compose.yaml" config --quiet
docker compose -f "$HOMER/compose.yaml" config --quiet
grep -q 'AmneziaWG 3.1' "$SRC/homer/assets/config.yml"
grep -q 'forgejo-runner' "$SRC/status/status_proxy.py"

STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="/opt/homer-dashboard-backups/$STAMP"
install -d -m 0700 "$BACKUP"
cp -a "$HOMER/assets/config.yml" "$BACKUP/config.yml"
cp -a "$STATUS/status_proxy.py" "$BACKUP/status_proxy.py"
cp -a "$STATUS/compose.yaml" "$BACKUP/status-compose.yaml"
echo "Backup: $BACKUP"

rollback() {
  local rc=$?
  trap - ERR
  echo "Health/deployment failure, restoring previous Homer and status configs." >&2
  cp -a "$BACKUP/config.yml" "$HOMER/assets/config.yml"
  cp -a "$BACKUP/status_proxy.py" "$STATUS/status_proxy.py"
  cp -a "$BACKUP/status-compose.yaml" "$STATUS/compose.yaml"
  (cd "$STATUS" && docker compose up -d --no-deps --force-recreate status) || true
  (cd "$HOMER" && docker compose up -d --no-deps --force-recreate homer) || true
  exit "$rc"
}
trap rollback ERR

cp "$SRC/homer/assets/config.yml" "$HOMER/assets/config.yml"
cp "$SRC/status/status_proxy.py" "$STATUS/status_proxy.py"
cp "$SRC/status/compose.yaml" "$STATUS/compose.yaml"

# Do not restart Docker, CSQTT/VPNSL, AWG, Forgejo or any other service.
(cd "$STATUS" && docker compose up -d --no-deps --force-recreate status)
(cd "$HOMER" && docker compose up -d --no-deps --force-recreate homer)

healthy=0
for attempt in $(seq 1 15); do
  if curl -fsS --max-time 5 "http://$LAN_IP:8090/" | grep -q '"forgejo"' \
     && curl -fsS --max-time 5 "http://$LAN_IP:8088/assets/config.yml" | grep -q 'AmneziaWG 3.1'; then
    healthy=1
    break
  fi
  sleep 2
done
[ "$healthy" = "1" ] || { echo "Dashboard health check failed" >&2; false; }
trap - ERR

echo "Homer dashboard updated; backup retained at $BACKUP"
echo "Service status checks (HTTP 200=running/available; HTTP 503=offline):"
for path in health/forgejo health/tcp/forgejo-ssh \
  health/docker-service/forgejo-runner \
  health/docker-service/forgejo-dind \
  health/docker-service/amneziawg \
  health/vpnsl; do
  curl -sS -o /dev/null --max-time 5 \
    -w "$path: HTTP %{http_code}\n" "http://$LAN_IP:8090/$path" || true
done
echo "Open http://$LAN_IP:8088/ and refresh the browser cache."
