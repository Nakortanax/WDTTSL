# HOME_SERVER_VPN_PLAN

## Цель

Перенести серверную часть VPNSL/CSQTT с удалённого VPS на домашний Ubuntu Server со статическим публичным IPv4 от провайдера.

Домашний сервер должен:

- принимать подключения Android и Windows клиентов VPNSL;
- выпускать их трафик в Интернет через домашнего провайдера;
- использовать существующий протокол/аутентификацию VPNSL без изменения финальных клиентских сборок;
- быть доступным из Интернета через точечный port-forward на домашнем роутере.

## Зафиксированные финальные клиентские версии

Android:

- release: `v1.0.8`
- commit: `75165dee7729a731f6a256cd31dffd982a1b53b7`
- snapshot branch: `final/android-v1.0.8`

Windows:

- release: `windows-v1.0.2`
- commit: `c2a1e4a73886f40ac0828420622ba8a2cfc966e2`
- snapshot branch: `final/windows-v1.0.2`

Windows 1.0.2 является потомком Android 1.0.8, поэтому новая ветка домашнего сервера создана от Windows 1.0.2 и содержит актуальную Android-базу.

Рабочая ветка:

```text
home-server-vpn
```

## Что уже умеет сервер

Текущая серверная часть рассчитана не только на VPS, а на Linux-хост с:

- systemd или Docker;
- TUN;
- `CAP_NET_ADMIN`;
- iptables;
- IPv4 forwarding.

По умолчанию:

```text
VPN peer: UDP/46000
Web panel: TCP/46002
HTTP/Let's Encrypt helper: TCP/80
VPN subnet: 10.66.67.0/24
```

Deploy-скрипт сам:

- включает `net.ipv4.ip_forward=1`;
- создаёт/восстанавливает TUN;
- добавляет INPUT/FORWARD rules;
- добавляет NAT `MASQUERADE` для `10.66.67.0/24` через определённый WAN-интерфейс;
- может запускать сервер как systemd service или Docker container.

Это означает, что архитектурно домашний Ubuntu Server подходит для роли VPNSL gateway без отдельного VPS.

## Предлагаемая схема

```text
Android / Windows client
        |
        | Internet
        v
Статический публичный IPv4 провайдера
        |
        v
Домашний роутер
  UDP 46000 -> LAN_IP_UBUNTU:46000
        |
        v
Ubuntu Server
  VPNSL/CSQTT
  TUN 10.66.67.0/24
  IPv4 forwarding
  NAT MASQUERADE
        |
        v
Домашний ISP -> Internet
```

После подключения внешний IP клиента будет домашним публичным IP провайдера.

## Какие порты пробрасывать

Минимально для рабочего VPN:

```text
UDP 46000 -> Ubuntu Server:46000
```

Web panel `TCP/46002` наружу по умолчанию не пробрасывать.

SSH `TCP/22` наружу по умолчанию не пробрасывать. Для первоначальной установки Windows deploy-функцией можно использовать SSH внутри домашней LAN.

`TCP/80` пробрасывать только если реально понадобится публичное получение/продление Let's Encrypt сертификата для web-panel. Для самого UDP peer этот порт не является основным VPN transport port.

## Статический IP

Наличие статического IPv4 у провайдера упрощает схему: DDNS не нужен.

Перед настройкой необходимо всё равно подтвердить:

1. WAN IPv4 в роутере совпадает с выданным провайдером статическим адресом;
2. это публичный routable IPv4, а не адрес за CGNAT;
3. роутер поддерживает UDP port-forward;
4. Ubuntu Server имеет постоянный LAN IPv4/DHCP reservation.

## VK hashes / TURN / peer

Финальные клиенты сохраняют поля:

- Peer;
- Password;
- VK hashes;
- TURN;
- SNI/obfs/auth параметры.

Переезд на домашний сервер не требует автоматически менять сам механизм VK hashes.

