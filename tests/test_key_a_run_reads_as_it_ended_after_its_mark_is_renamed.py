"""A run that ended PASS and merged reads as it ended after a mark it ran under is renamed.

On 17 Nov 2026 a merged run's reviewer mark was renamed in the config ten minutes after it
landed, and its seat was told the run finished FAIL.  The record holds both providers as they
were at review; a mark the config no longer defines leaves them standing, and one it still
defines is compared with them as before.  A job's task reads its run the same way in
`ak run status`.  Black-box: AK_BIN, a Home, git Rig, fake GitHub and the Seat that launched
the run, told at one tick.
"""

from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akseat import Seat
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

RUN = "20261117-2000-acme-api"


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class ARunReadsAsItEndedAfterItsMarkIsRenamed(unittest.TestCase):
    def told(self, models, reviewer_provider="openai"):
        """The line the seat is told of a run opus built and astra reviewed, merged, once the
        config defines `models`; and the run's pull request."""
        home = Home()
        self.addCleanup(home.close)
        akconfig.write(home, ["opus", "astra"])
        rig = Rig(home, "widget", files={"AGENTS.md": "---\n---\n"})
        github = GitHub(home)
        seat = Seat(home, "acme", cwd=rig.path, planned=True, record={"repo": str(rig.path)})
        sha = rig.branch("fix-api", {"api.txt": "ready\n"})
        pr = github.open_pr(rig, "fix-api", title="Acme api")
        done = home.run("gh", "pr", "merge", pr, "--squash", cwd=rig.path)
        self.assertEqual(done.code, 0, done.out + done.err)
        home.write(f".agentkit/runs/{RUN}/run.json", {
            "run_id": RUN, "title": "Acme api", "state": "pass", "verdict": "PASS",
            "repo": str(rig.path), "launched_session": seat.name, "pr": pr, "merged": True,
            "merge_sha": github.pr(1)["merge"]["commit"], "finished_at": time.time(),
            "deployed": None, "health": {}, "executor": "opus", "reviewer": "astra",
            "review": {"executor": "opus", "reviewer": "astra",
                       "executor_provider": "anthropic", "reviewer_provider": reviewer_provider,
                       "verdict": "PASS", "returncode": 0, "done_when": True,
                       "head_sha": sha, "tree_sha": rig.git("rev-parse", f"{sha}^{{tree}}")}})
        akconfig.write(home, models)
        done = home.tick()
        self.assertEqual(done.code, 0, done.out + done.err)
        line, = seat.wait_lines(1)
        return line, pr

    def test_its_reviewers_mark_renamed_it_reads_pass_merged(self):
        line, pr = self.told({"opus": {}, "nova": akconfig.SHIPPED["astra"]})
        self.assertIn(f"run {RUN} finished PASS merged: {pr}.", line)

    def test_its_reviewers_mark_removed_it_reads_pass_merged(self):
        line, pr = self.told(["opus"])
        self.assertIn(f"run {RUN} finished PASS merged: {pr}.", line)

    def test_a_mark_still_defined_and_named_another_provider_reads_fail(self):
        line, _ = self.told(["opus", "astra"], reviewer_provider="anthropic")
        self.assertIn(f"run {RUN} finished FAIL", line)


class AJobsTaskReadsAsItEndedAfterItsMarkIsRenamed(unittest.TestCase):
    def test_its_reviewers_mark_renamed_a_passed_task_reads_passed(self):
        home, now = Home(), time.time()
        self.addCleanup(home.close)
        home.write(f".agentkit/runs/{RUN}/run.json", {
            "run_id": RUN, "title": "Acme api", "state": "pass", "verdict": "PASS",
            "no_merge": True, "round_summaries": [{}, {}], "finished_at": now - 600,
            "executor": "opus", "reviewer": "astra",
            "review": {"executor": "opus", "reviewer": "astra", "executor_provider": "anthropic",
                       "reviewer_provider": "openai", "verdict": "PASS", "returncode": 0,
                       "done_when": True}})
        home.write(".agentkit/jobs/20261117-200000-acme-api/job.json", {
            "job_id": "20261117-200000-acme-api", "started_at": now - 1200,
            "finished_at": now - 600,
            "tasks": [{"name": "acme-api.md", "state": "passed", "run_id": RUN}]})
        akconfig.write(home, {"opus": {}, "nova": akconfig.SHIPPED["astra"]})
        done = home.ak("run", "status")
        self.assertEqual(done.code, 0, done.out + done.err)
        lines = done.out.splitlines()
        self.assertIn("job 20261117-200000-acme-api: 1 passed", lines)
        self.assertIn("  acme-api.md: PASS, passed after 2 rounds", lines)


if __name__ == "__main__":
    unittest.main()
