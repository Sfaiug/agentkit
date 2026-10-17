"""The lander's log holds each line, with its time, once the logging call returns.

Offline: the lander's standard output is a file and its pass is a stand-in that logs one line.
"""

from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import gitcall, land, run


class LanderLogLive(unittest.TestCase):
    def test_a_logged_line_is_in_the_file_with_its_time_before_the_call_returns(self):
        clock = Mock(now=Mock(return_value=datetime(2026, 10, 17, 0, 11, 7)))
        seen = []

        def check_line(_turn, log):
            log("merged acme#12")
            seen.append(Path(output.name).read_text())

        with tempfile.NamedTemporaryFile("w", prefix=".merge-x-") as output, \
                patch.object(gitcall, "datetime", clock), \
                patch.object(land, "check_line", check_line), redirect_stdout(output):
            self.assertEqual(run.main(["--lander", ".merge-x"]), 0)
        self.assertEqual(seen, ["[00:11:07] merged acme#12\n"])


if __name__ == "__main__":
    unittest.main()
