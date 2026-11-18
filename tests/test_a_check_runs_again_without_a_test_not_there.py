"""A check of just some tests (`gate.run_suite(shard=, only=)`) whose run names one as not there
(`AK_NOT_THERE`) and no other as failed goes again at once with only the others, where its
caller takes no such names, as a round's check takes none (`roundloop.verify_work`), and that
run's exit is the check's: a part the time record still times and its file no longer holds fails
no round and hides no failure beside it.  A run that names another test as failed, one it was
handed or a part of one, is the failing run it is, with none left the check passes, and a caller
that takes the names (`absent`, a landing's narrowing step) has the run as it was.

Offline: a sandbox HOME and a stand-in for the check box (`worker.boxed`) that names what a
runner would.
"""

from io import BytesIO
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.sandbox import Sandbox
from agentkit import gate, worker

HELD, GONE = "tests/test_acme.py", "tests/test_fix_api.py::removed"


class ACheckRunsAgainWithoutATestNotThere(Sandbox):
    def check(self, only, alone=0, named=(), **kw):
        """(The exit of a check of `only` alone, the tests each of its runs was handed): a run
        handed GONE names it as not there and, with `named`, as failed, as every_file.py does,
        exiting 1, and one handed the others alone exits `alone`."""
        handed = []

        def boxed(cmd, limit, *, only, ran, failed, absent, **_kw):
            handed.append(only)
            ran.extend(test for test in only if test != GONE)
            if GONE not in only:
                return alone, "", False
            absent.append(GONE)
            failed.extend([GONE, *named])
            return 1, "", False

        with patch.object(worker, "boxed", side_effect=boxed):
            code, _, _ = gate.run_suite("python3 suite.py", 10, cwd=self.root, output=BytesIO(),
                                        activity=self.root / "live.log", shard="1/1", only=only,
                                        **kw)
        return code, handed

    def test_the_others_run_again_alone_and_their_exit_is_the_checks(self):
        for alone in (0, 3):    # 3, as of a command after the runner: no name tells it
            with self.subTest(alone=alone):
                self.assertEqual(self.check([HELD, GONE], alone),
                                 (alone, [[HELD, GONE], [HELD]]))

    def test_a_run_that_names_another_test_as_failed_is_the_failing_run_it_is(self):
        for named in (HELD, f"{HELD}::test_total"):
            with self.subTest(named=named):
                self.assertEqual(self.check([HELD, GONE], named=[named]), (1, [[HELD, GONE]]))

    def test_with_none_left_the_check_passes(self):
        self.assertEqual(self.check([GONE]), (0, [[GONE]]))

    def test_a_caller_that_takes_the_names_has_the_run_as_it_was(self):
        absent = []
        self.assertEqual(self.check([HELD, GONE], absent=absent), (1, [[HELD, GONE]]))
        self.assertEqual(absent, [GONE])


if __name__ == "__main__":
    unittest.main()