Главное изменение для клиента — `Peer` должен указывать на домашний публичный IPv4 и порт VPN peer, например:

```text
PUBLIC_STATIC_IP:46000
```

Пароль сервера должен соответствовать конфигурации домашнего CSQTT.

TURN/VK параметры проверяются отдельно после базового прямого подключения к UDP peer.

## Режим установки на домашний сервер

Для первого домашнего развёртывания предпочтительно тестировать **native systemd mode**, а не Docker mode.

Причины:

- сервер напрямую работает с TUN и host iptables;
- на домашнем Ubuntu уже есть другие Docker workloads;
- Docker-режим CSQTT использует `--network host`, `NET_ADMIN`, `NET_RAW`, `/dev/net/tun` и host netfilter;
- systemd mode проще изолировать при первичной диагностике сетевых правил.

Docker mode оставить как альтернативу после успешного native-теста.

## Важная осторожность

Текущий `deploy.sh` — достаточно агрессивный системный установщик. Он:

- меняет sysctl;
- меняет iptables;
- создаёт TUN;
- управляет systemd units;
- в некоторых сценариях останавливает старые CSQTT runtime;
- умеет работать с Docker runtime.

Поэтому на домашнем сервере сначала выполнять только диагностику и dry planning. Не запускать install до фиксации текущих:

- интерфейсов;
- default route;
- iptables/nftables;
- Docker networks;
- UFW;
- занятых портов.

## План внедрения

### Этап 1. Диагностика домашней сети

Собрать на Ubuntu:

```bash
ip -br addr
ip route
ip route get 1.1.1.1
ss -lunpt
sudo iptables-save
sudo nft list ruleset
sudo ufw status verbose
docker network ls
```

На роутере:

- узнать LAN IPv4 Ubuntu;
- подтвердить WAN static public IPv4;
- настроить DHCP reservation для Ubuntu.

### Этап 2. Проверить свободный peer port

Проверить, что UDP/46000 не занят.

Если занят — выбрать другой внешний/внутренний peer port и сохранить его в конфигурации.

### Этап 3. Установить VPNSL server в systemd mode

Установка сначала из LAN, без внешнего SSH.

Не открывать web-panel в Интернет на первом этапе.

### Этап 4. Проверить локальный сервер

Проверить:

- `systemctl status csqtt`;
- UDP listener;
- TUN interface;
- `net.ipv4.ip_forward`;
- NAT/FORWARD rules;
- отсутствие конфликтов с Docker/WeightDiary/Transmission/Samba.

### Этап 5. Port-forward

На роутере:

```text
WAN UDP 46000 -> UBUNTU_LAN_IP UDP 46000
```

Firewall Ubuntu должен разрешать только нужный peer port.

### Этап 6. Проверка извне

Тестировать не из домашнего Wi-Fi, а через мобильную сеть.

Сначала Android final v1.0.8, затем Windows final 1.0.2.

Проверить:

- установление VPN;
- доступ в Интернет;
- внешний IP;
- DNS;
- MTU/крупные загрузки;
- reconnect;
- Android app-routing;
- Windows full-tunnel и Direct exceptions.

### Этап 7. Только после стабильного теста

Решить:

- нужен ли web-panel извне;
- нужен ли TCP/80 для сертификата;
- нужен ли remote SSH;
- нужен ли Docker mode;
- нужны ли изменения клиента для удобного режима «Домашний сервер».

## Критерий успеха

Без изменения финальных APK/Windows binaries:

1. клиент подключается к домашнему static public IP;
2. VPN получает рабочий tunnel;
3. весь выбранный трафик выходит через домашний ISP;
4. внешний IP клиента равен домашнему публичному IP;
5. существующие сервисы Ubuntu Server продолжают работать;
6. после disconnect сетевые правила не ломают обычный трафик сервера.



## Фактическая сеть домашнего Ubuntu Server — 27.09.2026

Первичная диагностика выполнена до установки VPNSL server.

