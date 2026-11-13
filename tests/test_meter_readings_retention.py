"""A reading kept already adds nothing, and drops nothing: rows past five weeks go only with a
write that keeps a new one.

A probe can bring back a reading history.db holds already -- Muse's adapter answers from its own
cache, and a spent window merged beside an older week leaves the snapshot dated before it -- so
the same reading reaches `meter_readings` twice.  Temporary HOME, invented readings.
"""

import sqlite3
import sys
import tempfile
import time
from pathlib import Path
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agentkit import config, history  # noqa: E402

NOW = time.time()
KEPT = ("acme", "default", "weekly", 30.0, NOW + 86400, 604800.0, NOW - 60, "probe", "pro", None)
AGED = ("acme", "default", "session", 20.0, None, 18000.0, NOW - 36 * 86400, "probe", "pro", None)
NEW = ("acme", "default", "weekly", 35.0, NOW + 86400, 604800.0, NOW, "probe", "pro", None)


class Retention(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="ak-meter-readings-")
        self.addCleanup(tmp.cleanup)
        home = patch.object(config, "HOME", Path(tmp.name))
        home.start()
        self.addCleanup(home.stop)
        history.keep_readings([KEPT])
        with sqlite3.connect(history.path()) as connection:
            connection.execute("INSERT INTO meter_readings VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", AGED)

    def kept(self):
        with sqlite3.connect(history.path()) as connection:
            return set(connection.execute("SELECT * FROM meter_readings"))

    def test_a_reading_kept_already_drops_nothing(self):
        history.keep_readings([KEPT])
        self.assertEqual(self.kept(), {KEPT, AGED})

    def test_a_new_reading_drops_the_rows_past_five_weeks(self):
        history.keep_readings([KEPT, NEW])
        self.assertEqual(self.kept(), {KEPT, NEW})


if __name__ == "__main__":
    unittest.main()
