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


## Stage 2 live verification — 2026-10-05

Confirmed on the live home server:

- Telegram bot responds to `/start`;
- Telegram `/status` reports Ollama OK and model `qwen3.5:4b-q4_K_M`;
- Web UI opens on the LAN;
- Web UI health header reports Ollama OK and Telegram ON;
- Web chat sends prompts to the local Qwen model and receives a response identifying itself as the local Server AI Agent.

One remaining Stage 2 check before declaring shared-history behavior fully verified:
send a normal (non-command) message in Telegram and confirm that the message and model reply appear in the Web UI history.

Do not enable host filesystem, shell, Docker socket or administrative execution until the shared-history check is complete.


## Shared history verified + empty-reply fix — 2026-10-05

Verified: a normal Telegram message appears in the Web UI with source `telegram`, so Telegram -> shared SQLite -> Web synchronization works.

Observed issue: the corresponding assistant row could be empty. Qwen 3.5 is a thinking-capable model and Ollama separates reasoning from the final `message.content`. The agent must not expose or persist the reasoning trace as a substitute for the final answer.

Fix:
- added `QWEN_THINK=false` default;
- chat requests now explicitly send `"think": false`;
- if Ollama still returns an empty final `message.content`, the agent stores a clear diagnostic message instead of a blank assistant bubble.

Set in local `.env`:

```text
QWEN_THINK=false
```

Then rebuild only the agent container:

```bash
cd ~/WDTTSL
git pull --ff-only
cd server-ai
docker compose up -d --build agent
```

After rebuild, repeat one normal Telegram message and confirm that both the message and a non-empty assistant reply appear in Web UI.


## Stage 2 fully verified — 2026-10-05

Final live check passed.

Telegram prompt:

```text
Ответь одним предложением: где ты сейчас работаешь?
```

Agent response:

```text
Я работаю локально на вашем домашнем Ubuntu-сервере.
```

This confirms:
- Telegram -> agent -> local Qwen response path works;
- `think=false` fix prevents blank assistant messages;
- the model correctly identifies its local deployment context;
- shared Telegram/Web history remains enabled.

Stage 2 is now considered complete. Next stage: READ-only server tools and filesystem visibility, without write/admin privileges.


## Stage 3 broker smoke test verified — 2026-10-05

The native READ broker was installed and successfully queried through:

```text
/run/server-ai/read.sock
```

Verified live result from `server_snapshot(section=overview)`:

- hostname: `home`;
- uptime: about 7h15m at test time;
- kernel: Ubuntu `7.0.0-38-generic`;
- memory: 15 GiB total, about 12 GiB available;
- swap: 4 GiB, effectively unused.

This confirms the host-side read-only broker and Unix-socket transport are working. Stage 3 is not yet fully verified until the container health reports `read_tools: true` and Qwen autonomously invokes at least one READ tool from Telegram or Web.


## GPU container recovery checkpoint — 2026-10-05

After installing the native READ broker, the existing Ollama container lost functional NVIDIA access: `/dev/nvidia*` was still present, but `nvidia-smi` inside the container returned `Failed to initialize NVML: Unknown Error`, CUDA initialization failed, and `ollama ps` showed the Qwen model on `100% CPU`.

Recreating only the Ollama container restored NVIDIA access:

```bash
cd ~/WDTTSL/server-ai
docker compose up -d --force-recreate ollama
```

Verified immediately after recreation: `docker compose exec ollama nvidia-smi` successfully reported the GTX 1660 Super.

The READ broker installer was also changed so repeated code updates do not run `systemctl daemon-reload` unless the unit file itself changed. This reduces the chance of repeating the NVIDIA container/cgroup disruption during normal broker updates.

The model GPU execution itself still requires a post-recreation inference check with `ollama ps` before marking full Qwen GPU operation restored.


## Stage 3 autonomous READ call verified, synthesis accuracy issue — 2026-10-05

The live agent successfully completed an autonomous READ-mode health request from Telegram after GPU recovery and READ-loop optimization.

Confirmed operational path:
- Telegram -> agent;
- agent -> Qwen on GPU;
- Qwen -> READ tools;
- READ broker -> host diagnostics;
- tool result -> Qwen;
- Qwen -> Telegram final response.

