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


## Primary-source extraction verified live — 2026-10-05

The source-extraction pass was verified directly inside the live agent container.

Verified:
- NVIDIA Container Toolkit release notes are now parsed from the document body instead of mostly navigation;
- the current official release-notes page exposed NVIDIA Container Toolkit 1.20.1 and 1.20.0, including package/container version details and a 1.20.0 change note;
- GitHub `NVIDIA/nvidia-container-toolkit/releases` is now handled through the public Releases API and returned recent unified-release notes including 1.20.1, 1.20.0 and 1.19.1 data;
- the direct fetch tests returned `ok: True`;
- Qwen remained on `100% GPU` after the rebuild.

No autonomous WEB trace was expected from this direct `execute_web_tool("web_fetch", ...)` smoke test because it bypasses the chat/tool orchestration layer.

Final Stage 4 verification still requires repeating the same Telegram research request and confirming the synthesized answer now uses these extracted current primary-source facts while retaining the one-call WEB trace.


## Stage 4 end-to-end WEB test passed; factual attribution hardening added — 2026-10-05

The latest Telegram test passed the complete WEB orchestration path:
- explicit WEB intent planned 3 focused queries;
- exactly one deterministic `web_research` call ran;
- no READ fallback occurred;
- the final Telegram answer used current primary sources and named NVIDIA Container Toolkit 1.20.1;
- Qwen remained on `100% GPU`;
- automatic source URLs were appended.

The answer was substantially better, but this checkpoint is not yet considered fully trusted for factual synthesis. Review identified several attribution risks:
- NVIDIA's CDI documentation says CDI generation support exists as of toolkit `v1.12.0`; the model rendered this imprecisely as “12.0”;
- Docker's Buildx v0.22 CDI documentation is specifically about build-time CDI/BuildKit support and must not be presented as equivalent to runtime CDI behavior;
- a claim mentioning `CDIPluginConfigMap` was not supported by the primary sources reviewed for this test and appears to be source mixing.

Hardening added:
- every WEB search result/document now has a stable source ID (`S1`, `S2`, ...);
- fetched documents are preferred over snippet-only results in source ordering;
- the synthesis prompt requires every verifiable WEB fact to carry a supporting `[S#]` marker;
- claims that cannot be tied to a specific source must be omitted;
- the application rejects a WEB synthesis with no valid source IDs or with unknown source IDs and gives Qwen one rewrite attempt;
- the final automatic source list now includes the same `[S#]` IDs, making claim-to-source checking straightforward.

Next live test: repeat the same NVIDIA Container Toolkit / Docker CDI request and confirm that factual bullets include matching `[S#]` markers and that unsupported mixed-source claims disappear.


## WEB factual-accuracy hardening after live cited test — 2026-10-05

The first live source-ID test confirmed that WEB orchestration and citation plumbing work:
- query planning completed;
- one `web_research` call ran;
- no READ fallback occurred;
- final answer contained `[S#]` citations and automatic matching source entries;
- Qwen remained on `100% GPU`.

However, source IDs alone were not sufficient to guarantee factual entailment. The live answer still contained examples of source mixing or imprecise technical transcription:
- `bugfix release` was rendered as `beta release`;
- NVIDIA Toolkit `v1.12.0` was rendered as `12.0`;
- an NVIDIA AI Enterprise release-note result entered a Container Toolkit/CDI answer despite weak topical relevance.

Hardening prepared:
- search results are now scored for topical overlap with the planned queries in addition to source authority;
- weakly related results that match only a vendor name are filtered when enough strongly relevant results exist;
- `/latest/` documentation is preferred over version-pinned pages for current-information requests;
- up to four evidence pages can be fetched, with at most two from the same host, allowing both current NVIDIA release notes and current NVIDIA CDI docs to coexist with Docker/GitHub evidence;
- final source IDs are now drawn from successfully fetched documents with `text`; search-only snippets are not treated as factual evidence when fetched documents exist;
- tool-result compaction preserves up to four fetched evidence documents while remaining valid JSON;
- the synthesis prompt explicitly preserves exact technical labels/versions and forbids cross-product source mixing;
- a second evidence-only verifier pass now checks the draft against `documents[].text`, removes unsupported claims, preserves exact versions/status labels, and keeps only valid `[S#]` citations.

