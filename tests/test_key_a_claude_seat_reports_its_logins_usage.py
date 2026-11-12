"""A Claude seat's status render is its login's usage reading, at once and with no ask.

ak asks Anthropic's usage endpoint about a login at most every fifteen minutes; every status
render of a seat on that login carries the numbers the API last reported to it (Claude Code
2.1.322's `rate_limits`).  A render carrying other numbers than its conversation's last is that
login's reading of `session` and `weekly_all` from then on, with no ask: `ak usage --json` holds
it.  A render carrying the same numbers again changes nothing, not the reading's time either.

Black-box against AK_BIN: a Home whose Claude provider lists a second login, read once through a
fake `curl` standing in for the endpoint, which counts each ask; then a seat on that login
(tests/fixtures/akseat.py), its status command as `ak orch --dry-run` prints it, run as Claude
Code runs it: in a shell, in the environment the seat's line sets, the render's JSON on stdin.
Each render is waited out with everything it started.  This test fails against `/bin/false`.
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
        try:
            return len(self.asks.read_text().splitlines())
        except FileNotFoundError:
            return 0

    def reading(self):
        """The second login's reading as `ak usage --json` shows it."""
        done = self.home.ak("usage", "--json")
        self.assertEqual(done.code, 0, done.out + done.err)
        return json.loads(done.out)["providers"]["anthropic"]["accounts"][LOGIN]

    def weekly(self, reading):
        return [meter["used"] for meter in reading["meters"] if meter["name"] == "weekly_all"]

    def render(self, command, env, cwd, payload):
        """Run the status command on `payload` and wait until it, and all it started, ended."""
        end, held = os.pipe()
        try:
            done = self.home.run("sh", "-c", command, input=json.dumps(payload), env=env,
                                 cwd=cwd, keep=(held,))
        finally:
            os.close(held)
        with os.fdopen(end, "rb") as drained:
            drained.read()
        self.assertEqual(done.code, 0, done.err)

    def test_a_render_is_its_logins_reading_and_the_same_render_again_changes_nothing(self):
        self.assertEqual(self.weekly(self.reading()), [10])
        self.assertEqual(self.asked(), 1)
        seat = Seat(self.home, "acme", alive=False, record={"account": LOGIN})
        done = self.home.ak("orch", seat.name, "--dry-run", cwd=self.home.path)
        self.assertEqual(done.code, 0, done.out + done.err)
        words = shlex.split(done.out.splitlines()[-1])
        command = json.loads(words[words.index("--settings") + 1])["statusLine"]["command"]
        env = {**seat_env(words), "AGENTKIT_SESSION": seat.name}
        self.assertEqual(env.get("AGENTKIT_ACCOUNT"), LOGIN, words)
        now = int(time.time())
        payload = {"session_id": seat.record["conversation"],
                   "model": {"id": "claude-opus-5-5"}, "effort": {"level": "high"},
                   "rate_limits": {"five_hour": {"used_percentage": 12.5, "resets_at": now + 3600},
                                   "seven_day": {"used_percentage": 42, "resets_at": now + WEEK - 60}}}
        self.render(command, env, seat.cwd, payload)
        reading = self.reading()
        self.assertEqual(self.weekly(reading), [42])
        self.assertEqual(self.asked(), 1, "a probe was asked")
        self.render(command, env, seat.cwd, payload)
        again = self.reading()
        self.assertEqual(self.weekly(again), [42])
        self.assertEqual(again["probed_at"], reading["probed_at"])
        self.assertEqual(self.asked(), 1, "a probe was asked")


if __name__ == "__main__":
    unittest.main()
