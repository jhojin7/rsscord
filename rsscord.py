#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "feedparser>=6.0.11",
#   "httpx>=0.27.0",
#   "PyYAML>=6.0.1",
# ]
# ///
"""
rsscord.py - small RSS/Atom -> Discord webhook notifier.

Run:
    uv run rsscord.py --config config.yaml
    uv run rsscord.py --config config.yaml --once --dry-run
    uv run rsscord.py --print-example-config > config.yaml

Design:
    - One Python file.
    - YAML config; no env vars.
    - SQLite state file prevents duplicate notifications.
    - JSONL logs for debugging.
"""

from __future__ import annotations

import argparse
import copy
import dataclasses
import datetime as dt
import difflib
import hashlib
import html
import json
import os
import random
import re
import signal
import sqlite3
import sys
import textwrap
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urlparse

import feedparser
import httpx
import yaml


EXAMPLE_CONFIG = """\
# rsscord config
# Copy to config.yaml, edit webhook_url + feeds, then run:
#   uv run rsscord.py --config config.yaml

discord:
  webhook_url: "https://discord.com/api/webhooks/REPLACE_WITH_ID/REPLACE_WITH_TOKEN"
  username: "rsscord"
  avatar_url: null

poll:
  interval_seconds: 300
  jitter_seconds: 15
  timeout_seconds: 20
  user_agent: "rsscord/0.1 (+local personal rss notifier)"

state:
  sqlite_path: "./rsscord_state.sqlite3"

  # mark_seen: first run stores current feed items without notifying. safest default.
  # notify_recent: first run notifies newest N items per feed.
  # notify_all: first run notifies every current item. can spam.
  first_run: "mark_seen"
  recent_limit_per_feed: 5

logging:
  level: "INFO"
  jsonl_path: "./rsscord.log.jsonl"

notifications:
  use_embeds: true
  max_items_per_poll: 25
  summary_max_chars: 500

  # Used as plain content. With use_embeds=true, this becomes short text above embed.
  # Available fields:
  #   feed_name, feed_title, title, link, published, author, summary, tags
  content_template: "📰 {feed_name}: {title}\\n{link}"

discord_rate_limit:
  max_retries: 4
  base_backoff_seconds: 1.0

feeds:
  - name: "Example feed"
    url: "https://hnrss.org/frontpage"
    enabled: true
    tags: ["tech"]
    # Optional per-feed webhook override:
    # webhook_url: "https://discord.com/api/webhooks/..."

  - name: "Another feed"
    url: "https://xkcd.com/atom.xml"
    enabled: false
    tags: ["comics"]
"""


LOG_LEVELS = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40}


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def iso_now() -> str:
    return utc_now().isoformat(timespec="seconds")


def safe_int(value: Any, default: int, *, min_value: int | None = None) -> int:
    try:
        out = int(value)
    except (TypeError, ValueError):
        return default
    if min_value is not None and out < min_value:
        return default
    return out


def safe_float(value: Any, default: float, *, min_value: float | None = None) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    if min_value is not None and out < min_value:
        return default
    return out


def coerce_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(x) for x in value]
    return [str(value)]


