"""A seat the owner closed counts only the hand-backs still waiting for it, not every run whose
`handback_pending` outlived its delivery.  Black-box: `AK_BIN` runs `ak orch stop` and `ak orch
list --why` (tests/fixtures/akbin.py); this test fails against `/bin/false`."""

import re
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home

CLOSED = "session closed by the owner: reopen it from past sessions"


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ClosedSeatCountsOnlyWaitingHandbacks(unittest.TestCase):
    def test_handed_back_endings_are_not_counted(self):
        home = Home()
        self.addCleanup(home.close)
        ended = time.time() - 3 * 86400

        def run(name, seat, **marks):
            home.write(f".agentkit/runs/{name}/run.json", {
                "run_id": name, "title": name, "state": "pass", "verdict": "PASS",
                "launched_session": seat, "finished_at": ended,
                "handback_pending": f"{name}: PASS", **marks})

        for seat in ("acme", "beta"):
            home.write(f".agentkit/state/session-{seat}.json", {
                "orchestrator": "opus", "workers": ["opus"], "conversation": f"conv-{seat}",
                "cwd": str(home.path), "id_source": "launcher", "launched": 1})
            for n in range(3):      # handed back days ago, the flag left behind
                run(f"{seat}-fix-{n}", seat, handed_back=ended + 60, reported=True)
            self.assertEqual(home.ak("orch", "stop", seat).code, 0)
        run("beta-fix-3", "beta", handed_back=False, reported=False)     # still waiting
        done = home.ak("orch", "list", "--why")
        self.assertEqual(done.code, 0, done.err)
        reason = lambda name: re.search(rf"^{name} .*\n.*\n  reason: +(.*)", done.out, re.M)[1]
        self.assertEqual(reason("acme"), CLOSED)
        self.assertEqual(reason("beta"), f"{CLOSED} · 1 hand-backs waiting")


if __name__ == "__main__":
    unittest.main()
