"""A matrix another ak build computed is computed again at the next refresh, so a matching or
scoring rule that landed since holds at the tick after the install moved, not a day later.

Offline: the boards answered by bytes, the catalogs and installed harnesses faked
(tests/test_model_rows.py), ak's build faked, a throwaway HOME.
"""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
from fixtures.sandbox import Sandbox
from agentkit import matrix, update
import test_model_rows as rows_test


class MatrixFollowsTheBuild(Sandbox):
    def setUp(self):
        super().setUp()
        rows_test.prepare(self)

    def test_a_matrix_another_build_computed_is_computed_again(self):
        with patch.object(update, "agentkit_version", return_value="abc1234 · 2026-10-01"):
            matrix.refresh(self.cfg, now=10000)
            self.assertEqual(matrix.stored()["build"], "abc1234 · 2026-10-01")
            # the build that computed it keeps it for the day
            with patch.object(matrix, "rows", side_effect=AssertionError("computed again")):
                matrix.refresh(self.cfg, now=10001)
        # another build carries rules the stored matrix was not computed by
        with patch.object(update, "agentkit_version", return_value="def5678 · 2026-10-02"):
            matrix.refresh(self.cfg, now=10002)
        held = matrix.stored()
        self.assertEqual((held["computed_at"], held["build"]), (10002, "def5678 · 2026-10-02"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
