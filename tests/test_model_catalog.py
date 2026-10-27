"""ak knows Artificial Analysis's current models, and what replaced each older one.

Each of the board's rows keeps its record's identity beside its numbers; `catalog.current` gives
the releases none of whose rows is deprecated, strongest first, each with its efforts, the
default one and each one's numbers, and `catalog.successor` follows a release's `deprecatedTo` chain to the current
release it ends at.  A series, one maker's releases of one release name, whose deprecated releases
name a successor takes its current variants along.  A reading an older build stored, its rows
carrying no identity, is asked again once by this build, and until then nothing is current.

Offline: the board's pages are handed in through `boards.fetch_bytes`, the other boards refuse,
and a throwaway HOME holds the cache.  The models are invented.
"""

import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
from fixtures.sandbox import Sandbox
from agentkit import boards, catalog

# (row slug, row name, release slug, release name, maker, deprecated, deprecatedTo, index)
RECORDS = [
    ("acme-7-low", "Acme 7 (Low)", "acme-7", "Acme 7", "Acme", False, None, 50),
    ("acme-7", "Acme 7 (Max)", "acme-7", "Acme 7", "Acme", False, None, 60),
    ("acme-6", "Acme 6 (Max)", "acme-6", "Acme 6", "Acme", True, "acme-6-5", 40),
    ("acme-6-5", "Acme 6.5 (Max)", "acme-6-5", "Acme 6.5", "Acme", True, "acme-7", 45),
    ("beta-3", "Beta 3 (Non-reasoning)", "beta-3", "Beta 3", "Beta", False, None, 30),
    ("beta-3-high", "Beta 3 (High)", "beta-3", "Beta 3", "Beta", False, None, 62),
    ("beta-2", "Beta 2 (High)", "beta-2", "Beta 2", "Beta", False, "beta-3", 20),
    ("beta-2-low", "Beta 2 (Low)", "beta-2", "Beta 2", "Beta", True, "beta-3", 15),
    ("gamma-1", "Gamma 1", "gamma-1", "Gamma 1", "Gamma", False, None, None),
    ("delta-1-preview", "Delta 1 Preview", "delta-1", "Delta 1", "Delta", False, None, None),
    ("omega-1", "Omega 1", "omega-1", "Omega 1", "Omega", True, "omega-2", 10),
    ("omega-0", "Omega 0", "omega-0", "Omega 0", "Omega", True, None, 5),
    ("loop-a", "Loop A", "loop-a", "Loop A", "Loop", True, "loop-b", 1),
    ("loop-b", "Loop B", "loop-b", "Loop B", "Loop", True, "loop-a", 1)]


def page(records):
    """A page of the board's site: each record, its index's evaluations listed, in the data the
    page hands its scripts."""
    data = json.dumps({"models": [
        {"id": f"{n:08x}-0000-4000-8000-000000000000", "slug": slug, "name": name,
         "intelligenceIndex": index, "deprecated": deprecated,
         "intelligenceIndexEvaluations": [{"slug": "acme-bench", "score": index}],
         "release": {"slug": release, "name": release_name, "deprecatedTo": replaced_by},
         "creator": {"id": "00000000-0000-4000-8000-0000000000ac", "name": maker}}
        for n, (slug, name, release, release_name, maker, deprecated, replaced_by, index)
        in enumerate(records)]}, separators=(",", ":"))
    return f"<script>self.__next_f.push([1,{json.dumps(data)}])</script>".encode()


