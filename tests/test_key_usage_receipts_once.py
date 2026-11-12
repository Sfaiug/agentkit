"""Every pick prices every plan's week.  On the owner's host, 8 Nov 2026, each pricing read a
turn row's `harness` receipt once for each row of its turn, for each provider whose week reads
its login, 22,000 reads and 5.9 s, and read the turns whose tokens ak does not know once for each
provider.  By the kernel's count (inotify), in one `ak usage --json`:

- the `harness` receipt of a turn of a run that ended, which kept several `turn_usage` rows, is
  opened once, as such a turn never changes;
- that of a turn of a run still going, which kept none, is opened as often with three providers
  configured as with one, each with a login named `default` and a meter.

Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py on
tests/fixtures/meters.py's harness, its Home set up as tests/test_key_usage_unknown_once.py's
is, with readings of each provider's week and the two runs and their turns written into it.
Fails against /bin/false.
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
from test_key_usage_reads_once import opens
from test_key_week_from_its_own_spend import TABLES
from test_key_week_price import BOARD

NOW = time.time()
HOUR, DAY = 3600, 86400
WEEK = NOW + 3 * DAY    # the week's reset, far from the one the meter fixture reads now
# each provider, the model on it and that model's harness, a copy of the meter fixture's
PROVIDERS = (("acme", "anvil", "echo"), ("brine", "bolt", "chime"), ("crest", "cog", "gong"))


class UsageReceiptsOnce(unittest.TestCase):
    def usage(self, providers):
        """How often one `ak usage --json` opens the `harness` receipt of a turn of a run that
        ended an hour ago and kept three `turn_usage` rows, and that of a turn of a run still
        going that kept none, in a Home of the first `providers` of PROVIDERS: each one's
        `default` login read its week rising over ten hours, the ended turn's rows among them."""
        home = Home()
        self.addCleanup(home.close)
        named = PROVIDERS[:providers]
        meter = meters.install(home)
        for provider, _, harness in named:
            meter.week(provider, "default", used=50)
            for suffix in (".sh", ".toml") if harness != "echo" else ():
                shutil.copy2(meter.dir / f"echo{suffix}", meter.dir / f"{harness}{suffix}")
        akconfig.write(home, {model: {"harness": harness, "provider": provider}
                              for provider, model, harness in named},
                       providers={provider: {"mode": "subscription", "accounts": ["default"]}
                                  for provider, _, _ in named})
        home.write(".agentkit/state/boards.json", BOARD)
        home.write(".agentkit/state/logins.json", {provider: {"default": {
            "email": f"default@{provider}.test", "ends": None, "plan": "Max",
            "checked_at": NOW}} for provider, _, _ in named})
        rows = {table: [] for table in TABLES}
        for provider, _, _ in named:
            for n, ago in enumerate((10, 8, 6, 4, 2)):
                for used, at in ((10 * n, ago), (10 * n + 5, ago - 1)):
                    rows["meter_readings"].append((provider, "default", "weekly", used, WEEK,
                                                   7 * DAY, NOW - at * HOUR, "probe", "Max"))
        ended = ".agentkit/runs/fix-api/round-1/executor-1"
        home.write(f"{ended}/account", "default", ago=10 * HOUR)
        home.write(f"{ended}/events.jsonl", "{}\n", ago=2 * HOUR)
        receipts = [home.write(f"{ended}/harness", "echo", ago=10 * HOUR)]
        rows["turn_usage"] += [(str(receipts[0].parent), "fix-api", "executor", "default",
                                "anvil-1", NOW - began * HOUR, NOW - (began - 1.5) * HOUR,
                                1e6, 0, 0, 0) for began in (9.5, 7.5, 5.5)]
        rows["runs"].append(("fix-api", NOW - DAY, NOW - HOUR,
                             json.dumps([str(receipts[0].parent)])))
        going = ".agentkit/runs/add-ui/round-1/executor-1"
        home.write(f"{going}/account", "default", ago=30 * HOUR)
        home.write(f"{going}/events.jsonl", "{}\n", ago=12 * HOUR)  # before them: it cuts none
        receipts.append(home.write(f"{going}/harness", "echo", ago=30 * HOUR))
        rows["runs"].append(("add-ui", NOW - 2 * DAY, None, "[]"))
        with closing(sqlite3.connect(home.path / ".agentkit/history.db")) as db, db:
            for table, columns in TABLES.items():
                db.execute(f"CREATE TABLE {table} ({columns})")
                for row in rows[table]:
                    db.execute(f"INSERT INTO {table} VALUES ({', '.join('?' * len(row))})", row)

        def run():
            done = home.ak("usage", "--json")
            self.assertEqual(done.code, 0, done.out + done.err)

        return opens(receipts, run)

    def test_a_turn_of_a_run_that_ended_is_read_once_whatever_its_rows(self):
        ended, _ = self.usage(providers=3)
        self.assertEqual(ended, 1)

    def test_a_turn_of_a_run_still_going_is_read_no_more_for_each_provider(self):
        _, alone = self.usage(providers=1)
        _, three = self.usage(providers=3)
        self.assertGreater(alone, 0)
        self.assertEqual(three, alone)


if __name__ == "__main__":
    unittest.main()
