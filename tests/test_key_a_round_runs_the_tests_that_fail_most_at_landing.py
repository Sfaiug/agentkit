"""Before its review a round runs, beside the tests its change edits, the project's tests that
landing checks of the last 14 days were red on, flakes aside: those that stopped the most runs
first, as many as the time record's times fit in one piece of the suite, at the median its pieces
took, or the whole record for a suite that runs uncut.  They are handed in the same run, named as
the record spells them, and its failing exit sends the round back.  Left out are a test red only
before then, one the record times not, one whose file is gone and one the target is red on now by
its landing line's record; one the target was red on and repaired runs, as that one does once the
target has moved past its red.

Owner, 16 Nov 2026: "Yes, this small set … And make sure this also happens for new repos we work
on".

Black-box, as tests/test_key_a_round_runs_its_changes_tests.py and with its fixtures, its clock
injected (tests/fixtures/clock.py): the program `AK_BIN` names runs three tasks in turn.  The first
leaves ak's history and its landing line's record.  Before the second the test writes the rows of
earlier landings and the line's record of its target red, its repair failed a moment ago; the
second's change breaks a test it does not edit.  Before the third, the test adds the rows of a
landing that ran the suite in two pieces.  Before each of those two it writes the time record.
"""

import json
import os
from pathlib import Path
import shlex
import socket
import sqlite3
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, clock, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig
from test_key_a_round_runs_its_changes_tests import SUITE

DAY = 86400
NOW = 1_900_000_000     # far from the real clock: a round reading that one would run old.sh
SAID = "./TESTS/OFTEN.SH IS BROKEN"
TASKS = ("one", "two", "three")
WORK = [
    {"write": {"one.txt": "1\n"}, "commit": "one", "final": "## Summary\none",
     "hand_in": [["done"]]},
    # Breaks often.sh, a test it does not edit, and the fix puts widget.txt back.
    {"write": {"two.txt": "2\n", "widget.txt": "v2\n"}, "commit": "two",
     "final": "## Summary\ntwo", "hand_in": [["done"]]},
    {"write": {"widget.txt": "v1\n"}, "commit": "widget v1", "final": "## Summary\nwidget v1",
     "hand_in": [["done"]]},
    {"write": {"three.txt": "3\n"}, "commit": "three", "final": "## Summary\nthree",
     "hand_in": [["done"]]},
]
# The record: often.sh and sometimes.sh cost 30 s each, more than the 45 s of one piece together.
TIMES = {"./tests/often.sh": 30, "./tests/sometimes.sh": 30, "./tests/held.sh": 1,
         "./tests/repaired.sh": 1, "./tests/flaky.sh": 1, "./tests/old.sh": 1, "./tests/gone.sh": 1}
EVERY = ("fix-a", "fix-b", "fix-c", "fix-d", "fix-e")
# test: (the runs whose landing it was red in, days back, flaky)
REDS = {"./tests/held.sh": (EVERY[:4], 1, 0),
        "./tests/often.sh": (EVERY[:3], 13, 0),
        "./tests/sometimes.sh": (EVERY[:2], 1, 0),
        "./tests/repaired.sh": (EVERY[:1], 1, 0),
        "./tests/flaky.sh": (EVERY, 1, 1),
        "./tests/old.sh": (EVERY, 15, 0),
        "./tests/untimed.sh": (EVERY, 1, 0),
        "./tests/gone.sh": (EVERY, 1, 0)}


