"""A stalled run started from no seat reaches the owner once.

A run launched outside any seat that climbs the stall ladder to its park is one nothing else
can move: the tick pages the owner, naming the run and how to resume it, and later ticks
neither page again nor warn about it.  A page the webhook did not take is asked again.

Offline: a temporary HOME, a fake process table (the loop is gone) and a fake sender behind
the suites' sink; no seat, webhook or tmux.
"""

from contextlib import ExitStack, redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import urllib.error

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, notify, watch  # noqa: E402
from agentkit import record as run_record  # noqa: E402

RUN = "20261021-0000-acme-parser"
SINK = "https://sink.invalid/api/webhooks/suite/token"
TASK = """---
rounds: 3
---
# Fix the parser

## Goal
Parse it.

## Done when
```bash
bash tests/smoke.sh
```
"""


class SeatlessStallTold(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-seatless-stall-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        stack = ExitStack()
        self.addCleanup(stack.close)
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            stack.enter_context(patch.object(config, name, self.root / name.lower()))
        stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), config.SESSION_ENV: "", "AK_RUN_ROLE": "orchestrator",
            "AK_RUN_LOG": "", config.RUN_DIR_ENV: "", notify.SINK_ENV: SINK,
            "AGENTKIT_DISCORD_WEBHOOK": "", "AGENTKIT_DISCORD_USER_ID": ""}))
        stack.enter_context(redirect_stdout(io.StringIO()))
        stack.enter_context(redirect_stderr(io.StringIO()))
        config.ensure_dirs()
        # the fake process table: the run's loop is gone
        stack.enter_context(patch.object(run_record, "process_active", return_value=False))
        stack.enter_context(patch.object(notify, "RETRY_BACKOFF", (0,)))
        self.posts, self.refuse, self.logs = [], 0, []
        stack.enter_context(patch.object(notify.urllib.request, "urlopen", side_effect=self.post))
        self.run_dir = config.RUNS / RUN
        self.run_dir.mkdir(parents=True)
        (self.run_dir / "task.md").write_text(TASK)
        (self.run_dir / "log.txt").write_text("[00:00:00] run started\n")
        step = "done-when: bash tests/smoke.sh"
        (self.run_dir / "run.json").write_text(json.dumps({
            "run_id": RUN, "title": "Fix the parser", "task": str(self.run_dir / "task.md"),
            "launched_session": None, "scratch": True, "state": "running", "rounds": 3,
            "executor": "opus", "reviewer": "astra", "pid": 2 ** 30,
            "started_at": time.time() - 7200, "finished_at": None,
            "round_summaries": [{"round": 1, "verdict": "FAIL", "summary": "first try"}],
            "stalls": [{"time": time.time() - 7200, "round": 2, "step": step,
                        "action": "killed step"},
                       {"time": time.time() - 3600, "round": 2, "step": step,
                        "action": "resumed"}]}))
        old = time.time() - 61 * 60
        for path in self.run_dir.iterdir():
            os.utime(path, (old, old))

    def post(self, request, **_kw):
        if self.refuse:
            self.refuse -= 1
            raise urllib.error.HTTPError(request.full_url, 503, "unavailable", {}, None)
        self.posts.append(json.loads(request.data))
        return io.BytesIO(b"{}")

    def tick(self):
        watch.recover_runs({}, dry_run=False, log=self.logs.append, now=time.time())
        return json.loads((self.run_dir / "run.json").read_text())

    def test_parked_without_a_seat_pages_the_owner_once(self):
        state = self.tick()
        self.assertEqual(state["state"], "stalled")
        self.assertTrue(state["stalled_notified"])
        self.assertEqual(len(self.posts), 1)
        self.assertIn(f"ak run resume {RUN}", self.posts[0]["content"])
        for _ in range(2):
            self.tick()
        self.assertEqual(len(self.posts), 1, "later ticks page nobody again")
        self.assertFalse([line for line in self.logs if "WARN" in line], self.logs)

    def test_a_page_the_webhook_refused_is_asked_again(self):
        self.refuse = 1
        state = self.tick()
        self.assertEqual(state["state"], "stalled")
        self.assertFalse(state.get("stalled_notified"))
        self.assertEqual(self.posts, [])
        self.assertTrue(self.tick()["stalled_notified"])
        self.assertEqual(len(self.posts), 1)
        self.tick()
        self.assertEqual(len(self.posts), 1)


if __name__ == "__main__":
    unittest.main()
