"""An expired login makes a seat `needs you`; a worker token only nearing its end changes no word.

A seat that cannot authenticate cannot move, and only the owner can log it back in, so its word
says so over whatever its screen shows, a turn or a question.  The tick asks each harness's
`auth` verb and asks `gh` about GitHub, and leaves what it found in ~/.agentkit/state/watch.json:
`auth_out` per harness, `gh_out` when it found gh logged out.  Every screen reads that record,
so these tests write it as the tick leaves it.  A worker token nearing its day, or a
subscription's login ending within the hour, is a line on the ak screen and never a word; one
already expired, like a logged-out gh, is every seat's `needs you`, on any harness.
Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, and
this test fails against `/bin/false`.
"""

import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat

TOKEN = "claude_oauth_token"     # the worker token claude's manifest declares, and its remedy
REMEDY = "run claude setup-token and replace ~/.agentkit/secrets/claude_oauth_token"
DAY = 86400


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class LoginWords(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        # a turn and a question are what a login has to outrank; codex has a login of its own
        Seat(cls.home, "acme")
        Seat(cls.home, "beta", screen="claude-working-pane.txt")
        Seat(cls.home, "delta", screen="claude-question-pane.txt")
        Seat(cls.home, "kappa", model="astra", screen="codex-prompt-pane.txt", composer="›")

    def tick_found(self, **found):
        """watch.json as a tick left it, holding only what this case's tick found."""
        self.home.write(".agentkit/state/watch.json", found)

    def worker_token(self, age_days):
        """The worker token file, dated `age_days` back, and the tick's daily record of it."""
        token = self.home.write(f".agentkit/secrets/{TOKEN}", "acme-token\n", ago=age_days * DAY)
        self.addCleanup(token.unlink)
        left, now = 365 - age_days, time.time()
        expired = left <= 0
        self.tick_found(worker_tokens={"claude": {
            "harness": "claude", "remedy": REMEDY, "at": now - 60 if expired else None,
            "checked_at": now - 60, "mtime": token.stat().st_mtime,
            "days": None if expired else left, "expired": expired,
            "why": "claude worker token " + ("expired" if expired else f"expires in {left} days")}})

    def why(self, name):
        """`ak orch why`'s first line and its reason."""
        done = self.home.ak("orch", "why", name)
        self.assertEqual(done.code, 0, done.err)
        lines = done.out.splitlines()
        reason = next(line for line in lines if line.startswith("  reason:"))
        return lines[0], reason.split(":", 1)[1].strip()

    def listed(self):
        """`ak orch list`'s row for each seat, by its name."""
        done = self.home.ak("orch", "list")
        self.assertEqual(done.code, 0, done.err)
        return {line.split()[0]: line for line in done.out.splitlines()[1:] if line.strip()}

    def test_an_expired_harness_login_needs_you_whatever_the_screen_shows(self):
        self.tick_found(auth_out={"claude": {"ok": False, "at": time.time() - 300,
                                             "why": "401"}})
        for name in ("acme", "beta", "delta"):
            with self.subTest(name):
                head, reason = self.why(name)
                self.assertEqual(head, f"{name}  needs you")
                self.assertIn("claude login expired", reason)
                self.assertIn("run /login", reason)    # claude's own remedy, from its manifest
        self.assertEqual(self.why("kappa")[0], "kappa  idle")    # codex's login is not claude's

    def test_only_a_login_recorded_as_refused_blocks_a_seat(self):
        self.tick_found(auth_out={"claude": {"ok": True, "at": time.time() - 300, "why": ""},
                                  "codex": {"ok": False, "at": time.time() - 300,
                                            "why": "401"}})
        self.assertEqual(self.why("acme"), ("acme  idle", "-"))
        head, reason = self.why("kappa")
        self.assertEqual(head, "kappa  needs you")
        self.assertIn("codex login expired", reason)
        self.assertIn("run codex login", reason)

    def test_a_logged_out_github_needs_you_on_every_seat(self):
        self.tick_found(gh_out={"at": time.time() - 300})
        # the record names no seat: a turn, a question and a seat with no run all read it
        rows = self.listed()
        for name in ("acme", "beta", "delta", "kappa"):
            with self.subTest(name):
                self.assertIn("! needs you", rows[name])
                self.assertEqual(self.why(name), (f"{name}  needs you", "GitHub is logged out: "
                                                  "run `gh auth login -p https -w`"))

    def test_a_worker_token_nearing_its_end_changes_no_word(self):
        self.worker_token(360)
        # ... nor does a subscription whose login ends within the hour
        now = time.time()
        self.home.write(".agentkit/state/logins.json",
                        {"anthropic": {"default": {"ends": now + 3600, "checked_at": now}}})
        self.addCleanup((self.home.path / ".agentkit/state/logins.json").unlink)
        rows = self.listed()
        for name in ("acme", "kappa"):
            with self.subTest(name):
                self.assertIn("○ idle", rows[name])
                self.assertEqual(self.why(name), (f"{name}  idle", "-"))

    def test_an_expired_worker_token_needs_you_on_every_harness(self):
        self.worker_token(366)
        rows = self.listed()
        for name in ("acme", "kappa"):
            with self.subTest(name):
                self.assertIn("! needs you", rows[name])
                head, reason = self.why(name)
                self.assertEqual(head, f"{name}  needs you")
                self.assertIn("claude worker token expired", reason)
                self.assertIn("run claude setup-token", reason)


if __name__ == "__main__":
    unittest.main()
