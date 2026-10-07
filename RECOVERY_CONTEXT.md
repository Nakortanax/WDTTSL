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


## Warm reboot diagnostics: board/firmware identified — 2026-10-07

Further live diagnostics identified the platform:
- motherboard: MSI B460M-A PRO (MS-7C88), revision 1.0;
- firmware vendor: American Megatrends;
- installed BIOS version: 1.60, dated 2020-11-30;
- boot mode: UEFI;
- kernel command line has no explicit `reboot=` override;
- EFI boot order contains only Ubuntu via `\\EFI\\UBUNTU\\SHIMX64.EFI`;
- GPU exposes four PCI functions: VGA, HDA audio, USB 3.1 host and USB Type-C UCSI controller;
- boot log repeatedly shows `nvidia-gpu 0000:01:00.3: i2c timeout` and `ucsi_ccg ... -110` on the NVIDIA UCSI function.

The evidence still points to the kernel/firmware warm-reset path rather than userspace shutdown. Before making persistent changes, compare behavior with another installed kernel if available. If the issue reproduces across kernels, test one alternative x86 reboot mechanism at a time (prefer a temporary kernel parameter such as `reboot=pci` first). BIOS update is also a strong candidate because the installed firmware is from 2020 and MSI has much newer firmware for this exact board, but firmware flashing should be treated as a separate deliberate maintenance step.


## Warm reboot diagnostics: available kernels / GRUB — 2026-10-07

Live inspection of installed kernels and GRUB found:
- dpkg database lists Linux images 7.0.0-31, 7.0.0-34 and 7.0.0-38;
- actual bootable kernel/initrd files currently present in /boot are 7.0.0-34 and 7.0.0-38;
- GRUB contains explicit menu entries for both 7.0.0-34 and 7.0.0-38;
- current default is the normal first Ubuntu entry;
- GRUB menu is hidden with timeout 0;
- no custom kernel command-line parameters are configured.

Because no pre-7.0 kernel is currently bootable, the safest next comparison is a one-time boot into 7.0.0-34, verify that kernel is actually running, then test a normal software reboot from 7.0.0-34. This can distinguish a 7.0.0-38 regression from a broader firmware/reset problem without changing the persistent default kernel.


## Warm reboot diagnostics: one-shot boot to 7.0.0-34 verified — 2026-10-07

The GRUB one-shot kernel test worked:
- after using `grub-reboot`, the server came up running `7.0.0-34-generic`;
- `grub-editenv list` showed `next_entry=`, confirming the one-shot entry was consumed and the persistent default was not changed.

Next test: issue a normal `sudo reboot` while running 7.0.0-34 and observe whether the machine returns without a hard reset. If it still hangs, that strongly argues against a regression specific to 7.0.0-38 and shifts focus to the firmware / platform reset path.


## Warm reboot diagnostics: kernel 7.0.0-34 reboot SUCCESS — 2026-10-07

Critical result:
- server was confirmed running `7.0.0-34-generic`;
- a normal `sudo reboot` issued from that kernel completed successfully without requiring a hard reset.

This is strong evidence that the recurring warm-reboot failure is specific to, or triggered by, the newer `7.0.0-38-generic` kernel / its interaction with the platform, rather than a generic BIOS/UEFI inability to warm reboot.

Previous evidence remains relevant:
- normal shutdown under 7.0.0-38 reached `reboot.target` and stopped userspace cleanly, but the machine failed to return without a hard reset;
- motherboard is MSI B460M-A PRO (MS-7C88), BIOS 1.60 (2020-11-30);
- NVIDIA GTX 1660 SUPER exposes UCSI/USB functions and logs `nvidia-gpu 0000:01:00.3: i2c timeout` / `ucsi_ccg ... -110`.

Recommended operational mitigation: keep 7.0.0-34 as the known-good boot kernel until the 7.0.0-38 regression is understood or superseded by a fixed kernel. Do not remove 7.0.0-38 yet; retain it for comparison and rollback testing.


## Warm reboot diagnostics: default kernel returned to 7.0.0-38 — 2026-10-07

After the successful reboot test from `7.0.0-34-generic`, the machine booted normally and `uname -r` reported `7.0.0-38-generic`. This confirms the earlier GRUB test was truly one-shot and the persistent default still points to the normal first Ubuntu entry (currently 7.0.0-38).

Operational plan: temporarily make `7.0.0-34-generic` the persistent GRUB default while retaining 7.0.0-38 installed for comparison. This avoids using the kernel that reproduces the warm-reboot failure without deleting it.


## Warm reboot diagnostics: subsequent reboot succeeded — 2026-10-07

The user reported that a subsequent plain `sudo reboot` completed normally without requiring a hard reset.

Important: do not treat the root cause as proven fixed yet. Earlier evidence showed:
- reboot from `7.0.0-34-generic` succeeded;
- reboot failures had occurred while running `7.0.0-38-generic`;
- after the successful 7.0.0-34 test, the machine had returned to `7.0.0-38-generic` by the normal GRUB default.

At this checkpoint it is not yet confirmed which kernel was active during the latest successful reboot, nor whether GRUB had already been changed to make 7.0.0-34 persistent. Verify `uname -r` and `GRUB_DEFAULT` before attributing the success to a specific change. A second normal reboot on the confirmed kernel is recommended before declaring the reboot issue resolved.
