"""Boundary maxima are compared by name with where the change left origin/main, without
running its code."""

from contextlib import redirect_stdout
import io
import subprocess
import unittest
from unittest.mock import patch

import test_boundaries as boundaries

BASE = [{"name": "first boundary", "home": (), "max": 2},
        {"name": "second boundary", "home": (), "max": 1}]


class Maxima(unittest.TestCase):
    def check(self, rules, source=None, returncode=0, base="5ba5e"):
        source = f"RULES = {BASE!r}\n" if source is None else source
        proc = subprocess.CompletedProcess([], returncode, source, "")

        def answer(argv, **_kw):
            if "merge-base" in argv:
                return subprocess.CompletedProcess(argv, 0 if base else 1, base + "\n", "")
            return proc

        output = io.StringIO()
        result = unittest.TestResult()
        with patch.object(boundaries, "RULES", rules), \
                patch.object(boundaries, "outside", return_value=[]), \
                patch.object(boundaries.subprocess, "run", side_effect=answer) as git, \
                redirect_stdout(output):
            unittest.defaultTestLoader.loadTestsFromTestCase(boundaries.Boundaries).run(result)
        return result, output.getvalue(), git

    def test_equal_and_lower_maxima_pass(self):
        for maxima in ((2, 1), (1, 0)):
            with self.subTest(maxima=maxima):
                rules = [dict(rule, max=maximum) for rule, maximum in zip(BASE, maxima)]
                result, _, _ = self.check(rules)
                self.assertTrue(result.wasSuccessful(), result.errors + result.failures)

    def test_each_existing_max_cannot_rise(self):
        for index, rule in enumerate(BASE):
            with self.subTest(rule=rule["name"]):
                rules = [dict(item) for item in BASE]
                rules[index]["max"] += 1
                result, _, _ = self.check(rules)
                self.assertEqual(result.errors, [])
                self.assertEqual(len(result.failures), 1, "a raised max passed")
                self.assertIn(rule["name"], result.failures[0][1])
                self.assertIn("origin/main", result.failures[0][1])

    def test_rule_order_does_not_change_the_comparison(self):
        result, _, _ = self.check(list(reversed(BASE)))
        self.assertTrue(result.wasSuccessful(), result.errors + result.failures)

    def test_new_rule_has_no_previous_max(self):
        result, _, _ = self.check(BASE + [{"name": "new boundary", "home": (), "max": 20}])
        self.assertTrue(result.wasSuccessful(), result.errors + result.failures)

    def test_reads_the_maxima_where_the_change_left_origin_main(self):
        # a commit main has moved past compares with itself, not with maxima main lowered later
        repo = str(boundaries.REPO)
        for base, shown in (("5ba5e", "5ba5e"), ("", "origin/main")):
            with self.subTest(base=base):
                result, _, git = self.check(BASE, base=base)
                self.assertTrue(result.wasSuccessful(), result.errors + result.failures)
                self.assertEqual([call.args[0] for call in git.call_args_list], [
                    ["git", "-C", repo, "merge-base", "HEAD", "origin/main"],
                    ["git", "-C", repo, "show", f"{shown}:tests/test_boundaries.py"]])

    def test_unreadable_origin_main_prints_and_skips(self):
        for returncode in (1, 128):
            with self.subTest(returncode=returncode):
                result, output, _ = self.check(BASE, source="", returncode=returncode)
                self.assertTrue(result.wasSuccessful(), result.errors + result.failures)
                self.assertEqual(len(result.skipped), 1)
                self.assertIn("origin/main", output)
                self.assertIn("skipping max comparison", output)

    def test_target_code_is_not_executed(self):
        source = f"raise AssertionError('target code ran')\nRULES = {BASE!r}\n"
        result, _, _ = self.check(BASE, source=source)
        self.assertTrue(result.wasSuccessful(), result.errors + result.failures)


if __name__ == "__main__":
    unittest.main(verbosity=2)
