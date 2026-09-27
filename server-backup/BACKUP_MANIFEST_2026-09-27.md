# Backup manifest — 27.09.2026

Backup branch:

```text
backup/home-server-2026-09-27
```

Canonical working branch:

```text
home-server-vpn
```

Included recovery sources:
- `rust-server/`
- `shared/`
- `app/src/main/assets/deploy.sh`
- `docs/HOME_SERVER_VPN_PLAN.md`
- `docs/PROJECT_CONTEXT_2026-09-27.md`
- `server-backup/README.md`
- `server-backup/RESTORE.md`
- `server-backup/export_safe_snapshot.sh`

Client snapshots referenced by the server backup:
- Android: `final/android-v1.0.10`, tag `v1.0.10`, commit `006bdce8309515c0e5b78f436569d186535e8ee9`
- Windows: `final/windows-v1.0.3`, tag `windows-v1.0.3`, commit `ec18bbede0037a1f72c0babbede94b2b4f783147`

Live server target state:
- CSQTT 2.1.9
- CSQTT-WIRE-3
- native systemd
- Ubuntu LAN 192.168.1.73/24 via enp2s0
- gateway 192.168.1.1
- inbound public IPv4 37.79.203.247
- peer UDP/46000
- web TCP/46002 local-only by default
- VPN subnet 10.66.67.0/24
- Keenetic direct ISP egress 37.79.203.247
- Keenetic Amnezia WG egress 144.31.103.134

This backup intentionally excludes all credentials, private keys, VK hashes/tokens and secret contents of /etc/csqtt.