This accuracy pass is committed but not yet live-verified. Repeat the same NVIDIA Container Toolkit / CDI request after rebuilding the agent. Expected: no unrelated AI Enterprise source, exact `v1.12.0` when supported, no `beta` substitution for `bugfix`, and a `[WEB] verification_pass result=accepted ...` log line.


## Stage 4 WEB cited verification pass — live result — 2026-10-05

The latest Telegram test verified the full WEB execution and verification pipeline live:
- 2 focused search queries were planned;
- exactly one deterministic `web_research` call executed;
- no READ fallback occurred;
- the evidence payload stayed within the configured tool-result budget;
- the evidence-only verifier ran and logged `verification_pass result=accepted`;
- the final answer used stable `[S#]` citations tied to the automatic source list;
- unrelated NVIDIA AI Enterprise results were no longer present;
- exact technical labels improved: `v1.12.0` was preserved and `v1.20.1` was described as a bugfix release;
- Qwen remained on `100% GPU`.

One residual wording issue remains before declaring factual synthesis fully trusted: the answer still said that v1.20.1 “does not contain new CDI changes compared with v1.12.0”. The checked evidence establishes that no such CDI changes were found in the fetched excerpts, but it does not prove their absolute absence. This should be phrased as “the checked sources did not confirm additional CDI changes”.

Operationally, Stage 4 WEB search/orchestration/citation plumbing is verified. One final negative-claim wording hardening is pending for factual conservatism.


## WEB citation/verifier fail-closed fix — prepared, awaiting live verification — 2026-10-05

The latest live test exposed one remaining trust bug in the WEB synthesis pipeline.

Observed live:
- query planning and the single deterministic `web_research` call succeeded;
- the first synthesis cited `S3`, but `S3` was not in the set of fetched evidence sources;
- the citation retry still produced a draft containing the bad source ID;
- the evidence-only verifier correctly logged `result=rejected`;
- despite that rejection, the application returned the unchecked draft because the verifier fallback returned the original draft.

Fix prepared:
- explicit WEB synthesis now receives evidence-only JSON containing only successfully fetched `documents[].text`, their source IDs, URLs and titles;
- search-only result IDs are no longer exposed as factual evidence to the synthesizer;
- the WEB evidence explicitly includes `allowed_source_ids`;
- after one citation rewrite, a second missing/unknown source-ID failure is blocked instead of being accepted;
- verifier rejection/error now returns no answer, and the application blocks the unchecked draft rather than sending it;
- the user receives an explicit message that the unverified draft was blocked if grounding cannot be repaired.

Expected healthy live path:
```text
[WEB] selected=web_research ...
[WEB] tool=web_research ...
[WEB] verification_pass result=accepted cited=[...]
```

Expected failure-safe path:
```text
[WEB] citation_grounding_block ...
```
or
```text
[WEB] verification_pass result=rejected ...
[WEB] verification_block final=1
```

In both failure cases, unsupported prose must no longer be returned to Telegram/Web.


## Stage 4 WEB research VERIFIED — 2026-10-05

Final live verification passed after the fail-closed grounding changes.

Observed live:
- the planner produced 3 focused search queries;
- exactly one deterministic `web_research` call executed;
- the evidence payload stayed within the configured tool-result budget (`2360` chars in this run);
- no READ fallback occurred;
- the evidence-only verifier returned `verification_pass result=accepted`;
- accepted citations were limited to fetched evidence sources (`S1`, `S2`, `S3`);
- the final Telegram answer used matching `[S#]` citations and an automatic source list;
- exact version transcription was preserved for `v1.12.0`;
- unsupported broad absence claims were softened to “в проверенных источниках не удалось подтвердить…”;
- Qwen remained on `100% GPU` with context `8192`;
- the fail-closed path introduced earlier remains in place, so a future citation/verifier failure blocks the unchecked draft instead of returning it.

