"""A seat put to sleep reads asleep, not closed, its plan done or not, until the owner closes it.
Black-box: `AK_BIN` runs `ak orch stop` and `ak orch list --why` (tests/fixtures/akbin.py)."""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class SleepingSeatReadsAsleep(unittest.TestCase):
    def test_asleep_until_the_owner_closes_it(self):
        home = Home()
        self.addCleanup(home.close)
        for name in ("acme", "beta", "gamma"):
            home.write(f".agentkit/state/session-{name}.json", {
                "orchestrator": "opus", "workers": ["opus"], "conversation": f"conv-{name}",
                "cwd": str(home.path), "id_source": "launcher", "launched": 1, "asleep": 2})
        home.write(".agentkit/state/plan-beta.md", "- [x] Shipped it\n")
        self.assertEqual(home.ak("orch", "stop", "gamma").code, 0)
        done = home.ak("orch", "list", "--why")
        self.assertEqual(done.code, 0, done.err)
        reason = lambda name: re.search(rf"^{name} .*\n.*\n  reason: +(.*)", done.out, re.M)[1]
        self.assertRegex(reason("acme"), r"^asleep: press \d+ to wake it")
        self.assertRegex(reason("beta"), r"^asleep: press \d+ to wake it")    # its plan done
        self.assertRegex(reason("gamma"), r"^session closed by the owner")


if __name__ == "__main__":
    unittest.main()
