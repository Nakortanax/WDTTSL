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


## Pre-install snapshot — 27.09.2026 08:01

Перед установкой создан локальный снимок состояния хоста:

```text
/home/igor/vpnsl-preinstall-20260927-080104
```

Содержит:

- `iptables-save.txt`
- `nft-ruleset.txt`
- `ip-addresses.txt`
- `routes.txt`
- `ip-forward.txt`

Проверки перед install:

```text
existing csqtt/vpnsl systemd units: none
/etc/csqtt: absent
/usr/local/bin/csqtt: absent
/usr/local/lib/csqtt: absent
UDP/46000: free
```

Это чистая установка, конфликт со старой CSQTT/VPNSL-инсталляцией не обнаружен.

Предпочтительный следующий шаг: развёртывание из финального Windows-клиента через SSH по LAN на `192.168.1.73:22` в `systemd` mode. Публичный SSH наружу для этого не нужен.


## SSH preflight — успешно

Проверка SSH из финального Windows-клиента VPNSL 1.0.2 прошла успешно:

```text
Архитектура: x86_64
Имя сервера: home
UID: 1000
```

Для установки будет использоваться:

```text
SSH host: 192.168.1.73
SSH port: 22
SSH user: igor
mode: native systemd
peer port: 46000/udp
web port: 46002/tcp
```

Пользователь не root, поэтому Windows deploy использует sudo через SSH-пароль.


## Windows deploy CRLF bug — обнаружен 27.09.2026

Первая попытка установки из финального Windows-клиента 1.0.2 завершилась сразу при запуске `/tmp/deploy.sh`:

```text
/tmp/deploy.sh: строка 4: $'\r': command not found
/tmp/deploy.sh: строка 5: set: pipefail: недопустимое название параметра
```

Причина: shell-скрипт был загружен с Windows CRLF line endings, а Linux bash ожидает LF.

В ветке `home-server-vpn` исправлен Windows deploy: перед SFTP upload `deploy.sh` теперь нормализуется в LF и отправляется UTF-8 без BOM.

Fix commit:

```text
fd99c6122200bcac9cdafc96cbb799ca378c1e33
```

Финальные snapshot-ветки Android/Windows не изменялись.


## Native systemd deployment — успешно 27.09.2026

Первая ручная установка после исправления CRLF завершилась успешно.

Результат:

```text
CSQTT_DEPLOY_OK
mode: systemd
binary: /usr/local/bin/csqtt
unit: /etc/systemd/system/csqtt.service
config: /etc/csqtt
peer: UDP/46000
web: TCP/46002
PID: 29951
TUN: csqtt1 active
WAN detected by deploy.sh: enp2s0
NAT: MASQUERADE for 10.66.67.0/24 via enp2s0
web local health: HTTPS 401
```

Установщик подтвердил:
- Ubuntu 26.04.1 LTS;
- kernel 7.0.0-34-generic;
- TUN работает;
- iptables backend: nf_tables;
- протокол бинарника: CSQTT-WIRE-3;
- systemd unit создан и включён.

### Публичные IPv4 и policy routing Keenetic — подтверждено

Во время установки Ubuntu/CSQTT исходящий публичный IPv4 определялся как:

```text
144.31.103.134
```

Белый входящий IPv4 домашнего подключения:

```text
37.79.203.247
```

Это не ошибка и не асимметричный маршрут. На Keenetic действует policy routing:

- часть направлений выходит напрямую через провайдера и видна как `37.79.203.247`;
- часть направлений уходит через Amnezia WireGuard и видна как `144.31.103.134`.

Ubuntu/CSQTT находится за Keenetic и передаёт ему уже NAT-ированный VPN-трафик. Какой внешний IP увидит конкретный сайт, определяется правилами Keenetic.

Проверено после native systemd deploy:

```text
ip route get 1.1.1.1 -> via 192.168.1.1 dev enp2s0 src 192.168.1.73
UDP/46000 -> csqtt listening on 0.0.0.0:46000
csqtt.service -> active (running)
web -> 0.0.0.0:46002
TUN -> Userspace TUN (CSQTT)
```

Внешний Android-тест через мобильную сеть успешно подключился к `37.79.203.247:46000/udp`, что подтвердило всю цепочку двойного NAT и port-forward.



# Актуальный снимок проекта — 27.09.2026

Этот раздел является текущим источником истины и заменяет ранние плановые формулировки выше, если между ними есть расхождения.

## Домашний сервер

