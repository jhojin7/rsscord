<!-- FILE: README.md -->

# rsscord

Config-driven RSS-to-Discord notifications.

`rsscord` watches RSS/Atom feeds, deduplicates items with local SQLite state, and posts new items to Discord webhooks.

Current implementation:

* One Python file
* YAML config
* SQLite state
* JSONL logs
* `uv` local run
* Docker deployment

> Status: early but usable. Best fit: personal feed monitoring, small Discord channels, self-hosted notification workflows.

---

## Why rsscord

Most RSS-to-Discord setups become heavier than they need to be.

`rsscord` keeps the moving parts small:

* **Config-first**: feed list and runtime behavior live in `config.yaml`.
* **Local state**: SQLite prevents duplicate notifications.
* **Safe first run**: default mode records existing items without flooding Discord.
* **Debuggable**: JSONL logs are easy to inspect with normal shell tools.
* **Self-hostable**: run with `uv` or Docker.

---

## Features

* Poll multiple RSS/Atom feeds.
* Send new items to a Discord webhook.
* Use a global webhook or per-feed webhook override.
* Render messages as Discord embeds or plain content.
* Deduplicate items with SQLite.
* Control first-run behavior with `mark_seen`, `notify_recent`, or `notify_all`.
* Validate config before running.
* Run once, dry-run, or long-running process mode.
* Retry Discord rate limits using `retry_after` where available.
* Keep structured JSONL runtime logs.

---

## Quickstart with uv

```bash
git clone https://github.com/jhojin7/rsscord.git
cd rsscord
cp config.example.yaml config.yaml
$EDITOR config.yaml
uv run rsscord.py --config config.yaml --validate-config
uv run rsscord.py --config config.yaml --once --dry-run
uv run rsscord.py --config config.yaml
```

---

## Quickstart with Docker

```bash
git clone https://github.com/jhojin7/rsscord.git
cd rsscord
cp config.docker.example.yaml config.yaml
$EDITOR config.yaml
mkdir -p data
docker compose up -d --build
```

Follow logs:

```bash
docker compose logs -f rsscord
```

Stop:

```bash
docker compose down
```

---

## Documentation

* [`docs/config.md`](docs/config.md): config reference and examples
* [`docs/docker.md`](docs/docker.md): Docker setup and mounted paths
* [`docs/operations.md`](docs/operations.md): runtime behavior, state, logs, failure model
* [`docs/troubleshooting.md`](docs/troubleshooting.md): common issues
* [`docs/roadmap.md`](docs/roadmap.md): planned work and agent-facing config ops
* [`AGENTS.md`](AGENTS.md): rules for coding agents working on this repo

---

## Non-goals

Current non-goals:

* No web UI.
* No account system.
* No hosted SaaS mode.
* No direct FreshRSS integration yet.
* No OPML import yet.
* No unread/star/read-later state.
* No database server.
* No MCP server in the current implementation.

FreshRSS integration, OPML import, and agent-safe config editing are possible future directions.
