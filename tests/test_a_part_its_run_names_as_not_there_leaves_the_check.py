"""A check of just some tests (`gate.run_suite(shard=, only=)`) whose caller takes no names of
those not there, as a round's check takes none (`roundloop.verify_work`), loses from `only`
itself each part its run names as not there (`AK_NOT_THERE`): the run need not name it as run,
it is none of the tests the run named as failed, the output says which it is, and a later go
handed that list, as a re-run is (`gate.run_done_when`), runs without it.  The run's exit stays
its own, as no name says what else failed.  A file of the checkout stays, whatever its runner
names, and a caller that takes the names (`absent`, a landing's narrowing step) keeps its list.

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


class APartItsRunNamesAsNotThereLeavesTheCheck(Sandbox):
    def setUp(self):
        super().setUp()
        (self.root / HELD).parent.mkdir()
        (self.root / HELD).touch()

    def check(self, only, code, ran=(), failed=(), gone=(), **kw):
        """(The exit of a check of `only`, what it wrote) where the one run exits `code` naming
        those tests as run, as failed and as not there."""
        names, output = {"ran": ran, "failed": failed, "absent": gone}, BytesIO()

        def boxed(cmd, limit, **given):
            for key, said in names.items():
                given[key].extend(said)
            return code, "", False

        with patch.object(worker, "boxed", side_effect=boxed):
            code, _, _ = gate.run_suite("python3 suite.py", 10, cwd=self.root, output=output,
                                        activity=self.root / "live.log", shard="1/1", only=only,
                                        **kw)
        return code, output.getvalue().decode()

    def test_a_run_that_does_not_name_it_as_run_passes_and_says_which_it_left_out(self):
        only = [GONE, HELD]
        code, wrote = self.check(only, 0, ran=[HELD], gone=[GONE])
        self.assertEqual((code, only), (0, [HELD]))
        self.assertIn(GONE, wrote)      # the stand-in box writes nothing: the gate's own line

    def test_a_failing_runs_exit_stays_its_own_and_only_and_its_failed_tests_lose_the_part(self):
        # It names none as run, as a runner that stops at the part names none.
        for code in (1, 127):   # 127, as of a command after the runner: no name tells it
            for held in ([HELD], []):
                with self.subTest(code=code, held=held):
                    only, named = [GONE, *held], []
                    failed = [GONE, *(f"{test}::test_total" for test in held)]
                    self.assertEqual(self.check(only, code, failed=failed, gone=[GONE],
                                                named=named)[0], code)
                    self.assertEqual((only, named), (held, failed[1:]))

    def test_a_file_of_the_checkout_stays_whatever_its_runner_names(self):
        only = [HELD]
        self.assertEqual((self.check(only, 0, gone=[HELD])[0], only), (1, [HELD]))

    def test_a_caller_that_takes_the_names_keeps_its_list(self):
        only, absent = [HELD, GONE], []
        self.assertEqual(self.check(only, 1, [HELD], [GONE], [GONE], absent=absent)[0], 1)
        self.assertEqual((only, absent), ([HELD, GONE], [GONE]))


if __name__ == "__main__":
    unittest.main()