Stage 4 is therefore considered VERIFIED for:
- public internet search through private SearXNG;
- focused multi-query research planning;
- primary-source extraction;
- source ranking and relevance filtering;
- bounded evidence passed to the local model;
- per-claim source IDs;
- evidence-only verification;
- fail-closed behavior on invalid grounding;
- shared use through the existing Telegram/Web agent;
- GPU-backed local inference.

Known non-blocking quality limitations:
- a 4B local model can still produce awkward wording or over-literal summaries from truncated excerpts;
- deep research may require larger evidence budgets, targeted source adapters, or a larger local model;
- this stage does not add arbitrary browser execution, shell access, or write/admin capabilities.

Recommended next stage: controlled WORK capabilities for repository/file edits and tests, with allowlisted paths, Git branch/diff workflow, and explicit approval gates for destructive or administrative actions.


## Stage 4 WEB research FULLY VERIFIED — 2026-10-06

Final live fail-closed verification passed.

Observed on the live server:
- explicit WEB request planned 3 focused queries;
- exactly one deterministic `web_research` call executed;
- tool evidence size was 2360 characters, below the configured budget;
- no READ fallback occurred;
- the evidence-only verifier returned `verification_pass result=accepted`;
- accepted citations were limited to fetched evidence sources `S1`, `S2`, `S3`;
- the final Telegram answer used matching source IDs and an automatic source list;
- exact technical version text such as `v1.12.0` was preserved;
- unsupported broad absence claims were phrased conservatively;
- Qwen stayed on `100% GPU` with context 8192.

The WEB subsystem is now considered production-ready for bounded read-only research:
- SearXNG search;
- multi-query planning;
- relevance/source ranking;
- safe public-page fetching with SSRF protection;
- primary-source extraction;
- evidence-only synthesis;
- per-claim source IDs;
- verifier pass;
- fail-closed behavior on invalid citations or rejected verification.

Known limitations are quality/capacity rather than trust-boundary failures: a 4B model can still summarize awkwardly, and very deep research may need larger evidence budgets or a larger local model.


## Stage 5 WORK — controlled isolated development — PREPARED, NOT LIVE-VERIFIED — 2026-10-06

Goal: let the local Qwen inspect and edit approved source code safely without giving the model a host shell, root privileges, the Docker socket, or direct write access to the deployment checkout.

Initial trust boundary:
- WORK is disabled by default with `AGENT_WORK_TOOLS=false`;
- only explicit code/project edit intent can expose mutation-capable WORK tools;
- normal chat, READ and WEB requests never receive WORK schemas opportunistically;
- the first approved workspace is `wdttsl` only;
- the deployment checkout remains `~/WDTTSL`;
- WORK operates in a separate linked Git worktree at `/var/lib/server-ai/workspaces/wdttsl`;
- the host broker runs as the non-root owner of the repository;
- the agent container receives only a Unix socket, not a writable host filesystem mount.

Host broker:
- source: `server-ai/work-broker/work_broker.py`;
- installer: `server-ai/install-work-broker.sh`;
- socket: `/run/server-ai/work/work.sock`;
- config: `/etc/server-ai/workspaces.json`;
- systemd service: `server-ai-work.service`.

Exposed WORK operations:
- `work_status` — branch/HEAD/dirty state and allowed checks;
- `work_list_files` — bounded workspace listing;
- `work_search_text` — bounded text search;
- `work_read_file` — focused line-range read with sha256;
- `work_create_branch` — new branches must use the `ai/` prefix and require a clean worktree;
- `work_write_file` — create/replace text files; existing files require the previously observed sha256;
- `work_replace_text` — exact one-occurrence replacement with sha256 compare-and-swap protection;
- `work_diff` — bounded diff plus `git diff --check`;
- `work_check` — allowlisted checks only.

Initial allowlisted checks:
- `diff-check`;
- `server-ai-python` — syntax-compiles the Server AI Python sources without running arbitrary project commands.

Explicitly unavailable in this stage:
- arbitrary shell commands;
- arbitrary subprocess commands supplied by Qwen;
- commit or push;
- delete/rename/reset/clean;
- Docker control;
- systemd control;
- package management;
- root/admin operations;
- access to `.git` internals, `.env`, private keys or credential-like paths.

