# Restore checklist — Home server

Актуализация: 29.09.2026.

## 1. Базовая сеть

Ubuntu:

```text
LAN: 192.168.1.73/24
gateway: 192.168.1.1
interface: enp2s0
```

Public VPNSL path:

```text
Internet UDP/46000
 -> ISP router
 -> Keenetic 192.168.0.13
 -> Ubuntu 192.168.1.73:46000/UDP
```

По умолчанию НЕ открывать наружу:
- 22/tcp;
- 53/tcp/udp;
- 46002/tcp;
- 8080/tcp;
- 8088/tcp;
- 8090/tcp;
- 8096/tcp;
- 9091/tcp;
- 61208/tcp;
- Samba/XRDP.

## 2. CSQTT

Требования:

```text
Linux
systemd
/dev/net/tun
iptables/nft compatible
net.ipv4.ip_forward=1
```

Ожидаемые пути:

```text
/usr/local/bin/csqtt
/etc/csqtt
/etc/systemd/system/csqtt.service
```

Параметры:

```text
version: 2.1.9
wire: CSQTT-WIRE-3
peer: UDP/46000
web: HTTPS/TCP/46002
VPN subnet: 10.66.67.0/24
```

Проверка:

```bash
sudo systemctl status csqtt --no-pager -l
ip -br addr
ip route
cat /proc/sys/net/ipv4/ip_forward
sudo ss -lunp | grep ':46000'
sudo iptables -S FORWARD
sudo iptables -t nat -S POSTROUTING
```

## 3. AdGuard Home

Docker paths:

```text
/opt/adguardhome/conf
/opt/adguardhome/work
```

Порты:

```text
192.168.1.73:53 -> 53/tcp+udp
192.168.1.73:8080 -> 80/tcp
```

Keenetic:
- DNS = `192.168.1.73`;
- ignore ISP DNSv4 = enabled;
- не возвращать глобальные DoT/DoH, если цель — обязательный проход через AdGuard.

Проверка:

```bash
nslookup example.com 192.168.1.73
```

## 4. Homer dashboard

GitHub source:

```text
branch: home-dashboard-homer
server-dashboard/homer/
```

Server path:

```text
/opt/homer/
```

Ожидаемый URL:

```text
http://192.168.1.73:8088
```

Проверка:

```bash
cd /opt/homer
sudo docker compose up -d
sudo docker compose ps
curl -I http://192.168.1.73:8088
```

## 5. Glances

GitHub source:

```text
server-dashboard/glances/
```

Server path:

```text
/opt/glances/
```

Проверка:

```bash
cd /opt/glances
sudo docker compose up -d
curl -s http://192.168.1.73:61208/api/4/status
```

Ожидаемая проверенная версия: `4.5.7`.

## 6. Homer status layer

GitHub source:

```text
server-dashboard/status/
```

Server path:

```text
/opt/homer-status/
```

Контейнеры:
- `homer-status`;
- `homer-docker-proxy`.

Проверка:

```bash
cd /opt/homer-status
sudo docker compose up -d
sudo docker compose ps
curl -s http://192.168.1.73:8090/summary
```

Docker proxy 2375 не должен быть опубликован на host.

Отдельный systemd helper на 8091 не требуется и в финальный вариант не входит.

## 7. Остальные сервисы

После восстановления проверить:
- WeightDiaryBot;
- PostgreSQL;
- Ollama;
- Fuel;
- Jellyfin;
- Transmission;
- Samba;
- XRDP;
- SSH.

Не удалять volumes и не использовать `docker compose down -v`.

## 8. Секреты

Не брать из GitHub. Восстановить из отдельного защищённого хранилища:
- VPNSL main password;
- CSQTT web login/password;
- SSH credentials;
- VK hashes/tokens;
- TLS private keys;
- AdGuard credentials;
- другие API keys/secrets.

## 9. Клиентский тест

Android:

```text
v1.0.10
final/android-v1.0.10
```

Windows:

```text
windows-v1.0.3
final/windows-v1.0.3
```

Проверять VPNSL из внешней сети на:

```text
37.79.203.247:46000/UDP
```

Ожидаемый public exit:
- `37.79.203.247` direct ISP;
- `144.31.103.134` через Amnezia WG.

Оба варианта штатны.
