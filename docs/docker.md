# Docker setup

Docker is recommended for always-on self-hosted use.

---

## Start

```bash
git clone https://github.com/jhojin7/rsscord.git
cd rsscord
cp config.docker.example.yaml config.yaml
$EDITOR config.yaml
mkdir -p data
docker compose up -d --build
```

---

## Logs

```bash
docker compose logs -f rsscord
```

---

## Stop

```bash
docker compose down
```

---

## Volumes

Compose should mount config read-only and state/logs as persistent data:

```yaml
volumes:
  - ./config.yaml:/config/config.yaml:ro
  - ./data:/data
```

Docker config should store SQLite state and JSONL logs under `/data`:

```yaml
state:
  sqlite_path: "/data/rsscord_state.sqlite3"

logging:
  jsonl_path: "/data/rsscord.log.jsonl"
```

---

## Update container

```bash
git pull
docker compose up -d --build
```

---

## Reset state

This makes `rsscord` forget which items were already seen.

```bash
docker compose down
rm -f ./data/rsscord_state.sqlite3
docker compose up -d
```

Use with care. `first_run: notify_all` can send many messages after state reset.