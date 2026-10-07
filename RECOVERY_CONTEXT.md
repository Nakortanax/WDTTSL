# Chat / Server Recovery Context — 2026-10-07

This file is a durable handoff for continuing work if ChatGPT conversation memory is unavailable.

## Working rules

- User prefers Russian and executes shell commands himself.
- After every live change that is confirmed working, save a checkpoint to GitHub immediately.
- Do not mark unverified work as stable.
- Do not expose tokens, passwords, Telegram IDs or other secrets.
- Avoid destructive commands unless the exact target has been verified.
- Never use `docker compose down -v` or delete unrelated Docker volumes.
- Avoid unnecessary `systemctl daemon-reload`. A prior NVIDIA/Ollama incident showed that legacy GPU container wiring could lose NVML after daemon reload. CDI later fixed that for the abandoned Server AI experiment, but the production server should still avoid needless reloads.
- Do not touch Android stable branches when working on WDTTSL/server tasks.

## Production WDTTSL state

Repository: `Nakortanax/WDTTSL`

Production branch on the server:
`home-server-vpn`

Verified production commit:
`e9edaf261393fed0d48175ce5b08169ae2d9f176`
(`Document resolved transient VPNSL outage`)

This is the intentional pre-Server-AI state.

The local production checkout `~/WDTTSL` was verified on 2026-10-07 to be on this exact branch and commit.

## Running production services after rollback

Verified running containers after removing Server AI:

- `weightdiarybot-bot-1`
- `weightdiarybot-fuel-1`
- `homer-status`
- `homer-docker-proxy`
- `glances`
- `homer`
- `adguardhome`

Verified absent:
- all `server-ai-*` containers
- `server-ai-work.service`
- `server-ai-read.service`
- failed systemd units (0 failed at verification)

## Server hardware / platform

- Ubuntu 26.04.1 LTS
- hostname: `home`
- LAN address: `192.168.1.73/24`
- main LAN interface: `enp2s0`
- gateway: `192.168.1.1`
- Intel Core i5-10400F, 6C/12T
- 16 GB RAM
- NVIDIA GeForce GTX 1660 Super 6 GB
- NVIDIA driver verified after rollback: `595.91.07`
- CUDA reported by nvidia-smi: `13.2`
- Docker 29.1.3
- Docker Compose 2.40.3+ds1
- root filesystem roughly 98 GB ext4
- media disk: `/dev/sdb2`, NTFS3, mounted at `/srv/media`

## VPNSL

The transient outage investigated around 2026-10-01 was not proven to be caused by local configuration. It was treated as an external/provider/VK/TURN/relay transient issue unless it repeats.

Checkpoint:
`e9edaf261393fed0d48175ce5b08169ae2d9f176`

Do not resume port 46100 troubleshooting unless the failure actually repeats.

## Server AI experiment — retired

An experimental local AI agent was built on branch:
`server-ai-agent`

It included:
- Ollama
- Qwen 3.5 4B
- FastAPI web/Telegram agent
- READ broker
- WEB/SearXNG research path
- isolated WORK Git broker

The experiment was abandoned because `qwen3.5:4b-q4_K_M` was too unreliable for multi-step autonomous code-edit orchestration. The safety boundaries generally blocked unsafe writes, but the model repeatedly made poor tool-sequencing decisions and exhausted tool rounds.

The production server was therefore restored to the pre-AI state.

Archive branch:
`server-ai-agent`

Final archive/checkpoint commit after rollback/model-storage verification:
`fcee7a8c57ed10df04a5a2b63f8e2475b743a563`

Do not deploy this branch to production unless the user explicitly decides to revisit the experiment.

## Server AI rollback — verified completed

Verified cleanup:
- Server AI compose stack stopped and removed.
- isolated AI worktree removed.
- production checkout switched back to `home-server-vpn`.
- `/var/lib/server-ai` absent.
- `/etc/server-ai` absent.
- `/usr/local/lib/server-ai` absent.
- `/run/server-ai` absent.
- `~/WDTTSL/server-ai` absent.
- `server-ai-work.service` absent.
- `server-ai-read.service` absent.
- custom image `server-ai-agent:latest` removed.
- Qwen 3.5 model data was removed because its Ollama storage was under `/var/lib/server-ai/ollama`.

