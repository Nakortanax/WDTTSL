#!/usr/bin/env bash
set -Eeuo pipefail

STAMP="$(date +%Y%m%d-%H%M%S)"
OUT="${1:-$HOME/vpnsl-safe-snapshot-$STAMP}"
mkdir -p "$OUT"

run() {
  local name="$1"
  shift
  {
    echo "# command: $*"
    echo "# time: $(date -Is)"
    "$@"
  } >"$OUT/$name" 2>&1 || true
}

run hostname.txt hostnamectl
run uname.txt uname -a
run os-release.txt cat /etc/os-release
run ip-addresses.txt ip -br addr
run routes.txt ip route
run rules.txt ip rule
run sockets.txt ss -lunpt
run ip-forward.txt sysctl net.ipv4.ip_forward
run csqtt-status.txt systemctl status csqtt --no-pager -l
run csqtt-unit.txt systemctl cat csqtt
run csqtt-binary.txt ls -l /usr/local/bin/csqtt
run csqtt-binary-sha256.txt sha256sum /usr/local/bin/csqtt
run csqtt-config-metadata.txt find /etc/csqtt -maxdepth 2 -type f -printf '%M %u:%g %s %TY-%Tm-%TdT%TH:%TM:%TS %p\n'
run sysctl-csqtt.txt sh -c 'cat /etc/sysctl.d/99-csqtt*.conf 2>/dev/null'
run iptables-save.txt sh -c 'sudo -n iptables-save'
run nft-ruleset.txt sh -c 'sudo -n nft list ruleset'
run docker-ps.txt docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
run docker-networks.txt docker network ls

cat >"$OUT/README.txt" <<'EOF'
SAFE VPNSL SERVER SNAPSHOT

This snapshot intentionally does NOT include:
- /etc/csqtt file contents
- passwords
- VK hashes/tokens
- private SSH keys
- TLS private keys
- /tmp/.csqtt-upload-web.env
- /tmp/.csqtt-upload-overrides.json
- full install logs

Review every file before publishing it anywhere.
EOF

echo "Snapshot created: $OUT"