Additional protections:
- writes are refused unless the isolated worktree is on an `ai/...` branch;
- existing-file writes use sha256 compare-and-swap to prevent stale overwrites;
- symlink paths are refused;
- file/request/output sizes are bounded;
- Git hooks are disabled for broker Git commands;
- broker network access is restricted to `AF_UNIX` by systemd;
- the systemd service gets explicit write access only to the isolated worktree, the source repository Git metadata required by linked worktrees, and its runtime socket directory;
- installer updates avoid recursive deletion and skip `systemctl daemon-reload` when the unit file is unchanged.

Agent behavior:
- explicit WORK tasks receive WORK tool precedence over READ/WEB;
- the application performs a fresh `work_status(wdttsl)` before Qwen starts a WORK task;
- up to 10 bounded tool rounds are available for multi-step edits;
- Qwen is instructed to create an `ai/...` branch, locate/read the target, edit with sha256 protection, inspect the diff and run allowed checks;
- if the model only describes a requested edit without attempting a controlled change, the answer is rejected once and retried;
- Web and Telegram status expose WORK ON/OFF.

Live verification is required before this stage is marked usable. Start with broker/status/security smoke tests before asking Qwen to edit any project file.


## Stage 5 WORK broker status smoke VERIFIED — 2026-10-06

The first live WORK broker status check passed.

Observed live:
- workspace id: `wdttsl`;
- isolated worktree: `/var/lib/server-ai/workspaces/wdttsl`;
- source deployment repository: `/home/igor/WDTTSL`;
- isolated worktree branch state: `DETACHED`;
- isolated worktree HEAD: `2b151578fc65`;
- worktree is clean (`dirty: false`);
- no pending changes are present;
- allowlisted checks are `diff-check` and `server-ai-python`;
- broker policy reports `commit=false`, `push=false`, `delete=false`, and `arbitrary_shell=false`.

This confirms that the host WORK broker is reachable and is operating on the separate isolated worktree rather than directly on the deployment checkout.

Stage 5 is not yet marked usable. Next live checks must verify:
1. write attempts are blocked while the worktree is DETACHED;
2. the deployment checkout remains unchanged;
3. the agent container can reach the WORK socket after `AGENT_WORK_TOOLS=true`;
4. an actual controlled edit is performed only after creation of an `ai/...` branch, followed by diff/check validation.


## Stage 5 deployment isolation check — partial live verification — 2026-10-06

The live checkout/worktree isolation check confirmed:
- deployment checkout remains on branch `server-ai-agent`;
- the isolated AI worktree remains detached before any WORK branch is created;
- the deployment checkout contained only untracked Python `__pycache__` artifacts produced by local syntax-compilation smoke tests, not WORK-broker edits.

Hardening added immediately:
- repository-level `.gitignore` now ignores Python bytecode/cache artifacts so syntax checks do not pollute `git status`;
- `work_status` now reports configured `base_ref`, current `base_head` and whether the detached worktree is behind that base;
- `work_create_branch` now creates every `ai/...` branch from the current configured `base_ref` (normally `server-ai-agent`) instead of from a potentially stale detached worktree HEAD.

This avoids an important stale-base failure mode: the isolated worktree may remain detached at an older commit between deployments, but the first WORK branch will still start from the current local deployment branch after the source checkout is updated.

The write-block smoke test while DETACHED is still required before enabling WORK inside the agent.


## Stage 5 WORK isolation and pre-branch write guard VERIFIED — 2026-10-06

Live host verification passed for the initial WORK safety boundary.

Observed:
- deployment checkout `/home/igor/WDTTSL` remained on `server-ai-agent`;
- deployment `git status --short` was clean after adding Python cache ignores;
- isolated worktree remained at `/var/lib/server-ai/workspaces/wdttsl`;
- isolated worktree was still `DETACHED` and clean;
- configured base is `server-ai-agent`;
- broker reported `base_head=2660cb5bffe7` while detached worktree HEAD remained `2b151578fc65`, so `behind_base=true` was correctly detected;
- a direct `work_write_file` attempt while DETACHED was rejected with `PermissionError: Writes require an isolated ai/... branch`;
- the forbidden test file was confirmed absent afterwards;
- broker reinstall did not change the systemd unit, so `daemon-reload` was correctly skipped;
- `server-ai-work.service` restarted successfully and the WORK Unix socket remained available.

