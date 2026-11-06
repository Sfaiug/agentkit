"""The done check sees each picture of a screen its seat kept with `ak orch look FILE`, as the
file was when kept: a screen the owner will see that the work changed and no kept picture shows
is a gap, and `ak plan` prints, beside it, how to keep one.

The owner asks for a chart; the seat's plan has every line done.  The model's turn names a gap
quoting that ask unless its workspace holds the seat's picture byte for byte, so the check finds
the gap until the seat keeps the chart, and none after, the file itself deleted.  A picture is
the seat's, as its plan is: it stays through a rename, a later one of the same file stands beside
it, and a seat renamed into a gone seat's name sees none of that seat's.  Black-box: the program `AK_BIN` names runs from outside through
tests/fixtures/akbin.py, on a Claude seat of tests/fixtures/akseat.py whose transcript the test
writes, with a fake harness of fakeadapter.py for the model.
"""

import json
import re
import shlex
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import AK, REAL_TMUX, Home
from fixtures.akseat import Seat

CONVERSATION = "9d4b2e71-3a6c-4f18-b5e0-7c1a8f2d6e93"
ASKED = "Add a chart of uploads per day to the dashboard."
PLANNED = "The dashboard has a chart of uploads per day"
CHART = b"\x89PNG\r\n\x1a\n" + bytes(range(256))     # every byte, so a copy is byte for byte


class DoneCheckSeesPictures(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        fake = fakeadapter.install(home, claude="pass")["claude"]
        akconfig.write(home, ["opus"], extra='[done_check]\nmodel = "opus"')
        self.seat = seat = Seat(home, "acme", alive=False, record={"conversation": CONVERSATION})
        folder = re.sub(r"[^A-Za-z0-9]", "-", str(seat.cwd))
        home.write(f".claude/projects/{folder}/{CONVERSATION}.jsonl", json.dumps({
            "type": "user", "timestamp": "2026-11-05T10:00:00Z",
            "message": {"role": "user", "content": ASKED}}) + "\n")
        home.write(".agentkit/state/plan-acme.md", f"- [x] {PLANNED} · check: `true` · acme · "
                                                   "written 2026-11-05 10:05 · done 0123456789ab\n")
        shown = fake.dir / "shown.png"      # the chart as the seat kept it, where the turn reads
        shown.write_bytes(CHART)
        fake.behave({"sh": f"find . -type f -exec cmp -s {{}} {shlex.quote(str(shown))} \\; "
                           f"-print | grep -q . || {shlex.quote(AK)} hand-in finding "
                           f"\"$(grep -rlF -- {shlex.quote(ASKED)} . | head -n 1):1\" "
                           f"'no picture shows the chart' 'the owner will see it' "
                           f"--quote {shlex.quote(ASKED)}",
                     "final": "Checked.", "hand_in": [["done"]]})

    def look(self, data, seat="acme"):
        """The seat keeps chart.png holding `data`, then deletes it."""
        chart = self.seat.cwd / "chart.png"
        chart.write_bytes(data)
        done = self.home.ak("orch", "look", "chart.png", env={"AGENTKIT_SESSION": seat},
                            cwd=self.seat.cwd)
        self.assertEqual(done.code, 0, done.out + done.err)
        chart.unlink()

    def test_the_check_finds_the_screen_until_the_seat_keeps_a_picture_of_it(self):
        done = self.home.ak("plan", env={"AGENTKIT_SESSION": "acme"})
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertIn(ASKED, done.out)
        self.assertIn("ak orch look", done.out)
        self.look(CHART)
        done = self.home.ak("orch", "check", "acme")
        self.assertEqual(done.code, 0, done.out + done.err)

    @unittest.skipUnless(REAL_TMUX, "no tmux installed")
    def test_a_picture_stays_through_a_rename_beside_a_later_one_of_the_same_file(self):
        self.seat.start()       # only a running seat is renamed
        self.look(CHART)
        self.look(b"a later chart")
        renamed = self.home.ak("orch", "rename", "acme", "quay")
        self.assertEqual(renamed.code, 0, renamed.out + renamed.err)
        done = self.home.ak("orch", "check", "quay")
        self.assertEqual(done.code, 0, done.out + done.err)

    @unittest.skipUnless(REAL_TMUX, "no tmux installed")
    def test_a_seat_renamed_into_a_gone_seat_s_name_sees_none_of_its_pictures(self):
        Seat(self.home, "quay", alive=False)
        self.look(CHART, seat="quay")
        (self.home.path / ".agentkit/state/session-quay.json").unlink()     # quay is gone
        self.seat.start()
        renamed = self.home.ak("orch", "rename", "acme", "quay")
        self.assertEqual(renamed.code, 0, renamed.out + renamed.err)
        done = self.home.ak("orch", "check", "quay")
        self.assertEqual(done.code, 1, done.out + done.err)
        self.assertIn(ASKED, done.out)


if __name__ == "__main__":
    unittest.main()
