"""A tmux control-mode client (`tmux -C`) has no terminal, so it is never sent a toast."""

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from agentkit import notify, orch


class ControlClientNotTarget(unittest.TestCase):
    def targets(self, rows):
        asked = []

        def tmux_out(*args, **_kw):
            asked.append(args)
            return 0, "".join("\t".join(row) + "\n" for row in rows)

        with patch.object(orch, "tmux_out", side_effect=tmux_out), \
                patch.object(orch, "socket_name", return_value="agentkit-test"):
            targets = notify.terminal_targets("source")
        self.assertIn("#{client_control_mode}", asked[0][-1])
        return targets

    def test_control_client_is_skipped_and_the_rest_targeted_as_before(self):
        rows = [("/dev/pts/1", "source", "@0", "/dev/pts/9", "0", "0"),
                ("/dev/pts/2", "acme", "@1", "/dev/pts/8", "0", "1"),
                ("/dev/pts/3", "acme", "@1", "/dev/pts/8", "0", "0"),
                ("/dev/pts/4", "hidden", "@2", "/dev/pts/7", "0", "1"),
                ("/dev/pts/5", "fix-api", "@3", "/dev/pts/6", "1", "0")]
        self.assertEqual(self.targets(rows), [("/dev/pts/8", True), ("/dev/pts/5", False)])

    def test_only_a_control_client_gets_nothing(self):
        self.assertEqual(self.targets([("/dev/pts/4", "hidden", "@2", "/dev/pts/7", "0", "1")]), [])


if __name__ == "__main__":
    unittest.main()
