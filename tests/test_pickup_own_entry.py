"""A queued run picks up new code through ak's own entry, whatever path started it: a link such as
`~/.local/bin/ak` may since point at another program, so the pickup runs `bin/ak` beside the
code with the launch's own arguments, as `resume` and `spawn_bg` do.

Offline: a temporary run directory and an injected exec; no test execs a real process.
"""

from io import StringIO
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, run


class PickupOwnEntry(unittest.TestCase):
    def test_the_pickup_runs_aks_own_entry_with_the_launchs_arguments(self):
        with tempfile.TemporaryDirectory(prefix=".ak-test-pickup-entry-", dir=REPO) as tmp:
            run_dir = Path(tmp) / "20990101-0000-acme-fix"
            run_dir.mkdir()
            execs = []
            argv = [str(Path(tmp) / "bin" / "ak"), "run", str(run_dir / "task.md")]
            with patch.dict(os.environ, {config.RUN_DIR_ENV: str(run_dir)}), \
                    patch.object(run, "_PICKUP_START", "aaa1111"), \
                    patch.object(sys, "argv", argv), patch("sys.stdout", StringIO()):
                self.assertTrue(run.pickup_while_queued(
                    run_dir, execv=lambda *a: execs.append(a), current="bbb2222"))
        self.assertEqual(execs, [(sys.executable, [sys.executable, str(config.REPO / "bin" / "ak"),
                                                   "run", argv[2]])])


if __name__ == "__main__":
    unittest.main()
