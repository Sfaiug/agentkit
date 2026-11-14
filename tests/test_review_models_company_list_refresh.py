"""On the company list with none of your companies listed, `+ add a company` stays lit when a
key draws it again after one of them gained scores meanwhile: the boards may land while it is
open.

Black-box: the program `AK_BIN` names in a terminal (tests/fixtures/akterm.py), over the
boards of tests/test_key_models_company_list.py, your one company Fenix, whose release has no
score until the test gives it Dyne Ultra 4's in the stored lineup.  Fails against /bin/false.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_key_models_company_list import Opened


class CompanyListRefresh(Opened):
    def test_the_add_row_stays_lit_when_the_first_of_yours_gains_scores(self):
        term, shown = self.open(companies=["Fenix"])
        self.assertEqual(shown[4:6], ["", "› + add a company"])
        stored = self.home.path / ".agentkit/state/matrix.json"
        held = json.loads(stored.read_text())
        lineup = held["matrix"]["lineup"]
        scores = next(row["values"] for row in lineup if row["release"] == "dyne-ultra-4")
        for row in lineup:
            if row["maker"] == "Fenix":
                row["values"] = scores
        self.home.write(".agentkit/state/matrix.json", held)
        term.keys("Right")
        shown = self.whole(term, "  Fenix  ■ Fenix 1")
        self.assertEqual(shown[5:7], ["  Fenix  ■ Fenix 1", "› + add a company"])


if __name__ == "__main__":
    unittest.main()
