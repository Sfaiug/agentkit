"""The models screen draws each row as `c` and the main menu draw theirs: its effort as `c` draws
one, its cells out of the efforts its release has on the boards and then its word, blank for a
row with none; and before its quality a line, full at its role's best and empty 10 points behind
it or more, every row's as long.  On 40 cells a row's line, numbers and notes take a line under
its name and effort, and its mark a line above them, nothing but a name cut and its notes broken
only between two.

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
REVIEWS = [("Acme Max 5  ▰▰▰▰  max", "100.0", "$20.00"),
           ("Acme Max 5  ▰▰▰▱  high", "97.0", "$10.00"),
           ("Acme Max 5  ▰▰▱▱  medium", "95.0", "$5.00"),
           ("Crux 2      ▰▰    high", "89.0", "$2.00")]


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
    """(mark, name and effort, line, quality, cost, notes) of a row drawn on one line, or None."""
    found = re.fullmatch(r"[ ›] (.{7})  (\S.*?) +([━╸─]{8,}) +(\d+\.\d) +(\$\d+\.\d\d)(?:  (.+))?",
                         line)
    return found and (found[1].rstrip(), *found.groups()[1:])


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
        at = shown.index("  reviews")
        rows = [drawn(line) for line in shown[at + 1:at + 1 + len(REVIEWS)]]
        self.assertEqual([(head, quality, cost) for _, head, _, quality, cost, _ in rows], REVIEWS)
        (_, _, best, *_), (mark, _, pick, *_), (_, _, half, *_), (*_, empty, _, _, crux) = rows
        self.assertEqual(mark, "★ pick")
        self.assertIn("no harness", crux)
        self.assertEqual(len({len(best), len(pick), len(half), len(empty)}), 1)
        self.assertEqual(best, "━" * len(best))
        self.assertRegex(half, "^━*╸?─*$")
        self.assertEqual(2 * half.count("━") + half.count("╸"), len(half))
        self.assertEqual(empty, "─" * len(empty))
        self.assertRegex(pick, "^━+╸?─+$")
        self.assertIn("Crux 2", [row[1] for row in map(drawn, shown) if row])    # no effort

    def test_every_row_within_the_points_shows_then_two_more(self):
        # review's qualities: 100 99 98 97, Bolt 2 96.4 the pick, Acme Max 5 medium 96 what `r` takes
        # though Bolt 2 is cheaper and better, then 88, 86 and 84, one too many.  Gulp 1 95 lies under
        # Bolt 2 and Acme Max 5 high 94 under Acme Max 5 medium, so both are left out.
        self.home.write(".agentkit/state/boards.json", boards([
            ("apex-5", "Apex 5", "max", 100, 20.0), ("apex-5", "Apex 5", "high", 95, 18.0),
            ("apex-5", "Apex 5", "medium", 90, 16.0), ("apex-5", "Apex 5", "low", 85, 14.0),
            ("bolt-2", "Bolt 2", None, 82, 1.0), ("gulp-1", "Gulp 1", None, 75, 2.0),
            ("acme-max-5", "Acme Max 5", "high", 70, 4.0), ("acme-max-5", "Acme Max 5", "medium", 80, 3.0),
            ("acme-max-5", "Acme Max 5", "low", 40, 0.5), ("crux-2", "Crux 2", None, 30, 0.4),
            ("dune-1", "Dune 1", None, 20, 0.3)]))
        shown = self.models(100, "comparing all 6 models")
        at = shown.index("  reviews")
        self.assertEqual([" ".join(row[1].split()) for row in map(drawn, shown[at + 1:]) if row],
                         ["Apex 5 ▰▰▰▰ max", "Apex 5 ▰▰▰▱ high", "Apex 5 ▰▰▱▱ medium",
                          "Apex 5 ▰▱▱▱ low", "Bolt 2", "Acme Max 5 ▰▰▱ medium", "Acme Max 5 ▰▱▱ low",
                          "Crux 2"])

    def test_on_40_cells_a_rows_line_numbers_and_notes_go_under_its_name_and_effort(self):
        rows = [row for row in map(drawn, self.models(100)) if row]
        shown, at = self.models(40), 0
        self.assertGreaterEqual(len(rows), len(REVIEWS))
        for mark, head, _, quality, cost, notes in rows:
            at = next(n for n in range(at, len(shown)) if shown[n][4:] == head)
            if mark:        # on a line of its own above the name
                self.assertEqual(shown[at - 1][4:], mark)
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
