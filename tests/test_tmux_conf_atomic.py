"""A failed write to state/tmux.conf preserves the previous config and leaves no temp file."""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REPO, Home

SCRIPT = """
import errno, resource, signal
from agentkit import config, orch

signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
resource.setrlimit(resource.RLIMIT_FSIZE, (1, 1))
try:
    orch.tmux_conf()
except config.Error as exc:
    if getattr(exc.__cause__, "errno", None) == errno.EFBIG:
        raise SystemExit(32)
    raise
"""


class TmuxConfAtomicWriteTest(unittest.TestCase):
    def test_failed_write_preserves_previous_config_and_cleans_temp_file(self):
        old = "set -g remain-on-exit on\n"
        home = Home()
        self.addCleanup(home.close)
        path = home.write(".agentkit/state/tmux.conf", old)
        result = home.run(sys.executable, "-c", SCRIPT, cwd=REPO)
        self.assertEqual(result.code, 32, result)
        self.assertEqual(path.read_text(), old)
        self.assertEqual([item.name for item in path.parent.iterdir()], ["tmux.conf"])


if __name__ == "__main__":
    unittest.main()
