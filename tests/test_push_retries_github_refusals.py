"""A push GitHub refuses for its own reasons is tried again; only the lease's refusal ends the run.

A fixer's push ended a review run on `! [remote rejected] HEAD -> ak/acme-row (failed)`, and
the same push went through by hand a minute later.  Both pushes to origin -- the delivery's
(`deliver.push`) and a fix's onto a PR branch (`deliver.push_pr_branch`) -- try such a refusal
again over the same lease, after ak's transient waits and a bounded number of times; a lease
refusal (`stale info`) ends the run at once.  The git call and the sleep are injected: nothing
is pushed anywhere and nothing waits.
"""

from contextlib import ExitStack
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, deliver, gitcall, turns

GITHUB = (" ! [remote rejected]     HEAD -> ak/acme-row (failed)\n"
          "error: failed to push some refs to 'github.com:acme/acme'")
LEASE = (" ! [rejected]        ak/acme-row -> ak/acme-row (stale info)\n"
         "error: failed to push some refs to 'github.com:acme/acme'")


class Fake:
    def __init__(self, root):
        self.run_dir, self.wt = root, root
        self.state = {"branch": "ak/acme-row", "verdict": "PASS", "review": {"verdict": "PASS"}}
        self.lines = []

    def log(self, line):
        self.lines.append(line)

    def write(self):
        pass


class PushRetries(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="ak-push-retries-")
        self.addCleanup(tmp.cleanup)
        self.lp = Fake(Path(tmp.name))
        self.pushes, self.slept = [], []
        sleep = patch.object(deliver.time, "sleep", side_effect=self.slept.append)
        sleep.start()
        self.addCleanup(sleep.stop)

    def answering(self, *answers):
        """git, answering each push with the next of `answers` and anything else with nothing."""
        answers = list(answers)

        def git_out(cwd, *args, **_kw):
            self.assertEqual(args[0], "push")
            self.pushes.append(args)
            return answers.pop(0)
        stack = ExitStack()
        stack.enter_context(patch.object(gitcall, "git", return_value=""))
        stack.enter_context(patch.object(gitcall, "git_out", side_effect=git_out))
        return stack

    def retries(self):
        return [line for line in self.lp.lines if "GitHub refused the push" in line]

    def deliver(self, *answers):
        with self.answering(*answers), patch.object(deliver, "require_review_pass"):
            return deliver.push(self.lp)

    def fix(self, *answers):
        remote = {"ref": "ak/acme-row", "repo": {"clone_url": "https://github.com/acme/acme.git"}}
        with self.answering(*answers):
            deliver.push_pr_branch(self.lp, remote, "abc123")

    def test_a_delivery_push_github_refused_goes_through_on_the_next_try(self):
        self.assertTrue(self.deliver((1, GITHUB), (0, "")), self.lp.state.get("merge_note"))
        self.assertEqual(len(self.pushes), 2)
        self.assertEqual(self.pushes[0], self.pushes[1], "the same push over the same lease")
        self.assertEqual(self.slept, [turns.transient_delay(1)])
        [line] = self.retries()
        self.assertIn("[remote rejected]     HEAD -> ak/acme-row (failed)", line)

    def test_a_fix_push_github_refused_goes_through_on_the_next_try(self):
        self.fix((1, GITHUB), (0, ""))
        self.assertEqual(len(self.pushes), 2)
        self.assertEqual(self.pushes[0], self.pushes[1], "the same push over the same lease")
        self.assertIn("--force-with-lease=refs/heads/ak/acme-row:abc123", self.pushes[1])
        self.assertEqual(self.slept, [turns.transient_delay(1)])
        self.assertEqual(len(self.retries()), 1)

    def test_a_lease_refusal_ends_the_delivery_at_once(self):
        self.assertFalse(self.deliver((1, LEASE)))
        self.assertEqual((len(self.pushes), self.slept, self.retries()), (1, [], []))
        self.assertIn("taken by another run", self.lp.state["merge_note"])
        self.assertTrue(self.lp.state["merge_failed"])

    def test_a_lease_refusal_ends_the_fix_at_once(self):
        with self.assertRaisesRegex(config.Error, "pushing to the PR branch failed: .*stale info"):
            self.fix((1, LEASE))
        self.assertEqual((len(self.pushes), self.slept, self.retries()), (1, [], []))

    def test_a_github_refusal_is_not_read_as_a_taken_branch(self):
        refusals = [(1, GITHUB)] * (deliver.GITHUB_RETRIES + 1)
        self.assertFalse(self.deliver(*refusals))
        self.assertEqual(len(self.pushes), deliver.GITHUB_RETRIES + 1)
        self.assertEqual(self.slept, [turns.transient_delay(n)
                                      for n in range(1, deliver.GITHUB_RETRIES + 1)])
        self.assertEqual(len(self.retries()), deliver.GITHUB_RETRIES)
        note = self.lp.state["merge_note"]
        self.assertIn("pushing ak/acme-row to origin failed", note)
        self.assertIn("(failed)", note)
        self.assertNotIn("taken by another run", note)

    def test_a_fix_github_keeps_refusing_ends_with_todays_error(self):
        with self.assertRaisesRegex(config.Error, r"pushing to the PR branch failed: .*\(failed\)"):
            self.fix(*[(1, GITHUB)] * (deliver.GITHUB_RETRIES + 1))
        self.assertEqual(len(self.pushes), deliver.GITHUB_RETRIES + 1)
        self.assertEqual(len(self.slept), deliver.GITHUB_RETRIES)

    def test_a_lease_refusal_after_a_github_refusal_is_not_tried_again(self):
        # someone pushed while GitHub was refusing: the retry's lease says so, and that ends it
        self.assertFalse(self.deliver((1, GITHUB), (1, LEASE)))
        self.assertEqual((len(self.pushes), len(self.slept)), (2, 1))
        self.assertIn("taken by another run", self.lp.state["merge_note"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
