"""A run parked on its executor's refusal resumes on a marked builder of the reviewer's lab once
that one has room, rather than waiting for the moment the refusal named.

astra (openai) and opus (anthropic) build, opus alone reviews: with no lineup stored, each
provider is a lab.  astra refused the work with a moment to try again at, still to come, so the
tick leaves it out until then (`refusal_retry`).  The owner, 22 Nov 2026: "Own lab reviews when
spent": with opus's window refilled, opus builds and reviews its own work.  Black-box: `ak watch
--dry-run` through AK_BIN, on the fixtures of tests/test_key_exhausted_resume.py.
"""

import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_key_exhausted_resume import staged


class RefusedExecutorsBackoff(unittest.TestCase):
    def test_a_dry_tick_would_resume_it_on_opus(self):
        home = staged(self, ["astra", "opus"], claude="pass", codex="pass")
        run = "20261123-0000-fix-api"
        home.write(f".agentkit/runs/{run}/run.json", {
            "run_id": run, "state": "exhausted", "quota_dry": True, "step": "executor",
            "executor": "astra", "reviewer": "opus", "worktree": str(home.path),
            "workers": ["astra", "opus"], "reviewers": ["opus"],
            "refusal_retry": {"model": "astra", "at": time.time() + 3600}})
        self.assertIn(f"would resume {run}: anthropic window refilled",
                      home.ak("watch", "--dry-run").out.splitlines())


if __name__ == "__main__":
    unittest.main()
