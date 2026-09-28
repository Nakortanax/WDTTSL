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


## Подтверждённый запуск — 28.09.2026

Контейнеры успешно запущены:

```text
homer-docker-proxy   Up
homer-status         Up
homer-status bind:   192.168.1.73:8090 -> 8090/tcp
docker proxy:        internal only, 2375/tcp not published on host
```

Проверка `/summary`:

```text
adguard      ok, HTTP 200
vpnsl        ok, HTTP 401
keenetic     ok, HTTP 200
jellyfin     ok, HTTP 200
transmission ok, HTTP 403
fuel         ok, HTTP 404
homer        ok, HTTP 200
glances      ok, HTTP 200
docker       ok, 9 running / 0 stopped / 9 total
```

Коды 401/403/404 здесь означают, что сервис ответил по HTTP и считается доступным; status-proxy возвращает offline только при сетевой ошибке/таймауте или ответе 5xx.

Sanitized Docker endpoint вернул только состояния девяти контейнеров:

```json
[{"State":"running"} ... x9]
```


## Docker-backed internal services

28.09.2026 подтверждены дополнительные health endpoints:

```text
/health/docker-service/weightdiary -> ok: true
/health/docker-service/ollama      -> ok: true
/health/docker-service/postgres    -> ok: true
```

Исправлен порядок маршрутов: `/health/docker-service/*` должен обрабатываться раньше общего `/health/*`, иначе возвращается `unknown service`.

Проверенный результат:

```json
{"service":"weightdiary","ok":true}
{"service":"ollama","ok":true}
{"service":"postgres","ok":true}
```


## Host TCP checks

28.09.2026 подтверждены живые TCP-проверки сервисов хоста:

```text
SSH   192.168.1.73:22    -> ok: true
Samba 192.168.1.73:445   -> ok: true
XRDP  192.168.1.73:3389  -> ok: true
```

Проверенные endpoints:

```text
/health/tcp/ssh
/health/tcp/samba
/health/tcp/xrdp
```
