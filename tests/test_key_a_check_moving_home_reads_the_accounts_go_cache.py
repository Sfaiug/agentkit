"""A check whose command moves HOME still finds Go's build cache, the account's, and leaves it as
it was.

Go keeps its build cache under HOME, and tasks ask every manual run to set HOME to a fresh
directory: such a check compiled the standard library from nothing, past its own timeout.  A
check's Go finds the cache `go env GOCACHE` names outside the check, whatever HOME it is given,
and what it writes there is gone when the check ends.  Black-box: the program `AK_BIN` names runs
from outside through tests/fixtures/akbin.py, on a project from gitrig.py, with scripted harnesses
from fakeadapter.py; the task's one check asks Go for its cache with HOME moved, reads a file the
account's cache holds and writes one of its own there.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.gitrig import Rig

CHECK = ('cache="$(HOME="$(mktemp -d)" go env GOCACHE)" && '
         'test "$(cat "$cache/held")" = account && echo check > "$cache/own"')


class ACheckMovingHomeReadsTheAccountsGoCache(unittest.TestCase):
    def test_the_check_reads_the_accounts_cache_and_leaves_it_as_it_was(self):
        home = Home()
        self.addCleanup(home.close)
        rig = Rig(home, "widgets")
        akconfig.write(home, ["opus", "astra"])
        fakeadapter.install(home, claude="work", codex="pass")
        # Where Go keeps the cache of a HOME, and an account's environment names no other.
        cache = home.path / ".cache" / "go-build"
        cache.mkdir(parents=True)
        (cache / "held").write_text("account\n")
        task = taskfile.write(home, rig.path, "Add retry file", front={"rounds": 1},
                              done_when=(CHECK,))
        done = home.ak("run", str(task), "--no-merge", timeout=300)
        state = json.loads((taskfile.only_run(home) / "run.json").read_text())
        self.assertEqual((done.code, state["state"]), (0, "pass"), done.out + done.err)
        self.assertEqual(sorted(path.name for path in cache.iterdir()), ["held"])


if __name__ == "__main__":
    unittest.main()
