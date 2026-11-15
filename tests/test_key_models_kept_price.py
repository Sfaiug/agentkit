"""A take with ← or → on `r recommended` on `c` that changes the row its role uses keeps that
role's price, the owner's design of 5 Nov 2026: a round `limit` from the choice's cost up to the
cheapest compared row's both dearer and better, null for the best, with the `cost_unit` and the
`model` and `effort` the role then uses; a take onto a row no choice removes its role's alone,
and one that changes no row, a restart not picked, keeps and removes nothing.  A seat's are its
record's `<role>_price`, following a rename during the write; new seats' each a file of ak's
state, `models-<role>-price`, a write that fails saying why and the take standing.  A mark and
an effort step leave every one, and config.toml holds none.

Black-box: `AK_BIN` in a terminal (tests/fixtures/akterm.py) over a seat or in a window of its
own, its harness a fake running five of seven invented releases, the boards held as asked
(tests/test_key_role_choices.py); judged by the seats' records, ak's state and config.toml.
Fails against /bin/false.
"""

import fcntl
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
from test_key_role_choices import hold

SEAT, MOVED = "acme-fix", "acme-move"
# Release, name, quality in every role and cost a task, each at `high`: Base, Step, Fine and Top
# the choices; Gap and Mid no harness runs, compared and no choice; Dear beaten by Step
ROWS = [("acme-base-1", "Acme Base 1", 92, 0.12), ("acme-gap-1", "Acme Gap 1", 94, 0.80),
        ("acme-step-1", "Acme Step 1", 96, 1.00), ("acme-dear-1", "Acme Dear 1", 95, 2.00),
        ("acme-mid-1", "Acme Mid 1", 97, 3.00), ("acme-fine-1", "Acme Fine 1", 98, 4.20),
        ("acme-top-1", "Acme Top 1", 100, 5.00)]
NAMES = ("base", "step", "dear", "fine", "top")
CREW = {"orchestrator": "top", "workers": ["step"], "reviewers": ["dear"]}
GROUPS = {"orchestrator": "orchestrator", "executor": "workers", "reviewer": "reviewers"}
# The executor's takes from Step and the limit each keeps: Base 0.12 and Gap 0.80 keep 0.3; Step
# 1.00 and Mid 3.00 keep 2, Dear, dearer, being worse; Fine 4.20 and Top 5.00 keep 4.6; Top none.
# Base's row names no effort: its take keeps the effort Base runs at, `high`
TAKES = [("Left", "base", 0.3), ("Right", "step", 2), ("Right", "fine", 4.6),
         ("Right", "top", None)]


