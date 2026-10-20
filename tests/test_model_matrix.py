"""`ak models` reads the three public boards once a day into `state/boards.json`.

Artificial Analysis is asked with the owner's key alone, Arena through its dataset's pages, each
of its boards at its category, and LiveBench 2.0 off its newest release that answers; a board's
row is one model at one effort, or at none where the board names no effort; within a day nothing
is asked again, `--refresh` asks now, and a board that fails keeps its last rows with the error
beside them.  An install upgraded from before 20 Oct 2026 reads them once out of
`state/matrix.json`, where they were kept beside the matrix, whole.

Offline: the boards' answers are handed in as bytes, counted, and a throwaway HOME holds the
cache and the key.  Artificial Analysis answers in pages of three, Arena's dataset in pages of
two, its rows grouped by category as Hugging Face serves them: overall first, then the others
in their alphabetical order.
"""

from concurrent.futures import ThreadPoolExecutor
import contextlib
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
from agentkit import boards, config, matrix

AA = [
    {"name": "Claude Opus 5.5 (max)", "evaluations": {"artificial_analysis_coding_index": 59.6},
     "pricing": {"price_1m_input_tokens": 4.0}, "performance": {"median_output_tokens_per_second": 95},
     "reasoning_model": True, "artificial_analysis_intelligence_index_cost":
         {"total_cost": 20.69, "cost_per_task": {"total_cost": 0.17}}},
    {"name": "Claude Opus 5.5 (xhigh)", "evaluations": {"artificial_analysis_coding_index": 59.6}},
    {"name": "Claude Haiku 4.5 (Non-reasoning)", "evaluations": {"artificial_analysis_coding_index": 9.0}},
    {"name": "Claude Sonnet 4.6 (Thinking)", "evaluations": {}}]
# each Arena board's rows as (model, category, the board's number), in the order it serves them
ARENA = {"agent_task_outcome_explicit": [("Claude Opus 5.5 (Max)", "overall", 0.17),
                                         ("GPT 6 Astra (xHigh)", "overall", 0.137)],
         "agent_steerability": [("Claude Opus 5.5 (Max)", "overall", 0.2)],
         "agent_bash_reliability": [("Claude Opus 5.5 (Max)", "overall", 0.1)],
         "webdev": [("Claude Opus 5.5 (Max)", "overall", 1600.0), ("Acme 8", "overall", 1500.0),
                    ("Claude Opus 5.5 (Max)", "webdev", 1590.0)],
         "text_factuality": [("Claude Opus 5.5 (Max)", "overall", 1500.0),
                             ("Claude Opus 5.5 (Max)", "chinese", 1400.0),
                             ("Claude Opus 5.5 (Max)", "coding", 1550.0),
                             ("Acme 8", "coding", 1540.0), ("Acme 9", "coding", 1400.0),
                             ("Claude Opus 5.5 (Max)", "math", 1450.0)],
         "text_style_control": [("Claude Opus 5.5 (Max)", "overall", 1510.0),
                                ("Claude Opus 5.5 (Max)", "coding", 1560.0)]}
# LiveBench 2.0 names its releases by date in its script; the v1 dates beside them are no 2.0's
SCRIPT = '_e=["20261020","20261014"],Oe=["2026-06-25"]'
TABLE = "model,coding,long_agentic\nclaude-opus-5.5,96.3,85.0\ngpt-6-astra,93.7,\n"
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
            return self.arena(url)
        if url == boards.LIVEBENCH:
            return b'<html><script defer="defer" src="./static/js/main.1.js"></script></html>'
        if url.endswith(".js"):
            return SCRIPT.encode()
        if url.endswith("data/20261014/table.csv"):
            return TABLE.encode()
        if url.endswith("data/20261014/cost.csv"):
            return COST.encode()
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)

    @staticmethod
    def arena(url):
        """The dataset's counts per category, or a page of a board's rows, at most two."""
        name = url.split("config=")[1].split("&")[0]
        rows = [{"model_name": m, "category": c, ("score" if name.startswith("agent") else
                                                  "rating"): n} for m, c, n in ARENA[name]]
        if "/statistics?" in url:
            counts = {}
            for row in rows:
                counts[row["category"]] = counts.get(row["category"], 0) + 1
            return json.dumps({"statistics": [
                {"column_name": "model_name", "column_statistics": {}},
                {"column_name": "category", "column_statistics": {"frequencies": counts}}]}).encode()
        offset, length = (int(url.split(f"&{word}=")[1].split("&")[0]) for word in ("offset", "length"))
        return json.dumps({"rows": [{"row": row} for row in rows[offset:offset + min(length, 2)]],
                           "num_rows_total": len(rows)}).encode()


