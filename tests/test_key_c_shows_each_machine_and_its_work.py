"""`c` shows every machine and its work, from the tick's records alone.

Black-box: AK_BIN runs under a terminal in a temporary HOME, with invented machines and
recorded readings, stamped by the real clock. No machine is asked while drawing. A home that
rented machines once keeps a `[google_cloud]` table and the files renting left in its state
folder: neither is read, so neither adds a row.
"""

import functools
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import Terminal

MINUTE, DAY = 60, 86400


def minute(at):
    """`at` as the program shows a time: the Home's TZ is UTC."""
    return time.strftime("%H:%M", time.gmtime(at))


def on_one_day(test):
    """`test`, set up afresh while it fails on a later UTC day than its records': the program
    read its clock somewhere between, so its words may follow either day."""
    @functools.wraps(test)
    def run(self):
        while True:
            try:
                return test(self)
            except AssertionError:
                if time.gmtime(self.at)[:3] == time.gmtime()[:3]:
                    raise
            self.doCleanups()
            self.setUp()
    return run


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class MachinesOnC(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        # the last tick, a minute back: a silent machine's next check is now
        self.at = time.time() - MINUTE
        fakeadapter.install(home, claude="pass")
        self.config = self.write_config()
        self.readings = home.write(".agentkit/state/machines.json", {
            "this one": self.machine("Linux", 8, 16, 9, 4.4),
            "acme-mac": self.machine("macOS", 4, 8, 6, 1),
            "acme-linux": self.machine("Linux", 16, 32, 22, 8),
            "acme-rental": self.machine("Linux", 16, 32, 22, 8)})
        self.route = home.write(".agentkit/state/google-cloud-ssh-config",
                                f"Host acme-rental\n  # until {int(self.at + DAY)}\n")

    def write_config(self, *, turns=True):
        return akconfig.write(self.home, ["fable"], settings={"turns_on_machines": turns},
                              extra="[machines.acme-mac]\n[machines.acme-linux]\n"
                                    '[google_cloud]\nactive = true\nwork = "all"\n')

    def machine(self, system, cores, memory, free, load, *, answering=True):
        return {"checks": [[self.at - MINUTE, True], [self.at, answering]], "said": {
            "at": self.at - MINUTE, "system": system, "processor": "arm64", "cores": cores,
            "memory_mb": memory * 1024, "free_mb": free * 1024, "load": load,
            "disk_free_mb": 102400, "battery": system == "macOS", "power": 1}}

    def page(self, *rows, width=120):
        self.term = Terminal(self.home, "attach", "--overlay", size=(width, 40),
                             env={"NO_COLOR": "1"})
        self.term.wait("esc leave")
        self.term.keys("c")
        self.config_screen = self.term.wait(lambda screen: "agentkit · config " in screen
                                           and "Machines" in screen and "esc back" in screen)
        self.term.keys(*(["Down"] * 5))       # one model, then the fifth config row
        self.term.wait("› Machines")
        self.term.keys("Enter")
        # A new title can still have the preceding config body beneath it.
        return self.term.wait(lambda screen: "config · machines" in screen
                              and "+ add a machine" in screen and "esc back" in screen
                              and all(row in " ".join(screen.split()) for row in (
                                  "this one ● runs ● tests home", "acme-mac", *rows)))

    def leave(self):
        self.term.keys("Escape", "Escape", "Escape")
        self.assertEqual(self.term.exit_code(), 0)
        self.assertEqual(self.home.calls("ssh"), [])
        self.assertEqual(self.home.calls("curl"), [])

    @on_one_day
    def test_each_machine_says_what_it_is_and_what_work_it_takes(self):
        before = [path.read_bytes() for path in (self.config, self.readings, self.route)]
        shown = " ".join(self.page(
            "this one ● runs ● tests home · 8 cores · 16 GB · 55% busy · 7 of 16 GB used",
            "acme-mac ○ runs ● tests sometimes on · 4 cores · 8 GB · 25% busy · 2 of 8 GB used",
            "acme-linux ● runs ● tests new · 16 cores · 32 GB · 50% busy · 10 of 32 GB used").split())
        self.assertIn("Machines 3 machines Limits", " ".join(self.config_screen.split()))
        self.assertLess(shown.index("this one"), shown.index("acme-mac"))
        self.assertLess(shown.index("acme-mac"), shown.index("acme-linux"))
        # This host has no marks; another machine opens its work with Enter.
        self.term.keys("Space", "Down")
        same = self.term.wait("› acme-mac")
        keys = next(line for line in reversed(same.splitlines()) if line.strip())
        self.assertIn("⏎ open", keys)
        self.assertNotIn("␣", keys)
        # The added machines are the last rows but the one that adds another.
        self.term.keys("Down", "Down")
        self.term.wait("› + add a machine")
        self.term.keys("Up")
        self.term.wait("› acme-linux")
        self.assertEqual(before, [path.read_bytes() for path in (
            self.config, self.readings, self.route)])
        self.leave()

    def test_the_keys_turn_the_pages_of_a_row_taller_than_the_page_before_leaving_it(self):
        self.page()
        self.term.resize(25, 9)
        # Cropping the 120-column frame to 25 still shows `› this one` and 25 rule dashes;
        # wait until the narrow redraw clears the other rows and finishes its key line.
        self.term.wait(lambda screen: "› this one" in screen and "● tests" in screen
                       and "─" * 25 in screen and "acme-" not in screen
                       and "esc back" in screen)
        self.term.keys("Down")
        # the row's next page: its later words, and the highlight has not moved onto the next row
        self.term.wait(lambda screen: "busy" in screen and "this one" not in screen
                       and "› acme-" not in screen)
        self.term.keys("Up")
        self.term.wait("› this one")
        self.leave()

    def test_the_tall_row_test_waits_for_the_narrow_redraw_before_pressing_down(self):
        # Before the program answers SIGWINCH, tmux shows the 120-column frame cropped to 25x9;
        # Down must wait until the narrow frame has cleared the other rows and finished drawing.
        cropped, held, stale, pressed = [], [0], [False], []
        real_resize, real_screen, real_keys = Terminal.resize, Terminal.screen, Terminal.keys

        def resize(term, width, height):
            cropped.append("\n".join(line[:width] for line in real_screen(term).splitlines()[:height]))
            held[0], stale[0] = 1, True
            return real_resize(term, width, height)

        def screen(term, *args, **kwargs):
            if held[0]:
                held[0] -= 1
                stale[0] = True
                return cropped[-1]
            stale[0] = False
            return real_screen(term, *args, **kwargs)

        def keys(term, *presses):
            if stale[0]:
                pressed.append(presses)
            return real_keys(term, *presses)

        with patch.object(Terminal, "resize", resize), \
             patch.object(Terminal, "screen", screen), \
             patch.object(Terminal, "keys", keys):
            self.test_the_keys_turn_the_pages_of_a_row_taller_than_the_page_before_leaving_it()
        self.assertTrue(cropped)
        self.assertEqual(pressed, [])

    def test_turns_off_the_other_machines_take_tests_alone(self):
        self.write_config(turns=False)
        self.page("acme-linux ○ runs ● tests new · 16 cores · 32 GB · 50% busy · 10 of 32 GB used",
                  "this one ● runs ● tests home")
        self.leave()

    def test_a_save_before_the_first_probe_leaves_defaults_to_the_probe(self):
        for system, head in (("macOS", "○ runs ● tests sometimes on"),
                             ("Linux", "● runs ● tests new")):
            with self.subTest(system=system):
                self.write_config()
                self.readings.unlink(missing_ok=True)
                self.page()
                # a save of another machine's marks writes the switch's into each machine's
                self.term.keys("Down", "Down", "Enter")
                self.term.wait("builds and reviews")
                self.term.keys("Space")
                self.term.wait("○ off")
                cfg = akconfig.read(self.home)
                self.assertEqual(cfg["machines"]["acme-mac"]["work"], ["turns", "tests"])
                self.assertEqual(cfg["machines"]["acme-linux"]["work"], ["tests"])
                # a table nothing reads is kept as it was
                self.assertEqual(cfg["google_cloud"], {"active": True, "work": "all"})
                self.term.keys("Escape")
                self.leave()
                self.home.write(".agentkit/state/machines.json", {
                    "acme-mac": self.machine(system, 4, 8, 6, 1)})
                self.page(f"acme-mac {head} · 4 cores · 8 GB · 25% busy · 2 of 8 GB used")
                self.leave()

    def test_a_mac_cannot_be_marked_to_build_or_review(self):
        before = self.config.read_bytes()
        self.page()
        self.term.keys("Down", "Enter")
        self.term.wait("builds and reviews")
        self.term.keys("Space")
        self.term.wait("this machine cannot build or review")
        self.assertEqual(self.config.read_bytes(), before)
        self.term.keys("Escape")
        self.term.wait("› acme-mac")
        self.leave()

    def test_one_machine_is_counted_as_one(self):
        akconfig.write(self.home, ["fable"])
        self.home.write(".agentkit/state/machines.json",
                        {"this one": self.machine("Linux", 8, 16, 9, 4.4)})
        self.term = Terminal(self.home, "attach", "--overlay", size=(120, 40),
                             env={"NO_COLOR": "1"})
        self.term.wait("esc leave")
        self.term.keys("c")
        screen = self.term.wait(lambda screen: "agentkit · config " in screen
                                and "Machines" in screen and "esc back" in screen)
        self.assertIn("Machines 1 machine Limits", " ".join(screen.split()))
        self.term.keys("Escape", "Escape")
        self.assertEqual(self.term.exit_code(), 0)

    @on_one_day
    def test_a_silent_machine_and_a_phone_keep_the_recorded_facts(self):
        silent = self.machine("macOS", 4, 8, 6, 1, answering=False)
        silent["checks"].append([self.at + MINUTE, False])
        self.home.write(".agentkit/state/machines.json", {
            "this one": self.machine("Linux", 8, 16, 9, 4.4),
            "acme-mac": silent})
        screen = self.page(
            f"acme-mac ○ runs ● tests sometimes on · 4 cores · 8 GB · not answering since {minute(self.at)}",
            "acme-linux ● runs ● tests new · never answered", width=40)
        self.assertTrue(all(len(line) <= 40 for line in screen.splitlines()))
        self.leave()


if __name__ == "__main__":
    unittest.main()
