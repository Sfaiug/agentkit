"""A client's popup claims no boot: on a machine whose server record (`state/server`) names a
home, `ak --overlay` with a seat that owes work and a watch.json holding another boot's id exits
1 naming that home, opens no session, and leaves that file's `boot_id` and `boot_resume` as they
were.  `Ctrl-b m`, whose popup tmux takes down as its command ends, leaves that home named on
the terminal.

A standby's ~/.agentkit is a copy of its home's, the home's boot id and seat records among them,
so to the boot resume every seat there looks cut off by a reboot: on 22 Nov 2026 a standby's menu
resumed all 21 of its home's sessions a second time.  Black-box: the program `AK_BIN` names runs
from outside through tests/fixtures/akbin.py with its clock and boot id given (`AK_NOW`), and the
seat is only its record (tests/fixtures/akseat.py); the key is pressed in a phone's terminal
(tests/fixtures/akterm.py), where the popup covers the seat's bar too, on a seat `ak orch` opened
in it before the record was written, a fake `claude` in it, which gives the server ak's
`Ctrl-b m`.
"""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import Terminal


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class AClientsPopup(unittest.TestCase):
    def test_it_opens_no_session_and_keeps_the_homes_claim(self):
        with Home() as home:
            akconfig.write(home, ["opus"])
            Seat(home, "acme", alive=False, planned=True)     # owes work, and tmux lost it
            watch = home.write(".agentkit/state/watch.json", {"boot_id": "the home's"})
            home.write(".agentkit/state/server", "acme-box\n")
            done = home.ak("--overlay", input="", env={"AK_NOW": "100 100 this-boot"})
            self.assertEqual(done.code, 1, done.out + done.err)
            self.assertIn("acme-box", done.out)
            self.assertEqual(home.tmux("list-sessions", "-F", "#{session_name}").out.split(), [])
            kept = json.loads(watch.read_text())
            self.assertEqual((kept.get("boot_id"), kept.get("boot_resume")), ("the home's", None))

    def test_ctrl_b_m_leaves_that_home_named_once_its_popup_is_down(self):
        with Home() as home:
            home.fake("claude", "#!/bin/sh\nexec sleep 600\n")
            seat = Terminal(home, "orch", "acme", "--model", "opus", "--workers", "opus",
                            size=(50, 20))
            seat.wait("Ctrl-b m")               # its bar is up: the seat has the keys
            home.write(".agentkit/state/server", "acme-box\n")
            seat.keys("C-b", "m")
            # the bar's key line is back in view: the popup is down
            seat.wait(lambda shown: "acme-box" in shown and "Ctrl-b m" in shown)


if __name__ == "__main__":
    unittest.main()
