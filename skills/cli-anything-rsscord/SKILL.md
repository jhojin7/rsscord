---
name: "cli-anything-rsscord"
description: >-
  Agent-facing CLI for rsscord, a config-driven RSS/Atom to Discord webhook
  notifier. Use it to validate configuration, list feeds, and safely add,
  enable, disable, or remove feeds for Hermes Discord slash-command workflows.
---

# cli-anything-rsscord

Use the `rsscord` command to operate rsscord from an agent or Discord slash-command bridge.

## Installation

From the repository root:

```bash
python -m pip install -e .
```

After installation, the base command is:

```bash
rsscord --help
```

For local development without installation:

```bash
uv run rsscord.py --help
```

## Agent Rules

- Prefer `--json` for Hermes and other agents.
- Never print or echo Discord webhook URLs.
- Use `--dry-run` before mutating `config.yaml` when asking for confirmation.
- Mutating commands create timestamped backups under `ops/config-backups/`.
- Diff output redacts every `webhook_url` value.
- Do not run a real poll without `--dry-run` unless the user explicitly asked to send Discord messages.

## Commands

| Purpose | Command |
| --- | --- |
| Validate config | `rsscord validate --config config.yaml --json` |
| List feeds | `rsscord config list-feeds --config config.yaml --json` |
| Add feed dry run | `rsscord config add-feed --config config.yaml --json --dry-run --name "Example" --url "https://example.com/rss.xml" --tag example` |
| Add feed | `rsscord config add-feed --config config.yaml --json --name "Example" --url "https://example.com/rss.xml" --tag example` |
| Disable feed | `rsscord config disable-feed --config config.yaml --json --name "Example"` |
| Enable feed | `rsscord config enable-feed --config config.yaml --json --name "Example"` |
| Remove feed | `rsscord config remove-feed --config config.yaml --json --name "Example"` |
| Poll dry run | `rsscord poll once --config config.yaml --dry-run` |
| OpenAI status smoke test | `rsscord config add-feed --config config.yaml --json --dry-run --name "OpenAI Status" --url "https://status.openai.com/feed.rss" --tag status --tag openai` |

## Output Contract

JSON commands return an object with `ok: true` on success.

Mutation commands include:

- `changed`: whether the config changed
- `dry_run`: whether the file was left untouched
- `backup_path`: backup path when a write happened
- `feed`: public feed metadata with no webhook value
- `diff`: redacted unified diff lines

Errors return non-zero and, with `--json`, an object containing `ok: false` and `error`.
