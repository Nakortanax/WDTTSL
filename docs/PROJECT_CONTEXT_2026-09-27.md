# PROJECT CONTEXT — VPNSL / Home Server — 27.09.2026

Этот файл нужен для продолжения проекта без истории чата.

## Репозиторий

```text
GitHub: Nakortanax/WDTTSL
server work branch: home-server-vpn
Android final: final/android-v1.0.10
Windows final: final/windows-v1.0.3
```

Не изменять без отдельного решения:
- старые final snapshots;
- main.

## Домашний сервер

```text
Ubuntu LAN IPv4: 192.168.1.73/24
interface: enp2s0
gateway: 192.168.1.1
public inbound IPv4: 37.79.203.247
Keenetic WAN behind ISP router: 192.168.0.13
Amnezia WG public exit: 144.31.103.134
```

CSQTT:

```text
version: 2.1.9
wire protocol: CSQTT-WIRE-3
mode: native systemd
binary: /usr/local/bin/csqtt
config: /etc/csqtt
unit: /etc/systemd/system/csqtt.service
TUN: csqtt1
VPN subnet: 10.66.67.0/24
peer: UDP/46000
web: TCP/46002
```

Публично проброшен только UDP/46000.

Не публиковать наружу по умолчанию:
- SSH TCP/22;
- HTTP TCP/80;
- web panel TCP/46002.

## Двойной NAT

```text
Internet 37.79.203.247:46000/UDP
 -> ISP router
 -> Keenetic 192.168.0.13
 -> Ubuntu 192.168.1.73:46000/UDP
```

Внешний Android-тест успешно подтвердил эту цепочку.

## Маршрутизация

Ubuntu CSQTT NAT/MASQUERADE:

```text
10.66.67.0/24 -> enp2s0
```

После Ubuntu трафик приходит на Keenetic, который уже решает:
- direct ISP -> внешний IP 37.79.203.247;
- Amnezia WireGuard -> внешний IP 144.31.103.134.

144.31.103.134 — штатный policy-routing exit, не ошибка.

## Android

Текущий релиз:

```text
VPNSL 1.0.10
tag: v1.0.10
final branch: final/android-v1.0.10
commit: 006bdce8309515c0e5b78f436569d186535e8ee9
```

Основное:
- Full Tunnel IPv4 по умолчанию;
- optional Applications routing;
- optional IP/files routing;
- BAT/domain route generator сохранён;
- deploy.sh нормализуется CRLF/CR -> LF;
- UTF-8 BOM удаляется;
- после upload выполняется bash -n;
- APK проверяется на наличие server binaries amd64/arm64/armv7.

## Windows

Текущий релиз:

```text
VPNSL Windows 1.0.3
tag: windows-v1.0.3
final branch: final/windows-v1.0.3
commit: ec18bbede0037a1f72c0babbede94b2b4f783147
```

Основное:
- routing 1.0.2 сохранён;
- deploy.sh нормализуется LF/no-BOM;
- удалённый bash -n до install/uninstall;
- SFTP upload size verification;
- server-assets проверяются в готовом пакете.

## История CRLF bug

Первая Windows-установка сервера падала:

```text
$'\r': command not found
set: pipefail: недопустимое название параметра
```

Корень проблемы: CRLF в deploy.sh.

Проблема теперь закрыта в Android 1.0.10 и Windows 1.0.3.

## Скорость

Текущая наблюдаемая скорость пользователя:

```text
~5 Мбит/с
```

Это не подтверждённый server cap.

Текущие параметры Android/native client:
- MTU 1300;
- default workers 18;
- worker group = 9;
- max workers = 126;
- UDP mode предпочтителен для throughput;
- UDP batching до 128 datagrams;
- server UDP socket buffers 16 MiB RX / 8 MiB TX;
- client UDP buffers 1 MiB RX / 512 KiB TX.

Следующий диагностический тест:
- UDP;
- 18 workers;
- 27 workers;
- 36 workers;
- 54 workers;
- один и тот же speed-test endpoint/network.

Если скорость растёт с workers — оптимизировать worker auto-scaling.
Если остаётся около 5 Мбит/с — исследовать TURN/VK path, packet loss и RTT.

## Что хранится в GitHub как backup

```text
rust-server/
shared/
app/src/main/assets/deploy.sh
server-backup/
docs/HOME_SERVER_VPN_PLAN.md
docs/PROJECT_CONTEXT_2026-09-27.md
```

Секреты намеренно не хранятся.

## Секреты, которые нельзя коммитить

- SSH passwords/private keys;
- VPNSL main password;
- web login/password;
- VK hashes/tokens;
- TLS private keys;
- /tmp/.csqtt-upload-web.env;
- /tmp/.csqtt-upload-overrides.json;
- содержимое секретных /etc/csqtt файлов.

## Безопасные проверки сервера

```bash
echo "=== CSQTT ==="
sudo systemctl status csqtt --no-pager -l

echo "=== INTERFACES / ROUTE ==="
ip -br addr
ip route

echo "=== IP FORWARD ==="
cat /proc/sys/net/ipv4/ip_forward

echo "=== CSQTT FIREWALL ==="
sudo iptables -S FORWARD
sudo iptables -t nat -S POSTROUTING

echo "=== DOCKER ==="
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
```

Не удалять Docker volumes и не применять destructive reset-команды без отдельного решения.


## AdGuard Home / Keenetic DNS — 28.09.2026

Актуальная фиксация состояния:

```text
AdGuard Home: Docker
DNS: 192.168.1.73:53 TCP/UDP
Web: http://192.168.1.73:8080
Keenetic DNS: 192.168.1.73
Ignore ISP DNSv4: enabled
```

Глобальные DoT/DoH на Keenetic были удалены, чтобы DNS не обходил AdGuard. Пользователь сообщил, что в списке DNS оставлен только `192.168.1.73`.

tcpdump подтвердил рабочий участок:

```text
192.168.1.1 -> 192.168.1.73:53
```

На контрольном скриншоте AdGuard:
- 5451 DNS-запрос;
- 189 заблокировано (~3%);
- 99.96% запросов от Keenetic `192.168.1.1`;
- upstream в панели: `9.9.9.9:53` и `1.1.1.1:53`.

Во время диагностики прямые UDP/53-запросы с Ubuntu к публичным DNS временно возвращали `REFUSED`. HTTPS к `https://cloudflare-dns.com/dns-query` устанавливался, а прямой `https://1.1.1.1/dns-query` и `https://dns.google/dns-query` не подключались. На момент финального скриншота AdGuard активно обрабатывал запросы.

Подробности:
`docs/ADGUARD_KEENETIC_2026-09-28.md`.

Homer для единой панели сервисов только запланирован; не установлен.
