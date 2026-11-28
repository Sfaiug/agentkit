"""Each machine's row on `config · machines` leads its value with two marks (`●`/`○` under UTF-8,
`*`/`.` under ASCII): `runs` on where `machines.work` holds `turns` and `tests` where it holds
`tests`, drawn with the glyphs and styles a machine's own page draws its two marks with, then the
rest of the chain with no work words at its end.  A stand-in that is not a listed machine has no
marks.  Space does nothing on a row, and Enter still opens a machine's page.

Black-box: AK_BIN under a terminal in a temporary HOME with invented machines and recorded
readings, the home's clocks from AK_NOW (`wall seconds-since-boot boot`).  No machine is asked
while drawing.
"""

from pathlib import Path
import re
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import Terminal

TOLD = "1789000000 50000 acme-boot-1"      # the home's clocks at the stand-in's request
LATER = "1789000180 50180 acme-boot-1"     # three minutes on, as the page is drawn
AT = 1789000000 - 60                       # the tick that last read each machine
ASCII = {"LANG": "C", "LC_ALL": "C", "NO_COLOR": "1"}
ANSI = re.compile(r"\x1b\[[0-9;]*m")
GLYPH_SGR = re.compile(r"((?:\x1b\[[0-9;]*m)+)([●○])")


def reading(system, cores, memory, free, load):
    """A machine's record: two checks a minute apart, both answered."""
    return {"checks": [[AT - 60, True], [AT, True]], "said": {
        "at": AT, "system": system, "processor": "arm64", "cores": cores,
        "memory_mb": memory * 1024, "free_mb": free * 1024, "load": load,
        "disk_free_mb": 102400, "battery": system == "macOS", "power": 1}}


