"""A rented machine's price holds the boot disk and the address it pays for, as the bill will: 20 GB
of the cheapest disk its series boots from in its region, at Google's monthly price over 730 hours
(older series Persistent Disk alone, C3, C3D, H3, M3 and Z3 either, every other series Hyperdisk
alone; a type whose region prices none is passed over), and an address, the same everywhere.
Spread over its cores, they make a larger machine cheaper per core.
Black-box: `AK_BIN` asks a fake Google on the loopback (`AK_GOOGLE_URL`).
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home
from fixtures.google import ADDRESS, IOWA, NL, SPOT, Google, kind, sku


def disk(product, place, regions, nanos):
    return sku(f"{product} Capacity in {place}", regions, nanos, "GiBy.mo")


# €0.0592 an hour for c4a-standard-8's cores and memory in europe-west4, €0.0074 a core
C4A = [sku(f"{SPOT} C4A Arm Instance Core running in Netherlands", NL, 5_000_000),
       sku(f"{SPOT} C4A Arm Instance Ram running in Netherlands", NL, 600_000)]
HYPERDISK = disk("Hyperdisk Balanced", "Netherlands", NL, 73_000_000)   # 20 GB €0.002 an hour
C4A_8 = {"zones/europe-west4-a": {"machineTypes": [kind("c4a-standard-8", 8, 32)]}}
BEST_C4A = ("rented machines: best now c4a-standard-8 in europe-west4 · 8 cores · 32 GB · "
            "€0.064 an hour")


class PriceHoldsDiskAndAddress(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)

    def rented(self, skus, zones):
        google = Google(self.home, [skus], [zones])
        self.addCleanup(google.close)
        google.key()
        return google.rented()

    def test_the_price_holds_the_boot_disk_and_the_address(self):
        # €0.062 without the address, €0.061 without the disk
        self.assertEqual(self.rented([*C4A, HYPERDISK, ADDRESS], C4A_8), [BEST_C4A])

    def test_c3_boots_from_the_cheaper_disk_it_takes(self):
        # Per core an hour: c3-standard-8 €0.0081 on Persistent Disk, €0.0091 on Hyperdisk;
        # c4a-standard-8 in us-central1 €0.0083 on Hyperdisk and €0.0078 on the Persistent Disk
        # C4A cannot boot from, as in europe-west4, where it would be €0.0077 with no disk.
        skus = [sku(f"{SPOT} C3 Instance Core running in Iowa", IOWA, 2_000_000),
                sku(f"{SPOT} C3 Instance Ram running in Iowa", IOWA, 400_000),
                sku(f"{SPOT} C4A Arm Instance Core running in Iowa", IOWA, 5_000_000),
                sku(f"{SPOT} C4A Arm Instance Ram running in Iowa", IOWA, 600_000), *C4A,
                disk("Balanced PD", "Iowa", IOWA, 36_500_000),
                disk("Balanced PD", "Netherlands", NL, 36_500_000),
                disk("Hyperdisk Balanced", "Iowa", IOWA, 182_500_000), ADDRESS]
        zones = {**C4A_8, "zones/us-central1-a": {"machineTypes": [
            kind("c3-standard-8", 8, 32, "X86_64"), kind("c4a-standard-8", 8, 32)]}}
        self.assertEqual(self.rented(skus, zones), [
            "rented machines: best now c3-standard-8 in us-central1 · 4 cores · 32 GB · "
            "€0.032 an hour"])

    def test_a_smaller_type_cheaper_by_its_cores_and_memory_costs_more_a_core_in_all(self):
        # t2a-standard-2 costs €0.013 an hour for its cores and memory, €0.0065 a core, and
        # €0.0035 more for its disk and address: €0.00825 a core to c4a-standard-8's €0.0080
        skus = [*C4A, HYPERDISK, ADDRESS, disk("Balanced PD", "Netherlands", NL, 36_500_000),
                sku(f"{SPOT} T2A Arm Instance Core running in Netherlands", NL, 4_500_000),
                sku(f"{SPOT} T2A Arm Instance Ram running in Netherlands", NL, 500_000)]
        zones = {"zones/europe-west4-a": {"machineTypes": [
            kind("c4a-standard-8", 8, 32), kind("t2a-standard-2", 2, 8)]}}
        self.assertEqual(self.rented(skus, zones), [BEST_C4A])


if __name__ == "__main__":
    unittest.main()
