import json
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ConfigCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.workdir = Path(self.tmp.name)
        self.config_path = self.workdir / "config.yaml"
        webhook = "https://discord.com/api/" + "webhooks/123456789/test-token"
        self.config_path.write_text(
            textwrap.dedent(
                f"""\
                discord:
                  webhook_url: "{webhook}"
                  username: "rsscord"
                  avatar_url: null

                poll:
                  interval_seconds: 300
                  jitter_seconds: 0
                  timeout_seconds: 5
                  user_agent: "rsscord/test"

                state:
                  sqlite_path: "{self.workdir / 'state.sqlite3'}"
                  first_run: "mark_seen"
                  recent_limit_per_feed: 5

                logging:
                  level: "INFO"
                  jsonl_path: "{self.workdir / 'rsscord.log.jsonl'}"

                notifications:
                  use_embeds: true
                  max_items_per_poll: 25
                  summary_max_chars: 500
                  content_template: "{{feed_name}}: {{title}}\\n{{link}}"

                discord_rate_limit:
                  max_retries: 1
                  base_backoff_seconds: 0.1

                feeds:
                  - name: "Hacker News"
                    url: "https://hnrss.org/frontpage"
                    enabled: true
                    tags: ["tech"]
                """
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_cli(self, args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [sys.executable, str(ROOT / "rsscord.py"), *args],
            capture_output=True,
            text=True,
            check=False,
        )
        if check and result.returncode != 0:
            self.fail(f"command failed: {result.args}\nstdout={result.stdout}\nstderr={result.stderr}")
        return result

    def test_list_feeds_json_omits_webhook_values(self) -> None:
        result = self.run_cli(["config", "list-feeds", "--config", str(self.config_path), "--json"])
        payload = json.loads(result.stdout)

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["feeds"][0]["name"], "Hacker News")
        self.assertFalse(payload["feeds"][0]["has_webhook_override"])
        self.assertNotIn("webhook_url", result.stdout)
        self.assertNotIn("test-token", result.stdout)

    def test_add_feed_dry_run_json_redacts_webhook_and_does_not_write(self) -> None:
        webhook = "https://discord.com/api/" + "webhooks/999999999/feed-token"
        before = self.config_path.read_text(encoding="utf-8")
        result = self.run_cli(
            [
                "config",
                "add-feed",
                "--config",
                str(self.config_path),
                "--json",
                "--dry-run",
                "--name",
                "Example",
                "--url",
                "https://example.com/rss.xml",
                "--tag",
                "example",
                "--webhook-url",
                webhook,
            ]
        )
        payload = json.loads(result.stdout)

        self.assertTrue(payload["ok"])
        self.assertTrue(payload["changed"])
        self.assertTrue(payload["dry_run"])
        self.assertIsNone(payload["backup_path"])
        self.assertIn("webhook_url: \"<redacted>\"", "\n".join(payload["diff"]))
        self.assertNotIn("feed-token", result.stdout)
        self.assertEqual(before, self.config_path.read_text(encoding="utf-8"))

    def test_add_disable_and_remove_feed_create_backups(self) -> None:
        add_result = self.run_cli(
            [
                "config",
                "add-feed",
                "--config",
                str(self.config_path),
                "--json",
                "--name",
                "Example",
                "--url",
                "https://example.com/rss.xml",
                "--tag",
                "example",
            ]
        )
        add_payload = json.loads(add_result.stdout)
        self.assertTrue(add_payload["changed"])
        self.assertTrue(Path(add_payload["backup_path"]).exists())

        disable_result = self.run_cli(
            [
                "config",
                "disable-feed",
                "--config",
                str(self.config_path),
                "--json",
                "--name",
                "Example",
            ]
        )
        disable_payload = json.loads(disable_result.stdout)
        self.assertTrue(disable_payload["changed"])
        self.assertFalse(disable_payload["feed"]["enabled"])
        self.assertTrue(Path(disable_payload["backup_path"]).exists())

        remove_result = self.run_cli(
            [
                "config",
                "remove-feed",
                "--config",
                str(self.config_path),
                "--json",
                "--name",
                "Example",
            ]
        )
        remove_payload = json.loads(remove_result.stdout)
        self.assertTrue(remove_payload["changed"])
        self.assertTrue(Path(remove_payload["backup_path"]).exists())

        list_result = self.run_cli(["config", "list-feeds", "--config", str(self.config_path), "--json"])
        feeds = json.loads(list_result.stdout)["feeds"]
        self.assertEqual([feed["name"] for feed in feeds], ["Hacker News"])

    def test_validate_json(self) -> None:
        result = self.run_cli(["validate", "--config", str(self.config_path), "--json"])
        payload = json.loads(result.stdout)

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["feed_count"], 1)
        self.assertEqual(payload["enabled_feed_count"], 1)


if __name__ == "__main__":
    unittest.main()
