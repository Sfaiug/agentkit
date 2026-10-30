"""`ak doctor` names the machine Google Cloud rents for the least money per core right now: an
arm64 vCPU is a core, two x86 vCPUs one; a type costs its cores, memory, boot disk and address, so
among sizes of a family the most cores win; one with less memory a core than a test piece is
estimated to need is passed over, and bare metal, never Spot.
Black-box: `AK_BIN` asks a fake Google on the loopback (`AK_GOOGLE_URL`).
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home
from fixtures.google import ADDRESS, NL, SPOT, Google, kind, sku

SKUS = [sku(f"{SPOT} C4A Arm Instance Core running in Netherlands", NL, 5_000_000),
        sku(f"{SPOT} C4A Arm Instance Ram running in Netherlands", NL, 600_000),
        sku(f"{SPOT} N2D AMD Instance Core running in Netherlands", NL, 3_000_000),
        sku(f"{SPOT} N2D AMD Instance Ram running in Netherlands", NL, 400_000),
        sku("N2D AMD Instance Core running in Netherlands", NL, 1),   # not Spot
        # the cheapest of all, where no zone offers it
        sku(f"{SPOT} T2A Arm Instance Core running in Iowa", ["us-central1"], 1_000),
        sku(f"{SPOT} T2A Arm Instance Ram running in Iowa", ["us-central1"], 1_000),
        sku("Hyperdisk Balanced Capacity in Netherlands", NL, 73_000_000, "GiBy.mo"),
        sku("Balanced PD Capacity in Netherlands", NL, 109_500_000, "GiBy.mo"), ADDRESS]

# Per core an hour, a boot disk €0.002 on Hyperdisk and €0.003 on Persistent Disk and an address
# €0.0025: c4a-standard-8 €0.0080, c4a-standard-4 €0.0085; n2d-standard-8 €0.0106, half that
# were its vCPUs cores; c4a-highcpu-8 €0.0057 with 256 MB a core.  The c4a-standard-16 and -96
# cost less with more cores, but one has a local SSD and the other is bare metal.
ZONES = [{"zones/europe-west4-a": {"machineTypes": [
             kind("c4a-standard-4", 4, 16), kind("c4a-standard-8", 8, 32),
             kind("c4a-highcpu-8", 8, 2), kind("n2d-standard-8", 8, 32, "X86_64"),
             {**kind("c4a-standard-16-lssd", 16, 64), "bundledLocalSsds": {"partitionCount": 1}},
             kind("c4a-standard-96-metal", 96, 384)]}},
         {"zones/us-central1-a": {"warning": {"code": "NO_RESULTS_ON_PAGE"}}}]
BEST = "rented machines: best now c4a-standard-8 in europe-west4 · 8 cores · 32 GB · €0.064 an hour"


class GoogleBestMachine(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.google = Google(self.home, [SKUS[:5], SKUS[5:]], ZONES)
        self.addCleanup(self.google.close)

    def test_the_lowest_price_per_core_among_offered_types_with_the_memory_wins(self):
        self.google.key()
        self.assertEqual(self.google.rented(), [BEST])
        skus = [path for path in self.google.asked if "/skus?" in path]
        self.assertEqual(len(skus), 2, "every page of the price list")
        self.assertTrue(all("currencyCode=EUR" in path for path in skus), skus)

    def test_a_zone_google_could_not_reach_leaves_no_best(self):
        self.google.key()
        self.google.missed = {"unreachables": ["zones/us-central1-c"]}
        self.assertEqual(self.google.rented(), ["rented machines: asking Google failed: "
                                                "zones/us-central1-c unreachable"])

    def test_a_key_ak_cannot_use_is_a_plain_line(self):
        for key in ("{", [], None, {"private_key": 7}):
            self.home.write(".agentkit/secrets/google-cloud.json", key)
            [line] = self.google.rented()
            self.assertTrue(line.startswith("rented machines: cannot use"), line)

    def test_without_a_key_ak_is_not_set_up_and_asks_nobody(self):
        [line] = self.google.rented()
        self.assertTrue(line.startswith("rented machines: not set up"), line)
        self.assertEqual(self.google.asked, [])


if __name__ == "__main__":
    unittest.main()
