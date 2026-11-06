"""An answer key runs the program `AK_BIN` names from outside.  One that imports Python ak's own
package answers for Python alone: `tests/test_go_keys.py` runs every claimed key against Go with
agentkit/ taken out, so Go could never claim it.  Five were written before this test; each
leaves BEFORE once it runs ak from outside, and none joins it."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMPORTS = re.compile(r"^\s*(from\s+agentkit[.\s]|import\s+agentkit\b)", re.M)
# the keys that imported agentkit when this test came (7 Nov 2026): the set only shrinks
BEFORE = {"test_key_a_tick_reads_each_run_once", "test_key_health_needs_a_working_ak",
          "test_key_no_line_is_typed_into_a_composer_ak_cannot_read_whole",
          "test_key_red_tests_rerun_at_once", "test_key_seat_runs_the_live_ak"}


class KeysRunAkFromOutside(unittest.TestCase):
    def test_no_key_imports_python_aks_own_package(self):
        inside = {path.stem for path in (ROOT / "tests").glob("test_key_*.py")
                  if IMPORTS.search(path.read_text())}
        self.assertEqual(inside - BEFORE, set(), "an answer key runs ak from outside, as "
                         "tests/fixtures/akbin.py does, never Python ak's own modules")
        self.assertEqual(BEFORE - inside, set(), "a key that runs ak from outside now leaves BEFORE")


if __name__ == "__main__":
    unittest.main()
