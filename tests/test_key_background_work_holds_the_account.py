"""A seat holding background work leaves its account only once it is spent, and is told to pick
the work up.

A move between turns respawns the seat's harness, which ends everything it runs in the
background: a monitor or a shell is no wait for its Stop, yet cutting it off left seats idle for
an hour.  So a seat whose Stop listed work in flight stays on an account with usage left, however
low, until it is spent; then it moves, and the line it reopens on names that work.  A harness whose
Stop lists no background work moves as before (owner, 24 Oct 2026).  Black-box: the program
`AK_BIN` names runs `ak watch` from outside through tests/fixtures/akbin.py, beside a seat of
tests/fixtures/akseat.py whose Stop is fired as its harness fires it (tests/fixtures/hookdrive.py),
on fake harnesses of fakeadapter.py and the usage readings the test writes.
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
from fixtures.hookdrive import Hooks

PROXIES = ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")
TWO = {"accounts": ["default", "second"]}
CONVERSATION = "0b9c6f4e-1d2a-4c3b-8e5f-6a7b8c9d0e1f"
MONITOR = {"id": "bg1", "type": "monitor", "status": "running", "description": "watch ci"}
SHELL = {"id": "bg2", "type": "shell", "status": "running", "description": "sleep 600"}


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class BackgroundWorkHoldsTheAccount(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        with socket.socket() as probe:     # a port nobody listens on: the tick reaches no board
            probe.bind(("127.0.0.1", 0))
            home.env.update(dict.fromkeys(PROXIES, f"http://127.0.0.1:{probe.getsockname()[1]}"),
                            GIT_ALLOW_PROTOCOL="file")
        akconfig.write(home, ["opus", "gemini"], providers={"anthropic": TWO, "google": TWO})
        self.fakes = fakeadapter.install(home, claude="pass", antigravity="pass")

    def seat(self, harness="claude", model="opus"):
        """A seat on its provider's first account, at its prompt, reopened as itself."""
        seat = Seat(self.home, "acme", model=model, screen=f"{harness}-prompt-pane.txt",
                    record={"conversation": CONVERSATION, "account": "default"})
        folder = re.sub(r"[^A-Za-z0-9]", "-", str(seat.cwd))
        self.home.write(f".claude/projects/{folder}/{CONVERSATION}.jsonl",
                        '{"type":"user","message":{"role":"user","content":"hello"}}\n')
        self.fakes[harness].answer("interactive", shlex.join(
            [sys.executable, str(PANE), str(seat.screen_file), str(seat.typed_file)]))
        return seat

    def stop(self, seat, *tasks):
        """Its turn ends, Claude's Stop listing the background work still in flight."""
        hooks = Hooks(self.home)
        fired = hooks.fire("Stop", {"background_tasks": list(tasks), "transcript_path": "",
                                    "last_assistant_message": "Started it."},
                           seat="acme", pane=seat)
        self.assertEqual(fired.code, 0, fired)

    def tick(self, seat, provider, used):
        """One tick with the seat's first account `used`% into its 5h window and the other at
        10%, its terminal untouched for ten minutes: the account it is on after, and the first
        prompt each relaunch handed its harness."""
        now = time.time()

        def reading(used):
            return {"provider": provider, "resets": 0, "meters": [
                {"name": "session", "used": used, "window_secs": 18000, "resets_at": now + 10800},
                {"name": "weekly_all", "used": 30, "window_secs": 604800,
                 "resets_at": now + 3 * 86400}]}
        # the readings of a moment ago, which a tick reads again only once they are stale
        self.home.write(".agentkit/state/usage.json", {
            "fetched_at": now, "reset_checked_at": now, "providers": {
                name: {**reading(used), "accounts": {"default": reading(used),
                                                    "second": reading(10)}}
                if name == provider else {"resets": 0, "meters": []}
                for name in ("anthropic", "google")}})
        tty = self.home.tmux("display-message", "-p", "-t", seat.pane, "#{pane_tty}").out.strip()
        os.utime(tty, (now - 600, now - 600))
        done = self.home.ak("watch", boxed=True)
        self.assertEqual(done.code, 0, done.out + done.err)
        record = json.loads((self.home.path / ".agentkit/state/session-acme.json").read_text())
        return record.get("account"), [call["env"].get("AGENTKIT_FIRST_PROMPT") or None
                                       for fake in self.fakes.values()
                                       for call in fake.calls("interactive")]

    def held_then_let_go(self, work):
        seat = self.seat()
        self.stop(seat, work)
        for event in ("PreCompact", "PostCompact"):     # a compaction ends no background work
            self.assertEqual(Hooks(self.home).fire(event, {"trigger": "manual"}, seat="acme",
                                                   pane=seat).code, 0)
        self.assertEqual(self.tick(seat, "anthropic", 97), ("default", []))
        self.stop(seat)
        self.assertEqual(self.tick(seat, "anthropic", 97), ("second", [None]))

    def test_a_low_account_keeps_a_seat_holding_a_monitor_until_it_holds_none(self):
        self.held_then_let_go(MONITOR)

    def test_a_low_account_keeps_a_seat_holding_a_shell_until_it_holds_none(self):
        self.held_then_let_go(SHELL)

    def test_a_spent_account_moves_it_and_the_line_it_is_given_names_its_work(self):
        seat = self.seat()
        self.stop(seat, MONITOR, SHELL)
        account, (line,) = self.tick(seat, "anthropic", 100)
        self.assertEqual(account, "second")
        self.assertIn("background work: monitor, shell", line)

    def test_a_harness_whose_stop_lists_no_background_work_moves_as_before(self):
        seat = self.seat("antigravity", "gemini")
        self.assertEqual(self.tick(seat, "google", 97), ("second", [None]))


if __name__ == "__main__":
    unittest.main()