This verifies that stale detached state is detected, writes are blocked before creation of an isolated `ai/...` branch, and the deployment checkout remains untouched.

Next live gate: enable `AGENT_WORK_TOOLS=true`, rebuild only the agent, verify `work_tools:true` in health, verify WORK socket access from inside the agent container, and then run the first autonomous controlled edit in the isolated worktree.


## Stage 5 first autonomous WORK run — orchestration reached edit path, round-limit issue found — 2026-10-06

The first Telegram autonomous WORK smoke request reached the controlled development path but did not finish verification before the model tool-round limit.

Observed tool trace from the user-visible answer:
- `work_status(wdttsl)`;
- `work_create_branch(wdttsl, ai/work-smoke-test)`;
- workspace search/read operations;
- attempts to edit `server-ai/README.md`;
- later unrelated discovery calls before diff/check completion;
- final response: tool-call limit reached.

This confirms that the agent can autonomously enter WORK mode, create an `ai/...` branch and invoke the isolated broker, but the 4B model can wander and spend too many planning rounds.

Hardening prepared after this live result:
- `work_write_file` now creates NEW files only and refuses replacement of existing files, eliminating the risk of truncating a large file after reading only a focused range;
- existing files must be edited with compare-and-swap protected `work_replace_text` or the new `work_insert_text`;
- `work_insert_text` inserts before/after one exact anchor and requires the sha256 returned by `work_read_file`;
- the WORK prompt tells the model to prefer `work_insert_text` for small additions and stop exploring unrelated files after a successful edit;
- WORK planning remains bounded but is raised from 10 to 14 rounds;
- a successful file mutation is now tracked separately from branch creation or failed write attempts;
- before accepting a successful WORK answer, the application deterministically runs `work_diff`, `diff-check` and `server-ai-python`;
- if the model exhausts its planning rounds after a successful edit, the application can recover by running those mandatory postchecks itself and returning the resulting diff/status instead of discarding the completed edit.

This hardening is committed but not yet live-verified. Before retrying the autonomous task, inspect the current isolated `ai/work-smoke-test` worktree because the first run may already have left a partial README modification.


## Stage 5 first WORK run left an inconsistent isolated worktree — diagnostic checkpoint — 2026-10-06

A read-only inspection after the first autonomous WORK attempt found an inconsistent isolated worktree state:
- `git branch --show-current` in `/var/lib/server-ai/workspaces/wdttsl` returned empty, so the worktree is currently detached rather than on the requested `ai/work-smoke-test` branch;
- `git status --short` reported staged/index-side changes:
  - `A  .gitignore`
  - `M  server-ai/README.md`
  - `M  server-ai/work-broker/work_broker.py`
- plain `git diff` and `git diff --check` showed no unstaged diff;
- the requested smoke-test line was not present in `server-ai/README.md`;
- the deployment checkout remained on `server-ai-agent` and clean.

Because the changes appear in the index rather than the working-tree diff, this is not yet treated as a successful WORK edit. No reset/clean/checkout should be performed until the index/HEAD/worktree relationship and the result of the attempted `work_create_branch` are inspected.

Next diagnostics are read-only: inspect porcelain v2 branch state, `git diff --cached`, local `ai/work-smoke-test` ref existence/target, linked-worktree metadata, and WORK/WORK-BROKER logs for the failed branch/edit calls.


## Stage 5 branch-creation failure trace captured — 2026-10-06

Live logs clarified the first autonomous WORK failure sequence.

Agent trace showed:
- fresh deterministic `work_status`;
- `work_create_branch(ai/work-smoke-test)` attempted and returned an error-sized result;
- subsequent `work_status`, search and README reads succeeded;
- repeated `work_create_branch` attempts failed;
- `work_replace_text` and `work_write_file` were then rejected because the worktree never became attached to an `ai/...` branch;
- the model continued with unrelated listing/reads and eventually exhausted its tool-round budget.