def mark_styles(line):
    """The ANSI sequences immediately before each `●` or `○` on `line`, keyed by the glyph."""
    return {glyph: sgr for sgr, glyph in GLYPH_SGR.findall(line)}


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class MachinesPageShowsTwoMarks(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        fakeadapter.install(home, claude="pass")
        self.config = akconfig.write(
            home, ["fable"],
            extra='[machines.acme-linux]\nwork = ["turns"]\n'
                  '[machines.acme-mac]\nwork = ["tests"]\n'
                  '[machines.acme-idle]\nwork = []\n')
        home.write(".agentkit/state/machines.json", {
            "this one": reading("Linux", 18, 47, 35, 5.58),
            "acme-linux": reading("Linux", 8, 16, 12, 2.0),
            "acme-mac": reading("macOS", 4, 8, 6, 1.0)})
        home.env["AK_NOW"] = TOLD
        began = home.ak("standby", "--began")
        self.assertEqual(began.code, 0, began.out + began.err)
        done = home.ak("standby", "--copied", "acme-vm", *began.out.split(), "yes")
        self.assertEqual(done.code, 0, done.out + done.err)

    def open_page(self, *, env=None):
        """Open `config · machines` and wait until all rows are drawn."""
        self.term = Terminal(self.home, "attach", "--overlay", size=(120, 40),
                             env={"AK_NOW": LATER, **(env or {"NO_COLOR": "1"})})
        self.term.wait("esc leave")
        self.term.keys("c")
        self.term.wait(lambda screen: "agentkit · config " in screen
                       and "Machines" in screen and "esc back" in screen)
        self.term.keys(*(["Down"] * 5))       # one model, then the fifth config row
        self.term.wait(lambda screen: "› Machines" in screen or "> Machines" in screen)
        self.term.keys("Enter")
        return self.term.wait(lambda screen: "config · machines" in screen
                              and "+ add a machine" in screen and "esc back" in screen
                              and "acme-idle" in screen)

    def leave(self, depth=3):
        self.term.keys(*(["Escape"] * depth))
        self.assertEqual(self.term.exit_code(), 0)
        self.assertEqual(self.home.calls("ssh"), [])

    def row_of(self, screen, name):
        return next(line for line in screen.splitlines()
                    if ANSI.sub("", line).lstrip("›> ").startswith(f"{name} "))

    def test_each_machine_leads_with_its_two_marks_aligned_and_no_work_words_at_the_end(self):
        before = self.config.read_bytes()
        screen = self.open_page()
        want = {
            "this one": "● runs  ● tests  home · 18 cores · 47 GB · 31% busy · 12 of 47 GB used",
            "acme-linux": "● runs  ○ tests  new · 8 cores · 16 GB · 25% busy · 4 of 16 GB used",
            "acme-mac": "○ runs  ● tests  sometimes on · 4 cores · 8 GB · 25% busy · 2 of 8 GB used",
            "acme-idle": "○ runs  ○ tests  new · never answered",
        }
        rows = {name: self.row_of(screen, name) for name in want}
        for name, value in want.items():
            self.assertTrue(rows[name].rstrip().endswith(value), (name, rows[name]))
        # The marks and the chain after them line up down the rows.
        self.assertEqual(len({row.index(value) for row, value in zip(rows.values(), want.values())}), 1,
                         rows)
        # No row ends in the old work words.
        for name, row in rows.items():
            for old in ("sessions", "builds", "reviews", "no work", "· tests"):
                self.assertNotIn(old, row, (name, row))
        # A stand-in that is not a listed machine has no marks and is as today.
        stand_in = self.row_of(screen, "acme-vm")
        self.assertTrue(stand_in.rstrip().endswith(
            "stand-in · copy 3m old · takes over when this one stops"), stand_in)
        for mark in ("●", "○", "runs", "tests"):
            self.assertNotIn(mark, stand_in, stand_in)
        # Space does nothing new and the key line names no mark; Enter opens the machine's page.
        self.term.keys("Down")
        on_linux = self.term.wait("› acme-linux")
        keys = next(line for line in reversed(on_linux.splitlines()) if line.strip())
        self.assertIn("⏎ open", keys)
        self.assertNotIn("␣", keys)
        self.term.keys("Space")
        self.term.keys("Enter")
        page = self.term.wait(lambda s: "config · machines · acme-linux" in s
                              and "builds and reviews ● on" in " ".join(s.split())
                              and "tests ○ off" in " ".join(s.split()))
        self.assertIn("builds and reviews", page)
        self.assertEqual(self.config.read_bytes(), before)
        self.leave(4)

    def test_marks_match_the_machine_page_styles_and_ascii_fallback(self):
        # Under colour, the on/off marks use the same styles as a machine's own page.
        self.open_page(env={"TERM": "xterm-256color"})
        # A key ends the page's fade-in on its resting colours; `this one` stays highlighted,
        # so `acme-linux` is drawn unhighlighted with both ● and ○.
        self.term.keys("Up")
        self.term.wait(lambda _: set(mark_styles(self.row_of(
            self.term.screen(colours=True), "acme-linux"))) == {"●", "○"})
        list_styles = mark_styles(self.row_of(self.term.screen(colours=True), "acme-linux"))
        self.assertNotEqual(list_styles["●"], list_styles["○"])
        self.term.keys("Down", "Enter")
        self.term.wait(lambda s: "config · machines · acme-linux" in s and "builds and reviews" in s)
        # Settle the fade-in with `Up` on row 0 (`builds and reviews`), so `tests` is unhighlighted.
        self.term.keys("Up")
        self.term.wait(lambda _: "○" in mark_styles(self.row_of(
            self.term.screen(colours=True), "tests")))
        off_style = mark_styles(self.row_of(self.term.screen(colours=True), "tests"))["○"]
        self.term.keys("Down")
        self.term.wait("› tests")
        # Now `builds and reviews` is unhighlighted (●).
        on_style = mark_styles(self.row_of(self.term.screen(colours=True), "builds and reviews"))["●"]
        self.assertEqual(list_styles["●"], on_style)
        self.assertEqual(list_styles["○"], off_style)
        self.leave(4)

        # Without UTF-8, the glyphs match the machine page's `*` and `.`.
        ascii_screen = self.open_page(env=ASCII)
        self.assertIn("* runs  * tests  home · 18 cores · 47 GB · 31% busy · 12 of 47 GB used",
                      self.row_of(ascii_screen, "this one"))
        self.assertIn("* runs  . tests  new · 8 cores · 16 GB · 25% busy · 4 of 16 GB used",
                      self.row_of(ascii_screen, "acme-linux"))
        self.assertIn(". runs  * tests  sometimes on · 4 cores · 8 GB · 25% busy · 2 of 8 GB used",
                      self.row_of(ascii_screen, "acme-mac"))
        self.assertIn(". runs  . tests  new · never answered",
                      self.row_of(ascii_screen, "acme-idle"))
        self.leave()

    def test_narrow_screen_with_long_name_keeps_both_marks_in_two_aligned_columns(self):
        host = "acme@acme-mini.example"
        akconfig.write(self.home, ["fable"], extra=f'[machines."{host}"]\nwork = ["tests"]\n')
        self.term = Terminal(self.home, "attach", "--overlay", size=(40, 40),
                             env={"NO_COLOR": "1", "AK_NOW": LATER})
        self.term.wait("esc leave")
        self.term.keys("c")
        self.term.wait(lambda screen: "agentkit · config " in screen and "Machines" in screen)
        self.term.keys(*(["Down"] * 5))
        self.term.wait("› Machines")
        self.term.keys("Enter")
        screen = self.term.wait(lambda s: "config · machines" in s and host in s
                                and "+ add a machine" in s and "esc back" in s)
        self.assertTrue(all(len(line) <= 40 for line in screen.splitlines()), screen)
        columns = [(runs.start(), tests.start())
                   for line in screen.splitlines()
                   if (runs := re.search(r"[●○] runs\b", line))
                   and (tests := re.search(r"[●○] tests\b", line))]
        self.assertEqual(len(columns), 2, screen)
        self.assertEqual(len(set(columns)), 1, screen)
        self.leave()


if __name__ == "__main__":
    unittest.main()
