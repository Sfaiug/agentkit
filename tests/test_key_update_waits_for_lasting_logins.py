"""The tick starts agentkit's tests/live.sh only once the logins it lends will outlast it.

A live check borrows copies of this host's logins that nothing renews, and everything needing one
fails once it lapses.  So while the first login lent lapses within the check's margin -- its
two-hour cap while no check has passed -- the tick holds the check, says so once, naming the
harness and when its login lapses, and starts it on the first tick that login would last.
Black-box: tests/fixtures/akinstall.py copies the program `AK_BIN` names into HOME/agentkit,
whose origin's main is one commit ahead with a tests/live.sh that passes, and each tick runs that
copy through tests/fixtures/akbin.py; the Home's only login is Claude's, which no renewal moves.
This test fails against `/bin/false`.
"""

import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import Home
from fixtures.akinstall import Install


class WaitsForLastingLogins(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        home.fake("security", "#!/bin/sh\nexit 1\n")    # no Keychain: the login is the file
        akconfig.write(home, ["opus"])
        cls.install = Install(home)
        (cls.install.seed / "tests").mkdir()
        (cls.install.seed / "tests" / "live.sh").write_text("#!/bin/sh\nexit 0\n")
        cls.tip = cls.install.advance()
        cls.soon = cls.login(10 * 60)
        cls.held = [cls.tick(), cls.tick()]
        cls.login(8 * 60 * 60)
        cls.started = cls.tick()
        checks = cls.home.path / ".agentkit" / "state" / "live-checks"
        cls.checks = sorted(checks.glob(f"{cls.tip}-*"))
        until = time.monotonic() + 120
        while cls.checks and not (cls.checks[0] / "exit").exists() and time.monotonic() < until:
            time.sleep(0.1)

    @classmethod
    def login(cls, lasts):
        """Claude's login, lapsing `lasts` seconds from now with no refresh token; when."""
        ends = int(time.time() + lasts)
        cls.home.write(".claude/.credentials.json", {"claudeAiOauth": {
            "accessToken": "acme-seat", "expiresAt": ends * 1000, "subscriptionType": "max"}})
        return ends

    @classmethod
    def tick(cls):
        """One `ak watch` of the live copy: its exit code and what it said of tests/live.sh."""
        done = cls.home.run(cls.install.ak, "watch")
        return done.code, [line for line in done.out.splitlines() if "tests/live.sh" in line]

    def test_a_login_lapsing_within_the_margin_holds_the_check_and_says_so_once(self):
        lapses = time.strftime("%Y-%m-%d %H:%M", time.gmtime(self.soon))
        self.assertEqual(self.held, [
            (0, [f"tests/live.sh waits: claude's login lapses at {lapses}, before it could end"]),
            (0, [])])

    def test_the_first_tick_the_login_lasts_starts_the_check(self):
        self.assertEqual(self.started, (0, [f"checking agentkit at {self.tip[:12]} with "
                                            "tests/live.sh before it goes live"]))
        self.assertEqual(len(self.checks), 1)
        self.assertEqual((self.checks[0] / "exit").read_text(), "0\n")


if __name__ == "__main__":
    unittest.main()
