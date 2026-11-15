"""A merge ak finds done after its `gh pr merge` failed says, in the run's log, what the call
answered: its exit code and the last of its output, so whether GitHub, gh or ak failed it shows.

Black-box: the program `AK_BIN` names runs a task to its merge through tests/fixtures/akbin.py,
against the bare origin of gitrig.py and the GitHub of fakegh.py, whose `gh pr merge` merges and
then either loses its connection before GitHub's answer, checked straight after the call, or
answers 504 Gateway Timeout, checked after ak's retry wait (a minute, so this file takes a little
over a minute).
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

ANSWERS = {
    "reset": ('Post "https://api.github.com/graphql": read tcp 192.0.2.7:50412->'
              "140.82.121.6:443: read: connection reset by peer\n"),
    "504": ('non-200 OK status code: 504 Gateway Timeout body: "{\\"message\\": \\"We '
            "couldn't respond to your request in time. Sorry about that. Please try "
            'resubmitting your request and contact us if the problem persists.\\"}"\n'),
}


class MergeFoundDoneSaysWhy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runs = {}
        for name, err in ANSWERS.items():
            home = Home()
            cls.addClassCleanup(home.close)
            rig = Rig(home)
            gh = GitHub(home)
            gh.grant(rig.slug, "WRITE")
            gh.reply("pr merge", err=err, code=1, acted=True)
            akconfig.write(home, ["opus", "astra"])
            fakeadapter.install(home, claude="work", codex="pass")
            task = taskfile.write(home, rig.path, "Add retry file")
            done = home.ak("run", str(task), timeout=300)
            run_dir = taskfile.only_run(home)
            state = json.loads((run_dir / "run.json").read_text())
            cls.runs[name] = (err, gh, done, run_dir, state)

    def test_the_log_says_the_call_s_exit_and_output(self):
        for name, (err, _gh, _done, run_dir, _state) in self.runs.items():
            with self.subTest(name):
                warned = [line for line in (run_dir / "log.txt").read_text().splitlines()
                          if "WARN" in line and "exited 1" in line]
                self.assertEqual(len(warned), 1, warned)
                self.assertIn(err.strip(), warned[0])

    def test_the_run_still_ends_merged_with_no_revert_line(self):
        for name, (_err, gh, done, _run_dir, state) in self.runs.items():
            with self.subTest(name):
                self.assertEqual(done.code, 0, done.out + done.err)
                self.assertTrue(state["merged"], state)
                pr = gh.pr(1)
                self.assertEqual(pr["state"], "MERGED")
                self.assertNotIn("## How to revert", pr["body"])


if __name__ == "__main__":
    unittest.main()