```text
LAN interface: enp2s0
LAN IPv4:      192.168.1.73/24
LAN gateway:   192.168.1.1
Internet path: enp2s0 -> 192.168.1.1
```

Docker-сети:

```text
docker0                  172.17.0.0/16
weightdiarybot_default   172.18.0.0/16
```

Конфликта с планируемой VPN-подсетью `10.66.67.0/24` на этом этапе не видно.

Проверено:

- `UDP/46000` свободен;
- `TCP/46002` свободен;
- `TCP/80` свободен;
- UFW неактивен;
- SSH уже слушает `TCP/22`;
- Transmission использует `51413/tcp+udp`;
- Samba использует `139/445/tcp`;
- Jellyfin использует `8096/tcp` и `7359/udp`;
- Docker/WeightDiary используют отдельные 172.17/16 и 172.18/16 сети.

LAN-адрес `192.168.1.73` получен по DHCP. До настройки router port-forward нужно сделать DHCP reservation/static lease для этого адреса, иначе проброс `UDP/46000` может сломаться после смены LAN-IP.

Следующая проверка перед установкой: TUN, текущий `ip_forward`, iptables backend/policies, отсутствие маршрута `10.66.67.0/24`, а также снимок текущих NAT/FORWARD правил Docker.


## Network preflight #2 — 27.09.2026

Проверено на домашнем Ubuntu Server:

```text
net.ipv4.ip_forward = 1
/dev/net/tun exists and is rw-rw-rw-
10.66.67.0/24 is not present in current route tables
iptables v1.8.11 (nf_tables backend)
FORWARD policy = DROP
```

Текущий `FORWARD` обслуживается Docker:

```text
-A FORWARD -j DOCKER-USER
-A FORWARD -j DOCKER-FORWARD
```

Текущий NAT:

```text
172.17.0.0/16 -> MASQUERADE
172.18.0.0/16 -> MASQUERADE
```

Docker сети не конфликтуют с планируемой CSQTT-подсетью `10.66.67.0/24`.

Текущий `deploy.sh` добавляет собственные ACCEPT-правила для CSQTT TUN через `iptables -I FORWARD` и отдельный `POSTROUTING MASQUERADE` для `10.66.67.0/24`, поэтому политика `FORWARD DROP` сама по себе не блокирует архитектуру. При установке нужно обязательно проверить порядок правил после deploy и убедиться, что Docker chains сохранились.

WAN/LAN interface:

```text
enp2s0
MAC: 2c:f0:5d:d8:ca:80
LAN IPv4: 192.168.1.73/24
gateway: 192.168.1.1
```

Следующий безопасный шаг перед install:

1. закрепить `192.168.1.73` за MAC `2c:f0:5d:d8:ca:80` в DHCP reservation роутера;
2. создать router port-forward `UDP 46000 -> 192.168.1.73:46000`;
3. пока не пробрасывать наружу TCP/22, TCP/46002 и TCP/80;
4. после этого выполнить локальный pre-install snapshot iptables/nftables и установить CSQTT в native systemd mode.


## Router port-forward — выполнено 27.09.2026

Домашняя схема использует двойной NAT.

Публичный IPv4 на роутере провайдера:

```text
37.79.203.247
```

WAN-адрес Keenetic в сети роутера провайдера:

```text
192.168.0.13
```

LAN-адрес Ubuntu Server за Keenetic:

```text
192.168.1.73
```

Настроена цепочка проброса:

```text
Internet
37.79.203.247:46000/UDP
        |
        v
ISP router
192.168.0.13:46000/UDP
        |
        v
Keenetic
192.168.1.73:46000/UDP
        |
        v
Ubuntu Server / VPNSL
```

На обоих роутерах пробрасывается только `UDP/46000`.

Не проброшены наружу:

- TCP/22
- TCP/80
- TCP/46002

Следующий этап: host pre-install snapshot, проверка отсутствия старой установки CSQTT/VPNSL и затем native systemd deployment.
