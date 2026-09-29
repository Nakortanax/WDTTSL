# Home server backup

Дата актуализации: 29.09.2026.

Эта папка хранит безопасную резервную копию знаний о домашнем сервере и recovery-инструкции. Это не byte-for-byte образ диска.

## Что хранится в GitHub

Серверный код и установщик VPNSL/CSQTT:

```text
rust-server/
shared/
app/src/main/assets/deploy.sh
```

Актуальная документация:

```text
docs/PROJECT_CONTEXT_2026-09-29.md
docs/ADGUARD_KEENETIC_2026-09-28.md
docs/HOME_SERVER_VPN_PLAN.md
server-backup/RESTORE.md
server-backup/BACKUP_MANIFEST_2026-09-29.md
```

Dashboard/monitoring конфиги находятся в отдельной рабочей ветке:

```text
home-dashboard-homer
server-dashboard/homer/
server-dashboard/glances/
server-dashboard/status/
```

Клиентские snapshots:

```text
Android: final/android-v1.0.10
Windows: final/windows-v1.0.3
```

## Текущая архитектура

```text
Internet
  |
  | UDP/46000
  v
ISP router
  |
  v
Keenetic
  |
  v
Ubuntu 192.168.1.73
  |
  +-- CSQTT 2.1.9
  +-- AdGuard Home
  +-- Homer
  +-- Glances
  +-- Homer status proxy
  +-- Docker workloads
  +-- Jellyfin / Transmission / Samba / XRDP / SSH
```

## Основные адреса

```text
Keenetic:       192.168.1.1
Ubuntu:         192.168.1.73
VPN subnet:     10.66.67.0/24

CSQTT peer:     UDP/46000
CSQTT web:      TCP/46002
AdGuard DNS:    192.168.1.73:53
AdGuard UI:     http://192.168.1.73:8080
Homer:          http://192.168.1.73:8088
Status API:     http://192.168.1.73:8090
Jellyfin:       http://192.168.1.73:8096
Transmission:   http://192.168.1.73:9091
Glances:        http://192.168.1.73:61208
```

Публично пробрасывать по умолчанию только UDP/46000.

## Секреты

Секреты намеренно не входят в GitHub backup.

Никогда не коммитить:
- SSH passwords/private keys;
- VPNSL main password;
- CSQTT web credentials;
- VK hashes/tokens;
- TLS private keys;
- AdGuard credentials;
- API keys;
- secret contents of `/etc/csqtt`;
- temporary secret env/override files.

## Живой snapshot

`export_safe_snapshot.sh` собирает безопасный диагностический снимок без содержимого секретных конфигов.

Такой snapshot полезно запускать после крупных изменений, но перед загрузкой в GitHub его нужно вручную проверить на отсутствие чувствительных данных.

## Что GitHub backup НЕ содержит

GitHub backup не заменяет резервную копию данных.

Отдельно нужно сохранять:
- PostgreSQL data;
- важные Docker volumes/bind mounts;
- пользовательские файлы/медиа;
- секреты в защищённом хранилище;
- при необходимости конфиги приложений после ручной очистки от секретов.
