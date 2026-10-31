"""A rent asks no region for more of a family's vCPUs than its quota leaves: the most specific
limit Google lists for the region and family, then all regions', against every machine it lists,
ak's or not.  With none left anywhere no create is made, and the tick says each region's use and
limit; with a limit unread, the walk is as before.  Black-box: `AK_BIN` runs `ak watch` in
`home.tick()`'s box and `ak doctor` on a fake Google's clock, the first tick keeping the prices
the machines listed cost, the second a day later reading prices and limits anew and renting.
"""

from datetime import UTC, datetime
import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home, boxable
from fixtures.google import ADDRESS, IOWA, NL, SPOT, Google, kind, sku

# A vCPU €0.70 an hour in europe-west4 and €0.80 in us-central1: in each a core of a 16 costs less
# than one of an 8, and that less than one of a 72; any in europe-west4 less than in us-central1
SKUS = [sku(f"{SPOT} C4A Arm Instance Core running in Netherlands", NL, 700_000_000),
        sku(f"{SPOT} C4A Arm Instance Core running in Iowa", IOWA, 800_000_000),
        sku(f"{SPOT} C4A Arm Instance Ram running in Europe and Iowa", NL + IOWA, 12_500_000),
        sku("Hyperdisk Balanced Capacity in Europe and Iowa", NL + IOWA, 73_000_000, "GiBy.mo"),
        ADDRESS]
ZONES = {f"zones/{zone}": {"machineTypes": [kind("c4a-highcpu-8", 8, 16), kind(
    "c4a-highcpu-16", 16, 32), kind("c4a-standard-72", 72, 288)]}
         for zone in ("europe-west4-a", "us-central1-a")}
T = datetime(2026, 11, 2, tzinfo=UTC).timestamp()
# 72 vCPUs of ak's and 72 of another's in europe-west4, and 8 of another's in us-east5, where
# nothing is offered; ak's living from half an hour ago for one hour
LISTED = [{"id": id, "name": f"acme-{id}", "labels": labels, "machineType": machine,
           "creationTimestamp": datetime.fromtimestamp(T - 1800, UTC).isoformat(),
           "scheduling": {"maxRunDuration": {"seconds": "3600"}}}
          for id, labels, machine in (
              ("1", {"ak": "rented"}, "zones/europe-west4-a/machineTypes/c4a-standard-72"),
              ("2", {"team": "acme"}, "zones/europe-west4-a/machineTypes/c4a-standard-72"),
              ("3", {"team": "acme"}, "zones/us-east5-a/machineTypes/c4a-highcpu-8"))]


@unittest.skipUnless(boxable() and shutil.which("ssh-keygen"), "no bwrap boxing a tick or ssh-keygen")
class GoogleRentsWhereQuotaIsLeft(unittest.TestCase):
    def rent(self, buckets, quotas):
        """Each machine a tick noting a need asked for, and its rented-machines lines past the
        running one, Google listing `buckets` and `quotas` as limits."""
        home = Home()
        self.addCleanup(home.close)
        google = Google(home, [SKUS], [ZONES])
        self.addCleanup(google.close)
        google.key()
        google.buckets, google.quotas = buckets, quotas
        google.at(T - 86400, 500)
        google.machines = LISTED
        home.write(".agentkit/state/google-cloud-need", "820\n")
        _, _, lines = google.at(T, 500)
        return google.made, lines[1:]

    def assertRents(self, rent, zone, name):
        made, lines = rent
        self.assertEqual(([one["machineType"] for one in made], lines), (
            [f"zones/{zone}/machineTypes/{name}"], [f"{made[0]['name']} rented: {name} in {zone}"]))

    def test_a_full_region_is_passed_over_for_the_cheapest_that_fits_elsewhere(self):
        # europe-west4's C4A holds 144 of 150, its CPUS no limit of C4A's; all regions' leave 12
        self.assertRents(self.rent({("europe-west4", "C4A"): 150, ("us-central1", "C4A"): 24}, {
            "europe-west4": {"CPUS": 1000}, "acme-build": {"CPUS_ALL_REGIONS": 164}}),
            "us-central1-a", "c4a-highcpu-8")

    def test_a_smaller_machine_fits_where_the_cheapest_would_not(self):
        self.assertRents(self.rent({("europe-west4", "C4A"): 152, ("us-central1", "C4A"): 8}, {}),
                         "europe-west4-a", "c4a-highcpu-8")

    def test_none_asked_where_no_region_has_room_and_each_is_said(self):
        # us-central1 lists no C4A bucket: its family's own quota comes before its CPUS
        self.assertEqual(self.rent({("europe-west4", "C4A"): 150}, {
            "us-central1": {"C4A_CPUS": 4, "CPUS": 1000}}), ([], [
                "too little quota left: C4A in europe-west4: 144 of 150 vCPUs in use; "
                "C4A_CPUS in us-central1: 0 of 4 vCPUs in use"]))

    def test_limits_unread_leave_the_walk_as_before(self):
        # Service Usage not answering, europe-west4's CPUS would hold C4A to nothing in its stead
        self.assertRents(self.rent(None, {"europe-west4": {"CPUS": 0}}),
                         "europe-west4-a", "c4a-highcpu-16")


if __name__ == "__main__":
    unittest.main()
