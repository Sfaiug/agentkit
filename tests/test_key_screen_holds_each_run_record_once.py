"""An open ak screen holds each run's record once, however many of its readers read it.

The screen's run list kept a parsed copy of every run's record of its own, and a seat's row with a
run waiting in a landing line, or a merge whose ending it was still owed, read every run through
the parses every reader shares, which kept a second: 132 MB more on a host with 74 MB of runs.
What the screen holds is its own resident memory (`VmRSS`, /proc/<pid>/status).  Black-box, on
tests/test_key_idle_screen_reads_only_what_changed.py's open screen.
"""

from pathlib import Path
import re
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_key_idle_screen_reads_only_what_changed import OpenScreen


class ScreenHoldsEachRunRecordOnce(OpenScreen):
    def resident(self):
        """Bytes of the screen's memory in RAM."""
        status = Path(f"/proc/{self.pid}/status").read_text()
        return int(re.search(r"^VmRSS:\s+(\d+) kB$", status, re.M)[1]) * 1024

    def test_runs_waiting_to_land_and_endings_owed_add_no_second_copy_of_the_runs(self):
        before = self.resident()
        self.line_up()
        runs = sum(path.stat().st_size
                   for path in (self.home.path / ".agentkit/runs").glob("*/run.json"))
        self.assertLess(self.resident() - before, runs / 2)


if __name__ == "__main__":
    unittest.main()
