# AdGuard Home + Keenetic DNS — состояние на 28.09.2026

Документ фиксирует рабочее состояние DNS-фильтрации домашней сети после настройки AdGuard Home и Keenetic. Секреты, пароли и приватные ключи не сохраняются.

## AdGuard Home

Развёрнут в Docker на домашнем Ubuntu-сервере.

```text
Ubuntu LAN: 192.168.1.73
DNS:        192.168.1.73:53 TCP/UDP
Web UI:     http://192.168.1.73:8080
Container:  adguardhome
Image:      adguard/adguardhome:v0.107.79
```

Docker bind-монты:

```text
/opt/adguardhome/work -> /opt/adguardhome/work
/opt/adguardhome/conf -> /opt/adguardhome/conf
```

Опубликованные порты:

```text
192.168.1.73:53/tcp  -> 53/tcp
192.168.1.73:53/udp  -> 53/udp
192.168.1.73:3000    -> 3000/tcp
192.168.1.73:8080    -> 80/tcp
```

Публичного проброса этих портов через ISP/Keenetic нет и по умолчанию быть не должно.

## Keenetic

Цель: все обычные DNS-запросы домашней сети направлять через AdGuard Home.

Зафиксированное состояние:

```text
DNS server: 192.168.1.73
Ignore ISP DNSv4: enabled
```

Пользователь удалил остальные записи DNS из общего списка Keenetic и оставил только `192.168.1.73`.

Ранее были настроены глобальные DoT/DoH (Cloudflare, Google, Quad9) и отдельные DNS для Amnezia. Они обходили AdGuard, поэтому журнал AdGuard почти не заполнялся.

## Подтверждённый маршрут DNS

tcpdump подтвердил запросы:

```text
192.168.1.1 -> 192.168.1.73:53
```

То есть Keenetic действительно пересылает DNS в AdGuard Home.

Пример наблюдаемого запроса:

```text
192.168.1.1.xxxxx > 192.168.1.73.53: A? google.com
```

## Текущее состояние панели AdGuard

На контрольном скриншоте 28.09.2026:

```text
DNS queries:        5451
Blocked by filters: 189 (~3%)
Main client:        192.168.1.1 — 5449 queries (99.96%)
Server itself:      192.168.1.73 — 2 queries
```

Часто запрашиваемые домены включали Telegram, ChatGPT, WhatsApp, Google APIs.

Часто блокируемые домены включали `beacons*.gvt2.com` и `mc.yandex.ru`.

Панель также показывала upstream:

```text
9.9.9.9:53
1.1.1.1:53
```

и среднее время ответа порядка 238–270 ms.

## Важная диагностическая история

В ходе настройки прямые DNS-запросы с Ubuntu к публичным DNS временно возвращали `REFUSED`:

```text
1.1.1.1:53   -> REFUSED
8.8.8.8:53   -> REFUSED
9.9.9.9:53   -> REFUSED
77.88.8.8:53 -> REFUSED
```

Также tcpdump показывал, что AdGuard отправлял запросы к `9.9.9.9:53`, после чего получал `REFUSED`.

При этом HTTPS к:

```text
https://cloudflare-dns.com/dns-query
```

успешно устанавливался и возвращал HTTP/2 415 на HEAD-запрос, что подтверждает доступность HTTPS endpoint. Прямой `https://1.1.1.1/dns-query` был недоступен, а `https://dns.google/dns-query` не подключался.

На момент финального контрольного скриншота AdGuard снова активно обрабатывал тысячи запросов. Поэтому `REFUSED` рассматривается как отдельная диагностическая аномалия/политика маршрута, а не как доказательство текущего отказа AdGuard.

## Что не менять без необходимости

- Не возвращать глобальные DoT/DoH в Keenetic, если цель — обязательная фильтрация через AdGuard.
- Не публиковать AdGuard DNS/Admin наружу.
- Не отключать `systemd-resolved`: он слушает только loopback и не конфликтует с AdGuard на `192.168.1.73:53`.
- Не удалять Docker volumes/data.
- Не менять VPNSL/CSQTT, WeightDiaryBot, Jellyfin, Transmission, Samba без отдельной задачи.

## Следующий контроль при продолжении

Если DNS снова станет нестабильным:

```bash
sudo tcpdump -ni enp2s0 -nn 'port 53'
```

Проверить три участка:

```text
клиент -> Keenetic
Keenetic -> 192.168.1.73:53
192.168.1.73 -> upstream
```

Также проверить журнал запросов AdGuard и текущий список upstream.

## Homer

Параллельно запланирована единая домашняя панель на базе Homer. Предлагаемый адрес:

```text
http://192.168.1.73:8088
```

Планируемые карточки: AdGuard Home, VPNSL/CSQTT, Keenetic, Jellyfin, Transmission, Samba, WeightDiaryBot, Fuel, Ollama, PostgreSQL, SSH, XRDP и legacy GPN-сервисы. Homer ещё не установлен.
