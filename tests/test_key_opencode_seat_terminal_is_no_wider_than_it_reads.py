"""A seat's OpenCode sees a terminal no wider than 120 columns, where it draws no sidebar.

A seat nobody is attached to is 240 columns wide
(tests/test_key_a_seat_nobody_is_attached_to_is_wide.py), and in a terminal wider than 120
OpenCode 2.4.2 draws a sidebar once a conversation has a turn: a screen no rule of its manifest
reads, so ak types no line into that seat again.  The wrapper on the seat's line therefore
tells its OpenCode a terminal of the window's rows and no more than 120 of its columns.

Black-box, as tests/test_key_seat_relay.py: the adapter beside the program `AK_BIN` names (or
`AK_ROOT`'s) prints the line, and it runs as printed, its wrapper included, a terminal of the
window's size on its stdin and a fake `opencode` first on PATH that prints the size of its own.
No tmux: outside a seat's pane the wrapper names nothing and looks at nothing.  This test fails
against `/bin/false`.
"""

from pathlib import Path
import shlex
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home
from fixtures.hookdrive import ROOT

# Prints its terminal's rows and columns once a wrapper has given it a size: 0 0 is none yet.
FAKE = '#!/bin/sh\nwhile [ "$(stty size)" = "0 0" ]; do sleep 0.05; done\nstty size\n'
# Makes the terminal on its stdin the size of a seat's window while nobody is attached, and runs
# the words after it there.
WINDOW = 'stty rows 50 columns 240 && exec "$@"'


class AnOpenCodeSeatsTerminal(unittest.TestCase):
    def test_a_window_240_columns_wide_is_120_to_the_seat_s_opencode(self):
        with Home() as home:
            home.fake("opencode", FAKE)
            # the seat's rulebook, as `orch.command` names it to the adapter
            rules = {"AGENTKIT_RULEBOOK": str(home.write("rb.md", "rb\n"))}
            printed = home.run("bash", str(ROOT / "adapters" / "opencode.sh"), "interactive",
                               "acme/flash", "high", env=rules)
            self.assertEqual(printed.code, 0, printed.err)
            seat = home.run("sh", "-c", WINDOW, "sh", *shlex.split(printed.out), tty=True)
            self.assertEqual((seat.code, seat.out.split()), (0, ["50", "120"]), seat.err)


if __name__ == "__main__":
    unittest.main()
