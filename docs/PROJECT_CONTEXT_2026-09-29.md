# PROJECT CONTEXT — Home Server — 29.09.2026

Этот файл фиксирует актуальное известное состояние домашнего сервера после настройки VPNSL/CSQTT, AdGuard Home, Homer, Glances и live status layer.

Это не byte-for-byte образ диска и не содержит секреты.

## Репозиторий и контрольные ветки

```text
GitHub: Nakortanax/WDTTSL

server working branch:
  home-server-vpn

dashboard working branch:
  home-dashboard-homer

Android final:
  final/android-v1.0.10
  tag v1.0.10
  commit 006bdce8309515c0e5b78f436569d186535e8ee9

Windows final:
  final/windows-v1.0.3
  tag windows-v1.0.3
  commit ec18bbede0037a1f72c0babbede94b2b4f783147
```

Не изменять старые final snapshots без отдельного решения.

## Ubuntu host

```text
LAN IPv4: 192.168.1.73/24
interface: enp2s0
gateway: 192.168.1.1
public inbound IPv4: 37.79.203.247
Keenetic WAN behind ISP router: 192.168.0.13
Amnezia WG public exit: 144.31.103.134
```

Известное железо:

```text
CPU: Intel Core i5-10400F
RAM: 16 GB
GPU: NVIDIA GeForce GTX 1660 Super
```

Docker и NVIDIA Container Toolkit настроены; Ollama использует GPU.

## VPNSL / CSQTT

```text
version: 2.1.9
wire: CSQTT-WIRE-3
mode: native systemd
binary: /usr/local/bin/csqtt
config: /etc/csqtt
unit: /etc/systemd/system/csqtt.service

TUN: csqtt1
VPN subnet: 10.66.67.0/24
peer: UDP/46000
web: HTTPS/TCP/46002
```

Сетевая цепочка:

```text
Internet 37.79.203.247:46000/UDP
 -> ISP router
 -> Keenetic 192.168.0.13
 -> Ubuntu 192.168.1.73:46000/UDP
 -> CSQTT
```

Публично проброшен только UDP/46000.

Не публиковать наружу по умолчанию:
- SSH 22/tcp;
- CSQTT web 46002/tcp;
- AdGuard 53/8080;
- Homer 8088;
- Glances 61208;
- status proxy 8090;
- Jellyfin, Transmission, Samba.

NAT:
```text
10.66.67.0/24 -> enp2s0 MASQUERADE
```

Keenetic policy routing:
- direct ISP -> 37.79.203.247;
- Amnezia WireGuard -> 144.31.103.134.

## AdGuard Home

Развёрнут в Docker.

```text
container: adguardhome
image: adguard/adguardhome:v0.107.79
DNS: 192.168.1.73:53 TCP/UDP
web UI: http://192.168.1.73:8080
setup mapping still present: 192.168.1.73:3000 -> 3000/tcp
```

Persisted paths:

```text
/opt/adguardhome/work
/opt/adguardhome/conf
```

Keenetic настроен использовать:

```text
DNS: 192.168.1.73
Ignore ISP DNSv4: enabled
```

Глобальные DoT/DoH Keenetic были удалены, чтобы DNS не обходил AdGuard.

tcpdump подтвердил:

```text
192.168.1.1 -> 192.168.1.73:53
```

Контрольный скриншот 28.09.2026:
- 5451 DNS queries;
- 189 blocked;
- 99.96% запросов от 192.168.1.1.

В ходе диагностики встречался `REFUSED` от публичных DNS/53. На финальном контрольном этапе AdGuard обрабатывал запросы нормально. Подробности: `docs/ADGUARD_KEENETIC_2026-09-28.md`.

## Homer dashboard

Рабочая панель:

```text
URL: http://192.168.1.73:8088
container: homer
image: b4bz/homer:latest
bind: 192.168.1.73:8088 -> 8080/tcp
status: healthy
HTTP check: 200 OK
```

Файлы в GitHub:

```text
branch: home-dashboard-homer
server-dashboard/homer/
```

Карточки:
- AdGuard Home;
- VPNSL / CSQTT;
- Keenetic;
- Jellyfin;
- Transmission;
- Samba;
- Fuel;
- WeightDiaryBot;
- Ollama;
- PostgreSQL 17;
- SSH;
- XRDP;
- Docker;
- server resources;
- static System Updater and legacy cards.

## Glances

```text
container: glances
image: nicolargo/glances:latest
URL: http://192.168.1.73:61208
bind: 192.168.1.73:61208 -> 61208/tcp
API status: /api/4/status
verified version: 4.5.7
```

Используется Homer для CPU/RAM/load/swap.

## Homer live status layer

```text
container: homer-status
image: python:3.12-alpine
bind: 192.168.1.73:8090 -> 8090/tcp

container: homer-docker-proxy
image: tecnativa/docker-socket-proxy:latest
2375/tcp: internal Docker network only
POST: disabled
CONTAINERS GET: enabled
```

Подтверждённые live checks:
- AdGuard;
- VPNSL;
- Keenetic;
- Jellyfin;
- Transmission;
- Fuel;
- Homer;
- Glances;
- Docker container count;
- WeightDiaryBot;
- Ollama;
- PostgreSQL;
- SSH 22/tcp;
- Samba 445/tcp;
- XRDP 3389/tcp.

Во время контрольной проверки:
```text
Docker: 9 running / 0 stopped / 9 total
```

Raw Docker socket наружу не публикуется.

Отдельный systemd helper на 8091 не установлен и удалён из финальной GitHub-конфигурации по решению пользователя.

