"""`c` shows every machine and its work, from the tick's records alone.

Black-box: AK_BIN runs under a terminal in a temporary HOME, with invented machines,
recorded readings and a cloud ledger. No machine or cloud is asked while drawing.
"""

from datetime import UTC, datetime
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import AK, REPO, REAL_TMUX, Home
from fixtures.akterm import Terminal
from fixtures.google import CLOCK

NOW = datetime(2031, 5, 15, 18, 40, tzinfo=UTC).timestamp()
UNTIL = datetime(2031, 5, 16, 15, 44, tzinfo=UTC).timestamp()


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class MachinesOnC(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        self.now = home.root / "now"
        self.now.write_text(str(NOW))
        clock = home.root / "sitecustomize.py"
        clock.write_text(CLOCK.format(ak=AK, repo=str(REPO), tests=str(REPO / "tests"),
                                      now=str(self.now)) + "\n"
                         "    from agentkit import machines, menu\n"
                         "    machines.time = menu.time = google_cloud.time\n")
        home.env["PYTHONPATH"] = str(home.root)
        fakeadapter.install(home, claude="pass")
        self.config = self.write_config()
        self.readings = home.write(".agentkit/state/machines.json", {
            "this one": self.machine("Linux", 8, 16, 9, 4.4),
            "acme-mac": self.machine("macOS", 4, 8, 6, 1),
            "acme-rental": self.machine("Linux", 16, 32, 22, 8)})
        self.ledger = home.write(".agentkit/state/google-cloud-ledger.json", {
            "answered": NOW, "spent": 31.74, "machines": {
                name: {"price": 0.5, "until": UNTIL} for name in ("one", "two")}})
        self.route = home.write(".agentkit/state/google-cloud-ssh-config",
                                f"Host acme-rental\n  # until {int(UNTIL)}\n")

    def write_config(self, *, turns=True, active=True):
        return akconfig.write(self.home, ["fable"], settings={"turns_on_machines": turns},
                              extra=f"[machines.acme-mac]\n[google_cloud]\n"
                                    f"active = {str(active).lower()}\nmax_month = 200\n")

    def machine(self, system, cores, memory, free, load, *, answering=True):
        return {"checks": [[NOW - 60, True], [NOW, answering]], "said": {
            "at": NOW - 60, "system": system, "processor": "arm64", "cores": cores,
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

    def test_each_machine_says_what_it_is_and_what_work_it_takes(self):
        before = [path.read_bytes() for path in (self.config, self.readings, self.ledger, self.route)]
        shown = " ".join(self.page(
            "this one home · 8 cores · 16 GB · 55% busy · 7 of 16 GB used · "
            "sessions, builds, reviews, tests",
            "acme-mac sometimes on · 4 cores · 8 GB · 25% busy · 2 of 8 GB used · tests",
            "acme-rental rented until 15:44 · 16 cores · 32 GB · 50% busy · "
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
                self.assertNotIn("work", akconfig.read(self.home)["machines"]["acme-mac"])
                self.leave()
                self.home.write(".agentkit/state/machines.json", {
                    "acme-mac": self.machine(system, 4, 8, 6, 1)})
                self.page(f"4 cores · 8 GB · 25% busy · 2 of 8 GB used · {work}")
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
        for content in ("broken", None, '{"answered": 0, "spent": 0, "machines": {}}',
                        '{"answered": 1, "spent": 31.74, "machines": {}}'):
            with self.subTest(content=content):
                if content is None:
                    self.ledger.unlink()
                else:
                    self.ledger.write_text(content)
                shown = " ".join(self.page("Google Cloud ● on · spend unknown").split())
                self.assertNotIn("€", shown + self.config_screen)
                self.leave()

    def test_a_silent_machine_and_a_phone_keep_the_recorded_facts(self):
        silent = self.machine("macOS", 4, 8, 6, 1, answering=False)
        silent["checks"].append([NOW + 60, False])
        self.now.write_text(str(NOW + 60))
        self.home.write(".agentkit/state/machines.json", {
            "this one": self.machine("Linux", 8, 16, 9, 4.4),
            "acme-mac": silent})
        screen = self.page("not answering since 18:40 · tests",
                           "acme-rental rented until 15:44 · never answered · builds, reviews, tests",
                           width=40)
        self.assertTrue(all(len(line) <= 40 for line in screen.splitlines()))
        self.leave()


if __name__ == "__main__":
    unittest.main()
