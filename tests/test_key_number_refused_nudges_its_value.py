"""A number on `c` whose step was refused nudges where its value is drawn, and lands back on it:
beside its name, or on a narrow terminal under it.  What a frame writes stays until the next
full draw, so a nudge anywhere else leaves a second value on the screen.

Black-box: the program `AK_BIN` names, in a person's terminal (tests/fixtures/akterm.py) with its
colours, its harnesses the fakes of tests/fixtures/fakeadapter.py.  The nudge is over whatever the
host's load once tmux's `pipe-pane` holds its last frame, the value between a blank each, written
from a place of its own; a full draw writes a line from its start.  Fails against `/bin/false`.
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

MODELS = {"fable": {"harness": "claude", "effort": "xhigh"},
          "astra": {"harness": "codex", "effort": "high"}}
FAR = {"rounds": 6, "review_lines": 7, "seat_lines": 8}     # j presses from the first model
WIDE, NARROW = (100, 30), (40, 50)


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class RefusedNumber(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        fakeadapter.install(cls.home, claude="pass", codex="pass")

    def after_refusal(self, size, settings, name):
        """The terminal at `size` over `settings`, once Left on `name`, at its floor, has nudged."""
        akconfig.write(self.home, MODELS, settings=settings)
        term = Terminal(self.home, size=size)
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        term.wait("esc leave")
        term.keys("c")
        term.wait("r recommended")
        term.keys(*["j"] * FAR[name])
        term.wait(f"› {name}")
        raw = term.status.parent / "raw"
        piped = self.home.tmux("pipe-pane", "-O", "-t", term.pane, f"cat >>{raw}", server=SERVER)
        self.assertEqual(piped.code, 0, piped.err)
        last = re.compile(rf"\x1b\[\d+;\d+H(?:\x1b\[[\d;]*m)* {settings[name]} ".encode())
        deadline = time.monotonic() + 30
        while True:
            term.keys("Left")       # a host slower than the nudge draws none of it: again
            for _ in range(100):
                if raw.exists() and last.search(raw.read_bytes()):
                    return term
                time.sleep(0.05)
            self.assertLess(time.monotonic(), deadline, f"no nudge written:\n{term.screen()}")

    def assert_shows(self, term, *rows):
        """The pointed row reads `rows` from its first line down: nothing left over them.  Read
        at once, as the menu's next full draw wipes what a nudge left; the key line, drawn last,
        says no such draw is part way."""
        found = [line.rstrip() for line in term.wait("esc back").split("\n")]
        at = next(number for number, line in enumerate(found) if line.startswith("›"))
        self.assertEqual(found[at:at + len(rows)], list(rows))

    def test_a_value_beside_its_name(self):
        self.assert_shows(self.after_refusal(WIDE, {"seat_lines": 0}, "seat_lines"),
                          "› seat_lines    0    default 50          moves built")

    def test_a_value_beside_its_name_over_its_folded_boards(self):
        self.assert_shows(self.after_refusal(NARROW, {"seat_lines": 0}, "seat_lines"),
                          "› seat_lines    0    default 50", "    moves built")

    def test_a_value_under_its_name_in_each_row(self):
        for name, settings, value in (
                ("rounds", {"rounds": 1, "review_lines": 10000, "seat_lines": 0}, "1 default 3"),
                ("review_lines", {"rounds": 10000, "review_lines": 1, "seat_lines": 0},
                 "1 default 300"),
                ("seat_lines", {"review_lines": 10000, "seat_lines": 0}, "0 default 50")):
            with self.subTest(name=name):
                self.assert_shows(self.after_refusal(NARROW, settings, name),
                                  f"› {name}", f"    {value}")


if __name__ == "__main__":
    unittest.main()
