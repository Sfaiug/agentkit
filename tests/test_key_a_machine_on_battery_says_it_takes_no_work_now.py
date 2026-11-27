"""`config · machines` says of a listed machine that answers on battery that it takes no work now:
its row ends `on battery · no work until on power` in place of its work, as ak gives it none
until a check finds it on power, after its stand-in words where it is the stand-in too.  The same
machine on power, and one on battery that does not answer, show their work; its own page shows
its marks.

Black-box: AK_BIN runs under a terminal in a temporary HOME, with invented machines and recorded
readings, stamped by the real clock, the home's clocks for the stand-in from AK_NOW
(`wall seconds-since-boot boot`).  No machine is asked while drawing.
"""

from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import Terminal

MINUTE = 60
LISTED = ("acme-laptop", "acme-plugged", "acme-shut")
USED = "sometimes on · 4 cores · 8 GB · 25% busy · 2 of 8 GB used"
TOLD = "1789000000 50000 acme-boot-1"      # the home's clocks at the stand-in's request
LATER = "1789000180 50180 acme-boot-1"     # three minutes on, as the page is drawn


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class AMachineOnBatterySaysItTakesNoWorkNow(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        fakeadapter.install(self.home, claude="pass")
        akconfig.write(self.home, ["fable"],
                       extra="".join(f"[machines.{name}]\n" for name in LISTED))
        at = time.time() - MINUTE

        def laptop(name, power, answering=True):
            return {"checks": [[at - MINUTE, True], [at, answering]], "said": {
                "at": at - MINUTE, "name": name, "system": "Linux", "processor": "arm64",
                "cores": 4, "memory_mb": 8192, "free_mb": 6144, "load": 1, "disk_free_mb": 102400,
                "battery": 1, "power": power}}
        self.home.write(".agentkit/state/machines.json", {
            "acme-laptop": laptop("acme-laptop", 0), "acme-plugged": laptop("acme-plugged", 1),
            "acme-shut": laptop("acme-shut", 0, answering=False)})

    def rows(self, **env):
        """Each listed machine's row, its words one space apart: from its name to the next row's,
        as a row longer than the layout folds under its value."""
        self.term = Terminal(self.home, "attach", "--overlay", size=(160, 40),
                             env={"NO_COLOR": "1", **env})
        self.term.wait("esc leave")
        self.term.keys("c")
        self.term.wait(lambda screen: "agentkit · config " in screen
                       and "Machines" in screen and "esc back" in screen)
        self.term.keys(*(["Down"] * 5))       # one model, then the fifth config row
        self.term.wait("› Machines")
        self.term.keys("Enter")
        # A new title can still have the preceding config body beneath it.
        screen = self.term.wait(lambda screen: "config · machines" in screen
                                and "+ add a machine" in screen and "esc back" in screen)
        text = " ".join(screen.replace("›", "").split())
        return {name: text[text.index(f"{name} "):text.index(f" {later}")]
                for name, later in zip(LISTED, [*LISTED[1:], "+ add a machine"])}

    def test_on_battery_it_says_no_work_until_on_power_and_on_power_its_work(self):
        rows = self.rows()
        self.assertEqual(rows["acme-laptop"],
                         f"acme-laptop {USED} · on battery · no work until on power")
        self.assertEqual(rows["acme-plugged"], f"acme-plugged {USED} · tests")
        self.assertRegex(rows["acme-shut"], r"^acme-shut sometimes on · 4 cores · 8 GB · "
                                             r"not answering since .* · tests$")
        # its own page holds its marks as ever
        self.term.keys("Down", "Enter")
        page = self.term.wait(lambda screen: "config · machines · acme-laptop" in screen
                              and "tests ● on" in " ".join(screen.split()))
        self.assertIn("builds and reviews ○ off", " ".join(page.split()))
        self.term.keys("Escape")
        self.leave()

    def test_on_battery_as_the_stand_in_its_row_ends_so_after_its_copy(self):
        self.home.env["AK_NOW"] = TOLD
        began = self.home.ak("standby", "--began")
        self.assertEqual(began.code, 0, began.out + began.err)
        done = self.home.ak("standby", "--copied", "acme-laptop", *began.out.split(), "yes")
        self.assertEqual(done.code, 0, done.out + done.err)
        rows = self.rows(AK_NOW=LATER)
        self.assertEqual(rows["acme-laptop"], f"acme-laptop {USED} · stand-in · copy 3m old · "
                                              "on battery · no work until on power")
        self.assertEqual(rows["acme-plugged"], f"acme-plugged {USED} · tests")
        self.leave()

    def leave(self):
        self.term.keys("Escape", "Escape", "Escape")
        self.assertEqual(self.term.exit_code(), 0)
        self.assertEqual(self.home.calls("ssh"), [])


if __name__ == "__main__":
    unittest.main()
