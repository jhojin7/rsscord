# rsscord

Small RSS/Atom feed notification system.

## What this package contains

```text
rsscord.py                  one-file Python app
config.example.yaml          sample YAML config
debug/assistant_trace.jsonl   safe implementation/tool-call trace, not hidden reasoning
README.md                    this file
```

## Requirements

- Python 3.10+
- `uv`

No env vars. Webhook URL, feed list, state path, logging path, and polling settings all live in YAML config.

## First run

```bash
unzip rsscord.zip
cd rsscord_package
cp config.example.yaml config.yaml
$EDITOR config.yaml
uv run rsscord.py --config config.yaml --validate-config
uv run rsscord.py --config config.yaml --once --dry-run
uv run rsscord.py --config config.yaml
```

`uv` reads inline script metadata from `rsscord.py` and installs:

- `feedparser`
- `httpx`
- `PyYAML`

## First-run behavior

Default:

```yaml
state:
  first_run: "mark_seen"
```

That means first run records current feed items as already seen and sends no Discord flood. After that, only new items notify.

Other options:

```yaml
state:
  first_run: "notify_recent"
  recent_limit_per_feed: 5
```

or:

```yaml
state:
  first_run: "notify_all"
```

## State

Default state file:

```yaml
state:
  sqlite_path: "./rsscord_state.sqlite3"
```

Delete this file to reset dedupe history.

## Logs

Default JSONL log file:

```yaml
logging:
  jsonl_path: "./rsscord.log.jsonl"
```

Each line is standalone JSON. Useful for agent/debug workflows.

## Discord webhook notes

Webhook URL goes in config:

```yaml
discord:
  webhook_url: "https://discord.com/api/webhooks/..."
```

Treat `config.yaml` as secret. Do not commit it to a public repo.

## Per-feed webhook override

```yaml
feeds:
  - name: "Important feed"
    url: "https://example.com/rss.xml"
    enabled: true
    webhook_url: "https://discord.com/api/webhooks/OTHER/WEBHOOK"
```

## Run as simple foreground daemon

```bash
uv run rsscord.py --config config.yaml
```

Stop with `Ctrl+C`.

## Run once from cron/system scheduler

```bash
uv run /path/to/rsscord.py --config /path/to/config.yaml --once
```

## Notification template fields

`notifications.content_template` supports:

```text
feed_name
feed_title
title
link
published
author
summary
tags
```

Example:

```yaml
notifications:
  content_template: |
    New RSS item
    Feed: {feed_name}
    Title: {title}
    URL: {link}
```

## Failure model

- Feed fetch error: logged, next feed continues.
- Discord 429: retries using `retry_after` when available.
- Discord send failure: item stays unseen, so next poll retries.
- Successful send: item gets marked seen in SQLite.
- Dry run: sends nothing and does not mutate SQLite state.
