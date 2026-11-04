"""AK_BIN draws each role's linear cost chart above its unchanged table.

Invented boards and a fake harness in a temporary HOME; only `ak models` output is read.
"""

from pathlib import Path
import re
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import Home
from test_key_models_answer import ENV, EVALUATIONS, aa, boards, lines

ROWS = [("base", .84, 1), ("pick", .89, 2), ("twice", .895, 4),
        ("other", .892, 6), ("best", .90, 8)]


class ModelsChart(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        fakeadapter.install(self.home, claude="pass")["claude"].answer(
            "models", "".join(f"{name}-1\t{name.title()} 1\thigh\n" for name, *_ in ROWS))
        akconfig.write(self.home, {name: {"harness": "claude", "model": f"{name}-1"}
                                   for name, *_ in ROWS})

    def models(self, width=100, rows=ROWS):
        held = boards()
        for board in held.values():
            board["rows"] = [row for row in board["rows"] if row["model"] == "Old 1"]
        for name, share, cost in rows:
            held["artificialanalysis.ai"]["rows"].append(aa(f"{name}-1", f"{name.title()} 1", "high", {
                "aa.intelligenceIndex": 50, "aa.frontierCode20": share,
                "aa.terminalBench40": share, "aa.omniscience": 100 * share,
                "aa.automationBenchPartialScore": share,
                **{f"aa.intelligenceIndexEvaluations.{slug}.costPerTask": cost
                   for slug in EVALUATIONS}}))
            held["arena.ai"]["rows"].append({"model": f"{name.title()} 1", "effort": "high",
                "values": {"arena.agent": share, "arena.agent.lower95ci": share - .196,
                           "arena.agent.upper95ci": share + .196}})
        self.home.write(".agentkit/state/boards.json", held)
        (self.home.path / ".agentkit/state/matrix.json").unlink(missing_ok=True)
        done = self.home.ak("models", env={**ENV, "COLUMNS": str(width)})
        self.assertEqual(done.code, 0, done.err)
        self.assertTrue(all(len(line) <= min(width, 120) for line in done.out.splitlines()))
        return done.out

    def plot(self, shown, role="builds"):
        section = shown.split(f"  {role}\n", 1)[1]
        return section.split("  quality ↑\n", 1)[1].split("  cost →", 1)[0].splitlines()

    def marks(self, plot):
        return sorted((x, y, c) for y, row in enumerate(plot) for x, c in enumerate(row)
                      if c in "●·★")

    def test_twice_the_cost_is_twice_as_far_from_zero_in_each_role(self):
        for width in (60, 80, 120, 160):
            shown = self.models(width)
            for role in ("orch", "builds", "reviews"):
                plot = self.plot(shown, role)
                zero = next(row.index("└") for row in plot if "└" in row)
                marks = self.marks(plot)
                self.assertEqual(len(marks), 5)
                a, b, c, _, d = [x - zero for x, *_ in marks]
                for cheap, dear in ((a, b), (b, c), (c, d)):
                    self.assertLessEqual(abs(2 * cheap - dear), 1)
                self.assertEqual([mark for *_, mark in marks], ["●", "★", "●", "·", "●"])
                for name in ("Base", "Pick", "Twice", "Best"):
                    self.assertIn(f"{name} 1 high", "\n".join(plot))
                self.assertIn("cost → board $ / task", shown)

    def test_the_dotted_reference_joins_the_cheapest_compared_row_to_the_best(self):
        plot = self.plot(self.models())
        (ax, ay, _), (_, py, pick), *_, (bx, by, _) = self.marks(plot)
        self.assertEqual(pick, "★")
        dots = [(x, y) for y, row in enumerate(plot) for x, c in enumerate(row) if c == "┄"]
        self.assertLessEqual(min(x for x, _ in dots), ax + 1)
        self.assertGreaterEqual(max(x for x, _ in dots), bx - 1)
        self.assertLess(py, ay)
        for x, y in dots:
            self.assertLessEqual(abs(y - (ay + (by - ay) * (x - ax) / (bx - ax))), 1)

    def test_low_quality_rows_stay_in_the_table_but_do_not_crush_the_chart(self):
        shown = self.models(rows=[("far", .30, .5), *ROWS])
        plot = self.plot(shown)
        self.assertEqual(len(self.marks(plot)), 5)
        self.assertNotIn("Far 1", "\n".join(plot))
        self.assertIn("Far 1", "\n".join(lines(shown)))
        self.assertIn("94.0", "\n".join(plot))

    def test_frontier_keeps_actual_cost_order_within_one_column(self):
        plot = self.plot(self.models(rows=[("base", .80, 1), ("pick", .85, 1.01), ("best", .90, 10)]))
        pick = next(row for row in plot if "★" in row)
        a, b = pick.index("★"), max(x for x, _, mark in self.marks(plot) if mark == "●")
        self.assertEqual(pick[a + (b - a) // 4], "─")

    def test_zero_costs_one_row_and_equal_costs_still_draw_a_pick(self):
        for rows in (ROWS[:1], [(n, s, 0) for n, s, _ in ROWS],
                     [(n, s, 2) for n, s, _ in ROWS]):
            plot = self.plot(self.models(rows=rows))
            self.assertEqual(sum(c == "★" for *_, c in self.marks(plot)), 1)
            self.assertNotIn("┄", "\n".join(plot))
        self.assertNotIn("quality ↑", self.models(rows=[("base", .84, None)]))

    def test_each_role_uses_its_own_error_for_the_quality_window(self):
        # Quality 90 is inside orch/build's window, outside review's narrower error.
        shown = self.models(rows=[("border", .80, 3), *ROWS])
        for role, count in (("orch", 6), ("builds", 6), ("reviews", 5)):
            self.assertEqual(len(self.marks(self.plot(shown, role))), count)

    def test_the_chart_uses_only_the_models_being_compared(self):
        akconfig.write(self.home, {"base": {"harness": "claude", "model": "base-1"}},
                       settings={"compare": ["twice-1", "best-1"]})
        plot = self.plot(self.models())
        self.assertEqual(len(self.marks(plot)), 2)
        self.assertNotIn("Base 1", "\n".join(plot))

    def test_below_sixty_columns_the_chart_leaves_the_same_table(self):
        def contents(shown):
            table = "\n".join(lines(shown))
            return (re.findall(r"(?:Base|Pick|Twice|Best) 1", table),
                    re.findall(r"\$\d+\.\d\d", table))
        expected = contents(self.models())
        for width in (40, 59):
            shown = self.models(width)
            self.assertNotIn("quality ↑", shown)
            self.assertNotIn("┄", shown)
            self.assertEqual(contents(shown), expected)


if __name__ == "__main__":
    unittest.main()
