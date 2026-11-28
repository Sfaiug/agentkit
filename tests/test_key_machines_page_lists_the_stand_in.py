"""`config · machines` on a home lists, under the machines ak uses and above `+ add a machine`,
each machine a record there says copied this one, as `ak standby --copied` keeps it: its name,
then `stand-in · copy 3m old`, with `takes over when this one stops` where its record says so and
`home goes back to it once it is steady` where it says `back`, or `stand-in · its record cannot
be read`.  Enter on the row does nothing, ↓ reaches it below a machine ak uses of its name too,
and the highlight stays on whichever of the two it is on as rows come and go above it.  `c`'s
count stays the machines ak gives work, and a home no machine copies lists none.  Records
that cannot be listed are said to be so, on the page and by `ak standby`, which fails.

Black-box: AK_BIN under a terminal in a temporary HOME, the home's clocks from AK_NOW (`wall
seconds-since-boot boot`).  No machine is asked while drawing.
"""

import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import Terminal

RECORDS = ".agentkit/tmp/copies"      # the home's records of the machines that copy it
TOLD = "1789000000 50000 acme-boot-1"      # the home's clocks at a request
LATER = "1789000180 50180 acme-boot-1"     # three minutes on, as the page is drawn
TAKES_OVER = "takes over when this one stops"
GOES_BACK = "home goes back to it once it is steady"


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class TheMachinesPageListsTheStandIn(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        fakeadapter.install(self.home, claude="pass")
        self.config = akconfig.write(self.home, ["fable"],
                                     extra="[machines.acme-mac]\n")

    def told(self, takes, host="acme-vm"):
        """`host`'s request, as its pass makes it: the home's stamp, handed back."""
        self.home.env["AK_NOW"] = TOLD
        began = self.home.ak("standby", "--began")
        self.assertEqual(began.code, 0, began.out + began.err)
        done = self.home.ak("standby", "--copied", host, *began.out.split(), takes)
        self.assertEqual(done.code, 0, done.out + done.err)

    def page(self, *rows):
        """The page's words, one space between each, once it shows `rows`."""
        self.term = Terminal(self.home, "attach", "--overlay", size=(120, 40),
                             env={"NO_COLOR": "1", "AK_NOW": LATER})
        self.term.wait("esc leave")
        self.term.keys("c")
        self.config_screen = self.term.wait(lambda screen: "agentkit · config " in screen
                                            and "Machines" in screen and "esc back" in screen)
        self.term.keys(*(["Down"] * 5))       # one model, then the fifth config row
        self.term.wait("› Machines")
        self.term.keys("Enter")
        # A new title can still have the preceding config body beneath it.
        screen = self.term.wait(lambda screen: "config · machines" in screen
                                and "esc back" in screen
                                and all(row in " ".join(screen.split()) for row in (
                                    "this one ● runs ● tests home", "acme-mac", "+ add a machine", *rows)))
        return " ".join(screen.split())

    def leave(self):
        self.term.keys("Escape", "Escape", "Escape")
        self.assertEqual(self.term.exit_code(), 0)
        self.assertEqual(self.home.calls("ssh"), [])

    def test_one_that_takes_over_is_listed_under_the_machines_ak_uses_and_enter_does_nothing(self):
        self.told("yes")
        kept = [path.read_bytes() for path in (self.config, self.home.path / RECORDS / "acme-vm")]
        shown = self.page(f"acme-vm stand-in · copy 3m old · {TAKES_OVER}")
        self.assertNotIn(GOES_BACK, shown)
        self.assertLess(shown.index("acme-mac"), shown.index("acme-vm"))
        self.assertLess(shown.index("acme-vm"), shown.index("+ add a machine"))
        self.assertIn("Machines 2 machines Limits", " ".join(self.config_screen.split()))
        self.term.keys("Down", "Down")
        row = self.term.wait("› acme-vm")
        keys = next(line for line in reversed(row.splitlines()) if line.strip())
        self.assertNotIn("⏎", keys)
        self.assertNotIn("␣", keys)
        self.term.keys("Enter", "Down")
        self.assertIn("config · machines", self.term.wait("› + add a machine"))
        self.assertEqual(kept, [path.read_bytes() for path in (
            self.config, self.home.path / RECORDS / "acme-vm")])
        self.leave()

    def test_one_that_does_not_take_over_is_listed_without_it(self):
        self.told("no")
        shown = self.page("acme-vm stand-in · copy 3m old")
        self.assertNotIn("takes over", shown)
        self.leave()

    def test_home_goes_back_to_one_whose_record_says_back(self):
        self.told("back")
        self.page(f"acme-vm stand-in · copy 3m old · {TAKES_OVER} · {GOES_BACK}")
        self.leave()

    def test_one_whose_record_cannot_be_read_is_listed_as_such(self):
        self.home.write(f"{RECORDS}/acme-vm", "not a record\n")
        self.page("acme-vm stand-in · its record cannot be read")
        self.leave()

    def test_a_machine_ak_uses_that_also_stands_in_has_both_rows_each_reached_in_turn(self):
        akconfig.write(self.home, ["fable"], extra="[machines.acme-mac]\n[machines.acme-vm]\n")
        self.told("yes")
        self.page("acme-vm ○ runs ● tests new", f"acme-vm stand-in · copy 3m old · {TAKES_OVER}")
        self.term.keys("Down", "Down", "Down")
        self.term.wait(lambda screen: any("› acme-vm" in line and "stand-in" in line
                                          for line in screen.splitlines()))
        self.term.keys("Down")
        self.term.wait("› + add a machine")
        self.leave()

    def test_the_highlight_keeps_to_its_row_of_a_name_two_rows_share_as_others_come_and_go(self):
        def pointed(*words):
            return lambda screen: any(line.lstrip().startswith("› acme-vm")
                                      and all(word in line for word in words)
                                      for line in screen.splitlines())
        machines = "[machines.acme-mac]\n[machines.acme-laptop]\n[machines.acme-vm]\n"
        self.config = akconfig.write(self.home, ["fable"], extra=machines)
        self.told("yes")
        self.page("acme-laptop", "acme-vm ○ runs ● tests new", "acme-vm stand-in")
        self.term.keys("Down", "Down", "Down")
        self.term.wait(pointed("new"))
        self.config.write_text(self.config.read_text().replace("[machines.acme-laptop]\n", ""))
        self.term.keys("Space")       # a key the row does nothing with: the page is drawn again
        self.term.wait(lambda screen: "acme-laptop" not in screen and pointed("new")(screen))
        self.term.keys("Down")
        self.term.wait(pointed("stand-in"))
        self.told("no", "acme-aaa")
        self.term.keys("Space")
        self.term.wait(lambda screen: "acme-aaa" in screen and pointed("stand-in")(screen))
        self.term.keys("Enter", "Down")
        self.term.wait("› + add a machine")
        self.leave()

    @unittest.skipIf(os.geteuid() == 0, "root lists a folder whatever its mode")
    def test_records_that_cannot_be_listed_are_said_to_be_so(self):
        self.told("yes")
        records = self.home.path / RECORDS
        records.chmod(0o111)
        self.addCleanup(records.chmod, 0o755)
        said = self.home.ak("standby")
        self.assertNotEqual(said.code, 0, said.out)
        self.assertIn("cannot be read", said.err)
        self.page("the records of the machines that copy this one cannot be read")
        self.leave()

    def test_a_home_no_machine_copies_lists_none(self):
        shown = self.page()
        self.assertNotIn("acme-vm", shown)
        self.assertNotIn("stand-in", shown)
        self.leave()


if __name__ == "__main__":
    unittest.main()
