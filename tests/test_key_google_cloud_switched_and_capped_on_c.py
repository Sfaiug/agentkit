"""Cloud settings on c save at once; switching off drains rentals without losing their work.

Black-box: AK_BIN in a terminal and a boxed tick, with a fake Google and SSH idle readings.
"""

from datetime import UTC, datetime
import json
from pathlib import Path
import sys
import tomllib
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akline import Line
from fixtures.akterm import Terminal
from fixtures.google import Google

NOW = datetime(2031, 5, 15, 18, 40, tzinfo=UTC).timestamp()
ROUTE = f'Host acme-busy\n  # until {int(NOW + 3600)}\n  HostName "192.0.2.1"\n'


class CloudSettings(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        fakeadapter.install(home, claude="pass")
        self.config = akconfig.write(home, ["fable"], extra=(
            "[google_cloud]\nactive = true\nmax_month = 200\nx_custom = 7\n"))
        home.env["AK_GOOGLE_CLOCK"] = str(home.write("clock/now", str(NOW)))

    @unittest.skipUnless(REAL_TMUX, "no tmux installed")
    def test_space_switches_and_enter_saves_only_whole_nonnegative_euros(self):
        self.home.write(".agentkit/state/google-cloud-ssh-config", ROUTE)
        self.home.write(".agentkit/state/google-cloud-ledger.json", {
            "answered": NOW, "spent": 31.74, "machines": {
                "busy": {"price": 0.5, "until": NOW + 3600}}})
        term = Terminal(self.home, "attach", "--overlay", size=(100, 30), env={"NO_COLOR": "1"})
        term.wait("esc leave")
        term.keys("c")
        term.wait("Machines")
        term.keys(*(["Down"] * 6))
        term.wait("› Machines")
        term.keys("Enter")
        term.wait("config · machines")
        term.keys("Down", "Down")
        shown = term.wait("› Google Cloud")
        self.assertIn("␣ mark", shown)
        self.assertIn("⏎ open", shown)
        original = tomllib.loads(self.config.read_text())
        for active in (False, True):
            term.keys("Space")
            term.wait(lambda screen: "› Google Cloud" in screen and (
                "○ off · 1 machine going once idle" if not active else "● on") in screen)
            expected = {**original, "google_cloud": {
                **original["google_cloud"], "active": active}}
            self.assertEqual(tomllib.loads(self.config.read_text()), expected)
        for value in ("150", "-5", "abc", "1.5", "", "1000000000000", "0"):
            before = self.config.read_bytes()
            term.keys("Enter")
            term.wait("Monthly cap")
            term.keys("Down", "Down", "Enter")
            term.wait("whole euros per month")
            if value == "150":
                term.type(" 1")
                term.wait(lambda screen: any(line.strip() == "1" for line in screen.splitlines()))
                self.home.write(".agentkit/state/google-cloud-ssh-config", "Host *\n")
                term.type("50")
            else:
                term.type(" " + value)
            term.keys("Enter")
            if value in ("150", "1000000000000", "0"):
                term.wait(lambda screen: "⏎ open" in screen and
                          f"Monthly cap €{int(value):g}" in " ".join(screen.split()))
                self.assertEqual(tomllib.loads(self.config.read_text())["google_cloud"], {
                    "active": True, "max_month": int(value), "x_custom": 7})
            else:
                term.wait("the monthly cap must be a whole number of euros, 0 or more")
                self.assertEqual(self.config.read_bytes(), before)
            term.keys("Escape")
            term.wait("› Google Cloud")
        term.keys("Enter")
        term.wait("Monthly cap")
        term.keys("Down", "Down", "Enter")
        term.wait("whole euros per month")
        term.type("999")
        term.keys("Escape")
        term.wait("⏎ open")
        self.assertEqual(tomllib.loads(self.config.read_text())["google_cloud"]["max_month"], 0)
        term.keys("Escape", "Escape", "Escape", "Escape")
        self.assertEqual(term.exit_code(), 0)
        self.assertEqual(self.home.calls("ssh"), [])

    @unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
    def test_off_keeps_metering_and_routes_but_rents_and_asks_for_no_quota(self):
        home = self.home
        google = Google(home, [[]], [{}])
        self.addCleanup(google.close)
        google.key()
        self.config.write_text(self.config.read_text() + (
            "\n[google_cloud]\nactive = false\nmax_month = 200\n"))
        self.route = home.write(".agentkit/state/google-cloud-ssh-config", ROUTE)
        ledger = home.write(".agentkit/state/google-cloud-ledger.json", {
            "answered": NOW - 180, "spent": 31.74, "machines": {}})
        home.write(".agentkit/state/google-cloud-offers.json", {"at": NOW - 90000, "offers": [
            ["c4a-standard-8", "europe-west4", 8, 32768, 0.5, [], "", ""]]})
        home.fake("ssh", '#!/bin/sh\ncase "$*" in *acme-idle*) echo 601;; *) echo 0;; esac\n')
        for name in ("busy", "idle"):
            google.machines.append({"id": name, "name": f"acme-{name}", "labels": {
                "ak": "rented"}, "creationTimestamp": "2031-05-15T18:00:00Z",
                "machineType": "zones/europe-west4-a/machineTypes/c4a-standard-8",
                "scheduling": {"maxRunDuration": {"seconds": "6000"}},
                "networkInterfaces": [{"accessConfigs": [{"natIP": "192.0.2.1"}]}]})
        need = home.write(".agentkit/state/google-cloud-need", "456\n")
        done = home.tick(env=google.env)
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertEqual([one for one in google.asked if one.startswith("DELETE ")], [
            "DELETE acme-idle"])
        moved = json.loads(ledger.read_text())
        self.assertEqual(moved["answered"], NOW)
        self.assertAlmostEqual(moved["spent"], 31.74 + 2 / 3)
        self.assertFalse(need.exists())
        self.assertEqual(google.made, [])
        self.assertEqual(google.asks, [])
        self.assertFalse(any("quota" in one.lower() or "/skus" in one for one in google.asked))
        self.assertIn("Host acme-busy\n", self.route.read_text())
        self.assertNotIn("Host acme-idle\n", self.route.read_text())
        # Lowering the cap below that spend keeps the existing past-the-cap return rule.
        google.machines = google.machines[:1]
        home.write(".agentkit/state/google-cloud-need", "456\n")
        _, deleted, _ = google.at(NOW + 180, 30)
        self.assertEqual(deleted, ["acme-busy"])
        self.assertEqual(google.made, [])
        # With no work marked, idle and booting rentals go back, busy or silent ones stay.
        self.config.write_text(self.config.read_text().split("\n[google_cloud]")[0] +
                               '\n[google_cloud]\nactive = true\nmax_month = 200\nwork = []\n')
        home.write(".agentkit/state/google-cloud-offers.json", {"at": NOW + 180, "offers": [
            ["c4a-standard-8", "europe-west4", 8, 32768, 0.5, ["europe-west4-a"], "", ""]]})
        for name, address in (("starting", False), ("setting-up", True),
                              ("working", True), ("silent", True)):
            google.machines.append({**google.machines[0], "id": name, "name": f"acme-{name}",
                                    "networkInterfaces": google.machines[0]["networkInterfaces"]
                                    if address else []})
        home.fake("ssh", '#!/bin/sh\ncase "$*" in *acme-setting-up*) echo -1;; '
                  '*acme-working*) echo 0;; *acme-silent*) exit 255;; *) echo 1;; esac\n')
        home.write(".agentkit/state/google-cloud-need", "456 tests\n789 turns\n")
        start = len(google.asked)
        done = home.tick(env=google.env)
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertEqual([one for one in google.asked[start:] if one.startswith("DELETE ")],
                         ["DELETE acme-busy", "DELETE acme-starting", "DELETE acme-setting-up"])
        self.assertEqual((google.made, google.asks), ([], []))
        self.assertIn("acme-busy listed no work marked, given back", json.loads(
            (home.path / ".agentkit/state/google-cloud-late.json").read_text()))

    def test_off_sends_no_new_work_to_a_rental(self):
        self.config.write_text(self.config.read_text().replace("active = true", "active = false"))
        self.home.write(".agentkit/state/google-cloud-ssh-config", ROUTE)
        line = Line({"t/ok.sh": "true\n", "tools/helper/Containerfile": "FROM acme\n"},
                    home=self.home)
        line.member({"api.txt": "x\n"})
        done = line.land()
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertTrue(line.runs())
        self.assertEqual(self.home.calls("ssh"), [])


if __name__ == "__main__":
    unittest.main()
