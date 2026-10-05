"""Claude's extra usage counts as credits left, in money; offline, with invented replies.

`adapters/claude.sh usage` reads extra usage off the same api.anthropic.com/api/oauth/usage
reply its meters come from and, while it is on, asks for the login's prepaid balance.  What is
left, as Claude Code counts it, is the smaller of the monthly limit's remainder and that
balance, the limit unbounded when none is set and the balance while auto-reload is on; both
unbounded is `unlimited`.  It is `credits`, in the major units of the reply's `currency`, which
it reports beside them.  Off, or with no balance read, neither is there, and the one-time
credit adds nothing.  Claude's usage row and `ak usage` then say `$12.40 credits left` while
ChatGPT's say `62,469 credits left`.  The replies are tests/fixtures/claude-usage-extra.json, a
fake curl serves them, and the token is invented.
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
ORG = "0f0e0d0c-0b0a-4908-8706-050403020100"

# The usage endpoint answering $REPLY, the prepaid balance $PREPAID or failing without it; each
# ask's URL goes to $ASKED, and the token stays unread.
FAKE_CURL = r'''#!/usr/bin/env python3
import os, sys
url = next(a for a in sys.argv[1:] if a.startswith("https://"))
with open(os.environ["ASKED"], "a") as asked:
    asked.write(url + "\n")
if "/prepaid/credits" in url:
    if not os.environ.get("PREPAID"):
        sys.exit(22)
    sys.stdout.write(os.environ["PREPAID"])
else:
    sys.stdout.write(os.environ["REPLY"] + "\n200")
'''


def changed(reply, **fields):
    """A copy of `reply` with `fields` set, a dotted name reaching into it."""
    reply = json.loads(json.dumps(reply))
    for name, value in fields.items():
        *path, last = name.split("__")
        inner = reply
        for key in path:
            inner = inner[key]
        inner[last] = value
    return reply


class Adapter(unittest.TestCase):
    def usage(self, reply, prepaid=REPLIES["prepaid"], org=ORG):
        """What the adapter says, and the URLs it asked."""
        with tempfile.TemporaryDirectory(prefix="ak-test-claude-credits-") as tmp:
            root = Path(tmp)
            (root / ".agentkit/secrets").mkdir(parents=True)
            (root / ".agentkit/secrets/claude_oauth_token").write_text("tok-invented")
            (root / ".claude.json").write_text(json.dumps(
                {"oauthAccount": {"organizationUuid": org}} if org else {}))
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
                       REPLY=json.dumps(reply), ASKED=str(root / "asked"),
                       PREPAID=json.dumps(prepaid) if prepaid else "")
            proc = subprocess.run(["bash", str(REPO / "adapters/claude.sh"), "usage"], env=env,
                                  capture_output=True, text=True, timeout=60)
            asked = (root / "asked").read_text().split()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        said = json.loads(proc.stdout)
        self.assertIsNone(said["error"])
        self.assertEqual([m["name"] for m in said["meters"]], ["session", "weekly_all"])
        return said, asked

    def test_the_smaller_of_the_limits_remainder_and_the_balance_is_credits_in_money(self):
        reloaded = changed(REPLIES["prepaid"], amount=200, auto_reload_settings={"enabled": True})
        for case, reply, prepaid, left in (
                # 5000 - 3760 cents under the limit, $90.00 held; the one-time credit adds none
                ("limit first", REPLIES["enabled"], REPLIES["prepaid"], 12.40),
                ("balance first", REPLIES["enabled"], changed(REPLIES["prepaid"], amount=200), 2.00),
                ("auto-reload", REPLIES["enabled"], reloaded, 12.40),
                ("no limit", REPLIES["uncapped"], REPLIES["prepaid"], 90.00)):
            with self.subTest(case=case):
                said, asked = self.usage(reply, prepaid)
                self.assertAlmostEqual(said["credits"], left)
                self.assertEqual(said["currency"], "USD")
                self.assertIn(f"https://api.anthropic.com/api/oauth/organizations/{ORG}"
                              "/prepaid/credits", asked)

    def test_no_limit_and_auto_reload_is_unlimited(self):
        said, _ = self.usage(REPLIES["uncapped"],
                             changed(REPLIES["prepaid"], auto_reload_settings={"enabled": True}))
        self.assertEqual((said["credits"], said["currency"]), ("unlimited", "USD"))

    def test_off_or_no_balance_read_leaves_both_out(self):
        for case, reply, prepaid, org, asks in (
                ("off", REPLIES["disabled"], REPLIES["prepaid"], ORG, 1),
                ("balance unavailable", REPLIES["enabled"], None, ORG, 2),
                ("no organization", REPLIES["enabled"], REPLIES["prepaid"], None, 1)):
            with self.subTest(case=case):
                said, asked = self.usage(reply, prepaid, org)
                self.assertNotIn("credits", said)
                self.assertNotIn("currency", said)
                self.assertEqual(len(asked), asks, asked)

    def test_the_reply_decides_the_unit(self):
        for currency, places, left, unit in ((None, 2, 12.40, "USD"), ("eur", 2, 12.40, "EUR"),
                                             ("JPY", 0, 1240, "JPY")):
            with self.subTest(currency=currency):
                said, _ = self.usage(changed(REPLIES["enabled"], extra_usage__currency=currency,
                                             extra_usage__decimal_places=places))
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

    def test_unlimited_credits_say_so(self):
        said = {"meters": [self.meter("weekly_all")], "credits": "unlimited", "currency": "USD",
                "error": None}
        answer = subprocess.CompletedProcess([], 0, stdout=json.dumps(said), stderr="")
        with patch.object(usage.subprocess, "run", return_value=answer), \
                patch.object(usage, "_resets", return_value=0.0):
            read = usage._probe(self.cfg, "anthropic", self.now)
        self.assertEqual(read["credits"], "unlimited")
        providers = usage._gate_flags({"anthropic": {**read, "resets": 0}}, self.now, self.cfg)
        self.assertTrue(providers["anthropic"]["on_credits"])
        (config.STATE / "usage.json").write_text(json.dumps(
            {"fetched_at": self.now, "providers": providers}))
        for width in (100, 40):
            rows = [terminal.plain(line) for line in menu.usage_lines(self.cfg, width)]
            claude = next(row for row in rows if row.lstrip().startswith("Claude"))
            self.assertRegex(claude, r"░ +unlimited credits")


if __name__ == "__main__":
    unittest.main()
