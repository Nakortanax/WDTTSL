# Homer dashboard

Центральная домашняя панель для сервисов сервера `192.168.1.73`.

## Адрес

После развёртывания:

```text
http://192.168.1.73:8088
```

Порт публикуется только на LAN-адресе сервера. На ISP/Keenetic наружу `8088/tcp` не пробрасывать.

## Состав первой версии

Панель содержит ссылки/карточки для:

- AdGuard Home;
- VPNSL / CSQTT;
- Keenetic;
- Jellyfin;
- Transmission;
- Samba;
- Fuel service;
- WeightDiaryBot;
- Ollama;
- PostgreSQL;
- SSH;
- XRDP;
- Docker;
- host metrics;
- system updater;
- legacy GPN bot/editor.

Секреты, API-ключи и пароли в `config.yml` не хранятся.

## Почему smart cards пока не включены

Homer отдаёт `assets/config.yml` браузеру. Поэтому нельзя помещать туда:

- пароль AdGuard;
- Jellyfin API key;
- Transmission credentials;
- VPNSL/CSQTT credentials.

После базовой проверки можно отдельно добавить безопасный proxy для динамических карточек.

## Развёртывание на сервере

Файлы должны находиться так:

```text
/opt/homer/
├── compose.yaml
└── assets/
    └── config.yml
```

Запуск:

```bash
cd /opt/homer
sudo docker compose up -d
sudo docker compose ps
curl -I http://192.168.1.73:8088
```

Остановка без удаления данных:

```bash
cd /opt/homer
sudo docker compose stop
```

Не использовать `docker compose down -v`.

## Безопасность

- Homer не публикуется в интернет.
- Не добавлять в YAML пароли, токены, API keys или private keys.
- Не менять существующие Docker volumes.
- Не изменять VPNSL/CSQTT, WeightDiaryBot, Jellyfin, Transmission или AdGuard при установке панели.


## Подтверждённая установка — 28.09.2026

Homer успешно развёрнут на домашнем сервере.

```text
Container: homer
Image: b4bz/homer:latest
Status: healthy
Bind: 192.168.1.73:8088 -> 8080/tcp
HTTP check: HTTP/1.1 200 OK
Server: lighttpd/1.4.85
```

Проверено командами:

```bash
cd /opt/homer
sudo docker compose ps
curl -I http://192.168.1.73:8088
```

На момент проверки контейнер был `Up ... (healthy)`.

Первый `docker compose up -d` завис на pull/finalization образа до создания контейнера. После отдельного:

```bash
sudo docker pull b4bz/homer:latest
```

повторный `docker compose up -d` завершился успешно.
