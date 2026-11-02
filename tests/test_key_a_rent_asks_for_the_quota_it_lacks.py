"""After its walk a rent asks Google for what the cheapest offer it skipped for quota lacks: each
quota past the limit, for the vCPUs in use there plus the offer's; one offer's each rent and one
ask per quota a day, Google's list of preferences being all that remembers.  Nothing waits and
nothing fails with it, and each ask, or a preference granted short, is a line.  Black-box: as
tests/test_key_google_rents_where_quota_is_left.py, 144 C4A vCPUs in use in europe-west4 and 152
in all regions, cheapest first the c4a-highcpu-16, -8 and standard-72 there, then in us-central1.
"""

import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home, boxable
from fixtures.google import QUOTAS, Google, stamp
from test_key_google_rents_where_quota_is_left import LISTED, SKUS, T, ZONES

FAMILY, ALL = "CPUS-PER-VM-FAMILY-per-project-region", "CPUS-ALL-REGIONS-per-project"
NL, US = {"region": "europe-west4", "vm_family": "C4A"}, {"region": "us-central1", "vm_family": "C4A"}
ROOM = {("europe-west4", "C4A"): 150, ("us-central1", "C4A"): 24}
RENTS_NEXT = ["zones/us-central1-a/machineTypes/c4a-highcpu-16"]
ASKED_NL = "C4A in europe-west4: 160 vCPUs asked of Google, the limit now 150"


def kept(quota_id, dimensions, ago, asked="160", granted="150", reconciling=False):
    return {"name": f"{QUOTAS[1:]}/{quota_id}", "service": "compute.googleapis.com", "etag": "e7",
            "quotaId": quota_id, "dimensions": dimensions, "updateTime": stamp(T - ago),
            "reconciling": reconciling, "quotaConfig": {
                "preferredValue": asked, **({"grantedValue": granted} if granted else {})}}


