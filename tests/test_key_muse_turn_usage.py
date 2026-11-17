"""A Muse worker turn's tokens are kept by type, and its login's spend priced from them.

`muse exec --json` streams no usage: its stream names the session and the run the turn opened,
and Muse's own session store records a `goal_usage_attribution` for each model request, its
input holding the cached prefix, which it says apart as `cached_tokens` where it does, and its
output the reasoning.  The turn's `turn_usage` row in history.db holds the sum of its run's
provider records -- input less what each says it cached, that under cache read, output, no
cache write -- under the model its entry launched it with; a resumed session's earlier run and a
tool's usage add nothing, and the turn's one number stays its records' input and output.  `ak
usage --json` then prices the login's `listed_usd` from that row.  Black-box: AK_BIN runs a task
through tests/fixtures/akbin.py on a fake harness configured as `muse`, whose turn streams in
the shape `muse exec --json` writes, with Muse's session store and an invented board in its
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
SESSION, RUN = "ses-acme", "run-acme-2"
STORE = f".local/share/muse/sessions/2026/11/17/{SESSION}/session.jsonl"

EVENTS = "".join(json.dumps({"schema_version": 1, "stream": {"kind": "session", "id": SESSION},
                             "payload": payload}) + "\n" for payload in (
    {"kind": "command_accepted"},
    {"kind": "session_run_linked", "run_stream": {"id": RUN, "kind": "run"}}))


def usage(run, family, input, output, cached=None, reasoning=0):
    """A session.jsonl line of one request's usage that `run` owns."""
    quantity = {"input_tokens": input, "output_tokens": output, "reasoning_tokens": reasoning,
                "main_llm_steps": 1, "reported": True, "unit": "tokens"}
    if cached is not None:
        quantity["cached_tokens"] = cached
    return json.dumps({"payload": {"kind": "run", "event": {
        "kind": "goal_usage_attribution", "record": {
            "usage_family": family, "owner": {"run_id": run, "session_id": SESSION},
            "quantity": quantity, "schema_version": 1}}}}) + "\n"


# the resumed session's earlier turn is another run's, and a tool's usage is no model's; the
# last request says no cached part apart
LOG = "".join((usage("run-acme-1", "provider", 9_000_000, 900_000, 8_000_000),
               usage(RUN, "provider", 3_000_000, 200_000, 2_000_000, 150_000),
               usage(RUN, "tool", 7, 7, 0),
               usage(RUN, "provider", 1_500_000, 50_000, 1_000_000, 20_000),
               usage(RUN, "provider", 500_000, 10_000)))
# Orbit 1's prices a million tokens of input, cache write, cache read and output
PRICES = {"aa.price1mInputTokens": 2, "aa.cacheWritePrice": 2.5, "aa.cacheHitPrice": 0.2,
          "aa.price1mOutputTokens": 10}


def board(now):
    return {"artificialanalysis.ai": {"asked_at": now, "fetched_at": now, "error": None,
                                      "build": "", "rows": [{
        "model": "Orbit 1", "effort": "high", "maker": "Acme", "deprecated": False,
        "slug": "orbit-1", "values": PRICES,
        "release": {"slug": "orbit-1", "name": "Orbit 1", "deprecatedTo": None}}]}}


class AMuseTurn(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        akconfig.write(cls.home, {"orbit": {"harness": "muse", "model": "orbit-1",
                                            "provider": "acme"}, "opus": {}},
                       workers=["orbit"], reviewers=["opus"],
                       providers={"acme": {"mode": "subscription", "accounts": ["second"]}})
        # Muse writes its store outside the box's walls, where history reads it after the turn
        cls.home.write(STORE, LOG)
        fakeadapter.install(cls.home, muse={**fakeadapter.WORK, "events": EVENTS},
                            claude="pass")
        task = taskfile.write(cls.home, Rig(cls.home, "widgets").path)
        cls.before = time.time()
        cls.done = cls.home.ak("run", str(task), "--no-merge", env=OWNERS, timeout=300)
        cls.after = time.time()
        cls.run_dir = taskfile.only_run(cls.home)
        connection = sqlite3.connect(cls.home.path / ".agentkit/history.db")
        connection.row_factory = sqlite3.Row
        try:
            cls.rows = [dict(row) for row in connection.execute("SELECT * FROM turn_usage")]
            cls.spent = connection.execute("SELECT executor_tokens FROM runs").fetchone()[0]
        finally:
            connection.close()
        cls.home.write(".agentkit/state/boards.json", board(time.time()))
        cls.usage = cls.home.ak("usage", "--json")

    def test_its_row_holds_its_records_input_cache_read_and_output_under_its_model(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        [row] = self.rows
        self.assertEqual(Path(row["turn"]).parent.parent.resolve(), self.run_dir.resolve())
        self.assertLessEqual(self.before, row["began"])
        self.assertLessEqual(row["began"], row["at"])
        self.assertLessEqual(row["at"], self.after)
        self.assertEqual((row["run_id"], row["role"], row["account"], row["model"],
                          *(row[kind] for kind in TYPES)),
                         (self.run_dir.name, "executor", "second", "orbit-1",
                          2_000_000, 0, 3_000_000, 260_000))

    def test_its_one_number_stays_its_records_input_and_output(self):
        self.assertEqual(self.spent, 5_260_000)

    def test_its_logins_spend_is_priced_from_it(self):
        self.assertEqual(self.usage.code, 0, self.usage.out + self.usage.err)
        login = json.loads(self.usage.out)["providers"]["acme"]["accounts"]["second"]
        self.assertAlmostEqual(login["listed_usd"], 2 * 2 + 3 * 0.2 + 0.26 * 10)


if __name__ == "__main__":
    unittest.main()
