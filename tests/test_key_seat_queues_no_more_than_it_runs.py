"""A seat may have as many runs waiting for a slot as holding one, and always one.

Seats launched everything at once, so the queue outgrew what the host could check: runs waited
hours for a slot while main moved on, and a seat's urgent work sat behind its own older work.  A
seat's launch beyond that is refused, before anything is created: it exits non-zero, leaves no
run, and names one of the seat's runs to `ak wait` for, the one holding its slot longest, else
its oldest waiting.  A launch of several task files needs room for all of them.  A `--review-pr`
and a launch from no seat are never refused.  Black-box: the program `AK_BIN` names runs from
outside through tests/fixtures/akbin.py, from seats of akseat.py, on a project from gitrig.py and
the GitHub of fakegh.py; the runs already holding or waiting are records written beside live
processes, and the host admits exactly as many runs as hold a slot, so every accepted launch
waits.
"""

import json
import subprocess
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home, owner
from fixtures.akseat import Seat
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

READINGS = {"free_mb": 64000, "mem_total_mb": 128000, "cpus": 8, "load": 0.1,
            "slice_cpu_pressure": 0, "slice_memory_pressure": 0}
# Each seat's runs already there: (run id, seat, holding a slot), oldest first.
GOING = (("20261029-0900-acme-holds", "acme", True), ("20261029-0901-acme-waits", "acme", False),
         ("20261029-0902-bravo-holds", "bravo", True), ("20261029-0903-bravo-too", "bravo", True),
         ("20261029-0904-bravo-waits", "bravo", False), ("20261029-0905-delta-holds", "delta", True),
         ("20261029-0906-nobody-waits", None, False), ("20261029-0907-nobody-too", None, False))
HOLDING = sum(holds for _, _, holds in GOING)
TITLES = iter(("Add retry file", "Bump alpha notes", "Write beta log", "Trim gamma docs",
               "Sort delta list", "Name epsilon flag", "Fix zeta cache", "Load eta page"))


def record(run_dir):
    try:
        return json.loads((run_dir / "run.json").read_text())
    except (OSError, ValueError):
        return {}


class SeatQueue(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sleeps = []

        def end_sleeps():
            for sleep in sleeps:
                sleep.kill()
                sleep.wait()
        cls.addClassCleanup(end_sleeps)
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        del home.env["AK_MAX_RUNS"]
        home.env["AK_HOST_READINGS"] = json.dumps(READINGS)
        cls.rig = Rig(home, "widgets")
        cls.gh = GitHub(home)
        akconfig.write(home, ["opus", "astra"], settings={"max_runs": HOLDING})
        fakeadapter.install(home, claude="work", codex="pass")
        for seat in ("acme", "bravo", "charlie", "delta"):
            Seat(home, seat, cwd=cls.rig.path, alive=False, record={"workers": ["opus", "astra"]},
                 planned=True)
        now = time.time()
        for n, (run_id, seat, holds) in enumerate(GOING):
            sleeps.append(subprocess.Popen(["sleep", "600"], start_new_session=True))
            at = now - 600 + n
            home.write(f".agentkit/runs/{run_id}/run.json", {
                "run_id": run_id, "title": run_id[14:], "launched_session": seat,
                "state": "running" if holds else "queued", "slot_waiting": not holds,
                **owner(sleeps[-1].pid), "run_depth": 0, "started_at": at, "queued_at": at,
                **({"slot_started_at": at} if holds else {})})
        cls.acme = cls.launch("acme")
        cls.bravo = cls.launch("bravo")
        cls.charlie = cls.launch("charlie")
        for waiting in cls.charlie[1]:
            deadline = time.monotonic() + 60
            while not (record(waiting).get("state") == "queued"
                       and record(waiting).get("slot_waiting")):
                assert time.monotonic() < deadline, f"{waiting.name} never waited for a slot"
                time.sleep(0.1)
        cls.charlie_again = cls.launch("charlie")
        cls.rig.branch("readme", {"README.md": "# widgets\n"})
        cls.review = cls.launch("acme", "--review-pr",
                                cls.gh.open_pr(cls.rig, "readme", title="Say what widgets is"))
        cls.nobody = cls.launch(None)
        cls.job = cls.launch("delta", cls.task(), cls.task())

    @classmethod
    def task(cls):
        title = next(TITLES)
        return str(taskfile.write(cls.home, cls.rig.path, title,
                                  done_when=(f"test -f {title.split()[1]}.txt",)))

    @classmethod
    def launch(cls, seat, *args):
        """`ak run ... --bg` from that seat, or from none, of a new task unless `args` name what;
        what it returned and the runs it added."""
        args = args or (cls.task(),)
        before = set(taskfile.runs(cls.home))
        done = cls.home.ak("run", *args, "--bg", cwd=cls.rig.path,
                           env={"AGENTKIT_SESSION": seat}, timeout=300)
        return done, sorted(set(taskfile.runs(cls.home)) - before)

    def refused(self, launched, named):
        done, added = launched
        self.assertNotEqual(done.code, 0, done.out + done.err)
        self.assertEqual(added, [], "a refused launch leaves no run")
        self.assertIn(f"ak wait {named}", done.err)

    def accepted(self, launched):
        done, added = launched
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertEqual(len(added), 1, added)

    def test_a_seat_holding_one_slot_with_one_run_waiting_is_refused_naming_the_holder(self):
        self.refused(self.acme, "20261029-0900-acme-holds")

    def test_a_seat_holding_two_slots_with_one_run_waiting_launches(self):
        self.accepted(self.bravo)

    def test_a_seat_with_no_runs_launches_and_then_is_refused_naming_that_waiting_run(self):
        self.accepted(self.charlie)
        self.refused(self.charlie_again, self.charlie[1][0].name)

    def test_a_review_and_a_launch_from_no_seat_are_launched_however_many_wait(self):
        self.accepted(self.review)
        self.accepted(self.nobody)

    def test_a_launch_of_two_task_files_with_room_for_one_is_refused_whole(self):
        self.refused(self.job, "20261029-0905-delta-holds")


if __name__ == "__main__":
    unittest.main()
