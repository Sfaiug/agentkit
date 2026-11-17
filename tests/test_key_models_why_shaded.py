"""⏎ on the models screen says why each model is none in two kinds, as the owner drew it on 5 Nov
2026: under `shaded` each the role's bars draw shaded, in the bars' order, the row it uses among
them where that is no choice, and under `not shown` the rest of its others, in their order; a
kind with none has no label.  The bars on a narrow screen shade fewer, and so does the page: on
100 cells the reviewer's bars shade two of its four others, on 26 none.

Black-box, as tests/test_key_models_why.py, on its drawing: the program `AK_BIN` names in a
terminal, its harnesses fakes listing invented models, the boards held as just asked and finished
builds and reviews; judged by the screen, its bars read as tests/test_key_models_bars.py reads
them.  Fails against /bin/false.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX
from test_key_models_bars import bars, drawn
import test_key_models_why as drawing

# The role's others, best first, each with its effort
OTHERS = ["Elm 1 high", "Dune 1 high", "Bolt 3 medium", "Crux 2 low"]


def kinds(page):
    """{label: [each entry's name and effort]} of a why page's lines, `not shown`'s cells wide:
    an entry's lines, those after its first two cells further in, joined, its name what comes
    before its first comma."""
    found, label = {}, None
    for line in filter(None, page):
        label, value = line[2:11].strip() or label, line[13:]
        if value.startswith("  "):
            found[label][-1] += " " + value.strip()
        else:
            found.setdefault(label, []).append(value)
    return {label: [entry.split(",")[0] for entry in entries] for label, entries in found.items()}


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ModelsWhyShaded(unittest.TestCase):
    # the home, the screen and its why page as tests/test_key_models_why.py has them
    setUpClass = classmethod(drawing.ModelsWhy.setUpClass.__func__)
    write, models, why = drawing.ModelsWhy.write, drawing.ModelsWhy.models, drawing.ModelsWhy.why

    def shown(self, width, role="reviewer", *keys):
        """The names and efforts of `role`'s bars drawn shaded, left to right, `width` cells wide,
        once `keys` move to it, and the kinds of its why page (kinds), as tall as it is: Acme Max
        5 high builds and Acme Max 5 max reviews, priced by their runs."""
        self.write(drawing.DRAWN, ["max"], runs=True)
        term = self.models(width, 120)
        term.keys(*keys or ("Down", "Down"))
        found = bars(term.wait(lambda screen: drawn(screen, role)), role)
        return ([f"{bar['name']} {bar['effort']}" for bar in found if bar["shaded"]],
                kinds(self.why(term)))

    def test_on_100_cells_the_bars_drawn_shaded_are_shaded_in_their_order_the_rest_not_shown(self):
        for role, keys, want in (("reviewer", (), ["Dune 1 high", "Elm 1 high"]),
                                 # the row it uses, a bar of its own though no choice
                                 ("executor", ("Down",),
                                  ["Dune 1 high", "Elm 1 high", "Acme Max 5 high"])):
            with self.subTest(role=role):
                shaded, page = self.shown(100, role, *keys)
                self.assertEqual(shaded, want)            # cheapest on the left
                self.assertEqual(page["shaded"], shaded)
                self.assertEqual(page["not shown"], ["Bolt 3 medium", "Crux 2 low"])

    def test_where_the_bars_shade_none_every_other_is_not_shown_and_shaded_is_left_out(self):
        shaded, page = self.shown(26)
        self.assertEqual(shaded, [])
        self.assertNotIn("shaded", page)
        self.assertEqual(page["not shown"], OTHERS)


if __name__ == "__main__":
    unittest.main()