class Catalog(Sandbox):
    def setUp(self):
        super().setUp()
        self.asked = []
        self.stack.enter_context(patch.object(boards, "fetch_bytes", self.fetch))

    def fetch(self, url, headers=None):
        self.asked.append(url)
        if url not in boards.AA_PAGES:
            raise OSError("refused")
        return page(RECORDS[:8] if url == boards.AA_PAGES[0] else RECORDS[8:])

    def aa_asks(self):
        return sum(url in boards.AA_PAGES for url in self.asked)

    def test_each_row_keeps_its_record_s_identity_beside_its_numbers(self):
        rows = {row["slug"]: row for row in boards.collect(now=10000)[catalog.BOARD]["rows"]}
        self.assertEqual(rows["acme-6"], {
            "model": "Acme 6", "effort": "max", "values": {"aa.intelligenceIndex": 40,
                                                       "aa.intelligenceIndexEvaluations.acme-bench.score": 40},
            "slug": "acme-6", "release": {"slug": "acme-6", "name": "Acme 6",
                                          "deprecatedTo": "acme-6-5"},
            "maker": "Acme", "deprecated": True})
        self.assertEqual((rows["gamma-1"]["values"], rows["gamma-1"]["deprecated"]), ({}, False))

    def test_the_current_releases_strongest_first_each_with_its_efforts(self):
        held = boards.collect(now=10000)
        aa = lambda index: {"aa.intelligenceIndex": index,
                            "aa.intelligenceIndexEvaluations.acme-bench.score": index}
        self.assertEqual(catalog.current(held), [
            {"slug": "beta-3", "name": "Beta 3", "maker": "Beta",
             "efforts": [{"effort": "none", "slug": "beta-3", "default": True, "values": aa(30)},
                         {"effort": "high", "slug": "beta-3-high", "default": False,
                          "values": aa(62)}]},
            {"slug": "acme-7", "name": "Acme 7", "maker": "Acme",
             "efforts": [{"effort": "low", "slug": "acme-7-low", "default": False,
                          "values": aa(50)},
                         {"effort": "max", "slug": "acme-7", "default": True, "values": aa(60)}]},
            # no index: last, by name; a release with no row of its own slug has no default
            {"slug": "delta-1", "name": "Delta 1", "maker": "Delta",
             "efforts": [{"effort": None, "slug": "delta-1-preview", "default": False,
                          "values": {}}]},
            {"slug": "gamma-1", "name": "Gamma 1", "maker": "Gamma",
             "efforts": [{"effort": None, "slug": "gamma-1", "default": True, "values": {}}]}])

    def test_a_release_s_successor_is_the_current_release_its_chain_ends_at(self):
        held = boards.collect(now=10000)
        successor = lambda slug: (catalog.successor(held, slug) or {}).get("slug")
        self.assertEqual(successor("acme-6"), "acme-7")              # through Acme 6.5
        self.assertEqual(successor("acme-7"), "acme-7")              # current: itself
        self.assertEqual(successor("beta-2"), "beta-3")              # one row deprecated is enough
        self.assertEqual(catalog.successor(held, "beta-2"), catalog.current(held)[0])
        for slug in ("omega-1", "omega-0", "loop-a", "nowhere", "acme-7-low"):
            self.assertIsNone(successor(slug), slug)

    def test_a_series_goes_for_the_successor_a_deprecated_release_of_it_names(self):
        series = [      # a series: one maker's releases of one release name
            # Acme 6.5's chain leaves it for Acme 7, and takes its variant along, with the
            # release Acme 5 replaced by that variant; a retired Acme 7 preview names none
            ("acme-6-5-fast", "Acme 6.5 (Fast)", "acme-6-5-fast", "Acme 6.5", "Acme", False, None, 44),
            ("acme-5", "Acme 5", "acme-5", "Acme 5", "Acme", True, "acme-6-5-fast", 30),
            ("acme-7-preview", "Acme 7 (Preview)", "acme-7-preview", "Acme 7", "Acme", True, None, 55),
            # one row naming the successor is enough, whichever row comes first
            ("kappa-6-max", "Kappa 6 (Max)", "kappa-6", "Kappa 6", "Kappa", True, None, 21),
            ("kappa-6", "Kappa 6 (High)", "kappa-6", "Kappa 6", "Kappa", True, "kappa-7", 20),
            ("kappa-6-blue", "Kappa 6 (Blue, max)", "kappa-6-blue", "Kappa 6", "Kappa", False, None, None),
            ("kappa-7", "Kappa 7", "kappa-7", "Kappa 7", "Kappa", False, None, 25),
            # a successor named inside the series stays, and takes its siblings
            ("zeta-1-old", "Zeta 1", "zeta-1-old", "Zeta 1", "Zeta", True, "zeta-1", 8),
            ("zeta-1", "Zeta 1", "zeta-1", "Zeta 1", "Zeta", False, None, 9),
            ("zeta-1-fast", "Zeta 1 (Fast)", "zeta-1-fast", "Zeta 1", "Zeta", False, None, 7),
            # but not once another of its releases leads outside it
            ("nu-6-early", "Nu 6 (Early)", "nu-6-early", "Nu 6", "Nu", True, "nu-6-fast", 11),
            ("nu-6", "Nu 6", "nu-6", "Nu 6", "Nu", True, "nu-7", 12),
            ("nu-6-fast", "Nu 6 (Fast)", "nu-6-fast", "Nu 6", "Nu", False, None, 13),
            ("nu-7", "Nu 7", "nu-7", "Nu 7", "Nu", False, None, 14),
            # chains ending nowhere and successors that disagree take their series with no successor
            ("omega-1-fast", "Omega 1 (Fast)", "omega-1-fast", "Omega 1", "Omega", False, None, 6),
            ("loop-a-fast", "Loop A (Fast)", "loop-a-fast", "Loop A", "Loop", False, None, 2),
            ("xi-1-a", "Xi 1 (A)", "xi-1-a", "Xi 1", "Xi", True, "xi-2", 3),
            ("xi-1-b", "Xi 1 (B)", "xi-1-b", "Xi 1", "Xi", True, "xi-3", 3),
            ("xi-1-fast", "Xi 1 (Fast)", "xi-1-fast", "Xi 1", "Xi", False, None, 3),
            ("xi-2", "Xi 2", "xi-2", "Xi 2", "Xi", False, None, 4),
            ("xi-3", "Xi 3", "xi-3", "Xi 3", "Xi", False, None, 5),
            # a series naming no successor stays as it is: the board shows a retired model
            # beside its variant as it shows a retired preview beside its model
            ("omega-0-fast", "Omega 0 (Fast)", "omega-0-fast", "Omega 0", "Omega", False, None, 6),
            # another maker's release of the same name is another series
            ("acme-nova-1", "Nova 1", "acme-nova-1", "Nova 1", "Acme", True, "acme-nova-2", 16),
            ("acme-nova-2", "Nova 2", "acme-nova-2", "Nova 2", "Acme", False, None, 18),
            ("beta-nova-1", "Nova 1", "beta-nova-1", "Nova 1", "Beta", False, None, 17)]
        for records in (RECORDS + series, RECORDS + series[::-1]):
            with patch(f"{__name__}.RECORDS", records):
                held = boards.collect(refresh=True, now=10000)
            self.assertEqual([release["slug"] for release in catalog.current(held)], [
                "beta-3", "acme-7", "kappa-7", "acme-nova-2", "beta-nova-1", "nu-7", "zeta-1",
                "omega-0-fast", "xi-3", "xi-2", "delta-1", "gamma-1"])
            successors = {slug: (catalog.successor(held, slug) or {}).get("slug") for slug in (
                "acme-6-5-fast", "acme-5", "acme-7-preview", "kappa-6", "kappa-6-blue",
                "zeta-1-old", "zeta-1-fast", "nu-6-early", "nu-6-fast", "omega-1-fast",
                "loop-a-fast", "xi-1-fast", "omega-0-fast", "beta-nova-1")}
            self.assertEqual(successors, {
                "acme-6-5-fast": "acme-7", "acme-5": "acme-7", "acme-7-preview": None,
                "kappa-6": "kappa-7", "kappa-6-blue": "kappa-7", "zeta-1-old": "zeta-1",
                "zeta-1-fast": "zeta-1", "nu-6-early": "nu-7", "nu-6-fast": "nu-7",
                "omega-1-fast": None, "loop-a-fast": None, "xi-1-fast": None,
                "omega-0-fast": "omega-0-fast", "beta-nova-1": "beta-nova-1"})

    def test_a_reading_an_older_build_stored_is_asked_again_once(self):
        boards.collect(now=10000, build="abc1234")
        cache = json.loads(boards.cache_path().read_text())
        for row in cache[catalog.BOARD]["rows"]:        # rows as an older reader gave them
            for field in boards.IDENTITY[catalog.BOARD]:
                row.pop(field)
        boards.cache_path().write_text(json.dumps(cache))
        asked = self.aa_asks()
        held = boards.collect(now=10001, build="abc1234")   # the build that read it waits
        self.assertEqual(self.aa_asks(), asked)
        self.assertEqual(catalog.current(held), [])
        held = boards.collect(now=10001, build="def5678")
        self.assertEqual(self.aa_asks(), 2 * asked)
        self.assertEqual(len(catalog.current(held)), 4)
        boards.collect(now=10002, build="ghi9012")          # once: its rows carry it now
        self.assertEqual(self.aa_asks(), 2 * asked)


if __name__ == "__main__":
    unittest.main()
