"""A job's task whose worker runs out of usage waits for the window, and the job goes on.

On 11 Nov 2026 a job called one `FAIL: needs you` and dropped the two tasks queued behind it,
nine minutes before the tick resumed its run.  The job's own retries wait the same way: when
GitHub refused a passed task's merge, the job's `ak run merge` whose conflict fixer is refused
keeps its run and lands once the window is back.  Black-box, as
tests/test_key_exhausted_resume.py.
"""

import shlex
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import taskfile
from fixtures.fakegh import GitHub
from test_key_exhausted_resume import SPENT, TITLES, record, staged

# GitHub refuses a merge twice, both tries a delivery makes, and main moves under the branch
# with the second: the job's own retry of the delivery meets the conflict.
REFUSE_TWICE = """#!/bin/sh
if [ "$1 $2" = "pr merge" ] && [ -e {flag} ]; then
  if [ -e {flag}.again ]; then
    rm -f {flag} {flag}.again
    git --git-dir={bare} update-ref refs/heads/main refs/fixture/sibling
  else
    : > {flag}.again
  fi
  echo 'GraphQL: Pull Request is not mergeable (mergePullRequest)' >&2
  exit 1
fi
"""


class AJobWaitsForUsage(unittest.TestCase):
    def test_the_refused_task_is_resumed_and_the_job_ends_with_every_task_passed(self):
        refused = {"final": SPENT + " Try again at {in 5}.", "exit": 1}
        home = staged(type(self), ["opus"], claude=[refused, "work"], codex="pass")
        tasks = [str(taskfile.write(home, self.rig.path, title)) for title in TITLES]
        done = home.ak("run", *tasks, "--no-merge", timeout=300)
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertNotIn("needs you", done.out + done.err)
        self.assertEqual([record(run)["state"] for run in taskfile.runs(home)], ["pass"] * 2)

    def test_a_delivery_retry_whose_fixer_is_refused_waits_then_lands(self):
        refused = {"final": SPENT + " Try again at {in 5}.", "exit": 1}
        resolve = {"sh": "printf 'hello\\nsibling\\n' > retry.txt && git add retry.txt && "
                         "GIT_EDITOR=true git rebase --continue",
                   "hand_in": [["done"]], "final": "Resolved both sides."}
        home = staged(type(self), ["opus"], codex="pass",
                      claude=["work", "pass", refused, resolve, "pass", "not-needed", "pass"])
        GitHub(home).grant(self.rig.slug, "WRITE")
        sibling = home.root / "sibling"
        self.assertEqual(home.run("git", "clone", "-q", str(self.rig.bare), str(sibling)).code, 0)
        (sibling / "retry.txt").write_text("sibling\n")
        for argv in (["add", "retry.txt"], ["commit", "-q", "-m", "sibling"],
                     ["push", "-q", "origin", "HEAD:refs/fixture/sibling"]):
            self.assertEqual(home.run("git", "-C", str(sibling), *argv).code, 0)
        flag = home.root / "merge-refused"
        flag.write_text("")
        delegate = (home.bin / "gh").read_text().split("\n", 1)[1]
        home.fake("gh", REFUSE_TWICE.format(flag=shlex.quote(str(flag)),
                                            bare=shlex.quote(str(self.rig.bare))) + delegate)
        tasks = [str(taskfile.write(home, self.rig.path, title)) for title in TITLES]
        done = home.ak("run", *tasks, "--in-order", timeout=900)
        self.assertFalse(flag.exists(), "GitHub never refused the merge twice")
        self.assertEqual(done.code, 0, done.out + done.err)
        # the fixer refused on the delivery retry came back on the same run, which landed
        self.assertEqual([turn["role"] for turn in self.fakes["claude"].runs()][:5],
                         ["executor", "reviewer", "fixer", "fixer", "reviewer"])
        first = min(taskfile.runs(home), key=lambda run: record(run)["started_at"])
        self.assertEqual([record(first)[key] for key in ("title", "state", "merged")],
                         [TITLES[0], "pass", True])


if __name__ == "__main__":
    unittest.main()
