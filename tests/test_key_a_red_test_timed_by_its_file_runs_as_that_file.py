"""A test a landing was red on runs once a reviewer passed a round, as the name the time record
times it by: its own, else its file, for a runner that reports a file's seconds while its landings
name the test that failed (`./tests/often.sh::stays_v1`).  A name runs once, at its time, placed by
the most runs one red of it stopped, and its failing exit fails the round.  A file holding a test
the target is red on now is left out.  A file and a test of it the record times both are judged
apart: a file too long for the piece leaves its test running by its own name, and a test taken by
its own name is not handed beside its file.

Live since 17 Nov 2026 the choice asked the record of the red's whole name: on one project whose
runner times files, 305 tests were red at a landing in 14 days and no round ran one.

Black-box, as tests/test_key_a_round_runs_the_tests_that_fail_most_at_landing.py and on its
fixtures: the program `AK_BIN` names runs three tasks in turn.  The first leaves ak's history and
its landing line's record; before the second the test writes the time record of files alone, the
rows of earlier landings red on tests of them, one that ran the suite in two pieces among them,
and the line's record of its target red on a test of held.sh now, its repair failed a moment ago.
The second's change breaks often.sh.  Before the third, the target's `tests:` line is cut in
pieces and the record times often.sh and quick.sh both whole and by a test of each.
"""

import json
from pathlib import Path
import shlex
import sqlite3
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, clock, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig
from fixtures.notes import Notes
from test_key_a_round_runs_its_changes_tests import SUITE

DAY = 86400
NOW = 1_900_000_000
SAID = "./TESTS/OFTEN.SH IS BROKEN"
TASKS = ("one", "two", "three")
# A runner that runs a test named by its file and its own name (`file::test`) in that file.
SUITE = SUITE.replace('["sh", test]', '["sh", test.partition("::")[0]]')
WORK = [
    {"write": {"one.txt": "1\n"}, "commit": "one", "final": "## Summary\none",
     "hand_in": [["done"]]},
    # Breaks often.sh, and the fix puts widget.txt back.
    {"write": {"two.txt": "2\n", "widget.txt": "v2\n"}, "commit": "two",
     "final": "## Summary\ntwo", "hand_in": [["done"]]},
    {"write": {"widget.txt": "v1\n"}, "commit": "widget v1", "final": "## Summary\nwidget v1",
     "hand_in": [["done"]]},
    {"write": {"three.txt": "3\n"}, "commit": "three", "final": "## Summary\nthree",
     "hand_in": [["done"]]},
]
CUT = ': "$AK_SHARD"; python3 suite.py'
# Files alone, 62 s in all.  often.sh spent twice would leave other.sh no room, and placed by its
# fewest runs it would follow other.sh; held.sh, first by its runs, holds the test the target is
# red on now.
TIMES = {"./tests/often.sh": 30, "./tests/quick.sh": 1, "./tests/other.sh": 30,
         "./tests/held.sh": 1}
# In a piece of 45 s: often.sh whole is too long for it, quick.sh whole fits.
BOTH = {"./tests/held.sh": 1, "./tests/often.sh::stays_v1": 1, "./tests/often.sh": 60,
        "./tests/quick.sh::passes": 1, "./tests/quick.sh": 2}
RUNS = ("fix-a", "fix-b", "fix-c", "fix-d", "fix-e", "fix-f")
# test: the runs whose landing it was red in
REDS = {"./tests/held.sh::passes": RUNS,
        "./tests/untimed.sh::passes": RUNS,
        "./tests/often.sh::stays_v1": RUNS[:5],
        "./tests/quick.sh::passes": RUNS[:4],
        "./tests/other.sh::passes": RUNS[:2],
        "./tests/often.sh::also": RUNS[:1],
        "./tests/quick.sh::other": RUNS[:1]}


