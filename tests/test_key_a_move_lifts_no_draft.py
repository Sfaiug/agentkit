"""A subscription move types nothing into a seat holding text, even one ak's editor could lift.

The tick moved a seat off a spent account at once where its pane was launched with ak's editor:
it pressed the editor's keys to lift the owner's text, respawned the harness, and pasted the text
back much later, mid-turn.  Black-box: `AK_BIN` runs `ak watch` (tests/fixtures/akbin.py) beside
a seat (tests/fixtures/akseat.py) launched with ak's editor as its $VISUAL, showing captures of a
real Claude Code, on a fake harness (fakeadapter.py) and usage the test writes.  The whole file
runs in one box (`rerun_boxed`): a tick boxed apart could not read the pane's environment.
"""

import json
import os
import re
import shlex
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import BOXED, REAL_TMUX, REPO, Home, rerun_boxed
from fixtures.akseat import PANE, Seat

CONVERSATION = "0b9c6f4e-1d2a-4c3b-8e5f-6a7b8c9d0e1f"


# "Swithich providers, models, accounts, always the input in the text field must be preserved."
# [12 Nov 2026]
@unittest.skipUnless(BOXED and REAL_TMUX, "no tmux, or no bwrap able to box the test here")
class AMoveLiftsNoDraft(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        home.env["VISUAL"] = str(REPO / "tools" / "aside-editor")    # the seat's, from its server
        akconfig.write(home, ["opus"], providers={"anthropic": {"accounts": ["default", "second"]}})
        self.seat = seat = Seat(home, "acme", screen="claude-draft-pane.txt",
                                record={"conversation": CONVERSATION, "account": "default"})
        home.write(f".claude/projects/{re.sub(r'[^A-Za-z0-9]', '-', str(seat.cwd))}/"
                   f"{CONVERSATION}.jsonl", '{"type":"user","message":{"role":"user"}}\n')
        fakeadapter.install(home, claude="pass")["claude"].answer("interactive", shlex.join(
            [sys.executable, str(PANE), str(seat.screen_file), str(seat.typed_file)]))

    def tick(self):
        """One tick, the seat's account spent and the other's at 10%, its terminal untouched: the
        account the seat is on after."""
        now = time.time()

        def reading(used):
            return {"provider": "anthropic", "resets": 0, "meters": [{
                "name": "session", "used": used, "window_secs": 18000, "resets_at": now + 10800}]}
        self.home.write(".agentkit/state/usage.json", {
            "fetched_at": now, "reset_checked_at": now, "providers": {"anthropic": {
                **reading(100), "accounts": {"default": reading(100), "second": reading(10)}}}})
        tty = self.home.tmux("display-message", "-p", "-t", self.seat.pane, "#{pane_tty}").out
        os.utime(tty.strip(), (now - 600, now - 600))
        done = self.home.ak("watch")
        self.assertEqual(done.code, 0, done.out + done.err)
        return json.loads((self.home.path / ".agentkit/state/session-acme.json").read_text())[
            "account"]

    def test_a_spent_account_moves_the_seat_only_once_its_input_field_is_empty(self):
        self.assertEqual((self.tick(), self.seat.typed()), ("default", ""))
        self.seat.show("claude-prompt-pane.txt")
        self.assertEqual(self.tick(), "second")


if __name__ == "__main__":
    rerun_boxed()
    unittest.main()