At the last verification there were no Ollama containers.

Remaining Docker artifacts at that point:
- Docker image `ollama/ollama:latest` still existed locally.
- Docker volume `server-ai_searxng-cache` still existed locally.

These two were not yet confirmed deleted. Do not assume they are gone without checking.

The `ollama/ollama` image is only the runtime image, not the removed Qwen model blobs.

## WeightDiaryBot context

Repository:
`Nakortanax/WeightDiaryBot`

Local path:
`~/WeightDiaryBot`

General architecture:
- Docker Compose
- PostgreSQL 17
- Telegram bot
- local-model approach was chosen because OpenAI API payment was not practical for the user

Current product direction:
- personal weight diary
- Russian UI / Russian natural-language input
- bottom keyboard buttons
- weight
- steps
- workouts (type + minutes)
- notes
- manual calories consumed
- manual calories burned
- long-term storage for later analytics

Important product decision:
automatic food recognition / AI nutrition vision was abandoned. Calories are entered manually.

Do not reintroduce food-image recognition unless the user explicitly asks.

Known durable checkpoint in that project:
Issue #6 was used as a recovery/checkpoint reference.

## Windows dual-network routing context

Desktop has two network interfaces:

Ethernet:
- corporate/VPN path
- gateway `192.168.1.1`
- ifIndex `11`

Wi-Fi:
- direct ISP path
- gateway `192.168.0.1`
- ifIndex `14`

Known site-specific routing work:
- `gosuslugi.ru` was routed over Wi-Fi using /32 routes including `213.59.253.7` and `213.59.254.7`
- user also wanted `avito.ru` handled over Wi-Fi
- user requested a small GUI application to enter a website, create the needed routes, show existing custom rules, and restore defaults

If continuing this task, inspect the live Windows route table first instead of assuming old metrics are still current.

## Git discipline

For WDTTSL:
- production branch: `home-server-vpn`
- archived AI work: `server-ai-agent`
- this handoff is stored on documentation-only branch:
  `server-state-checkpoint-2026-10-07`

The documentation branch exists specifically so the production branch can remain exactly at the pre-AI commit.

When resuming work after lost chat memory:
1. read this file first;
2. inspect the current server state before changing anything;
3. compare live state to the verified production commit;
4. save each newly confirmed milestone to GitHub.


## Reboot failure diagnostics — 2026-10-07

The server has a recurring warm-reboot failure: a normal software reboot performs an orderly shutdown, but the machine does not come back and requires a physical hard reset.

Confirmed from the previous-boot journal:
- systemd reached `shutdown.target`, `final.target`, and `reboot.target`;
- `systemd-reboot.service` finished successfully;
- `systemd-shutdown` synced filesystems/block devices and sent SIGTERM to remaining processes;
- journald then stopped normally;
- Docker/containerd and mounted filesystems had already shut down/unmounted cleanly;
- no failed systemd units were present after the subsequent hard-reset boot.

Current platform details from the same diagnostic capture:
- firmware mode: UEFI;
- kernel: `7.0.0-38-generic`;
- NVIDIA driver: `595.91.07`, CUDA 13.2;
- GPU: GTX 1660 SUPER;
- root disk: SanDisk SATA SSD with EFI + /boot + LVM root;
- media disk: WDC 500 GB NTFS at `/srv/media`.

Interpretation: the evidence points away from Docker or a userspace shutdown service. The hang most likely occurs after userspace shutdown, during the kernel/firmware warm-reset transition or early firmware/POST path. Do not change BIOS/kernel parameters blindly. Next diagnostics should collect motherboard/BIOS identity, current kernel command line, EFI/ACPI/reboot-related kernel messages, then test alternative reboot mechanisms one at a time if needed.
