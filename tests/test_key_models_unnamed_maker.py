"""A maker the boards leave unnamed, its name empty or missing, is one company: `p` and `a` list it
as `unknown`, `companies` writes it `""`, and a `[defaults]` model running one of its releases
makes it yours, all on, as any other.

Black-box: the program `AK_BIN` names in a terminal (tests/fixtures/akterm.py), over the boards
of tests/test_key_models_company_list.py with Crux's releases named under no maker, Crux 2's
empty and the defaults' Crux Flash 1's missing; judged by the screen and config.toml.  Fails
against /bin/false.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_key_models_company_list import ADD_KEYS, Opened, boards


class UnnamedMaker(Opened):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        held = boards()
        for row in held["artificialanalysis.ai"]["rows"]:
            if row["model"].startswith("Crux"):
                row["maker"] = "" if row["model"] == "Crux 2" else None
        cls.home.write(".agentkit/state/boards.json", held)

    def test_p_lists_it_as_unknown_and_writes_it_empty(self):
        term, shown = self.open()
        self.assertEqual(shown[5:10], [
            "›[Acme]    ■ Acme Max 5  ■ Acme Mid 5", "  unknown  ■ Crux 2", "  + add a company", "",
            "  3 models on, from 2 companies · 2 more companies have benchmark scores"])
        term.keys("Down", "Right", "Space")
        self.whole(term, "› unknown [□ Crux 2]")
        self.assertEqual(self.saved(), (["Acme", ""], ["crux-2"]))
        term.keys("Space")
        self.whole(term, "› unknown [■ Crux 2]")
        self.assertEqual(self.saved(), (["Acme", ""], None))

    def test_a_adds_it_as_unknown(self):
        term, _ = self.open(companies=["Acme"])
        term.keys("a")
        shown = self.whole(term, last=ADD_KEYS)
        self.assertEqual(shown[2:5], ["› Dyne     2 models  Dyne Ultra 4",
                                      "  Bolt     1 model   Bolt 3", "  unknown  1 model   Crux 2"])
        term.keys("Down", "Down", "Enter")
        self.whole(term, "›[unknown] ■ Crux 2")
        self.assertEqual(self.saved(), (["Acme", ""], None))


if __name__ == "__main__":
    unittest.main()