Host broker logs confirm the same:
- first branch creation at 06:18:39 failed with `RuntimeError`;
- later branch creation attempts also failed with `RuntimeError`;
- edit attempts failed with `PermissionError`;
- read-only operations continued to work normally.

This confirms the primary blocker is branch creation, not the file-edit guard. The staged/index state seen afterwards may be a partial side effect of the failed Git switch, but the exact Git error text is still required before any cleanup or recovery action.

Do not reset, clean, switch or rewrite the isolated worktree yet. Next step remains read-only Git diagnostics: porcelain-v2 branch state, cached diff, refs for `server-ai-agent` and `ai/work-smoke-test`, and linked-worktree metadata.


## Stage 5 failed switch left index/worktree at base content while HEAD stayed detached — 2026-10-06

The read-only Git inspection resolved the shape of the failed branch switch.

Observed:
- isolated worktree HEAD is still detached at `2b151578fc6595960b59d2ed2654fcf1ca8e4bc3`;
- local `server-ai-agent` points to `9969946eefee84e3dc18fe5afa65ab69485c2e03`;
- `ai/work-smoke-test` does not exist as a valid local ref;
- the index contains exactly the files changed between the old detached HEAD and the newer base:
  - `.gitignore` added;
  - `server-ai/README.md` updated;
  - `server-ai/work-broker/work_broker.py` updated;
- plain working-tree diff is empty, while `git diff --cached` shows those base-branch changes.

This strongly indicates that the failed `git switch -c ai/work-smoke-test server-ai-agent` updated the isolated worktree/index toward the requested base commit, then failed before completing branch-ref/HEAD attachment. The requested autonomous smoke-test line was never inserted.

The deployment checkout remained clean and on `server-ai-agent`.

Before any recovery mutation, inspect possible ref namespace conflicts and linked-worktree metadata. The broker has also been hardened to log a bounded sanitized exception message, not only the exception type, so any subsequent branch-creation failure exposes the actual Git error.


## Stage 5 root cause confirmed — branch namespace permissions — 2026-10-06

Live diagnostics found the cause of the failed WORK branch creation.

Observed:
- there is no existing branch named `ai`;
- the local branch namespace directory for `ai/...` exists with mode `0660`;
- because the directory has no execute/search bit, Git cannot create a nested `ai/work-smoke-test` branch ref;
- the failed switch left the linked worktree detached while its index had already moved toward the configured base content.

Hardening:
- the WORK installer now ensures the `ai` branch namespace directory is owned by the repository user/group with mode `0770`;
- the broker now validates that the branch namespace is writable and traversable before invoking branch creation;
- broker errors include a bounded exception message for future diagnosis.

The deployment checkout remained clean. The isolated worktree still requires one scoped recovery to realign its detached HEAD/index before another autonomous WORK test.


## Stage 5 isolated worktree recovery VERIFIED — 2026-10-06

The one-time recovery of the linked WORK worktree completed successfully.

Observed live:
- installer repaired the `ai/...` ref namespace to mode `0770` owned by `igor:igor`;
- the current staged/index anomaly was backed up to a patch before recovery;
- `git reset --hard server-ai-agent` was executed only inside `/var/lib/server-ai/workspaces/wdttsl`;
- isolated worktree HEAD and configured base now both equal `16a868c981acaf7988cf79e00e5628158e78864d`;
- isolated worktree remains intentionally `DETACHED`, clean, and reports `behind_base=false`;
- deployment checkout remains on `server-ai-agent` and clean;
- `work_status` confirms no pending changes and the expected restricted WORK policy.

This verifies that the partial failed-switch state has been fully recovered without touching the deployment checkout.

Next live gate: rebuild the agent with the hardened WORK orchestration, then rerun the autonomous `ai/work-smoke-test` edit and confirm branch creation, one controlled edit, automatic diff/check validation, clean deployment checkout, and GPU-backed inference.
