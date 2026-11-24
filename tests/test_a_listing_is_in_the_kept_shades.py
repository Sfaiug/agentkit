"""A listing is drawn in the shades the background a menu last kept fits, black's where none is.

The owner (20 Nov 2026): the terminal's background picks the shades, and ak adapts by itself.
`ak orch list` and `ak usage` print and leave, so they paint no background and ask the terminal
nothing: asking took the keys typed ahead and a signal's place (16 Nov 2026).  A person's
terminal of 24-bit colour over a working seat, each cell judged by how it looks, the answer kept
written as a menu keeps it (terminal.sense).
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.aklooks import ATTRIBUTES, look, looks
from fixtures.akseat import Seat
from fixtures.akterm import KEPT, SERVER, Terminal, forget

WHITE = ("38;2;0;103;198", "38;2;111;117;126")      # its accent and its dim: 0067c6, 6f757e
BLACK = ("38;2;77;163;255", "38;2;134;141;151")     # 4da3ff, 868d97


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class AListingIsInTheKeptShades(unittest.TestCase):
    def test_orch_list_and_usage_are_in_the_kept_shades_on_no_background(self):
        with Home() as home:
            Seat(home, "acme", screen="claude-working-pane.txt")
            for answer, (accent, dim) in (("light", WHITE), ("dark", BLACK), (None, BLACK)):
                if answer:
                    home.write(KEPT, f"{answer}\n")
                else:
                    forget(home)
                shown = {}
                for args in (("orch", "list"), ("usage",)):
                    term = Terminal(home, *args)
                    self.assertEqual(term.exit_code(60), 0, term.screen())
                    shown[args[0]] = looks(term.screen(colours=True))
                    home.tmux("kill-session", "-t", term.pane, server=SERVER)
                with self.subTest(answer=answer):
                    working = look(shown["orch"], "working", on="acme")
                    self.assertEqual(set(working) - ATTRIBUTES, {accent})
                    self.assertEqual(set(look(shown["usage"], "provider")) - ATTRIBUTES, {dim})
                    self.assertEqual([part for rows in shown.values() for line in rows
                                      for _, parts in line for part in parts
                                      if part.startswith("48")], [])


if __name__ == "__main__":
    unittest.main()
