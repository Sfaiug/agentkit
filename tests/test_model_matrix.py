"""`ak models` reads the three public boards once a day into `state/boards.json`.

Artificial Analysis is read off its site's pages, Arena through its dataset's pages, each of its
boards at its category, and LiveBench 2.0 off its newest release that answers; a board's
row is one model at one effort, or at none where the board names no effort; within a day nothing
is asked again, `--refresh` asks now, and a board that fails keeps its last rows with the error
beside them.  An install upgraded from before 20 Oct 2026 reads them once out of
`state/matrix.json`, where they were kept beside the matrix, whole.

Offline: the boards' answers are handed in as bytes, counted, and a throwaway HOME holds the
cache.  Artificial Analysis's pages hand their scripts the records split across two strings,
Arena's dataset answers in pages of two, its rows grouped by category as Hugging Face serves them: overall first, then the others
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

# Artificial Analysis's records on its retired model's page, and on DeepsecBench's
AA = [
    {"name": "Claude Opus 5.5 (max)", "intelligenceIndex": 58, "terminalBench40": 0.6,
     "price1mInputTokens": 4.0, "isReasoning": True, "omniscienceHallucinationRate": None,
     "briefcaseBreakdown": {"elo": 1800.0, "rubricPassRate": 0.6},    # flat, as the newest are
     "intelligenceIndexCostPerTask": {"cost": {"total": 5.98}}},
    {"name": "Claude Opus 5.5 (xhigh)", "intelligenceIndex": 56},
    {"name": "Claude Haiku 4.5 (Non-reasoning)", "intelligenceIndex": 9.0,
     "intelligenceIndexEvaluations": [{"slug": "acme-bench", "score": 0.3}]},
    {"name": "Claude Sonnet 4.6 (Thinking)", "briefcaseBreakdown": {"overall": {"elo": 1500.0}}}]
DEEPSEC = [{"name": "Claude Opus 5.5 (max)", "deepsecBench": 0.27, "intelligenceIndex": None}]
# each Arena board's rows as (model, category, the board's number, any other fields), in the
# order it serves them
ARENA = {"agent": [("Acme 9", "overall", 0.3, {"score_ci_lower": 0.25, "score_ci_upper": 0.35})],
         "agent_task_outcome_explicit": [("Claude Opus 5.5 (Max)", "overall", 0.17),
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


def aa_page(records):
    """A page of Artificial Analysis's site: each record with an id, a slug off its name, its
    release and its maker, in the data the page hands its scripts, split across two strings."""
    data = json.dumps({"models": [
        {"id": f"{n:08x}-0000-4000-8000-000000000000",
         "slug": "-".join("".join(c if c.isalnum() else " " for c in record["name"].lower()).split()),
         **record, "release": {"name": record["name"]},
         "creator": {"id": "00000000-0000-4000-8000-0000000000ac", "slug": "acme", "name": "Acme"}}
        for n, record in enumerate(records)]}, separators=(",", ":"))
    return "".join(f"<script>self.__next_f.push([1,{json.dumps(part)}])</script>"
                   for part in (data[:len(data) // 2], data[len(data) // 2:])).encode()


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
        if url in boards.AA_PAGES:
            return aa_page(DEEPSEC if "deepsec" in url else AA)
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
                                                  "rating"): n, **dict(*other)}
                for m, c, n, *other in ARENA[name]]
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

    def test_artificial_analysis_s_pages_give_each_model_s_record_whole(self):
        held = boards.collect(now=10000)
        aa = {(row["model"], row["effort"]): row["values"] for row in held["artificialanalysis.ai"]["rows"]}
        # a table's fields under its name, Briefcase's overall rating under `overall` however
        # the record gives it, and DeepsecBench's page's score merged in, its nulls never
        self.assertEqual(aa[("Claude Opus 5.5", "max")],
                         {"aa.intelligenceIndex": 58, "aa.terminalBench40": 0.6,
                          "aa.price1mInputTokens": 4.0, "aa.briefcaseBreakdown.overall.elo": 1800.0,
                          "aa.briefcaseBreakdown.rubricPassRate": 0.6,
                          "aa.intelligenceIndexCostPerTask.cost.total": 5.98,
                          "aa.deepsecBench": 0.27})
        self.assertEqual(len(aa), 4)                               # no row for the maker
        self.assertIn(("Claude Opus 5.5", "xhigh"), aa)
        self.assertIn(("Claude Haiku 4.5", "none"), aa)            # a board's words, as ak's
        self.assertEqual(aa[("Claude Sonnet 4.6", None)],          # a bracket naming no effort
                         {"aa.briefcaseBreakdown.overall.elo": 1500.0})
        self.assertEqual([url for url, _ in self.boards.asked if "artificialanalysis" in url],
                         list(boards.AA_PAGES))

    def test_each_board_s_rows_are_a_model_at_an_effort_with_its_numbers(self):
        held = boards.collect(now=10000)
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
        # a page with no model's record on it is no answer: the site changed
        with patch.object(sys.modules[__name__], "DEEPSEC", []):
            held = boards.collect(now=20000, refresh=True)
        self.assertEqual(held["artificialanalysis.ai"]["error"],
                         f"no model's record on {boards.AA_PAGES[1]}")
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

    def test_the_command_asks_the_boards_again_on_refresh(self):
        self.stack.enter_context(patch.object(config, "manifests", return_value=[]))
        with redirect_stdout(io.StringIO()):
            self.assertEqual(matrix.main([]), 0)
        self.boards.down.add("livebench.ai")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(matrix.main(["--refresh", "--json"]), 0)
        held = json.loads(boards.cache_path().read_text())["livebench.ai"]
        self.assertEqual(held["error"], "livebench.ai refused")
        self.assertEqual(held["rows"][0]["model"], "claude-opus-5.5")   # what it last said stays
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
