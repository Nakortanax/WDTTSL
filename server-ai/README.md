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


## Mandatory fresh READ evidence — 2026-10-05

A subsequent live health reply exposed another failure mode: Qwen sometimes answered a current server-state request from recent chat history without invoking any READ tool.

Evidence from the failed live attempt:
- no new `[READ]` log lines were produced for that reply;
- the automatic `Проверено инструментами` suffix was absent;
- the response repeated stale pseudo-filesystem details that had already been removed from the current compact `server_health` payload.

Application-level enforcement was added:
- current server-state requests are detected before a model-only answer is accepted;
- broad health requests execute `server_health` deterministically before Qwen synthesizes the response;
- other detected server-state requests get one retry instruction if Qwen tries to answer without calling a READ tool;
- if Qwen still does not call a READ tool, the stale/model-only answer is blocked and replaced with an explicit diagnostic message;
- explicit chat-history questions remain normal conversation and do not trigger server diagnostics.

Health now reports `"read_enforcement": true`. Telegram `/status` reports `READ enforcement: ON`.

Stage 3 still requires one final live verification after this enforcement change.


## Mandatory READ enforcement verified live — 2026-10-05

The enforced health path was verified on the live server.

Agent trace:

```text
[READ] selected=server_health reason=health_request
[READ] tool=server_health elapsed=0.03s result_chars=1710
```

This confirms that a broad current server-health request can no longer be answered from stale chat history: the application selects and executes fresh `server_health` data before synthesis.

The compact structured payload is now 1710 characters, comfortably below the configured tool-result limit. Final Stage 3 verification still requires checking the Telegram answer itself against the current structured health data and confirming the `Проверено инструментами: server_health.` suffix.


## Full project checkpoint saved — 2026-10-05

All Server AI Agent work completed up to this point has been committed to GitHub on branch `server-ai-agent`.

Included in the checkpoint:
- local Ollama/Qwen deployment and verified GPU execution;
- shared Telegram + Web agent with SQLite history;
- READ-only host broker and filesystem visibility;
- secret filtering and broker allowlists;
- strict grounding for diagnostic answers;
- compact structured `server_health`;
- protection against stale chat-history answers for current server-state requests;
- mandatory fresh READ execution for broad health checks;
- live verification that `server_health` is selected automatically and returns a compact payload below the configured tool-result limit;
- documented NVIDIA container recovery after the systemd daemon-reload incident;
- installer hardening to avoid unnecessary `systemctl daemon-reload`.

Local secrets and machine-specific secret values remain intentionally excluded from GitHub (for example `server-ai/.env`, Telegram token, and web password).

Current next step: verify the final grounded Telegram health response itself, then mark Stage 3 fully complete before enabling any WORK-mode write capabilities.


## CDI GPU stabilization rollout — 2026-10-05

The Ollama container lost NVIDIA access a second time while still showing the legacy Docker GPU device request. Live symptoms repeated exactly:
- `ollama ps`: `100% CPU`;
- `nvidia-smi` inside the existing Ollama container: `Failed to initialize NVML: Unknown Error`;
- recreating only the Ollama container immediately restored NVIDIA/NVML access and Qwen returned to `100% GPU`.

The host already has working NVIDIA CDI support:
- `nvidia-ctk cdi list` reports `nvidia.com/gpu=0`, the GPU UUID, and `nvidia.com/gpu=all`;
- `nvidia-cdi-refresh.path` is active;
- the one-shot `nvidia-cdi-refresh.service` previously completed successfully.

The Compose definition is therefore being migrated from legacy:

```yaml
gpus: all
```

to native CDI:

```yaml
devices:
  - "nvidia.com/gpu=all"
```

This change is committed but must be verified live by recreating only the Ollama container, checking `nvidia-smi` and `ollama ps`, and then testing that GPU access survives `systemctl daemon-reload`. Do not mark the CDI migration verified until that resilience test passes.


## CDI live activation verified — 2026-10-05

The server pulled the CDI Compose configuration and recreated only the Ollama container.

Verified live:
- `docker compose config` resolves the Ollama device as `nvidia.com/gpu=all`;
- `nvidia-smi` works inside the CDI-created Ollama container;
- after one API inference, `ollama ps` reports `100% GPU`;
- host `nvidia-smi` shows `/usr/lib/ollama/llama-server` using about 3916 MiB VRAM;
- total GPU memory usage was about 3986 MiB.

This confirms CDI device injection is active and Qwen inference is running on the GTX 1660 Super.

One resilience check remains before marking the GPU issue fully fixed: run `systemctl daemon-reload` while the CDI Ollama container is alive, then confirm both in-container `nvidia-smi` and `ollama ps` still show working GPU access.


