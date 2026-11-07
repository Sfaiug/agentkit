"""⏎ on the models screen opens the why of the row the role `▸` is on uses, as the owner drew it
on 5 Nov 2026, a label column beside values that wrap at words in their own: its quality give
or take 1.96 standard errors, the benchmarks that scored it and how far below the role's best
choice it is; its cost, `≈` before one no runs measured, and where that comes from -- its runs,
its board price times what runs on its provider or on every provider cost a board dollar, or
its board price alone.  Esc returns with `▸` where it was, and a page taller than the screen
turns with ↓ and ↑.

Black-box, as tests/test_key_models_answer.py: the program `AK_BIN` names in a terminal, its
harnesses fakes listing invented models, the boards held as just asked with invented rows, and
finished builds and reviews as tests/test_key_role_cost_from_runs.py writes them; judged by the
screen.  Fails against /bin/false.
"""

import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import SERVER, Terminal
from test_key_models_answer import ENV, EVALUATIONS, OLD, aa, lines
from test_key_role_cost_from_runs import NOW, History

# Per release and effort: intelligence index, frontier-code and terminal shares, Arena's agent
# share, none for Acme Max 5 high (carried from max) and Crux 2 (missing), Omniscience and cost
# a task, a dollar a million tokens; AutomationBench on Acme Max 5 max alone
ROWS = [("acme-max-5", "Acme Max 5", "max", 70, .80, .80, 50, 20.0),
        ("acme-max-5", "Acme Max 5", "high", 66, .74, None, 48, 10.0),
        ("acme-mid-5", "Acme Mid 5", "high", 66, .72, .77, 49, 1.5),
        ("bolt-3", "Bolt 3", "medium", 60, .64, .74, 45, 3.0),
        ("crux-2", "Crux 2", "low", 50, .60, None, 42, 1.0),
        ("dune-1", "Dune 1", "high", 64, .75, .775, 47, 4.0),
        ("elm-1", "Elm 1", "high", 68, .78, .78, 46, 6.0)]
MODELS = {"crux": {"harness": "codex", "model": "crux-2", "effort": "low"},
          "mid": {"harness": "claude", "model": "acme-mid-5"},
          "max": {"harness": "claude", "model": "acme-max-5", "review_effort": "max"}}

MAX_HIGH_BUILDS = [
    "  why Acme Max 5 high builds",
    "",
    "  quality    94.8   give or take 3.7, from three benchmarks",
    "             FrontierCode 2.0, Arena Agent carried from max, Terminal-Bench 4.0",
    "             5.2 below the best, Acme Max 5 max",
    "",
    "  cost       ≈ $10.00 a build   estimated: its board price, times what your runs on its provider",
    "             cost a board dollar"]
MAX_MAX_REVIEWS = [
    "  why Acme Max 5 max reviews",
    "",
    "  quality    100.0   give or take 5.5, from two benchmarks",
    "             FrontierCode 2.0, AA-Omniscience",
    "             the best of these choices"]
MID_BUILDS = [
    "  why Acme Mid 5 high builds",
    "",
    "  quality    94.0   give or take 3.8, from three benchmarks",
    "             FrontierCode 2.0, Arena Agent, Terminal-Bench 4.0",
    "             6.0 below the best, Acme Max 5 max",
    "",
    "  cost       $1.50 a build   from 2 of your builds"]
CRUX_REVIEWS = [
    "  why Crux 2 low reviews",
    "",
    "  quality    82.4   give or take 6.7, from two benchmarks",
    "             FrontierCode 2.0, AA-Omniscience",
    "             17.6 below the best, Acme Max 5 max",
    "",
    "  cost       ≈ $1.00 a review   estimated: its board price, times what your runs on every provider",
    "             cost a board dollar"]
CRUX_BUILDS_40 = [
    "  why Crux 2 low builds",
    "",
    "  quality    80.0   give or take 7.1,",
    "             from two benchmarks",
    "             FrontierCode 2.0, Arena",
    "             Agent no score, counted as",
    "             its worst, Terminal-Bench",
    "             4.0",
    "             20.0 below the best, Acme",
    "             Max 5 max",
    "",
    "  cost       ≈ $1.00 a build   its board",
    "             price alone: no build of",
    "             yours priced a model"]


