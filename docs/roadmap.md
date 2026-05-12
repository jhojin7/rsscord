# Roadmap

This document tracks likely future work. Items here are not implemented unless stated elsewhere.

---

## Near-term

* [ ] Add tests for config validation.
* [ ] Add tests for dedupe behavior.
* [ ] Add tests for first-run modes.
* [ ] Add tests for Discord send failure behavior.
* [ ] Add screenshot or GIF of Discord notification output.
* [ ] Add release packaging for easier `uvx` use.
* [ ] Add `AGENTS.md` to repo root.

---

## Agent-facing config operations

Goal: allow a local agent such as Hermes Agent to add, edit, disable, and remove feeds safely.

Likely commands:

```bash
uv run rsscord.py config list-feeds --config config.yaml
uv run rsscord.py config add-feed --config config.yaml --name "Example" --url "https://example.com/rss.xml" --tag example
uv run rsscord.py config disable-feed --config config.yaml --name "Example"
uv run rsscord.py config enable-feed --config config.yaml --name "Example"
uv run rsscord.py config remove-feed --config config.yaml --name "Example"
uv run rsscord.py config validate --config config.yaml
```

Design constraints:

* Preserve comments when possible, or document that comments may be lost.
* Always create timestamped config backup before mutation.
* Never print Discord webhook tokens.
* Validate feed URL shape before write.
* Validate full config after write.
* Prefer idempotent commands.
* Support dry-run diff mode.
* Keep human-readable YAML as source of truth.

Potential implementation options:

* Native subcommands inside `rsscord.py`.
* Separate helper script such as `rsscord-config`.
* `cli-anything` wrapper for rapid command scaffolding.
* Later MCP server only if truly needed. Not part of current implementation.

Recommended direction:

1. Start with native CLI subcommands.
2. Add dry-run diff and backup.
3. Let Hermes call CLI commands directly on same machine.
4. Avoid MCP until there is a concrete need for remote tool discovery or richer protocol semantics.

Reasoning:

* Hermes and `rsscord` run on same host.
* Config is a local YAML file.
* Desired operations are deterministic file mutations.
* CLI keeps the trust boundary smaller than an always-on config server.

---

## FreshRSS integration

Possible later direction:

* [ ] Read feeds from FreshRSS API.
* [ ] Reuse FreshRSS categories as Discord routing metadata.
* [ ] Support FreshRSS as source of truth while `rsscord` handles Discord delivery.

Current implementation watches feed URLs directly.

---

## Import/export

* [ ] OPML import.
* [ ] OPML export.
* [ ] Export feed list as Markdown.
* [ ] Export recent notifications as JSONL or Markdown digest.

---

## Routing and templates

* [ ] Per-feed/category routing rules.
* [ ] Better Discord embed templates.
* [ ] Tag-based webhook routing.
* [ ] Optional keyword filters.
* [ ] Optional title/link rewrite hooks.

---

## Reliability

* [ ] Dead-letter queue for repeated Discord send failures.
* [ ] Healthcheck command.
* [ ] Optional heartbeat notification.
* [ ] Better noisy-feed dedupe controls.