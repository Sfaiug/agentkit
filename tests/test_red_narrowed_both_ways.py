"""Confirmed failures narrow a red stack in either direction without whole halfway checks.

Offline: real Git and shell checks in the landing fixture, fake processes and wakes.
"""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_a_red_is_narrowed_by_its_failed_tests import NAMED, NarrowFixture, on
from agentkit import worker

# Affect only a halfway tests-alone check, after the deepest stack confirmed t_tax red.
HALFWAY = '[ -n "$AK_RAN" ] && [ -f member-2.txt ] && [ ! -f member-4.txt ]'


class RedNarrowedBothWays(NarrowFixture, unittest.TestCase):
    def test_a_bad_second_of_four_is_found_with_tests_alone_in_both_directions(self):
        checked, fix = self.narrow(NAMED, {}, 4, 2, {"broken.txt": "broken\n"})
        self.assertEqual(checked, [
            (on(1, 2, 3, 4), None),
            (on(1, 2), ["t_tax"]),              # red: move earlier without a whole check
            (on(1), ["t_tax"]),                # green: the second member turned it red
            (on(1, 3, 4), None)])
        self.assertEqual(fix["tests"], ["t_tax"])
        self.assertIn("FAIL t_tax", Path(fix["log"]).read_text())

    def test_a_red_first_member_still_gets_a_target_probe(self):
        checked, fix = self.narrow(NAMED, {}, 4, 1, {"broken.txt": "broken\n"})
        self.assertEqual(checked, [
            (on(1, 2, 3, 4), None),
            (on(1, 2), ["t_tax"]),
            (on(1), ["t_tax"]),
            (on(), ["t_tax"]),                 # the target itself passes
            (on(2, 3, 4), None)])
        self.assertEqual(fix["tests"], ["t_tax"])

    def inconclusive(self, suite):
        checked, fix = self.narrow(suite, {}, 4, 2, {"broken.txt": "broken\n"})
        self.assertEqual(checked, [
            (on(1, 2, 3, 4), None),
            (on(1, 2), ["t_tax"]),              # inconclusive: its whole check decides
            (on(1, 2), None),
            (on(1), ["t_tax"]),
            (on(1, 3, 4), None)])
        self.assertEqual(fix["tests"], ["t_tax"])

    def test_a_failure_not_named_as_run_gets_a_whole_check(self):
        self.inconclusive(f'if {HALFWAY}; then unset AK_RAN; fi; ' + NAMED)

    def test_a_failure_not_named_as_failed_gets_a_whole_check(self):
        self.inconclusive(f'if {HALFWAY}; then unset AK_FAILED; fi; ' + NAMED)

    def test_a_run_killed_after_naming_its_failure_gets_a_whole_check(self):
        boxed = worker.boxed

        def killed(*args, only=None, ran=None, failed=None, **kw):
            cwd = Path(kw["cwd"])
            if (ran is not None and (cwd / "member-2.txt").exists()
                    and not (cwd / "member-4.txt").exists()):
                ran.extend(only)
                failed.extend(only)
                return 137, "", True
            return boxed(*args, only=only, ran=ran, failed=failed, **kw)

        with patch.object(worker, "boxed", side_effect=killed):
            self.inconclusive(NAMED)

    def test_a_confirmed_failure_on_a_moved_checkout_gets_a_whole_check(self):
        moving = (f'if {HALFWAY}; then git -c user.name=fixture '
                  '-c user.email=fixture@localhost commit --allow-empty -qm moved; fi; ')
        self.inconclusive(moving + NAMED)


if __name__ == "__main__":
    unittest.main()
