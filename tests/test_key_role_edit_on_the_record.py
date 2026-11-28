"""A flip (Space on a seat's `c`) changes the seat's record as it stands when the key comes,
another window having saved it since the screen opened: on the executor and on the reviewer,
both roles' marks saved since stay, in the record and on the screen, including one naming a
model the config gained since.

Black-box: the program `AK_BIN` names in a terminal of 100 cells (tests/fixtures/akterm.py)
over a seat (tests/fixtures/akseat.py), its harness a fake running three invented releases;
another window's save is the config and the record rewritten behind the open screen, the
record as ak writes one.  Judged by the seat's record and the screen.  Fails against /bin/false.
"""

import fcntl
import json
import os
import re
import sys
from pathlib import Path
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import SERVER, Terminal
from fixtures.akboards import ENV

SEAT = "acme-fix"
MODELS = {name: {"harness": "claude", "model": f"acme-{name}-1"}
          for name in ("base", "step", "top")}
FRESH = {"fresh": {"harness": "claude", "model": "acme-fresh-1"}}   # what the config gains
CREW = {"orchestrator": "base", "workers": ["base"], "reviewers": ["top"]}
# the keys onto Step's mark of each role on `c`
TO_MARK = {"workers": ("Down", "Right"), "reviewers": ("Down", "Right", "Right")}
LIT = {"workers": r"› Acme Step 1\s+○\s+\[□\]", "reviewers": r"› Acme Step 1\s+○\s+□\s+\[□\]"}
ROLE = {"workers": "executor", "reviewers": "reviewer"}


def marks(screen):
    """{model: its three marks} of each model's row on `c`."""
    return {found[1]: "".join(char for char in found[2] if char in "●○■□")
            for found in re.finditer(r"^[› ] (Acme \w+ 1)(.*)$", screen, re.MULTILINE)}


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

    def opened(self, record):
        """Seat SEAT holding `record` and `c` open over it."""
        akconfig.write(self.home, MODELS, **CREW)
        self.save(record)
        term = Terminal(self.home, "attach", "--overlay", size=(100, 60),
                        env={**ENV, "AGENTKIT_SESSION": SEAT})
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        term.wait("esc leave")
        term.keys("c")
        term.wait("r your runs")
        return term

    def since(self, record):
        """Another window's save behind the open screen: the config gaining FRESH, and the
        record `record`."""
        akconfig.write(self.home, {**MODELS, **FRESH}, **CREW)
        self.save(record)

    def record(self):
        return json.loads(self.path.read_text())

    @property
    def lock(self):
        """The file ak's writers of the record lock, one at a time (config.record_lock_path)."""
        return self.path.with_name(f".{self.path.stem}.lock")

    def save(self, record):
        """The seat's record replaced by `record` as ak writes one, under its lock through the
        `.tmp` its writers share: an ak writing it as the save comes puts back nothing it read."""
        with self.lock.open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            self.home.write(self.path.with_suffix(".tmp"), record).replace(self.path)

    def until(self, test, what):
        deadline = time.monotonic() + 30
        while not test():
            self.assertLess(time.monotonic(), deadline, what)
            time.sleep(0.05)

    def test_a_save_since_outlasts_a_write_under_way(self):
        # an ak tick under way as the save comes, as an earlier screen's adds the `repo` a record
        # the test wrote lacks: it holds the record's lock from reading the record to writing it
        # back, so a save asking for that lock is written after it, and one that does not, before
        self.since(self.seat.record)
        read, flock, ticked = self.record(), fcntl.flock, []

        def tick():
            ticked.append(self.home.write(self.path, {**read, "repo": None}))

        def asked(file, operation):
            held = os.fstat(file if isinstance(file, int) else file.fileno())
            if (operation == fcntl.LOCK_EX and not ticked
                    and os.path.samestat(held, self.lock.stat())):
                tick()
            return flock(file, operation)
        with patch.object(fcntl, "flock", asked):
            self.since({**read, "workers": ["top"]})
        if not ticked:
            tick()
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
