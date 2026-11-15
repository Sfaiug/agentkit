"""A seat's own PR ak squash-merged says how its final check went, ahead of how to revert it.

The PR keeps the seat's description, so the `final check:` line of the body ak writes for a
task's PR never reaches it: the one update after the merge adds it.  Black-box: the program
`AK_BIN` names runs `ak run --review-pr` from outside through tests/fixtures/akbin.py, from the
seat of akseat.py, against the bare origin of gitrig.py and the GitHub of fakegh.py, with
scripted harnesses from fakeadapter.py.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.akseat import Seat
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

RULES = "---\ntests: test -f contrib.txt\nusers: none\n---\n# widgets\n"
DESCRIPTION = "Adds contrib.txt, which the widgets docs link to."


class OwnPrSaysItsFinalCheck(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.rig = Rig(cls.home, "widgets", files={"AGENTS.md": RULES})
        cls.gh = GitHub(cls.home)
        akconfig.write(cls.home, ["opus", "astra"])
        fakeadapter.install(cls.home, claude="pass", codex="pass")
        Seat(cls.home, "acme", cwd=cls.rig.path, alive=False,
             record={"workers": ["opus", "astra"]}, planned=True)
        cls.rig.branch("contrib", {"contrib.txt": "c\n"})
        url = cls.gh.open_pr(cls.rig, "contrib", body=DESCRIPTION)
        cls.done = cls.home.ak("run", "--review-pr", url, env={"AGENTKIT_SESSION": "acme"},
                               cwd=cls.rig.path, timeout=300)
        cls.result = (taskfile.only_run(cls.home) / "result.md").read_text()

    def test_the_merged_body_is_the_seat_s_then_the_final_check_then_how_to_revert(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        pr = self.gh.pr(1)
        self.assertEqual((pr["state"], pr["merge"]["method"]), ("MERGED", "squash"))
        (line,) = [line for line in self.result.splitlines() if line.startswith("final check: ")]
        self.assertTrue(line.startswith("final check: passed "), line)
        self.assertEqual(pr["body"], f"{DESCRIPTION}\n\n## Final check\n\n{line}\n\n"
                                     f"## How to revert\n\n```bash\ngit revert "
                                     f"{pr['merge']['commit']}\n```\n")


if __name__ == "__main__":
    unittest.main()
