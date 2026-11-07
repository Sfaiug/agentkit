"""`ak run gc` ends each OpenCode session idle for 30 days, read from OpenCode's own database.

OpenCode keeps every conversation as rows of opencode.db under its data folder.  A top-level
session nobody updated for 30 days is planned by its id and ended with `opencode session delete
--standalone`, which takes its children along; a child is never planned by itself, and a newer
session stays.  The rows are as OpenCode 2.0.14 writes them (tests/fixtures/README.md), and the
fake `opencode` only logs its calls.  Black-box: the program `AK_BIN` names runs from outside
through tests/fixtures/akbin.py, boxed with a /tmp, a /var/tmp and processes of its own.
"""

import contextlib
import json
from pathlib import Path
import shlex
import sqlite3
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import AK, LOG, REPO, boxable, Home
from fixtures.garbage import DAY, ROOM

STORAGE = json.loads((REPO / "tests/fixtures/opencode-title-storage.json").read_text())
OLD, NEW, CHILD, NAMED, OWN = (f"ses_0fa1c2d3e4ffAcme{name}"
                               for name in ("Old", "New", "Child", "Named", "Own"))


def database(path, *sessions):
    """opencode.db at `path`, a session_v2 row for each (id, parent, days since it was updated)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.closing(sqlite3.connect(path)) as db, db:
        db.execute(STORAGE["schema"])
        for sid, parent, days in sessions:
            at = int((time.time() - days * DAY) * 1000)    # OpenCode stamps milliseconds
            row = {**STORAGE["row"], "id": sid, "parent_id": parent, "time_created": at,
                   "time_updated": at}
            db.execute(f"INSERT INTO session_v2 ({', '.join(row)})"
                       f" VALUES ({', '.join('?' * len(row))})", tuple(row.values()))


@unittest.skipUnless(boxable(), "no bwrap able to box a collection here")
class GcEndsIdleOpencodeSessions(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        home.fake("opencode", LOG.format(python=shlex.quote(sys.executable),
                                         log=shlex.quote(str(home.log("opencode")))))
        database(home.path / ".local/share/opencode/opencode.db",
                 (OLD, None, 31), (NEW, None, 29), (CHILD, NEW, 40))

    def gc(self, *args, env=None):
        """The program's `run gc` in a box whose empty /tmp and /var/tmp leave it nothing else
        to plan."""
        tmp, var = self.home.root / "box-tmp", self.home.root / "box-var"
        tmp.mkdir(exist_ok=True)
        var.mkdir(exist_ok=True)
        box = ("bwrap", "--dev-bind", "/", "/", "--bind", str(tmp), "/tmp", "--bind", str(var),
               "/var/tmp", "--unshare-pid", "--proc", "/proc")
        done = self.home.run(*self.home.box(box), AK, "run", "gc", *args,
                             env={**ROOM, **(env or {})})
        self.assertEqual((done.code, done.err), (0, ""))
        return done.out.splitlines()

    def test_the_plan_is_the_top_level_session_idle_for_30_days_by_its_id(self):
        self.assertEqual(self.gc("--dry-run"),
                         [f"gc: would remove conversation {OLD}: untouched for 30 days"])
        self.assertEqual(self.home.calls("opencode"), [])

    def test_the_collection_ends_that_session_with_opencodes_own_delete(self):
        self.gc()
        self.assertEqual(self.home.calls("opencode"),
                         [["session", "delete", "--standalone", OLD]])

    def test_the_database_read_is_the_one_opencode_keeps(self):
        data, own = self.home.path / "data", self.home.path / "acme/sessions.db"
        for env, path, sid in (({"XDG_DATA_HOME": str(data), "OPENCODE_DB": "acme.db"},
                                data / "opencode/acme.db", NAMED),
                               ({"XDG_DATA_HOME": str(data), "OPENCODE_DB": str(own)}, own, OWN)):
            with self.subTest(**env):
                database(path, (sid, None, 31))
                self.assertEqual(self.gc("--dry-run", env=env),
                                 [f"gc: would remove conversation {sid}: untouched for 30 days"])


if __name__ == "__main__":
    unittest.main()
