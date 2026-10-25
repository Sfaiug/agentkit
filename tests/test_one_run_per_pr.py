"""A second run on a pull request is refused at launch while one on it has not ended.

`ak run --review-pr` finds every other run on that pull request, however its URL is spelled
(`transitions.runs_on`), and refuses before any slot wait while one of them has not ended
(`record.ENDED`), naming it and `ak wait` on it; a run that ended, or a run on another pull
request, does not stand in the way.  Offline: a temporary HOME, fake records and a fake GitHub.
"""

from contextlib import ExitStack, redirect_stdout
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import box, config, gate, record, run

URL = "https://github.com/acme/widget/pull/7"


class OneRunPerPr(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-one-run-per-pr-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        stack = ExitStack()
        self.addCleanup(stack.close)
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            stack.enter_context(patch.object(config, name, self.root / name.lower()))
        stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "AGENTKIT_SESSION": "", "AGENTKIT_RUN": "", "AK_PARENT_RUN": "",
            "AK_RUN_LOG": "", "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "1",
            "AGENTKIT_DISCORD_WEBHOOK": "off", "NO_COLOR": "1",
            "AK_HOST_READINGS": json.dumps({"free_mb": 4096, "mem_total_mb": 16384, "load": 1,
                                            "cpus": 8})}))
        stack.enter_context(redirect_stdout(io.StringIO()))
        config.ensure_dirs()
        # someone else's PR: a review only, read from a fake GitHub
        pr = {"state": "OPEN", "title": "Mend the fence", "author": "someone", "baseRefName": "main",
              "headRefOid": "a" * 40, "body": ""}
        stack.enter_context(patch.object(run, "pr_view", return_value=pr))
        stack.enter_context(patch.object(run, "viewer_login", return_value="owner"))
        stack.enter_context(patch.object(run, "collect_usage", return_value={}))
        stack.enter_context(patch.object(record, "process_active", return_value=True))
        stack.enter_context(patch.object(box, "check"))

    def other_run(self, run_id, state, url):
        run_dir = config.RUNS / run_id
        run_dir.mkdir()
        record.save_state(run_dir, {"run_id": run_id, "state": state, "review_pr": url,
                                    "started_at": 1000.0})

    def launch(self):
        """(the refusal or None, how many background runs started)."""
        with patch.object(run, "spawn_bg", return_value=0) as spawned, \
                patch.object(gate, "wait_for_slot", side_effect=AssertionError("waited for a slot")):
            try:
                run.main(["--review-pr", URL, "--bg"])
            except config.Error as refused:
                return str(refused), spawned.call_count
        return None, spawned.call_count

    def test_a_going_run_on_the_pr_however_spelled_refuses_the_launch(self):
        self.other_run("20261024-1700-review-pr-7", "waiting", "https://github.com/ACME/Widget/pull/7/")
        why, spawned = self.launch()
        self.assertIn("20261024-1700-review-pr-7", why)
        self.assertIn("`ak wait 20261024-1700-review-pr-7`", why)
        self.assertEqual(spawned, 0)

    def test_a_run_on_the_pr_that_ended_does_not_stand_in_the_way(self):
        self.other_run("20261024-1700-review-pr-7", "pass", URL)
        self.assertEqual(self.launch(), (None, 1))

    def test_a_receipt_not_yet_past_preflight_refuses_the_next(self):
        # two launches at once, or a launcher gone before its preflight, whose run is resumed
        launches = [config.RUNS / name for name in ("launch-a", "launch-b")]
        for run_dir in launches:
            run_dir.mkdir()
        self.assertIsNone(run.capture_launch(launches[0], {"--review-pr": URL}))
        self.assertIn("`ak wait launch-a`", run.capture_launch(launches[1], {"--review-pr": URL}))

    def test_a_going_run_on_another_pr_does_not_stand_in_the_way(self):
        self.other_run("20261024-1700-review-pr-8", "running", "https://github.com/acme/widget/pull/8")
        self.assertEqual(self.launch(), (None, 1))


if __name__ == "__main__":
    unittest.main(verbosity=2)
