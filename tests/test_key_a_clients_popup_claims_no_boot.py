"""A client's popup claims no boot: on a machine whose server record (`state/server`) names a
home, `ak --overlay` with a seat that owes work and a watch.json holding another boot's id exits
1 naming that home, opens no session, and leaves that file's `boot_id` and `boot_resume` as they
were.  `Ctrl-b m`, whose popup tmux takes down as its command ends, leaves that home's whole name
on a terminal forty columns wide; a popup tmux hands no terminal's name leaves its line on the
only terminal attached, and on neither of two.

A standby's ~/.agentkit is a copy of its home's, the home's boot id and seat records among them,
so to the boot resume every seat there looks cut off by a reboot: on 22 Nov 2026 a standby's menu
resumed all 21 of its home's sessions a second time.  Black-box: the program `AK_BIN` names runs
from outside through tests/fixtures/akbin.py with its clock and boot id given (`AK_NOW`), and the
seat is only its record (tests/fixtures/akseat.py); the key is pressed in a phone's terminal
(tests/fixtures/akterm.py), where the popup covers the seat's bar too, on a seat `ak orch` opened
in it before the record was written, a fake `claude` in it, which gives the server ak's
`Ctrl-b m`.  The popup handed no name is `display-popup`'s own, as a tmux before 3.3 opens the
key's, and tmux's message log (`show-messages`) says which terminals have its line.
"""

import json
from pathlib import Path
import shlex
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import AK, REAL_TMUX, SOCKET, Home
from fixtures.akseat import Seat
from fixtures.akterm import Terminal

# the home a seat's terminal is told of: a name a line saying it last would cut at forty columns
SERVER = "acme-standby-box"


def on_a_seat(home, **terminal):
    """A terminal on a seat of `home`, which is made a client only then: a client opens none."""
    home.fake("claude", "#!/bin/sh\nexec sleep 600\n")
    seat = Terminal(home, "orch", "acme", "--model", "opus", "--workers", "opus", **terminal)
    seat.wait("Ctrl-b m")                   # its bar is up: the seat has the keys
    home.write(".agentkit/state/server", SERVER + "\n")
    return seat


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

    def test_ctrl_b_m_leaves_that_homes_whole_name_at_forty_columns(self):
        with Home() as home:
            seat = on_a_seat(home, size=(40, 20))
            seat.keys("C-b", "m")
            # the bar's key line is back in view: the popup is down
            seat.wait(lambda shown: SERVER in shown and "Ctrl-b m" in shown)

    def test_a_popup_handed_no_terminals_name_leaves_its_line_on_the_only_one_attached(self):
        with Home() as home:
            on_a_seat(home)
            first, = home.tmux("list-clients", "-F", "#{client_name}").out.split()

            def left_on():
                """The terminals that have the line of a popup opened on the first."""
                popup = home.tmux("display-popup", "-E", "-c", first, "-t", "=acme:",
                                  shlex.join([AK, "--overlay"]))
                # back once the popup is down, with its command's code and no word of tmux's own
                self.assertEqual((popup.code, popup.err), (1, ""))
                rows = (row.partition(" message: ")
                        for row in home.tmux("show-messages").out.splitlines())
                return [terminal.split()[-1] for terminal, _, line in rows if SERVER in line]

            self.assertEqual(left_on(), [first])
            Terminal(home, "-L", SOCKET, "attach-session", "-t", "=acme:",
                     program=REAL_TMUX).wait("Ctrl-b m")
            # tmux's own pick is the terminal it heard from last, the second: no line is left
            self.assertEqual(left_on(), [first])


if __name__ == "__main__":
    unittest.main()
