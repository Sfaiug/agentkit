"""Claude's 20x plan reads ULTRA on a screen: "Rename 20x max to ULTRA." (owner, 10 Nov 2026).

A login's plan stays in `login-end`'s words, `max 20x`, wherever it is kept and priced:
state/logins.json, `[plans]`, and each of history.db's `meter_readings`
(tests/test_key_meter_readings_plan.py), where a changed word would start a fit of its own.  Only
what a screen says changes: the line `Subscriptions` opens under a login on `max 20x` says
`ULTRA`, and under one on `max 5x`, `max 5x`.
Black-box: the program `AK_BIN` names ticks, and draws its menu in a person's terminal
(tests/fixtures/akterm.py), from outside, over two Claude subscriptions whose adapter, a fake
(tests/fixtures/fakeadapter.py) under the shipped adapters/claude.toml, answers `login-end` by
AGENTKIT_ACCOUNT; the database is read with sqlite3.  This test fails against `/bin/false`.
"""

import json
import sqlite3
import sys
from pathlib import Path
import time
import tomllib
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, boxable, Home
from fixtures.akterm import SERVER, Terminal
from test_key_subscriptions_page import MAIN_KEYS, PAGE, body, lines, title

# each login's, under the provider of Claude's shipped models
LOCK = ".agentkit/state/anthropic.{}-probe.lock"
# before the fake itself: `login-end` says the login of the account it is asked for
BY_ACCOUNT = """case "$1" in login-end)
  case "$AGENTKIT_ACCOUNT" in
    two) echo '{"email": "two@acme.test", "ends": null, "plan": "max 5x"}' ;;
    *) echo '{"email": "owner@acme.test", "ends": null, "plan": "max 20x"}' ;;
  esac
  exit 0 ;;
esac
"""


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class PlanReadsUltra(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        fake = fakeadapter.install(self.home, claude="pass")["claude"]
        fake.script.write_text(fake.script.read_text().replace(
            "#!/bin/sh\n", "#!/bin/sh\n" + BY_ACCOUNT, 1))
        akconfig.write(self.home, {"fable": "claude"}, providers={
            "anthropic": {"mode": "subscription", "accounts": ["default", "two"]}})
        self.tick()          # learns each login's plan, its meters refused
        fake.answer("usage", json.dumps({"meters": [{
            "name": "weekly_all", "used": 40, "resets_at": int(time.time()) + 3 * 86400,
            "window_secs": 604800}]}))
        every = tomllib.loads(fake.manifest.read_text())["usage"]["probe_every"]
        for account in ("default", "two"):
            self.home.write(LOCK.format(account), repr(time.time() - every - 5))
        self.tick()          # reads each login's meters

    def tick(self):
        done = self.home.tick()
        self.assertEqual(done.code, 0, done.out + done.err)

    def test_the_screen_says_ultra_and_every_reading_keeps_the_logins_own_word(self):
        connection = sqlite3.connect(self.home.path / ".agentkit/history.db")
        try:
            kept = connection.execute("SELECT DISTINCT account, plan FROM meter_readings "
                                      "ORDER BY account").fetchall()
        finally:
            connection.close()
        self.assertEqual(kept, [("default", "max 20x"), ("two", "max 5x")])

        term = Terminal(self.home, size=(100, 40), env={"NO_COLOR": "1"})
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        term.wait(lambda screen: MAIN_KEYS in lines(screen))
        term.keys("c")
        term.wait("› Fable 5.1")
        for _ in range(10):
            if "› Subscriptions" in term.screen():
                break
            shown = term.screen()
            term.keys("Down")
            term.wait(lambda screen: screen != shown)
        term.keys("Enter")
        first = term.wait(lambda screen: title(screen) == PAGE
                          and "    owner@acme.test · ULTRA   − remove" in lines(screen))
        self.assertEqual(body(first)[1:3], ["› Claude I   ━━━━━━────  60% left",
                                            "    owner@acme.test · ULTRA   − remove"])
        self.assertNotIn("max 20x", first)
        term.keys("Down")
        second = term.wait(lambda screen: "› Claude II" in screen)
        self.assertEqual(body(second)[2:4], ["› Claude II  ━━━━━━────  60% left",
                                             "    two@acme.test · max 5x   − remove"])


if __name__ == "__main__":
    unittest.main()
