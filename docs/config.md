# Config reference

`rsscord` is configured with one YAML file.

Default local path:

```bash
config.yaml
```

Docker path inside container:

```bash
/config/config.yaml
```

---

## Minimal config

```yaml
discord:
  webhook_url: "https://discord.com/api/webhooks/REPLACE_WITH_ID/REPLACE_WITH_TOKEN"
  username: "rsscord"
  avatar_url: null

poll:
  interval_seconds: 300
  jitter_seconds: 15
  timeout_seconds: 20
  user_agent: "rsscord/0.1"

state:
  sqlite_path: "./rsscord_state.sqlite3"
  first_run: "mark_seen"
  recent_limit_per_feed: 5

logging:
  level: "INFO"
  jsonl_path: "./rsscord.log.jsonl"

notifications:
  use_embeds: true
  max_items_per_poll: 25
  summary_max_chars: 500
  content_template: |
    {feed_name}: {title}
    {link}

discord_rate_limit:
  max_retries: 4
  base_backoff_seconds: 1.0

feeds:
  - name: "Hacker News frontpage"
    url: "https://hnrss.org/frontpage"
    enabled: true
    tags: ["tech"]
```

---

## `discord`

| Field         | Required | Description                                   |
| ------------- | -------: | --------------------------------------------- |
| `webhook_url` |      yes | Default Discord webhook URL. Treat as secret. |
| `username`    |       no | Display name used by webhook messages.        |
| `avatar_url`  |       no | Optional avatar URL for webhook messages.     |

---

## `poll`

| Field              |       Default | Description                            |
| ------------------ | ------------: | -------------------------------------- |
| `interval_seconds` |         `300` | Main polling interval.                 |
| `jitter_seconds`   |          `15` | Random extra delay added to each loop. |
| `timeout_seconds`  |          `20` | HTTP timeout for feed fetches.         |
| `user_agent`       | `rsscord/0.1` | User-Agent sent to feed servers.       |

---

## `state`

| Field                   |                   Default | Description                                        |
| ----------------------- | ------------------------: | -------------------------------------------------- |
| `sqlite_path`           | `./rsscord_state.sqlite3` | SQLite file used for dedupe state.                 |
| `first_run`             |               `mark_seen` | What to do when a feed is seen for the first time. |
| `recent_limit_per_feed` |                       `5` | Used only when `first_run: notify_recent`.         |

### `first_run` modes

| Mode            | Behavior                                                               |
| --------------- | ---------------------------------------------------------------------- |
| `mark_seen`     | Store current items as seen and send nothing. Safest default.          |
| `notify_recent` | Send newest `recent_limit_per_feed` items, then mark the rest as seen. |
| `notify_all`    | Send every current item. Can spam Discord.                             |

---

## `logging`

| Field        |               Default | Description                                                  |
| ------------ | --------------------: | ------------------------------------------------------------ |
| `level`      |                `INFO` | Log threshold. Supports `DEBUG`, `INFO`, `WARNING`, `ERROR`. |
| `jsonl_path` | `./rsscord.log.jsonl` | Runtime JSONL log path.                                      |

---

## `notifications`

| Field                |     Default | Description                                     |
| -------------------- | ----------: | ----------------------------------------------- |
| `use_embeds`         |      `true` | Send Discord embeds in addition to content.     |
| `max_items_per_poll` |        `25` | Per-feed cap for new notifications in one poll. |
| `summary_max_chars`  |       `500` | Max summary length before truncation.           |
| `content_template`   | see example | Template for plain text content above embed.    |

Supported `content_template` fields:

* `feed_name`
* `feed_title`
* `title`
* `link`
* `published`
* `author`
* `summary`
* `tags`

---

## `discord_rate_limit`

| Field                  | Default | Description                   |
| ---------------------- | ------: | ----------------------------- |
| `max_retries`          |     `4` | Max Discord send retries.     |
| `base_backoff_seconds` |   `1.0` | Base delay for retry backoff. |

---

## `feeds`

| Field         | Required | Description                                   |
| ------------- | -------: | --------------------------------------------- |
| `name`        |      yes | Human-readable feed name.                     |
| `url`         |      yes | RSS/Atom feed URL.                            |
| `enabled`     |       no | Disable without deleting. Defaults to `true`. |
| `tags`        |       no | Tags added to the item metadata/embed.        |
| `webhook_url` |       no | Per-feed webhook override.                    |

Per-feed webhook example:

```yaml
feeds:
  - name: "Important feed"
    url: "https://example.com/rss.xml"
    enabled: true
    tags: ["important"]
    webhook_url: "https://discord.com/api/webhooks/OTHER/WEBHOOK"
```

---

## Secrets

Discord webhook URL is a secret.

Do not commit:

* `config.yaml`
* SQLite state files
* runtime logs containing webhook-related errors
* local debug dumps

Use `config.example.yaml` and `config.docker.example.yaml` for public examples.
