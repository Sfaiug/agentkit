"""A completed seat still comes home between turns, and never waits for usage it needs
nothing from.

A seat whose plan is finished has nothing a subscription would continue, so a spent account
never makes it `out of usage` (owner, 2 Nov 2026).  That says nothing about where it sits:
an idle seat on its provider's second account comes home once its home account has a window
again, as every seat between turns does, and the move starts no turn.  Black-box: the program
`AK_BIN` names runs `ak watch` from outside through tests/fixtures/akbin.py, beside a seat of
tests/fixtures/akseat.py, on fake harnesses of fakeadapter.py and the usage readings the test
writes.
"""

import json
import os
import re
import shlex
import socket
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akseat import PANE, Seat

PROXIES = ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")
TWO = {"accounts": ["default", "second"]}
CONVERSATION = "3f7a2c91-8b4d-4e6a-9c1f-5d2e7a0b6c84"


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class DoneSeatComesHome(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        with socket.socket() as probe:     # a port nobody listens on: the tick reaches no board
            probe.bind(("127.0.0.1", 0))
            home.env.update(dict.fromkeys(PROXIES, f"http://127.0.0.1:{probe.getsockname()[1]}"),
                            GIT_ALLOW_PROTOCOL="file")
        akconfig.write(home, ["opus"], providers={"anthropic": TWO})
        self.fakes = fakeadapter.install(home, claude="pass")

    def seat(self):
        """A seat left on the second account, its plan finished, at its prompt."""
        seat = Seat(self.home, "acme", record={
            "conversation": CONVERSATION, "account": "second", "home_account": "default"})
        folder = re.sub(r"[^A-Za-z0-9]", "-", str(seat.cwd))
        self.home.write(f".claude/projects/{folder}/{CONVERSATION}.jsonl",
                        '{"type":"user","message":{"role":"user","content":"hello"}}\n')
        self.fakes["claude"].answer("interactive", shlex.join(
            [sys.executable, str(PANE), str(seat.screen_file), str(seat.typed_file)]))
        self.home.write(".agentkit/state/plan-acme.md", "- [x] Shipped it\n")
        return seat

    def tick(self, seat, used):
        """One tick with each account `used[account]`% into its windows, the seat's terminal
        untouched for ten minutes: the account it is on after, and the first prompt each
        relaunch handed its harness."""
        now = time.time()

        def reading(used):
            return {"provider": "anthropic", "resets": 0, "meters": [
                {"name": "session", "used": used, "window_secs": 18000,
                 "resets_at": now + 10800},
                {"name": "weekly_all", "used": used, "window_secs": 604800,
                 "resets_at": now + 3 * 86400}]}
        # the readings of a moment ago, which a tick reads again only once they are stale
        self.home.write(".agentkit/state/usage.json", {
            "fetched_at": now, "reset_checked_at": now, "providers": {
                "anthropic": {**reading(used["second"]),
                              "accounts": {"default": reading(used["default"]),
                                           "second": reading(used["second"])}}}})
        tty = self.home.tmux("display-message", "-p", "-t", seat.pane, "#{pane_tty}").out.strip()
        os.utime(tty, (now - 600, now - 600))
        done = self.home.ak("watch", boxed=True)
        self.assertEqual(done.code, 0, done.out + done.err)
        record = json.loads((self.home.path / ".agentkit/state/session-acme.json").read_text())
        return record.get("account"), [call["env"].get("AGENTKIT_FIRST_PROMPT") or None
                                        for fake in self.fakes.values()
                                        for call in fake.calls("interactive")]

    def word(self):
        why = self.home.ak("orch", "why", "acme")
        self.assertEqual(why.code, 0, why.err)
        return why.out.splitlines()[0].split(None, 1)[1]

    def waiting(self):
        try:
            live = json.loads((self.home.path / ".agentkit/state/seat-acme.json").read_text())
        except (FileNotFoundError, ValueError):
            live = {}
        return live.get("usage_wait")

    def test_a_done_seat_comes_home_once_home_has_a_window_starting_no_turn(self):
        seat = self.seat()
        self.assertEqual(self.tick(seat, {"default": 10, "second": 10}), ("default", [None]))
        self.assertEqual(seat.lines(), [])
        self.assertEqual(self.word(), "done")
        self.assertIsNone(self.waiting())

    def test_a_done_seat_on_spent_accounts_waits_for_nothing_and_stays_done(self):
        seat = self.seat()
        self.assertEqual(self.tick(seat, {"default": 100, "second": 100}), ("second", []))
        self.assertEqual(seat.lines(), [])
        self.assertEqual(self.word(), "done")
        self.assertIsNone(self.waiting())


if __name__ == "__main__":
    unittest.main()
