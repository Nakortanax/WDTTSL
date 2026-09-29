# Backup manifest — 29.09.2026

Canonical server working branch:

```text
home-server-vpn
```

Server snapshot branch:

```text
backup/home-server-2026-09-29
```

Dashboard working branch:

```text
home-dashboard-homer
```

Dashboard snapshot branch:

```text
backup/home-dashboard-2026-09-29
```

Dashboard snapshot commit:

```text
8362703d4b031bba039833b6cb8fa8a20077da18
```

## Included recovery knowledge

```text
rust-server/
shared/
app/src/main/assets/deploy.sh

docs/PROJECT_CONTEXT_2026-09-29.md
docs/ADGUARD_KEENETIC_2026-09-28.md
docs/HOME_SERVER_VPN_PLAN.md

server-backup/README.md
server-backup/RESTORE.md
server-backup/export_safe_snapshot.sh
server-backup/BACKUP_MANIFEST_2026-09-29.md
```

Dashboard/monitoring source is snapshotted separately in `backup/home-dashboard-2026-09-29`:

```text
server-dashboard/homer/
server-dashboard/glances/
server-dashboard/status/
```

## Verified/current known target state

```text
Ubuntu LAN: 192.168.1.73/24
gateway: 192.168.1.1
interface: enp2s0

CSQTT: 2.1.9
wire: CSQTT-WIRE-3
peer: UDP/46000
web: TCP/46002
VPN subnet: 10.66.67.0/24

AdGuard DNS: 192.168.1.73:53
AdGuard UI: 192.168.1.73:8080

Homer: 192.168.1.73:8088
Glances: 192.168.1.73:61208
Homer status API: 192.168.1.73:8090
Docker socket proxy: internal Docker network only
```

Live dashboard checks confirmed for:
- AdGuard;
- VPNSL/CSQTT;
- Keenetic;
- Jellyfin;
- Transmission;
- Fuel;
- WeightDiaryBot;
- Ollama;
- PostgreSQL;
- SSH;
- Samba;
- XRDP;
- Docker count;
- host resources via Glances.

The optional systemd helper on port 8091 was not installed and is intentionally excluded from the final dashboard configuration.

## Client snapshots

```text
Android:
  final/android-v1.0.10
  tag v1.0.10
  commit 006bdce8309515c0e5b78f436569d186535e8ee9

Windows:
  final/windows-v1.0.3
  tag windows-v1.0.3
  commit ec18bbede0037a1f72c0babbede94b2b4f783147
```

## Backup limitations

This GitHub backup is a configuration/code/recovery-knowledge backup.

It intentionally does NOT include:
- passwords;
- private keys;
- VPNSL/CSQTT secrets;
- VK hashes/tokens;
- AdGuard credentials;
- API keys;
- secret contents of `/etc/csqtt`;
- PostgreSQL database contents;
- Docker volume contents;
- media/library data.

A fresh `server-backup/export_safe_snapshot.sh` capture from the physical host has not been added as part of this GitHub update unless explicitly uploaded after manual secret review.

For full disaster recovery, separately back up application data and secrets.