## CDI daemon-reload resilience test — device access passed, inference recheck pending — 2026-10-05

Live resilience test after migrating Ollama to CDI:
- before `systemctl daemon-reload`, in-container `nvidia-smi` succeeded;
- after `systemctl daemon-reload`, in-container `nvidia-smi` still succeeded;
- therefore the prior failure mode (`Failed to initialize NVML: Unknown Error`) did not recur.

At the exact test moment `ollama ps` was empty both before and after daemon-reload because the model had already unloaded after its keep-alive timeout. Therefore this test proves CDI preserved NVIDIA device/NVML access across daemon-reload, but one final post-reload inference is still required to confirm Qwen reloads on `100% GPU`.


## CDI GPU stabilization VERIFIED — 2026-10-05

Final post-`systemctl daemon-reload` inference check passed.

Verified live after the reload:
- `ollama ps` reports `qwen3.5:4b-q4_K_M` on `100% GPU`;
- in-container `nvidia-smi` works normally;
- host `nvidia-smi` shows `/usr/lib/ollama/llama-server` using about 3924 MiB VRAM;
- total GPU memory usage is about 3994 MiB;
- the prior failure mode (`Failed to initialize NVML: Unknown Error` followed by CPU fallback) did not recur.

The CDI migration is therefore considered fully verified. The persistent Compose configuration remains:

```yaml
devices:
  - "nvidia.com/gpu=all"
```

Do not revert Ollama back to legacy `gpus: all` unless there is a specific compatibility reason and the NVML/cgroup regression is re-evaluated.


## Stage 4 WEB research — prepared, not yet live-verified — 2026-10-05

Goal: allow the local Qwen agent to search the public internet, read relevant pages, compare sources and return structured answers with source URLs, without giving the model arbitrary shell/network execution.

Architecture:
- private `searxng/searxng` container on the internal Compose network;
- no SearXNG host/LAN port is published;
- SearXNG JSON search API is enabled for the agent;
- new agent tools: `web_search`, `web_fetch`, `web_research`;
- `web_research` searches several results and fetches a small number of diverse pages in one bounded call;
- final agent replies automatically append the public source URLs actually returned by WEB tools.

WEB safety controls:
- only HTTP/HTTPS public destinations;
- local, private, loopback, link-local, multicast, reserved and internal-name destinations are blocked;
- fetch is limited to ports 80/443;
- redirects are revalidated;
- bounded timeouts, download size and extracted text size;
- non-text content is refused in this first version;
- page content is explicitly treated as untrusted evidence, never as instructions;
- no arbitrary shell and no raw network command execution is exposed to Qwen.

Grounding behavior:
- explicit internet/current-information requests must use a WEB tool;
- if Qwen tries to answer such a request only from memory/history, the answer is rejected and Qwen receives one forced tool-use retry;
- WEB evidence from the current request is used for synthesis;
- source URLs are appended by the application, not left solely to the model.

Configuration added:
- `AGENT_WEB_TOOLS=false` by default;
- `SEARXNG_SECRET` must be generated locally and kept only in `server-ai/.env`;
- `SEARXNG_URL=http://searxng:8080` is injected internally by Compose.

Live verification checklist before marking Stage 4 verified:
1. generate local `SEARXNG_SECRET` and set `AGENT_WEB_TOOLS=true`;
2. start `searxng` and rebuild only `agent`;
3. verify `/health` reports `web_tools:true` and `searxng:true`;
4. verify Telegram `/status` reports `WEB tools: ON`;
5. ask an explicitly current internet question;
6. confirm agent logs contain `[WEB] tool=...`;
7. confirm the answer contains structured facts and an automatic `Источники:` section;
8. test that `web_fetch` refuses a private URL such as `http://127.0.0.1/`.


## Stage 4 WEB smoke test verified — 2026-10-05

Live server verification passed for the new web-research substrate:
- SearXNG container started and reached `healthy`;
- agent `/health` reports `web_tools:true` and `searxng:true`;
- direct `web_search` returned real public results from NVIDIA documentation, NVIDIA GitHub releases, and Docker documentation;
- SSRF protection correctly rejected `http://127.0.0.1/` with a private-address permission error.

The Ollama process list was empty during this check because no model was loaded at that instant; this is not a GPU failure by itself.

Stage 4 is not yet fully verified until Telegram/Web chat performs an autonomous WEB tool call, returns a grounded structured answer, and appends the automatic `Источники:` section.


## Stage 4 autonomous WEB loop fix — prepared, awaiting live verification — 2026-10-05

