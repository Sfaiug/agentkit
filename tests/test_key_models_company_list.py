"""`p` on the models screen lists your companies, each a line of its listed models, `●` on and
`○` off: at first the `[defaults]` models' companies, every listed model on, no release without
scores and no other company.  Space turns the model pointed at on or off, saved at once in
`models_off`, and on a company's name all of its models off, then on; the first change writes
the companies the config had.  Esc drops a company left with none on from `companies` and its
models from `models_off`, and the answer compares only the models still on.  `a` lists the
other companies with scores, strongest first, and ⏎ adds one with all of its models on.  On
40 cells a company's models go on under the column where they began.

Black-box: the program `AK_BIN` names in a terminal (tests/fixtures/akterm.py), its harnesses
fakes listing invented models and the boards held as just asked with the invented rows of
tests/test_key_models_on.py -- Acme Max 5 and Acme Mid 5 under Acme, Bolt 3 under Bolt, Crux 2
and Crux Flash 1, with no score, under Crux -- and Dyne's two, the stronger above Bolt 3; judged
by the screen, config.toml and what `ak models --json` compares.  Fails against /bin/false.
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
KEYS = "  ↑↓ company   ←→ model   ␣ on or off   a add a company   esc done"
# what [defaults] runs: Acme's Mid 5, and Crux's Flash 1, a release without a score
DEFAULTS = {"orchestrator": "mid", "workers": ["flash"]}


def boards():
    """Those of the models-on key, with Dyne's two releases, intelligence 68 and 55."""
    held = listed()
    rows = held["artificialanalysis.ai"]["rows"]
    mid = next(row for row in rows if row["model"] == "Acme Mid 5")
    for slug, name, index in (("dyne-ultra-4", "Dyne Ultra 4", 68),
                              ("dyne-lite-4-mini", "Dyne Lite 4 Mini", 55)):
        rows.append(aa(slug, name, "high", {**mid["values"], "aa.intelligenceIndex": index}))
        rows[-1]["maker"] = "Dyne"
    return held


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class CompanyList(unittest.TestCase):
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
        """`p` on the models screen, the config holding `settings` before it opened: the
        terminal and the screen once drawn whole."""
        akconfig.write(self.home, {name: MODELS[name] for name in ("mid", "bolt", "flash")},
                       settings=settings, **DEFAULTS)
        (self.home.path / ".agentkit/state/matrix.json").unlink(missing_ok=True)
        term = Terminal(self.home, size=(width, 40), env=ENV)
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        term.wait("esc leave")
        term.keys("c")
        term.wait("r recommended")
        term.keys("r")
        term.wait("boards read")      # the answer over the boards landed
        term.keys("p")
        return term, self.whole(term, "esc done")

    @staticmethod
    def whole(term, last, test=lambda shown: True):
        """The screen once its key line, ending in `last`, is drawn and `test` holds of it: a
        draw writes its key line last."""
        return lines(term.wait(lambda screen: screen.rstrip().endswith(last)
                               and test(lines(screen))))

    def saved(self):
        held = akconfig.read(self.home)
        return held.get("companies"), held.get("models_off")

    def test_p_lists_the_defaults_companies_with_their_listed_models_on(self):
        _, shown = self.open()
        self.assertTrue(shown[0].startswith("agentkit · config · recommended · new seats · models"),
                        shown[0])
        self.assertEqual(" ".join(line.strip() for line in shown[2:4]), SAID)
        # the pointer on the first company's name; Crux Flash 1, with no score, is not listed,
        # nor are Bolt and Dyne, no company of yours
        self.assertEqual(shown[4:12], ["", "›[Acme] ● Acme Max 5  ● Acme Mid 5",
                                       "  Crux  ● Crux 2", "  + add a company", "",
                                       "  3 models on, from 2 companies · 2 more companies have "
                                       "benchmark scores", "", KEYS])
        self.assertEqual(self.saved(), (None, None))

    def test_space_turns_a_model_and_on_a_name_its_companys_off_and_on(self):
        term, _ = self.open()
        term.keys("Right", "Space")
        self.whole(term, "esc done", lambda shown: "› Acme [○ Acme Max 5] ● Acme Mid 5" in shown)
        # the first change writes the companies the config had
        self.assertEqual(self.saved(), (["Acme", "Crux"], ["acme-max-5"]))
        term.keys("Space", "Down", "Space")
        self.whole(term, "esc done", lambda shown: "› Crux [○ Crux 2]" in shown)
        self.assertEqual(self.saved(), (["Acme", "Crux"], ["crux-2"]))
        term.keys("Left", "Space")
        self.whole(term, "esc done", lambda shown: "›[Crux] ● Crux 2" in shown)
        self.assertEqual(self.saved(), (["Acme", "Crux"], None))
        term.keys("Up", "Space")
        shown = self.whole(term, "esc done",
                           lambda shown: "›[Acme] ○ Acme Max 5  ○ Acme Mid 5" in shown)
        self.assertIn("  1 model on, from 1 company · 2 more companies have benchmark scores",
                      shown)
        self.assertEqual(self.saved(), (["Acme", "Crux"], ["acme-max-5", "acme-mid-5"]))
        term.keys("Space")
        self.whole(term, "esc done", lambda shown: "›[Acme] ● Acme Max 5  ● Acme Mid 5" in shown)
        self.assertEqual(self.saved(), (["Acme", "Crux"], None))

    def test_esc_drops_a_company_with_none_on_and_the_answer_compares_what_is_on(self):
        term, _ = self.open()
        term.keys("Right", "Space", "Down", "Left", "Space")
        self.whole(term, "esc done", lambda shown: "›[Crux] ○ Crux 2" in shown)
        self.assertEqual(self.saved(), (["Acme", "Crux"], ["acme-max-5", "crux-2"]))
        term.keys("Escape")
        self.whole(term, "esc back", lambda shown: "  comparing 1 of 2 models" in " ".join(shown))
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
        self.assertTrue(shown[0].startswith(
            "agentkit · config · recommended · new seats · models · add a company"), shown[0])
        self.assertEqual(shown[2:6], ["› Dyne  2 models  Dyne Ultra 4",
                                      "  Bolt  1 model   Bolt 3", "",
                                      "  ↑↓ company   ⏎ add   esc back"])
        term.keys("Enter")
        shown = self.whole(term, "esc done")
        self.assertEqual(shown[5:9], ["  Acme  ● Acme Max 5  ● Acme Mid 5", "  Crux  ● Crux 2",
                                      "›[Dyne] ● Dyne Ultra 4  ● Dyne Lite 4 Mini",
                                      "  + add a company"])
        self.assertEqual(self.saved(), (["Acme", "Crux", "Dyne"], None))
        term.keys("Down", "Enter")      # Enter on `+ add a company` opens it too; Esc adds none
        shown = self.whole(term, "esc back")
        self.assertEqual(shown[2:4], ["› Bolt  1 model  Bolt 3", ""])
        term.keys("Escape")
        self.whole(term, "esc done", lambda shown: "› + add a company" in shown)
        self.assertEqual(self.saved(), (["Acme", "Crux", "Dyne"], None))

    def test_on_40_cells_a_companys_models_go_on_under_the_column_where_they_began(self):
        _, shown = self.open(width=40, companies=["Acme", "Dyne"])
        at = shown.index("  Dyne  ● Dyne Ultra 4")
        self.assertEqual(shown[at - 1:at + 3], ["›[Acme] ● Acme Max 5  ● Acme Mid 5",
                                                "  Dyne  ● Dyne Ultra 4",
                                                "        ● Dyne Lite 4 Mini",
                                                "  + add a company"])


if __name__ == "__main__":
    unittest.main()
