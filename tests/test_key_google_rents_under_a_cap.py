"""A suite no machine takes has the tick rent the type cheapest a core with its memory a core, in
a zone where ak has none first, on to the next zone where a zone's stock is out and to another
region where a region's quota of that family's cores is, a smaller type of it there first, until
Google's own end; none while one comes up or `[google_cloud]` is off, nor past the month's cap,
which one whose reply was cut short counts against.  Black-box: `AK_BIN` lands a line beside a
helper with no room, then runs `ak watch` in `home.tick()`'s box and `ak doctor` on a fake
Google's clock.
"""

from datetime import UTC, datetime
import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home, boxable
from fixtures.akline import Line
from fixtures.google import IOWA, SKUS, SPOT, Google, kind, sku

# An hour: c4a-small-8, 512 MiB a core, €5.6545; c4a-highcpu-8 €5.8045, c4a-highcpu-4 €2.9045,
# c4a-standard-8 €6.0045; in Iowa a core costs €0.05 more
ZONES = {f"zones/{zone}": {"machineTypes": [
    kind("c4a-small-8", 8, 4), kind("c4a-highcpu-8", 8, 16), kind("c4a-highcpu-4", 4, 8),
    kind("c4a-standard-8", 8, 32)]} for zone in (
    "europe-west4-a", "europe-west4-b", "us-central1-a")}
IOWA_SKUS = [sku(f"{SPOT} C4A Arm Instance Core running in Americas", IOWA, 750_000_000),
             sku(f"{SPOT} C4A Arm Instance Ram running in Americas", IOWA, 12_500_000),
             sku("Hyperdisk Balanced Capacity in Iowa", IOWA, 73_000_000, "GiBy.mo")]
NO_QUOTA = ({"error": {"errors": [{"reason": "quotaExceeded"}]}}, 403)
NO_STOCK = ({"status": "DONE", "error": {"errors": [{"code": "ZONE_RESOURCE_POOL_EXHAUSTED"}]}},)
T = datetime(2026, 11, 2, tzinfo=UTC).timestamp()
CAPPED = ("rents nothing: €{0}.00 of €{0}.00 spent this month or held to the machines' ends "
          "leaves less than 10 minutes of c4a-standard-8")


@unittest.skipUnless(boxable() and shutil.which("ssh-keygen"), "no bwrap boxing a tick or ssh-keygen")
class GoogleRentsUnderACap(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        cls.google = google = Google(home, [SKUS + IOWA_SKUS], [ZONES])
        cls.addClassCleanup(google.close)
        google.key()
        home.fake("ssh", "#!/bin/sh\nexit 252\n")     # the helper has no room
        toml = home.path / ".agentkit/config.toml"
        toml.write_text('suite_helper = "acme-1"\n' + toml.read_text())
        google.at(T - 180)      # the prices kept
        line = Line({"t/a.sh": "true\n", "tools/helper/Containerfile": "FROM acme\n"}, home=home)
        line.member({"api.txt": "x\n"})
        cls.landed, google.answers = line.land(), [NO_STOCK, NO_QUOTA, NO_QUOTA]
        cls.rent, made = (google.at(T), google.made[:]), google.made[-1]
        # on the meter by name, then listed from T + 300 and not ready: coming up
        cls.coming = [cls.needs(T + 180)]
        google.machines = [{"id": "1", "name": made["name"], "labels": {"ak": "rented"},
                            "creationTimestamp": datetime.fromtimestamp(T + 300, UTC).isoformat(),
                            "machineType": made["machineType"], "scheduling": made["scheduling"]}]
        cls.coming.append(cls.needs(T + 840))
        cls.capped, google.answers = cls.needs(T + 960), [({"status": "DONE"}, 200, 1)]
        cls.cut = cls.needs(T + 1140, 100), google.made[-1]
        cls.counted, cls.off = cls.needs(T + 1800, 100), cls.needs(T + 1980, 0)
        cls.dropped = google.at(T + 2160, 100)

    @classmethod
    def needs(cls, when, cap=50):
        cls.home.write(".agentkit/state/google-cloud-need", "820\n")    # as the line's suite
        return cls.google.at(when, cap)

    def test_the_type_the_suite_needs_cheapest_a_core_in_a_region_with_room_until_googles_end(self):
        self.assertEqual(self.landed.code, 0, self.landed.out + self.landed.err)
        (_, _, lines), made = self.rent
        self.assertEqual([one["machineType"].split("/")[1::2] for one in made], [
            ["europe-west4-a", "c4a-highcpu-8"], ["europe-west4-b", "c4a-highcpu-8"],
            ["europe-west4-a", "c4a-highcpu-4"], ["us-central1-a", "c4a-highcpu-8"]])
        # what €50 buys of it, under 12 hours
        self.assertEqual((made[-1]["labels"], made[-1]["scheduling"], lines[1:]), ({"ak": "rented"}, {
            "provisioningModel": "SPOT", "instanceTerminationAction": "DELETE",
            "maxRunDuration": {"seconds": "29011"}, "automaticRestart": False,
            "onHostMaintenance": "TERMINATE"}, [f"{made[-1]['name']} rented: c4a-highcpu-8 in "
                                                "us-central1-a"]))

    def test_none_while_one_comes_up_or_off_or_past_the_cap_where_one_cut_short_counts(self):
        for asked, _, lines in [*self.coming, self.off, self.dropped]:
            self.assertFalse([one for one in asked if one.endswith("/instances")], asked)
        self.assertEqual((self.off[0], self.dropped[2][1:]), ([], []))  # a need while off dropped
        self.assertEqual(self.capped[2][1:], [CAPPED.format(50)])   # the first held to its end
        (_, _, lines), made = self.cut
        self.assertEqual(made["machineType"], "zones/europe-west4-b/machineTypes/c4a-highcpu-8")
        self.assertTrue(lines[1].startswith(f"{made['name']} asked for in europe-west4-b, kept on "
                                            "the meter: asking Google failed: "), lines)
        self.assertEqual(self.counted[2][1:], [CAPPED.format(100)])


if __name__ == "__main__":
    unittest.main()