class ThreeRuns(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        clock.standing(cls.home, "AK_ROUND_CLOCK", NOW)
        said = Notes()
        cls.rig = Rig(cls.home, "widgets", files={
            "AGENTS.md": "---\nhealth: none\ntests: python3 suite.py\n---\n# widgets\n",
            "suite.py": SUITE.format(said=said.address), "widget.txt": "v1\n",
            "tests/often.sh": "grep -qx v1 widget.txt\n",
            **{f"tests/{name}.sh": "true\n" for name in ("quick", "other", "held", "untimed")}})
        cls.rig.git("config", "ak.repository", "0123456789ab")
        GitHub(cls.home).grant(cls.rig.slug, "WRITE")
        akconfig.write(cls.home, ["opus", "astra"])
        review = ("import socket; socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)"
                  f".sendto(b'review', {said.address!r})")
        cls.fakes = fakeadapter.install(cls.home, claude=WORK, codex={
            "sh": f"python3 -c {shlex.quote(review)}", "final": "Handed in.",
            "hand_in": [["done"]]})
        cls.done, cls.notes, cls.states = {}, {}, {}
        for name, before in zip(TASKS, (None, cls.landed_before, cls.cut_in_pieces)):
            if before:
                before()
            task = taskfile.write(cls.home, cls.rig.path, f"Add {name}",
                                  done_when=(f"test -f {name}.txt",))
            cls.done[name] = cls.home.ak("run", str(task), timeout=300)
            cls.notes[name] = said.since()
            run_dir = next(path for path in taskfile.runs(cls.home)
                           if path.name.endswith(f"-add-{name}"))
            cls.states[name] = (run_dir, json.loads((run_dir / "run.json").read_text()))

    @classmethod
    def landed_before(cls):
        """The record of files alone, the rows earlier runs' landings left, one that ran the suite
        in two pieces of 45 s among them, and the line's record of the target red on
        held.sh::fails now, its repair failed a moment ago."""
        cls.home.write(".agentkit/state/test-times-0123456789ab.json", TIMES)
        with sqlite3.connect(cls.home.path / ".agentkit/history.db") as connection:
            connection.executemany(
                "INSERT INTO runs (run_id, repo, final_state, started_at, finished_at) "
                "VALUES (?, 'widgets', 'pass', ?, ?)",
                [(run, NOW - DAY, NOW - DAY) for run in RUNS])
            connection.executemany(
                "INSERT INTO test_reds (run_id, round, kind, tree, test, flaky, at) "
                "VALUES (?, NULL, 'landing', 'tree', ?, 0, ?)",
                [(run, test, NOW - DAY) for test, landed in REDS.items() for run in landed])
            connection.executemany(
                "INSERT INTO checks (run_id, kind, command, started_at, finished_at, rerun, "
                "exit) VALUES ('fix-a', 'landing', ?, ?, ?, 0, 0)",
                [(f"AK_SHARD={share}/2 {CUT}", NOW - DAY, NOW - DAY + 45) for share in (1, 2)])
        tip = cls.rig.head()
        cls.home.write(".agentkit/runs/repair/run.json", {
            "run_id": "repair", "state": "fail", "repair_tip": tip, "finished_at": time.time()})
        path, = (cls.home.path / ".agentkit/runs").glob(".merge-*.green")
        path.write_text(json.dumps({**json.loads(path.read_text()), "red": {
            cls.rig.origin("rev-parse", f"{tip}^{{tree}}"): {
                "at": 0, "run": "repair", "probe": {"sha": tip},
                "tests": ["./tests/held.sh::fails"]}}}))

    @classmethod
    def cut_in_pieces(cls):
        """The target's `tests:` line cut in pieces, and the record of often.sh and quick.sh both
        whole and by a test of each."""
        cls.home.write(".agentkit/state/test-times-0123456789ab.json", BOTH)
        cls.rig.git("pull", "-q", "--ff-only")
        cls.rig.commit({"AGENTS.md": f"---\nhealth: none\ntests: {CUT}\n---\n# widgets\n"},
                       "cut the suite")

    def test_each_run_merges(self):
        for name in TASKS:
            done, (_, state) = self.done[name], self.states[name]
            self.assertEqual(done.code, 0, f"{name}: {done.out}{done.err}")
            self.assertEqual((state["state"], state["merged"]), ("pass", True), name)

    def test_runs_as_its_file_once_and_its_failing_exit_sends_the_round_back(self):
        # after the review, failing, its re-run failing, then passing after the next turn's review
        ran = "suite ./tests/often.sh ./tests/quick.sh ./tests/other.sh"
        self.assertEqual(self.notes["two"], ["review", ran, ran, "review", ran, "suite whole"])
        self.assertEqual([run["role"] for run in self.fakes["claude"].runs()],
                         ["executor", "executor", "fixer", "executor"])
        run_dir, state = self.states["two"]
        self.assertIn(SAID, (run_dir / "round-2/executor/prompt.md").read_text())
        self.assertEqual([summary["verdict"] for summary in state["round_summaries"]],
                         ["FAIL", "PASS"])

    def test_a_file_and_a_test_of_it_are_judged_apart(self):
        # held.sh too, the target moved past its red; often.sh::stays_v1 by its own name, its
        # file too long; quick.sh::passes taken and run by its file alone; landing then runs the
        # suite's pieces
        self.assertEqual(self.notes["three"][:2], [
            "review", "suite ./tests/held.sh ./tests/often.sh::stays_v1 ./tests/quick.sh"])


if __name__ == "__main__":
    unittest.main()
