"""`ak models` reads the three public boards once a day into `state/matrix.json`.

Artificial Analysis is asked with the owner's key alone, Arena Agent through its dataset's pages
and LiveBench off its newest release that answers; a board's row is one model at one effort, or
at none where the board names no effort; within a day nothing is asked again, `--refresh` asks
now, and a board that fails keeps its last rows with the error beside them.

Offline: the boards' answers are handed in as bytes, counted, and a throwaway HOME holds the
cache and the key.  Artificial Analysis answers in pages of three.
"""

from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch
import urllib.error

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
from fixtures.sandbox import Sandbox
from agentkit import config, matrix

AA = [
    {"name": "Claude Opus 5.5 (max)", "evaluations": {"terminalbench_v4_0": 59.6},
     "pricing": {"price_1m_input_tokens": 4.0}, "median_output_tokens_per_second": 95,
     "reasoning_model": True, "artificial_analysis_intelligence_index_cost":
         {"total_cost": 20.69, "cost_per_task": {"total_cost": 0.17}}},
    {"name": "Claude Opus 5.5 (xhigh)", "evaluations": {"terminalbench_v4_0": 59.6}},
    {"name": "Claude Haiku 4.5 (Non-reasoning)", "evaluations": {"terminalbench_v4_0": 9.0}},
    {"name": "Claude Sonnet 4.6 (Thinking)", "evaluations": {}}]
ARENA = {"agent": [("Claude Opus 5.5 (Max)", 0.17), ("GPT 6 Astra (xHigh)", 0.137)],
         "agent_steerability": [("Claude Opus 5.5 (Max)", 0.2)]}
SCRIPT = 'x="2026-10-13";y="2026-09-02"'
TABLE = "model,coding,long_horizon\nclaude-opus-5.5,96.3,85.0\ngpt-6-astra,93.7,\n"
COST = "model,coding,nq_coding\nclaude-opus-5.5,113.0,29\ngpt-6-astra,,29\n"


class Boards:
    """The three boards' answers, as bytes per URL, counting the asks."""
    def __init__(self):
        self.asked = []
        self.down = set()           # parts of a URL that refuse
        self.hold = None            # a barrier every Arena ask waits at

    def __call__(self, url, headers=None):
        self.asked.append((url, headers or {}))
        for part in self.down:
            if part in url:
                raise OSError(f"{part} refused")
        if "artificialanalysis" in url:
            page = int(url.rsplit("page=", 1)[1])
            return json.dumps({"pagination": {"has_more": page * 3 < len(AA)},
                               "data": AA[(page - 1) * 3:page * 3]}).encode()
        if "huggingface" in url:
            if self.hold:
                try:
                    self.hold.wait()
                except threading.BrokenBarrierError:
                    pass
            name = url.split("config=")[1].split("&")[0]
            rows = [{"row": {"model_name": m, "score": s}} for m, s in ARENA[name]]
            return json.dumps({"rows": rows, "num_rows_total": len(rows)}).encode()
        if url == matrix.LIVEBENCH:
            return b'<html><script defer="defer" src="./static/js/main.1.js"></script></html>'
        if url.endswith(".js"):
            return SCRIPT.encode()
        if url.endswith("table_2026_09_02.csv"):
            return TABLE.encode()
        if url.endswith("cost_2026_09_02.csv"):
            return COST.encode()
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)