def price(model, limit=None):
    """The price a take of `model`'s choice keeps, at `high`, `limit` None for the best's."""
    return {"limit": limit, "cost_unit": "board_dollars", "model": model, "effort": "high"}


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class KeptPrice(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        cls.fake = fakeadapter.install(home, claude="pass")["claude"]
        cls.fake.answer("models", "".join(f"acme-{name}-1\tAcme {name.title()} 1\tmedium high\n"
                                          for name in NAMES))
        cls.seats = {name: Seat(home, name, model="top", record=CREW) for name in (SEAT, MOVED)}
        cls.state = home.path / ".agentkit/state"

    def fresh(self):
        """The config, the boards, the seats' records and no price kept, as each test starts."""
        akconfig.write(self.home, {name: {"harness": "claude", "model": f"acme-{name}-1"}
                                   for name in NAMES}, **CREW)
        hold(self.home, [(release, name, None if release == "acme-base-1" else "high",
                          quality / 100 - 0.1, cost) for release, name, quality, cost in ROWS])
        for name, seat in self.seats.items():
            self.home.write(f".agentkit/state/session-{name}.json", seat.record)
        for role in GROUPS:
            self.path(role).unlink(missing_ok=True)

    def path(self, role):
        """Where new seats' price for `role` is kept."""
        return self.state / f"models-{role}-price"

    def models(self, seat=None, recommended=True):
        """`c` over `seat`, else in a window of its own, and `r` on it where `recommended`."""
        term = Terminal(self.home, *(("attach", "--overlay") if seat else ()), size=(100, 60),
                        env={**ENV, **({"AGENTKIT_SESSION": seat} if seat else {})})
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        term.wait("esc leave")
        term.keys("c")
        term.wait("r recommended")
        if recommended:
            term.keys("r")
            term.wait("orchestrator · four choices")
        return term

    def record(self, seat):
        return json.loads((self.state / f"session-{seat}.json").read_text())

    def groups(self, seat=None):
        """Seat `seat`'s record, else [defaults]."""
        return self.record(seat) if seat else akconfig.read(self.home)["defaults"]

    def kept(self, seat=None):
        """{role: price} seat `seat`'s record keeps, else new seats' files in ak's state."""
        if seat:
            record = self.record(seat)
            return {role: record[f"{role}_price"] for role in GROUPS if f"{role}_price" in record}
        return {role: json.loads(self.path(role).read_text()) for role in GROUPS
                if self.path(role).exists()}

    def keeps(self, want, seat=None):
        """Wait for `seat`, else new seats, to keep the prices `want`, the take written first."""
        deadline = time.monotonic() + 30
        while self.kept(seat) != want and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertEqual(self.kept(seat), want)

    def until(self, test, what):
        deadline = time.monotonic() + 30
        while not test():
            self.assertLess(time.monotonic(), deadline, what)
            time.sleep(0.05)

    def test_a_take_keeps_the_round_price_up_to_the_next_row_dearer_and_better_the_best_none(self):
        for seat in (SEAT, None):
            with self.subTest(seat=seat):
                self.fresh()
                term = self.models(seat)
                term.keys("Down")
                for key, model, limit in TAKES:
                    term.keys(key)
                    self.keeps({"executor": price(model, limit)}, seat)
                    self.assertEqual(self.groups(seat)["workers"], [model])

    def test_a_take_back_onto_a_row_no_choice_removes_its_roles_price_and_no_other(self):
        for seat in (SEAT, None):
            with self.subTest(seat=seat):
                self.fresh()
                term = self.models(seat)
                term.keys("Down", "Left")
                self.keeps({"executor": price("base", 0.3)}, seat)
                term.keys("Down", "Right")          # off Dear, which the reviewer used
                self.keeps({"executor": price("base", 0.3), "reviewer": price("fine", 4.6)}, seat)
                term.keys("Left")
                self.until(lambda: self.groups(seat)["reviewers"] == ["dear"], "← took nothing")
                self.keeps({"executor": price("base", 0.3)}, seat)

    def test_a_seats_orchestrator_keeps_its_price_once_moved_and_none_where_kept(self):
        self.fresh()
        term = self.models(SEAT)                # its harness at its prompt: moved in place
        term.keys("Left")                       # off Top, onto Fine
        self.keeps({"orchestrator": price("fine", 4.6)}, SEAT)
        self.assertEqual(self.record(SEAT)["orchestrator"], "fine")
        pane = self.seats[MOVED].pane           # its harness ended: restarted, once asked
        self.home.tmux("respawn-pane", "-k", "-t", pane, "true")
        self.until(lambda: self.home.tmux("display-message", "-p", "-t", pane,
                                          "#{pane_dead}").out.strip() == "1", "it never ended")
        # Keep, another window having moved it meanwhile onto a choice and onto none: a price
        # kept before, whose model it no longer runs, stays as it was
        for other in ("base", "dear"):
            with self.subTest(other=other):
                self.fresh()
                stale = {**self.seats[MOVED].record, "orchestrator_price": price("top")}
                self.home.write(f".agentkit/state/session-{MOVED}.json", stale)
                term = self.models(MOVED)
                term.keys("Left")
                term.wait("× Restart")
                self.home.write(f".agentkit/state/session-{MOVED}.json",
                                {**stale, "orchestrator": other})
                term.keys("Enter")              # Keep
                term.wait(lambda screen: "orchestrator · four choices" in screen
                          and "× Restart" not in screen)
                self.assertEqual(self.kept(MOVED), {"orchestrator": price("top")})
        self.fresh()
        term = self.models(MOVED)
        term.keys("Down", "Left", "Up")
        self.keeps({"executor": price("base", 0.3)}, MOVED)
        term.keys("Left")
        term.wait("× Restart")
        term.keys("Down", "Enter")              # Restart
        self.keeps({"executor": price("base", 0.3), "orchestrator": price("fine", 4.6)}, MOVED)
        self.assertEqual(self.record(MOVED)["orchestrator"], "fine")

    def test_a_mark_and_an_effort_step_on_c_leave_every_price_and_config_toml_holds_none(self):
        every = {"orchestrator": price("fine", 4.6), "executor": price("base", 0.3),
                 "reviewer": price("fine", 4.6)}
        for seat in (SEAT, None):
            with self.subTest(seat=seat):
                self.fresh()
                marks = self.models(seat, recommended=False)    # another window's, open since
                term = self.models(seat)
                term.keys("Left", "Down", "Left", "Down", "Right")
                self.keeps(every, seat)
                marks.keys("Down", "Down", "Right", "Space")      # Dear builds too
                self.until(lambda: "dear" in self.groups(seat)["workers"], "the mark never landed")
                self.assertEqual(self.kept(seat), every)
                marks.keys("Right", "Space")                     # its build effort a step on
                self.until(lambda: "exec_effort" in (
                    self.record(seat)["efforts"]["dear"] if seat
                    else akconfig.read(self.home)["models"]["dear"]), "the step never landed")
                self.assertEqual(self.kept(seat), every)
                self.assertNotIn("cost_unit", json.dumps(akconfig.read(self.home)))

    def test_a_price_that_cannot_be_written_says_why_and_the_take_stands(self):
        self.fresh()
        self.path("executor").mkdir()           # a directory where the file goes
        self.addCleanup(self.path("executor").rmdir)
        term = self.models()
        term.keys("Down", "Left")
        term.wait("Is a directory")
        self.assertEqual(self.groups()["workers"], ["base"])

    def test_a_price_write_follows_a_rename_or_says_when_the_record_went(self):
        pane = self.seats[MOVED].pane
        gate = self.state / "watch.lock"
        record_lock = self.state / f".session-{MOVED}.lock"
        self.addCleanup((self.state / "session-acme-next.json").unlink, missing_ok=True)
        for moved in (True, False):
            with self.subTest(moved=moved):
                self.fresh()
                self.home.write(f".agentkit/state/session-{MOVED}.json",
                                {**self.seats[MOVED].record, "conversation": None})
                (self.state / "session-acme-next.json").unlink(missing_ok=True)
                self.home.tmux("respawn-pane", "-k", "-t", pane, "true")
                self.until(lambda: self.home.tmux("display-message", "-p", "-t", pane,
                                                  "#{pane_dead}").out.strip() == "1",
                           "it never ended")
                term = self.models(MOVED)
                term.keys("Left")
                term.wait("× Restart")
                with record_lock.open("a") as held:
                    with gate.open("a") as stop:
                        fcntl.flock(stop, fcntl.LOCK_EX)
                        term.keys("Down", "Enter")      # Restart: writes Fine, then waits on gate
                        self.until(lambda: waited_for(gate), "restart never reached watch.lock")
                        fcntl.flock(held, fcntl.LOCK_EX)
                    # watch.lock let go: seat_effort reads Fine, keep_price resolves MOVED and waits
                    self.until(lambda: waited_for(record_lock),
                               "keep_price never waited on the record lock")
                    if moved:
                        self.home.write(".agentkit/state/session-acme-next.json",
                                        self.record(MOVED))
                        self.home.write(f".agentkit/state/session-{MOVED}.json",
                                        {"renamed": "acme-next"})
                    else:
                        (self.state / f"session-{MOVED}.json").unlink()
                if moved:
                    self.keeps({"orchestrator": price("fine", 4.6)}, "acme-next")
                    self.assertEqual(self.record("acme-next")["orchestrator"], "fine")
                else:
                    term.wait(f"{MOVED} has no saved models")


def waited_for(path):
    """Does a process wait for that lock, as Linux's /proc/locks lists it: a `->` row on its
    inode."""
    inode = str(path.stat().st_ino)
    return any("->" in row.split() and row.split()[-3].rsplit(":", 1)[1] == inode
               for row in Path("/proc/locks").read_text().splitlines())


if __name__ == "__main__":
    unittest.main()
