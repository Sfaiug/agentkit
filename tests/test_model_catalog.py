"""ak knows Artificial Analysis's current models, and what replaced each older one.

Each of the board's rows keeps its record's identity beside its numbers; `catalog.current` gives
the releases nothing replaced, strongest first, each with its efforts, the default one and each
one's numbers, and `catalog.successor` follows what replaced a release, a variant listed under a
replaced release's name replaced with it, to the current release it ends at.  A reading an older
build stored, its rows carrying no identity, is asked again once by this build, and until then
nothing is current.

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

    def test_a_variant_listed_under_a_replaced_release_s_name_is_replaced_with_it(self):
        records = RECORDS + [     # the newest listed anew under a name, and rows that disagree
            ("acme-6-5-fast", "Acme 6.5 (Fast)", "acme-6-5-fast", "Acme 6.5", "Acme", False, None, 44),
            ("acme-5", "Acme 5", "acme-5", "Acme 5", "Acme", True, "acme-6-5-fast", 30),
            ("omega-0-fast", "Omega 0 (Fast)", "omega-0-fast", "Omega 0", "Omega", False, None, 6),
            ("zeta-1-old", "Zeta 1", "zeta-1-old", "Zeta 1", "Zeta", True, "zeta-1", 8),
            ("zeta-1-retired", "Zeta 1", "zeta-1-retired", "Zeta 1", "Zeta", True, None, 7),
            ("zeta-1", "Zeta 1", "zeta-1", "Zeta 1", "Zeta", False, None, 9),
            ("eta-1", "Eta 1", "eta-1", "Eta 1", "Eta", True, None, 3),
            ("eta-1-low", "Eta 1 (Low)", "eta-1", "Eta 1", "Eta", True, "zeta-1", 2),
            ("gamma-1-preview", "Gamma 1 (Preview)", "gamma-1-preview", "Gamma 1", "Gamma", True,
             None, None),          # retired with nothing in its place, beside a named successor
            ("gamma-0", "Gamma 0", "gamma-0", "Gamma 0", "Gamma", True, "gamma-1", None),
            ("omega-00", "Omega 00", "omega-00", "Omega 00", "Omega", True, "omega-0-fast", 4)]
        with patch(f"{__name__}.RECORDS", records):
            held = boards.collect(now=10000)
        self.assertEqual([release["slug"] for release in catalog.current(held)],
                         ["beta-3", "acme-7", "zeta-1", "delta-1", "gamma-1"])
        self.assertEqual([(catalog.successor(held, slug) or {}).get("slug") for slug in (
            "acme-6-5-fast", "acme-5", "omega-0-fast", "zeta-1-old", "eta-1", "gamma-0",
            "omega-00")],
            ["acme-7", "acme-7", None, "zeta-1", "zeta-1", "gamma-1", None])

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
