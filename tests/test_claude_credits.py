"""Claude's extra usage counts as credits left, in money; offline, with invented replies.

`adapters/claude.sh usage` reads what extra usage has left under its monthly limit off the
same api.anthropic.com/api/oauth/usage reply its meters come from: `credits` while
`is_enabled` and a limit is set, in the major units of the reply's `currency`, which it
reports beside them.  Off or uncapped, neither is there, and the one-time credit adds
nothing.  Claude's usage row and `ak usage` then say `$12.40 credits left` while ChatGPT's
say `62,469 credits left`.  The replies are tests/fixtures/claude-usage-extra.json, a fake
curl serves them, and the token is invented.
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import tomllib
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, menu, terminal, usage  # noqa: E402

WEEK = 604800
REPLIES = json.loads((REPO / "tests/fixtures/claude-usage-extra.json").read_text())

# The usage endpoint answering the reply in $REPLY; the token stays unread.
FAKE_CURL = r'''#!/usr/bin/env python3
import os, sys
sys.stdout.write(os.environ["REPLY"] + "\n200")
'''


class Adapter(unittest.TestCase):
    def usage(self, reply):
        with tempfile.TemporaryDirectory(prefix="ak-test-claude-credits-") as tmp:
            root = Path(tmp)
            (root / ".agentkit/secrets").mkdir(parents=True)
            (root / ".agentkit/secrets/claude_oauth_token").write_text("tok-invented")
            (root / "bin").mkdir()
            (root / "bin/curl").write_text(FAKE_CURL)
            # no Keychain on any host this runs on
            (root / "bin/security").write_text("#!/usr/bin/env bash\nexit 1\n")
            for tool in ("curl", "security"):
                (root / "bin" / tool).chmod(0o755)
            env = {k: v for k, v in os.environ.items()
                   if not k.startswith(("AK_", "AGENTKIT_"))
                   and k not in ("CLAUDE_CONFIG_DIR", "CLAUDE_CODE_OAUTH_TOKEN")}
            env.update(HOME=tmp, PATH=f"{root / 'bin'}:{os.environ['PATH']}",
                       REPLY=json.dumps(reply))
            proc = subprocess.run(["bash", str(REPO / "adapters/claude.sh"), "usage"], env=env,
                                  capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        said = json.loads(proc.stdout)
        self.assertIsNone(said["error"])
        self.assertEqual([m["name"] for m in said["meters"]], ["session", "weekly_all"])
        return said

    def test_extra_usage_left_under_its_limit_is_credits_in_money(self):
        said = self.usage(REPLIES["enabled"])
        # 5000 - 3760 cents; the one-time credit beside it says no amount, so adds none
        self.assertAlmostEqual(said["credits"], 12.40)
        self.assertEqual(said["currency"], "USD")

    def test_extra_usage_off_or_uncapped_leaves_both_out(self):
        for case in ("disabled", "uncapped"):
            with self.subTest(case=case):
                said = self.usage(REPLIES[case])
                self.assertNotIn("credits", said)
                self.assertNotIn("currency", said)

    def test_the_reply_decides_the_unit(self):
        for currency, left, unit in ((None, 12.40, "USD"), ("eur", 12.40, "EUR"),
                                     ("JPY", 1240, "JPY")):
            with self.subTest(currency=currency):
                reply = json.loads(json.dumps(REPLIES["enabled"]))
                reply["extra_usage"]["currency"] = currency
                said = self.usage(reply)
                self.assertAlmostEqual(said["credits"], left)
                self.assertEqual(said["currency"], unit)


class Shown(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="ak-test-claude-credits-")
        self.addCleanup(tmp.cleanup)
        self.state = patch.object(config, "STATE", Path(tmp.name))
        self.state.start()
        self.addCleanup(self.state.stop)
        self.cfg = tomllib.loads((REPO / "config.default.toml").read_text())
        for model in ("grok", "gemini", "mimo"):
            self.cfg["providers"].pop(self.cfg["models"].pop(model)["provider"])
        self.cfg["defaults"] = {"orchestrator": "astra", "workers": ["opus", "astra", "spark"]}
        self.now = time.time()

    def meter(self, name):
        return {"name": name, "used": 100, "window_secs": WEEK,
                "resets_at": self.now + WEEK / 2, "elapsed": 50.0, "pace": 50.0}

    def test_the_probe_keeps_the_unit_beside_the_credits(self):
        said = {"meters": [self.meter("weekly_all")], "credits": 12.4, "currency": "USD",
                "error": None}
        answer = subprocess.CompletedProcess([], 0, stdout=json.dumps(said), stderr="")
        with patch.object(usage.subprocess, "run", return_value=answer), \
                patch.object(usage, "_resets", return_value=0.0):
            read = usage._probe(self.cfg, "anthropic", self.now)
        self.assertEqual((read["credits"], read["currency"]), (12.4, "USD"))
        kept = usage._kept({**read, "probed_at": self.now},
                           {"meters": [], "error": "unknown: HTTP 429"}, self.now)
        self.assertEqual((kept["credits"], kept["currency"]), (12.4, "USD"))

    def test_claude_says_money_and_chatgpt_says_credits(self):
        providers = usage._gate_flags({
            "anthropic": {"provider": "anthropic", "meters": [self.meter("weekly_all")],
                          "resets": 0, "error": None, "credits": 12.4, "currency": "USD"},
            "openai": {"provider": "openai", "meters": [self.meter("weekly")], "resets": 0,
                       "error": None, "credits": 62469.67}}, self.now, self.cfg)
        self.assertTrue(providers["anthropic"]["on_credits"])
        (config.STATE / "usage.json").write_text(json.dumps(
            {"fetched_at": self.now, "providers": providers}))
        for width in (100, 40):
            rows = [terminal.plain(line) for line in menu.usage_lines(self.cfg, width)]
            claude = next(row for row in rows if row.lstrip().startswith("Claude"))
            chat = next(row for row in rows if row.lstrip().startswith("ChatGPT"))
            self.assertRegex(claude, r"░ +\$12\.40 credits left")
            self.assertRegex(chat, r"░ +62,469 credits left")
        with patch.object(usage, "review_pair", return_value=None):
            shown = terminal.plain(usage.render(self.cfg, providers, ["opus", "astra"]))
        self.assertIn("anthropic: $12.40 credits left", shown)
        self.assertIn("openai: 62,469 credits left", shown)


if __name__ == "__main__":
    unittest.main()
