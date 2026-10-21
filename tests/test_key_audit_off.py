"""With `[audit] on = false` the tick writes no weekly audit and opens no seat for it.

The audit seat is the one seat ak opens without a person, so switching it off must leave the
tick opening nothing at all: no board under state/audit/, no state/audit.json, no record of an
`audit` seat and no tmux session.  An owner who turned it off and still found a seat, or the
week's board, would have no way to stop ak improving itself on its own.

Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py; its
config is the one tests/fixtures/akconfig.py writes, with the audit off.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, Home

# The tick asks the public boards: a proxy nobody answers keeps it off the network, as offline.
OFFLINE = {name: "http://127.0.0.1:9"
           for name in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY")}


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class AuditOff(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        akconfig.write(cls.home, {"alpha": "claude", "beta": "claude"})
        cls.state = cls.home.path / ".agentkit" / "state"
        cls.done = cls.home.ak("watch", env=OFFLINE)

    def test_the_tick_with_the_audit_off_passes(self):
        self.assertEqual(akconfig.read(self.home)["audit"], {"on": False})
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)

    def test_no_board_and_no_line_are_written(self):
        self.assertFalse((self.state / "audit.json").exists())
        self.assertFalse((self.state / "audit").exists())

    def test_no_audit_seat_is_recorded_or_opened(self):
        self.assertFalse((self.state / "session-audit.json").exists())
        sessions = self.home.tmux("list-sessions", "-F", "#{session_name}").out.split()
        self.assertEqual(sessions, [])


if __name__ == "__main__":
    unittest.main()
