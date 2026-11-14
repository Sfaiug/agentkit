"""Every list marks what is on, highlights its row and names its keys the same way, the owner's
ask of 10 Nov 2026 that ak feel like one app (docs/cli-design.md, Words and Keys): `recommended`
draws the row the keys are on bold behind a `›` in the accent; on `c` a mark that is on is in
the accent and one that is off dim; and the company list, where any model may be on, marks one
`■` in the accent and one off `□` dim, Space marking it, its key line read as every list's.

Black-box: the program `AK_BIN` names in a terminal of 24-bit colour (tests/fixtures/akterm.py),
over the boards and harnesses of tests/test_key_models_company_list.py; each cell judged by how
it looks (tests/fixtures/aklooks.py), against the accent and the dim as `c` draws them, so what
holds is that every screen draws them alike, whatever the theme's colours.  Fails against
/bin/false.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.aklooks import look, plain, settled
from test_key_models_company_list import ENV, KEYS, Opened

COLOUR = {**{name: value for name, value in ENV.items() if name != "NO_COLOR"},
          "COLORTERM": "truecolor"}


class OneVocabulary(Opened):
    def walk(self, *steps, **settings):
        """The menu in colour opened on `c`, the accent and the dim read off it -- its
        highlight's `›` (terminal.highlight) and its column heads -- then each (text, key) of
        `steps` pressed once the text shows."""
        term = self.menu(env=COLOUR, **settings)
        term.wait("esc leave")
        term.keys("c")
        shown = settled(term, "r recommended")
        self.accent, self.dim = look(shown, "›") - {"1"}, look(shown, "orch", on="builds")
        self.assertTrue(self.accent and self.dim and self.accent != self.dim, shown)
        for wait, key in steps:
            term.wait(wait)
            term.keys(key)
        return term

    def test_recommended_draws_its_row_bold_behind_a_chevron_in_the_accent(self):
        shown = settled(self.walk(("r recommended", "r")), "boards read")
        self.assertEqual(look(shown, "›"), {"1", *self.accent})
        self.assertEqual(look(shown, "orchestrator  Acme Mid 5 high", on="›"), {"1"})
        self.assertEqual([line for line in map(plain, shown) if "▸" in line], [])

    def test_c_draws_a_mark_that_is_on_in_the_accent_and_one_that_is_off_dim(self):
        # the highlight on Bolt 3, so no mark looked at is bold or the keys' reversed one
        shown = settled(self.walk(("r recommended", "Down")), "› Bolt 3")
        self.assertEqual(look(shown, "●", on="Acme Mid 5"), self.accent)       # it orchestrates
        self.assertEqual(look(shown, "■", on="Crux Flash 1"), self.accent)     # it builds
        self.assertEqual(look(shown, "○", on="Crux Flash 1"), self.dim)

    def test_the_company_list_marks_a_model_on_as_any_may_be_and_reads_every_lists_keys(self):
        term = self.walk(("r recommended", "r"), ("boards read", "p"),
                         ("a add a company", "Down"), ("› Crux", "Down"),
                         models_off=["acme-max-5"])
        # the highlight on `+ add a company`, so no company's row is bold
        shown = settled(term, "› + add a company")
        self.assertEqual(look(shown, "□", on="Acme Max 5"), self.dim)
        self.assertEqual(look(shown, "■", on="Acme Mid 5"), self.accent)
        self.assertEqual([line for line in map(plain, shown) if {"●", "○"} & set(line)], [])
        self.assertIn(KEYS, [plain(line).rstrip() for line in shown])
        term.keys("Up", "Up", "Right", "Space", "Down", "Down")      # Space on Acme Max 5
        shown = settled(term, lambda text: "  Acme  ■ Acme Max 5  ■ Acme Mid 5" in text
                        and "› + add a company" in text)
        self.assertEqual(look(shown, "■", on="Acme Max 5"), self.accent)


if __name__ == "__main__":
    unittest.main()
