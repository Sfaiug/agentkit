"""`boards.collect` asks only what ak rates models on: Artificial Analysis, and of Arena exactly
the boards whose columns `matrix.needed()` names, a measure added on another board read with it;
a board an older build kept, LiveBench's, leaves `state/boards.json` at the next collection.
The boards' answers are faked; a throwaway HOME."""

import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
from fixtures.sandbox import Sandbox
from agentkit import boards, matrix, quality
from test_model_matrix import Boards


class ReadWhatIsRated(Sandbox):
    def setUp(self):
        super().setUp()
        self.boards = Boards()
        self.stack.enter_context(patch.object(boards, "fetch_bytes", self.boards))

    def asked(self):
        """(hosts asked, Arena boards asked) by the collections so far."""
        urls = [urlsplit(url) for url, _ in self.boards.asked]
        return ({url.netloc for url in urls},
                {parse_qs(url.query)["config"][0] for url in urls if "huggingface" in url.netloc})

    def test_one_collection_asks_artificial_analysis_and_the_arena_boards_rated_on(self):
        held = boards.collect(now=10000)
        rated = {column.split(".")[1] for column in matrix.needed()["arena.ai"]}
        self.assertEqual(rated, {"agent"})
        self.assertEqual(self.asked(), ({"artificialanalysis.ai", "datasets-server.huggingface.co"},
                                        rated))
        self.assertEqual(sorted(held), ["arena.ai", "artificialanalysis.ai"])

    def test_a_measure_on_another_arena_board_is_read_with_it(self):
        factuality = ("arena.text_factuality.coding", "rating", 0.1,
                      "coding answers judged for facts")
        with patch.dict(quality.ROLES, review=(*quality.ROLES["review"], factuality)):
            held = boards.collect(now=10000)
        self.assertEqual(self.asked()[1], {"agent", "text_factuality"})
        self.assertIn("arena.text_factuality.coding",
                      {column for row in held["arena.ai"]["rows"] for column in row["values"]})

    def test_an_older_build_s_livebench_board_is_gone_after_one_collection(self):
        held = boards.collect(now=10000)
        boards.cache_path().write_text(json.dumps({**held, "livebench.ai": {
            "asked_at": 10000, "fetched_at": 10000, "error": None, "build": "abc1234",
            "rows": [{"model": "acme-7", "effort": None, "values": {"livebench.coding": 70.0}}]}}))
        asked = len(self.boards.asked)
        self.assertEqual(boards.collect(now=10001), held)            # within the day: asks nothing
        self.assertEqual(len(self.boards.asked), asked)
        self.assertEqual(json.loads(boards.cache_path().read_text()), held)


if __name__ == "__main__":
    unittest.main()
