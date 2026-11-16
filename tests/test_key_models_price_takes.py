"""Each time `r recommended` on `c` over a seat makes its answer (it opens, the boards land, `p`
turns a model on or off), the seat's executor and reviewer whose kept price holds
(tests/test_key_models_price_said.py) take the best of their choices that costs no more than its
limit, the best for none, where that is not the row the role uses, the owner's design of 5 Nov
2026: as ← and → take it, in one write of the record that also names the new model and effort
in the entry, its limit and unit as they were, saying `executor took Acme Mid 1 medium, the best
up to $0.30 a build` under the rows.  Where no choice costs that little the role stays; one marked
onto another model since keeps none that holds and stays; a record changed or renamed after
the screen judged it is written nothing, nothing is said and the screen stays as it was; a take
refused, its model since gone from the config, says why and the role stays.  The seat's
orchestrator stays, as moving it moves the seat's own session, its heading saying what it keeps.

Black-box: `AK_BIN` in a terminal (tests/fixtures/akterm.py) over a seat, a fake harness running
five invented releases, the boards held as asked (tests/test_key_role_choices.py); judged by
the screen and the seat's record.  Fails against /bin/false.
"""

import fcntl
import json
import re
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
from test_key_models_kept_price import waited_for
from test_key_models_price_said import more, uses
from test_key_role_choices import hold

SEAT, MOVED = "acme-fix", "acme-move"
# Release, name, effort, quality in every role and cost a task, each a choice; Mid's cost the
# one a test holds: under the executor's limit of 0.3, or over it
ROWS = [("acme-base-1", "Acme Base 1", "high", 92, 0.12),
        ("acme-step-1", "Acme Step 1", "high", 94, 0.25),
        ("acme-mid-1", "Acme Mid 1", "medium", 96, None),
        ("acme-fine-1", "Acme Fine 1", "high", 98, 3.00),
        ("acme-top-1", "Acme Top 1", "high", 100, 5.00)]
CHEAP, DEAR = 0.28, 1.00
NAMES = ("base", "step", "mid", "fine", "top")
CREW = {"orchestrator": "top", "workers": ["step"], "reviewers": ["fine"]}
MID = "executor took Acme Mid 1 medium, the best up to $0.30 a build"


def under(screen):
    """What the models screen says under its rows, between its comparing line and its keys, on
    one line."""
    lines = screen.split("\n")
    first = next(n for n, line in enumerate(lines) if "comparing" in line)
    return " ".join(" ".join(lines[first + 1:next(
        n for n, line in enumerate(lines) if "u unit" in line)]).split())


