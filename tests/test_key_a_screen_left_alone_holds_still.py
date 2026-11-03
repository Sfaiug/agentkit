"""The main screen's rule holds still while usage is asked: it draws from the cache, so it waits on
nothing, and the owner's 14 Oct screen moves only while a model works, once when a thing changes, or
under the pointer.  Black-box: what a menu writes to the rule's row from its start until the answer."""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import SERVER, Terminal


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class LeftAlone(unittest.TestCase):
    # Something moves only while a model works on it, once when it changes, or under the pointer.
    # [2, 14, 19, 23, 26 Oct 2026]
    def test_the_rule_holds_still_while_usage_is_asked(self):
        with Home() as home:
            Seat(home, "s-one")
            menu, raw = Terminal(home), home.root / "raw"
            raw.touch()
            home.tmux("pipe-pane", "-t", menu.pane, f"cat >{raw}", server=SERVER)
            answer = home.path / ".agentkit" / "state" / "usage.json"
            menu.wait(lambda _: answer.exists())
            self.assertNotIn(b"\x1b[2;2H", raw.read_bytes())


if __name__ == "__main__":
    unittest.main()
