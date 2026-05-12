# Troubleshooting

## `config_error: discord.webhook_url is required in config.yaml`

Add a Discord webhook URL:

```yaml
discord:
  webhook_url: "https://discord.com/api/webhooks/..."
```

---

## First run sends nothing

This is expected when using the default:

```yaml
state:
  first_run: "mark_seen"
```

Existing feed items are recorded as seen. New future items will notify.

---

## Test with recent items

Use:

```yaml
state:
  first_run: "notify_recent"
  recent_limit_per_feed: 5
```

Then delete SQLite state before testing again.

Local:

```bash
rm -f ./rsscord_state.sqlite3
```

Docker:

```bash
docker compose down
rm -f ./data/rsscord_state.sqlite3
docker compose up -d
```

---

## Discord messages are not arriving

Check:

1. Webhook URL is valid.
2. Feed is enabled.
3. `--dry-run` is not being used.
4. SQLite state has not already marked items as seen.
5. JSONL logs contain no `discord_send_failed` or `discord_rate_limited` events.

---

## Docker container restarts but sends nothing

Check mounted paths:

```yaml
volumes:
  - ./config.yaml:/config/config.yaml:ro
  - ./data:/data
```

Check config paths:

```yaml
state:
  sqlite_path: "/data/rsscord_state.sqlite3"
logging:
  jsonl_path: "/data/rsscord.log.jsonl"
```

---

## Duplicate-looking items appear

Some feeds change item IDs, links, titles, or timestamps. `rsscord` tries to derive a stable ID, but feed behavior can vary.

Possible mitigations:

* Prefer canonical feed URLs.
* Avoid duplicate feed subscriptions.
* Reset state only when necessary.
* Add future feed-specific dedupe rules if one source is noisy.