class ModelBoards(Sandbox):
    def setUp(self):
        super().setUp()
        self.boards = Boards()
        self.stack.enter_context(patch.object(boards, "fetch_bytes", self.boards))
        (config.SECRETS / boards.AA_KEY).write_text("k\n")

    def test_each_board_s_rows_are_a_model_at_an_effort_with_its_numbers(self):
        held = boards.collect(now=10000)
        aa = {(row["model"], row["effort"]): row["values"] for row in held["artificialanalysis.ai"]["rows"]}
        self.assertEqual(aa[("Claude Opus 5.5", "max")],          # a table's fields under its name
                         {"aa.evaluations.artificial_analysis_coding_index": 59.6,
                          "aa.pricing.price_1m_input_tokens": 4.0,
                          "aa.performance.median_output_tokens_per_second": 95,
                          "aa.artificial_analysis_intelligence_index_cost.total_cost": 20.69,
                          "aa.artificial_analysis_intelligence_index_cost.cost_per_task.total_cost": 0.17})
        self.assertIn(("Claude Opus 5.5", "xhigh"), aa)
        self.assertIn(("Claude Haiku 4.5", "none"), aa)            # a board's words, as ak's
        self.assertIn(("Claude Sonnet 4.6", None), aa)             # a bracket naming no effort; page two
        self.assertEqual([h for u, h in self.boards.asked if "artificialanalysis" in u],
                         [{"x-api-key": "k"}] * 2)
        arena = {(row["model"], row["effort"]): row["values"] for row in held["arena.ai"]["rows"]}
        self.assertEqual(arena[("Claude Opus 5.5", "max")],     # each board at its category
                         {"arena.agent_task_outcome_explicit": 0.17, "arena.agent_steerability": 0.2,
                          "arena.agent_bash_reliability": 0.1, "arena.webdev": 1600.0,
                          "arena.text_factuality.coding": 1550.0,
                          "arena.text_style_control.coding": 1560.0})
        self.assertEqual(arena[("GPT 6 Astra", "xhigh")], {"arena.agent_task_outcome_explicit": 0.137})
        self.assertEqual(arena[("Acme 8", None)],
                         {"arena.webdev": 1500.0, "arena.text_factuality.coding": 1540.0})
        self.assertIn(("Acme 9", None), arena)                       # read past the first page
        # the coding rows are asked where the counts put them, past overall's and chinese's
        self.assertEqual([u.split("offset=")[1] for u, _ in self.boards.asked
                          if "config=text_factuality" in u and "/rows?" in u],
                         ["2&length=3", "4&length=1"])
        live = {row["model"]: row for row in held["livebench.ai"]["rows"]}
        self.assertEqual(live["claude-opus-5.5"]["effort"], None)
        self.assertEqual(live["claude-opus-5.5"]["release"], "2026-10-14")   # the newest that answers
        self.assertEqual(live["claude-opus-5.5"]["values"],
                         {"livebench.coding": 96.3, "livebench.long_agentic": 85.0,
                          boards.TASK_COST: round(113 / (29 * .963), 2)})
        self.assertEqual(live["gpt-6-astra"]["values"], {"livebench.coding": 93.7})
        self.assertTrue(any(u.endswith("data/20261020/table.csv") for u, _ in self.boards.asked))
        self.assertFalse(any("2026_06_25" in u or "2026-06-25" in u for u, _ in self.boards.asked))
        self.assertEqual(boards.split_effort("GPT 5 (Non-reasoning)"), ("GPT 5", "none"))
        self.assertEqual(boards.split_effort("Gemini 4 Argon (High)"), ("Gemini 4 Argon", "high"))
        self.assertEqual(boards.split_effort("Acme Pro (High) (0813)"), ("Acme Pro (0813)", "high"))

    def test_each_board_is_asked_once_a_day_and_a_failure_keeps_its_rows(self):
        first = boards.collect(now=10000)
        asked = len(self.boards.asked)
        self.assertEqual(boards.collect(now=10000 + boards.FRESH_FOR - 1), first)
        self.assertEqual(len(self.boards.asked), asked)          # within the day: nothing asked
        self.assertEqual(json.loads(boards.cache_path().read_text()), first)
        self.boards.down.add("datasets-server.huggingface.co")
        held = boards.collect(now=10000 + boards.FRESH_FOR)
        self.assertGreater(len(self.boards.asked), asked)
        self.assertEqual(held["arena.ai"]["error"], "datasets-server.huggingface.co refused")
        self.assertEqual(len(held["arena.ai"]["rows"]), 4)       # what it last said stays
        self.assertEqual(held["arena.ai"]["fetched_at"], 10000)
        self.assertEqual((held["livebench.ai"]["error"], held["livebench.ai"]["fetched_at"]),
                         (None, 10000 + boards.FRESH_FOR))
        asked = len(self.boards.asked)                           # a failed ask waits for the day too
        self.assertEqual(boards.collect(now=10000 + 2 * boards.FRESH_FOR - 1), held)
        self.assertEqual(len(self.boards.asked), asked)
        self.boards.down.clear()
        held = boards.collect(now=20000, refresh=True)
        self.assertIsNone(held["arena.ai"]["error"])
        self.assertGreater(len(self.boards.asked), asked)
        self.boards.down.add("data/20261014/cost.csv")           # the costs are part of the answer
        self.assertEqual(boards.collect(now=20000, refresh=True)["livebench.ai"],
                         {**held["livebench.ai"], "error": "data/20261014/cost.csv refused"})
        self.boards.down.clear()
        # rows that are not where the counts put them are no answer: the coding rows were read
        # off another category
        with patch.dict(ARENA, text_factuality=[*ARENA["text_factuality"][:2],
                                                ("Acme 9", "math", 1400.0),
                                                *ARENA["text_factuality"][2:5]]):
            self.assertEqual(boards.collect(now=20000, refresh=True)["arena.ai"],
                             {**held["arena.ai"], "error": "arena.ai: text_factuality's coding "
                                                           "rows are not where its counts put them"})
        (config.SECRETS / boards.AA_KEY).unlink()
        held = boards.collect(now=20000, refresh=True)
        self.assertEqual(held["artificialanalysis.ai"]["error"],
                         f"no key: put one in {config.SECRETS / boards.AA_KEY}")
        self.assertEqual(len(held["artificialanalysis.ai"]["rows"]), 4)

    def test_callers_at_once_share_one_collection(self):
        # were both collecting, both would reach the barrier and ask Arena twice over; the
        # second waits for the first and reads what it wrote
        self.boards.hold = threading.Barrier(2, timeout=1)
        with ThreadPoolExecutor(2) as pool:
            held = [f.result() for f in [pool.submit(boards.collect, now=10000) for _ in range(2)]]
        self.assertEqual(held[0], held[1])
        asked = sum("huggingface" in u for u, _ in self.boards.asked)
        self.boards.hold = None
        boards.collect(now=10000, refresh=True)                  # what one collection asks
        self.assertEqual(sum("huggingface" in u for u, _ in self.boards.asked), 2 * asked)

    def test_the_boards_kept_beside_the_matrix_move_whole_to_their_own_file(self):
        # until 20 Oct 2026 the boards were kept beside the matrix in `state/matrix.json`: an
        # install upgraded reads them from there once, whole, so a board down on the first ask
        # after keeps what it last said and its day goes on; the matrix's next write leaves them
        first = boards.collect(now=10000)
        matrix.cache_path().write_text(json.dumps({**first, "matrix": {"rows": []}}))
        boards.cache_path().unlink()
        hosts = ("artificialanalysis.ai", "datasets-server.huggingface.co", "livebench.ai")
        self.boards.down.update(hosts)
        asked = len(self.boards.asked)
        self.assertEqual(boards.collect(now=10000 + boards.FRESH_FOR - 1), first)
        self.assertEqual(len(self.boards.asked), asked)
        self.assertEqual(boards.collect(now=10000 + boards.FRESH_FOR),
                         {board: {**first[board], "asked_at": 10000 + boards.FRESH_FOR,
                                  "error": f"{host} refused"}
                          for board, host in zip(boards.BOARDS, hosts)})
        self.stack.enter_context(patch.object(config, "manifests", return_value=[]))
        matrix.refresh(self.cfg, now=10000 + boards.FRESH_FOR)
        self.assertEqual(list(json.loads(matrix.cache_path().read_text())), ["matrix"])

    def test_the_command_says_what_each_board_gave_and_when(self):
        self.stack.enter_context(patch.object(config, "manifests", return_value=[]))
        with patch.object(matrix.time, "time", return_value=10000):
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(matrix.main([]), 0)
        lines = out.getvalue().splitlines()[-3:]             # the last lines of the screen
        self.assertEqual([line.split(":")[0] for line in lines], list(boards.BOARDS))
        self.assertRegex(lines[0], r"^artificialanalysis\.ai: 4 rows as of \d\d \w\w\w \d\d:\d\d$")
        self.boards.down.add("livebench.ai")
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(matrix.main(["--refresh", "--json"]), 0)
        held = json.loads(out.getvalue())["boards"]
        self.assertEqual(sorted(held), sorted(boards.BOARDS))
        self.assertEqual(held["livebench.ai"]["error"], "livebench.ai refused")
        self.assertEqual(json.loads(boards.cache_path().read_text())["livebench.ai"]["rows"][0]["model"],
                         "claude-opus-5.5")                      # what it last said stays
        out = io.StringIO()
        with redirect_stdout(out):
            matrix.main([])
        self.assertIn("livebench.ai: 2 rows as of", out.getvalue())
        self.assertIn("note: livebench.ai refused", out.getvalue())
        with self.assertRaises(config.Error):
            matrix.main(["--all"])


