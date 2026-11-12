"""A suite's cost is what one piece needed while it ran: the CPU seconds its boxes needed over the
seconds those boxes ran, however long its places stood empty meanwhile.

Offline: temporary HOME and injected host readings; each box's command and report are faked, on
an injected clock (tests/fixtures/clock.py) where every box starts at 0 and reads its own end.
"""

from contextlib import ExitStack
from io import BytesIO
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from fixtures.clock import Clock
from fixtures.sandbox import account_home
from agentkit import box, config, gate, record, worker

ROOM = {"cpus": 3, "load": 0, "free_mb": 16000}     # four pieces at the initial cost
SUITE = 'printf "piece %s\\n" "$AK_SHARD"'
NEEDED = 2      # the CPU seconds each box needs for every second it runs


class ASuitesCostIsWhatItsRunningPiecesNeeded(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-running-cost-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(account_home(self.root))
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            stack.enter_context(patch.object(config, name, self.root / name.lower()))
        stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "AK_MAX_RUNS": "0", "AK_HOST_READINGS": json.dumps(ROOM),
            "AK_CGROUP_FILE": str(self.root / "no-cgroup")}))
        config.ensure_dirs()
        self.run_dir = config.RUNS / "fixture"
        self.run_dir.mkdir()
        record.save_state(self.run_dir, {"run_id": "fixture", "state": "running",
                                        "repo": str(self.root)})

    def recorded(self, ends):
        """The cost a pass records whose pieces' boxes all start at 0, the one of share k ending
        at `ends[k - 1]`; the pass ends with its last."""
        latest, mine = [0.0], threading.local()
        clock = Clock(time.sleep)
        clock.monotonic = lambda: getattr(mine, "now", latest[0])
        together = threading.Barrier(len(ends), timeout=30)

        def limited(cmd, limit, env, output, **_kw):
            together.wait()     # every box has read its start
            mine.now = ends[int(env["AK_SHARD"].split("/")[0]) - 1]
            latest[0] = max(latest[0], mine.now)
            return 0, "", False

        with patch.object(gate, "time", clock), patch.object(worker, "time", clock), \
                patch.object(worker, "limited", side_effect=limited), \
                patch.object(box, "cpu_seconds", lambda _out_dir: NEEDED * mine.now):
            code, text, killed = gate.run_suite(
                SUITE, 3600, cwd=self.root, activity=self.run_dir / "live.log",
                output=BytesIO(), run_dir=self.run_dir)
        self.assertEqual((code, killed), (0, False), text)
        self.assertEqual(text.count("--- AK_SHARD="), len(ends))
        return gate.read_suite_cost(gate.suite_cost(SUITE, self.root, self.run_dir)[0])

    def test_pieces_run_all_at_once_cost_what_each_needed(self):
        self.assertEqual(self.recorded([60, 60, 60, 60])["cpus"], NEEDED)

    def test_places_left_empty_for_half_the_pass_change_nothing(self):
        self.assertEqual(self.recorded([60, 60, 120, 120])["cpus"], NEEDED)


if __name__ == "__main__":
    unittest.main()