The first autonomous Telegram WEB test reached the tool-round limit instead of synthesizing a final answer. Live trace showed two consecutive `web_research` calls, and the final tool trace also contained an unrelated `server_health` call. Qwen stayed on `100% GPU`.

Root cause in the agent loop:
- explicit WEB requests still exposed both READ and WEB tools;
- after a successful aggregate `web_research`, the model was allowed to call tools again;
- clipped tool-result strings could exceed the configured character limit because the truncation suffix was appended after the full limit.

Fix prepared:
- explicit WEB requests expose only `web_research`;
- after one successful `web_research`, the next turn has no tools and is forced to synthesize the final answer from that evidence;
- explicit WEB requests can no longer wander into `server_health`;
- web evidence is further bounded (up to 4 results, up to 2 fetched pages, smaller excerpts);
- generic tool-result clipping now includes its suffix inside `AGENT_TOOL_RESULT_CHARS`.

Expected live trace after rollout: one `[WEB] tool=web_research ...` call, followed by a normal structured answer and automatic `Источники:` section, with no `server_health` in that request.


## Explicit WEB precedence and deterministic search enforcement — 2026-10-05

A second live Telegram test still showed two `web_research` calls followed by READ fallback and `server_health`, while Qwen remained on `100% GPU`.

The overlapping-intent cause is now fixed at application level:
- explicit WEB intent takes precedence over overlapping READ keywords such as `Docker`, `server` or `NVIDIA`;
- for explicit internet/current-information requests, the application itself executes exactly one fresh `web_research` call before model synthesis;
- that request is then switched to synthesis-only mode with no tools exposed on the next model turn;
- READ enforcement is disabled for that explicit WEB request, so it cannot fall through to `server_health`;
- final answers still receive automatic source URLs gathered from the current WEB result.

Expected trace for the same Telegram test after rollout:
```text
[WEB] selected=web_research reason=explicit_web_request
[WEB] tool=web_research elapsed=... result_chars=...
```
There should be no second `web_research`, no `[READ] rejected_stale_answer`, and no `server_health`.


## Stage 4 research-quality pass — prepared, awaiting live verification — 2026-10-05

The deterministic WEB execution loop is now correct in live use: one explicit WEB request produced exactly one `web_research` call, no READ fallback, and Qwen stayed on `100% GPU`. However, the answer quality was not accepted as final because the raw user instruction was being sent directly as the SearXNG query. That produced weak Russian-language results (including unrelated aggregator pages) and encouraged unsupported conclusions such as inferring that no newer changes existed simply because they were not found.

Quality improvements prepared:
- an internal Qwen query-planning pass now converts the user request into 2-3 focused search queries;
- international technical topics are instructed to include an English query aimed at official docs/release notes/releases;
- `web_research` now merges multiple focused searches, deduplicates URLs and ranks likely primary sources higher;
- documentation hosts, release-note/changelog paths and official repository release pages receive higher source scores;
- up to three diverse pages may be fetched, while evidence remains bounded;
- WEB grounding explicitly forbids converting “not found” into claims such as “there were no changes after year X”;
- dates, versions and years may only be stated when present in current WEB evidence;
- tool-result compaction now preserves valid JSON instead of cutting JSON mid-string;
- Telegram reply chunking now prefers newline/word boundaries so source URLs are less likely to be split between messages.

This quality pass is not yet marked verified. Re-run the same NVIDIA Container Toolkit / Docker CDI research request and check that primary sources dominate the final source list and that unsupported absence claims are gone.


## Stage 4 WEB orchestration VERIFIED; source extraction still being improved — 2026-10-05

The latest live Telegram test verified the control-flow portion of Stage 4:
- explicit internet intent planned 3 focused queries;
- exactly one deterministic `web_research` call executed;
- no READ fallback or `server_health` call occurred;
- the result stayed under the configured tool-result budget;
- Qwen stayed on `100% GPU`;
- the final answer was synthesized and automatic source URLs were appended.

Remaining quality issue observed live:
- primary sources were selected correctly (NVIDIA release notes, NVIDIA CDI docs, NVIDIA GitHub releases), but generic HTML extraction often returned navigation/insufficient page text;
- the answer therefore remained appropriately cautious but could not extract enough current release detail.

Prepared extraction improvements:
- documentation HTML now prefers `article`/`main`/documentation body containers instead of whole-page navigation;
- long documents are focused around terms from the planned research queries;
- GitHub `/releases` pages now use the public GitHub Releases API internally and return recent tag names, publication timestamps and release-note excerpts;
- fetched evidence remains bounded and SSRF/public-network validation remains in force.

Stage 4 should be marked fully VERIFIED only after a live retest shows both correct one-call orchestration and useful current facts extracted from primary sources.
