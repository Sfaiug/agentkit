"""`ak run status` says, under a waiting run's row, where it waits: its place in a landing line,
or in the slots queue.

A run that passed waits in its repository and target's landing line, and its line reads its place
there, in join order, and the target it lands on.  A run waiting for a slot is listed in
`runs/.slots.queue` as the last poll left it: a run behind the queue's first reads how many are
queued before it, and that the run limit is full while the queue's running runs fill it, unless
its record says `first`, which skips the limit.  The queue's first, and a run the queue does not
list, read the reason their own record keeps.  The other lines under a row are other keys', so
only the lines saying what the run waits for are read here.

Black-box: the runs are records written by hand where ak keeps them, and the program `AK_BIN`
names runs from outside through tests/fixtures/akbin.py; this test fails against `/bin/false`.
"""

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home, owner

PLACES = ("1st 2nd 3rd 4th 5th 6th 7th 8th 9th 10th 11th 12th 13th 14th 15th 16th 17th 18th "
          "19th 20th 21st 22nd").split()
# A run lands in the order it joined its line, not the order it started: the one started last
# joins first here.
MAIN = [f"20261107-09{58 - 2 * place:02d}-land-part-{place}" for place in range(1, 23)]
RELEASE = "20261107-1000-cut-the-release"
QUEUED, FIRST, UNLISTED = (["20261107-1101-queue-one", "20261107-1102-queue-two",
                            "20261107-1103-queue-three"],
                           ["20261107-1104-fix-first", "20261107-1105-fix-second"],
                           "20261107-1106-queue-unlisted")
REASONS = {run: f"waiting for memory · {free} G free, needs 3 G"
           for free, run in enumerate([*QUEUED, *FIRST, UNLISTED], start=1)}


def lock(target):
    """A landing line's name, as ak names the lock of one repository and target."""
    digest = hashlib.sha256(f"github.com/acme/widget\n{target}".encode()).hexdigest()
    return f".merge-{digest}.lock"


def record(home, run_id, **fields):
    home.write(f".agentkit/runs/{run_id}/run.json",
               {"run_id": run_id, "title": run_id[14:].replace("-", " ").capitalize(),
                "executor": "opus", "reviewer": "astra", "rounds": 2, **fields})


def wait_lines(out):
    """Each run's lines saying what it waits for, as printed under its row."""
    said, run = {}, None
    for line in out.splitlines():
        if not line.startswith(" "):
            run = said.setdefault(line.split(" ", 1)[0], [])
        elif line.startswith("  waiting"):
            run.append(line.strip())
    return said


class WaitingRunSaysWhereItWaits(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        now = time.time()
        for place, run in enumerate(MAIN, start=1):
            record(home, run, state="waiting", base="origin/main", target="origin/main",
                   started_at=now - 2 * 3600 - 60 * place, round_summaries=[{}],
                   waiting_on={"line": lock("main"), "joined": now - 3600 + 60 * place})
        # joined before every run in the main line, and based on main: only its target says
        # where it lands
        record(home, RELEASE, state="waiting", base="origin/main", target="origin/release",
               started_at=now - 3 * 3600, round_summaries=[{}],
               waiting_on={"line": lock("release"), "joined": now - 2 * 3600})
        # a queued run waits in its own `ak run`, which owns its record
        keeper = subprocess.Popen(["sleep", "3600"], start_new_session=True)
        cls.addClassCleanup(lambda: (keeper.kill(), keeper.wait()))
        for run in [*QUEUED, *FIRST, UNLISTED]:
            record(home, run, state="queued", slot_waiting=True, slot_wait_reason=REASONS[run],
                   started_at=now - 600, **({"first": True} if run in FIRST else {}),
                   **owner(keeper.pid))

    def waits(self, queue=(), running=0, limit=0):
        """What each run waits for, by `ak run status`, while the slots queue lists `queue` with
        `running` runs holding a slot, and the run limit is `limit` (0: none)."""
        self.home.write(".agentkit/runs/.slots.queue",
                        {"at": time.time(), "running": running, "queue": list(queue),
                         "since": time.time()})
        done = self.home.ak("run", "status", env={"AK_MAX_RUNS": str(limit)})
        self.assertEqual(done.code, 0, done.err)
        return wait_lines(done.out)

    def assertMainPlaces(self, said):
        self.assertEqual({run: said.get(run) for run in MAIN},
                         {run: [f"waiting · {place} in line to land on main"]
                          for run, place in zip(MAIN, PLACES)})

    def test_each_run_in_a_landing_line_reads_its_own_place(self):
        self.assertMainPlaces(self.waits())

    def test_a_line_to_another_target_counts_its_own_places(self):
        said = self.waits()
        self.assertEqual(said.get(RELEASE), ["waiting · 1st in line to land on release"])
        self.assertMainPlaces(said)

    def test_a_run_behind_the_first_in_the_slots_queue_reads_how_many_are_ahead(self):
        said = self.waits(QUEUED)
        self.assertEqual([said.get(run) for run in QUEUED],
                         [[REASONS[QUEUED[0]]], ["waiting for a slot · 1 ahead"],
                          ["waiting for a slot · 2 ahead"]])

    def test_a_full_limit_holds_every_run_behind_the_first_but_one_marked_first(self):
        said = self.waits([*FIRST, QUEUED[0]], running=2, limit=2)
        self.assertEqual([said.get(run) for run in [*FIRST, QUEUED[0]]],
                         [[REASONS[FIRST[0]]], ["waiting for a slot · 1 ahead"],
                          ["waiting for a slot · limit full (2 running) · 2 ahead"]])

    def test_a_queued_run_the_queue_does_not_list_reads_its_own_reason(self):
        self.assertEqual(self.waits(QUEUED).get(UNLISTED), [REASONS[UNLISTED]])


if __name__ == "__main__":
    unittest.main()