class ModelBoards(Sandbox):
    def setUp(self):
        super().setUp()
        self.boards = Boards()
        self.stack.enter_context(patch.object(matrix, "fetch_bytes", self.boards))
        (config.SECRETS / matrix.AA_KEY).write_text("k\n")

    def test_each_board_s_rows_are_a_model_at_an_effort_with_its_numbers(self):
        held = matrix.collect(now=10000)
        aa = {(row["model"], row["effort"]): row["values"] for row in held["artificialanalysis.ai"]["rows"]}
        self.assertEqual(aa[("Claude Opus 5.5", "max")],          # a table's fields under its name
                         {"aa.evaluations.terminalbench_v4_0": 59.6,
                          "aa.pricing.price_1m_input_tokens": 4.0,
                          "aa.median_output_tokens_per_second": 95,
                          "aa.artificial_analysis_intelligence_index_cost.total_cost": 20.69,
                          "aa.artificial_analysis_intelligence_index_cost.cost_per_task.total_cost": 0.17})
        self.assertIn(("Claude Opus 5.5", "xhigh"), aa)
        self.assertIn(("Claude Haiku 4.5", "none"), aa)            # a board's words, as ak's
        self.assertIn(("Claude Sonnet 4.6", None), aa)             # a bracket naming no effort; page two
        self.assertEqual([h for u, h in self.boards.asked if "artificialanalysis" in u],
                         [{"x-api-key": "k"}] * 2)
        arena = {(row["model"], row["effort"]): row["values"] for row in held["arena.ai"]["rows"]}
        self.assertEqual(arena[("Claude Opus 5.5", "max")],
                         {"arena.agent": 0.17, "arena.agent_steerability": 0.2})
        self.assertEqual(arena[("GPT 6 Astra", "xhigh")], {"arena.agent": 0.137})
        live = {row["model"]: row for row in held["livebench.ai"]["rows"]}
        self.assertEqual(live["claude-opus-5.5"]["effort"], None)
        self.assertEqual(live["claude-opus-5.5"]["release"], "2026-09-02")   # the newest that answers
        self.assertEqual(live["claude-opus-5.5"]["values"],
                         {"livebench.coding": 96.3, "livebench.long_horizon": 85.0,
                          matrix.COST: round(113 / (29 * .963), 2)})
        self.assertEqual(live["gpt-6-astra"]["values"], {"livebench.coding": 93.7})
        self.assertTrue(any(u.endswith("table_2026_10_13.csv") for u, _ in self.boards.asked))
        self.assertEqual(matrix.split_effort("GPT 5 (Non-reasoning)"), ("GPT 5", "none"))
        self.assertEqual(matrix.split_effort("Gemini 4 Argon (High)"), ("Gemini 4 Argon", "high"))
        self.assertEqual(matrix.split_effort("Acme Pro (High) (0813)"), ("Acme Pro (0813)", "high"))

    def test_each_board_is_asked_once_a_day_and_a_failure_keeps_its_rows(self):
        first = matrix.collect(now=10000)
        asked = len(self.boards.asked)
        self.assertEqual(matrix.collect(now=10000 + matrix.FRESH_FOR - 1), first)
        self.assertEqual(len(self.boards.asked), asked)          # within the day: nothing asked
        self.assertEqual(json.loads(matrix.cache_path().read_text()), first)
        self.boards.down.add("datasets-server.huggingface.co")
        held = matrix.collect(now=10000 + matrix.FRESH_FOR)
        self.assertGreater(len(self.boards.asked), asked)
        self.assertEqual(held["arena.ai"]["error"], "datasets-server.huggingface.co refused")
        self.assertEqual(len(held["arena.ai"]["rows"]), 2)       # what it last said stays
        self.assertEqual(held["arena.ai"]["fetched_at"], 10000)
        self.assertEqual((held["livebench.ai"]["error"], held["livebench.ai"]["fetched_at"]),
                         (None, 10000 + matrix.FRESH_FOR))
        asked = len(self.boards.asked)                           # a failed ask waits for the day too
        self.assertEqual(matrix.collect(now=10000 + 2 * matrix.FRESH_FOR - 1), held)
        self.assertEqual(len(self.boards.asked), asked)
        self.boards.down.clear()
        held = matrix.collect(now=20000, refresh=True)
        self.assertIsNone(held["arena.ai"]["error"])
        self.assertGreater(len(self.boards.asked), asked)
        self.boards.down.add("cost_2026_09_02")                  # the costs are part of the answer
        self.assertEqual(matrix.collect(now=20000, refresh=True)["livebench.ai"],
                         {**held["livebench.ai"], "error": "cost_2026_09_02 refused"})
        self.boards.down.clear()
        (config.SECRETS / matrix.AA_KEY).unlink()
        held = matrix.collect(now=20000, refresh=True)
        self.assertEqual(held["artificialanalysis.ai"]["error"],
                         f"no key: put one in {config.SECRETS / matrix.AA_KEY}")
        self.assertEqual(len(held["artificialanalysis.ai"]["rows"]), 4)

    def test_callers_at_once_share_one_collection(self):
        # were both collecting, both would reach the barrier and ask Arena twice over; the
        # second waits for the first and reads what it wrote
        self.boards.hold = threading.Barrier(2, timeout=1)
        with ThreadPoolExecutor(2) as pool:
            held = [f.result() for f in [pool.submit(matrix.collect, now=10000) for _ in range(2)]]
        self.assertEqual(held[0], held[1])
        self.assertEqual(sum("huggingface" in u for u, _ in self.boards.asked),
                         len(matrix.ARENA_CONFIGS))

    def test_the_command_says_what_each_board_gave_and_when(self):
        with patch.object(matrix.time, "time", return_value=10000):
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(matrix.main([]), 0)
        lines = out.getvalue().splitlines()
        self.assertEqual([line.split(":")[0] for line in lines], list(matrix.BOARDS))
        self.assertRegex(lines[0], r"^artificialanalysis\.ai: 4 rows as of \d\d \w\w\w \d\d:\d\d$")
        self.boards.down.add("livebench.ai")
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(matrix.main(["--refresh", "--json"]), 0)
        held = json.loads(out.getvalue())
        self.assertEqual(sorted(held), sorted(matrix.BOARDS))
        self.assertEqual(held["livebench.ai"]["error"], "livebench.ai refused")
        self.assertEqual(len(held["livebench.ai"]["rows"]), 2)
        out = io.StringIO()
        with redirect_stdout(out):
            matrix.main([])
        self.assertIn("livebench.ai: 2 rows as of", out.getvalue())
        self.assertIn("note: livebench.ai refused", out.getvalue())
        with self.assertRaises(config.Error):
            matrix.main(["--all"])


if __name__ == "__main__":
    unittest.main()
