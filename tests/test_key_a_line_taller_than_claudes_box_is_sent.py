"""A line taller than Claude Code's input box is read there, and gets its Enter.

Claude Code 2.1.331 shows a draft taller than its box as the box's last rows under a top rule
counting the rows above (`─── ↑ 5 more ───…─── name ─`), and draws no prompt row.  On 25 Nov
2026 six seats each held a job's ending ak had typed there, read as no composer at all: it never
got its Enter, every later ending waited behind it, and the seats stayed on their spent logins.
The capture is one of those seats, its words invented.  It reads as the line's unsent text: a
tick gives the line typed there its Enter and no other key, gives a seat no ending waits on no
key, and moves no seat over it to a login with room.  Black-box: `AK_BIN` runs from outside
(tests/fixtures/akbin.py) beside a seat (tests/fixtures/akseat.py) showing the capture, and this
test fails against `/bin/false`.
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

SCREEN = "claude-scrolled-rule-line-pane.txt"
CONVERSATION = "0b9c6f4e-1d2a-4c3b-8e5f-6a7b8c9d0e1f"
AGAIN = " and the reviewer of round two asks for the same file again, which the build cannot write" \
        " there either;"
# the line ak typed there, 771 characters, 12 rows of the pane
LINE = ("job 20261006-153400-fix-api: fix-api.md: BLOCKED: the done-when command reads"
        " fixtures/api.json, which the task never names, so no change can make it pass;"
        + AGAIN * 5 + " and the reviewer… Result: ~/.agentkit/jobs/20261006-153400-fix-api/"
        "ending.txt. Decide the next step.")
# what of it the capture's box shows: its last 7 rows, from its second "cannot write" on
SHOWN = LINE[LINE.index("cannot write", LINE.index("cannot write") + 1):]


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class ALineTallerThanClaudesBoxIsSent(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        with socket.socket() as probe:     # a port nobody listens on: the tick reaches no board
            probe.bind(("127.0.0.1", 0))
            dead = f"http://127.0.0.1:{probe.getsockname()[1]}"
        home.env.update(https_proxy=dead, HTTPS_PROXY=dead, GIT_ALLOW_PROTOCOL="file")
        akconfig.write(home, ["opus"], providers={"anthropic": {"accounts": ["default", "second"]}})
        self.seat = seat = Seat(home, "acme", screen=SCREEN,
                                record={"conversation": CONVERSATION, "account": "default"})
        home.write(f".claude/projects/{re.sub(r'[^A-Za-z0-9]', '-', str(seat.cwd))}/"
                   f"{CONVERSATION}.jsonl", '{"type":"user","message":{"role":"user"}}\n')
        fakeadapter.install(home, claude="pass")["claude"].answer("interactive", shlex.join(
            [sys.executable, str(PANE), str(seat.screen_file), str(seat.typed_file)]))
        self.harness = self.pane("#{pane_pid}")

    def pane(self, field):
        return self.home.tmux("display-message", "-p", "-t", self.seat.pane, field).out.strip()

    def tick(self, used=10):
        """One tick, the seat's login `used`% into its 5h window and the other's at 10%, its
        terminal untouched: the login the seat is on after, and whether it runs the harness it
        had."""
        now = time.time()

        def reading(used):
            return {"provider": "anthropic", "resets": 0, "meters": [{
                "name": "session", "used": used, "window_secs": 18000, "resets_at": now + 10800}]}
        self.home.write(".agentkit/state/usage.json", {
            "fetched_at": now, "reset_checked_at": now, "providers": {"anthropic": {
                **reading(used), "accounts": {"default": reading(used), "second": reading(10)}}}})
        os.utime(self.pane("#{pane_tty}"), (now - 600, now - 600))
        done = self.home.ak("watch", boxed=True)
        self.assertEqual(done.code, 0, done.out + done.err)
        record = json.loads((self.home.path / ".agentkit/state/session-acme.json").read_text())
        return record.get("account"), self.pane("#{pane_pid}") == self.harness

    def test_the_seat_reads_as_holding_the_rows_its_box_shows(self):
        done = self.home.ak("orch", "why", "acme")
        self.assertEqual(done.code, 0, done.err)
        data = json.loads((self.home.path / ".agentkit/state/seat-acme.json").read_text())
        self.assertEqual((data.get("state"), data.get("rule"), data.get("unsent")),
                         ("draft", "prompt.draft", SHOWN[:160].rstrip()))

    def test_the_ending_typed_there_gets_its_enter_and_no_other_key(self):
        self.home.write(".agentkit/jobs/20261006-153400-fix-api/job.json", {
            "job_id": "20261006-153400-fix-api", "seat": "acme", "finished_at": time.time() - 60,
            "tasks": [], "handback_pending": LINE, "handback_typed": self.seat.mark(LINE)})
        self.assertEqual(self.tick(), ("default", True))
        self.assertEqual(self.seat.typed(), "\r")

    def test_with_no_ending_waiting_the_seat_gets_no_key(self):
        self.assertEqual(self.tick(), ("default", True))
        self.assertEqual(self.seat.typed(), "")

    def test_a_spent_login_is_not_left_by_a_respawn_over_the_line(self):
        self.assertEqual(self.tick(100), ("default", True))
        self.assertEqual(self.seat.typed(), "")


if __name__ == "__main__":
    unittest.main()
