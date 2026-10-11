# Wi-Fi server migration — verified 2026-10-11

Production Ubuntu server migration validated by user-supplied command output after a reboot.

- Wi-Fi hardware: Intel AX210, driver `iwlwifi`, interface `wlp3s0`. Connected to SSID `28_5`.
- Wi-Fi IPv4: `192.168.1.73/24` (single IPv4 address after reboot). Gateway `192.168.1.1`; default route uses `wlp3s0`.
- Network renderer: Netplan with `systemd-networkd` and generated file `/run/systemd/network/10-netplan-wlp3s0.network`; `netplan-wpa-wlp3s0.service` active.
- Configuration: `/etc/netplan/01-home.yaml` (contains Wi-Fi credentials; do not commit file contents). NetworkManager exclusion: `/etc/NetworkManager/conf.d/90-unmanaged-wlp3s0.conf` with `unmanaged-devices=interface-name:wlp3s0`.
- Prior conflict: NetworkManager and networkd both managing Wi-Fi caused duplicate DHCP address `192.168.1.151` and routes; Netplan WPA process could not start. Post-switch result: single static address, clean routes, Netplan WPA active.
- CSQTT: service active after reboot, with managed VPN MASQUERADE through `wlp3s0` for `10.66.67.0/24`. Mobile VPN worked before reboot; no post-reboot external mobile test recorded.
- AdGuard DNS queried at `192.168.1.73:53`: successful. Homer HTTP response at `192.168.1.73:8088`: 200 OK.
- All seven production Docker containers running after reboot: weightdiarybot-bot-1, weightdiarybot-fuel-1, homer-status, homer-docker-proxy, glances, homer (healthy), adguardhome.
- Backups saved on host under `/root/netplan-cutover-backup/`; previous YAML files moved into its `old-yaml/` subfolder.
- No changes to production branch `home-server-vpn`.

Do not publish Wi-Fi passwords or raw Netplan files. Check Keenetic DHCP reservation / UDP 46000 forwarding against the new Wi-Fi adapter after future router changes.
