"""A suite with no room makes the tick rent the type cheapest a core with a piece's memory, Spot,
in the next zone where one refuses, on the meter first; none while one comes up or ak may not rent,
nor past the month's cap or the day's share.  Black-box: `AK_BIN` lands a line beside a helper with
no room, then runs `ak watch` boxed and `ak doctor` on tests/fixtures/google.py's Google."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home, boxable
from fixtures.akline import Line
from fixtures.google import SKUS, Google, kind

# A core an hour: c4a-lowmem-8 €0.707, too little memory; c4a-highcpu-8 €0.726 (P an hour)
TYPES = [kind("c4a-lowmem-8", 8, 4), kind("c4a-highcpu-8", 8, 16), kind("c4a-standard-8", 8, 32)]
P, T, HOUR = 5.8045, 1793491200, 3600    # T: 1 Nov 2026 00:00 UTC
LIFE = int(2 * 1000 / 30 * HOUR / P)    # the day's share of €1000 on 1 Nov at P, under 12 hours


@unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
class GoogleRentsUnderACap(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        cls.google = google = Google(home, [SKUS], [{
            f"zones/europe-west4-{zone}": {"machineTypes": TYPES} for zone in "ab"}])
        cls.addClassCleanup(google.close)
        google.key()
        home.fake("ssh", "#!/bin/sh\nexit 252\n")     # the helper has no room, nor a rented one
        cls.toml = (home.path / ".agentkit/config.toml").read_text()
        home.write(".agentkit/state/google-cloud-offers.json", {     # kept before renting
            "at": T, "offers": [["c4a-highcpu-8", "europe-west4", 8, 16384, P]]})
        cls.quiet = cls.step(T - 180, need=False)
        line = Line({"t/a.sh": "true\n", "tools/helper/Containerfile": "FROM acme\n"}, home=home)
        line.member({"api.txt": "x\n"})
        cls.landed, google.answers = line.land(), [["ZONE_RESOURCE_POOL_EXHAUSTED"]]
        cls.made, cls.said = cls.step(T, need=False)
        google.machines = [{**cls.made[1], "id": "1", "creationTimestamp": "2026-11-01T00:00:00Z",
                            "networkInterfaces": [{"accessConfigs": [{"natIP": "203.0.113.1"}]}]}]
        cls.steps = [cls.step(T + 180), cls.step(T + 360, cap=0), cls.step(T + 600, need=False)]
        google.machines, google.answers = [], [None]
        cls.steps += [cls.step(T + at) for at in (780, 960, 1380)]
        cls.steps.append(cls.step(T + 29.5 * 24 * HOUR, cap=67))

    @classmethod
    def step(cls, when, cap=1000, need=True):
        """At `when` and `cap` euros, 0 not active, a need noted, what a tick asked for, ak's lines."""
        cls.home.write(".agentkit/config.toml", f'suite_helper = "acme-helper"\n{cls.toml}\n'
                       f"[google_cloud]\nactive = {'true' if cap else 'false'}\nmax_month = {cap}\n")
        if need:
            cls.home.write(".agentkit/state/google-cloud-need", "820\n")
        cls.google.at(when)
        made, done = len(cls.google.made), cls.home.tick(env=cls.google.env)
        assert done.code == 0, done.out + done.err
        return cls.google.made[made:], [line[17:] for line in cls.google.rented()]

    def test_the_cheapest_core_with_a_pieces_memory_is_rented_where_google_has_stock(self):
        self.assertEqual((self.landed.code, self.quiet[0]), (0, []), self.landed.out + self.landed.err)
        self.assertEqual([one["machineType"] for one in self.made], [
            f"zones/europe-west4-{zone}/machineTypes/c4a-highcpu-8" for zone in "ab"])
        self.assertEqual((self.made[1]["labels"], self.made[1]["scheduling"]), ({"ak": "rented"}, {
            "provisioningModel": "SPOT", "instanceTerminationAction": "DELETE",
            "maxRunDuration": {"seconds": str(LIFE)}, "automaticRestart": False,
            "onHostMaintenance": "TERMINATE"}))
        self.assertEqual(self.said, [
            "0 running · €0.00 of €1000.00 this month",
            "c4a-highcpu-8 in europe-west4-a refused: ZONE_RESOURCE_POOL_EXHAUSTED",
            f"{self.made[1]['name']} rented: c4a-highcpu-8 in europe-west4-b for 11.5 hours"])

    def test_none_while_one_comes_up_or_ak_may_not_rent_nor_past_either_limit(self):
        listed, off, not_ready, cut, booked, day, month = self.steps
        running = f"0 running · €{P * 780 / HOUR:.2f} of €1000.00 this month"
        # listed, coming up; the need read while not active is gone; one never ready goes back
        self.assertEqual([listed, off[0], not_ready], [
            ([], [f"1 running · €{P / 20:.2f} of €1000.00 this month"]), [], ([], [
                f"1 running · €{P / 6:.2f} of €1000.00 this month",
                f"{self.made[1]['name']} listed not ready, given back"])])
        # one cut short stays on the meter, coming up, then counts, whole once past its end
        self.assertEqual([cut[1], booked, day, month], [[
            running, f"{cut[0][0]['name']} asked of Google, no answer: on the meter to its end"],
            ([], [running]), ([], [running, "not rented: €0.00 left of what today may cost"]),
            ([], [f"0 running · €{P * LIFE / HOUR:.2f} of €67.00 this month",
                  f"not rented: €{67 - P * LIFE / HOUR:.2f} left of what this month may cost"])])


if __name__ == "__main__":
    unittest.main()