class ThreeRuns(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        clock.standing(cls.home, "AK_ROUND_CLOCK", NOW)
        said = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        cls.addClassCleanup(said.close)
        said.bind(address := f"\0ak-round-runs-reds-{os.getpid()}")
        said.setblocking(False)
        cls.rig = Rig(cls.home, "widgets", files={
            "AGENTS.md": "---\nhealth: none\ntests: python3 suite.py\n---\n# widgets\n",
            "suite.py": SUITE.format(said=address), "widget.txt": "v1\n",
            "tests/often.sh": "grep -qx v1 widget.txt\n",
            **{f"tests/{name}.sh": "true\n"
               for name in ("sometimes", "held", "repaired", "flaky", "old", "untimed")}})
        cls.rig.git("config", "ak.repository", "0123456789ab")
        cls.first = cls.rig.origin("rev-parse", "main^{tree}")
        GitHub(cls.home).grant(cls.rig.slug, "WRITE")
        akconfig.write(cls.home, ["opus", "astra"])
        review = ("import socket; socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)"
                  f".sendto(b'review', {address!r})")
        cls.fakes = fakeadapter.install(cls.home, claude=WORK, codex={
            "sh": f"python3 -c {shlex.quote(review)}", "final": "Handed in.",
            "hand_in": [["done"]]})
        cls.done, cls.notes, cls.states = {}, {}, {}
        for name, before in zip(TASKS, (None, cls.landed_before, cls.cut_in_pieces)):
            if before:
                # each landing keeps the times it measured: the record goes back to these
                cls.home.write(".agentkit/state/test-times-0123456789ab.json", TIMES)
                with sqlite3.connect(cls.home.path / ".agentkit/history.db") as connection:
                    before(connection)
            task = taskfile.write(cls.home, cls.rig.path, f"Add {name}",
                                  done_when=(f"test -f {name}.txt",))
            cls.done[name] = cls.home.ak("run", str(task), timeout=300)
            cls.notes[name] = []
            while True:
                try:
                    cls.notes[name].append(said.recv(4096).decode())
                except BlockingIOError:
                    break
            run_dir = next(path for path in taskfile.runs(cls.home)
                           if path.name.endswith(f"-add-{name}"))
            cls.states[name] = (run_dir, json.loads((run_dir / "run.json").read_text()))

    @classmethod
    def landed_before(cls, connection):
        """The rows earlier runs' landings left, the target red at its first tree on
        repaired.sh as well; and the line's record of the target red on held.sh now, its
        repair failed a moment ago, so the line lands over that red."""
        connection.executemany(
            "INSERT INTO runs (run_id, repo, final_state, started_at, finished_at) "
            "VALUES (?, 'widgets', 'pass', ?, ?)", [(run, NOW - DAY, NOW - DAY) for run in EVERY])
        connection.executemany(
            "INSERT INTO test_reds (run_id, round, kind, tree, test, flaky, at) "
            "VALUES (?, NULL, ?, 'tree', ?, ?, ?)",
            [(run, "landing", test, flaky, NOW - days * DAY)
             for test, (runs, days, flaky) in REDS.items() for run in runs]
            + [("fix-e", "tip", "./tests/repaired.sh", 0, NOW - 2 * DAY)])
        tip = cls.rig.head()
        cls.home.write(".agentkit/runs/repair/run.json", {
            "run_id": "repair", "state": "fail", "repair_tip": tip, "finished_at": time.time()})
        path, = (cls.home.path / ".agentkit/runs").glob(".merge-*.green")
        held = {"at": 0, "run": "repair", "probe": {"sha": tip}}
        path.write_text(json.dumps({**json.loads(path.read_text()), "red": {
            cls.rig.origin("rev-parse", f"{tip}^{{tree}}"): {**held, "tests": ["./tests/held.sh"]},
            cls.first: {**held, "tests": ["./tests/repaired.sh"]}}}))

    @classmethod
    def cut_in_pieces(cls, connection):
        """A landing that ran the suite in two pieces of 45 s."""
        connection.executemany(
            "INSERT INTO checks (run_id, kind, command, started_at, finished_at) "
            "VALUES ('fix-a', 'landing', ?, ?, ?)",
            [(f"AK_SHARD={share}/2 python3 suite.py", NOW - DAY, NOW - DAY + 45)
             for share in (1, 2)])

    def test_each_run_merges(self):
        for name in TASKS:
            done, (_, state) = self.done[name], self.states[name]
            self.assertEqual(done.code, 0, f"{name}: {done.out}{done.err}")
            self.assertEqual((state["state"], state["merged"]), ("pass", True), name)

    def test_a_project_whose_landings_named_no_failed_test_adds_none(self):
        self.assertEqual(self.notes["one"], ["review", "suite whole"])

    def test_a_red_test_runs_most_first_and_its_failing_exit_sends_the_round_back(self):
        # A suite run uncut fits all: failing, its re-run failing, then passing after the
        # fixer's turn, the test the target is red on now left out.
        self.assertEqual(self.notes["two"],
                         ["suite ./tests/often.sh ./tests/sometimes.sh ./tests/repaired.sh"] * 3
                         + ["review", "suite whole"])
        self.assertEqual([run["role"] for run in self.fakes["claude"].runs()],
                         ["executor", "executor", "fixer", "executor"])
        run_dir, state = self.states["two"]
        self.assertIn(SAID, (run_dir / "round-1/fixer/prompt.md").read_text())
        self.assertEqual([summary["verdict"] for summary in state["round_summaries"]], ["PASS"])

    def test_of_more_than_fit_one_piece_the_most_often_red_run(self):
        # held.sh too, the target moved past its red
        self.assertEqual(self.notes["three"], [
            "suite ./tests/held.sh ./tests/often.sh ./tests/repaired.sh", "review",
            "suite whole"])


if __name__ == "__main__":
    unittest.main()