def price(model, effort="high", limit=0.3):
    """The price a role keeps on `model` at `effort`, up to `limit`, None for the best."""
    return {"limit": limit, "cost_unit": "board_dollars", "model": model, "effort": effort}


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class PriceTakes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        fakeadapter.install(home, claude="pass")["claude"].answer("models", "".join(
            f"acme-{name}-1\tAcme {name.title()} 1\tmedium high\n" for name in NAMES))
        cls.seat = Seat(home, SEAT, model="top", record=CREW)
        cls.state = home.path / ".agentkit/state"

    def fresh(self, off=(), **record):
        """The config with the releases `off` turned off, the boards with Mid cheap, and the
        seat's record with `record` over it, as a test starts."""
        self.configure(NAMES, off)
        self.boards(CHEAP)
        self.home.write(f".agentkit/state/session-{SEAT}.json", {**self.seat.record, **record})

    def configure(self, names, off=()):
        """The config's models `names`, the releases `off` turned off."""
        akconfig.write(self.home, {name: {"harness": "claude", "model": f"acme-{name}-1"}
                                   for name in names},
                       settings={"models_off": list(off)} if off else None, **CREW)

    def boards(self, mid):
        """The boards holding Mid at cost `mid`, the answer made anew from them as they land."""
        hold(self.home, [(release, name, effort, quality / 100 - 0.1, mid if cost is None else cost)
                         for release, name, effort, quality, cost in ROWS])
        (self.state / "matrix.json").unlink(missing_ok=True)

    def record(self):
        return json.loads((self.state / f"session-{SEAT}.json").read_text())

    def records(self):
        """Every seat's record as it stands, by its file's name."""
        return {path.name: path.read_text() for path in self.state.glob("session-*.json")}

    def roles(self):
        """What of the seat's record a take writes: its roles, their efforts and prices."""
        return {key: value for key, value in self.record().items()
                if key in ("orchestrator", "workers", "reviewers", "efforts")
                or key.endswith("_price")}

    def config(self):
        """`c` over the seat."""
        term = Terminal(self.home, "attach", "--overlay", size=(100, 60),
                        env={**ENV, "AGENTKIT_SESSION": SEAT})
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        term.wait("esc leave")
        term.keys("c")
        term.wait("r recommended")
        return term

    def recommended(self, term):
        """`r` on `c`, once the boards landed: its answer made of them."""
        term.keys("r")
        term.wait("boards read")
        return term

    def turn(self, term, *names):
        """`p`, and each model `names` turned on or off in it, the list left open."""
        term.keys("p")
        shown = term.wait(lambda screen: "a add a company" in screen and "Acme Top 1" in screen)
        marks = {name: mark for mark, name in re.findall(r"([■□]) (Acme \w+ 1)", shown)}
        at = 0          # the company's name; its models after it
        for name in names:
            to = list(marks).index(name) + 1
            term.keys(*["Right" if to > at else "Left"] * abs(to - at), "Space")
            at = to
        term.wait(lambda screen: all(f"{'■□'.replace(marks[name], '')} {name}" in screen
                                     for name in names))

    def switch(self, term, *names):
        """`turn` and Esc: the screen's answer made anew."""
        self.turn(term, *names)
        term.keys("Escape")
        term.wait("comparing")

    def said(self, term, text):
        term.wait(lambda screen: text in " ".join(screen.split()))

    def until(self, test, what):
        deadline = time.monotonic() + 30
        while not test():
            self.assertLess(time.monotonic(), deadline, what)
            time.sleep(0.05)

    def test_a_better_model_as_cheap_as_the_limit_is_taken_by_the_next_screen_and_said(self):
        self.fresh(executor_price=price("step"))
        self.boards(DEAR)
        before = self.roles()
        self.recommended(self.config())
        self.assertEqual(self.roles(), before)
        self.boards(CHEAP)
        term = self.recommended(self.config())
        self.said(term, MID)
        record = self.record()
        self.assertEqual((record["workers"], record["executor_price"], record["reviewers"]),
                         (["mid"], price("mid", "medium"), ["fine"]))
        self.assertEqual(record["efforts"]["mid"]["exec_effort"], "medium")

    def test_the_model_taken_turned_off_in_p_takes_the_next_best_and_on_again_takes_it(self):
        self.fresh(executor_price=price("step"))
        term = self.recommended(self.config())
        self.said(term, MID)
        for names, said, model, effort in (
                (["Acme Mid 1"], "executor took Acme Step 1 high, the best up to $0.30 a build",
                 "step", "high"),
                (["Acme Mid 1"], MID, "mid", "medium")):
            self.switch(term, *names)
            self.said(term, said)
            record = self.record()
            self.assertEqual((record["workers"], record["executor_price"]),
                             ([model], price(model, effort)))
        before = self.roles()
        self.switch(term, "Acme Base 1", "Acme Step 1", "Acme Mid 1")   # Fine and Top: dearer
        term.wait(lambda screen: "comparing 2 of 5 models" in screen
                  and uses(screen, "executor") == "Acme Mid 1")
        self.assertEqual(self.roles(), before)

    def test_an_entry_with_no_limit_takes_the_best_once_a_better_one_is_compared(self):
        self.fresh(off=["acme-top-1"], reviewer_price=price("fine", limit=None))
        term = self.recommended(self.config())
        self.assertEqual(self.record()["reviewers"], ["fine"])     # the best compared
        self.switch(term, "Acme Top 1")
        self.said(term, "reviewer took Acme Top 1 high, the best, whatever it costs")
        record = self.record()
        self.assertEqual((record["reviewers"], record["reviewer_price"]),
                         (["top"], price("top", limit=None)))

    def test_a_reviewer_marked_onto_another_model_on_c_since_stays(self):
        self.fresh(reviewer_price=price("fine", limit=None))
        term = self.config()
        term.keys("Down", "Down", "Right", "Right", "Space")       # Mid reviews
        self.until(lambda: self.record()["reviewers"] == ["fine", "mid"], "Mid never marked")
        term.keys("Down", "Space")                                  # and Fine no longer
        self.until(lambda: self.record()["reviewers"] == ["mid"], "Fine never unmarked")
        before = self.roles()
        self.recommended(term)
        self.assertEqual(self.roles(), before)

    def test_a_record_saved_after_the_screen_judged_it_stays_and_a_model_gone_says_why(self):
        def marked():       # onto Fine
            self.home.write(f".agentkit/state/session-{SEAT}.json",
                            {**self.record(), "workers": ["fine"]})

        def renamed():
            self.addCleanup((self.state / f"session-{MOVED}.json").unlink, missing_ok=True)
            self.home.write(f".agentkit/state/session-{MOVED}.json", self.record())
            self.home.write(f".agentkit/state/session-{SEAT}.json", {"renamed": MOVED})

        def removed():      # Mid, judged, from the config
            self.configure([name for name in NAMES if name != "mid"])
        # another window's mark or rename: nothing written, said or read again; Mid removed:
        # refused, saying why
        for change, said in ((marked, None), (renamed, None), (removed, "unknown model 'mid'")):
            with self.subTest(change=change.__name__):
                self.fresh(off=["acme-mid-1"], executor_price=price("step"))
                term = self.recommended(self.config())
                self.turn(term, "Acme Mid 1")
                lock = self.state / f".session-{SEAT}.lock"
                with lock.open("a") as held:
                    fcntl.flock(held, fcntl.LOCK_EX)
                    term.keys("Escape")     # Mid compared: the take, judged on Step, waits
                    self.until(lambda: waited_for(lock), "the take never waited on the lock")
                    change()
                    saved = self.records()
                # the screen, drawn once the take ended down to its keys, as it was
                term.wait(lambda screen: "comparing" in screen and "u unit" in screen
                          and uses(screen, "executor") == "Acme Step 1"
                          and (said in under(screen) if said else under(screen) == ""))
                self.assertEqual(self.records(), saved)

    def test_a_seats_orchestrator_stays_where_a_cheaper_better_choice_fits_its_limit(self):
        kept = price("step")
        self.fresh(orchestrator="step", orchestrator_price=kept, executor_price=kept)
        term = self.recommended(self.config())
        self.said(term, MID)
        term.wait(lambda screen: more(screen, "orchestrator")
                  == "keeps the best up to $0.30 a task")
        record = self.record()
        self.assertEqual((record["orchestrator"], record["orchestrator_price"]), ("step", kept))


if __name__ == "__main__":
    unittest.main()
