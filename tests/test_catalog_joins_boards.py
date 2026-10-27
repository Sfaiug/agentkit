"""Each current release's efforts carry every board's numbers for that release at that effort.

`catalog.current` and `catalog.successor` give each effort its Artificial Analysis row's numbers
and those of every other board's rows naming the release: the names match on letters and digits
alone, a bracket of dates and sizes dropped and an eight-digit date matching as its last four
digits; a name keeping another bracket, or matching two current releases, joins nothing.  A row
joins the effort it names, the default where it names none, else the release's only effort;
of several rows on one column the lowest is kept, with its own interval.

Offline: `catalog` is handed a `boards` dict as `boards.collect` returns it.  The models are
invented.
"""

from pathlib import Path
import sys
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import catalog


def aa(slug, model, effort, release, index, deprecated=False, replaced_by=None):
    return {"model": model, "effort": effort, "values": {"aa.intelligenceIndex": index},
            "slug": slug, "release": {"slug": release, "name": model, "deprecatedTo": replaced_by},
            "maker": "Acme", "deprecated": deprecated}


def arena(model, effort, rating, lower=None, upper=None):
    values = {"arena.webdev": rating}
    if lower is not None:
        values.update({"arena.webdev.lower95ci": lower, "arena.webdev.upper95ci": upper})
    return {"model": model, "effort": effort, "values": values}


BOARDS = {
    "artificialanalysis.ai": {"rows": [
        aa("acme-7-low", "Acme 7", "low", "acme-7", 50),
        aa("acme-7", "Acme 7", "max", "acme-7", 60),
        aa("acme-6", "Acme 6", "max", "acme-6", 40, deprecated=True, replaced_by="acme-7"),
        aa("acme-7-flash", "Acme 7 Flash 1017", "high", "acme-7-flash", 55),
        aa("beta-2", "Beta 2", "high", "beta-2", 45),
        aa("gamma-1", "Gamma 1", "low", "gamma-1", 30),
        aa("gamma-1-x", "Gamma-1", "low", "gamma-1-x", 20)]},
    "arena.ai": {"rows": [
        arena("Acme 7", "low", 1200),                         # the effort it names
        arena("acme-7", None, 1300, 1290, 1310),              # none named: the default
        arena("Acme 7 (32K, 20261101)", None, 1280, 1250, 1320),   # lower: kept, its interval
        arena("ACME 7 (2026-11-01)", None, 1290, 1285, 1295),
        arena("Acme 7 (64K 20261101)", "low", 1150),             # spaces part them too
        arena("Acme 7 (Instant)", None, 900),                 # a variant: joins nothing
        arena("Acme 7", "medium", 800),                       # no such effort, two: nothing
        arena("Acme-7-Flash-20261017", None, 1250),           # the date as its last four digits
        arena("Beta 2", "max", 1100),                         # the only effort
        arena("Gamma 1", None, 700),                          # two releases: neither
        arena("Acme 6", None, 600)]}}                         # no current release


class JoinsBoards(unittest.TestCase):
    def efforts(self, release):
        return {each["effort"]: each["values"] for each in release["efforts"]}

    def test_each_effort_carries_every_board_s_numbers_for_it(self):
        releases = {release["slug"]: release for release in catalog.current(BOARDS)}
        self.assertEqual(self.efforts(releases["acme-7"]), {
            "low": {"aa.intelligenceIndex": 50, "arena.webdev": 1150},
            "max": {"aa.intelligenceIndex": 60, "arena.webdev": 1280,
                    "arena.webdev.lower95ci": 1250, "arena.webdev.upper95ci": 1320}})
        self.assertEqual(self.efforts(releases["acme-7-flash"]),
                         {"high": {"aa.intelligenceIndex": 55, "arena.webdev": 1250}})
        self.assertEqual(self.efforts(releases["beta-2"]),
                         {"high": {"aa.intelligenceIndex": 45, "arena.webdev": 1100}})
        self.assertEqual(self.efforts(releases["gamma-1"]), {"low": {"aa.intelligenceIndex": 30}})
        self.assertEqual(self.efforts(releases["gamma-1-x"]),
                         {"low": {"aa.intelligenceIndex": 20}})

    def test_a_successor_carries_them_too(self):
        self.assertEqual(catalog.successor(BOARDS, "acme-6"),
                         next(release for release in catalog.current(BOARDS)
                              if release["slug"] == "acme-7"))

    def test_a_board_s_rows_are_left_as_they_were(self):
        before = repr(BOARDS)
        catalog.current(BOARDS)
        self.assertEqual(repr(BOARDS), before)


if __name__ == "__main__":
    unittest.main()
