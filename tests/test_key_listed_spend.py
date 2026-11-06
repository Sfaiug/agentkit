"""`ak usage --json` gives each login under `providers.<provider>.accounts` its `listed_usd`: what
it spent over the last seven days at listed prices, null where none of its rows can be priced.

Each of the login's token rows in history.db, a seat's in `seat_usage` and a worker turn's in
`turn_usage`, is priced per type at its model's prices on Artificial Analysis's board, those of
its release's default effort, a cache price the release lists none of at its input price.  A row
whose model lists no price, or whose counts are unknown, costs what the login's priced rows cost
a token.  A seat row is its login's under the provider of the harness its event names, a turn
row under the provider of the harness its turn's `harness` receipt names; a harness running
two providers' models is neither's.

Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py on
tests/fixtures/meters.py's harness, copied as `chime` and `drum`, with an invented board and
rows written into its Home.  Fails against /bin/false.
"""

from contextlib import closing
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, meters
from fixtures.akbin import Home

NOW = time.time()
DAY = 86400
# each model's harness and provider: `echo` runs acme's alone, `chime` brine's, `drum` both's
MODELS = {"anvil": ("echo", "acme"), "bolt": ("chime", "brine"),
          "dual-a": ("drum", "acme"), "dual-b": ("drum", "brine")}
LOGINS = [(provider, account) for provider in ("acme", "brine")
          for account in ("default", "second")]
# each type's price a million tokens on the board
COLUMNS = {"input": "aa.price1mInputTokens", "cache_write": "aa.cacheWritePrice",
           "cache_read": "aa.cacheHitPrice", "output": "aa.price1mOutputTokens"}
# each release's name and its prices at each effort, `high` its default: Anvil's weakest effort,
# which lists first, is not; Awl lists no cache price, Crux no output price
RELEASES = {"anvil-1": ("Anvil 1", {"high": (2, 2.5, 0.2, 10), "low": (20, 25, 2, 100)}),
            "awl-1": ("Awl 1", {"high": (1, None, None, 4)}),
            "crux-1": ("Crux 1", {"high": (1, 1, 1, None)})}
SEAT_USAGE = ("CREATE TABLE seat_usage (event TEXT PRIMARY KEY, repo TEXT, at REAL, "
              "tokens INTEGER, account TEXT, model TEXT, input INTEGER, cache_write INTEGER, "
              "cache_read INTEGER, output INTEGER)")
TURN_USAGE = ("CREATE TABLE turn_usage (turn TEXT, run_id TEXT, role TEXT, account TEXT, "
              "model TEXT, began REAL, at REAL, input INTEGER, cache_write INTEGER, "
              "cache_read INTEGER, output INTEGER)")


def board():
    rows = [{"model": name, "effort": effort, "maker": "Acme", "deprecated": False,
             "slug": release if effort == "high" else f"{release}-{effort}",
             "values": {column: price for column, price in zip(COLUMNS.values(), prices)
                        if price is not None},
             "release": {"slug": release, "name": name, "deprecatedTo": None}}
            for release, (name, efforts) in RELEASES.items() for effort, prices in efforts.items()]
    return {"artificialanalysis.ai": {"asked_at": NOW, "fetched_at": NOW, "error": None,
                                      "build": "", "rows": rows}}


