"""A take (← → on a seat's models screen) and a flip (Space on its `c`) change the seat's record
as it stands when the key comes, another window having saved it since the screen opened.  For
each, on the executor and on the reviewer: the other role's marks saved since stay, in the
record and on the screen, and so does one naming a model the config gained since, in the
record; a flip keeps a mark another window gave its own role since.  A record naming no
reviewers reviews, after its executor's take, with the executors it had when the key came;
and a take of the model a role shows at another effort saves that model at that effort, the
record holding another for the role since.

Black-box: the program `AK_BIN` names in a terminal of 100 cells (tests/fixtures/akterm.py)
over a seat (tests/fixtures/akseat.py), its harness a fake running three of four invented
releases, one at two efforts, the boards held as just asked (tests/test_key_role_choices.py);
another window's save is the config and the record rewritten behind the open screen, the
record as ak writes one.  Judged by the seat's record and the screen.  Fails against /bin/false.
"""

from contextlib import contextmanager
import fcntl
import json
import re
import sys
from pathlib import Path
import threading
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import SERVER, Terminal
from test_key_models_answer import ENV
from test_key_role_choices import hold

SEAT = "acme-fix"
# Release, name, effort, every measure's share and cost a task: four choices a point or more
# apart, cheapest first, Step running at two efforts, and Gap, which no harness runs
ROWS = [("acme-base-1", "Acme Base 1", "high", 0.82, 2),
        ("acme-gap-1", "Acme Gap 1", "high", 0.84, 3),
        ("acme-step-1", "Acme Step 1", "medium", 0.86, 4),
        ("acme-step-1", "Acme Step 1", "high", 0.88, 5),
        ("acme-top-1", "Acme Top 1", "high", 0.90, 8)]
MODELS = {name: {"harness": "claude", "model": f"acme-{name}-1"}
          for name in ("base", "step", "top")}
FRESH = {"fresh": {"harness": "claude", "model": "acme-fresh-1"}}   # what the config gains
CREW = {"orchestrator": "base", "workers": ["base"], "reviewers": ["top"]}
# the keys onto each role's line of the models screen, and onto Step's mark of each on `c`
TO_ROLE = {"workers": ("Down",), "reviewers": ("Down", "Down")}
TO_MARK = {"workers": ("Down", "Right"), "reviewers": ("Down", "Right", "Right")}
LIT = {"workers": r"› Acme Step 1\s+○\s+\[□\]", "reviewers": r"› Acme Step 1\s+○\s+□\s+\[□\]"}
ROLE = {"workers": "executor", "reviewers": "reviewer"}
OTHER = {"workers": "reviewers", "reviewers": "workers"}


def marks(screen):
    """{model: its three marks} of each model's row on `c`."""
    return {found[1]: "".join(char for char in found[2] if char in "●○■□")
            for found in re.finditer(r"^[› ] (Acme \w+ 1)(.*)$", screen, re.MULTILINE)}


