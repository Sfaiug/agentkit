"""The tick's log rolls over to one kept generation once it is past 5 MB, and only then.

Cron only appends each tick's output to ~/.agentkit/tmp/watch.log, every three minutes for
years, so the tick is the one thing that keeps that file bounded: a tick whose output is the
log moves it to watch.log.1 (the generation before is gone) and starts a new one with its own
lines.  A tick printing anywhere else, or a dry run, renames nothing.  The tick lock is held
from outside for every case, so each pass is the short one that finds another tick running;
that lock file is the one every tick takes, whichever build runs it.  Black-box: the program
`AK_BIN` names runs from outside through tests/fixtures/akbin.py.
"""

import fcntl
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import AK, Home

LIMIT = 5 * 1024 * 1024
# cron's own line: both streams appended to the log
TICK = '"$0" watch "$@" >>"$HOME/.agentkit/tmp/watch.log" 2>&1'
OVERLAP = "tick already running"


class TickLogRoll(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        lock = cls.home.path.joinpath(".agentkit/state/watch.tick.lock").open("a+")
        cls.addClassCleanup(lock.close)
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        cls.log = cls.home.path / ".agentkit/tmp/watch.log"
        cls.kept = cls.log.with_name("watch.log.1")

    def setUp(self):
        self.kept.unlink(missing_ok=True)

    def tick(self, *args):
        done = self.home.run("sh", "-c", TICK, AK, *args)
        self.assertEqual(done.code, 0, self.log.read_text()[-2000:])
        return done

    def test_a_tick_writing_into_a_log_past_5_mb_moves_it_aside_and_starts_a_new_one(self):
        self.home.write(".agentkit/tmp/watch.log", "x" * (LIMIT + 10))
        self.home.write(".agentkit/tmp/watch.log.1", "old")
        self.tick()
        self.assertEqual(self.kept.stat().st_size, LIMIT + 10)
        self.assertEqual(self.kept.read_bytes(), b"x" * (LIMIT + 10))
        fresh = self.log.read_text()
        self.assertTrue(fresh.startswith(OVERLAP), fresh[:200])
        self.assertLess(len(fresh), 1024 * 1024)

    def test_a_log_of_exactly_5_mb_is_not_rolled(self):
        self.home.write(".agentkit/tmp/watch.log", "x" * LIMIT)
        self.tick()
        self.assertFalse(self.kept.exists())
        grown = self.log.read_bytes()
        self.assertEqual(grown[:LIMIT], b"x" * LIMIT)
        self.assertTrue(grown[LIMIT:].startswith(OVERLAP.encode()), grown[LIMIT:])

    def test_a_tick_printing_elsewhere_leaves_a_big_log_alone(self):
        self.home.write(".agentkit/tmp/watch.log", "x" * (LIMIT + 10))
        done = self.home.ak("watch")
        self.assertEqual(done.code, 0, done.err)
        self.assertTrue(done.out.startswith(OVERLAP), done.out)
        self.assertFalse(self.kept.exists())
        self.assertEqual(self.log.read_bytes(), b"x" * (LIMIT + 10))

    def test_a_dry_run_into_a_big_log_renames_nothing(self):
        self.home.write(".agentkit/tmp/watch.log", "x" * (LIMIT + 10))
        self.tick("--dry-run")
        self.assertFalse(self.kept.exists())
        grown = self.log.read_bytes()
        self.assertEqual(grown[:LIMIT + 10], b"x" * (LIMIT + 10))
        self.assertGreater(len(grown), LIMIT + 10)


if __name__ == "__main__":
    unittest.main()