```text
Ubuntu host LAN: 192.168.1.73/24
LAN interface:   enp2s0
Gateway:         192.168.1.1
Public inbound:  37.79.203.247
Amnezia WG exit: 144.31.103.134
CSQTT peer:      UDP/46000
CSQTT web:       TCP/46002 (локально, наружу не публиковать)
VPN subnet:      10.66.67.0/24
Service mode:    native systemd
Binary:          /usr/local/bin/csqtt
Config dir:      /etc/csqtt
Unit:            /etc/systemd/system/csqtt.service
Wire protocol:   CSQTT-WIRE-3
Server version:  2.1.9
```

Проброс портов:

```text
Internet 37.79.203.247:46000/UDP
 -> ISP router
 -> Keenetic WAN 192.168.0.13
 -> Ubuntu 192.168.1.73:46000/UDP
```

Наружу не открывать без отдельной необходимости:

```text
TCP/22
TCP/80
TCP/46002
```

## Маршрутизация после домашнего сервера

CSQTT выполняет NAT/MASQUERADE для `10.66.67.0/24` через `enp2s0`. Далее Keenetic применяет собственную policy routing:

```text
VPNSL client
 -> CSQTT/Ubuntu
 -> Keenetic
    -> direct ISP -> 37.79.203.247
    OR
    -> Amnezia WG -> 144.31.103.134
```

Поэтому `144.31.103.134` является штатным выходом через Amnezia WG, а не ошибкой.

## Актуальные клиенты

Android:

```text
release: v1.0.10
final branch: final/android-v1.0.10
release commit: 006bdce8309515c0e5b78f436569d186535e8ee9
```

Основное:
- Full Tunnel IPv4 по умолчанию;
- режим «Приложения» сохранён;
- режим «IP / файлы» сохранён;
- генератор маршрутов сохранён;
- установка Linux-сервера усилена защитой от CRLF/BOM и проверкой `bash -n`.

Windows:

```text
release: windows-v1.0.3
final branch: final/windows-v1.0.3
release commit: ec18bbede0037a1f72c0babbede94b2b4f783147
```

Основное:
- маршрутизация Windows 1.0.2 сохранена;
- `deploy.sh` нормализуется CRLF/CR -> LF без BOM;
- после SFTP выполняется удалённая проверка `bash -n /tmp/deploy.sh`;
- проверяются размеры загруженных файлов;
- server-assets проверяются в готовом Windows-пакете.

## Ошибка CRLF и окончательное исправление

Наблюдавшаяся ошибка первой Windows-установки:

```text
/tmp/deploy.sh: $'\r': command not found
set: pipefail: недопустимое название параметра
```

Причина: Windows CRLF в shell script.

Исправление теперь присутствует и в Android 1.0.10, и в Windows 1.0.3. Скрипт перед исполнением нормализуется и проходит синтаксическую проверку Bash. Установка не должна переходить к замене работающего сервера, если `deploy.sh` повреждён.

## Текущая производительность

На пользовательском подключении наблюдалась скорость порядка:

```text
~5 Мбит/с
```

Это зафиксировано как текущая измеренная базовая точка, а не как лимит сервера. Для дальнейшей диагностики планируется сравнивать скорость на UDP при 18 / 27 / 36 / 54 воркерах. В коде Android:
- MTU = 1300;
- стандартно 18 воркеров;
- воркеры идут группами по 9;
- поддерживается до 126;
- UDP batching до 128 datagrams;
- серверные UDP socket buffers настроены значительно выше 5 Мбит/с.

## Безопасность и секреты

В GitHub намеренно НЕ сохраняются:
- SSH password;
- основной пароль VPNSL;
- web login/password;
- VK hashes/tokens;
- приватные SSH-ключи;
- `/tmp/.csqtt-upload-web.env`;
- `/tmp/.csqtt-upload-overrides.json`;
- приватные TLS-ключи;
- содержимое секретных файлов из `/etc/csqtt`.

Для восстановления эти значения должны быть введены заново из личного безопасного хранилища.

## Репозиторий как резервная копия

Серверный исходный код уже находится в этом репозитории:

```text
rust-server/
app/src/main/assets/deploy.sh
shared/
```

Дополнительно создан безопасный backup-набор в `server-backup/`, содержащий:
- текущую топологию и параметры;
- restore checklist;
- скрипт безопасного экспорта состояния живого сервера без секретов;
- список того, что никогда нельзя публиковать в GitHub.

