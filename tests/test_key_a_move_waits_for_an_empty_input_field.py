"""A subscription move never restarts a seat over text in its input field.

The tick moves a seat to another subscription by respawning its harness, between turns when its
account runs low and at once when it is spent; the respawn ends whatever the input field holds.
Claude Code 2.1.318 draws a draft of ten rows as an empty prompt, and one of seventeen scrolled
past its rows, so the move waits until the field, read whole, is empty.  Black-box: the program
`AK_BIN` names runs `ak watch` from outside through tests/fixtures/akbin.py, beside a seat of
tests/fixtures/akseat.py showing captures of a real Claude Code, on a fake harness of
fakeadapter.py and the usage readings the test writes.
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
CONVERSATION = "0b9c6f4e-1d2a-4c3b-8e5f-6a7b8c9d0e1f"
DRAFTS = ("claude-ten-row-draft-pane.txt", "claude-scrolled-draft-pane.txt")


# A move waits for an empty input field: "the text in the input field should never be deleted".
# [5 Nov 2026]
@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class AMoveWaitsForAnEmptyInputField(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        with socket.socket() as probe:     # a port nobody listens on: the tick reaches no board
            probe.bind(("127.0.0.1", 0))
            home.env.update(dict.fromkeys(PROXIES, f"http://127.0.0.1:{probe.getsockname()[1]}"),
                            GIT_ALLOW_PROTOCOL="file")
        akconfig.write(home, ["opus"], providers={"anthropic": {"accounts": ["default", "second"]}})
        fake = fakeadapter.install(home, claude="pass")["claude"]
        self.seat = Seat(self.home, "acme", screen=DRAFTS[0],
                         record={"conversation": CONVERSATION, "account": "default"})
        folder = re.sub(r"[^A-Za-z0-9]", "-", str(self.seat.cwd))
        self.home.write(f".claude/projects/{folder}/{CONVERSATION}.jsonl",
                        '{"type":"user","message":{"role":"user","content":"hello"}}\n')
        fake.answer("interactive", shlex.join(
            [sys.executable, str(PANE), str(self.seat.screen_file), str(self.seat.typed_file)]))
        self.harness = self.pane("#{pane_pid}")

    def pane(self, field):
        return self.home.tmux("display-message", "-p", "-t", self.seat.pane, field).out.strip()

    def tick(self, used):
        """One tick with the seat's account `used`% into its 5h window and the other at 10%, its
        terminal untouched for ten minutes: the account it is on after, and whether its harness
        is the one it had."""
        now = time.time()

        def reading(used):
            return {"provider": "anthropic", "resets": 0, "meters": [
                {"name": "session", "used": used, "window_secs": 18000, "resets_at": now + 10800},
                {"name": "weekly_all", "used": 30, "window_secs": 604800,
                 "resets_at": now + 3 * 86400}]}
        self.home.write(".agentkit/state/usage.json", {
            "fetched_at": now, "reset_checked_at": now, "providers": {"anthropic": {
                **reading(used), "accounts": {"default": reading(used), "second": reading(10)}}}})
        os.utime(self.pane("#{pane_tty}"), (now - 600, now - 600))
        done = self.home.ak("watch", boxed=True)
        self.assertEqual(done.code, 0, done.out + done.err)
        record = json.loads((self.home.path / ".agentkit/state/session-acme.json").read_text())
        return record.get("account"), self.pane("#{pane_pid}") == self.harness

    def waits_then_moves(self, used):
        for screen in DRAFTS:
            with self.subTest(screen=screen):
                self.seat.show(screen)
                self.assertEqual(self.tick(used), ("default", True))
                self.assertEqual(self.seat.typed(), "")
        self.seat.show("claude-prompt-pane.txt")
        self.assertEqual(self.tick(used), ("second", False))

    def test_a_low_account_moves_the_seat_once_its_input_field_is_empty(self):
        self.waits_then_moves(97)

    def test_a_spent_account_moves_the_seat_once_its_input_field_is_empty(self):
        self.waits_then_moves(100)


if __name__ == "__main__":
    unittest.main()
