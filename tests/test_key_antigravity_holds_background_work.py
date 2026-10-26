"""An Antigravity seat holds the background work its screen shows running, as a Claude seat holds
what its Stop lists.

agy runs no hooks, but under its composer it lists each command it moved to the background
(`● [12:08:46] sleep 45 running`).  A seat showing one stays on an account with usage left until
it is spent, and the line it comes back on names a `shell`; once the list is gone it holds
nothing, and a screen that cannot show the list (too narrow) leaves what was last read.
Black-box: the program `AK_BIN` names runs `ak` from outside through tests/fixtures/akbin.py,
beside a seat of tests/fixtures/akseat.py showing real agy 1.3.5 captures, on fake harnesses of
fakeadapter.py and the usage readings the test writes.
"""

import json
import os
import shlex
import socket
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akseat import PANE, Seat

PROXIES = ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")
TWO = {"accounts": ["default", "second"]}
CONVERSATION = "0b9c6f4e-1d2a-4c3b-8e5f-6a7b8c9d0e1f"
TRAY = "antigravity-background-pane.txt"            # a `sleep 45` running under the composer
EMPTY = "antigravity-bracketed-label-pane.txt"      # the same seat at its prompt, no list
NARROW = "antigravity-narrow-pane.txt"              # at 40 columns: the footer names no list
BOOT_FILE = Path("/proc/sys/kernel/random/boot_id")


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class AntigravityHoldsBackgroundWork(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        with socket.socket() as probe:     # a port nobody listens on: the tick reaches no board
            probe.bind(("127.0.0.1", 0))
            home.env.update(dict.fromkeys(PROXIES, f"http://127.0.0.1:{probe.getsockname()[1]}"),
                            GIT_ALLOW_PROTOCOL="file")
        akconfig.write(home, ["gemini"], providers={"google": TWO})
        self.fake = fakeadapter.install(home, antigravity="pass")["antigravity"]

    def seat(self, screen, planned=False):
        """A seat on the first account showing `screen`, reopened as itself."""
        seat = Seat(self.home, "acme", model="gemini", screen=screen, planned=planned,
                    record={"conversation": CONVERSATION, "account": "default"})
        self.fake.answer("interactive", shlex.join(
            [sys.executable, str(PANE), str(seat.screen_file), str(seat.typed_file)]))
        return seat

    def account(self):
        return json.loads((self.home.path / ".agentkit/state/session-acme.json")
                          .read_text()).get("account")

    def lines(self):
        """The first prompt each relaunch handed the harness."""
        return [call["env"].get("AGENTKIT_FIRST_PROMPT") or None
                for call in self.fake.calls("interactive")]

    def tick(self, seat, used):
        """One tick with the first account `used`% into its 5h window and the other at 10%, the
        seat's terminal untouched for ten minutes: the account it is on after."""
        now = time.time()

        def reading(used):
            return {"provider": "google", "resets": 0, "meters": [
                {"name": "session", "used": used, "window_secs": 18000, "resets_at": now + 10800},
                {"name": "weekly_all", "used": 30, "window_secs": 604800,
                 "resets_at": now + 3 * 86400}]}
        self.home.write(".agentkit/state/usage.json", {
            "fetched_at": now, "reset_checked_at": now, "providers": {"google": {
                **reading(used), "accounts": {"default": reading(used), "second": reading(10)}}}})
        tty = self.home.tmux("display-message", "-p", "-t", seat.pane, "#{pane_tty}").out.strip()
        os.utime(tty, (now - 600, now - 600))
        done = self.home.ak("watch", boxed=True)
        self.assertEqual(done.code, 0, done.out + done.err)
        return self.account()

    def test_a_running_command_keeps_a_low_account(self):
        self.assertEqual(self.tick(self.seat(TRAY), 97), "default")
        self.assertEqual(self.lines(), [])

    def test_a_seat_showing_no_list_moves_off_a_low_account(self):
        self.assertEqual(self.tick(self.seat(EMPTY), 97), "second")
        self.assertEqual(self.lines(), [None])

    def test_a_spent_account_moves_it_and_the_line_names_a_shell(self):
        self.assertEqual(self.tick(self.seat(TRAY), 100), "second")
        line, = self.lines()
        self.assertIn("background work: shell", line)

    def test_once_the_list_is_gone_it_holds_nothing_and_a_narrow_screen_says_nothing(self):
        seat = self.seat(TRAY)
        self.assertEqual(self.tick(seat, 97), "default")
        seat.show(NARROW)
        self.assertEqual(self.tick(seat, 97), "default")
        seat.show(EMPTY)
        self.assertEqual(self.tick(seat, 97), "second")
        self.assertEqual(self.lines(), [None])

    @unittest.skipUnless(BOOT_FILE.is_file(), "no kernel boot id")
    def test_a_seat_whose_process_ended_showing_the_list_is_told_to_pick_up_a_shell(self):
        seat = self.seat(TRAY, planned=True)       # its open plan line brings it back
        looked = self.home.ak("orch", "list")
        self.assertEqual(looked.code, 0, looked.out + looked.err)
        # the owner's own session keeps ak's tmux server up once tmux has lost the seat's
        kept = self.home.tmux("-f", "/dev/null", "new-session", "-d", "-s", "notes", "sleep 600")
        self.assertEqual(kept.code, 0, kept.err)
        self.home.tmux("kill-session", "-t", f"={seat.name}")
        state = self.home.path / ".agentkit/state/watch.json"
        self.home.write(".agentkit/state/watch.json", {
            **(json.loads(state.read_text()) if state.is_file() else {}), "boot_id": "before"})
        done = self.home.ak("watch", boxed=True)
        self.assertEqual(done.code, 0, done.out + done.err)
        line, = self.lines()
        self.assertIn("background work: shell", line)


if __name__ == "__main__":
    unittest.main()
