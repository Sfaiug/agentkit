"""`ak usage --json` prices each plan's week over every window it checks.  On the owner's host,
7 Nov 2026, that read the receipts of each turn whose tokens ak does not know 90 times, 238,000
files and 43% of over a minute, and parsed the boards 724 times, once for each stretch of
readings such a turn cut, 20% more.  By the kernel's count (inotify), in one `ak usage --json`:

- the `harness` receipt of a turn whose run ended an hour ago and kept no `turn_usage` row is
  opened once, as such a turn never changes;
- `boards.json` is opened no more often in a Home where four such turns cut a login's readings
  into five stretches than in one where the readings form one stretch.

Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py on
tests/fixtures/meters.py's harness, its Home set up as tests/test_key_week_checked.py's is, with
readings, a run and its turns written into it.  Fails against /bin/false.
"""

from collections import Counter
from contextlib import closing
import ctypes
import json
import os
from pathlib import Path
import sqlite3
import struct
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, meters
from fixtures.akbin import Home
from test_key_week_from_its_own_spend import TABLES
from test_key_week_price import BOARD

NOW = time.time()
HOUR, DAY = 3600, 86400
WEEK = NOW + 3 * DAY    # the week's reset, far from the one the meter fixture reads now
# A close between each two opens, or the kernel counts them as one.
IN_OPEN, IN_CLOSE = 0x20, 0x18
EVENT = struct.Struct("iIII")


def opens(paths, act):
    """How often each of `paths` is opened while `act()` runs."""
    libc = ctypes.CDLL(None, use_errno=True)
    queue = libc.inotify_init1(os.O_CLOEXEC | os.O_NONBLOCK)
    assert queue >= 0, os.strerror(ctypes.get_errno())
    try:
        watches = []
        for path in paths:
            watch = libc.inotify_add_watch(queue, os.fsencode(path.parent), IN_OPEN | IN_CLOSE)
            assert watch >= 0, os.strerror(ctypes.get_errno())
            watches.append((watch, os.fsencode(path.name)))
        act()
        events = b""
        while True:
            try:
                events += os.read(queue, 1 << 20)
            except BlockingIOError:
                break
    finally:
        os.close(queue)
    count, at = Counter(), 0
    while at < len(events):
        watch, mask, _, size = EVENT.unpack_from(events, at)
        if mask & IN_OPEN:
            count[watch, events[at + EVENT.size:at + EVENT.size + size].rstrip(b"\0")] += 1
        at += EVENT.size + size
    return [count[watch] for watch in watches]


class UsageReadsOnce(unittest.TestCase):
    def usage(self, cut):
        """How often one `ak usage --json` opens each turn's `harness` receipt, and the boards,
        in a Home whose login read its week rising over ten hours, in five pairs an hour apart
        with a dollar spent between: between each pair and the next, where `cut`, a turn of a
        run that ended an hour ago, which kept no `turn_usage` row."""
        home = Home()
        self.addCleanup(home.close)
        meter = meters.install(home)
        meter.week("acme", "default", used=50)
        akconfig.write(home, {"anvil": {"harness": "echo", "provider": "acme"}},
                       providers={"acme": {"mode": "subscription", "accounts": ["default"]}})
        boards = home.write(".agentkit/state/boards.json", BOARD)
        home.write(".agentkit/state/logins.json", {"acme": {"default": {
            "email": "default@acme.test", "ends": None, "plan": "Max", "checked_at": NOW}}})
        rows, receipts = {table: [] for table in TABLES}, []
        for n, ago in enumerate((10, 8, 6, 4, 2)):
            for used, at in ((10 * n, ago), (10 * n + 5, ago - 1)):
                rows["meter_readings"].append(("acme", "default", "weekly", used, WEEK, 7 * DAY,
                                               NOW - at * HOUR, "probe", "Max"))
            rows["seat_usage"].append((f"echo:event-{n}", NOW - (ago - 0.5) * HOUR, 1e6,
                                       "default", "anvil-1", 1e6, 0, 0, 0))
            if cut and n < 4:
                turn = f".agentkit/runs/fix-api/round-1/executor-{n}"
                home.write(f"{turn}/account", "default", ago=(ago - 1.4) * HOUR)
                home.write(f"{turn}/events.jsonl", "{}\n", ago=(ago - 1.6) * HOUR)
                receipts.append(home.write(f"{turn}/harness", "echo", ago=(ago - 1.4) * HOUR))
        rows["runs"].append(("fix-api", NOW - DAY, NOW - HOUR,
                             json.dumps([str(receipt.parent) for receipt in receipts])))
        with closing(sqlite3.connect(home.path / ".agentkit/history.db")) as db, db:
            for table, columns in TABLES.items():
                db.execute(f"CREATE TABLE {table} ({columns})")
                for row in rows[table]:
                    db.execute(f"INSERT INTO {table} VALUES ({', '.join('?' * len(row))})", row)

        def run():
            done = home.ak("usage", "--json")
            self.assertEqual(done.code, 0, done.out + done.err)

        *read, parsed = opens([*receipts, boards], run)
        return read, parsed

    def test_a_turn_of_a_run_that_ended_is_read_once(self):
        read, _ = self.usage(cut=True)
        self.assertEqual(read, [1, 1, 1, 1])

    def test_the_boards_are_read_no_more_for_each_stretch_a_turn_cuts(self):
        _, alone = self.usage(cut=False)
        _, cut = self.usage(cut=True)
        self.assertLessEqual(cut, alone)


if __name__ == "__main__":
    unittest.main()