def boards():
    """The boards holding `ROWS`, and the rows keeping them from being asked, just answered:
    newer than the answer an earlier case drew."""
    rows = {board: [{"model": "Old 1", "effort": "high", "values": dict.fromkeys(names.split(), 0)}]
            for board, names in OLD.items()}
    rows["artificialanalysis.ai"] = [aa("old-1", "Old 1", "high", rows["artificialanalysis.ai"][0]
                                        ["values"], retired=True)]
    for release, name, effort, index, share, agent, omni, cost in ROWS:
        rows["artificialanalysis.ai"].append(aa(release, name, effort, {
            "aa.briefcaseBreakdown.overall.elo": 1400, "aa.omniscience": omni,
            **({"aa.automationBenchPartialScore": 0.9} if effort == "max" else {}),
            "aa.intelligenceIndex": index, "aa.frontierCode20": share, "aa.terminalBench40": share,
            "aa.price1mInputTokens": 1, "aa.price1mOutputTokens": 1,
            **{f"aa.intelligenceIndexEvaluations.{slug}.costPerTask": cost for slug in EVALUATIONS}}))
        if agent:
            rows["arena.ai"].append({"model": name, "effort": effort,
                                     "values": {"arena.agent": agent}})
    now = time.time()
    return {board: {"asked_at": now, "fetched_at": now, "error": None, "build": "", "rows": found}
            for board, found in rows.items()}


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ModelsWhy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        fakes = fakeadapter.install(home, claude="pass", codex="pass")
        fakes["claude"].answer("models", "acme-mid-5\tAcme Mid 5\tlow medium high xhigh max\n"
                                         "acme-max-5\tAcme Max 5\thigh max\n")
        fakes["codex"].answer("models", "bolt-3\tBolt 3\tlow medium high\ncrux-2\tCrux 2\tlow\n")
        home.write(".agentkit/state/usage.json", {"providers": {provider: {"meters": [
            {"name": "weekly", "used": 40, "window_secs": 604800, "resets_at": NOW + 86400}]}
            for provider in ("anthropic", "openai")}})

    def setUp(self):
        History(self.home).save()        # no runs, until a case writes some

    def write(self, workers, reviewers=None, runs=False):
        """The boards holding `ROWS`; Crux 2 at low orchestrates new seats, `workers` build
        them and `reviewers` review, every plan a dollar; with `runs`, two finished builds of
        Acme Mid 5 high and a review by it, costing what its board does, a point of a week a
        dollar."""
        self.home.write(".agentkit/state/boards.json", boards())
        akconfig.write(self.home, MODELS, orchestrator="crux", workers=workers,
                       reviewers=reviewers, providers={
                           provider: {"mode": "subscription", "price": 1}
                           for provider in ("anthropic", "openai", "acme")})
        if not runs:
            return
        history = History(self.home)
        # the login's week $100 at a dollar a million tokens: a million tokens is a point
        history.week("anthropic", "default", "claude", "acme-mid-5", 50e6, 50)
        spent = lambda model, millions: [[("default", model, (millions * 1e6, 0, 0, 0))]]
        history.run(("mid", "high"), built=spent("acme-mid-5", 1))
        history.run(("mid", "high"), "mid", ["high"], built=spent("acme-mid-5", 2),
                    reviewed=spent("acme-mid-5", 1.5))
        history.save()

    def models(self, width=100, height=60):
        """`r` on `c` in a window of its own, once the answer is drawn."""
        term = Terminal(self.home, size=(width, height), env=ENV)
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        term.wait("esc leave")
        term.keys("c")
        term.wait("r recommended")
        term.keys("r")
        term.wait("comparing all 6 models")
        return term

    def why(self, term, *keys):
        """The why `keys` then ⏎ open, from its heading to the line over its key line."""
        term.keys(*keys, "Enter")
        # drawn whole once its own key line, the last, stands under its heading
        shown = lines(term.wait(lambda screen: "\n  why " in screen and lines(
            screen.rstrip())[-1] == "  esc back").rstrip())
        return shown[shown.index(next(line for line in shown if line.startswith("  why "))):-2]

    def test_enter_says_why_a_row_is_used_as_the_owner_drew_it_and_esc_returns(self):
        self.write(["max"], runs=True)
        term = self.models()
        self.assertEqual(self.why(term, "Down"), MAX_HIGH_BUILDS)
        term.keys("Escape")
        self.assertIn("\n  ▸ executor      Acme Max 5 high ", term.wait("comparing all"))
        self.assertEqual(self.why(term, "Down")[:len(MAX_MAX_REVIEWS)], MAX_MAX_REVIEWS)

    def test_a_cost_from_your_runs_says_how_many(self):
        self.write(["mid"], ["crux"], runs=True)
        term = self.models()
        self.assertEqual(self.why(term, "Down"), MID_BUILDS)
        term.keys("Escape")
        term.wait("\n  ▸ executor ")
        self.assertEqual(self.why(term, "Down"), CRUX_REVIEWS)

    def test_on_40_cells_each_value_wraps_at_words_in_its_column(self):
        self.write(["crux"])
        term = self.models(40)
        self.assertEqual(self.why(term, "Down"), CRUX_BUILDS_40)

    def test_a_why_taller_than_the_screen_turns_a_page_at_a_time_to_its_last_line_and_back(self):
        self.write(["crux"])
        term = self.models(40, 14)
        first = self.why(term, "Down")
        self.assertEqual(first, CRUX_BUILDS_40[:len(first)])
        self.assertLess(len(first), len(CRUX_BUILDS_40))
        term.keys(*["Down"] * len(CRUX_BUILDS_40))      # a page at a time, never past the last
        # its last line, under its fold, then over its key line
        term.wait(lambda screen: lines(screen.rstrip())[-3:] == [CRUX_BUILDS_40[-1], "",
                                                                 "  esc back"])
        term.keys(*["Up"] * len(CRUX_BUILDS_40))        # and back to its heading
        term.wait(lambda screen: CRUX_BUILDS_40[0] in lines(screen))


if __name__ == "__main__":
    unittest.main()