## WeightDiaryBot stack

Существующий стек сохранять без разрушительных операций.

Известные компоненты:
- bot;
- PostgreSQL 17;
- Ollama;
- fuel service;
- GPU acceleration для Ollama.

Не удалять Docker volumes/data.

## Остальные установленные сервисы

Известные сервисы хоста:
- Jellyfin;
- Transmission;
- Samba;
- XRDP;
- SSH;
- legacy GPN bot/editor;
- WeightDiary host metrics/system updater units.

Часть legacy/systemd карточек в Homer оставлена статической.

## Порты, используемые домашними сервисами

```text
22/tcp      SSH
53/tcp/udp  AdGuard DNS
445/tcp     Samba
3389/tcp    XRDP
46000/udp   CSQTT peer (единственный публично проброшенный по умолчанию)
46002/tcp   CSQTT web
8080/tcp    AdGuard Home UI
8088/tcp    Homer
8090/tcp    Homer status proxy
8096/tcp    Jellyfin
9091/tcp    Transmission
61208/tcp   Glances
11434/tcp   Ollama internal
5432/tcp    PostgreSQL internal
```

Fuel service ранее использовал `192.168.1.73:8081`.

## Безопасность

Не коммитить:
- SSH passwords/private keys;
- VPNSL main password;
- CSQTT web credentials;
- VK hashes/tokens;
- TLS private keys;
- AdGuard credentials/config secrets;
- API keys;
- secret contents of `/etc/csqtt`;
- temporary secret env/override files.

Не выполнять:
- `docker compose down -v`;
- удаление Docker volumes;
- firewall flush;
- destructive reset без отдельного решения.

## Safe checks

```bash
echo "=== CSQTT ==="
sudo systemctl status csqtt --no-pager -l

echo "=== NETWORK ==="
ip -br addr
ip route

echo "=== LISTEN ==="
sudo ss -lntup

echo "=== FORWARDING ==="
cat /proc/sys/net/ipv4/ip_forward

echo "=== FIREWALL ==="
sudo iptables -S FORWARD
sudo iptables -t nat -S POSTROUTING

echo "=== DOCKER ==="
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'

echo "=== DASHBOARD ==="
curl -I http://192.168.1.73:8088
curl -s http://192.168.1.73:61208/api/4/status
curl -s http://192.168.1.73:8090/summary
```

## Backup scope

GitHub backup хранит код, deployment-конфиги и recovery knowledge. Он не является полным образом живого сервера и не содержит секреты.

Для полного disaster recovery дополнительно нужны:
- секреты из отдельного защищённого хранилища;
- данные PostgreSQL;
- важные Docker volumes/bind mounts;
- медиаданные/общие папки по отдельной политике;
- при необходимости локальный safe snapshot через `server-backup/export_safe_snapshot.sh`.


## Подготовка удаления локального ИИ и дневника — 29.09.2026

Пользователь принял решение удалить локальный ИИ/Ollama и дневник из активного Telegram-бота.

GitHub-подготовка выполнена до изменений живого сервера.

WeightDiaryBot:
```text
main: 9fa10f39cca3f430a84c4350b4f56db9c24d7902
backup before change: backup/pre-remove-ai-diary-2026-09-29
```

Целевая активная Docker-архитектура WeightDiaryBot:
```text
fuel
bot
```

Из Compose и runtime-кода удалены:
- Ollama / локальная модель;
- PostgreSQL как зависимость дневника;
- дневник;
- AI chat;
- OCR/vision/Huawei Health;
- diary_data и связанные handlers/tests.

Старый PostgreSQL volume на живом сервере пока не удалять: сохранить как безопасную
историческую точку данных до отдельного решения после проверки новой версии.

Ollama/model volume должен быть удалён после успешного обновления живого сервера и проверки,
что оставшиеся сервисы от него не зависят.

Homer:
```text
branch: home-dashboard-homer
commit: 6e5b1a943267353236ef3c7a9959908c4a5a41e2
backup before change: backup/pre-remove-ai-diary-dashboard-2026-09-29
```

Из целевой панели удалены карточки Ollama и PostgreSQL 17. Карточка WeightDiaryBot
оставлена как Telegram-сервис «Топливо · сервер · климат». Status proxy больше не ожидает
старые контейнеры Ollama/PostgreSQL.

ВАЖНО: этот раздел фиксирует подготовленное GitHub-состояние. На момент записи live deployment
на Ubuntu ещё не подтверждён. Не считать Ollama/дневник удалёнными с физического сервера,
пока не выполнены pull/redeploy, проверка Telegram/Docker/Homer и финальный checkpoint.


## Live cleanup completed — 29.09.2026

WeightDiaryBot live server cleanup подтверждён пользователем после успешной проверки новой версии.

Удалено с Ubuntu runtime:
- `weightdiarybot-ollama-1`;
- `weightdiarybot-db-1`;
- `weightdiarybot_ollama_data`;
- image `ollama/ollama:latest`.

Активные контейнеры проекта:
```text
weightdiarybot-bot-1
weightdiarybot-fuel-1
```

Сохранены как страховочная точка данных:
```text
weightdiarybot_postgres_data
weightdiarybot_diary_data
```

Сохранён рабочий volume:
```text
weightdiarybot_fuel_data
```

Дисковое пространство после удаления Ollama/model data:
```text
root filesystem: ~28G used / ~66G free
Docker images: ~4.742GB
```

Следующий шаг: применить подготовленный `home-dashboard-homer` на live Homer/status proxy и проверить,
что карточки Ollama/PostgreSQL исчезли, а WeightDiaryBot остаётся online.
