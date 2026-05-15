# Roadmap

This document tracks likely future work. Items here are not implemented unless stated elsewhere.

---

## Near-term

* [ ] Add tests for config validation.
* [ ] Add tests for dedupe behavior.
* [ ] Add tests for first-run modes.
* [ ] Add tests for Discord send failure behavior.
* [ ] Add screenshot or GIF of Discord notification output.
* [x] Add release packaging for easier `uvx` use.
* [x] Add `AGENTS.md` to repo root.

---

## Agent-facing config operations

Status: initial native CLI implemented.

Goal: allow a local agent such as Hermes Agent to add, edit, disable, and remove feeds safely.

Current commands:

```bash
rsscord config list-feeds --config config.yaml --json
rsscord config add-feed --config config.yaml --json --dry-run --name "Example" --url "https://example.com/rss.xml" --tag example
rsscord config add-feed --config config.yaml --json --name "Example" --url "https://example.com/rss.xml" --tag example
rsscord config disable-feed --config config.yaml --json --name "Example"
rsscord config enable-feed --config config.yaml --json --name "Example"
rsscord config remove-feed --config config.yaml --json --name "Example"
rsscord config validate --config config.yaml --json
```

Implemented constraints:

* Comments are not preserved; config writes use PyYAML serialization.
* Mutations create timestamped config backups before writing.
* Discord webhook values are redacted from JSON and diff output.
* Feed URLs are validated before writing.
* Full config is validated before and after writing.
* Enable/disable/add exact duplicates are idempotent where possible.
* Dry-run diff mode is supported.
* Human-readable YAML remains the source of truth.

Potential implementation options:

* Native subcommands inside `rsscord.py`.
* Separate helper script such as `rsscord-config`.
* `cli-anything` wrapper for rapid command scaffolding.
* Later MCP server only if truly needed. Not part of current implementation.

Remaining direction:

1. Add an update-feed command for renames, URL changes, and tag edits.
2. Add OPML import/export once feed list management stabilizes.
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
