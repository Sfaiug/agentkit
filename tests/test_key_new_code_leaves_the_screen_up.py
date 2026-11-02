"""New code under an open screen leaves it up: the menu that restarts for it neither leaves nor
clears the alternate screen.  Black-box: what a menu writes as an install is stamped under it."""

import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import SERVER, Terminal


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class NewCode(unittest.TestCase):
    def test_a_restart_shows_no_blank_and_leaving_gives_the_terminal_back(self):
        with Home() as home:
            Seat(home, "s-one")
            home.write(".agentkit/state/installed-at", str(time.time() - 3600))
            menu, raw = Terminal(home), home.root / "raw"
            menu.wait("s-one")
            raw.touch()
            home.tmux("pipe-pane", "-t", menu.pane, f"cat >{raw}", server=SERVER)
            home.write(".agentkit/state/installed-at", str(time.time()))
            menu.wait(lambda _: b"s-one" in raw.read_bytes().partition(b"\x1b[?1003h")[2], bound=60)
            heard = raw.read_bytes()
            self.assertNotIn(b"\x1b[?1049", heard)
            self.assertNotIn(b"\x1b[2J", heard)
            menu.keys("Escape")
            self.assertEqual(menu.exit_code(), 0)
            menu.wait(lambda _: b"\x1b[?1049l" in raw.read_bytes())


if __name__ == "__main__":
    unittest.main()
