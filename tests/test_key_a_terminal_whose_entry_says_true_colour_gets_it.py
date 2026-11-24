"""A terminal whose entry says it takes true colour gets it, said elsewhere or not.

Over ssh a terminal's name (TERM) arrives and COLORTERM does not, so the menu in the whole window
drew the nearest of 256 colours while the one over a seat, told by tmux that its client takes
true colour, drew the look's own: one terminal, two looks.  tmux reads that from the terminal's
entry (`Tc`, `RGB`, or `setrgbf` with `setrgbb`), and so does the menu.  Black-box, through
tests/fixtures/akterm.py; the entries are compiled here, as no host need have one.
"""

import subprocess
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.aklooks import ink, look, settled
from fixtures.akterm import SERVER, Terminal

ENTRIES = {"acme-tc": "Tc,", "acme-rgb": "RGB,", "acme-256": "",
           "acme-set": "setrgbf=\\E[38;2;%p1%d;%p2%d;%p3%dm, setrgbb=\\E[48;2;%p1%d;%p2%d;%p3%dm,"}


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class TrueColour(unittest.TestCase):
    def test_the_text_is_the_look_s_own_where_the_entry_says_true_colour(self):
        home = Home()
        self.addCleanup(home.close)
        entries = Path(home.path) / "terminfo"
        for name, says in ENTRIES.items():
            source = f"{name}|a terminal, colors#256, {says} use=xterm-256color,\n"
            subprocess.run(["tic", "-x", "-o", str(entries), "-"], input=source, text=True,
                           check=True, capture_output=True)
            with self.subTest(entry=name):
                menu = Terminal(home, env={"TERM": name, "TERMINFO": str(entries)})
                self.addCleanup(home.tmux, "kill-session", "-t", menu.pane, server=SERVER)
                shown = settled(menu, lambda text: "n starts one" in text)
                self.assertEqual(ink(look(shown, "n starts one")) - {"1"},
                                 {"38;5;254"} if name == "acme-256" else {"38;2;226;232;239"})


if __name__ == "__main__":
    unittest.main()