However, the first synthesized health report contained factual inconsistencies versus previously verified live diagnostics, including uptime and some container/storage details. Therefore Stage 3 plumbing is working, but factual grounding/synthesis is not yet considered production-safe.

Next requirement before marking Stage 3 fully trusted:
- make factual server reports strictly grounded in tool output;
- prefer compact structured health tools;
- expose/retain tool-call evidence for debugging;
- avoid filling missing fields from model memory or guesses;
- optionally include a short "checked data" section from tool results in diagnostic answers.


## Stage 3 strict grounding rollout — 2026-10-05

A stricter synthesis path was added for READ requests.

After the first READ tool call in a request:
- previous chat history is removed from the factual synthesis context;
- only the current user request and READ tool results from the current turn remain authoritative;
- the model is instructed to copy current values exactly from tool output;
- missing values must be reported as `не проверено`;
- tool errors must be reported instead of replaced by guesses;
- inferences must be separated from observed data;
- the final reply automatically appends a `Проверено инструментами` line.

Health now exposes:

```json
"strict_grounding": true
```

Telegram `/status` and the Web UI also display `Grounding: STRICT`.

This rollout must be live-tested against the same server-health request and compared with direct READ broker output before Stage 3 is considered trusted.


## Strict grounding status verified live — 2026-10-05

Telegram `/status` was verified on the live server and reports:

```text
Ollama: OK
Модель: qwen3.5:4b-q4_K_M
READ tools: ON
Grounding: STRICT
```

This confirms the updated agent build is running with READ mode and strict grounding enabled. Final Stage 3 trust verification still requires comparing a grounded health response against the direct `server_health` broker output.


## Strict grounding baseline captured — 2026-10-05

Direct `server_health` broker output was captured before the final grounding comparison.

Verified baseline at the test moment:
- uptime: about 7h45m;
- memory: 15 GiB total, 4.1 GiB used, 10 GiB available;
- swap: 4.0 GiB total, ~104 KiB used;
- root filesystem: 98G total, 40G used, 54G available, 43%;
- `/srv/media`: 466G total, 198G used, 268G available, 43%;
- Docker: 9 running containers;
- failed systemd units: 0.

The agent log grep returned no `[READ]` lines at this point, so the grounded Telegram health request still needs to be sent/re-sent and then compared against this baseline before Stage 3 is marked fully trusted.


## Grounding comparison result — 2026-10-05

The strict-grounding health request was executed successfully with:

```text
[READ] tool=server_health argument_keys=[]
[READ] tool=server_health elapsed=0.04s result_chars=3348
```

Ollama remained on `100% GPU`.

The final Telegram response matched the live READ data closely, including uptime, memory, root storage, `/srv/media`, all 9 running Docker containers, and zero failed systemd units. One transcription error remained: the EFI filesystem usage percentage was reported as 11% although the direct `df` evidence showed 1% (11% belonged to `/boot`).

Because of that residual numeric transcription error, Stage 3 is not yet marked fully trusted. The `server_health` broker now returns structured JSON fields instead of raw human-readable command tables for uptime, memory, filesystems, Docker containers and failed units. This is intended to reduce row/column confusion and numeric copying errors in the 4B model.

The strict grounding prompt was also tightened to require Russian-only diagnostic prose unless another language is requested.


## Grounding truncation fix — 2026-10-05

The structured `server_health` result was still being clipped to the configured tool-result budget before the Docker and failed-systemd fields reached Qwen. Evidence: the READ trace reported `result_chars=3525` while the configured cap was 3500, and the model then incorrectly stated that Docker/systemd information was absent even though the direct broker JSON contained both sections.

Fix:
- `server_health` now omits pseudo filesystems (`overlay`, `tmpfs`, `efivarfs`) from the broad health summary;
- real mounted filesystems remain, including root, `/boot`, `/boot/efi`, and `/srv/media`;
- Docker containers plus `docker_count` are returned explicitly;
- failed systemd units plus `failed_systemd_count` are returned explicitly;
- the strict grounding prompt requires those fields to be reported when present.

Detailed pseudo/overlay filesystem information remains available through the broader storage snapshot tool when specifically requested.

This keeps the broad health payload compact enough to preserve all requested sections without increasing the local model context budget.
