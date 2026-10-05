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

## Stage 1 — Ollama + Qwen

The initial compose file starts only Ollama. It binds the API to localhost and uses the NVIDIA container runtime through Docker Compose GPU support.

Recommended first model for the GTX 1660 Super 6 GB:

```text
qwen3.5:4b-q4_K_M
```

Start with an 8K context window and increase only after measuring VRAM/RAM use and latency.

### Server deployment

```bash
sudo mkdir -p /var/lib/server-ai/ollama
sudo chown -R "$USER":"$USER" /var/lib/server-ai

cd ~/WDTTSL/server-ai
cp -n .env.example .env

docker compose up -d ollama
docker compose exec ollama ollama pull qwen3.5:4b-q4_K_M
docker compose exec ollama ollama list
```

Then verify GPU activity with `nvidia-smi` while running a prompt.

Do not continue to Telegram, Web UI or host executor until this stage is verified.