class ListedSpend(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        meter = meters.install(self.home)
        for harness in ("chime", "drum"):
            for suffix in (".sh", ".toml"):
                shutil.copy2(meter.dir / f"echo{suffix}", meter.dir / f"{harness}{suffix}")
        akconfig.write(self.home, {name: {"harness": harness, "provider": provider}
                                   for name, (harness, provider) in MODELS.items()},
                       providers={provider: {"mode": "subscription",
                                             "accounts": ["default", "second"]}
                                  for provider in ("acme", "brine")})
        self.home.write(".agentkit/state/boards.json", board())
        self.seats, self.turns = [], []

    def seat(self, harness, account, model, counts, *, tokens=None, ago=DAY):
        """A seat's row: `counts` by type or None, `tokens` their sum unless given."""
        self.seats.append((f"{harness}:event-{len(self.seats)}", "acme-repo", NOW - ago,
                           sum(counts) if tokens is None else tokens, account, model,
                           *(counts or (None,) * 4)))

    def turn(self, receipt, account, model, counts, *, ago=DAY):
        """A worker turn's row, its turn's `harness` receipt naming `receipt`, or gone."""
        turn = self.home.path / f".agentkit/runs/fix-api/round-1/executor-{len(self.turns)}"
        turn.mkdir(parents=True)
        if receipt:
            (turn / "harness").write_text(receipt)
        self.turns.append((str(turn), "fix-api", "executor", account, model, NOW - ago - 60,
                           NOW - ago, *counts))

    def spent(self):
        """Each login's `listed_usd`, the rows written into history.db first."""
        with closing(sqlite3.connect(self.home.path / ".agentkit/history.db")) as db, db:
            db.execute(SEAT_USAGE)
            db.execute(TURN_USAGE)
            db.executemany(f"INSERT INTO seat_usage VALUES ({', '.join('?' * 10)})", self.seats)
            db.executemany(f"INSERT INTO turn_usage VALUES ({', '.join('?' * 11)})", self.turns)
        done = self.home.ak("usage", "--json")
        self.assertEqual(done.code, 0, done.out + done.err)
        providers = json.loads(done.out)["providers"]
        return {(provider, account): providers[provider]["accounts"][account]["listed_usd"]
                for provider, account in LOGINS}

    def test_each_type_is_priced_at_its_models_listed_price(self):
        self.seat("echo", "default", "anvil-1", (1_000_000, 200_000, 5_000_000, 100_000))  # 4.5
        self.seat("echo", "default", "awl-1", (100_000, 1_000_000, 2_000_000, 250_000))   # 4.1
        self.turn("echo", "default", "anvil-1", (500_000, 0, 1_000_000, 50_000))          # 1.7
        spent = self.spent()
        self.assertAlmostEqual(spent["acme", "default"], 4.5 + 4.1 + 1.7)

    def test_a_row_with_no_listed_price_costs_the_logins_average_a_token(self):
        # $3 over six million tokens: half a dollar a million
        self.seat("echo", "default", "anvil-1", (1_000_000, 0, 5_000_000, 0))
        self.seat("echo", "default", "easel-2", (1_000_000, 0, 1_000_000, 0))   # on no board
        self.seat("echo", "default", "anvil-1", None, tokens=4_000_000)       # counts unknown
        self.turn("echo", "default", "crux-1", (1_000_000, 0, 0, 1_000_000))   # no output price
        # a login none of whose rows can be priced spent nothing anyone can name
        self.seat("echo", "second", "easel-2", (1_000_000, 0, 0, 0))
        spent = self.spent()
        self.assertAlmostEqual(spent["acme", "default"], 3 + 1 + 2 + 1)
        self.assertIsNone(spent["acme", "second"])

    def test_only_the_logins_rows_of_the_last_seven_days_count(self):
        self.seat("echo", "default", "anvil-1", (1_000_000, 0, 5_000_000, 0), ago=6 * DAY)  # 3
        self.seat("echo", "default", "anvil-1", (1_000_000, 0, 0, 0), ago=8 * DAY)
        self.turn("echo", "default", "anvil-1", (0, 0, 0, 100_000), ago=8 * DAY)
        self.seat("echo", "second", "anvil-1", (0, 0, 0, 100_000))                       # 1
        self.turn("chime", "default", "anvil-1", (1_000_000, 0, 0, 0))                   # 2
        # rows of no login: no account, a receipt gone, a harness of two providers
        self.seat("echo", None, "anvil-1", (0, 0, 0, 1_000_000))
        self.turn(None, "default", "anvil-1", (0, 0, 0, 1_000_000))
        self.seat("drum", "default", "anvil-1", (0, 0, 0, 1_000_000))
        spent = self.spent()
        self.assertAlmostEqual(spent["acme", "default"], 3)
        self.assertAlmostEqual(spent["acme", "second"], 1)
        self.assertAlmostEqual(spent["brine", "default"], 2)
        self.assertIsNone(spent["brine", "second"])


if __name__ == "__main__":
    unittest.main()
