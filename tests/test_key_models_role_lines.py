"""`r recommended` on `c` says what each role uses: the row its seat, or [defaults], runs at its
effort -- the orchestrator's model, else the first mark as the pick ranks them; a board row
naming no effort, or a harness taking none, that row -- its quality and cost, `≈` before one no
runs measured, under `quality` and the cost unit.  ↑↓ move `▸`, ⏎ opens that row's why; on
40 cells each line still shows its quality and cost; `ak models` prints a seat's without `▸`.

Black-box: `AK_BIN` in a terminal and as `ak models`, a fake harness, the boards as
tests/test_key_role_choices.py writes them and one measured build (test_key_role_cost_from_runs's
History); judged by the screen and the output.  Fails against /bin/false.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import SERVER, Terminal
from test_key_models_answer import ENV, EVALUATIONS, aa, boards, lines
from test_key_role_cost_from_runs import NOW, History

# Release, effort, every measure's share and its cost a task; Plain's one row names no effort,
# and Bare's default is medium, the row a harness running it at no effort runs
ROWS = [("fast", "low", .70, 2), ("fast", "high", .80, 6), ("top", "low", .75, 3),
        ("top", "high", .90, 8), ("plain", None, .85, 10), ("bare", "medium", .60, 1),
        ("bare", "high", .65, 2)]
DEFAULTS = {"plain": None, "bare": "medium"}
MODELS = {"fast": {"effort": "low"}, "top": {"effort": "low", "exec_effort": "high"},
          "plain": {"effort": "high"}, "bare": {"effort": "none"}}
# New seats: Bare orchestrates, Top ranks over Plain to build, Plain reviews; only Top's is
# measured, its 0.2 points over $8, so every other row is 0.025 points a board dollar
NEW_SEATS = {"orchestrate": ("orchestrator", "Acme Bare 1 medium", "70.0", "≈0.03%"),
             "execute": ("executor", "Acme Top 1 high", "100.0", "0.20%"),
             "review": ("reviewer", "Acme Plain 1", "95.0", "≈0.25%")}
# A seat running Fast at high, and Top at low to build and at high to review
SEAT = {"orchestrator": "fast", "workers": ["top"], "reviewers": ["top"], "efforts": {
    "fast": {"effort": "high"}, "top": {"effort": "low", "review_effort": "high"}}}
AT_SEAT = {"orchestrate": ("orchestrator", "Acme Fast 1 high", "90.0", "≈0.15%"),
           "execute": ("executor", "Acme Top 1 low", "85.0", "≈0.08%"),
           "review": ("reviewer", "Acme Top 1 high", "100.0", "≈0.20%")}
DOES = {"orchestrate": "orchestrates", "execute": "builds", "review": "reviews"}


def said(screen):
    """The lines from the first column head to the blank line under them, over the bars (tests/
    test_key_models_bars.py), one space between words."""
    shown = [" ".join(line.split()) for line in lines(screen)]
    first = next(n for n, line in enumerate(shown) if line.startswith("quality "))
    return shown[first:shown.index("", first)]


def role_lines(answer, at=None):
    """Each role's line, `▸` before `at`'s, under the column heads: every role's in week shares."""
    return ["quality week %", *(" ".join(["▸"] * (role == at) + list(line))
                                for role, line in answer.items())]


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ModelsRoleLines(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        fakeadapter.install(home, claude="pass")["claude"].answer("models", "".join(
            f"acme-{name}-1\tAcme {name.title()} 1\t{'none' if name == 'bare' else 'low high'}\n"
            for name in MODELS))
        akconfig.write(home, {name: {"harness": "claude", "model": f"acme-{name}-1", **entry}
                              for name, entry in MODELS.items()},
                       orchestrator="bare", workers=["plain", "top"], reviewers=["plain"])
        held = boards()
        for board in held.values():
            board["rows"] = [row for row in board["rows"] if row["model"] == "Old 1"]
        for name, effort, share, cost in ROWS:
            row = aa(f"acme-{name}-1", f"Acme {name.title()} 1", effort, {
                "aa.intelligenceIndex": 50, "aa.frontierCode20": share,
                "aa.terminalBench40": share, "aa.omniscience": 100 * share,
                "aa.automationBenchPartialScore": share, "aa.price1mInputTokens": 1,
                "aa.price1mOutputTokens": 1, **{
                    f"aa.intelligenceIndexEvaluations.{slug}.costPerTask": cost
                    for slug in EVALUATIONS}})
            if DEFAULTS.get(name, "") == effort:
                row["slug"] = f"acme-{name}-1"
            held["artificialanalysis.ai"]["rows"].append(row)
            held["arena.ai"]["rows"].append({"model": f"Acme {name.title()} 1", "effort": effort,
                                            "values": {"arena.agent": share}})
        home.write(".agentkit/state/boards.json", held)
        home.write(".agentkit/state/usage.json", {"providers": {"anthropic": {"meters": [
            {"name": "weekly", "used": 40, "window_secs": 604800, "resets_at": NOW + 86400}]}}})
        # a week of $100 at a dollar a million tokens: the build's 0.2M tokens are 0.2 points
        history = History(home)
        history.week("anthropic", "default", "claude", "acme-top-1", 50e6, 50)
        history.run(("top", "high"), built=[[("default", "acme-top-1", (.2e6, 0, 0, 0))]])
        history.save()
        Seat(home, "acme-fix", model="fast", record=SEAT)

    def models(self, width=100, seat=None):
        """`r` on `c`, over `seat` or in a window of its own, once its lines are drawn."""
        term = Terminal(self.home, *(("attach", "--overlay") if seat else ()), size=(width, 40),
                        env={**ENV, **({"AGENTKIT_SESSION": seat} if seat else {})})
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        term.wait("esc leave")
        term.keys("c")
        term.wait("r recommended")
        term.keys("r")
        return term, term.wait("comparing all 4 models")

    def test_each_role_says_the_row_it_uses_at_its_effort_and_its_quality_and_cost(self):
        self.assertEqual(said(self.models()[1]), role_lines(NEW_SEATS, "orchestrate"))
        self.assertEqual(said(self.models(seat="acme-fix")[1]), role_lines(AT_SEAT, "orchestrate"))

    def test_up_and_down_move_the_pointer_and_enter_opens_why_the_role_uses_its_row(self):
        term, _ = self.models()
        on = lambda role: term.wait(lambda screen: "comparing" in screen
                                    and said(screen) == role_lines(NEW_SEATS, role))
        for key, role in (("Down", "execute"), ("Down", "review"), ("Down", "review"),
                          ("Up", "execute"), ("Up", "orchestrate"), ("Up", "orchestrate")):
            term.keys(key)
            on(role)
        for role, (_, row, *_) in NEW_SEATS.items():
            term.keys("Enter")
            term.wait(f"\n  why {row} {DOES[role]}\n")
            term.keys("Escape")
            on(role)
            term.keys("Down")

    def test_on_40_cells_each_roles_line_still_shows_its_quality_and_cost(self):
        shown = said(self.models(40)[1])
        for word, _, *numbers in NEW_SEATS.values():
            # its line, or the one under its word where the word takes a line of its own
            at = next(n for n, line in enumerate(shown) if word in line.split())
            self.assertTrue(any(line.endswith(" " + " ".join(numbers))
                                for line in shown[at:at + 2]), (word, shown))

    def test_ak_models_prints_the_same_lines(self):
        screen = said(self.models()[1])
        done = self.home.ak("models", env={**ENV, "COLUMNS": "100"})
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual(said(done.out), [line.replace("▸ ", "") for line in screen])
        self.assertEqual(said(done.out), role_lines(NEW_SEATS))
        done = self.home.ak("models", env={**ENV, "COLUMNS": "100", "AGENTKIT_SESSION": "acme-fix"})
        self.assertEqual((done.code, said(done.out)), (0, role_lines(AT_SEAT)), done.err)


if __name__ == "__main__":
    unittest.main()
