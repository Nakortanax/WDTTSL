# Restore checklist — Home VPNSL server

## 1. Сеть

На Ubuntu восстановить постоянный LAN адрес:

```text
192.168.1.73/24
gateway 192.168.1.1
interface enp2s0
```

На роутерах восстановить только:

```text
Internet UDP/46000
 -> ISP router
 -> Keenetic 192.168.0.13
 -> Ubuntu 192.168.1.73:46000/UDP
```

По умолчанию не открывать наружу TCP/22, TCP/80, TCP/46002.

## 2. Сервер

Требования:

```text
Linux
systemd
/dev/net/tun
iptables/nft compatible
net.ipv4.ip_forward=1
```

Установщик и серверный код брать из этого репозитория.

Предпочтительный режим:

```text
native systemd
```

Ожидаемые пути после deploy:

```text
/usr/local/bin/csqtt
/etc/csqtt
/etc/systemd/system/csqtt.service
```

## 3. Секреты

Не брать из GitHub. Ввести заново:
- основной пароль VPNSL;
- web login/password;
- SSH credentials;
- клиентские VK hashes/tokens.

## 4. Проверка после восстановления

```bash
sudo systemctl status csqtt --no-pager -l
ip -br addr
ip route
cat /proc/sys/net/ipv4/ip_forward
sudo ss -lunp | grep ':46000'
sudo iptables -S FORWARD
sudo iptables -t nat -S POSTROUTING
```

Ожидается:
- csqtt active;
- UDP/46000 listening;
- TUN csqtt1;
- IPv4 forwarding = 1;
- NAT/MASQUERADE для 10.66.67.0/24.

## 5. Клиентский тест

Android:

```text
release v1.0.10
branch final/android-v1.0.10
```

Windows:

```text
release windows-v1.0.3
branch final/windows-v1.0.3
```

Проверять из внешней сети подключение к:

```text
37.79.203.247:46000/UDP
```

После подключения внешний IP может быть:
- 37.79.203.247 при direct ISP;
- 144.31.103.134 при маршруте Keenetic через Amnezia WG.

Оба варианта штатные.
