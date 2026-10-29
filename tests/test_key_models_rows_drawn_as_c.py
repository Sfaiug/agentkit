"""The models screen draws each row as `c` and the main menu draw theirs: its effort as `c` draws
one, its cells out of the efforts its release has on the boards and then its word, blank for a
row with none; and before its quality a line, full at its role's best and empty 10 points behind
it or more, every row's as long.  On 40 cells a row's line, numbers and notes take a line under
its name and effort, and a row too wide beside a role's head folds so, nothing but a name cut
and its notes broken only between two.

Black-box, as tests/test_key_models_answer.py: the program `AK_BIN` names in a terminal, its
harness a fake listing an invented model, the boards held as just asked with invented rows;
judged by the screen.  Fails against /bin/false.
"""

import re
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import SERVER, Terminal
from test_key_models_answer import ENV, EVALUATIONS, NOW, OLD, aa, lines

# Per release and effort, Acme Max 5's four and Crux 2's row naming none and high: Omniscience,
# which alone parts them on review, a point of it a fifth of a point of quality, and cost a task.
# Acme Max 5 low costs more than medium for less, so it is off the line of best quality for the
# money.
ROWS = [("acme-max-5", "Acme Max 5", "low", 30, 6.0),
        ("acme-max-5", "Acme Max 5", "medium", 35, 5.0),
        ("acme-max-5", "Acme Max 5", "high", 45, 10.0),
        ("acme-max-5", "Acme Max 5", "max", 60, 20.0),
        ("crux-2", "Crux 2", None, 0, 1.0), ("crux-2", "Crux 2", "high", 5, 2.0)]
# what review shows: the best, the pick 3 behind, a row 5 behind and one 11 behind, the last of
# two rows of its release
REVIEWS = [("Acme Max 5  ▰▰▰▰ max", "100.0", "$20.00"), ("Acme Max 5  ▰▰▰▱ high", "97.0", "$10.00"),
           ("Acme Max 5  ▰▰▱▱ medium", "95.0", "$5.00"), ("Crux 2      ▰▰   high", "89.0", "$2.00")]


def boards(releases=ROWS):
    rows = {board: [{"model": "Old 1", "effort": "high", "values": dict.fromkeys(names.split(), 0)}]
            for board, names in OLD.items()}
    rows["artificialanalysis.ai"] = [aa("old-1", "Old 1", "high", rows["artificialanalysis.ai"][0]
                                        ["values"], retired=True)]
    for release, name, effort, omniscience, cost in releases:
        rows["artificialanalysis.ai"].append(aa(release, name, effort, {
            "aa.intelligenceIndex": 60, "aa.frontierCode20": 0.7, "aa.terminalBench40": 0.7,
            "aa.briefcaseBreakdown.overall.elo": 1400, "aa.omniscience": omniscience,
            **{f"aa.intelligenceIndexEvaluations.{slug}.costPerTask": cost
               for slug in EVALUATIONS}}))
    return {board: {"asked_at": NOW, "fetched_at": NOW, "error": None, "build": "", "rows": found}
            for board, found in rows.items()}


def drawn(line):
    """(name and effort, line, quality, cost, notes) of a row drawn on one line, or None."""
    found = re.fullmatch(r"[ ›]   (\S.*?) +([━╸─]{8,}) +(\d+\.\d) +(\$\d+\.\d\d)(?:  (.+))?", line)
    return found and found.groups()


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ModelsRowsDrawnAsC(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        fakes = fakeadapter.install(home, claude="pass")
        fakes["claude"].answer("models", "acme-max-5\tAcme Max 5\tlow medium high max\n")

    def setUp(self):
        akconfig.write(self.home, {"max": {"harness": "claude", "model": "acme-max-5",
                                           "effort": "high"}}, settings={"within": 4})
        self.home.write(".agentkit/state/boards.json", boards())
        (self.home.path / ".agentkit/state/matrix.json").unlink(missing_ok=True)  # answered anew

    def models(self, width, until="comparing all 2 models"):
        """`r` on `c` in a window of its own, once the answer is drawn."""
        term = Terminal(self.home, size=(width, 60), env=ENV)
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        term.wait("esc leave")
        term.keys("c")
        term.wait("r recommended")
        term.keys("r")
        return lines(term.wait(until))

    def test_a_rows_effort_is_its_cells_and_word_and_its_quality_a_line(self):
        shown = self.models(100)
        at = next(n for n, line in enumerate(shown) if line.startswith("  reviews · best 100.0"))
        rows = [drawn(line) for line in shown[at + 1:at + 1 + len(REVIEWS)]]
        self.assertEqual([(head, quality, cost) for head, _, quality, cost, _ in rows], REVIEWS)
        (_, best, *_), (_, pick, *_, notes), (_, half, *_), (_, empty, *_, crux) = rows
        self.assertEqual(notes, "★ pick")
        self.assertIn("no harness", crux)
        self.assertEqual(len({len(best), len(pick), len(half), len(empty)}), 1)
        self.assertEqual(best, "━" * len(best))
        self.assertRegex(half, "^━*╸?─*$")
        self.assertEqual(2 * half.count("━") + half.count("╸"), len(half))
        self.assertEqual(empty, "─" * len(empty))
        self.assertRegex(pick, "^━+╸?─+$")
        self.assertIn("Crux 2", [row[0] for row in map(drawn, shown) if row])    # no effort

    def test_a_roles_head_is_never_cut_beside_a_short_name(self):
        # A 1's row would fit one line, its line 9 cells, but not under its role's head
        self.home.write(".agentkit/state/boards.json", boards([("a-1", "A 1", None, 50, 1.0)]))
        shown = self.models(58, "comparing all 1 models")
        for role in ("orch", "builds", "reviews"):
            self.assertIn(f"  {role} · best 100.0", shown)

    def test_on_40_cells_a_rows_line_numbers_and_notes_go_under_its_name_and_effort(self):
        rows = [row for row in map(drawn, self.models(100)) if row]
        shown, at = self.models(40), 0
        self.assertGreaterEqual(len(rows), len(REVIEWS))
        for head, _, quality, cost, notes in rows:
            at = next(n for n in range(at, len(shown)) if shown[n][4:] == head)
            under = re.fullmatch(r"    ([━╸─]{8,}) +(\d+\.\d) +(\$\d+\.\d\d)(?:  (.+))?",
                                 shown[at + 1])
            self.assertIsNotNone(under, shown[at + 1])
            self.assertEqual(under.group(2, 3), (quality, cost))
            said, at = under.group(4) or "", at + 2
            while said != (notes or "") and shown[at].startswith("      "):
                said, at = " · ".join(filter(None, (said, shown[at].strip()))), at + 1
            self.assertEqual(said, notes or "", head)


if __name__ == "__main__":
    unittest.main()
