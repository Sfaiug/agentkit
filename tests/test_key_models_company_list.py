"""`p` on the models screen lists your companies, a line each of its listed models, `●` on and `○`
off: at first the `[defaults]` models' companies, all on.  Space turns a model, or on a name its
company's, on or off, saved at once; Esc drops a company left with none on, its releases without
a score too, and those releases from `models_off`, and the answer compares only what is on.  `a`
lists the other companies with scores, strongest first, and ⏎ adds one all on.  On 40 cells a
company's models go on under the column where they began, and a count too long for its line goes
on at its words.

Black-box: the program `AK_BIN` names in a terminal (tests/fixtures/akterm.py), over the
invented boards and harnesses of tests/test_key_models_on.py, Dyne's two releases, the stronger
above Bolt 3, and Fenix's one, without a score; judged by the screen, config.toml and `ak models
--json`.  Fails against /bin/false.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import SERVER, Terminal
from test_key_models_answer import ENV, aa, lines
from test_key_models_on import MODELS, boards as listed

SAID = ("ak uses only the models that are on. Space turns one on or off, or, on a company's "
        "name, all of them. A company with none on leaves the list.")
TITLE = "agentkit · config · recommended · new seats · models"


def boards():
    held = listed()
    rows = held["artificialanalysis.ai"]["rows"]
    mid = next(row for row in rows if row["model"] == "Acme Mid 5")
    for slug, name, index in (("dyne-ultra-4", "Dyne Ultra 4", 68),
                              ("dyne-lite-4-mini", "Dyne Lite 4 Mini", 55)):
        rows.append({**aa(slug, name, "high", {**mid["values"], "aa.intelligenceIndex": index}),
                     "maker": "Dyne"})
    rows.append({**aa("fenix-1", "Fenix 1", "high", {}), "maker": "Fenix"})
    return held


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class Opened(unittest.TestCase):
    """The Home these boards and harnesses are in, and opening and reading its company list."""
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        fakes = fakeadapter.install(home, claude="pass", codex="pass")
        fakes["claude"].answer("models", "acme-mid-5\tAcme Mid 5\tlow medium high xhigh max\n")
        fakes["codex"].answer("models", "bolt-3\tBolt 3\tlow medium high\ncrux-2\tCrux 2\tlow\n"
                                        "crux-flash-1\tCrux Flash 1\thigh\n")
        home.write(".agentkit/state/boards.json", boards())

    def open(self, width=100, **settings):
        """`p` on the models screen, [defaults] running Acme Mid 5 and Crux Flash 1, a release
        without a score; the terminal and its screen."""
        akconfig.write(self.home, {name: MODELS[name] for name in ("mid", "bolt", "flash")},
                       settings=settings, orchestrator="mid", workers=["flash"])
        (self.home.path / ".agentkit/state/matrix.json").unlink(missing_ok=True)
        term = Terminal(self.home, size=(width, 40), env=ENV)
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        for wait, key in (("esc leave", "c"), ("r recommended", "r"), ("boards read", "p")):
            term.wait(wait)
            term.keys(key)
        return term, self.whole(term, "esc done")

    @staticmethod
    def whole(term, last, *shown):
        """The screen once drawn whole, its key line ending in `last`, holding the lines `shown`."""
        return lines(term.wait(lambda screen: screen.rstrip().endswith(last)
                               and set(shown) <= set(lines(screen))))

    def saved(self):
        held = akconfig.read(self.home)
        return held.get("companies"), held.get("models_off")


class CompanyList(Opened):
    def test_p_lists_the_defaults_companies_with_their_listed_models_on(self):
        _, shown = self.open()
        self.assertTrue(shown[0].startswith(TITLE), shown[0])
        self.assertEqual(" ".join(line.strip() for line in shown[2:4]), SAID)
        # no Crux Flash 1, without a score, nor Bolt or Dyne, no company of yours
        self.assertEqual(shown[4:12], [
            "", "›[Acme] ● Acme Max 5  ● Acme Mid 5", "  Crux  ● Crux 2", "  + add a company", "",
            "  3 models on, from 2 companies · 2 more companies have benchmark scores", "",
            "  ↑↓ company   ←→ model   ␣ on or off   a add a company   esc done"])
        self.assertEqual(self.saved(), (None, None))

    def test_space_turns_a_model_and_on_a_name_its_companys_off_and_on(self):
        term, _ = self.open()
        term.keys("Right", "Space")
        self.whole(term, "esc done", "› Acme [○ Acme Max 5] ● Acme Mid 5")
        self.assertEqual(self.saved(), (["Acme", "Crux"], ["acme-max-5"]))    # companies written
        term.keys("Space", "Left", "Space")
        self.whole(term, "esc done", "›[Acme] ○ Acme Max 5  ○ Acme Mid 5",
                   "  1 model on, from 1 company · 2 more companies have benchmark scores")
        self.assertEqual(self.saved(), (["Acme", "Crux"], ["acme-max-5", "acme-mid-5"]))
        term.keys("Space")
        self.whole(term, "esc done", "›[Acme] ● Acme Max 5  ● Acme Mid 5")
        self.assertEqual(self.saved(), (["Acme", "Crux"], None))

    def test_esc_drops_a_company_with_none_on_and_the_answer_compares_what_is_on(self):
        term, _ = self.open(companies=["Acme", "Crux", "Fenix"], models_off=["crux-flash-1"])
        term.keys("Right", "Space", "Down", "Left", "Space")
        self.whole(term, "esc done", "›[Crux] ○ Crux 2")
        self.assertEqual(self.saved(), (["Acme", "Crux", "Fenix"],
                                        ["acme-max-5", "crux-2", "crux-flash-1"]))
        term.keys("Escape")
        term.wait("comparing 1 of 2 models")
        self.assertEqual(self.saved(), (["Acme"], ["acme-max-5"]))
        done = self.home.ak("models", "--json", env=ENV)
        self.assertEqual(done.code, 0, done.out + done.err)
        answer = json.loads(done.out)
        self.assertEqual({row["release"] for role in ("orchestrate", "execute", "review")
                          for row in answer[role]["front"]}, {"acme-mid-5"})

    def test_a_lists_the_other_companies_strongest_first_and_enter_adds_one_all_on(self):
        term, _ = self.open(models_off=["dyne-lite-4-mini"])
        term.keys("a")
        shown = self.whole(term, "esc back")
        self.assertTrue(shown[0].startswith(TITLE + " · add a company"), shown[0])
        self.assertEqual(shown[2:4], ["› Dyne  2 models  Dyne Ultra 4", "  Bolt  1 model   Bolt 3"])
        term.keys("Enter")
        shown = self.whole(term, "esc done")
        self.assertEqual(shown[5:9], ["  Acme  ● Acme Max 5  ● Acme Mid 5", "  Crux  ● Crux 2",
                                      "›[Dyne] ● Dyne Ultra 4  ● Dyne Lite 4 Mini",
                                      "  + add a company"])
        self.assertEqual(self.saved(), (["Acme", "Crux", "Dyne"], None))

    def test_a_company_written_twice_is_one_row_and_down_goes_on_past_it(self):
        term, shown = self.open(companies=["Acme", "Acme", "Crux"])
        self.assertEqual(shown[5:8], ["›[Acme] ● Acme Max 5  ● Acme Mid 5", "  Crux  ● Crux 2",
                                      "  + add a company"])
        term.keys("Down")
        self.whole(term, "esc done", "›[Crux] ● Crux 2")

    def test_on_40_cells_a_companys_models_go_on_under_the_column_where_they_began(self):
        _, shown = self.open(width=40, companies=["Acme", "Dyne"])
        at = shown.index("  Dyne  ● Dyne Ultra 4")
        self.assertEqual(shown[at:at + 3], ["  Dyne  ● Dyne Ultra 4", "        ● Dyne Lite 4 Mini",
                                            "  + add a company"])

    def test_a_count_too_long_for_its_line_goes_on_at_its_words(self):
        # a 38-cell count in a 32-cell line: on 40 cells a longer one once broke as `score` / `s`
        _, shown = self.open(width=34, companies=["Acme"])
        at = shown.index("  2 models on, from 1 company")
        self.assertEqual(shown[at + 1:at + 3], ["  3 more companies have benchmark", "  scores"])


if __name__ == "__main__":
    unittest.main()
