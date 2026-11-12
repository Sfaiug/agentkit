"""A job's task whose worker runs out of usage waits for the window, and the job goes on.

On 11 Nov 2026 a job called one `FAIL: needs you` and dropped the two tasks queued behind it,
nine minutes before the tick resumed its run.  Black-box, as tests/test_key_exhausted_resume.py.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import taskfile
from test_key_exhausted_resume import SPENT, TITLES, record, staged


class AJobWaitsForUsage(unittest.TestCase):
    def test_the_refused_task_is_resumed_and_the_job_ends_with_every_task_passed(self):
        refused = {"final": SPENT + " Try again at {in 5}.", "exit": 1}
        home = staged(type(self), ["opus"], claude=[refused, "work"], codex="pass")
        tasks = [str(taskfile.write(home, self.rig.path, title)) for title in TITLES]
        done = home.ak("run", *tasks, "--no-merge", timeout=300)
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertNotIn("needs you", done.out + done.err)
        self.assertEqual([record(run)["state"] for run in taskfile.runs(home)], ["pass"] * 2)


if __name__ == "__main__":
    unittest.main()
