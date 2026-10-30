"""A history write flushes nothing under the one lock every run and the tick take: on 30 Oct 2026
each held it 1 to 4 s on a busy disk, a commit flushing the WAL and the last close emptying it.
"""

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, history  # noqa: E402

# A writer that dies at once after its write, as a killed run does.
WRITER = """import os, sys; sys.path.insert(0, sys.argv[1])
from pathlib import Path
from agentkit import config, history
config.HOME = Path(sys.argv[2]); history.start_run("died", repo="acme"); os._exit(0)"""


class WriteFlushesNothing(unittest.TestCase):
    def test_no_flush_and_what_a_killed_writer_wrote_reaches_another_process(self):
        with tempfile.TemporaryDirectory() as home, patch.object(config, "HOME", Path(home)):
            history.start_run("first", repo="acme")
            history.start_run("second", repo="acme")
            self.assertGreater(Path(f"{history.path()}-wal").stat().st_size, 0)
            with history._writing():
                connection = history._writable()
                self.assertEqual(connection.execute("PRAGMA synchronous").fetchone()[0], 1)
                connection.close()
            subprocess.run([sys.executable, "-c", WRITER, str(REPO), home], check=True, timeout=120)
            self.assertEqual(history.get("died")["repo"], "acme")


if __name__ == "__main__":
    unittest.main()
