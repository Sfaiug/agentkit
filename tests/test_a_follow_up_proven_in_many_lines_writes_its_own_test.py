"""A finding ak makes a follow-up, its defect older than the task, whose proof spans lines gets a
fix run with a regression test of its own: each of the proof's lines would run as a done-when
check of its own, and past three ak refuses the run.

Temporary HOME, local git remote, fake gh and fake models (`test_followup_runs`); no detached run
is started.
"""

import sys
import unittest

import test_followup_runs as runs
from agentkit import hand_in, record, task

PROOF = "python3 - <<'PY'\nfrom broken import first\nfirst([])\nPY"
ONE_LINE = "python3 -c 'from broken import first; first([])'"


def follow_up(run):
    """A finding on a line the change left, whose proof fails on base too (`prompts`)."""
    return {"kind": "follow-up", "path": "broken.py", "line": 2, "what": "empty input crashes",
            "why": "callers crash", "before": "base abc123: the proof fails there too",
            "evidence": {"run": run, "commit": "1" * 40, "returncode": 1, "output": "IndexError"}}


class FollowUpProvenInManyLines(unittest.TestCase):
    script = runs.FollowupRuns.script
    setUp, git, spawn, gh = (runs.FollowupRuns.setUp, runs.FollowupRuns.git,
                             runs.FollowupRuns.spawn, runs.FollowupRuns.gh)
    source, start = runs.FollowupRuns.source, runs.FollowupRuns.start

    def fix_run(self, run):
        review = hand_in.Review([follow_up(run), {"kind": "done"}])
        directory, state = self.source(followups=review.followups,
                                       followup_checks=review.followup_checks)
        children = self.start(directory, state)
        self.assertEqual(len(children), 1, "\n".join(self.logs))     # its fix run started
        _, body, _ = task.parse_task(children[0] / "task.md")
        return task.done_when(body, children[0] / "task.md"), record.read_state(children[0])

    def test_a_proof_of_many_lines_leaves_its_fix_run_one_check_a_test_of_its_own(self):
        checks, receipt = self.fix_run(PROOF)
        self.assertEqual(len(checks), 1)
        self.assertTrue(checks[0].startswith("bash ") and checks[0].endswith("regression.sh"))
        self.assertEqual(receipt["base_proof"], "regression.sh")

    def test_a_proof_on_one_line_stays_its_fix_runs_check(self):
        self.assertEqual(self.fix_run(ONE_LINE)[0], [ONE_LINE])


if __name__ == "__main__":
    sys.exit(unittest.main())
