# AGENTS.md

Instructions for AI coding agents working on this repository.

---

## Project summary

`rsscord` is a small RSS/Atom-to-Discord notifier.

Core properties:

* Python script entrypoint: `rsscord.py`
* Config file: `config.yaml`
* Public examples: `config.example.yaml`, `config.docker.example.yaml`
* Local state: SQLite
* Runtime logs: JSONL
* Supported run paths: `uv` and Docker

Keep the project small, inspectable, and easy to run on a personal server.

---

## Hard rules

Do not commit secrets.

Never expose or print full Discord webhook URLs in:

* README examples
* logs
* tests
* screenshots
* error messages
* generated docs

Never assume `config.yaml` is safe to modify without backup.

Do not add a web UI, database server, hosted service, account system, or MCP server unless the user explicitly asks for that implementation.

Do not replace human-readable YAML config with opaque state.

Do not introduce environment-variable-only config. This project intentionally keeps runtime configuration in YAML.

---

## Supported workflows

Use these commands when validating changes:

```bash
uv run rsscord.py --config config.yaml --validate-config
uv run rsscord.py --config config.yaml --once --dry-run
```

For Docker changes:

```bash
docker compose build
docker compose up -d
docker compose logs -f rsscord
docker compose down
```

If real webhook access is unavailable, use dry-run mode and config validation.

---

## Code style

Prefer simple standard-library code where reasonable.

Keep dependencies minimal.

Current dependency set:

* `feedparser`
* `httpx`
* `PyYAML`

When adding behavior:

* Keep functions small.
* Keep side effects explicit.
* Make config validation fail early.
* Log structured events.
* Avoid swallowing exceptions without a log event.
* Preserve existing CLI flags unless there is a strong reason to change them.

---

## Config mutation rules

Agent-facing config edits are a planned feature, not a free-form editing habit.

Until dedicated config commands exist, any agent editing `config.yaml` must:

1. Create a timestamped backup first.
2. Change the smallest possible YAML section.
3. Preserve webhook URL values exactly.
4. Never print webhook URL values back to chat/logs.
5. Run config validation after edit.
6. Show a short diff with secrets redacted.

Suggested backup path:

```text
ops/config-backups/config.YYYYMMDD-HHMMSS.yaml
```

Suggested redaction form:

```text
https://discord.com/api/webhooks/<redacted>/<redacted>
```

---

## Planned config CLI

Preferred future UX for Hermes Agent and similar local agents:

```bash
uv run rsscord.py config list-feeds --config config.yaml
uv run rsscord.py config add-feed --config config.yaml --name "Example" --url "https://example.com/rss.xml" --tag example --dry-run
uv run rsscord.py config add-feed --config config.yaml --name "Example" --url "https://example.com/rss.xml" --tag example
uv run rsscord.py config disable-feed --config config.yaml --name "Example"
uv run rsscord.py config remove-feed --config config.yaml --name "Example"
```

Required behavior for config-mutating commands:

* Create backup before write.
* Support `--dry-run`.
* Print diff with secrets redacted.
* Validate full config after write.
* Exit non-zero on validation failure.
* Keep operation idempotent where possible.

---

## Documentation rules

Keep `README.md` short.

Put longer content in `docs/*.md`.

Preferred layout:

```text
README.md
docs/config.md
docs/docker.md
docs/operations.md
docs/troubleshooting.md
docs/roadmap.md
AGENTS.md
```

Docs should distinguish current implementation from roadmap items.

Do not describe roadmap items as available features.

---

## Testing expectations

For any behavior change, prefer adding or updating tests.

Minimum manual checks when tests are unavailable:

```bash
uv run rsscord.py --print-example-config > /tmp/rsscord.example.yaml
uv run rsscord.py --config /tmp/rsscord.example.yaml --validate-config
uv run rsscord.py --config /tmp/rsscord.example.yaml --once --dry-run
```

Do not run commands that send real Discord messages unless the user explicitly asks.

---

## Commit hygiene

Good commit scopes:

* `docs:`
* `config:`
* `cli:`
* `docker:`
* `logging:`
* `state:`
* `tests:`

Examples:

```bash
git commit -m "docs: split README into focused docs"
git commit -m "cli: add config validation command"
git commit -m "config: add agent-safe feed mutation commands"
```

---

## Design preference

Prefer boring local tooling over protocol-heavy architecture.

For this repo, local CLI commands are usually better than an always-on tool server because:

* Hermes Agent can run commands on the same host.
* Config changes are deterministic file edits.
* YAML remains source of truth.
* Backups and diffs are easy.
* Security boundary stays smaller.

Only add MCP or a long-running config service after CLI commands prove insufficient.