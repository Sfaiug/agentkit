"""A seat's own PR that the merge step parks before it joins the landing line is the tick's to
retry.

A park off the line, here a rebase conflict the writer's model leaves unresolved through
every conflict round, is no ending a person owes anything: the run waits on the next merge to
main, and the tick resumes it then, as it does a task run parked the same way.  A dry tick
says so.  Black-box: the program `AK_BIN` names runs from outside through
tests/fixtures/akbin.py, as tests/test_key_own_pr_fix_and_land.py runs a seat's own PR.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_key_own_pr_fix_and_land import reviewed


class ParkedOffTheLine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # each fixer turn hands in done with the rebase still stopped on the conflict
        reviewed(cls, "pass", "pass", main={"contrib.txt": "main\n"})

    def test_the_run_waits_on_main_outside_any_line(self):
        self.assertEqual(self.state["state"], "waiting", self.done.out + self.done.err)
        self.assertEqual(self.state["waiting_on"]["ref"], "origin/main")
        self.assertNotIn("line", self.state["waiting_on"])
        self.assertEqual(self.gh.pr(1)["state"], "OPEN")

    def test_a_dry_tick_would_resume_it_after_the_next_merge_to_main(self):
        done = self.home.ak("watch", "--dry-run")
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertIn(f"would resume {self.run_dir.name} after the next merge to origin/main",
                      done.out.splitlines())


if __name__ == "__main__":
    unittest.main()
