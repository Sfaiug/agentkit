"""`u` on `r recommended` on `c` counts every cost in the next unit, the owner's design of 5 Nov
2026: dollars a task, the points of its plan's week a task takes, then how many such tasks a week
holds, to two significant figures, and dollars again; the role lines' heading names it, and the
role lines and the bars count in it, `≈` before a cost no run measured, each bar as tall as the
number on its top over the largest.  The screen opens again in the unit last chosen, which the
config never holds.  Before any run of yours priced a model, the boards' prices are dollars a task
too, and the other two have no week to count them in; a plan of no price still counts every
task's week.

Black-box: `AK_BIN` in terminals of 100 and 40 cells, a fake harness, the boards of
tests/test_key_models_bars.py at a dollar a million tokens, a plan's price and runs that measure
a build and a review (test_key_role_cost_from_runs's History); judged by the screen and
config.toml.  Fails against /bin/false.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import SERVER, Terminal
from test_key_models_answer import ENV
from test_key_models_bars import CONFIGURED, ROWS, bars
from test_key_models_role_lines import said
from test_key_role_choices import hold
from test_key_role_cost_from_runs import NOW, History

WIDTHS = (100, 40)
WORDS = ("orchestrator", "executor", "reviewer")
# $130 a month, so a week of it is $30 and a point of that week 30 cents.  Top builds in 2
# points, $0.60, and Base reviews in 0.1, $0.03: the orchestrator, which no run measures, costs
# both their $0.63 over their $10 on the boards, 6.3 cents a board dollar
PRICE = 130
# Per unit, in the turn `u` takes: what the role lines say each role costs, Step orchestrating,
# Top building and Base reviewing, and the costs on the orchestrator's bars, left to right
# (test_key_models_bars.BARS): Base, Long Name, Step, Dear and Top, $2 to $8 on the boards
COUNTED = {"$ a task": (["≈$0.25", "$0.60", "$0.03"],
                        ["≈$0.13", "≈$0.19", "≈$0.25", "≈$0.38", "≈$0.50"]),
           "% of a week": (["≈0.84%", "2.00%", "0.10%"],
                           ["≈0.42%", "≈0.63%", "≈0.84%", "≈1.26%", "≈1.68%"]),
           "a week": (["≈120", "50", "1,000"], ["≈240", "≈160", "≈120", "≈79", "≈60"])}
# a plan of no price: every task free, its week counted as on a priced one, the bars, each as
# cheap as the next, standing worst first: Base, Long Name, Dear, Step and Top
FREE = {"$ a task": (["≈$0.00", "$0.00", "$0.00"], ["≈$0.00"] * 5),
        "% of a week": (COUNTED["% of a week"][0],
                        ["≈0.42%", "≈0.63%", "≈1.26%", "≈0.84%", "≈1.68%"]),
        "a week": (COUNTED["a week"][0], ["≈240", "≈160", "≈79", "≈120", "≈60"])}
# Per unit, the eighths of a cell the orchestrator's bars stand, left to right, each the number
# on its top over the largest, 7 cells, $0.13 of $0.50 14.56 eighths: Long Name's and Dear's,
# shaded, in whole cells, and none under a smaller number.  A week holds the most tasks of the
# cheapest, the tallest
HEIGHTS = {"$ a task": [15, 24, 28, 40, 56], "% of a week": [14, 24, 28, 40, 56],
           "a week": [56, 40, 28, 16, 14]}
# Top building and Base reviewing in 20,000 tokens each, 0.02 points, so a board dollar is 0.004
# points, $0.0012: costs as COUNTED has them, and the bars as HEIGHTS, each of two carrying one
# number as tall, the solid one standing its shaded one's whole cells
TIED = {"$ a task": (["≈$0.005", "$0.01", "$0.01"],
                     ["≈$0.002", "≈$0.004", "≈$0.005", "≈$0.01", "≈$0.01"]),
        "% of a week": (["≈0.02%", "0.02%", "0.02%"],
                        ["≈0.01%", "≈0.01%", "≈0.02%", "≈0.02%", "≈0.03%"])}
TIED_HEIGHTS = {"$ a task": [11, 24, 28, 56, 56], "% of a week": [16, 16, 40, 40, 56]}
# no run of yours: the boards' dollars a task, and no week in the other two
UNRUN = {"$ a task": (["≈$4.00", "≈$8.00", "≈$2.00"],
                      ["≈$2.00", "≈$3.00", "≈$4.00", "≈$6.00", "≈$8.00"]),
         "% of a week": (["-"] * 3, ["-"] * 5)}


def counted(screen):
    """(the role lines' unit, each role's cost, the costs on the orchestrator's bars); None
    before they are drawn.  A role's cost ends its word's line, its model too wide beside it
    going under it."""
    try:
        shown = said(screen)
        costs = [next(line.split()[-1] for line in shown if word in line.split())
                 for word in WORDS]
        return shown[0].removeprefix("quality "), costs, [bar["cost"] for bar in bars(
            screen, "orchestrator")]
    except (StopIteration, ValueError, IndexError):
        return None


def want(unit, counts=COUNTED):
    return unit, *counts[unit]


def planned(home, price):
    """`home` holding the boards, the harness and [defaults] of tests/test_key_models_bars.py, on
    a plan of `price` a month making every Acme model, so each row is on its week, at a dollar a
    million tokens; and its History, for the runs a case saves."""
    fakeadapter.install(home, claude="pass")["claude"].answer("models", "".join(
        f"{release}\t{name}\thigh\n" for release, name, *_ in ROWS
        if release in CONFIGURED.values()))
    akconfig.write(home, {name: {"harness": "claude", "model": release}
                          for name, release in CONFIGURED.items()},
                   orchestrator="step", workers=["top"], reviewers=["base"],
                   providers={"anthropic": {"mode": "subscription", "price": price,
                                            "maker": "Acme"}})
    hold(home, [(release, name, "high", quality / 100 - 0.1, cost)
                for release, name, quality, cost in ROWS])
    held = json.loads((home.path / ".agentkit/state/boards.json").read_text())
    for row in held["artificialanalysis.ai"]["rows"]:
        row["values"].update({"aa.price1mInputTokens": 1, "aa.price1mOutputTokens": 1})
    home.write(".agentkit/state/boards.json", held)
    home.write(".agentkit/state/usage.json", {"providers": {"anthropic": {"meters": [
        {"name": "weekly", "used": 40, "window_secs": 604800, "resets_at": NOW + 86400}]}}})
    return History(home)


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ModelsUnitSwitch(unittest.TestCase):
    def home(self, runs=(2e6, .1e6), price=PRICE):
        """A Home planned at `price`, its `runs` the tokens Top builds in and Base reviews in,
        else none."""
        home = Home()
        self.addCleanup(home.close)
        history = planned(home, price)
        if runs:
            built, reviewed = runs
            # a listed week of $100 at a dollar a million tokens: a million tokens is a point
            history.week("anthropic", "default", "claude", "acme-top-1", 50e6, 50)
            history.run(("top", "high"), built=[[("default", "acme-top-1", (built, 0, 0, 0))]])
            history.run(None, "base", ["high"],
                        reviewed=[[("default", "acme-base-1", (reviewed, 0, 0, 0))]])
        history.save()
        return home

    def models(self, home, width, unit, counts=COUNTED):
        """`r` on `c` in a window of its own, 40 rows high, once it counts in `unit`."""
        term = Terminal(home, size=(width, 40), env=ENV)
        self.addCleanup(home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        term.wait("esc leave")
        term.keys("c")
        term.wait("r recommended")
        term.keys("r")
        term.wait(lambda screen: counted(screen) == want(unit, counts))
        return term

    def test_each_u_counts_every_cost_in_the_next_unit_and_the_third_back_in_dollars(self):
        for width in WIDTHS:
            with self.subTest(width=width):
                home = self.home()
                term = self.models(home, width, "$ a task")
                for unit in ("% of a week", "a week", "$ a task"):
                    term.keys("u")
                    term.wait(lambda screen: counted(screen) == want(unit))

    def test_the_screen_opens_again_in_the_last_unit_and_the_config_never_holds_it(self):
        for width in WIDTHS:
            with self.subTest(width=width):
                home = self.home()
                config = home.path / ".agentkit/config.toml"
                term = self.models(home, width, "$ a task")
                before = config.read_bytes()
                term.keys("u", "u")
                term.wait(lambda screen: counted(screen) == want("a week"))
                term.keys("Escape")
                term.wait("r recommended")
                self.models(home, width, "a week")
                self.assertEqual(config.read_bytes(), before)

    def test_a_plan_of_no_price_counts_each_task_in_its_week(self):
        for width in WIDTHS:
            with self.subTest(width=width):
                term = self.models(self.home(price=0), width, "$ a task", FREE)
                for unit in ("% of a week", "a week"):
                    term.keys("u")
                    term.wait(lambda screen: counted(screen) == want(unit, FREE))

    def test_a_bar_is_as_tall_as_the_number_on_its_top(self):
        for width in WIDTHS:
            for runs, counts, heights in (((2e6, .1e6), COUNTED, HEIGHTS),
                                          ((2e4, 2e4), TIED, TIED_HEIGHTS)):
                with self.subTest(width=width, runs=runs):
                    term = self.models(self.home(runs), width, "$ a task", counts)
                    for unit in heights:        # in the turn `u` takes
                        term.wait(lambda screen: counted(screen) == want(unit, counts) and [
                            bar["eighths"] for bar in bars(screen, "orchestrator")]
                                  == heights[unit])
                        term.keys("u")

    def test_before_a_run_of_yours_the_boards_dollars_are_a_task_and_no_week_counts_them(self):
        for width in WIDTHS:
            with self.subTest(width=width):
                term = self.models(self.home(runs=False), width, "$ a task", UNRUN)
                term.keys("u")
                term.wait(lambda screen: counted(screen) == want("% of a week", UNRUN))


if __name__ == "__main__":
    unittest.main()
