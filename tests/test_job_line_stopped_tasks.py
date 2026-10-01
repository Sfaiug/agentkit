"""A job's closing line counts only failed or blocked tasks as needing the owner. Offline.

A task the owner stopped was ended on purpose: the line names it as stopped, and a job whose
only undelivered tasks were stopped says nobody is needed instead of sending the seat after it.
"""

from contextlib import ExitStack
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, job as jobs, run


class JobLineStoppedTasks(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".job-line-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(config, "HOME", self.root / ".agentkit"))
        for name in ("RUNS", "WT", "STATE", "TMP"):
            stack.enter_context(patch.object(config, name, config.HOME / name.lower()))
        env = {key: value for key, value in os.environ.items()
               if key not in ("AGENTKIT_RUN", "AK_PARENT_RUN", "AK_RUN_LOG")}
        env.update(HOME=str(self.root), AK_RUN_DEPTH="0", AK_MAX_RUNS="0",
                   AGENTKIT_DISCORD_WEBHOOK="off")
        stack.enter_context(patch.dict(os.environ, env, clear=True))
        self.handed = []
        self.cards = []
        stack.enter_context(patch.object(
            jobs, "job_hand_back",
            lambda seat, line, *args, **kwargs: self.handed.append(line) or "sent"))
        stack.enter_context(patch.object(
            run.notify, "shaped",
            lambda kind, text, **kwargs: self.cards.append((kind, text)) or 0))
        self.job_dir = self.root / "jobs" / "job-acme"
        self.job_dir.mkdir(parents=True)

    def close(self, *states):
        tasks = [{"name": f"fix-api-{n}.md", "state": state, "after": [],
                  "verdict_line": f"fix-api-{n}.md: {state}"}
                 for n, state in enumerate(states)]
        job = {"job_id": "job-acme", "seat": "seat-acme", "tasks": tasks}
        return jobs.run_job_loop({}, self.job_dir, job, to_file=True)

    def test_a_job_whose_only_undelivered_tasks_were_stopped_needs_nobody(self):
        self.close("passed", "stopped", "stopped")
        self.assertEqual(self.handed, [], "a stopped task is never handed back as needing you")
        self.assertEqual(len(self.cards), 1)
        kind, text = self.cards[0]
        self.assertEqual(kind, "done")
        self.assertNotIn("need you", text)
        self.assertIn("2 task(s) stopped", text)
        self.assertIn("nobody is needed", text)

    def test_only_failed_and_blocked_tasks_are_counted_as_needing_you(self):
        self.close("failed", "blocked", "stopped", "stopped", "passed")
        self.assertEqual(len(self.handed), 1)
        self.assertIn("job job-acme: 2 task(s) need you, 2 stopped", self.handed[0])


if __name__ == "__main__":
    unittest.main()
