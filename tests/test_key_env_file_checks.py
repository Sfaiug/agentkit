"""The repository's env file under HOME/.agentkit/env/ is in the environment of its checks.

A project's test secrets live on the machine, never in the repository: ak reads
`~/.agentkit/env/<the checkout's directory name>.env`, one KEY=value a line, and every done-when
check of a run on that checkout sees those variables.  Without them a check that needs a secret
fails a round no executor can fix.  The run's log names the file and the variables it set,
never their values.  Black-box: the program `AK_BIN` names runs from outside through
tests/fixtures/akbin.py, on a project from gitrig.py, with scripted harnesses from
fakeadapter.py.
"""

import json
import re
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.gitrig import Rig

CHECKS = ("test -f retry.txt", '[ "${SMOKE_SECRET:-}" = v1 ]',
          '[ "${SMOKE_REGION:-}" = north ]')


class EnvFileReachesChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.rig = Rig(cls.home, "repo")
        akconfig.write(cls.home, ["opus", "astra"])
        fakeadapter.install(cls.home, claude="work", codex="pass")
        cls.env_file = cls.home.write(".agentkit/env/repo.env", (
            "# test secrets for repo\n\nSMOKE_SECRET=\"v1\"\nexport SMOKE_REGION=north\n"))
        # Another checkout's file: the one read is chosen by this checkout's name alone.
        cls.home.write(".agentkit/env/widgets.env", "SMOKE_SECRET=v2\nSMOKE_REGION=south\n")
        task = taskfile.write(cls.home, cls.rig.path, "Add retry file", done_when=CHECKS)
        cls.done = cls.home.ak("run", str(task), "--no-merge", timeout=300)
        cls.run_dir = taskfile.only_run(cls.home)
        cls.state = json.loads((cls.run_dir / "run.json").read_text())

    def test_every_check_sees_the_checkouts_variables_and_round_one_passes(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual((self.state["state"], self.state["verdict"]), ("pass", "PASS"))
        self.assertEqual([summary["verdict"] for summary in self.state["round_summaries"]],
                         ["PASS"])
        log = (self.run_dir / "round-1/donewhen.log").read_text()
        for check in CHECKS:
            with self.subTest(check):
                self.assertRegex(log, rf"(?m)^\$ {re.escape(check)}\n\[exit 0\]$")

    def test_the_log_names_the_file_and_the_variables_it_set_but_no_value(self):
        lines = [re.sub(r"^\[[\d:]+\] ", "", line)
                 for line in (self.run_dir / "log.txt").read_text().splitlines()]
        named = [line for line in lines if line.startswith("env: ")]
        self.assertEqual(named, [f"env: {self.env_file} -> SMOKE_REGION, SMOKE_SECRET"])


if __name__ == "__main__":
    unittest.main()
