"""No line is typed into a composer ak cannot read whole; one read empty takes it.

Claude Code scrolls a long draft inside its box, and ak cannot read that screen whole -- nor
with its top above the capture, nor without its key-hint row.  A line typed there would join
the owner's unsent text, and its Enter would send both.  So a tick telling a seat its run is
parked as stalled sends the line as the seat's `needs` card there, once, and types it only into
a composer read empty; either way the run's record says it was told.  Black-box: the program
`AK_BIN` names runs from outside through tests/fixtures/akbin.py, each tick in the box
`home.tick()` builds, before a seat of tests/fixtures/akseat.py showing a captured Claude Code
screen, and this test fails against `/bin/false`.
"""

import json
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akseat import FIXTURES, Seat

RUN = "20261105-fix-api"
RESUME = f"ak run resume {RUN}"
SCROLLED = (FIXTURES / "claude-scrolled-draft-pane.txt").read_text(encoding="utf-8").splitlines()
# a cut screen is given as its text, so its pane is as tall as its rows
UNREAD = {"as captured": "claude-scrolled-draft-pane.txt",
          "its bottom twelve rows": "\n".join(SCROLLED[-12:]),
          "without its last row": "\n".join(SCROLLED[:-1])}


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class NoLineIntoAComposerReadInPart(unittest.TestCase):
    def parked(self, screen):
        """A Home whose seat `acme`, on Claude Code and showing `screen`, launched RUN two days
        ago, since parked as stalled at review with nobody told."""
        home = Home()
        self.addCleanup(home.close)
        home.write(f".agentkit/runs/{RUN}/run.json", {
            "run_id": RUN, "title": f"Task {RUN}", "launched_session": "acme",
            "started_at": time.time() - 2 * 86400, "state": "stalled",
            "stalls": [{"step": "review"}], "finished_at": None, "stalled_notified": False,
            "error": f"stalled three times at review; parked: {RESUME}"})
        return home, Seat(home, "acme", model="opus", screen=screen)

    def tick(self, home):
        done = home.tick()
        self.assertEqual(done.code, 0, done.out + done.err)
        record = json.loads((home.path / f".agentkit/runs/{RUN}/run.json").read_text())
        self.assertIs(record.get("stalled_notified"), True)
        notice = home.path / ".agentkit/state/notify-acme.json"
        return json.loads(notice.read_text()) if notice.is_file() else {}

    def test_a_composer_read_in_part_gets_no_keys_and_an_empty_one_takes_the_line(self):
        for kind, screen in UNREAD.items():
            with self.subTest(kind=kind):
                home, seat = self.parked(screen)
                notice = self.tick(home)
                self.assertEqual(notice.get("kind"), "needs")
                self.assertIn(RESUME, notice.get("text", ""))
                self.assertEqual(self.tick(home), notice)      # no second card
                self.assertEqual(seat.typed(), "")
        home, seat = self.parked("claude-prompt-pane.txt")
        self.assertNotIn(RESUME, self.tick(home).get("text", ""))
        line, = seat.wait_lines(1)
        self.assertIn(RESUME, line)


if __name__ == "__main__":
    unittest.main(verbosity=2)
