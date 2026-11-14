"""An open menu looks for news as often as a look is cheap, and never less often than `STIR`.

The watcher waited a second between looks, so a seat's new word was drawn up to a second after
its record said it.  `Live._watch` runs here on a fake clock: each look takes what the test
says, and the wait before the next is that many `LOOKS` of it, `STIR` at most.
"""

import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from fixtures.clock import Clock
from agentkit import config, menu


class LooksAsOftenAsALookIsCheap(Sandbox):
    def test_the_wait_follows_what_the_last_look_cost(self):
        live = menu.Live(config.load())
        self.addCleanup(live.close)
        now, waits, costs = [0.0], [], [0.002, 0.5, 0.01]

        def wait(timeout):
            waits.append(timeout)
            if len(waits) > len(costs):
                live.done.set()

        def recorded():
            now[0] += costs[len(waits) - 1]
            return live.seen

        clock = Clock(None)
        clock.monotonic = lambda: now[0]
        with patch.object(menu, "time", clock), patch.object(live.asked, "wait", wait), \
                patch.object(live, "recorded", recorded):
            live._watch()
        self.assertEqual(waits[0], menu.STIR)
        for waited, want in zip(waits[1:], (menu.LOOKS * 0.002, menu.STIR, menu.LOOKS * 0.01)):
            self.assertAlmostEqual(waited, want)


if __name__ == "__main__":
    unittest.main()
