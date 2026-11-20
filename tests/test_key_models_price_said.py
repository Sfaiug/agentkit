"""`r recommended` on `c` says the price the highlighted role keeps
(tests/test_key_models_kept_price.py) where it holds, the owner's design of 5 Nov 2026: the
heading over its bars ends with one more part, joined and wrapped as its others are, `keeps the
best up to $0.30 a build`, the limit in the unit it was kept in whatever `u` counts in, to two
decimals or every figure it has, or `keeps the best, whatever it costs`; `no choice up to $0.10
a build` where every choice a configured model runs costs more, as the role then stays
(tests/test_key_models_price_takes_new_seats.py).  It holds while the role uses the model and
effort it names, and one with a limit while the role's costs are counted
in its unit: a role marked onto another model on `c` says nothing more, and marked back says it
again; one with no price says nothing more.

Black-box: `AK_BIN` in terminals of 100 and 40 cells (tests/fixtures/akterm.py) over a seat or
in a window of its own, a fake harness running five of seven invented releases, the boards held
as asked (tests/test_key_role_choices.py); judged by the screen.  Fails against /bin/false.
"""

import re
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import SERVER, Terminal
from test_key_models_answer import ENV
from test_key_role_choices import hold

SEAT = "acme-fix"
# Release, name, quality in every role and cost a task, each at `high`: Base, Step, Fine and Top
# the choices, Base's take keeping 0.3, Fine's 4.6 and Top's none; Gap and Mid no harness runs
ROWS = [("acme-base-1", "Acme Base 1", 92, 0.12), ("acme-gap-1", "Acme Gap 1", 94, 0.80),
        ("acme-step-1", "Acme Step 1", 96, 1.00), ("acme-dear-1", "Acme Dear 1", 95, 2.00),
        ("acme-mid-1", "Acme Mid 1", 97, 3.00), ("acme-fine-1", "Acme Fine 1", 98, 4.20),
        ("acme-top-1", "Acme Top 1", 100, 5.00)]
NAMES = ("base", "step", "dear", "fine", "top")      # as `c` lists them
CREW = {"orchestrator": "top", "workers": ["step"], "reviewers": ["dear"]}
FIELDS = {"executor": "executor_price", "reviewer": "reviewer_price"}
BASE = "keeps the best up to $0.30 a build"


def more(screen, word):
    """What the heading over `word`'s bars says after counting them, its lines' words on one
    line; None before it is drawn.  The bars' top line under it holds no word."""
    shown = screen.split("\n")
    head = next((n for n, line in enumerate(shown) if line.strip().startswith(word + " · ")), None)
    if head is None:
        return None
    lines = []
    for line in shown[head:]:
        if not re.search("[a-z]", line):
            break
        lines.append(line)
    words = " ".join(part for part in " ".join(lines).split() if part != "·")
    return re.fullmatch(r"\S+ \S+ choices?(?: \S+ more shaded)? ?(.*)", words)[1]


def answered(screen):
    """Whether the orchestrator's bars stand as the boards answer, a frame before having no choice
    to take, its heading saying nothing more, as it keeps no price."""
    return "orchestrator · four choices" in screen and more(screen, "orchestrator") == ""


