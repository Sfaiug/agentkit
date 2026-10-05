"""A launch whose reader stops reading -- `ak run ... | head -1` -- still runs, its log whole."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]


class LaunchClosedPipe(unittest.TestCase):
    def test_a_closed_reader_ends_the_reading_never_the_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            read, write = os.pipe()
            os.close(read)                      # the reader is gone before the first line
            try:
                done = subprocess.run(
                    [sys.executable, "-c",
                     "import sys; from pathlib import Path; from agentkit import run\n"
                     "log = run.logger(Path(sys.argv[1]))\n"
                     "for step in ('--- preflight', '--- preflight: picked', 'launched'):\n"
                     "    log(step)\n"
                     "print('after the log')\n",
                     tmp],
                    cwd=REPO, stdout=write, stderr=subprocess.PIPE, text=True, timeout=60)
            finally:
                os.close(write)
            self.assertEqual((done.returncode, done.stderr), (0, ""))
            lines = (Path(tmp) / "log.txt").read_text().splitlines()
            self.assertEqual([line.split("] ", 1)[1] for line in lines],
                             ["--- preflight", "--- preflight: picked", "launched"])


if __name__ == "__main__":
    unittest.main()
