"""A line ak's editor puts in that the screen never draws gets no Enter, and the tick says so.

Text left standing in a seat launched with ak's editor goes aside for ak's line, which goes in
through that editor; its Enter waits for the composer to read as the line alone.  A screen that
never draws it looked, in the log, like nothing happened at all.  Black-box: `AK_BIN` runs
`ak watch` (tests/fixtures/akbin.py) beside a seat (tests/fixtures/akseat.py) owed a line,
launched with ak's editor as its $VISUAL, showing a capture of a real Claude Code with text in
its composer and drawing nothing typed into it.  The whole file runs in one box (`rerun_boxed`):
a tick boxed apart could not read the pane's environment.
"""

import os
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import BOXED, REAL_TMUX, REPO, Home, rerun_boxed
from fixtures.akseat import Seat

LINE = "run 20261126-0900-fix-api ended PASS, merged as https://github.com/acme/api/pull/42."
SAID = f"WARN acme: its composer does not read as the line typed, so no Enter: {LINE[:60]}"


@unittest.skipUnless(BOXED and REAL_TMUX, "no tmux, or no bwrap able to box the test here")
class ALineItsEditorPutInUnseen(unittest.TestCase):
    def test_a_tick_puts_the_line_in_through_the_editor_and_no_enter_and_says_so(self):
        home = Home()
        self.addCleanup(home.close)
        home.env["VISUAL"] = str(REPO / "tools" / "aside-editor")    # the seat's, from its server
        seat = Seat(home, "acme", screen="claude-draft-pane.txt", composer="drawn nowhere",
                    editor=True)
        home.write(".agentkit/state/seat-acme.json", {"owed_lines": [{"id": "1", "line": LINE}]})
        # a terminal the owner has left: only then is their text set aside for a line
        tty = home.tmux("display-message", "-p", "-t", seat.pane, "#{pane_tty}").out.strip()
        os.utime(tty, (time.time() - 600, time.time() - 600))
        done = home.ak("watch")
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertEqual(seat.typed(), "\x07")      # the editor's key, and no Enter
        self.assertEqual([row for row in done.out.splitlines() if "no Enter" in row], [SAID])


if __name__ == "__main__":
    rerun_boxed()
    unittest.main()
