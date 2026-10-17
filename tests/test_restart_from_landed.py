"""A run stopped waiting on the run that lands its `from:` branch starts again from the target.

Built on the branch after it landed by squash, the change would count the landed lines again
from where the branch left the target, and on a conflict with the target it could not take the
target in: a 164-line change was refused as 453.  A branch moved on past what landed keeps
`from:`.  Offline: the lease stage (`fixtures.leases`), a fake launch.
"""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from fixtures.leases import OLDER, YOUNGER, LiveRuns
from agentkit import config, leases, run
from agentkit import record

TASK = f"---\nrepo: acme\nfrom: ak/{OLDER}\n---\n# Change line 5\n"


class RestartFromLanded(LiveRuns):
    def restarted_task(self, beyond=False):
        """The task the younger run, built from the older run's branch, starts again with once
        the older one landed its branch's tip; with `beyond`, the branch moved on since."""
        older, _ = self.collide()
        record.save_state(config.RUNS / YOUNGER, {**self.state(YOUNGER), "from": f"ak/{OLDER}"})
        (config.RUNS / YOUNGER / "task.md").write_text(TASK)
        leases.scan(self.repo, now=2000)
        record.save_state(config.RUNS / OLDER, {**self.state(OLDER), "state": "pass", "merged": True,
                                                "head_sha": self.git(older, "rev-parse", "HEAD")})
        if beyond:
            self.edit(older, "api.py", 9, "the branch's line 9", commit=True)
        launched = []
        with patch.object(run, "preflight"), \
                patch.object(run, "spawn_bg", side_effect=lambda d, argv: launched.append(d)):
            leases.restart(log=self.logs.append, now=3000)
        fresh, = launched
        return (fresh / "task.md").read_text(), (fresh / "log.txt").read_text()

    def test_a_from_branch_that_landed_with_the_holder_is_dropped(self):
        task, log = self.restarted_task()
        self.assertEqual(task, f"---\nrepo: {self.repo}\n---\n# Change line 5\n")
        self.assertIn(f"ak/{OLDER} landed with it, so it starts from the target", log)

    def test_a_from_branch_moved_on_past_what_landed_is_kept(self):
        task, _ = self.restarted_task(beyond=True)
        self.assertIn(f"\nfrom: ak/{OLDER}\n", task)


if __name__ == "__main__":
    unittest.main()
