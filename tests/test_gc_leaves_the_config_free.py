"""A collection pass does not lock what a config write locks.

Both once locked ak's home directory, so a pass ending old conversations for minutes held
every config write: the models screen stood still at the first mark made during one.
"""

import os
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import config, gc


class GcLeavesTheConfigFree(Sandbox):
    def test_no_pass_locks_the_directory_a_config_write_locks(self):
        config.STATE.mkdir(parents=True, exist_ok=True)
        locked = []
        with patch.object(gc.fcntl, "flock", side_effect=lambda fd, _: locked.append(
                os.fstat(fd if isinstance(fd, int) else fd.fileno()).st_ino)):
            gc.gc(lambda message: None)
            gc.sweep(lambda message: None)
        self.assertGreaterEqual(len(locked), 2)
        self.assertNotIn(config.HOME.stat().st_ino, locked)


if __name__ == "__main__":
    unittest.main()
