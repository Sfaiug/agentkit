"""A smoke.sh share whose failed checks the kernel killed for memory ends as a killed piece.

A check the kernel killed for memory says nothing of the checkout, and the gate runs a piece that
died by SIGKILL while its cgroup's `oom_kill` count rose once more alone, blaming no test
(tests/test_key_memory_killed_piece_never_blamed.py).  smoke.sh catches its checks' deaths and
counts each a failed check, so it is smoke.sh that ends such a share with 137.  A failure of any
other kind beside one, even while the kernel killed some other process in the cgroup, keeps the
share's own red, as does a SIGKILL with no memory kill counted.  The suite does not run here: a
stand-in checkout holds smoke.sh's own lines before its shared setup, which choose and run the
share, acceptance.sh, and a stand-in share; its cgroup is the test's (`AK_CGROUP_ROOT`,
`AK_CGROUP_FILE`).
"""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests"))
import suite_shares

UNIT = "acme.slice/lander.service"
# Each of ACME_CHECKS passes, dies by SIGKILL or fails an assertion; ACME_KILL has the kernel
# kill in the share's cgroup for memory meanwhile.
SHARE = """. "$REPO/tests/acceptance.sh"
[ -z "${ACME_KILL:-}" ] || printf 'oom 1\\noom_kill %s\\n' $((ACME_KILLS + 1)) >"$ACME_EVENTS"
for check in $ACME_CHECKS; do
  case $check in
    passed) ok "$check" ;;
    killed) { sh -c 'kill -9 $$'; } 2>/dev/null || no "$check" ;;
    failed) test -f acme-result || no "$check" ;;
  esac
done
finish
"""


class SmokeChecksKilledForMemory(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-smoke-memory-kill-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / "tests").mkdir()
        smoke = (REPO / "tests/smoke.sh").read_text()
        (self.root / "tests/smoke.sh").write_text(
            smoke[:smoke.index(suite_shares.SETUP)] + suite_shares.SETUP + SHARE)
        for name in ("suite_shares.py", "acceptance.sh"):
            shutil.copy(REPO / "tests" / name, self.root / "tests" / name)
        (self.root / "agentkit").symlink_to(REPO / "agentkit")
        self.events = self.root / "cgroups" / UNIT / "memory.events"
        self.events.parent.mkdir(parents=True)
        (self.root / "cgroup").write_text(f"0::/{UNIT}\n")

    def share(self, checks, kill, kills=0):
        """smoke.sh's exit for a share of `checks`, the kernel killing in its cgroup for memory
        with `kill`, `kills` killed there before it began."""
        self.events.write_text(f"oom {kills}\noom_kill {kills}\n")
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(("AK_", "AGENTKIT_"))}
        env.update(AK_CGROUP_ROOT=str(self.root / "cgroups"), AK_CGROUP_FILE=str(self.root / "cgroup"),
                   WORK=str(self.root), ACME_EVENTS=str(self.events), ACME_CHECKS=checks,
                   ACME_KILL="1" if kill else "", ACME_KILLS=str(kills), PYTHONDONTWRITEBYTECODE="1")
        done = subprocess.run(["bash", str(self.root / "tests/smoke.sh")], cwd=self.root, env=env,
                              capture_output=True, text=True)
        self.assertEqual(done.stderr, "")
        return done.returncode

    def test_checks_killed_for_memory_end_the_share_killed(self):
        self.assertEqual(self.share("killed", kill=True), 137)
        self.assertEqual(self.share("passed killed killed", kill=True, kills=3), 137)

    def test_a_failure_of_any_other_kind_keeps_the_shares_red(self):
        # another process the kernel killed for memory does not make an assertion's red its own
        self.assertEqual(self.share("passed failed", kill=True), 1)
        self.assertEqual(self.share("killed failed", kill=True), 1)

    def test_a_sigkill_with_no_memory_kill_keeps_the_shares_red(self):
        self.assertEqual(self.share("killed", kill=False), 1)
        self.assertEqual(self.share("killed", kill=False, kills=3), 1)

    def test_a_green_share_beside_one_stays_green(self):
        self.assertEqual(self.share("passed", kill=True), 0)


if __name__ == "__main__":
    unittest.main()
