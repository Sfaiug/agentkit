"""A git that asks no remote gets time by the host's load: one waiting for a core is not hung.

On 12 Nov 2026 a host stood at 16 times its cores' load for hours, and seven runs stopped
because such a git had not answered in 120 s.  It now gets 120 s for each time the host's
one-minute load fills its cores, an hour at most; where a core is free, 120 s as before.
Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, in a
project from gitrig.py, with the host's load injected (AK_HOST_READINGS) and a `git` first on its
PATH that takes 125 s over what `ak run status --tests` asks first, then answers as git does.
"""

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import shlex
import shutil
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import SYSTEM, Home
from fixtures.gitrig import Rig

GIT = shutil.which("git", path=os.pathsep.join(SYSTEM))
SLOW = '#!/bin/sh\ncase "$*" in *--show-toplevel) sleep 125 ;; esac\nexec {git} "$@"\n'


class LocalGitGetsTimeByLoad(unittest.TestCase):
    def test_a_git_past_120_s_is_waited_for_only_where_no_core_is_free(self):
        with Home() as home:
            rig = Rig(home)
            home.fake("git", SLOW.format(git=shlex.quote(GIT)))

            def audit(load):
                """`ak run status --tests` on a host at `load` for each of its cores."""
                return home.ak("run", "status", "--tests", cwd=rig.path, timeout=600,
                               env={"AK_HOST_READINGS": json.dumps({"load": load, "cpus": 1})})

            with ThreadPoolExecutor() as pool:      # at once: each waits two minutes for git
                busy, free = pool.map(audit, (16, 0))
        self.assertEqual(busy.code, 0, busy.err)
        self.assertIn("widgets tests: 0 files", busy.out)
        self.assertEqual(free.code, 2, free.out + free.err)
        self.assertIn("was killed after 120s", free.err)


if __name__ == "__main__":
    unittest.main()
