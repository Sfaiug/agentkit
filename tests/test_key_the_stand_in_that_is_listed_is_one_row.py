"""`config · machines` gives a machine that is both listed and the stand-in one row: a stand-in
whose host name is the `name` a listed machine's last reading prints has no row of its own, and
that machine's row ends ` · stand-in · copy 3m old`, whatever its record says of taking over, and
opens its page on Enter.  Where two listed machines' readings print the name, the first in list
order takes it; the home's row never does, so a stand-in no listed machine's reading names keeps
its own row.

Black-box: AK_BIN under a terminal in a temporary HOME with invented machines and recorded
readings, the home's clocks from AK_NOW (`wall seconds-since-boot boot`).  No machine is asked
while drawing.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import Terminal

TOLD = "1789000000 50000 acme-boot-1"      # the home's clocks at the stand-in's request
LATER = "1789000180 50180 acme-boot-1"     # three minutes on, as the page is drawn
AT = 1789000000 - 60                       # the tick that last read each machine
COPY = "stand-in · copy 3m old"


def reading(name, system="Linux"):
    """A machine's record: one check, answered, its reading printing host `name`."""
    return {"checks": [[AT, True]], "said": {
        "at": AT, "name": name, "system": system, "processor": "arm64", "cores": 4,
        "memory_mb": 8192, "free_mb": 4096, "load": 1, "disk_free_mb": 102400,
        "battery": system == "macOS", "power": 1}}


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class TheStandInThatIsListedIsOneRow(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        fakeadapter.install(self.home, claude="pass")

    def machines(self, home, **listed):
        """config.toml listing `listed` in order, each recorded as printing its host name."""
        akconfig.write(self.home, ["fable"],
                       extra="".join(f"[machines.{name}]\n" for name in listed))
        self.home.write(".agentkit/state/machines.json", {
            "this one": reading(home), **{name: reading(*said) for name, said in listed.items()}})

    def told(self, host="acme-vm", takes="yes"):
        """`host`'s request, as its pass makes it, its record saying `takes`."""
        self.home.env["AK_NOW"] = TOLD
        began = self.home.ak("standby", "--began")
        self.assertEqual(began.code, 0, began.out + began.err)
        done = self.home.ak("standby", "--copied", host, *began.out.split(), takes)
        self.assertEqual(done.code, 0, done.out + done.err)

    def rows(self):
        """The page's rows, top to bottom, each its words one space apart, once `+ add a
        machine` is drawn."""
        self.term = Terminal(self.home, "attach", "--overlay", size=(160, 40),
                             env={"NO_COLOR": "1", "AK_NOW": LATER})
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
        lines = [" ".join(line.replace("›", "").split()) for line in screen.splitlines()]
        first = next(at for at, line in enumerate(lines) if line.startswith("this one "))
        last = next(at for at, line in enumerate(lines) if line.startswith("+ add a machine"))
        return lines[first:last + 1]

    def leave(self):
        self.term.keys("Escape", "Escape", "Escape")
        self.assertEqual(self.term.exit_code(), 0)
        self.assertEqual(self.home.calls("ssh"), [])

    def test_the_listed_machine_that_is_the_stand_in_says_so_on_its_row_and_opens_its_page(self):
        self.machines("acme-home", **{"acme-box": ("acme-vm",),
                                      "acme-laptop": ("acme-laptop", "macOS")})
        self.told()
        rows = self.rows()
        self.assertEqual(len(rows), 4, rows)
        self.assertTrue(rows[0].startswith("this one ● runs ● tests home"), rows)
        self.assertTrue(rows[1].startswith("acme-box ● runs ● tests new"), rows)
        self.assertTrue(rows[1].endswith(f"used · {COPY}"), rows)
        self.assertTrue(rows[2].startswith("acme-laptop ○ runs ● tests sometimes on"), rows)
        self.assertEqual(rows[3], "+ add a machine", rows)
        self.assertNotIn("stand-in", " ".join(rows[:1] + rows[2:]))
        self.term.keys("Down")
        self.term.wait("› acme-box")
        self.term.keys("Enter")
        self.term.wait(lambda screen: "config · machines · acme-box" in screen
                       and "builds and reviews" in screen)
        self.term.keys("Escape")
        self.term.wait("› acme-box")
        self.leave()

    def test_one_home_goes_back_to_says_only_its_copy_age_on_the_listed_row(self):
        self.machines("acme-home", **{"acme-box": ("acme-vm",)})
        self.told(takes="back")
        rows = self.rows()
        self.assertEqual(len(rows), 3, rows)
        self.assertTrue(rows[1].startswith("acme-box ● runs ● tests new")
                        and rows[1].endswith(f"used · {COPY}"), rows)
        self.leave()

    def test_of_two_listed_machines_that_print_its_name_the_first_takes_it(self):
        self.machines("acme-home", **{"acme-box": ("acme-vm",), "acme-twin": ("acme-vm",)})
        self.told()
        rows = self.rows()
        self.assertEqual(len(rows), 4, rows)
        self.assertTrue(rows[1].startswith("acme-box ● runs ● tests ") and rows[1].endswith(COPY), rows)
        self.assertTrue(rows[2].startswith("acme-twin ● runs ● tests ")
                        and rows[2].endswith("used"), rows)
        self.leave()

    def test_a_stand_in_no_listed_machine_is_keeps_its_own_row_whatever_the_home_prints(self):
        self.machines("acme-vm", **{"acme-box": ("acme-box",),
                                    "acme-laptop": ("acme-laptop", "macOS")})
        self.told()
        rows = self.rows()
        self.assertEqual(len(rows), 5, rows)
        self.assertNotIn("stand-in", " ".join(rows[:3]))
        self.assertEqual(rows[3], f"acme-vm {COPY} · takes over when this one stops", rows)
        self.assertEqual(rows[4], "+ add a machine", rows)
        self.leave()


if __name__ == "__main__":
    unittest.main()