@unittest.skipUnless(boxable() and shutil.which("ssh-keygen"), "no bwrap boxing a tick or ssh-keygen")
class ARentAsksForTheQuotaItLacks(unittest.TestCase):
    def rent(self, buckets=ROOM, quotas={}, preferences=(), refusing={}, cap=500):
        """(What was asked as (method, quotaId, vCPUs), each machine made, the rent's lines),
        Google listing `buckets` and `quotas` as limits."""
        home = Home()
        self.addCleanup(home.close)
        self.google = google = Google(home, [SKUS], [ZONES])
        self.addCleanup(google.close)
        google.key()
        google.buckets, google.quotas = buckets, quotas
        google.at(T - 86400, 500)
        google.machines, google.preferences, google.refusing = LISTED, [*preferences], refusing
        home.write(".agentkit/state/google-cloud-need", "820\n")
        lines = google.at(T, cap)[2]
        return ([(method, ask["quotaId"], ask["quotaConfig"]["preferredValue"])
                 for method, _, ask in google.asks],
                [one["machineType"] for one in google.made], lines[1:])

    def test_the_cheapest_skipped_is_asked_for_and_the_next_rented(self):
        asks, made, lines = self.rent()
        self.assertEqual((asks, made), ([("POST", FAMILY, "160")], RENTS_NEXT))
        self.assertEqual(lines[1:], [ASKED_NL])
        ask = self.google.asks[0][2]
        self.assertEqual((ask["dimensions"], ask["service"], ask["contactEmail"]), (
            NL, "compute.googleapis.com", "ak@acme-build.example"))

    def test_family_and_all_regions_both_past_are_both_asked(self):
        asks, made, lines = self.rent(quotas={"acme-build": {"CPUS_ALL_REGIONS": 164}})
        self.assertEqual(asks, [("POST", FAMILY, "160"), ("POST", ALL, "168")])
        self.assertEqual(made, ["zones/us-central1-a/machineTypes/c4a-highcpu-8"])
        self.assertEqual(self.google.asks[1][2]["dimensions"], {})
        self.assertEqual(lines[1:], [
            ASKED_NL, "CPUS_ALL_REGIONS: 168 vCPUs asked of Google, the limit now 164"])

    def test_a_region_limit_is_asked_under_its_own_id_and_found_there_again(self):
        where = {"region": "europe-west4"}
        for quotas, quota_id in (({"C4A_CPUS": 8}, "C4A-CPUS-per-project-region"),
                                 ({"CPUS": 8}, "CPUS-per-project-region")):
            with self.subTest(quota_id):
                self.rent({("us-central1", "C4A"): 24}, {"europe-west4": quotas})
                self.assertEqual(self.google.asks[0][2]["quotaId"], quota_id)
                self.assertEqual(self.google.asks[0][2]["dimensions"], where)
                asks = self.rent({("us-central1", "C4A"): 24}, {"europe-west4": quotas},
                                 [kept(quota_id, where, 86400)])[0]
                self.assertEqual(asks[0][:2], ("PATCH", quota_id))

    def test_one_asked_under_a_day_ago_passes_the_ask_to_the_next_skipped(self):
        asks, made, _ = self.rent({("europe-west4", "C4A"): 150, ("us-central1", "C4A"): 8},
                                  preferences=[kept(FAMILY, NL, 86399, reconciling=True)])
        self.assertEqual((asks, made), ([("POST", FAMILY, "16")], [
            "zones/us-central1-a/machineTypes/c4a-highcpu-8"]))
        self.assertEqual(self.google.asks[0][2]["dimensions"], US)

    def test_every_one_asked_under_a_day_ago_asks_nothing(self):
        self.assertEqual(self.rent(preferences=[kept(FAMILY, NL, 3600, reconciling=True)])[:2],
                         ([], RENTS_NEXT))

    def test_an_offer_with_one_quota_left_to_ask_takes_the_rents_ask(self):
        self.assertEqual(
            self.rent({("europe-west4", "C4A"): 150, ("us-central1", "C4A"): 0}, {
                "acme-build": {"CPUS_ALL_REGIONS": 164}},
                [kept(FAMILY, NL, 3600, reconciling=True)])[0], [("POST", ALL, "168")])

    def test_one_asked_over_a_day_ago_is_changed_by_its_etag(self):
        asks, made, _ = self.rent(preferences=[kept(FAMILY, NL, 86400, reconciling=True)])
        self.assertEqual((asks, made), ([("PATCH", FAMILY, "160")], RENTS_NEXT))
        self.assertEqual(self.google.asks[0][2]["etag"], "e7")
        self.assertEqual(self.google.preferences[0]["quotaConfig"]["preferredValue"], "160")

    def test_a_refused_or_unanswered_ask_is_a_line_and_the_next_still_asked(self):
        for code, why in ((403, "Forbidden"), (None, "")):
            with self.subTest(code):
                asks, made, lines = self.rent(quotas={"acme-build": {"CPUS_ALL_REGIONS": 164}},
                                              refusing={"POST": code})
                self.assertEqual(len(asks), 2)
                self.assertEqual(made, ["zones/us-central1-a/machineTypes/c4a-highcpu-8"])
                self.assertEqual(len(lines), 3, lines)
                self.assertTrue(lines[1].startswith(f"{ASKED_NL}: "), lines)
                self.assertIn(why, lines[1])

    def test_a_list_refused_or_unanswered_is_a_line_and_asks_nothing(self):
        for code in (403, None):
            with self.subTest(code):
                asks, made, lines = self.rent(refusing={"GET": code})
                self.assertEqual((asks, made, len(lines)), ([], RENTS_NEXT, 2), lines)
                self.assertTrue(lines[1].startswith("no quota asked for: "), lines)

    def test_a_preference_granted_short_is_a_line_with_both_numbers(self):
        for granted, numbers in (("150", "150 of the 216"), (None, "0 of the 216")):
            with self.subTest(granted):
                lines = self.rent(preferences=[kept(FAMILY, NL, 3600, "216", granted)])[2]
                self.assertEqual(lines[1:], [
                    f"C4A in europe-west4: Google granted {numbers} vCPUs asked"])

    def test_a_preference_granted_short_of_a_quota_not_skipped_is_a_line_too(self):
        lines = self.rent(preferences=[kept(FAMILY, US, 3600, "216", "24")])[2]
        self.assertEqual(lines[1:], ["C4A in us-central1: Google granted 24 of the 216 vCPUs asked",
                                     ASKED_NL])

    def test_a_preference_reconciling_or_granted_in_full_is_no_line(self):
        for one in (kept(FAMILY, NL, 3600, "216", "150", True), kept(FAMILY, NL, 3600, "150")):
            with self.subTest(one["reconciling"]):
                self.assertEqual(self.rent(preferences=[one])[2][1:], [])

    def test_a_rent_the_cap_stops_or_that_skips_nothing_asks_nothing(self):
        for kwargs in ({"cap": 1}, {"buckets": {("europe-west4", "C4A"): 1000}}):
            with self.subTest(kwargs):
                self.rent(**kwargs)
                self.assertEqual(self.google.asks, [])
                self.assertFalse([one for one in self.google.asked if QUOTAS in one])


if __name__ == "__main__":
    unittest.main()
