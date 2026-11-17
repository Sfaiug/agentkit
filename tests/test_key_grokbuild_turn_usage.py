"""A Grok Build worker turn's tokens are kept by type, and its login's spend priced from them.

Grok Build's stream closes on a `result` whose `usage` counts the turn's own input, cache write,
cache read and output, its cached input beside its input, and whose `modelUsage` repeats them
under a name of Grok's own (`<model>-build`) that no board lists.  The turn's `turn_usage` row in
history.db holds the `result`'s four counts under the model its entry launched it with, and
`ak usage --json` prices the login's `listed_usd` from that row.  Black-box: AK_BIN runs a task
through tests/fixtures/akbin.py on a fake harness configured as `grokbuild`, whose events are in
the shape `grok --output-format streaming-messages-json` writes them, an invented board in its
Home, and history.db is read with sqlite3.
"""

import json
from pathlib import Path
import sqlite3
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.gitrig import Rig

OWNERS = {"AK_NOTIFY_SINK": None}
TYPES = ("input", "cache_write", "cache_read", "output")
SESSION = "0b7e4c1a-acme-4f00-9a11-000000000001"
# the turn's input, cache write, cache read and output
COUNTS = (1_000_000, 200_000, 3_000_000, 100_000)


def usage(fresh, written, cached, output):
    return {"input_tokens": fresh, "output_tokens": output, "cache_read_input_tokens": cached,
            "cache_creation_input_tokens": written}


# A model call's message, then the turn's `result`, as tests/fixtures/grok-events.jsonl has them.
EVENTS = "".join(json.dumps(event) + "\n" for event in (
    {"type": "system", "subtype": "init", "session_id": SESSION, "model": "acme-4-build"},
    {"type": "assistant", "session_id": SESSION, "message": {
        "id": "msg_0", "type": "message", "role": "assistant", "model": "acme-4-build",
        "content": [{"type": "text", "text": "Done."}], "stop_reason": "end_turn",
        "usage": usage(600_000, 200_000, 1_000_000, 60_000)}},
    {"type": "result", "subtype": "success", "is_error": False, "num_turns": 2,
     "result": "Done.", "session_id": SESSION,
     "usage": {**usage(*COUNTS), "server_tool_use": {"web_search_requests": 0}},
     "modelUsage": {"acme-4-build": {
         "inputTokens": COUNTS[0], "cacheCreationInputTokens": COUNTS[1],
         "cacheReadInputTokens": COUNTS[2], "outputTokens": COUNTS[3]}}}))
# Acme 4's prices a million tokens of input, cache write, cache read and output
PRICES = {"aa.price1mInputTokens": 2, "aa.cacheWritePrice": 2.5, "aa.cacheHitPrice": 0.2,
          "aa.price1mOutputTokens": 10}


def board(now):
    return {"artificialanalysis.ai": {"asked_at": now, "fetched_at": now, "error": None,
                                      "build": "", "rows": [{
        "model": "Acme 4", "effort": "high", "maker": "Acme", "deprecated": False,
        "slug": "acme-4", "values": PRICES,
        "release": {"slug": "acme-4", "name": "Acme 4", "deprecatedTo": None}}]}}


class AGrokBuildTurn(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        akconfig.write(cls.home, {"forge": {"harness": "grokbuild", "model": "acme-4",
                                            "provider": "acme"}, "opus": {}},
                       workers=["forge"], reviewers=["opus"],
                       providers={"acme": {"mode": "subscription", "accounts": ["second"]}})
        fakeadapter.install(cls.home, grokbuild={**fakeadapter.WORK, "session": SESSION,
                                                 "events": EVENTS}, claude="pass")
        task = taskfile.write(cls.home, Rig(cls.home, "widgets").path)
        cls.before = time.time()
        cls.done = cls.home.ak("run", str(task), "--no-merge", env=OWNERS, timeout=300)
        cls.after = time.time()
        cls.run_dir = taskfile.only_run(cls.home)
        connection = sqlite3.connect(cls.home.path / ".agentkit/history.db")
        connection.row_factory = sqlite3.Row
        try:
            cls.rows = [dict(row) for row in connection.execute("SELECT * FROM turn_usage")]
        finally:
            connection.close()
        cls.home.write(".agentkit/state/boards.json", board(time.time()))
        cls.usage = cls.home.ak("usage", "--json")

    def test_its_row_holds_its_results_counts_under_the_model_it_was_launched_with(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        [row] = self.rows
        self.assertEqual(Path(row["turn"]).parent.parent.resolve(), self.run_dir.resolve())
        self.assertLessEqual(self.before, row["began"])
        self.assertLessEqual(row["began"], row["at"])
        self.assertLessEqual(row["at"], self.after)
        self.assertEqual((row["run_id"], row["role"], row["account"], row["model"],
                          *(row[kind] for kind in TYPES)),
                         (self.run_dir.name, "executor", "second", "acme-4", *COUNTS))

    def test_its_logins_spend_is_priced_from_it(self):
        self.assertEqual(self.usage.code, 0, self.usage.out + self.usage.err)
        login = json.loads(self.usage.out)["providers"]["acme"]["accounts"]["second"]
        self.assertAlmostEqual(login["listed_usd"], 1 * 2 + 0.2 * 2.5 + 3 * 0.2 + 0.1 * 10)


if __name__ == "__main__":
    unittest.main()
