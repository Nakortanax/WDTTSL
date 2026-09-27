# Home VPNSL server backup

Дата снимка: 27.09.2026.

Эта папка нужна как безопасная резервная копия знаний о домашнем VPNSL/CSQTT-сервере. Она позволяет восстановить сервер и продолжить работу даже без истории чата.

## Что уже хранится в GitHub

Серверный код и установщик:

```text
rust-server/
shared/
app/src/main/assets/deploy.sh
```

Документация текущего состояния:

```text
docs/HOME_SERVER_VPN_PLAN.md
docs/WINDOWS_SERVER_DEPLOY_FIX_1.0.3.md
```

Актуальные клиентские snapshots:

```text
final/android-v1.0.10
final/windows-v1.0.3
```

Релизы:

```text
Android: v1.0.10
Windows: windows-v1.0.3
```

## Текущая схема

```text
Internet
  |
  | 37.79.203.247:46000/UDP
  v
ISP router
  |
  | -> Keenetic WAN 192.168.0.13
  v
Keenetic
  |
  | -> Ubuntu 192.168.1.73:46000/UDP
  v
Ubuntu / CSQTT 2.1.9
  |
  +-> direct ISP -> 37.79.203.247
  |
  +-> Amnezia WG -> 144.31.103.134
```

Ubuntu:

```text
LAN: 192.168.1.73/24
gateway: 192.168.1.1
interface: enp2s0
service: csqtt.service
binary: /usr/local/bin/csqtt
config: /etc/csqtt
VPN subnet: 10.66.67.0/24
peer: UDP/46000
web: TCP/46002
wire: CSQTT-WIRE-3
```

## Секреты

Секреты намеренно не входят в GitHub backup.

Никогда не коммитить:
- SSH passwords/private keys;
- VPNSL main password;
- web-panel credentials;
- VK hashes/tokens;
- TLS private keys;
- secret contents of /etc/csqtt;
- /tmp/.csqtt-upload-web.env;
- /tmp/.csqtt-upload-overrides.json.

Используйте личное защищённое хранилище для секретов.

## Живой снимок сервера

Скрипт `export_safe_snapshot.sh` собирает диагностический снимок без содержимого секретных конфигов. Его можно запускать после значимых изменений и сохранять полученную папку отдельно или после ручной проверки добавлять в приватный GitHub-репозиторий.
