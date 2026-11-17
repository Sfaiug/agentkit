"""The piece of the suite a round's red tests fit in is the median piece of the project's latest
landing check that ran its suite whole: its pieces run to their end as first run, red or green,
cut in more than one; not a piece run again, nor the tests of a narrowing, nor pieces that never
ran, nor older suites cut finer, nor a round's.

Black-box, as tests/test_key_a_round_runs_the_tests_that_fail_most_at_landing.py and on its
fixtures, its clock injected: the program `AK_BIN` names runs three tasks in turn on a target whose
`tests:` line is cut in pieces.  The first leaves ak's history.  Before the second the test writes
the rows of earlier runs: landings red on three tests of 20 s each, many older pieces of 5 s, a
whole landing run in two pieces of 40 and 50 s and after it a narrowing's pieces of seconds and a
landing whose pieces never ran.  Before the third, a later whole landing run in four pieces of
25 s, red.  Before each of those two it writes the time record.
"""

import os
from pathlib import Path
import shlex
import socket
import sqlite3
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, clock, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig
from test_key_a_round_runs_its_changes_tests import SUITE
from test_key_a_round_runs_the_tests_that_fail_most_at_landing import CUT, DAY, NOW

TASKS = ("one", "two", "three")
TIMES = {"./tests/first.sh": 20, "./tests/second.sh": 20, "./tests/third.sh": 20}
# test: the runs whose landing it was red in
REDS = {"./tests/first.sh": ("fix-a", "fix-b", "fix-c"), "./tests/second.sh": ("fix-a", "fix-b"),
        "./tests/third.sh": ("fix-a",)}
RUNS = ("fix-a", "fix-b", "fix-c", "fix-d", "fix-e")


def whole(run, kind, seconds, ended, code=0):
    """The rows of `run`'s check of the suite in as many pieces as `seconds` holds, each as first
    run, ending at `ended` with the exit `code`."""
    return [(run, kind, "tree", f"AK_SHARD={share}/{len(seconds)} {CUT}", ended - took, ended, 0,
             code) for share, took in enumerate(seconds, 1)]


class ThreeRuns(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        clock.standing(cls.home, "AK_ROUND_CLOCK", NOW)
        said = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        cls.addClassCleanup(said.close)
        said.bind(address := f"\0ak-round-piece-{os.getpid()}")
        said.setblocking(False)
        cls.rig = Rig(cls.home, "widgets", files={
            "AGENTS.md": f"---\nhealth: none\ntests: {CUT}\n---\n# widgets\n",
            "suite.py": SUITE.format(said=address),
            **{f"tests/{name}.sh": "true\n" for name in ("first", "second", "third")}})
        cls.rig.git("config", "ak.repository", "0123456789ab")
        GitHub(cls.home).grant(cls.rig.slug, "WRITE")
        akconfig.write(cls.home, ["opus", "astra"])
        review = ("import socket; socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)"
                  f".sendto(b'review', {address!r})")
        cls.fakes = fakeadapter.install(cls.home, claude=[
            {"write": {f"{name}.txt": "\n"}, "commit": name, "final": f"## Summary\n{name}",
             "hand_in": [["done"]]} for name in TASKS], codex={
            "sh": f"python3 -c {shlex.quote(review)}", "final": "Handed in.",
            "hand_in": [["done"]]})
        cls.done, cls.notes = {}, {}
        for name, rows in zip(TASKS, (None, cls.long_pieces, cls.finer_pieces)):
            if rows:
                # each landing keeps the times it measured: the record goes back to these
                cls.home.write(".agentkit/state/test-times-0123456789ab.json", TIMES)
                with sqlite3.connect(cls.home.path / ".agentkit/history.db") as connection:
                    connection.executemany(
                        "INSERT INTO checks (run_id, kind, tree, command, started_at, "
                        "finished_at, rerun, exit) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows())
            task = taskfile.write(cls.home, cls.rig.path, f"Add {name}",
                                  done_when=(f"test -f {name}.txt",))
            cls.done[name] = cls.home.ak("run", str(task), timeout=300)
            cls.notes[name] = []
            while True:
                try:
                    cls.notes[name].append(said.recv(4096).decode())
                except BlockingIOError:
                    break

    @classmethod
    def long_pieces(cls):
        """The rows of earlier runs: their landings' reds, many short pieces a week older, of
        landings and of rounds, a whole landing run of long pieces and after it a narrowing:
        one of its pieces run again and the tests it named on another tree, and a landing whose
        pieces the suite's own lock kept from running (75, busy)."""
        with sqlite3.connect(cls.home.path / ".agentkit/history.db") as connection:
            connection.executemany(
                "INSERT INTO runs (run_id, repo, final_state, started_at, finished_at) "
                "VALUES (?, 'widgets', 'pass', ?, ?)", [(run, NOW - DAY, NOW - DAY) for run in RUNS])
            connection.executemany(
                "INSERT INTO test_reds (run_id, round, kind, tree, test, flaky, at) "
                "VALUES (?, NULL, 'landing', 'tree', ?, 0, ?)",
                [(run, test, NOW - DAY) for test, runs in REDS.items() for run in runs])
        return [*(row for run in RUNS[:3] for kind in ("landing", "done-when")
                  for row in whole(run, kind, [5] * 12, NOW - 8 * DAY)),
                *whole("fix-d", "landing", [40, 50], NOW - 2 * DAY),
                ("fix-d", "landing", "tree", f"AK_SHARD=2/2 {CUT}", NOW - DAY - 3, NOW - DAY,
                 1, 0),
                ("fix-e", "landing", "narrowed", f"AK_SHARD=1/2 {CUT}", NOW - DAY - 2, NOW - DAY,
                 0, 0),
                *whole("fix-c", "landing", [0, 0], NOW - DAY, 75)]

    @classmethod
    def finer_pieces(cls):
        """A later whole landing run, cut finer, its tests ending red."""
        return whole("fix-e", "landing", [25] * 4, NOW - DAY / 2, 1)

    def test_each_run_merges(self):
        for name in TASKS:
            done = self.done[name]
            self.assertEqual(done.code, 0, f"{name}: {done.out}{done.err}")

    def test_the_red_tests_fit_one_piece_of_the_latest_whole_run(self):
        self.assertEqual(self.notes["two"][:2],
                         ["suite ./tests/first.sh ./tests/second.sh", "review"])

    def test_a_later_whole_run_cut_finer_fits_fewer(self):
        self.assertEqual(self.notes["three"][:2], ["suite ./tests/first.sh", "review"])


if __name__ == "__main__":
    unittest.main()
