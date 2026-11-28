"""`c` lists no weekly audit, and a tick opens no audit seat unless config.toml turns it on.

The owner, 10 Nov 2026: "Remove the weekly audit feature for now. Dont delete it, but remove
it."  Over a config.toml with no `[audit]` table `c` has no row for it, `Done check` coming
right under `Discord`, and the tick a week after the last audit opens no seat; written
`[audit] on = true`, the same tick opens the `audit` seat as before, so nothing of it is gone.
Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, `c` in
a tmux terminal through tests/fixtures/akterm.py with a fake harness logged in, and a tick is
judged by the seat record it writes and the tmux sessions it leaves.
"""

from datetime import datetime, timezone
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import Terminal

WEEK = 7 * 86400
# The tick asks the public boards: a proxy nobody answers keeps it off the network, as offline.
OFFLINE = {name: "http://127.0.0.1:9"
           for name in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY")}


def week_of(stamp):
    year, week, _ = datetime.fromtimestamp(stamp, timezone.utc).isocalendar()
    return f"{year}-W{week:02d}"


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class WeeklyAuditOff(unittest.TestCase):
    def home(self, audit):
        """A Home over a config.toml saying `[audit] on = audit`, no table for None."""
        home = Home()
        self.addCleanup(home.close)
        akconfig.write(home, {"alpha": "claude", "beta": "claude"}, audit=audit)
        return home

    def ticked(self, audit):
        """The tmux sessions, and whether a record of the `audit` seat is kept, after a tick a
        week after the last audit, whose line was delivered then."""
        home = self.home(audit)
        last = time.time() - WEEK
        home.write(".agentkit/state/audit.json", {
            "week": week_of(last), "report": "", "line": f"ak's week {week_of(last)}",
            "typed": last, "delivered": last})
        done = home.ak("watch", env=OFFLINE)
        self.assertEqual(done.code, 0, done.out + done.err)
        sessions = home.tmux("list-sessions", "-F", "#{session_name}").out.split()
        return sessions, (home.path / ".agentkit/state/session-audit.json").is_file()

    def test_c_lists_done_check_right_under_discord_and_nothing_reads_audit(self):
        home = self.home(None)
        fakeadapter.install(home, claude="pass")
        term = Terminal(home, size=(100, 40), env={"NO_COLOR": "1"})
        term.wait("esc leave")
        term.keys("c")
        shown = [line.rstrip() for line in term.wait("r your runs").split("\n")]
        rows = [line.split()[0] for line in shown if line.startswith("  ") and line.strip()]
        self.assertEqual(rows[rows.index("Discord") + 1], "Done", shown)
        self.assertFalse([line for line in shown if "audit" in line.lower()], shown)

    def test_a_tick_a_week_after_the_last_audit_opens_no_seat(self):
        self.assertEqual(self.ticked(None), ([], False))

    def test_the_same_tick_over_audit_on_opens_the_seat(self):
        self.assertEqual(self.ticked(True), (["audit"], True))


if __name__ == "__main__":
    unittest.main()
