"""`ak orch project` tells a session when its project's suite reports none of its tests to ak.

A suite that ran whole to its end at landing, green or red, while ak holds no time of any of its
tests has a runner that prints no `PASS  <file> (<seconds>s)` line, and everything ak does with
tests by name is lost to the project: the session filing a seat there hears so in one line under
the rest, its suite read from its default branch as last fetched, whatever its checkout
holds.  A project with times hears nothing, nor does one that never landed its suite whole:
checked only in rounds, a piece stopped, missing, busy, lost by a helper or killed by a signal,
one piece run alone, or its run still going, which keeps its suite's times only as the check
ends.  Black-box: the program `AK_BIN`
names runs from outside through tests/fixtures/akbin.py, judged by what it prints from the
history's rows and the test-times record written into its HOME.
"""

from contextlib import closing
from pathlib import Path
import sqlite3
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home
from fixtures.akseat import Seat
from fixtures.gitrig import Rig

WHOLE, PIECES = "bash tests/all.sh", "export AK_SHARD; bash tests/all.sh"
TOLD = ("this project's suite reports no tests to ak, so a landing cannot retry or narrow a red "
        "by the tests that failed, the suite is cut into pieces by count instead of by time, and "
        "a round runs none of the change's tests: its runner must print "
        "`PASS  <file> (<seconds>s)` for each file that passes and take ak's files AK_ONLY, "
        "AK_RAN, AK_FAILED and AK_NOT_THERE")
FINISHED, GOING = 1, None
# project, its suite and its runs' landing checks: run, its end, round, kind, command, exit
PROJECTS = {
    "silent": (WHOLE, [("a", FINISHED, None, "landing", WHOLE, 0)]),
    "pieces": (PIECES, [("b", FINISHED, None, "landing", f"AK_SHARD=1/2 {PIECES}", 1),
                        ("b", FINISHED, None, "landing", f"AK_SHARD=2/2 {PIECES}", 0)]),
    "timed": (WHOLE, [("c", FINISHED, None, "landing", WHOLE, 0)]),
    "aside": (WHOLE, [("k", FINISHED, None, "landing", WHOLE, 0)]),
    "fresh": (PIECES, [("d", FINISHED, 1, "done-when", f"AK_SHARD=1/1 {PIECES}", 0),
                       ("e", FINISHED, None, "landing", f"AK_SHARD=1/2 {PIECES}", 0),
                       ("e", FINISHED, None, "landing", f"AK_SHARD=2/2 {PIECES}", None),
                       ("f", FINISHED, None, "landing", f"AK_SHARD=1/2 {PIECES}", 0),
                       ("f", FINISHED, None, "landing", f"AK_SHARD=2/2 {PIECES}", 75),
                       ("g", FINISHED, None, "landing", PIECES, 0),
                       ("i", FINISHED, None, "landing", f"AK_SHARD=1/1 {PIECES}", 255),
                       ("j", FINISHED, None, "landing", f"AK_SHARD=1/1 {PIECES}", -9),
                       ("h", GOING, None, "landing", f"AK_SHARD=1/2 {PIECES}", 0),
                       ("h", GOING, None, "landing", f"AK_SHARD=2/2 {PIECES}", 1)]),
}


class Told(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        Seat(home, "fix-api", cwd=home.path, alive=False)
        with closing(sqlite3.connect(home.path / ".agentkit/history.db")) as db, db:
            # both tables hold a `kind` and a `finished_at`, as ak's own history does
            db.execute("CREATE TABLE runs (run_id TEXT PRIMARY KEY, repo TEXT, kind TEXT, "
                       "finished_at REAL)")
            db.execute("CREATE TABLE checks (run_id TEXT, round INTEGER, kind TEXT, tree TEXT, "
                       "command TEXT, exit INTEGER, finished_at REAL)")
            for number, (name, (suite, checks)) in enumerate(PROJECTS.items()):
                rig = Rig(home, name, files={
                    "AGENTS.md": f"---\ntests: {suite}\nhealth: none\nusers: none\n---\n"})
                rig.git("config", "ak.repository", f"{number:012x}")
                for run, end, *check in checks:
                    db.execute("INSERT OR IGNORE INTO runs VALUES (?, ?, 'task', ?)",
                               (run, name, end))
                    db.execute("INSERT INTO checks VALUES (?, ?, ?, 'cedar', ?, ?, 2)",
                               (run, *check))
                if name == "aside":
                    # Its checkout is on a branch of its own that declares no suite, called
                    # origin/HEAD: that short name would read it, not the default branch.
                    rig.git("checkout", "-q", "-b", "origin/HEAD")
                    rig.commit({"AGENTS.md": "---\nhealth: none\nusers: none\n---\n"}, push=False)
        home.write(".agentkit/state/test-times-000000000002.json", {"tests/test_api.py": 3.0})

    def project(self, checkout, columns):
        done = self.home.ak("orch", "project", "fix-api", checkout,
                            env={"COLUMNS": str(columns)})
        self.assertEqual(done.code, 0, done.err)
        return done.out.splitlines()

    def test_a_suite_run_whole_at_landing_with_no_times_is_told_in_one_line(self):
        for name in ("silent", "pieces", "aside"):
            for columns, cap in ((60, 60), (250, 120)):
                with self.subTest(name, columns=columns):
                    lines = self.project(name, columns)
                    self.assertEqual(lines[:2], [f"filed fix-api under {name}",
                                                 f"nothing else in flight on {name}"])
                    self.assertEqual(" ".join(lines[2:]), TOLD)
                    self.assertLessEqual(max(map(len, lines)), cap)
                    # the line a runner prints never breaks, its two spaces kept
                    self.assertTrue(any("`PASS  <file> (<seconds>s)`" in line for line in lines))

    def test_a_terminal_too_narrow_for_the_runners_line_keeps_its_spaces(self):
        self.assertIn("`PASS  <file> (<seconds>s)`", "".join(self.project("silent", 24)))

    def test_a_project_with_times_or_that_never_landed_its_suite_whole_is_told_nothing(self):
        for name in ("timed", "fresh"):
            with self.subTest(name):
                self.assertEqual(self.project(name, 120), [f"filed fix-api under {name}",
                                                           f"nothing else in flight on {name}"])


if __name__ == "__main__":
    unittest.main()
