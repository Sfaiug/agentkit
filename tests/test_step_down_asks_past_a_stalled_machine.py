"""A home standing still asks each machine its records say takes over from it whether it is home,
in the order of their names: one that stalls past `standby.TIMEOUT` answers no, so the next is
still asked, as the stalled one is asked first by every paused firing.
"""

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import standby, step_down


class AStalledMachine(unittest.TestCase):
    def test_a_machine_silent_past_the_timeout_leaves_the_next_asked(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(standby.config, "TMP", Path(tmp)):
            folder = Path(tmp) / standby.COPIES
            folder.mkdir()
            for name in "acme-a", "acme-b":
                (folder / name).write_text("1 2 boot\nyes\n")
            replies = [subprocess.TimeoutExpired("ssh", standby.TIMEOUT),
                       subprocess.CompletedProcess("ssh", 0)]
            with patch.object(step_down.subprocess, "run", side_effect=replies) as run, \
                    patch.object(standby, "_home_began", return_value=[]) as began:
                step_down.where_another_is_home()
        self.assertEqual([call.args[0][3] for call in run.call_args_list], ["acme-a", "acme-b"])
        began.assert_called_once_with("acme-b")


if __name__ == "__main__":
    unittest.main()
