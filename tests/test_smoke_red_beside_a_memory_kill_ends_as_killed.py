"""A smoke.sh share left red while the kernel killed in its cgroup for memory ends as a killed piece.

A check the kernel killed for memory says nothing of the checkout, and the gate runs a piece that
died by SIGKILL while its cgroup's `oom_kill` count rose once more alone, blaming no test
(tests/test_key_memory_killed_piece_never_blamed.py).  smoke.sh catches its checks' deaths and
counts each a red check, so it is smoke.sh that ends such a share with 137.  A share red with no
kill during it, or green beside one, keeps its own code.  The suite does not run here: a stand-in
checkout holds smoke.sh's own lines before its shared setup, which choose and run the share, and
a stand-in share; its cgroup is the test's (`AK_CGROUP_ROOT`, `AK_CGROUP_FILE`).
"""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests"))
import suite_shares

UNIT = "acme.slice/lander.service"
# The share's checks end as ACME_RED says, the kernel killing one for memory with ACME_KILL.
SHARE = """[ -z "${ACME_KILL:-}" ] || printf 'oom 1\\noom_kill %s\\n' $((ACME_KILLS + 1)) >"$ACME_EVENTS"
(exit "$ACME_RED")
"""


class SmokeRedBesideAMemoryKill(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-smoke-memory-kill-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / "tests").mkdir()
        smoke = (REPO / "tests/smoke.sh").read_text()
        (self.root / "tests/smoke.sh").write_text(
            smoke[:smoke.index(suite_shares.SETUP)] + suite_shares.SETUP + SHARE)
        (self.root / "tests/suite_shares.py").write_text((REPO / "tests/suite_shares.py").read_text())
        (self.root / "agentkit").symlink_to(REPO / "agentkit")
        self.events = self.root / "cgroups" / UNIT / "memory.events"
        self.events.parent.mkdir(parents=True)
        (self.root / "cgroup").write_text(f"0::/{UNIT}\n")

    def share(self, red, kill, kills=0):
        """smoke.sh's exit for a share ending `red`, the kernel killing in it for memory with
        `kill`, `kills` killed in its cgroup before it began."""
        self.events.write_text(f"oom {kills}\noom_kill {kills}\n")
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(("AK_", "AGENTKIT_"))}
        env.update(AK_CGROUP_ROOT=str(self.root / "cgroups"), AK_CGROUP_FILE=str(self.root / "cgroup"),
                   ACME_EVENTS=str(self.events), ACME_RED=str(red), ACME_KILL="1" if kill else "",
                   ACME_KILLS=str(kills), PYTHONDONTWRITEBYTECODE="1")
        done = subprocess.run(["bash", str(self.root / "tests/smoke.sh")], cwd=self.root, env=env,
                              capture_output=True, text=True)
        self.assertEqual(done.stderr, "")
        return done.returncode

    def test_a_red_share_beside_a_memory_kill_ends_killed(self):
        self.assertEqual(self.share(1, kill=True), 137)
        self.assertEqual(self.share(2, kill=True, kills=3), 137)

    def test_a_red_share_without_one_keeps_its_code(self):
        self.assertEqual(self.share(1, kill=False), 1)
        self.assertEqual(self.share(2, kill=False, kills=3), 2)

    def test_a_green_share_beside_one_stays_green(self):
        self.assertEqual(self.share(0, kill=True), 0)


if __name__ == "__main__":
    unittest.main()
