"""A worker turn's spend at listed prices outlives its model's place on the boards.

A board drops a model once its maker ships the next one.  A turn's `turn_usage` row costs what
its counts cost at the prices the boards stored at its end listed for its model, so `ak usage
--json` gives its login the same `listed_usd` once the boards stored later list it no more.  A
row of a model those boards listed nothing for is priced as it is read: it costs what the
login's priced rows cost a token (tests/test_key_listed_spend.py).

Black-box: AK_BIN runs a task through tests/fixtures/akbin.py on a fake Claude executor whose
turn's `result` counts tokens of two models, an invented board in its Home before the run and
another after it, and a history.db from before rows kept dollars, so the run's write is the one
adding them.  Fails against /bin/false.
"""

from contextlib import closing
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
from test_key_listed_spend import TURN_USAGE

OWNERS = {"AK_NOTIFY_SINK": None}
SESSION = "session-acme"
COUNTS = ("inputTokens", "cacheCreationInputTokens", "cacheReadInputTokens", "outputTokens")
# the turn's tokens of each model by type: Anvil 1's cost $4.50 over four million tokens at its
# prices, Easel 2 is on no board
MODELS = {"anvil-1": (1_000_000, 400_000, 2_500_000, 100_000),
          "easel-2": (1_000_000, 0, 1_000_000, 0)}
SPENT = 4.5 + 4.5 * 2 / 4


def events():
    """The turn's `result`, in the shape Claude writes it, its `modelUsage` counting MODELS."""
    totals = [sum(counts) for counts in zip(*MODELS.values())]
    result = {"type": "result", "subtype": "success", "session_id": SESSION,
              "usage": dict(zip(("input_tokens", "cache_creation_input_tokens",
                                 "cache_read_input_tokens", "output_tokens"), totals)),
              "modelUsage": {model: dict(zip(COUNTS, counts)) for model, counts in MODELS.items()}}
    return "".join(json.dumps(event) + "\n" for event in (
        {"type": "system", "subtype": "init", "session_id": SESSION}, result))


def board(release, name):
    """A board listing one release, at $2, $2.50, $0.20 and $10 a million tokens of input,
    cache write, cache read and output."""
    now = time.time()
    return {"artificialanalysis.ai": {"asked_at": now, "fetched_at": now, "error": None,
                                      "build": "", "rows": [{
        "model": name, "effort": "high", "maker": "Acme", "deprecated": False, "slug": release,
        "values": {"aa.price1mInputTokens": 2, "aa.cacheWritePrice": 2.5,
                   "aa.cacheHitPrice": 0.2, "aa.price1mOutputTokens": 10},
        "release": {"slug": release, "name": name, "deprecatedTo": None}}]}}


class ATurnOnAModelTheBoardsDrop(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        akconfig.write(cls.home, ["opus", "astra"], workers=["opus"], reviewers=["astra"],
                       providers={"anthropic": {"mode": "subscription", "accounts": ["second"]}})
        fakeadapter.install(cls.home, claude={**fakeadapter.WORK, "session": SESSION,
                                              "events": events()}, codex="pass")
        cls.home.write(".agentkit/state/boards.json", board("anvil-1", "Anvil 1"))
        with closing(sqlite3.connect(cls.home.path / ".agentkit/history.db")) as db, db:
            db.execute(TURN_USAGE)
        cls.done = cls.home.ak("run", str(taskfile.write(cls.home, Rig(cls.home, "widgets").path)),
                               "--no-merge", env=OWNERS, timeout=300)
        cls.before = cls.home.ak("usage", "--json")
        # its maker shipped the next one
        cls.home.write(".agentkit/state/boards.json", board("anvil-2", "Anvil 2"))
        cls.after = cls.home.ak("usage", "--json")

    def spent(self, done):
        self.assertEqual(done.code, 0, done.out + done.err)
        return json.loads(done.out)["providers"]["anthropic"]["accounts"]["second"]["listed_usd"]

    def test_the_run_passes(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)

    def test_its_login_spent_at_the_prices_listed_at_its_end(self):
        self.assertAlmostEqual(self.spent(self.before), SPENT)

    def test_its_login_spent_the_same_once_the_boards_list_its_model_no_more(self):
        self.assertAlmostEqual(self.spent(self.after), SPENT)


if __name__ == "__main__":
    unittest.main()
