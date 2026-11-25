"""A failed write to ~/.agentkit/state/tmux.conf leaves the previous config intact.

If writing ak's own tmux config fails mid-write (such as hitting a file-size limit), the
previously usable tmux.conf stays whole for concurrent or subsequent tmux server starts and
no temporary file is left behind in state/.  Black-box: the program `AK_BIN` names runs
from outside through tests/fixtures/akbin.py, and this test fails against `/bin/false`.
"""

import shlex
import shutil
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home

CONF = ".agentkit/state/tmux.conf"
PRLIMIT = shutil.which("prlimit")


@unittest.skipUnless(REAL_TMUX and PRLIMIT, "requires tmux and prlimit")
class FailedTmuxConfWrite(unittest.TestCase):
    def test_failed_write_preserves_previous_tmux_conf_and_cleans_temp_files(self):
        old = "set -g remain-on-exit on\n"
        home = Home()
        self.addCleanup(home.close)
        conf = home.write(CONF, old)
        # Apply a one-byte file-size limit to ak right before it writes tmux.conf: both Python
        # and Go query `tmux -V` while composing the config, immediately before writing the file.
        home.fake("tmux", (
            "#!/bin/sh\n"
            'for arg in "$@"; do\n'
            '  if [ "$arg" = "-V" ]; then\n'
            f'    {shlex.quote(PRLIMIT)} --fsize=1:1 --pid="$PPID" || exit 1\n'
            '    printf "tmux 3.4\\n"\n'
            '    exit 0\n'
            '  fi\n'
            'done\n'
            f'exec {shlex.quote(REAL_TMUX)} "$@"\n'
        ))
        cwd = home.path / "code" / "acme"
        cwd.mkdir(parents=True)
        done = home.run("/bin/bash", "-c", 'trap "" XFSZ; exec "$@"', "_",
                        home.program, "orch", "acme", "--model", "opus", "--workers", "opus",
                        tty=True, cwd=cwd)
        self.assertNotEqual(done.code, 0, done)
        self.assertIn("cannot write the tmux config", done.err)
        self.assertEqual(conf.read_text(), old)
        self.assertEqual([item.name for item in conf.parent.iterdir() if "tmux.conf" in item.name],
                         ["tmux.conf"])


if __name__ == "__main__":
    unittest.main()