def strip_html(value: str) -> str:
    value = re.sub(r"(?is)<(script|style).*?>.*?</\1>", "", value or "")
    value = re.sub(r"(?s)<br\s*/?>", "\n", value)
    value = re.sub(r"(?s)</p\s*>", "\n\n", value)
    value = re.sub(r"(?s)<.*?>", "", value)
    value = html.unescape(value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    value = re.sub(r"[ \t]+", " ", value)
    return value.strip()


def truncate(value: str, max_chars: int) -> str:
    value = value or ""
    if max_chars <= 0 or len(value) <= max_chars:
        return value
    return value[: max_chars - 1].rstrip() + "…"


def normalize_url(value: str) -> str:
    return (value or "").strip()


def struct_time_to_iso(value: Any) -> str:
    if not value:
        return ""
    try:
        # feedparser returns UTC-ish time.struct_time for *_parsed.
        return dt.datetime(*value[:6], tzinfo=dt.timezone.utc).isoformat(timespec="seconds")
    except Exception:
        return ""


def parse_entry_timestamp(entry: Any) -> str:
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        out = struct_time_to_iso(entry.get(key))
        if out:
            return out
    for key in ("published", "updated", "created"):
        raw = str(entry.get(key, "") or "").strip()
        if raw:
            return raw
    return ""


def first_entry_text(entry: Any, *keys: str) -> str:
    for key in keys:
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return value
    content = entry.get("content")
    if isinstance(content, list) and content:
        first = content[0]
        if isinstance(first, dict):
            value = first.get("value")
            if isinstance(value, str) and value.strip():
                return value
    return ""


def discord_timestamp_or_none(value: str) -> str | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed.astimezone(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    except Exception:
        return None


class JsonlLogger:
    def __init__(self, path: Path, level: str = "INFO") -> None:
        self.path = path
        self.level_name = level.upper()
        self.level = LOG_LEVELS.get(self.level_name, 20)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def event(self, level: str, event: str, **fields: Any) -> None:
        level = level.upper()
        if LOG_LEVELS.get(level, 20) < self.level:
            return
        record = {"ts": iso_now(), "level": level, "event": event}
        record.update(fields)
        line = json.dumps(record, ensure_ascii=False, sort_keys=True)
        print(line, flush=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    def debug(self, event: str, **fields: Any) -> None:
        self.event("DEBUG", event, **fields)

    def info(self, event: str, **fields: Any) -> None:
        self.event("INFO", event, **fields)

    def warning(self, event: str, **fields: Any) -> None:
        self.event("WARNING", event, **fields)

    def error(self, event: str, **fields: Any) -> None:
        self.event("ERROR", event, **fields)


@dataclasses.dataclass
class DiscordConfig:
    webhook_url: str
    username: str | None = None
    avatar_url: str | None = None


@dataclasses.dataclass
class PollConfig:
    interval_seconds: int = 300
    jitter_seconds: int = 15
    timeout_seconds: int = 20
    user_agent: str = "rsscord/0.1"


@dataclasses.dataclass
class StateConfig:
    sqlite_path: Path
    first_run: str = "mark_seen"
    recent_limit_per_feed: int = 5


@dataclasses.dataclass
class LoggingConfig:
    level: str = "INFO"
    jsonl_path: Path = Path("./rsscord.log.jsonl")


@dataclasses.dataclass
class NotificationConfig:
    use_embeds: bool = True
    max_items_per_poll: int = 25
    summary_max_chars: int = 500
    content_template: str = "📰 {feed_name}: {title}\n{link}"


@dataclasses.dataclass
class RateLimitConfig:
    max_retries: int = 4
    base_backoff_seconds: float = 1.0


@dataclasses.dataclass
class FeedConfig:
    name: str
    url: str
    enabled: bool = True
    tags: list[str] = dataclasses.field(default_factory=list)
    webhook_url: str | None = None


@dataclasses.dataclass
class AppConfig:
    discord: DiscordConfig
    poll: PollConfig
    state: StateConfig
    logging: LoggingConfig
    notifications: NotificationConfig
    discord_rate_limit: RateLimitConfig
    feeds: list[FeedConfig]


def require_mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a YAML mapping/object")
    return value


def load_raw_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"config file not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return require_mapping(raw, "config")


def parse_config(raw: dict[str, Any]) -> AppConfig:
    raw = require_mapping(raw, "config")

    discord_raw = require_mapping(raw.get("discord", {}), "discord")
    webhook_url = str(discord_raw.get("webhook_url", "") or "").strip()
    if not webhook_url:
        raise ValueError("discord.webhook_url is required in config.yaml")
    discord = DiscordConfig(
        webhook_url=webhook_url,
        username=(str(discord_raw.get("username")).strip() if discord_raw.get("username") else None),
        avatar_url=(str(discord_raw.get("avatar_url")).strip() if discord_raw.get("avatar_url") else None),
    )

    poll_raw = require_mapping(raw.get("poll", {}), "poll")
    poll = PollConfig(
        interval_seconds=safe_int(poll_raw.get("interval_seconds"), 300, min_value=5),
        jitter_seconds=safe_int(poll_raw.get("jitter_seconds"), 15, min_value=0),
        timeout_seconds=safe_int(poll_raw.get("timeout_seconds"), 20, min_value=1),
        user_agent=str(poll_raw.get("user_agent") or "rsscord/0.1"),
    )

    state_raw = require_mapping(raw.get("state", {}), "state")
    first_run = str(state_raw.get("first_run") or "mark_seen").strip()
    if first_run not in {"mark_seen", "notify_recent", "notify_all"}:
        raise ValueError("state.first_run must be one of: mark_seen, notify_recent, notify_all")
    state = StateConfig(
        sqlite_path=Path(str(state_raw.get("sqlite_path") or "./rsscord_state.sqlite3")),
        first_run=first_run,
        recent_limit_per_feed=safe_int(state_raw.get("recent_limit_per_feed"), 5, min_value=0),
    )

    logging_raw = require_mapping(raw.get("logging", {}), "logging")
    logging_cfg = LoggingConfig(
        level=str(logging_raw.get("level") or "INFO").upper(),
        jsonl_path=Path(str(logging_raw.get("jsonl_path") or "./rsscord.log.jsonl")),
    )

    notifications_raw = require_mapping(raw.get("notifications", {}), "notifications")
    notifications = NotificationConfig(
        use_embeds=bool(notifications_raw.get("use_embeds", True)),
        max_items_per_poll=safe_int(notifications_raw.get("max_items_per_poll"), 25, min_value=1),
        summary_max_chars=safe_int(notifications_raw.get("summary_max_chars"), 500, min_value=0),
        content_template=str(
            notifications_raw.get("content_template") or "📰 {feed_name}: {title}\n{link}"
        ),
    )

    rate_raw = require_mapping(raw.get("discord_rate_limit", {}), "discord_rate_limit")
    rate = RateLimitConfig(
        max_retries=safe_int(rate_raw.get("max_retries"), 4, min_value=0),
        base_backoff_seconds=safe_float(rate_raw.get("base_backoff_seconds"), 1.0, min_value=0.0),
    )

    feeds_raw = raw.get("feeds")
    if not isinstance(feeds_raw, list) or not feeds_raw:
        raise ValueError("feeds must be a non-empty YAML list")

    feeds: list[FeedConfig] = []
    for index, feed_raw in enumerate(feeds_raw):
        feed_raw = require_mapping(feed_raw, f"feeds[{index}]")
        name = str(feed_raw.get("name") or "").strip()
        url = str(feed_raw.get("url") or "").strip()
        if not name:
            raise ValueError(f"feeds[{index}].name is required")
        if not url:
            raise ValueError(f"feeds[{index}].url is required")
        feeds.append(
            FeedConfig(
                name=name,
                url=url,
                enabled=bool(feed_raw.get("enabled", True)),
                tags=coerce_list(feed_raw.get("tags")),
                webhook_url=(str(feed_raw.get("webhook_url")).strip() if feed_raw.get("webhook_url") else None),
            )
        )

    return AppConfig(
        discord=discord,
        poll=poll,
        state=state,
        logging=logging_cfg,
        notifications=notifications,
        discord_rate_limit=rate,
        feeds=feeds,
    )


def load_config(path: Path) -> AppConfig:
    return parse_config(load_raw_config(path))


class StateStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.execute("PRAGMA synchronous=NORMAL;")
        self.migrate()

    def migrate(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS feed_state (
                feed_url TEXT PRIMARY KEY,
                feed_name TEXT NOT NULL,
                first_seen_at TEXT NOT NULL,
                last_checked_at TEXT
            );

            CREATE TABLE IF NOT EXISTS seen_items (
                feed_url TEXT NOT NULL,
                item_id TEXT NOT NULL,
                title TEXT,
                link TEXT,
                published TEXT,
                first_seen_at TEXT NOT NULL,
                notified_at TEXT,
                PRIMARY KEY (feed_url, item_id)
            );

            CREATE INDEX IF NOT EXISTS idx_seen_items_feed_seen
            ON seen_items(feed_url, first_seen_at);
            """
        )
        self.conn.commit()

    def has_feed(self, feed_url: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM feed_state WHERE feed_url = ? LIMIT 1", (feed_url,)
        ).fetchone()
        return row is not None

    def upsert_feed(self, feed_url: str, feed_name: str) -> None:
        now = iso_now()
        self.conn.execute(
            """
            INSERT INTO feed_state(feed_url, feed_name, first_seen_at, last_checked_at)
            VALUES(?, ?, ?, ?)
            ON CONFLICT(feed_url) DO UPDATE SET
                feed_name = excluded.feed_name,
                last_checked_at = excluded.last_checked_at
            """,
            (feed_url, feed_name, now, now),
        )
        self.conn.commit()

    def touch_feed(self, feed_url: str, feed_name: str) -> None:
        now = iso_now()
        self.conn.execute(
            """
            INSERT INTO feed_state(feed_url, feed_name, first_seen_at, last_checked_at)
            VALUES(?, ?, ?, ?)
            ON CONFLICT(feed_url) DO UPDATE SET
                feed_name = excluded.feed_name,
                last_checked_at = excluded.last_checked_at
            """,
            (feed_url, feed_name, now, now),
        )
        self.conn.commit()

    def is_seen(self, feed_url: str, item_id: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM seen_items WHERE feed_url = ? AND item_id = ? LIMIT 1",
            (feed_url, item_id),
        ).fetchone()
        return row is not None

    def mark_seen(self, item: "FeedItem", *, notified: bool) -> None:
        now = iso_now()
        self.conn.execute(
            """
            INSERT OR IGNORE INTO seen_items(
                feed_url, item_id, title, link, published, first_seen_at, notified_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item.feed_url,
                item.item_id,
                item.title,
                item.link,
                item.published,
                now,
                now if notified else None,
            ),
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()


@dataclasses.dataclass
class FeedItem:
    feed_name: str
    feed_title: str
    feed_url: str
    item_id: str
    title: str
    link: str
    published: str
    author: str
    summary: str
    tags: list[str]


def stable_item_id(feed_url: str, entry: Any) -> str:
    candidates = [
        str(entry.get("id", "") or "").strip(),
        str(entry.get("guid", "") or "").strip(),
        normalize_url(str(entry.get("link", "") or "")),
        str(entry.get("title", "") or "").strip() + "|" + parse_entry_timestamp(entry),
    ]
    for candidate in candidates:
        if candidate and candidate != "|":
            return hashlib.sha256(f"{feed_url}|{candidate}".encode("utf-8")).hexdigest()
    raw = json.dumps(dict(entry), ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(f"{feed_url}|{raw}".encode("utf-8")).hexdigest()


def extract_feed_items(feed: FeedConfig, parsed: Any, summary_max_chars: int) -> list[FeedItem]:
    feed_title = str(parsed.feed.get("title") or feed.name).strip() or feed.name
    out: list[FeedItem] = []
    for entry in parsed.entries:
        title = strip_html(str(entry.get("title") or "(untitled)"))
        link = normalize_url(str(entry.get("link") or ""))
        summary_raw = first_entry_text(entry, "summary", "description")
        summary = truncate(strip_html(summary_raw), summary_max_chars)
        author = strip_html(str(entry.get("author") or ""))
        published = parse_entry_timestamp(entry)
        out.append(
            FeedItem(
                feed_name=feed.name,
                feed_title=feed_title,
                feed_url=feed.url,
                item_id=stable_item_id(feed.url, entry),
                title=title,
                link=link,
                published=published,
                author=author,
                summary=summary,
                tags=feed.tags,
            )
        )
    return out


def fetch_feed(client: httpx.Client, feed: FeedConfig, logger: JsonlLogger) -> Any | None:
    try:
        response = client.get(feed.url)
        response.raise_for_status()
    except Exception as exc:
        logger.error(
            "feed_fetch_failed",
            feed_name=feed.name,
            feed_url=feed.url,
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return None

    parsed = feedparser.parse(response.content)
    if parsed.bozo:
        logger.warning(
            "feed_parse_warning",
            feed_name=feed.name,
            feed_url=feed.url,
            warning=str(getattr(parsed, "bozo_exception", "")),
        )
    return parsed


def format_template(template: str, item: FeedItem) -> str:
    fields = {
        "feed_name": item.feed_name,
        "feed_title": item.feed_title,
        "title": item.title,
        "link": item.link,
        "published": item.published,
        "author": item.author,
        "summary": item.summary,
        "tags": ", ".join(item.tags),
    }
    try:
        return template.format(**fields)
    except KeyError as exc:
        missing = str(exc).strip("'")
        raise ValueError(f"notifications.content_template references unknown field: {missing}") from exc


def build_discord_payload(
    item: FeedItem,
    app_config: AppConfig,
    webhook_url: str,
) -> dict[str, Any]:
    del webhook_url  # included for call-site symmetry; webhook URL is never logged.

    content = truncate(format_template(app_config.notifications.content_template, item), 1900)
    payload: dict[str, Any] = {"content": content}

    if app_config.discord.username:
        payload["username"] = app_config.discord.username
    if app_config.discord.avatar_url:
        payload["avatar_url"] = app_config.discord.avatar_url

    if app_config.notifications.use_embeds:
        embed: dict[str, Any] = {
            "title": truncate(item.title, 256),
            "description": truncate(item.summary, 4096),
            "footer": {"text": truncate(item.feed_name, 2048)},
        }
        if item.link:
            embed["url"] = item.link
        ts = discord_timestamp_or_none(item.published)
        if ts:
            embed["timestamp"] = ts
        if item.author:
            embed["author"] = {"name": truncate(item.author, 256)}
        if item.tags:
            embed["fields"] = [{"name": "Tags", "value": truncate(", ".join(item.tags), 1024), "inline": True}]
        payload["embeds"] = [embed]

    return payload


def send_discord_webhook(
    client: httpx.Client,
    webhook_url: str,
    payload: dict[str, Any],
    rate_config: RateLimitConfig,
    logger: JsonlLogger,
    item: FeedItem,
    *,
    dry_run: bool,
) -> bool:
    if dry_run:
        logger.info(
            "discord_send_dry_run",
            feed_name=item.feed_name,
            title=item.title,
            link=item.link,
            item_id=item.item_id,
        )
        return True

    for attempt in range(rate_config.max_retries + 1):
        try:
            response = client.post(webhook_url, json=payload)
        except Exception as exc:
            backoff = rate_config.base_backoff_seconds * (2**attempt)
            logger.warning(
                "discord_send_exception",
                feed_name=item.feed_name,
                item_id=item.item_id,
                attempt=attempt + 1,
                error_type=type(exc).__name__,
                error=str(exc),
                backoff_seconds=backoff,
            )
            if attempt >= rate_config.max_retries:
                return False
            time.sleep(backoff)
            continue

        if response.status_code in {200, 204}:
            logger.info(
                "discord_send_success",
                feed_name=item.feed_name,
                title=item.title,
                item_id=item.item_id,
                status_code=response.status_code,
            )
            return True

        if response.status_code == 429:
            retry_after = None
            try:
                retry_after = response.json().get("retry_after")
            except Exception:
                retry_after = None
            if retry_after is None:
                retry_after = response.headers.get("Retry-After")
            wait_seconds = safe_float(
                retry_after,
                rate_config.base_backoff_seconds * (2**attempt),
                min_value=0.0,
            )
            logger.warning(
                "discord_rate_limited",
                feed_name=item.feed_name,
                item_id=item.item_id,
                attempt=attempt + 1,
                wait_seconds=wait_seconds,
                status_code=response.status_code,
            )
            if attempt >= rate_config.max_retries:
                return False
            time.sleep(wait_seconds)
            continue

        # Discord webhooks often return useful JSON/text; log truncated only.
        logger.error(
            "discord_send_failed",
            feed_name=item.feed_name,
            item_id=item.item_id,
            status_code=response.status_code,
            response_body=truncate(response.text, 500),
        )
        return False

    return False


def sort_oldest_first(items: Sequence[FeedItem]) -> list[FeedItem]:
    # Feed lists are usually newest-first. Notify oldest-first so Discord reads naturally.
    return list(reversed(items))


def poll_once(
    app_config: AppConfig,
    state: StateStore,
    logger: JsonlLogger,
    *,
    dry_run: bool,
) -> int:
    enabled_feeds = [f for f in app_config.feeds if f.enabled]
    logger.info("poll_started", enabled_feed_count=len(enabled_feeds), dry_run=dry_run)

    total_sent = 0
    headers = {"User-Agent": app_config.poll.user_agent}
    timeout = httpx.Timeout(app_config.poll.timeout_seconds)
    with httpx.Client(headers=headers, timeout=timeout, follow_redirects=True) as client:
        for feed in enabled_feeds:
            parsed = fetch_feed(client, feed, logger)
            if parsed is None:
                continue

            items = extract_feed_items(
                feed,
                parsed,
                summary_max_chars=app_config.notifications.summary_max_chars,
            )
            logger.info(
                "feed_checked",
                feed_name=feed.name,
                feed_url=feed.url,
                item_count=len(items),
            )

            feed_known = state.has_feed(feed.url)
            webhook_url = feed.webhook_url or app_config.discord.webhook_url

            if not feed_known:
                if not dry_run:
                    state.upsert_feed(feed.url, feed.name)
                if app_config.state.first_run == "mark_seen":
                    if not dry_run:
                        for item in items:
                            state.mark_seen(item, notified=False)
                    logger.info(
                        "feed_initialized_mark_seen",
                        feed_name=feed.name,
                        stored_count=len(items),
                        dry_run=dry_run,
                    )
                    continue

                if app_config.state.first_run == "notify_recent":
                    notify_items = items[: app_config.state.recent_limit_per_feed]
                else:
                    notify_items = items

                for item in sort_oldest_first(notify_items):
                    payload = build_discord_payload(item, app_config, webhook_url)
                    if send_discord_webhook(
                        client,
                        webhook_url,
                        payload,
                        app_config.discord_rate_limit,
                        logger,
                        item,
                        dry_run=dry_run,
                    ):
                        if not dry_run:
                            state.mark_seen(item, notified=True)
                        total_sent += 1

                # Mark the rest as seen to avoid later flood.
                if not dry_run:
                    notified_ids = {item.item_id for item in notify_items}
                    for item in items:
                        if item.item_id not in notified_ids:
                            state.mark_seen(item, notified=False)
                continue

            new_items = [item for item in items if not state.is_seen(feed.url, item.item_id)]
            if app_config.notifications.max_items_per_poll > 0:
                new_items = new_items[: app_config.notifications.max_items_per_poll]

            logger.info(
                "feed_new_items_found",
                feed_name=feed.name,
                new_item_count=len(new_items),
            )

            for item in sort_oldest_first(new_items):
                payload = build_discord_payload(item, app_config, webhook_url)
                if send_discord_webhook(
                    client,
                    webhook_url,
                    payload,
                    app_config.discord_rate_limit,
                    logger,
                    item,
                    dry_run=dry_run,
                ):
                    if not dry_run:
                        state.mark_seen(item, notified=True)
                    total_sent += 1
                else:
                    logger.warning(
                        "item_left_unseen_due_to_send_failure",
                        feed_name=item.feed_name,
                        item_id=item.item_id,
                        title=item.title,
                    )

            if not dry_run:
                state.touch_feed(feed.url, feed.name)

    logger.info("poll_finished", notifications_sent=total_sent)
    return total_sent


class StopFlag:
    def __init__(self) -> None:
        self.stop = False

    def install(self, logger: JsonlLogger) -> None:
        def handler(signum: int, _frame: Any) -> None:
            self.stop = True
            logger.info("shutdown_signal_received", signal=signum)

        signal.signal(signal.SIGINT, handler)
        signal.signal(signal.SIGTERM, handler)


DISCORD_WEBHOOK_RE = re.compile(
    r"https://(?:canary\.|ptb\.)?discord(?:app)?\.com/api/webhooks/[^\s\"']+",
    re.IGNORECASE,
)
WEBHOOK_LINE_RE = re.compile(r"(?m)^([+\- ]?\s*webhook_url:\s*).*$")


@dataclasses.dataclass
class ConfigMutation:
    operation: str
    changed: bool
    message: str
    feed: dict[str, Any] | None = None


def redact_secrets(value: str) -> str:
    value = DISCORD_WEBHOOK_RE.sub(
        "https://discord.com/api/webhooks/<redacted>/<redacted>",
        value,
    )
    return WEBHOOK_LINE_RE.sub(lambda match: f'{match.group(1)}"<redacted>"', value)


def dump_config_text(raw: dict[str, Any]) -> str:
    return yaml.safe_dump(raw, sort_keys=False, allow_unicode=True, default_flow_style=False)


def config_summary(config_path: Path, app_config: AppConfig) -> dict[str, Any]:
    enabled_count = len([feed for feed in app_config.feeds if feed.enabled])
    return {
        "ok": True,
        "config_path": str(config_path),
        "feed_count": len(app_config.feeds),
        "enabled_feed_count": enabled_count,
        "state_path": str(app_config.state.sqlite_path),
        "log_path": str(app_config.logging.jsonl_path),
    }


def feed_record(feed: FeedConfig) -> dict[str, Any]:
    return {
        "name": feed.name,
        "url": feed.url,
        "enabled": feed.enabled,
        "tags": feed.tags,
        "has_webhook_override": bool(feed.webhook_url),
    }


def raw_feed_record(feed: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": str(feed.get("name") or ""),
        "url": str(feed.get("url") or ""),
        "enabled": bool(feed.get("enabled", True)),
        "tags": coerce_list(feed.get("tags")),
        "has_webhook_override": bool(feed.get("webhook_url")),
    }


def print_json(data: dict[str, Any]) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True))


def emit_error(message: str, *, json_output: bool, code: int = 1) -> int:
    if json_output:
        print_json({"ok": False, "error": redact_secrets(message)})
    else:
        print(f"error: {redact_secrets(message)}", file=sys.stderr)
    return code


def print_feed_table(feeds: list[dict[str, Any]]) -> None:
    if not feeds:
        print("No feeds configured.")
        return

    rows = []
    for index, feed in enumerate(feeds, start=1):
        tags = ", ".join(feed["tags"]) if feed["tags"] else "-"
        rows.append(
            [
                str(index),
                "yes" if feed["enabled"] else "no",
                feed["name"],
                feed["url"],
                tags,
                "yes" if feed["has_webhook_override"] else "no",
            ]
        )
    headers = ["#", "enabled", "name", "url", "tags", "webhook"]
    widths = [
        max(len(headers[column]), *(len(row[column]) for row in rows))
        for column in range(len(headers))
    ]
    print("  ".join(headers[column].ljust(widths[column]) for column in range(len(headers))))
    print("  ".join("-" * widths[column] for column in range(len(headers))))
    for row in rows:
        print("  ".join(row[column].ljust(widths[column]) for column in range(len(headers))))


def validate_feed_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("feed URL must be an absolute http(s) URL")


def validate_discord_webhook_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or "discord" not in parsed.netloc or not parsed.path.startswith("/api/webhooks/"):
        raise ValueError("webhook URL must be a Discord webhook URL")


def ensure_feeds_list(raw: dict[str, Any]) -> list[dict[str, Any]]:
    feeds = raw.get("feeds")
    if feeds is None:
        feeds = []
        raw["feeds"] = feeds
    if not isinstance(feeds, list):
        raise ValueError("feeds must be a YAML list")
    for index, feed in enumerate(feeds):
        require_mapping(feed, f"feeds[{index}]")
    return feeds


def find_feed_index(feeds: list[dict[str, Any]], name: str) -> int | None:
    exact_matches = [index for index, feed in enumerate(feeds) if str(feed.get("name") or "") == name]
    if len(exact_matches) == 1:
        return exact_matches[0]
    if len(exact_matches) > 1:
        raise ValueError(f"multiple feeds named {name!r}; fix config before mutating")

    folded = name.casefold()
    folded_matches = [
        index for index, feed in enumerate(feeds) if str(feed.get("name") or "").casefold() == folded
    ]
    if len(folded_matches) == 1:
        return folded_matches[0]
    if len(folded_matches) > 1:
        raise ValueError(f"multiple feeds match {name!r}; use exact casing after fixing config")
    return None


def config_diff(before_text: str, after_text: str, config_path: Path) -> list[str]:
    before_lines = before_text.splitlines(keepends=True)
    after_lines = after_text.splitlines(keepends=True)
    diff = difflib.unified_diff(
        before_lines,
        after_lines,
        fromfile=str(config_path),
        tofile=f"{config_path} (updated)",
        lineterm="",
    )
    return [redact_secrets(line.rstrip("\n")) for line in diff]


def create_config_backup(config_path: Path, before_text: str) -> Path:
    backup_dir = config_path.parent / "ops" / "config-backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    suffix = config_path.suffix or ".yaml"
    base = f"{config_path.stem}.{timestamp}{suffix}"
    backup_path = backup_dir / base
    counter = 1
    while backup_path.exists():
        backup_path = backup_dir / f"{config_path.stem}.{timestamp}.{counter}{suffix}"
        counter += 1
    backup_path.write_text(before_text, encoding="utf-8")
    return backup_path


def emit_mutation_result(payload: dict[str, Any], *, json_output: bool) -> None:
    if json_output:
        print_json(payload)
        return

    print(payload["message"])
    if payload.get("dry_run"):
        print("dry_run: no file written")
    if payload.get("backup_path"):
        print(f"backup: {payload['backup_path']}")
    diff_lines = payload.get("diff") or []
    if diff_lines:
        print("\n".join(diff_lines))


def run_config_mutation(args: argparse.Namespace, mutator: Any) -> int:
    config_path = args.config
    before_text = config_path.read_text(encoding="utf-8")
    raw = load_raw_config(config_path)
    candidate = copy.deepcopy(raw)
    mutation = mutator(candidate, args)
    parse_config(candidate)

    after_text = dump_config_text(candidate)
    diff_lines = config_diff(before_text, after_text, config_path) if mutation.changed else []
    backup_path = None
    if mutation.changed and not args.dry_run:
        backup_path = create_config_backup(config_path, before_text)
        config_path.write_text(after_text, encoding="utf-8")
        load_config(config_path)

    payload = {
        "ok": True,
        "operation": mutation.operation,
        "changed": mutation.changed,
        "dry_run": bool(args.dry_run),
        "config_path": str(config_path),
        "backup_path": str(backup_path) if backup_path else None,
        "message": mutation.message,
        "feed": mutation.feed,
        "diff": diff_lines,
    }
    emit_mutation_result(payload, json_output=args.json_output)
    return 0


def mutate_add_feed(raw: dict[str, Any], args: argparse.Namespace) -> ConfigMutation:
    name = str(args.name or "").strip()
    url = str(args.url or "").strip()
    tags = [str(tag).strip() for tag in (args.tag or []) if str(tag).strip()]
    webhook_url = str(args.webhook_url or "").strip()
    enabled = not args.disabled

    if not name:
        raise ValueError("feed name is required")
    validate_feed_url(url)
    if webhook_url:
        validate_discord_webhook_url(webhook_url)

    feeds = ensure_feeds_list(raw)
    existing_index = find_feed_index(feeds, name)
    new_feed: dict[str, Any] = {"name": name, "url": url, "enabled": enabled, "tags": tags}
    if webhook_url:
        new_feed["webhook_url"] = webhook_url

    if existing_index is not None:
        existing = feeds[existing_index]
        existing_webhook = str(existing.get("webhook_url") or "").strip()
        if raw_feed_record(existing) == raw_feed_record(new_feed) and existing_webhook == webhook_url:
            return ConfigMutation("config.add-feed", False, f"feed already exists: {name}", raw_feed_record(existing))
        raise ValueError(f"feed already exists with different settings: {name}")

    for feed in feeds:
        if str(feed.get("url") or "").strip() == url:
            raise ValueError("another feed already uses this URL")

    feeds.append(new_feed)
    return ConfigMutation("config.add-feed", True, f"added feed: {name}", raw_feed_record(new_feed))


def mutate_set_feed_enabled(raw: dict[str, Any], args: argparse.Namespace, *, enabled: bool) -> ConfigMutation:
    name = str(args.name or "").strip()
    feeds = ensure_feeds_list(raw)
    index = find_feed_index(feeds, name)
    if index is None:
        raise ValueError(f"feed not found: {name}")
    feed = feeds[index]
    if bool(feed.get("enabled", True)) == enabled:
        state = "enabled" if enabled else "disabled"
        return ConfigMutation(f"config.{state}-feed", False, f"feed already {state}: {name}", raw_feed_record(feed))
    feed["enabled"] = enabled
    state = "enabled" if enabled else "disabled"
    return ConfigMutation(f"config.{state}-feed", True, f"{state} feed: {name}", raw_feed_record(feed))


def mutate_remove_feed(raw: dict[str, Any], args: argparse.Namespace) -> ConfigMutation:
    name = str(args.name or "").strip()
    feeds = ensure_feeds_list(raw)
    index = find_feed_index(feeds, name)
    if index is None:
        raise ValueError(f"feed not found: {name}")
    removed = feeds.pop(index)
    return ConfigMutation("config.remove-feed", True, f"removed feed: {name}", raw_feed_record(removed))


def command_example_config(_args: argparse.Namespace) -> int:
    print(EXAMPLE_CONFIG)
    return 0


def command_validate(args: argparse.Namespace) -> int:
    app_config = load_config(args.config)
    payload = config_summary(args.config, app_config)
    if args.json_output:
        print_json(payload)
    else:
        print(f"config valid: {args.config}")
        print(f"feeds: {payload['feed_count']} total, {payload['enabled_feed_count']} enabled")
        print(f"state: {payload['state_path']}")
        print(f"logs: {payload['log_path']}")
    return 0


def command_list_feeds(args: argparse.Namespace) -> int:
    app_config = load_config(args.config)
    feeds = [feed_record(feed) for feed in app_config.feeds]
    payload = {"ok": True, "config_path": str(args.config), "feeds": feeds}
    if args.json_output:
        print_json(payload)
    else:
        print_feed_table(feeds)
    return 0


def command_add_feed(args: argparse.Namespace) -> int:
    return run_config_mutation(args, mutate_add_feed)


def command_enable_feed(args: argparse.Namespace) -> int:
    return run_config_mutation(args, lambda raw, ns: mutate_set_feed_enabled(raw, ns, enabled=True))


def command_disable_feed(args: argparse.Namespace) -> int:
    return run_config_mutation(args, lambda raw, ns: mutate_set_feed_enabled(raw, ns, enabled=False))


def command_remove_feed(args: argparse.Namespace) -> int:
    return run_config_mutation(args, mutate_remove_feed)


def command_poll_once(args: argparse.Namespace) -> int:
    app_config = load_config(args.config)
    logger = JsonlLogger(app_config.logging.jsonl_path, app_config.logging.level)
    state = StateStore(app_config.state.sqlite_path)
    try:
        poll_once(app_config, state, logger, dry_run=args.dry_run)
        return 0
    finally:
        state.close()


def run_daemon(
    app_config: AppConfig,
    logger: JsonlLogger,
    state: StateStore,
    stop: StopFlag,
    *,
    dry_run: bool = False,
) -> int:
    logger.info(
        "daemon_started",
        interval_seconds=app_config.poll.interval_seconds,
        jitter_seconds=app_config.poll.jitter_seconds,
        feed_count=len(app_config.feeds),
    )
    while not stop.stop:
        poll_once(app_config, state, logger, dry_run=dry_run)
        jitter = random.uniform(0, app_config.poll.jitter_seconds) if app_config.poll.jitter_seconds else 0
        sleep_seconds = app_config.poll.interval_seconds + jitter
        logger.info("sleeping", seconds=round(sleep_seconds, 3))
        deadline = time.monotonic() + sleep_seconds
        while not stop.stop and time.monotonic() < deadline:
            time.sleep(min(1.0, deadline - time.monotonic()))

    logger.info("daemon_stopped")
    return 0


def command_poll_daemon(args: argparse.Namespace) -> int:
    app_config = load_config(args.config)
    logger = JsonlLogger(app_config.logging.jsonl_path, app_config.logging.level)
    state = StateStore(app_config.state.sqlite_path)
    stop = StopFlag()
    stop.install(logger)
    try:
        return run_daemon(app_config, logger, state, stop, dry_run=args.dry_run)
    finally:
        state.close()


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", type=Path, default=argparse.SUPPRESS, help="YAML config path")
    parser.add_argument("--json", dest="json_output", action="store_true", default=argparse.SUPPRESS, help="print JSON output")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="RSS/Atom -> Discord webhook notifier. YAML config. SQLite state. JSONL logs."
    )
    parser.add_argument("--config", type=Path, default=Path("config.yaml"), help="YAML config path")
    parser.add_argument("--json", dest="json_output", action="store_true", help="print JSON output for agent commands")
    parser.add_argument("--once", action="store_true", help="legacy: poll once and exit")
    parser.add_argument("--dry-run", action="store_true", help="legacy: do not send Discord messages")
    parser.add_argument("--print-example-config", action="store_true", help="legacy: print sample YAML config")
    parser.add_argument("--validate-config", action="store_true", help="legacy: load config and exit")

    subparsers = parser.add_subparsers(dest="command")

    example_parser = subparsers.add_parser("example-config", help="print sample YAML config")
    example_parser.set_defaults(handler=command_example_config)

    validate_parser = subparsers.add_parser("validate", help="validate config and print a summary")
    add_common_args(validate_parser)
    validate_parser.set_defaults(handler=command_validate)

    poll_parser = subparsers.add_parser("poll", help="poll feeds or run the daemon")
    poll_subparsers = poll_parser.add_subparsers(dest="poll_command", required=True)
    poll_once_parser = poll_subparsers.add_parser("once", help="poll once and exit")
    add_common_args(poll_once_parser)
    poll_once_parser.add_argument("--dry-run", action="store_true", help="do not send Discord messages")
    poll_once_parser.set_defaults(handler=command_poll_once)
    poll_daemon_parser = poll_subparsers.add_parser("daemon", help="run the long-lived poller")
    add_common_args(poll_daemon_parser)
    poll_daemon_parser.add_argument("--dry-run", action="store_true", help="do not send Discord messages")
    poll_daemon_parser.set_defaults(handler=command_poll_daemon)

    config_parser = subparsers.add_parser("config", help="agent-safe YAML config operations")
    config_subparsers = config_parser.add_subparsers(dest="config_command", required=True)

    config_validate_parser = config_subparsers.add_parser("validate", help="validate config and print a summary")
    add_common_args(config_validate_parser)
    config_validate_parser.set_defaults(handler=command_validate)

    list_feeds_parser = config_subparsers.add_parser("list-feeds", help="list configured feeds")
    add_common_args(list_feeds_parser)
    list_feeds_parser.set_defaults(handler=command_list_feeds)

    add_feed_parser = config_subparsers.add_parser("add-feed", help="add an RSS/Atom feed")
    add_common_args(add_feed_parser)
    add_feed_parser.add_argument("--name", required=True, help="feed display name")
    add_feed_parser.add_argument("--url", required=True, help="RSS/Atom feed URL")
    add_feed_parser.add_argument("--tag", action="append", default=[], help="feed tag; repeat for multiple tags")
    add_feed_parser.add_argument("--webhook-url", help="optional per-feed Discord webhook override")
    add_feed_parser.add_argument("--disabled", action="store_true", help="add feed disabled")
    add_feed_parser.add_argument("--dry-run", action="store_true", help="show redacted diff without writing")
    add_feed_parser.set_defaults(handler=command_add_feed)

    enable_feed_parser = config_subparsers.add_parser("enable-feed", help="enable a feed by name")
    add_common_args(enable_feed_parser)
    enable_feed_parser.add_argument("--name", required=True, help="feed display name")
    enable_feed_parser.add_argument("--dry-run", action="store_true", help="show redacted diff without writing")
    enable_feed_parser.set_defaults(handler=command_enable_feed)

    disable_feed_parser = config_subparsers.add_parser("disable-feed", help="disable a feed by name")
    add_common_args(disable_feed_parser)
    disable_feed_parser.add_argument("--name", required=True, help="feed display name")
    disable_feed_parser.add_argument("--dry-run", action="store_true", help="show redacted diff without writing")
    disable_feed_parser.set_defaults(handler=command_disable_feed)

    remove_feed_parser = config_subparsers.add_parser("remove-feed", help="remove a feed by name")
    add_common_args(remove_feed_parser)
    remove_feed_parser.add_argument("--name", required=True, help="feed display name")
    remove_feed_parser.add_argument("--dry-run", action="store_true", help="show redacted diff without writing")
    remove_feed_parser.set_defaults(handler=command_remove_feed)

    return parser


def run_legacy(args: argparse.Namespace) -> int:
    if args.print_example_config:
        print(EXAMPLE_CONFIG)
        return 0

    try:
        app_config = load_config(args.config)
    except Exception as exc:
        return emit_error(f"config_error: {exc}", json_output=args.json_output, code=2)

    if args.validate_config and args.json_output:
        print_json(config_summary(args.config, app_config))
        return 0

    logger = JsonlLogger(app_config.logging.jsonl_path, app_config.logging.level)

    if args.validate_config:
        logger.info(
            "config_validated",
            config_path=str(args.config),
            feed_count=len(app_config.feeds),
            enabled_feed_count=len([f for f in app_config.feeds if f.enabled]),
            state_path=str(app_config.state.sqlite_path),
        )
        return 0

    state = StateStore(app_config.state.sqlite_path)
    stop = StopFlag()
    stop.install(logger)

    try:
        if args.once:
            poll_once(app_config, state, logger, dry_run=args.dry_run)
            return 0

        return run_daemon(app_config, logger, state, stop, dry_run=args.dry_run)
    finally:
        state.close()


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "json_output"):
        args.json_output = False
    if not hasattr(args, "config"):
        args.config = Path("config.yaml")

    handler = getattr(args, "handler", None)
    if handler is None:
        return run_legacy(args)

    try:
        return handler(args)
    except Exception as exc:
        return emit_error(str(exc), json_output=args.json_output)


if __name__ == "__main__":
    raise SystemExit(main())
