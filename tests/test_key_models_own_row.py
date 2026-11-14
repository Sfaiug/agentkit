"""On `r recommended` on `c` the row a role uses, where it is no choice, stands among the role's
bars: shaded, its why under it as `others` have theirs, `━` under it while in use, in the first
of the shaded places, a sixth bar beside five choices.  Once shown it stays until the screen
closes, and ← and → step onto it at its cost's place among the choices, taking the model and
the effort the role used: the owner, 12 Nov 2026.  `ak models` draws it the same.

Black-box: the program `AK_BIN` names in a terminal of 100 cells and of 40 (tests/fixtures/
akterm.py), over a seat (tests/fixtures/akseat.py) or in a window of its own, and as `ak models`,
its harness a fake, the boards held as just asked (tests/test_key_role_choices.py); judged by
the bars (tests/test_key_models_bars.py reads them), the seat's record and config.toml.  Fails
against /bin/false.
"""

import json
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import SERVER, Terminal
from test_key_models_answer import ENV
from test_key_models_bars import bars, drawn
from test_key_role_choices import hold

SEAT = "acme-fix"
LOW = ("acme-low-1", "Acme Low 1", "medium", 89, 1)
# Release, name, effort, quality in every role and cost a task, cheapest first: Low, 11 points
# under the best, then three choices; Near close to Base and Dear beaten by Step, the best two
# others, so Low is no bar but the one a role uses
ROWS = [LOW, ("acme-base-1", "Acme Base 1", "high", 92, 2),
        ("acme-near-1", "Acme Near 1", "high", 92.5, 3),
        ("acme-step-1", "Acme Step 1", "high", 96, 4),
        ("acme-dear-1", "Acme Dear 1", "high", 95, 6),
        ("acme-top-1", "Acme Top 1", "high", 100, 8)]
# Low under five choices
FIVE = [LOW, *((f"acme-{word.lower()}-1", f"Acme {word} 1", "high", quality, cost)
               for word, quality, cost in (("Base", 91, 2), ("Mid", 93, 3), ("Step", 95, 4),
                                           ("Wide", 97, 6), ("Top", 100, 8)))]
# What the reviewer's bars say, left to right: name, quality, cost, why (a choice none), effort
BARS = [("Acme Low 1", "89.0", "≈$1.00", "░ far below", "medium"),
        ("Acme Base 1", "92.0", "≈$2.00", None, "high"),
        ("Acme Step 1", "96.0", "≈$4.00", None, "high"),
        ("Acme Dear 1", "95.0", "≈$6.00", "░ beaten", "high"),
        ("Acme Top 1", "100.0", "≈$8.00", None, "high")]
HEADING = "reviewer · three choices · two more shaded"
# Low reviews at medium, on [defaults] and on the seat, Top does the rest; every choice is a
# configured model's, as only those are choices (tests/test_key_models_choices_are_yours.py)
MODELS = {"low": {"harness": "claude", "model": "acme-low-1", "review_effort": "medium"},
          **{word: {"harness": "claude", "model": f"acme-{word}-1"}
             for word in ("base", "mid", "step", "wide", "top")}}
CREW = {"orchestrator": "top", "workers": ["top"], "reviewers": ["low"]}
EFFORTS = {"low": {"effort": "high", "review_effort": "medium"}}


def want(marked):
    """BARS, each with a why shaded and only those, the dearer taller, `marked`'s marked."""
    return BARS, True, True, [marked]


