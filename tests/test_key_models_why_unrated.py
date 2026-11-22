"""⏎ on the models screen names, on a role's why page, each release on that the role rates no row
of, as `p` names it, after the others under `not shown` and in the order `p` lists them:
"fewer than two of this role's benchmarks score it"; where it has no other, `not shown` holds
them alone, and a role rating none of the releases on says them under the model its line names.
A role that rates it says it as it says any row, a choice or one of its others.

Black-box, as tests/test_key_models_why.py, on its drawing: the program `AK_BIN` names in a
terminal, its harnesses fakes listing invented models and the boards held as just asked; judged
by the screen, its kinds read as tests/test_key_models_why_shaded.py reads them.  Fails against
/bin/false.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX
from test_key_models_why_shaded import kinds
import test_key_models_why as drawing

UNRATED = ": fewer than two of this role's benchmarks score it"
MID = [row for row in drawing.DRAWN if row[0] == "acme-mid-5"]
CRUX = [row for row in drawing.DRAWN if row[0] == "crux-2"]
# scored, of the roles' measures, on FrontierCode 2.0 and Omniscience alone: two of review's, one
# of execute's and one of orchestrate's; Cove 1 stronger than Bolt 2, Zeal 9 weakest of all
BOLT = ("bolt-2", "Bolt 2", "high", 58, .70, None, 45, 1.0)
COVE = ("cove-1", "Cove 1", "high", 59, .71, None, 46, 1.2)
ZEAL = ("zeal-9", "Zeal 9", "high", 40, .55, None, 30, 0.5)


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ModelsWhyUnrated(unittest.TestCase):
    # the home, the screen and its why page as tests/test_key_models_why.py has them
    setUpClass = classmethod(drawing.ModelsWhy.setUpClass.__func__)
    setUp, models, why = drawing.ModelsWhy.setUp, drawing.ModelsWhy.models, drawing.ModelsWhy.why
    write = drawing.ModelsWhy.write

    def on(self, rows, alone, companies=None):
        """The boards holding `rows`, those of `alone` scored as BOLT is, Acme Mid 5 building and
        reviewing and Crux 2 orchestrating; a row of Zeal 9 Zeal's, and the config listing
        `companies` first."""
        self.write(rows, ["mid"], models={name: drawing.MODELS[name] for name in ("crux", "mid")})
        held = drawing.boards(rows)
        for row in held["artificialanalysis.ai"]["rows"]:
            row["maker"] = "Zeal" if row["model"] == "Zeal 9" else row["maker"]
            if row["model"] in alone:
                del row["values"]["aa.terminalBench40"]
                del row["values"]["aa.briefcaseBreakdown.overall.elo"]
        self.home.write(".agentkit/state/boards.json", held)
        if companies:
            path = self.home.path / ".agentkit/config.toml"
            path.write_text(f"companies = {json.dumps(companies)}\n" + path.read_text())

    def test_a_release_one_role_rates_is_on_the_why_page_of_the_role_that_does_not(self):
        self.on([*MID, BOLT], {"Bolt 2"})
        term = self.models()
        page = self.why(term, "Down")
        self.assertEqual(page[0], "  why Acme Mid 5 high builds")
        # no other: it alone is not shown, under the rule that makes the choices
        self.assertEqual(page[-2:], [drawing.CHOICES, "  not shown  Bolt 2" + UNRATED])
        term.keys("Escape")
        term.wait("\n› executor ")
        reviews = kinds(self.why(term, "Down"))
        self.assertIn("Bolt 2 high", reviews.get("shaded", []) + reviews.get("not shown", []))
        self.assertNotIn("Bolt 2" + UNRATED, reviews.get("not shown", []))

    def test_they_follow_the_others_in_the_order_p_lists_them(self):
        # five choices leave the bars no place to shade: every other is not shown; then p lists
        # Zeal first, as the config does, then Acme's strongest first
        self.on([*drawing.FIVE, BOLT, COVE, ZEAL], {"Bolt 2", "Cove 1", "Zeal 9"}, ["Zeal", "Acme"])
        self.assertEqual(kinds(self.why(self.models(), "Down"))["not shown"], [
            "Acme Max 5 max", "Holm 1 high", "Fern 1 high", "Bolt 3 medium", "Crux 2 low",
            "Zeal 9" + UNRATED, "Cove 1" + UNRATED, "Bolt 2" + UNRATED])

    def test_a_role_rating_none_of_them_says_so_under_the_model_its_line_names(self):
        # Acme Mid 5, on no board, builds: no row of the role's to give a quality or a cost, and
        # none of a model in use names its company
        self.on([BOLT, COVE], {"Bolt 2", "Cove 1"}, ["Acme"])
        self.assertEqual(self.why(self.models(), "Down"), [
            "  why Acme Mid 5 high builds", "", drawing.CHOICES,
            "  not shown  Cove 1" + UNRATED, "             Bolt 2" + UNRATED])


if __name__ == "__main__":
    unittest.main()