def uses(screen, word):
    """The model `word`'s role line names, beside its word or, too wide for that, under it."""
    found = re.search(rf"^. {word} +(?:\S+ +\S+\n +)?(Acme \w+ 1)", screen, re.M)
    return found and found[1]


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class PriceSaid(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        fakeadapter.install(home, claude="pass")["claude"].answer("models", "".join(
            f"acme-{name}-1\tAcme {name.title()} 1\tmedium high\n" for name in NAMES))
        cls.seat = Seat(home, SEAT, model="top", record=CREW)
        cls.state = home.path / ".agentkit/state"

    def fresh(self, off=()):
        """The config, the releases `off` turned off, the boards and the seat's record as each
        test starts, no price kept and the screen counting in dollars."""
        akconfig.write(self.home, {name: {"harness": "claude", "model": f"acme-{name}-1"}
                                   for name in NAMES},
                       settings={"models_off": list(off)} if off else None, **CREW)
        hold(self.home, [(release, name, None if release == "acme-base-1" else "high",
                          quality / 100 - 0.1, cost) for release, name, quality, cost in ROWS])
        self.home.write(f".agentkit/state/session-{SEAT}.json", self.seat.record)
        for path in [self.state / "models-unit", *(self.state / f"models-{word}-price"
                                                   for word in FIELDS)]:
            path.unlink(missing_ok=True)

    def keep(self, seat, word, entry):
        """`entry` as the price `word`'s role keeps on seat `seat`, else on new seats."""
        if seat:
            self.home.write(f".agentkit/state/session-{SEAT}.json",
                            {**self.seat.record, FIELDS[word]: entry})
        else:
            self.home.write(f".agentkit/state/models-{word}-price", entry)

    def models(self, seat=None, width=100, ready=answered):
        """`r` on `c` over `seat`, else in a window of its own, `width` cells wide, once it
        shows `ready`."""
        term = Terminal(self.home, *(("attach", "--overlay") if seat else ()), size=(width, 60),
                        env={**ENV, **({"AGENTKIT_SESSION": seat} if seat else {})})
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        term.wait("esc leave")
        term.keys("c")
        term.wait("r recommended")
        term.keys("r")
        term.wait(ready)
        return term

    def says(self, term, word, said, model=None):
        """Wait for `word`'s heading to end with `said`, "" for nothing more, its role using
        `model` where one is named."""
        term.wait(lambda screen: more(screen, word) == said
                  and (model is None or uses(screen, word) == model))

    def test_a_take_says_the_limit_kept_on_a_seat_and_new_seats_at_100_and_40_and_after_u(self):
        for seat in (SEAT, None):
            for width in (100, 40):
                with self.subTest(seat=seat, width=width):
                    self.fresh()
                    term = self.models(seat, width)
                    term.keys("Down")
                    self.says(term, "executor", "", "Acme Step 1")
                    term.keys("Left")
                    self.says(term, "executor", BASE, "Acme Base 1")
                    term.keys("u")
                    term.wait(lambda screen: "% of a week" in screen
                              and more(screen, "executor") == BASE)

    def test_a_take_of_the_best_says_whatever_it_costs(self):
        self.fresh()
        term = self.models()
        term.keys("Down", "Right", "Right")         # Step, Fine, Top
        self.says(term, "executor", "keeps the best, whatever it costs", "Acme Top 1")

    def test_a_limit_says_every_figure_and_one_in_another_unit_or_none_says_nothing_more(self):
        for seat in (SEAT, None):
            for unit, said in (("board_dollars", "no choice up to $0.105 a build"),
                               ("money", "")):
                with self.subTest(seat=seat, unit=unit):
                    self.fresh()
                    # under every choice's cost, so its executor takes none
                    self.keep(seat, "executor", {"limit": 0.105, "cost_unit": unit,
                                                 "model": "step", "effort": "high"})
                    term = self.models(seat)
                    term.keys("Down")
                    self.says(term, "executor", said, "Acme Step 1")

    def test_a_kept_price_no_choice_costs_as_little_as_says_so(self):
        every = [release for release, *_ in ROWS]
        for seat in (SEAT, None):
            # under every choice's cost, Base's 0.12 the least; Step's 1.00, no better one; and
            # none, leaving no choice out though every release is off and none runs
            for limit, off, said in ((0.105, (), "no choice up to $0.105 a build"),
                                     (1.5, (), "keeps the best up to $1.50 a build"),
                                     (None, every, "keeps the best, whatever it costs")):
                with self.subTest(seat=seat, limit=limit):
                    self.fresh(off)
                    self.keep(seat, "executor", {"limit": limit, "cost_unit": "board_dollars",
                                                 "model": "step", "effort": "high"})
                    term = self.models(seat, ready="comparing 0 of" if off else answered)
                    term.keys("Down")
                    self.says(term, "executor", said, "Acme Step 1")
                    for unit in ("% of a week", "a week"):     # each `u` turns to
                        term.keys("u")
                        term.wait(lambda screen: f"quality  {unit}" in screen
                                  and more(screen, "executor") == said
                                  and uses(screen, "executor") == "Acme Step 1")

    def test_a_reviewer_marked_onto_another_model_says_nothing_more_and_marked_back_again(self):
        self.fresh()
        term = self.models(SEAT)
        term.keys("Down", "Down", "Right")              # off Dear, onto Fine
        self.says(term, "reviewer", "keeps the best up to $4.60 a review", "Acme Fine 1")
        # on `c`, Fine's review mark and Top's under it: Top reviews, then Fine no longer; and back
        for there, said, model in (
                (("Down", "Down", "Down", "Right", "Right", "Down", "Space", "Up", "Space"), "",
                 "Acme Top 1"),
                (("Space", "Down", "Space"), "keeps the best up to $4.60 a review",
                 "Acme Fine 1")):
            term.keys("Escape")
            term.wait("r recommended")
            term.keys(*there)
            term.keys("r")
            term.wait(answered)
            term.keys("Down", "Down")
            self.says(term, "reviewer", said, model)


if __name__ == "__main__":
    unittest.main()
