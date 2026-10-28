"""Another board's row whose name holds a bracketed date joins the current release whose name
holds that date, as eight digits or their last four; only where no current release's does it
join by its name without those brackets.

Offline: `catalog` is handed a `boards` dict as `boards.collect` returns it.  The models are
invented.
"""

from pathlib import Path
import sys
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import catalog


def aa(slug, model, index):
    return {"model": model, "effort": "high", "values": {"aa.intelligenceIndex": index},
            "slug": slug, "release": {"slug": slug, "name": model, "deprecatedTo": None},
            "maker": "Acme", "deprecated": False}


def arena(model, rating):
    return {"model": model, "effort": None, "values": {"arena.webdev": rating}}


def joined(aa_rows, arena_rows):
    """{release slug: its Arena number, None where it has none}."""
    return {release["slug"]: release["efforts"][0]["values"].get("arena.webdev")
            for release in catalog.current({"artificialanalysis.ai": {"rows": aa_rows},
                                            "arena.ai": {"rows": arena_rows}})}


class DatedBoardNames(unittest.TestCase):
    def test_a_dated_row_joins_the_release_of_its_date(self):
        self.assertEqual(joined(
            [aa("acme-max", "Acme3.8 Max", 50), aa("acme-max-0902", "Acme3.8 Max (0902)", 60),
             aa("beta-pro", "Beta V4 Pro", 40), aa("beta-pro-0813", "Beta V4 Pro 0813", 55),
             aa("gamma", "Gamma 2", 30), aa("gamma-0101", "Gamma 2 20260101", 35)],
            [arena("Acme3.8-Max (0902)", 1300), arena("Beta-V4-Pro (20260813)", 1200),
             arena("Gamma 2 (32K, 2026-01-01)", 1100)]),
            {"acme-max-0902": 1300, "acme-max": None, "beta-pro-0813": 1200, "beta-pro": None,
             "gamma-0101": 1100, "gamma": None})

    def test_without_a_release_of_its_date_it_joins_by_its_undated_name(self):
        self.assertEqual(joined([aa("acme-max", "Acme3.8 Max", 50),
                                 aa("acme-max-0101", "Acme3.8 Max (0101)", 45)],
                                [arena("Acme3.8-Max (0902)", 1300)]),
                         {"acme-max": 1300, "acme-max-0101": None})


if __name__ == "__main__":
    unittest.main()
