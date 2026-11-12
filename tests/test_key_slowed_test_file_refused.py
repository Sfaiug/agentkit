"""Landing refuses a test file over the piece target that the change adds, or edits from a
version at most the target, both versions timed again together; one over it on the target too,
or whose version there times nothing, lands.

Black-box through AK_BIN, as test_key_landing_refuses_a_slow_test_file.py lands: the piece
target is 200s, and a test file holds the seconds the suite prints for it.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_key_landing_refuses_a_slow_test_file import FILE, Landing


class SlowedTestFileRefused(Landing):
    def test_an_edited_file_the_change_took_over_the_target_is_refused(self):
        self.assertRegex(self.refused(before=50), r"600s, up from 50s on ")

    def test_an_edited_file_over_the_target_on_both_versions_lands(self):
        self.landed(601, before=600)

    def test_an_edited_file_whose_target_version_times_nothing_lands(self):
        self.landed(600, before="untimed")

    def test_an_added_file_over_the_target_is_refused(self):
        self.refused()

    def landed(self, seconds, **how):
        rig, _, fakes, heads = self.land(seconds, **how)
        self.assertEqual([turn["role"] for turn in fakes["claude"].runs()], ["executor"])
        self.assertEqual(len(heads), 1)
        self.assertEqual(rig.origin("show", f"main:{FILE}"), str(seconds))


if __name__ == "__main__":
    unittest.main()
