# Homer systemd status helper

Минимальный read-only helper на самом Ubuntu-хосте для проверки нескольких systemd unit'ов.

## Почему отдельный helper

Контейнер `homer-status` не получает доступ к systemd/DBus хоста. Вместо монтирования host systemd socket в контейнер используется маленький host-сервис, который разрешает только заранее заданный список unit'ов.

## Endpoint

```text
http://192.168.1.73:8091
```

Не пробрасывать этот порт через ISP/Keenetic.

Разрешённые логические сервисы:

```text
system-updater -> weightdiary-system-updater.service
host-metrics   -> weightdiary-host-metrics.service
gpn-bot        -> gpn-bot.service
gpn-editor     -> gpn-editor.service
csqtt          -> csqtt.service
```

Сервис возвращает только `active/inactive/failed/unknown`; запуск, остановка и изменение unit'ов не поддерживаются.

## Установка

```bash
sudo mkdir -p /opt/homer-systemd-status
sudo cp systemd_status.py /opt/homer-systemd-status/systemd_status.py
sudo cp homer-systemd-status.service /etc/systemd/system/homer-systemd-status.service
sudo chmod 644 /opt/homer-systemd-status/systemd_status.py
sudo chmod 644 /etc/systemd/system/homer-systemd-status.service
sudo systemctl daemon-reload
sudo systemctl enable --now homer-systemd-status.service
```

## Проверка

```bash
curl -s http://192.168.1.73:8091/
curl -s http://192.168.1.73:8091/service/system-updater
curl -s http://192.168.1.73:8091/service/host-metrics
curl -s http://192.168.1.73:8091/service/gpn-bot
curl -s http://192.168.1.73:8091/service/gpn-editor
```
