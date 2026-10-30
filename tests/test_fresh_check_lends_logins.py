"""ak's fresh-install check holds only copies of logins that cannot renew, and writes nothing back.

Through step c's own code and cleanup_logs, from the caller HOME of fixture logins, Grok's
lapsed, and faked harness programs of tests/test_checks_lend_logins_that_cannot_renew.py.
"""

import subprocess
import tarfile
import unittest

from test_checks_lend_logins_that_cannot_renew import REPO, LentLogins

FRESH = (REPO / "tests/e2e-fresh.sh").read_text()
STEP_C = FRESH[FRESH.index('  LENT=" "'):FRESH.index("  # Whether each harness can log in")]
CLEANUP = FRESH[FRESH.index("cleanup_logs() {"):FRESH.index("\ncleanup() {")]


class FreshCheckLendsLogins(LentLogins):
    def setUp(self):
        super().setUp()
        self.work = self.root / "e2e work"     # a space in the new HOME's path, as a caller's may hold
        self.home = self.work / "home"
        self.home.mkdir(parents=True)

    def gate(self, script, **env):
        result = subprocess.run(["/bin/bash", "-c", '. "$REPO/tests/acceptance.sh"\nsay() { :; }\n' + script],
                                env={**self.env, "INVHOME": str(self.caller), "WORK": str(self.work),
                                     "UH": str(self.home), **env},
                                text=True, capture_output=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def step_c(self):
        """Step c's lending into the new HOME: its LENT, SEATPAIR, bad and BORROWED."""
        return self.gate('bad="" BORROWED="" HOSTBIN=" "\n' + STEP_C
                         + 'printf "%s\\n" "$LENT" "$SEATPAIR" "$bad" "$BORROWED"\n').split("\n")[-5:-1]

    def archived(self, borrowed):
        """A failed gate's cleanup: the archive's files that hold a fixture value, and the caller's
        logins as they are afterwards."""
        self.gate(CLEANUP + "\ncleanup_logs 1\n", BORROWED=borrowed)
        self.assertFalse(self.work.exists())
        with tarfile.open(self.caller / ".agentkit/tmp/e2e-fresh-failure.tar.gz") as saved:
            leaked = [member.name for member in saved.getmembers()
                      if member.isfile() and b"fixture" in saved.extractfile(member).read()]
        self.assertEqual({path: path.read_bytes() for path in self.before}, self.before)
        return leaked

    def test_the_new_home_holds_copies_that_cannot_renew_and_the_archive_none(self):
        webhook = self.caller / ".agentkit/secrets/discord_webhook"
        webhook.parent.mkdir(parents=True)
        webhook.write_text("fixture-webhook")
        lent, seat, bad, borrowed = self.step_c()
        self.assertEqual((lent, seat, bad), (" antigravity claude codex muse opencode ", "1", ""))
        self.assert_lent_copies(self.home)
        self.assertEqual(self.archived(borrowed), [])

    def test_a_lend_failing_partway_leaves_none_lent_or_archived(self):
        taken = self.home / ".config/opencode/opencode.json"   # OpenCode's, lent last
        taken.parent.mkdir(parents=True)
        taken.write_text("{}")
        lent, seat, bad, borrowed = self.step_c()
        self.assertEqual((lent, seat, bad), (" ", "", "; this host's logins could not be lent"))
        self.assertEqual([path for path in self.home.rglob("*") if path.is_file()], [taken])
        self.assertEqual(self.archived(borrowed), [])


if __name__ == "__main__":
    unittest.main()
