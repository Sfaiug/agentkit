"""A seat on a login its provider lists no more, moved on `c`, restarts on the first listed one
whose seat login passes, which its record then names as its account and its home; the removed
login is never asked.

On 12 Nov 2026 `a` on `c` moved no seat: each one still recorded on a subscription the owner had
removed, which signs it out, answered "claude: no OAuth credentials … run /login" with four other
subscriptions signed in.  Black-box: `AK_BIN`, as the popup over a seat on Opus 5.5 recorded on
`pro`, gone from the provider's `accounts`, its harness the fake whose `auth` says no for `pro`
alone; fails against `/bin/false`."""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import SERVER, Terminal
from test_key_seat_switches_in_place import KEYS, OFFLINE, key_line, rows

SEAT = "acme-fix"
# before the fake itself: the removed login's `auth` leaves a mark and answers as one signed out
SIGNED_OUT = """if [ "$1" = auth ] && [ "$AGENTKIT_ACCOUNT" = pro ]; then
  echo >>%s; echo "claude: no OAuth credentials in /home/acme/.claude-pro ... run /login"; exit 1
fi
"""


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ASwitchNeverAsksARemovedLogin(unittest.TestCase):
    def test_a_seat_on_a_removed_login_restarts_on_a_listed_one(self):
        home = Home()
        self.addCleanup(home.close)
        fake = fakeadapter.install(home, claude="pass")["claude"]
        asked = fake.dir / "asked-pro"
        fake.script.write_text(fake.script.read_text().replace(
            "#!/bin/sh\n", "#!/bin/sh\n" + SIGNED_OUT % asked, 1))
        akconfig.write(home, ["opus", "fable"], workers=["opus"],
                       providers={"anthropic": {"mode": "subscription", "accounts": ["max"]}})
        seat = Seat(home, SEAT, model="opus", record={"account": "pro", "home_account": "pro"})
        path = home.path / ".agentkit" / "state" / f"session-{SEAT}.json"
        term = Terminal(home, "attach", "--overlay", size=(100, 30),
                        env={"NO_COLOR": "1", "AGENTKIT_SESSION": SEAT, **OFFLINE})
        self.addCleanup(home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        term.wait("esc leave")
        term.keys("c")
        term.wait(lambda screen: key_line(screen) == KEYS and "› Opus 5.5" in screen)
        pid = home.tmux("display-message", "-p", "-t", seat.pane, "#{pane_pid}").out.strip()
        term.keys("Down", "Space")      # Fable 5.1's orchestrator mark
        term.wait(lambda screen: f"  Restart {SEAT} on Fable 5.1?" in rows(screen))
        term.keys("Down", "Enter")
        shown = rows(term.wait(lambda screen: key_line(screen) == KEYS
                               and "› Fable 5.1  [●]" in screen))
        record = json.loads(path.read_text())
        self.assertEqual((record["orchestrator"], record["account"], record["home_account"]),
                         ("fable", "max", "max"))
        self.assertNotEqual(home.tmux("display-message", "-p", "-t", seat.pane,
                                      "#{pane_pid}").out.strip(), pid)
        self.assertEqual([call["env"].get("AGENTKIT_ACCOUNT")
                          for call in fake.calls("interactive")], ["max"])
        under = shown.index(next(row for row in shown if row.startswith("  Version "))) + 1
        self.assertEqual([row for row in shown[under:shown.index(KEYS)] if row], [])
        self.assertFalse(asked.exists())


if __name__ == "__main__":
    unittest.main()
