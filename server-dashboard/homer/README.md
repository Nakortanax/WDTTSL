# Homer dashboard

Центральная домашняя панель сервера `192.168.1.73`.

## Текущее рабочее состояние — 28.09.2026

```text
URL:       http://192.168.1.73:8088
Container: homer
Image:     b4bz/homer:latest
Status:    healthy
Bind:      192.168.1.73:8088 -> 8080/tcp
HTTP:      200 OK
```

Порт публикуется только на LAN-адресе сервера. Через ISP/Keenetic наружу `8088/tcp` не пробрасывать.

## Что показывает панель

Живые карточки:
- ресурсы Ubuntu через Glances: CPU, RAM, load, swap;
- Docker: количество running/stopped контейнеров;
- AdGuard Home;
- VPNSL / CSQTT;
- Keenetic;
- Jellyfin;
- Transmission;
- Fuel service;
- WeightDiaryBot (топливо, сервер, климат);
- SSH;
- Samba;
- XRDP.

Статические карточки:
- System Updater;
- legacy GPN Fuel Bot;
- legacy GPN Stations Editor.

Systemd helper для последних трёх сервисов обсуждался, но пользователь решил остановиться на текущем варианте. Он не установлен и в финальной конфигурации отсутствует.

## Файлы на сервере

```text
/opt/homer/
├── compose.yaml
└── assets/
    └── config.yml
```

Конфигурация в GitHub:

```text
branch: home-dashboard-homer
server-dashboard/homer/
```

## Связанные сервисы панели

```text
Glances:
  http://192.168.1.73:61208

Homer status proxy:
  http://192.168.1.73:8090

Docker socket proxy:
  internal compose network only
  host port 2375 NOT published
```

## Безопасность

- Homer не публикуется в интернет.
- В `config.yml` нет паролей, токенов и API keys.
- Raw Docker socket не доступен браузеру и не опубликован наружу.
- Docker proxy read-only: разрешён только необходимый GET к контейнерам, POST отключён.
- Status proxy отдаёт только минимальные состояния сервисов.
- Существующие Docker volumes не изменялись и не удалялись.
- VPNSL/CSQTT, WeightDiaryBot, Jellyfin, Transmission и AdGuard при установке панели не изменялись.

## Проверка

```bash
cd /opt/homer
sudo docker compose ps
curl -I http://192.168.1.73:8088
```

Остановка без удаления данных:

```bash
cd /opt/homer
sudo docker compose stop
```

Не использовать `docker compose down -v`.


## Актуализация — 29–30.09.2026

После упрощения WeightDiaryBot из панели удалены отдельные карточки Ollama и PostgreSQL 17.
Локальный ИИ и дневник больше не входят в активную архитектуру Telegram-бота.

Текущий раздел «Наши приложения» содержит Fuel service и WeightDiaryBot.

30.09.2026 конфигурация из ветки `home-dashboard-homer` применена на живом сервере.
Подтверждено:
- контейнер `homer` healthy и отвечает HTTP 200 на `:8088`;
- `homer-status` работает на `:8090`;
- `/health/docker-service/weightdiary` возвращает HTTP 200 и `ok: true`;
- старые endpoints `/health/docker-service/ollama` и `/health/docker-service/postgres`
  возвращают HTTP 404 `unknown docker service`;
- live `config.yml` больше не содержит карточки Ollama и PostgreSQL.