def uses(screen, field):
    """What the models screen's line for `field`'s role names: its model and effort."""
    found = re.search(rf"^[› ] {ROLE[field]}\s+(Acme \w+ 1 \w+)", screen, re.MULTILINE)
    return found and found[1]


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class RoleEditOnTheRecord(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        fake = fakeadapter.install(home, claude="pass")["claude"]
        fake.answer("models", "acme-base-1\tAcme Base 1\thigh\n"
                              "acme-step-1\tAcme Step 1\tmedium high\n"
                              "acme-top-1\tAcme Top 1\thigh\n")
        cls.seat = Seat(home, SEAT, model="base", record=CREW)
        cls.path = home.path / f".agentkit/state/session-{SEAT}.json"

    def opened(self, record, models=False):
        """Seat SEAT holding `record` and `c` open over it, its models screen on it (`r`) where
        `models`."""
        akconfig.write(self.home, MODELS, **CREW)
        hold(self.home, ROWS)
        self.save(record)
        term = Terminal(self.home, "attach", "--overlay", size=(100, 60),
                        env={**ENV, "AGENTKIT_SESSION": SEAT})
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        term.wait("esc leave")
        term.keys("c")
        term.wait("r recommended")
        if models:
            term.keys("r")
            term.wait("orchestrator · four choices")
        return term

    def since(self, record):
        """Another window's save behind the open screen: the config gaining FRESH, and the
        record `record`."""
        akconfig.write(self.home, {**MODELS, **FRESH}, **CREW)
        self.save(record)

    def record(self):
        return json.loads(self.path.read_text())

    @contextmanager
    def locked(self):
        """The seat's record held as each of ak's writers holds it while it reads, changes and
        writes it (config.update_session): one at a time, under its lock."""
        with self.path.with_name(f".{self.path.stem}.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def save(self, record):
        """The seat's record replaced by `record` as ak writes one, under its lock through the
        `.tmp` its writers share: an ak writing it as the save comes puts back nothing it read."""
        with self.locked():
            self.home.write(self.path.with_suffix(".tmp"), record).replace(self.path)

    def until(self, test, what):
        deadline = time.monotonic() + 30
        while not test():
            self.assertLess(time.monotonic(), deadline, what)
            time.sleep(0.05)

    def take(self, opened, saved, field, key):
        """`opened` the record as the models screen opens, `saved` as another window saves it
        then, and `key` taking `field`'s role on to Step; the record once it holds Step there."""
        term = self.opened(opened, models=True)
        term.keys(*TO_ROLE[field])
        term.wait(lambda screen: re.search(rf"› {ROLE[field]}", screen))
        self.since(saved)
        term.keys(key)
        self.until(lambda: self.record()[field] == ["step"], "the take took nothing")
        return term, self.record()

    def test_a_take_keeps_the_other_roles_marks_saved_since(self):
        crew = self.seat.record
        for field, key, other, shown in (("workers", "Right", ["base", "fresh"], "Acme Base 1 high"),
                                         ("reviewers", "Left", ["top", "fresh"], "Acme Top 1 high")):
            with self.subTest(role=ROLE[field]):
                term, record = self.take(crew, {**crew, OTHER[field]: other}, field, key)
                self.assertEqual(record[OTHER[field]], other)
                term.wait(lambda screen: uses(screen, OTHER[field]) == shown)

    def test_a_take_of_a_record_naming_no_reviewers_reviews_with_the_executors_it_had(self):
        legacy = {key: value for key, value in self.seat.record.items() if key != "reviewers"}
        _, record = self.take(legacy, {**legacy, "workers": ["top"]}, "workers", "Right")
        self.assertEqual(record["reviewers"], ["top"])

    def test_a_take_of_the_model_shown_at_another_effort_saves_it_with_that_effort(self):
        effort = {"workers": "exec_effort", "reviewers": "review_effort"}
        for field in ("workers", "reviewers"):
            with self.subTest(role=ROLE[field]):
                # Step at its entry's effort, high: Left takes it at medium
                opened = {**self.seat.record, field: ["step"], "efforts": {"step": {"effort": "high"}}}
                _, record = self.take(opened, {**opened, field: ["top"]}, field, "Left")
                self.assertEqual(record["efforts"]["step"][effort[field]], "medium")

    def test_a_save_since_outlasts_a_write_under_way(self):
        # an ak writing the record as the save comes, as an earlier screen's tick adds the `repo`
        # a record the test wrote lacks: the save waits for it, so it puts back nothing
        self.since(self.seat.record)
        with self.locked():
            read = self.record()
            saving = threading.Thread(target=self.since, args=({**read, "workers": ["top"]},))
            saving.start()
            saving.join(1)          # a save that waits for no lock is written by now
            self.home.write(self.path, {**read, "repo": None})
        saving.join()
        self.assertEqual(self.record()["workers"], ["top"])

    def test_a_flip_keeps_both_roles_marks_saved_since(self):
        crew = self.seat.record
        # each role's marks as another window saves them, and then each row's three on `c`
        for field, saved, shown in (
                ("workers", {"workers": ["base", "top"], "reviewers": ["base", "fresh"]},
                 {"Acme Base 1": "●■■", "Acme Step 1": "○■□", "Acme Top 1": "○■□"}),
                ("reviewers", {"workers": ["top", "fresh"], "reviewers": ["top", "base"]},
                 {"Acme Base 1": "●□■", "Acme Step 1": "○□■", "Acme Top 1": "○■■"})):
            with self.subTest(role=ROLE[field]):
                term = self.opened(crew)
                term.keys(*TO_MARK[field])
                term.wait(lambda screen: re.search(LIT[field], screen))
                self.since({**crew, **saved})
                term.keys("Space")
                self.until(lambda: "step" in self.record()[field], "the flip took nothing")
                record = self.record()
                self.assertEqual({key: record[key] for key in saved},
                                 {**saved, field: [*saved[field], "step"]})
                # the rows judged: Fresh's has one where `c` follows the config, and none where not
                term.wait(lambda screen: {name: marks(screen).get(name) for name in shown} == shown)


if __name__ == "__main__":
    unittest.main()
