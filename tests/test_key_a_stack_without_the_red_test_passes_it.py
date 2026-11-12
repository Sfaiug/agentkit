"""A stack whose tree does not hold the red test passes it: a narrowing step counts a test the
suite names as not there as passing on that stack, so the member that added a failing test is
blamed as soon as the probes reach the stack below it, with no stack checked whole on the way;
the red test then runs alone on the top rebuilt without it, before any whole check.

Black-box: the program `AK_BIN` names checks a landing line from outside through
tests/fixtures/akline.py, whose suite names a listed test its tree does not hold as not there;
ssh runs what it is given on `acme-linux`, the Linux machine of tests/fixtures/akmachine.py, with
room for four pieces at once.  Of eight members the sixth adds a test that fails.  Each member has
its row in the Home's history.db, where each check leaves one.
"""

import contextlib
from itertools import groupby
from pathlib import Path
import sqlite3
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, akmachine
from fixtures.akline import SUITE, Line
from test_key_history_db import ORIGINAL


class AStackWithoutTheRedTestPassesIt(unittest.TestCase):
    def test_the_member_adding_a_failing_test_is_blamed_on_the_probes_alone(self):
        line = Line({"t/ok.sh": "true\n",
                     "tools/helper/Containerfile": "FROM docker.io/library/alpine:3.20\n"})
        self.addCleanup(line.close)
        akconfig.write(line.home, ["opus", "astra"], settings={"suite_helper": "acme-linux"})
        akmachine.install(line.home, cpus=8)
        history = line.home.path / ".agentkit" / "history.db"
        # a run with no row keeps no checks
        with contextlib.closing(sqlite3.connect(history)) as db:
            db.execute("CREATE TABLE runs (%s)" % ", ".join(map(" ".join, ORIGINAL)))
            db.executemany("INSERT INTO runs (run_id) VALUES (?)",
                           [(f"fix-{n}",) for n in range(1, 9)])
            db.commit()
        for n in range(1, 9):
            # the sixth adds new.sh, failing: no stack below it holds that test
            line.member({f"member-{n}.txt": f"{n}\n",
                         **({"t/new.sh": "false\n"} if n == 6 else {})})
        done = line.land()
        self.assertEqual(done.code, 0, done.out + done.err)
        for n in range(1, 9):
            self.assertEqual([key for key in ("land", "fix") if key in line.verdict(n)],
                             ["fix"] if n == 6 else ["land"], n)
        self.assertEqual(line.verdict(6)["fix"]["tests"], ["new.sh"])
        with contextlib.closing(sqlite3.connect(history)) as db:
            rows = db.execute("SELECT run_id, tree, command, place FROM checks "
                              "WHERE kind = 'landing' ORDER BY started_at, rowid").fetchall()
        # A whole check leaves a row a piece, `AK_SHARD=<share> <suite>`; a run of the red test
        # alone, a probe there or a step here, leaves one naming the suite.
        whole = [stack for stack, _ in groupby(
            (run_id, tree) for run_id, tree, command, _ in rows if command != SUITE)]
        # The top, red; the stack just below the sixth, once it is blamed; the top rebuilt.
        self.assertEqual([run_id for run_id, _ in whole], ["fix-8", "fix-5", "fix-8"], rows)
        first = max(index for index, row in enumerate(rows) if tuple(row[:2]) == whole[0])
        below = min(index for index, row in enumerate(rows) if tuple(row[:2]) == whole[1])
        between = rows[first + 1:below]
        self.assertEqual({command for _, _, command, _ in between}, {SUITE}, rows)
        self.assertTrue(any(place == "acme-linux" for *_, place in between), rows)
        # Here: the step blaming the sixth, then the red test alone on the top rebuilt without it.
        here = [stack for stack, _ in groupby(
            (run_id, tree) for run_id, tree, _, place in between if place != "acme-linux")]
        self.assertEqual([run_id for run_id, _ in here], ["fix-6", "fix-8"], rows)
        self.assertEqual(here[1], whole[2], rows)


if __name__ == "__main__":
    unittest.main()
