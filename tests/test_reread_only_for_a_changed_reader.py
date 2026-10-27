"""A new build of ak asks Artificial Analysis again before the day is up only when its reader
changed: never for an interval the board does not publish, of a share `quality` reads its error
off its task count or of Omniscience, read off its accuracy and hallucination rate; still for a
column a measure's error cannot be had without.  The board's answers faked; a throwaway HOME."""

import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
from fixtures.sandbox import Sandbox
from agentkit import boards, matrix, quality
from test_model_matrix import Boards

AA = "artificialanalysis.ai"
# What Artificial Analysis publishes of what ak reads: every measure, cost and the index, the
# intervals of Briefcase and GDPval and Omniscience's accuracy and hallucination rate
PUBLISHED = ({quality.INTEL, *quality.COSTS.values(), *quality.OMNISCIENCE[1:3]}
             | {column for role in quality.ROLES.values() for column, _, _ in role
                if column.startswith("aa.")}
             | {name for pair in quality.INTERVALS.values() for name in pair})


class RereadOnlyForAChangedReader(Sandbox):
    def setUp(self):
        super().setUp()
        self.boards = Boards()
        self.stack.enter_context(patch.object(boards, "fetch_bytes", self.boards))

    def asked_again(self, without=()):
        """Whether a new build asks Artificial Analysis again, its rows held by the build
        before it with every published column but `without`."""
        row = {"model": "Acme One", "effort": "high", "slug": "acme-one", "release": "acme-one",
               "maker": "Acme", "deprecated": False,
               "values": {column: 0.5 for column in PUBLISHED - set(without)}}
        boards.cache_path().write_text(json.dumps({AA: {
            "asked_at": 10000, "fetched_at": 10000, "rows": [row], "error": None,
            "build": "abc1234"}}))
        asked = len(self.boards.asked)
        boards.collect(now=10001, needs=matrix.needed(), build="def5678")
        return any("artificialanalysis" in url for url, _ in self.boards.asked[asked:])

    def test_a_new_build_waits_for_the_day_on_all_the_board_publishes(self):
        self.assertFalse(self.asked_again())

    def test_a_new_build_asks_again_for_what_a_measure_cannot_be_had_without(self):
        for column in ("aa.lcr", "aa.omniscienceAccuracy", "aa.gdpvalInterval.lower",
                       quality.COSTS["review"]):
            with self.subTest(column=column):
                self.assertTrue(self.asked_again(without=[column]))


if __name__ == "__main__":
    unittest.main()
