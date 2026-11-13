"""A Claude seat's status render is its login's usage reading, at once and with no ask.

ak asks Anthropic's usage endpoint about a login at most every fifteen minutes; every status
render carries the numbers the API last reported to its seat (Claude Code 2.1.322's
`rate_limits`), an idle seat's the same again and again.  Numbers for a window other than its
conversation's last render's are that login's reading of the window's meter, with no ask; a
conversation's first numbers may be as old as its last answer and are only kept.

Black-box against AK_BIN: a Home whose Claude provider lists a second login, read once through a
fake `curl` counting each ask; two seats on that login (tests/fixtures/akseat.py) run their status
command as `ak orch --dry-run` prints it, in the environment it sets, the render's JSON on stdin,
waited out with all it started.  This test fails against `/bin/false`.
"""

import json
import os
import shlex
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import Home
from fixtures.akseat import Seat

LOGIN = "second"
WEEK = 604800


def seat_env(words):
    """The environment a command line's leading `env` words set, as `{name: value}`, a name
    they unset None."""
    told = {}
    while words and words[0] == "env":
        words = words[1:]
        while words:
            if words[0] == "-u":
                told[words[1]] = None
                words = words[2:]
            elif "=" in words[0] and not words[0].startswith("-"):
                name, _, value = words[0].partition("=")
                told[name] = value
                words = words[1:]
            else:
                break
    return told


class ClaudeSeatReportsItsLoginsUsage(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        akconfig.write(self.home, {"opus": "claude"}, providers={
            "anthropic": {"mode": "subscription", "accounts": ["default", LOGIN]}})
        # Only the second login holds a token: each ask of the endpoint is one of it.
        self.home.write(f".agentkit/secrets/claude_oauth_token.{LOGIN}", "tok-second")
        self.home.fake("security", "#!/bin/sh\nexit 1\n")     # no Keychain login on any host
        resets = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(time.time() + 3 * 86400))
        answer = self.home.write("answer.json", {"limits": [
            {"kind": "weekly_all", "group": "weekly", "percent": 10, "resets_at": resets}]})
        self.asks = self.home.root / "asks.log"
        self.home.fake("curl", f"#!/bin/sh\necho ask >>{shlex.quote(str(self.asks))}\n"
                               f"cat {shlex.quote(str(answer))}\nprintf '\\n200'\n")

    def asked(self):
        return len(self.asks.read_text().splitlines()) if self.asks.exists() else 0

    def reading(self):
        """The second login's reading as `ak usage --json` shows it."""
        done = self.home.ak("usage", "--json")
        self.assertEqual(done.code, 0, done.out + done.err)
        return json.loads(done.out)["providers"]["anthropic"]["accounts"][LOGIN]

    def weekly(self, reading):
        return [meter["used"] for meter in reading["meters"] if meter["name"] == "weekly_all"]

    def status(self, name):
        """`render(week, session=None)`: seat `name`'s status line run on those percentages."""
        seat = Seat(self.home, name, alive=False, record={"account": LOGIN})
        done = self.home.ak("orch", seat.name, "--dry-run", cwd=self.home.path)
        self.assertEqual(done.code, 0, done.out + done.err)
        words = shlex.split(done.out.splitlines()[-1])
        command = json.loads(words[words.index("--settings") + 1])["statusLine"]["command"]
        env = {**seat_env(words), "AGENTKIT_SESSION": seat.name}
        self.assertEqual(env.get("AGENTKIT_ACCOUNT"), LOGIN, words)
        now = int(time.time())

        def render(week, session=None):
            limits = {"seven_day": {"used_percentage": week, "resets_at": now + WEEK - 60}}
            if session is not None:
                limits["five_hour"] = {"used_percentage": session, "resets_at": now + 3600}
            payload = {"session_id": seat.record["conversation"],
                       "model": {"id": "claude-opus-5-5"}, "rate_limits": limits}
            end, held = os.pipe()
            try:
                done = self.home.run("sh", "-c", command, input=json.dumps(payload), env=env,
                                     cwd=seat.cwd, keep=(held,))
            finally:
                os.close(held)
            with os.fdopen(end, "rb") as drained:
                drained.read()
            self.assertEqual(done.code, 0, done.err)
        return render

    def test_only_a_conversations_changed_numbers_are_its_logins_reading(self):
        self.assertEqual(self.weekly(self.reading()), [10])
        one = self.status("acme")
        one(20, session=12.5)
        self.assertEqual(self.weekly(self.reading()), [10])
        one(42, session=12.5)
        reading = self.reading()
        self.assertEqual(self.weekly(reading), [42])
        two = self.status("brine")
        for render, week, session in ((one, 42, 12.5), (one, 42, None), (two, 20, None),
                                      (two, 20, None)):
            render(week, session)
            again = self.reading()
            self.assertEqual((self.weekly(again), again["probed_at"]), ([42], reading["probed_at"]))
        self.assertEqual(self.asked(), 1, "a probe was asked")


if __name__ == "__main__":
    unittest.main()
