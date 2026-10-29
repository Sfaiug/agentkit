"""The pages `c` opens come up and move as `c` does: `Models` opening is written a frame whose
header has `agentkit` and only part of `config · models` before the frame with all of it, and
Space on Weekly audit's `On` is written the half-way mark (`◉`) before the new one.

The owner's ask of 27 Oct 2026, every screen moving as the main menu does.  Black-box: the
program `AK_BIN` names, in a person's terminal (tests/fixtures/akterm.py) with its colours,
its harnesses the fakes of tests/fixtures/fakeadapter.py.  A frame is the first of its motion
whatever the host's load, so what the pane is written is read from tmux's `pipe-pane`, never
timed off a capture.  Fails against `/bin/false`.
"""

import re
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import SERVER, Terminal

NAME = " · config · models"
NOTE = "takes it in or out of the config"      # under the rows of `Models` alone
HEADER = re.compile(r"agentkit([^\x1b\n]*?) +\d\d:\d\d")    # each header written, its name


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class CPagesComeUp(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        fakeadapter.install(self.home, claude="pass", codex="pass")
        akconfig.write(self.home, {"fable": {"harness": "claude", "effort": "xhigh"},
                                   "astra": {"harness": "codex", "effort": "high"}})
        self.term = Terminal(self.home, size=(100, 30))
        self.term.wait("esc leave")
        self.raw = self.home.root / "raw"
        piped = self.home.tmux("pipe-pane", "-O", "-t", self.term.pane, f"cat >>{self.raw}",
                               server=SERVER)
        self.assertEqual(piped.code, 0, piped.err)
        self.term.keys("c", "j", "j")
        self.term.wait("› Models")

    def written(self, until, since=0):
        """What the pane was written from byte `since` once it holds `until`."""
        deadline = time.monotonic() + 30
        while True:
            out = (self.raw.read_bytes() if self.raw.exists() else b"")[since:].decode(
                "utf-8", "replace")
            if re.search(until, out, re.S):
                return out
            assert time.monotonic() < deadline, f"never written {until!r}; written:\n{out!r}"
            time.sleep(0.05)

    def test_models_comes_up_its_name_writing_itself_out(self):
        self.term.keys("Enter")
        # the page's first frame writes it top down: its header, then under its rows its note
        out = self.written(NOTE)
        opened = [found[1] for found in HEADER.finditer(out, 0, out.index(NOTE))][-1]
        self.assertNotEqual(opened, NAME)
        self.assertTrue(NAME.startswith(opened), opened)
        self.written(f"{NOTE}.*agentkit{NAME} ")      # and then all of it

    def test_space_on_audits_on_is_written_half_way_before_the_new_mark(self):
        self.term.keys("j", "j", "j", "Enter")
        self.term.wait(lambda screen: re.search(r"› On +○ off", screen))
        since = self.raw.stat().st_size
        self.term.keys("Space")
        self.written("◉.*●", since)


if __name__ == "__main__":
    unittest.main()
