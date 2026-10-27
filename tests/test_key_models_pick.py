"""`p` on the models screen picks the releases the answer compares: each current release under
its maker, the strongest first, Space marking one and on `all` clearing every mark, what is
typed finding, each mark saved at once as `compare`, a replaced release's counting as its
successor; Esc answers again over the marked ones and says how many.  On 40 cells the count
takes its own line, and the answer's notes break only between notes.

Black-box: the program `AK_BIN` names in a terminal (tests/fixtures/akterm.py), its harnesses
fakes listing invented models and the boards held as just asked with invented rows (those of
tests/test_key_models_answer.py, each under its own maker, with Bolt 2 replaced by Bolt 3);
judged by the screen and config.toml.  Fails against /bin/false.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import SERVER, Terminal
from test_key_models_answer import ENV, aa, boards, lines

LIST = ["  ■ all 4 models", "  Acme", "    □ Acme Max 5", "    □ Acme Mid 5", "  Bolt",
        "    □ Bolt 3", "  Crux", "    □ Crux 2"]


def renamed(long=False):
    """The answer key's boards, each release under its own maker, and Bolt 2 replaced; `long`,
    with Bolt 3 named too long for a phone."""
    held = boards()
    rows = held["artificialanalysis.ai"]["rows"]
    for row in rows:
        row["maker"] = row["model"].split()[0]
        if long and row["release"]["slug"] == "bolt-3":
            row["release"]["name"] = "Bolt 3 Long Context Preview Edition"
    rows.append(aa("bolt-2", "Bolt 2", "high", {}, retired=True))
    rows[-1]["release"]["deprecatedTo"] = "bolt-3"
    return held


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ModelsPick(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        fakes = fakeadapter.install(home, claude="pass", codex="pass")
        fakes["claude"].answer("models", "acme-mid-5\tAcme Mid 5\tlow medium high xhigh max\n")
        fakes["codex"].answer("models", "bolt-3\tBolt 3\tlow medium high\n")

    def pick(self, width=100, height=60, compare=None, long=False):
        """`p` on the models screen, `compare` saved before it opened."""
        akconfig.write(self.home, {
            "mid": {"harness": "claude", "model": "acme-mid-5", "effort": "low"},
            "bolt": {"harness": "codex", "model": "bolt-3", "effort": "low"}},
            settings={"compare": compare} if compare else None)
        self.home.write(".agentkit/state/boards.json", renamed(long))
        (self.home.path / ".agentkit/state/matrix.json").unlink(missing_ok=True)    # answered anew
        term = Terminal(self.home, size=(width, height), env=ENV)
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        term.wait("esc leave")
        term.keys("c")
        term.wait("r recommended")
        term.keys("r")
        term.wait("boards read")      # the answer over the boards landed
        term.keys("p")
        return term, lines(term.wait("type to find"))

    def compare(self):
        return akconfig.read(self.home).get("compare")

    def test_two_marks_move_a_roles_pick(self):
        term, shown = self.pick()
        # the count at the right edge of the layout, as wide as the rule under the title
        at = shown.index("  models to compare".ljust(len(shown[1]) - 14) + "all 4 compared")
        self.assertEqual(shown[at + 1:at + 10],
                         ["  find  ▏", "›" + LIST[0][1:], *LIST[1:]])
        self.assertEqual(next(line for line in reversed(shown) if line),
                         "  ↑↓ move   space mark   type to find   esc done")
        term.keys("Down", "Space", "Down", "Space")
        shown = lines(term.wait("2 of 4 marked"))
        self.assertIn("›   ■ Acme Mid 5", shown)
        self.assertIn("  □ all 4 models", shown)
        self.assertEqual(self.compare(), ["acme-max-5", "acme-mid-5"])
        term.keys("Escape")
        shown = lines(term.wait("comparing 2 of 4 models"))
        at = shown.index("  orch · best 100.0    quality  a task")      # was Bolt 3's
        self.assertEqual(shown[at + 3], "›   Acme Max 5 high       99.6  $10.00  ★ pick · no harness")

    def test_find_narrows_the_list(self):
        term, _ = self.pick()
        term.type("MID")
        shown = lines(term.wait("find  MID"))
        at = shown.index("  find  MID▏")
        self.assertEqual(shown[at + 1:at + 5], ["  ■ all 4 models", "  Acme", "›   □ Acme Mid 5", ""])
        term.keys("Space")             # straight after a find, as anywhere, a space marks
        term.wait("■ Acme Mid 5")
        self.assertEqual(self.compare(), ["acme-mid-5"])
        term.keys("BSpace", "BSpace", "BSpace")
        term.wait(lambda screen: "  find  ▏" in screen)
        term.type("acmem")            # letters and digits alone: no find needs a space
        shown = lines(term.wait("find  acmem▏"))
        at = shown.index("  find  acmem▏")
        self.assertEqual(shown[at + 1:at + 6], ["  □ all 4 models", "  Acme", "›   □ Acme Max 5",
                                                "    ■ Acme Mid 5", ""])
        term.keys("Up", "Space")
        term.wait("all 4 compared")
        term.keys("BSpace", "BSpace", "BSpace", "BSpace", "BSpace")
        shown = lines(term.wait(lambda screen: "  find  ▏" in screen))
        self.assertIn("    □ Crux 2", shown)

    def test_a_mark_on_a_replaced_release_counts_as_its_successor(self):
        term, shown = self.pick(compare=["bolt-2", "gone-1"])
        self.assertIn("    ■ Bolt 3", shown)
        self.assertIn("1 of 4 marked", shown[shown.index("  find  ▏") - 1])
        term.keys("Escape")
        term.wait("comparing 1 of 4 models")

    def test_space_on_all_compares_every_model_again(self):
        term, _ = self.pick(compare=["acme-mid-5"])
        term.keys("Space")
        shown = lines(term.wait("all 4 compared"))
        self.assertIn("› ■ all 4 models", shown)
        self.assertIsNone(self.compare())
        term.keys("Escape")
        term.wait("comparing all 4 models")

    def test_the_list_scrolls_saying_how_many_makers_are_cut_off(self):
        term, shown = self.pick(height=14)
        self.assertIn("  2 more makers below", shown)
        term.keys("Down", "Down", "Down", "Down")
        shown = lines(term.wait("more maker above"))
        self.assertIn("  1 more maker above", shown)

    def test_on_40_cells_the_count_takes_a_line_and_notes_break_between_notes(self):
        _, shown = self.pick(width=40)
        at = shown.index("  models to compare")
        self.assertEqual(shown[at + 1], "  all 4 compared")
        term, shown = self.pick(width=40, compare=["crux-2"], long=True)
        at = shown.index("  models to compare")
        self.assertEqual(shown[at + 1:at + 3], ["  1 of 4 marked", "  find  ▏"])
        self.assertIn("    □ Bolt 3 Long Context Preview Editi…", shown)
        term.keys("Escape")
        shown = lines(term.wait("comparing 1 of 4 models"))
        at = shown.index("  builds · best 80.3")
        self.assertEqual(shown[at + 2:at + 6], ["    Crux 2 low", "       80.3   $1.00  ★ pick",
                                                " " * 21 + "1 estimated", " " * 21 + "no harness"])
        self.assertEqual(shown[shown.index("  comparing 1 of 4 models") + 1][:14], "  boards read ")


if __name__ == "__main__":
    unittest.main()
