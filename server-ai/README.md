# Server AI Agent

Local Qwen-based administration and development agent for the home Ubuntu server.

Working branch: `server-ai-agent`.

## Target interfaces

- Telegram bot;
- web UI linked from Homer;
- one shared conversation/task history.

## Target capabilities

- read system files, logs and mounted disks;
- inspect Docker, systemd, network, storage and server health;
- work with Git repositories through branches, tests and diffs;
- internet search and documentation retrieval;
- controlled administrative actions through a separate host executor.

## Security model

Three modes are planned:

- READ — diagnostics and read-only access;
- WORK — controlled edits inside approved Git workspaces and test/build actions;
- ADMIN — host changes through an approval-gated executor.

The Qwen/Ollama container must not receive unrestricted root shell, privileged mode, or the raw Docker socket.

Destructive actions such as volume deletion, filesystem formatting, firewall flushes and destructive resets are prohibited unless explicitly approved outside the agent policy.

## Stage 1 — Ollama + Qwen — VERIFIED 2026-10-05

Model:

```text
qwen3.5:4b-q4_K_M
```

Verified on the live server with NVIDIA GPU acceleration.

Observed during a real prompt:

```text
GPU: NVIDIA GeForce GTX 1660 Super 6 GB
llama-server VRAM: ~3924 MiB
total GPU memory in use: ~3994 MiB
GPU utilization: ~83%
temperature: 73 C
```

The model's first raw CLI answer said it ran "in the cloud". That was model self-description without deployment context, not an infrastructure result. Stage 2 adds a system prompt that explicitly identifies it as the local Server AI Agent.

## Stage 2 — shared Web + Telegram chat

The `agent` service provides:

- FastAPI on `192.168.1.73:8092`;
- HTTP Basic authentication for the web UI;
- SQLite history at `/var/lib/server-ai/agent/agent.db`;
- one shared message history for Web and Telegram;
- Telegram long polling when a token is configured;
- only explicitly allowed Telegram user IDs;
- system prompt identifying Qwen as a local model;
- no filesystem, shell, Docker socket or host-admin access yet.

Container hardening for this stage:

- non-root host UID/GID;
- read-only container filesystem;
- only `/data` writable;
- all Linux capabilities dropped;
- `no-new-privileges`;
- no Docker socket;
- no host filesystem mounts.

### Update local branch

```bash
cd ~/WDTTSL
git pull --ff-only
cd server-ai
```

### Prepare data directory

```bash
sudo mkdir -p /var/lib/server-ai/agent
sudo chown -R "$USER":"$USER" /var/lib/server-ai
```

### Update local secrets

Do not paste secrets into GitHub or chat.

Generate a web password:

```bash
openssl rand -base64 24
```

Edit the untracked local file:

```bash
nano ~/WDTTSL/server-ai/.env
```

Ensure it contains at least:

```text
SERVER_AI_DATA_DIR=/var/lib/server-ai
SERVER_AI_UID=1000
SERVER_AI_GID=1000
OLLAMA_CONTEXT_LENGTH=8192
QWEN_MODEL=qwen3.5:4b-q4_K_M
AGENT_BIND_IP=192.168.1.73
AGENT_WEB_USER=igor
AGENT_WEB_PASSWORD=<strong local password>
AGENT_HISTORY_MESSAGES=24
TELEGRAM_BOT_TOKEN=
TELEGRAM_ALLOWED_USER_IDS=
```

### Telegram

Create a dedicated bot with `@BotFather`. Put its token only in `.env`:

```text
TELEGRAM_BOT_TOKEN=<token>
```

Use the Telegram user ID already allowed by the existing private bot, or obtain your numeric user ID locally. Put only the numeric ID(s) in:

```text
TELEGRAM_ALLOWED_USER_IDS=<numeric id>
```

If the token is blank, the agent starts normally with Telegram disabled.

### Build and start

```bash
cd ~/WDTTSL/server-ai
docker compose up -d --build agent
docker compose ps
curl -s http://192.168.1.73:8092/health
```

Expected health payload includes:

```json
{"ok":true,"ollama":true,"model":"qwen3.5:4b-q4_K_M","telegram":false}
```

Open:

```text
http://192.168.1.73:8092
```

The browser asks for the configured Basic Auth username/password.

Recommended first Web prompt:

```text
Где ты сейчас работаешь и какие инструменты у тебя подключены?
```

At this stage Qwen should identify itself as local and must say that filesystem/shell/Git/web tools are not connected yet.

Telegram commands:

```text
/start
/status
/new
```

`/new` clears the shared Web + Telegram conversation history.

## Next stages

After Stage 2 is verified:

1. READ filesystem and server diagnostics;
2. Git workspaces and controlled code edits;
3. internet search;
4. approval-gated host executor;
5. Homer card and monitoring integration;
6. recovery checkpoint.
