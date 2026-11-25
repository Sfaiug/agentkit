"""A user that is only a number, with no account, launches a run.

A turn on a machine runs in a container as that machine's user, whom the image may give no
account.  `ak run` there passes the check of the worker's box, HOME being the one home it hides
credentials in.  Black-box: the program `AK_BIN` names runs through tests/fixtures/akbin.py as
a user number no account here has, with a `bwrap` that starts.
"""

import json
from pathlib import Path
import pwd
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home


class NoAccount(unittest.TestCase):
    def test_a_user_with_no_account_passes_the_box_check(self):
        home = Home()
        self.addCleanup(home.close)
        akconfig.write(home, ["opus", "astra"])
        fakeadapter.install(home, claude="work", codex="pass")
        home.fake("bwrap", "#!/bin/sh\nexit 0\n")
        taken = {account.pw_uid for account in pwd.getpwall()}
        number = str(next(uid for uid in range(54321, 60000) if uid not in taken))
        # four checks: the launch ends at the task, past the box, and starts no turn
        task = taskfile.write(home, "none", "Fix api", done_when=("true",) * 4)
        done = home.run("unshare", "--user", f"--map-user={number}", f"--map-group={number}",
                        home.program, "run", str(task))
        state = json.loads((taskfile.only_run(home) / "run.json").read_text())
        self.assertEqual((done.code, state["state"]), (2, "error"), done.out + done.err)
        self.assertIn("4 done-when checks", state["error"])


if __name__ == "__main__":
    unittest.main()
