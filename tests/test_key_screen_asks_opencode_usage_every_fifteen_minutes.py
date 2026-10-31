"""An open screen asks OpenCode for its usage at most once every fifteen minutes.

The screen refreshes every provider's usage each minute, and each of OpenCode's answers boots
servers of its own: some six seconds of CPU, a tenth of a core while a screen stayed open.
Black-box: `AK_BIN` runs in a person's terminal (tests/fixtures/akterm.py), its one model on
OpenCode, whose `opencode` is the Home's fake that logs each call (tests/fixtures/akbin.py).
"""

from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import Home
from fixtures.akterm import Terminal

BOUND = 120       # the screen opens and asks every provider, on a loaded host
SETTLE = 30       # the first ask's calls are all in, its login check's among them
PAST = 150        # two of the screen's minutes: a harness it asks each minute is asked again


class ScreenAsksOpenCodeRarely(unittest.TestCase):
    def test_a_screen_open_three_minutes_asks_opencode_once(self):
        with Home() as home:
            akconfig.write(home, {"flash": {"harness": "opencode", "model": "opencode/flash-free",
                                            "provider": "opencode"}})
            Terminal(home)
            asks = lambda: sum(call[:2] == ["auth", "list"] for call in home.calls("opencode"))
            deadline = time.monotonic() + BOUND
            while not asks():
                self.assertLess(time.monotonic(), deadline, "the screen never asked OpenCode")
                time.sleep(1)
            time.sleep(SETTLE)
            first = asks()
            time.sleep(PAST)
            self.assertEqual(asks(), first)


if __name__ == "__main__":
    unittest.main()