class Asking(unittest.TestCase):
    """The one network call, on a fake clock: what it waited, and what each ask answered."""
    def setUp(self):
        self.now, self.slept, self.answers = 100.0, [], []
        clock = self

        class Time:
            @staticmethod
            def monotonic():
                return clock.now

            @staticmethod
            def sleep(seconds):
                clock.slept.append(seconds)
                clock.now += seconds

        def urlopen(request, timeout):
            answer = self.answers.pop(0)
            if isinstance(answer, int):
                raise urllib.error.HTTPError(request.full_url, answer, "refused", {}, None)
            return contextlib.nullcontext(io.BytesIO(answer))
        for patched in (patch.object(boards, "time", Time), patch.dict(boards._ASKED, clear=True),
                        patch.object(boards.urllib.request, "urlopen", urlopen)):
            patched.start()
            self.addCleanup(patched.stop)

    def test_a_host_is_asked_at_its_pace_and_after_a_server_error_again(self):
        self.answers[:] = [502, 503, b"rows"]
        self.assertEqual(boards.fetch_bytes("https://acme.example/a"), b"rows")
        self.assertEqual(self.slept, [0.0, 2, 0.0, 4, 0.0])      # the waits after each error
        self.answers[:] = [404]                                  # a refusal is the answer
        with self.assertRaises(urllib.error.HTTPError):
            boards.fetch_bytes("https://acme.example/b")
        self.assertEqual(self.slept[5:], [1.0])                  # asked a second later
        self.answers[:] = [b"other"]
        self.assertEqual(boards.fetch_bytes("https://other.example/"), b"other")
        self.assertEqual(self.slept[6:], [0.0])                  # another host waits for none
        self.answers[:] = [500, 500, 500]
        with self.assertRaises(urllib.error.HTTPError):          # the third error is the answer
            boards.fetch_bytes("https://acme.example/c")
        self.assertEqual(self.answers, [])


if __name__ == "__main__":
    unittest.main()