def held(home, rows):
    """`home` holding the boards of `rows`, the harness running those MODELS names, and
    [defaults] CREW."""
    fakeadapter.install(home, claude="pass")["claude"].answer("models", "".join(
        f"{release}\t{name}\tmedium high\n" for release, name, *_ in rows
        if release in {entry["model"] for entry in MODELS.values()}))
    akconfig.write(home, MODELS, **CREW)
    hold(home, [(release, name, effort, quality / 100 - 0.1, cost)
                for release, name, effort, quality, cost in rows])


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class OwnRow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.seat = Seat(cls.home, SEAT, model="top", record={**CREW, "efforts": EFFORTS})

    def fresh(self):
        """The config, the boards and the seat's record as each test starts from them."""
        held(self.home, ROWS)
        self.home.write(f".agentkit/state/session-{SEAT}.json", self.seat.record)

    def reviewer(self, width, seat=None):
        """`r` on `c`, `width` cells wide, over `seat` or in a window of its own, `▸` moved to
        the reviewer once its bars stand with Low in use."""
        term = Terminal(self.home, *(("attach", "--overlay") if seat else ()), size=(width, 60),
                        env={**ENV, **({"AGENTKIT_SESSION": seat} if seat else {})})
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        term.wait("esc leave")
        term.keys("c")
        term.wait("r recommended")
        term.keys("r")
        term.wait("orchestrator · ")
        term.keys("Down", "Down")
        term.wait(lambda screen: drawn(screen, "reviewer") == want("Acme Low 1"))
        return term

    def record(self):
        return json.loads((self.home.path / f".agentkit/state/session-{SEAT}.json").read_text())

    def until(self, test, what):
        deadline = time.monotonic() + 30
        while not test():
            self.assertLess(time.monotonic(), deadline, what)
            time.sleep(0.05)

    def test_a_seats_reviewer_stays_a_bar_and_a_step_once_the_next_choice_is_taken(self):
        for width in (100, 40):
            with self.subTest(width=width):
                self.fresh()
                term = self.reviewer(width, SEAT)
                term.keys("Right")          # Base, at twice Low's cost
                self.until(lambda: self.record()["reviewers"] == ["base"], "→ took nothing")
                term.wait(lambda screen: drawn(screen, "reviewer") == want("Acme Base 1"))
                term.keys("Left")
                self.until(lambda: self.record()["reviewers"] == ["low"], "← took nothing")
                record = self.record()
                self.assertEqual(record["efforts"]["low"], EFFORTS["low"])
                self.assertEqual((record["orchestrator"], record["workers"]), ("top", ["top"]))
                term.wait(lambda screen: drawn(screen, "reviewer") == want("Acme Low 1"))

    def test_on_new_seats_the_round_trip_leaves_the_defaults_mark_as_it_was(self):
        self.fresh()
        term = self.reviewer(100)
        reviewers = lambda: akconfig.read(self.home)["defaults"]["reviewers"]
        term.keys("Right")
        self.until(lambda: reviewers() == ["base"], "→ took nothing")
        term.wait(lambda screen: drawn(screen, "reviewer") == want("Acme Base 1"))
        term.keys("Left")
        self.until(lambda: reviewers() == ["low"], "← took nothing")
        saved = akconfig.read(self.home)
        self.assertEqual(saved["defaults"], CREW)
        self.assertEqual(saved["models"]["low"]["review_effort"], "medium")
        term.wait(lambda screen: drawn(screen, "reviewer") == want("Acme Low 1"))

    def test_ak_models_draws_it(self):
        self.fresh()
        done = self.home.ak("models", env={**ENV, "COLUMNS": "100"})
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual(drawn(done.out, "reviewer"), want("Acme Low 1"), done.out)
        self.assertIn("\n  " + HEADING + "\n", done.out)

    def test_beside_five_choices_it_is_a_sixth_bar(self):
        with Home() as home:
            held(home, FIVE)
            done = home.ak("models", env={**ENV, "COLUMNS": "100"})
        self.assertEqual(done.code, 0, done.err)
        self.assertIn("\n  reviewer · five choices · one more shaded\n", done.out)
        found = bars(done.out, "reviewer")
        self.assertEqual([(bar["name"], bar["why"], bar["marked"]) for bar in found],
                         [("Acme Low 1", "░ far below", True),
                          *((name, None, False) for _, name, *_ in FIVE[1:])], done.out)


if __name__ == "__main__":
    unittest.main()
