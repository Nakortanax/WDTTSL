# Homer live status proxy

Минимальный read-only слой для живых статусов Homer.

## Зачем он нужен

Homer работает в браузере, поэтому прямые запросы к AdGuard, Jellyfin, Transmission, Keenetic и VPNSL могут блокироваться CORS, авторизацией или self-signed TLS.

Этот сервис:
- проверяет доступность сервисов сервер-сайд;
- возвращает только `online/offline` + latency/status code;
- не хранит логины, пароли или API keys;
- добавляет CORS только к собственным безопасным ответам;
- предоставляет Homer минимальный Docker endpoint только со значением `State` каждого контейнера.

## Docker socket

Raw Docker socket не публикуется наружу.

`docker-socket-proxy`:
- доступен только внутри compose-сети;
- разрешает только GET к `CONTAINERS`;
- POST отключён;
- наружу порт 2375 не публикуется.

Публичный для LAN слой `homer-status` возвращает лишь sanitized состояния контейнеров.

## LAN endpoint

```text
http://192.168.1.73:8090
```

На роутерах наружу не пробрасывать.

## Проверка

```bash
curl -s http://192.168.1.73:8090/
curl -s http://192.168.1.73:8090/summary
curl -s http://192.168.1.73:8090/health/adguard
curl -s 'http://192.168.1.73:8090/containers/json?all=true'
```
