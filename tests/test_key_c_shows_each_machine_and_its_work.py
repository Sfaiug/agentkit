"""`c` shows every machine and its work, from the tick's records alone.

Black-box: AK_BIN runs under a terminal in a temporary HOME, with invented machines,
recorded readings and a cloud ledger, all stamped by the real clock. No machine or cloud is
asked while drawing.
"""

import functools
import json
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import Terminal

MINUTE, HOUR, DAY = 60, 3600, 86400


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
        self.until = self.at + 21 * HOUR
        fakeadapter.install(home, claude="pass")
        self.config = self.write_config()
        self.readings = home.write(".agentkit/state/machines.json", {
            "this one": self.machine("Linux", 8, 16, 9, 4.4),
            "acme-mac": self.machine("macOS", 4, 8, 6, 1),
            "acme-rental": self.machine("Linux", 16, 32, 22, 8)})
        self.ledger = home.write(".agentkit/state/google-cloud-ledger.json", {
            "answered": self.at, "spent": 31.74, "machines": {
                name: {"price": 0.5, "until": self.until} for name in ("one", "two")}})
        self.route = home.write(".agentkit/state/google-cloud-ssh-config",
                                f"Host acme-rental\n  # until {int(self.until)}\n")

    def write_config(self, *, turns=True, active=True):
        return akconfig.write(self.home, ["fable"], settings={"turns_on_machines": turns},
                              extra=f"[machines.acme-mac]\n[google_cloud]\n"
                                    f"active = {str(active).lower()}\nmax_month = 200\n")

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
                              and "Google Cloud" in screen and "esc back" in screen
                              and all(row in " ".join(screen.split()) for row in (
                                  "this one home", "acme-mac", *rows)))

    def leave(self):
        self.term.keys("Escape", "Escape", "Escape")
        self.assertEqual(self.term.exit_code(), 0)
        self.assertEqual(self.home.calls("ssh"), [])
        self.assertEqual(self.home.calls("curl"), [])

    @on_one_day
    def test_each_machine_says_what_it_is_and_what_work_it_takes(self):
        before = [path.read_bytes() for path in (self.config, self.readings, self.ledger, self.route)]
        shown = " ".join(self.page(
            "this one home · 8 cores · 16 GB · 55% busy · 7 of 16 GB used · "
            "sessions, builds, reviews, tests",
            "acme-mac sometimes on · 4 cores · 8 GB · 25% busy · 2 of 8 GB used · tests",
            f"acme-rental rented until {minute(self.until)} · 16 cores · 32 GB · 50% busy · "
            "10 of 32 GB used · builds, reviews, tests",
            "Google Cloud ● on · €31.74 of €200 this month · 2 machines up").split())
        self.assertIn("3 machines · Google Cloud on · €31.74 of €200 this month",
                      " ".join(self.config_screen.split()))
        self.assertNotIn("machines up", self.config_screen)
        self.assertLess(shown.index("this one"), shown.index("acme-mac"))
        self.assertLess(shown.index("acme-mac"), shown.index("acme-rental"))
        # This host has no marks; another machine opens its work with Enter.
        self.term.keys("Enter", "Space", "Down")
        same = self.term.wait("› acme-mac")
        keys = next(line for line in reversed(same.splitlines()) if line.strip())
        self.assertIn("⏎ open", keys)
        self.assertNotIn("␣", keys)
        self.assertEqual(before, [path.read_bytes() for path in (
            self.config, self.readings, self.ledger, self.route)])
        self.leave()

    def test_the_keys_turn_the_pages_of_a_row_taller_than_the_page_before_leaving_it(self):
        self.page()
        self.term.resize(25, 9)
        self.term.wait(lambda screen: "› this one" in screen and "─" * 25 in screen)
        self.term.keys("Down")
        self.term.wait("55% busy")
        self.term.keys("Up")
        self.term.wait("› this one")
        self.leave()

    def test_turns_off_the_other_machines_take_tests_alone(self):
        self.write_config(turns=False)
        self.page("10 of 32 GB used · tests", "sessions, builds, reviews, tests")
        self.leave()

    def test_a_save_before_the_first_probe_leaves_defaults_to_the_probe(self):
        for system, work in (("macOS", "tests"), ("Linux", "builds, reviews, tests")):
            with self.subTest(system=system):
                self.write_config()
                self.readings.unlink(missing_ok=True)
                self.page()
                self.term.keys("Down", "Down", "Down", "Space")
                self.term.wait("○ off")
                self.assertEqual(akconfig.read(self.home)["machines"]["acme-mac"]["work"],
                                 ["turns", "tests"])
                self.leave()
                self.home.write(".agentkit/state/machines.json", {
                    "acme-mac": self.machine(system, 4, 8, 6, 1)})
                self.page(f"4 cores · 8 GB · 25% busy · 2 of 8 GB used · {work}")
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

    def test_inactive_cloud_says_off(self):
        self.write_config(active=False)
        shown = " ".join(self.page("Google Cloud ○ off · 2 machines going once idle").split())
        self.assertNotIn("€", shown)
        self.assertIn("2 machines · Google Cloud off", " ".join(self.config_screen.split()))
        self.leave()
        self.ledger.write_text('{"answered": 0, "spent": 0, "machines": {}}')
        shown = " ".join(self.page("Google Cloud ○ off").split())
        self.assertNotIn("going once idle", shown)
        self.leave()

    def test_unreadable_missing_or_old_ledger_never_invents_spend(self):
        # 31 days back is always an earlier month
        for content in ("broken", None, '{"answered": 0, "spent": 0, "machines": {}}',
                        json.dumps({"answered": self.at - 31 * DAY, "spent": 31.74,
                                    "machines": {}})):
            with self.subTest(content=content):
                if content is None:
                    self.ledger.unlink()
                else:
                    self.ledger.write_text(content)
                shown = " ".join(self.page("Google Cloud ● on · spend unknown").split())
                self.assertNotIn("€", shown + self.config_screen)
                self.leave()

    @on_one_day
    def test_a_silent_machine_and_a_phone_keep_the_recorded_facts(self):
        silent = self.machine("macOS", 4, 8, 6, 1, answering=False)
        silent["checks"].append([self.at + MINUTE, False])
        self.home.write(".agentkit/state/machines.json", {
            "this one": self.machine("Linux", 8, 16, 9, 4.4),
            "acme-mac": silent})
        screen = self.page(f"not answering since {minute(self.at)} · tests",
                           f"acme-rental rented until {minute(self.until)} · never answered · "
                           "builds, reviews, tests", width=40)
        self.assertTrue(all(len(line) <= 40 for line in screen.splitlines()))
        self.leave()


if __name__ == "__main__":
    unittest.main()
