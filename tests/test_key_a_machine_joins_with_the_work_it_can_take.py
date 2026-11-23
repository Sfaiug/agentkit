"""A machine with no work written takes what its last answer says it is: an always-on Linux
machine builds, reviews and tests; a laptop, a Mac or one not answered yet tests alone.

Black-box: AK_BIN runs under a terminal in a temporary HOME, with invented machines and their
recorded answers. `c` shows that work without writing it; a written mark still decides.
"""

from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import Terminal

MACHINES = ("acme-box", "acme-laptop", "acme-mac", "acme-new")


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class AMachineJoinsWithTheWorkItCanTake(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        fakeadapter.install(home, claude="pass")
        at = time.time()
        home.write(".agentkit/state/machines.json", {
            name: {"checks": [[at, True]], "said": {
                "at": at, "system": system, "processor": "arm64", "cores": 4,
                "memory_mb": 8192, "free_mb": 6144, "load": 1, "disk_free_mb": 102400,
                "battery": battery, "power": 1}}
            for name, system, battery in (("acme-box", "Linux", 0), ("acme-laptop", "Linux", 1),
                                          ("acme-mac", "macOS", 0))})

    def write_config(self, box=""):
        return akconfig.write(self.home, ["fable"], extra="".join(
            f"[machines.{name}]\n{box if name == 'acme-box' else ''}" for name in MACHINES)
            + "[google_cloud]\nactive = false\n")

    def page(self, *rows):
        self.term = Terminal(self.home, "attach", "--overlay", size=(120, 40),
                             env={"NO_COLOR": "1"})
        self.term.wait("esc leave")
        self.term.keys("c")
        self.term.wait(lambda screen: "agentkit · config " in screen and "Machines" in screen)
        self.term.keys(*(["Down"] * 5))       # one model, then the fifth config row
        self.term.wait("› Machines")
        self.term.keys("Enter")
        return self.term.wait(lambda screen: "config · machines" in screen and all(
            row in " ".join(screen.split()) for row in rows))

    def leave(self, depth=3):
        self.term.keys(*(["Escape"] * depth))
        self.assertEqual(self.term.exit_code(), 0)

    def test_each_unmarked_machine_takes_what_it_is_and_c_writes_none_of_it(self):
        config = self.write_config()
        before = config.read_bytes()
        used = "4 cores · 8 GB · 25% busy · 2 of 8 GB used"
        self.page(f"acme-box new · {used} · builds, reviews, tests",
                  f"acme-laptop sometimes on · {used} · tests",
                  f"acme-mac new · {used} · tests",
                  "acme-new new · never answered · tests")
        self.term.keys("Down", "Enter")
        own = self.term.wait("config · machines · acme-box")
        self.assertIn("builds and reviews ● on", " ".join(own.split()))
        self.leave(4)
        self.assertEqual(config.read_bytes(), before)

    def test_a_written_mark_keeps_a_linux_machine_at_tests(self):
        self.write_config('work = ["tests"]\n')
        self.page("acme-box new · 4 cores · 8 GB · 25% busy · 2 of 8 GB used · tests")
        self.leave()


if __name__ == "__main__":
    unittest.main()
