"""An OpenCode session nobody updated for 30 days is ended by `opencode session delete`.

Offline: HOME, PATH's `opencode` and /proc are the fixture's.  The database is laid out as
OpenCode 2.1.1 lays it out: session_v2 rows, a child's `parent_id` naming its parent, times in
milliseconds, and their session_message rows.  The fake `opencode session delete --standalone`
records its arguments and deletes the session with its children and messages, as 2.1.1 does.
"""

import contextlib
import os
from pathlib import Path
import sqlite3
import time
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import gc, orch, retention

DAY = 86400
DELETE = """import sqlite3, sys
db = sqlite3.connect(sys.argv[1])
db.execute("DELETE FROM session_message WHERE session_id IN"
           " (SELECT id FROM session_v2 WHERE ? IN (id, parent_id))", (sys.argv[2],))
db.execute("DELETE FROM session_v2 WHERE ? IN (id, parent_id)", (sys.argv[2],))
db.commit()
"""


class GcOpenCodeConversations(Sandbox):
    def setUp(self):
        real_time = time.time
        super().setUp()
        self.stack.enter_context(patch.object(time, "time", real_time))
        self.stack.enter_context(patch.object(orch, "user_manager", return_value=False))
        self.stack.enter_context(patch.dict(os.environ, {"AGENTKIT_GC_DISK_PERCENT": "100",
                                                        "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0"}))
        for name in ("AGENTKIT_RUN", "AK_PARENT_RUN", "AK_RUN_LOG", "XDG_DATA_HOME", "OPENCODE_DB"):
            os.environ.pop(name, None)
        proc = self.root / "proc"
        proc.mkdir()
        self.stack.enter_context(patch.object(retention, "process_dirs", proc.iterdir))
        self.stack.enter_context(patch.object(gc, "tmp_hidden_processes", return_value=None))
        self.db = Path.home() / ".local/share/opencode/opencode.db"
        self.db.parent.mkdir(parents=True)
        with contextlib.closing(sqlite3.connect(self.db)) as db, db:
            db.execute("CREATE TABLE session_v2 (id TEXT PRIMARY KEY, parent_id TEXT,"
                       " time_updated INTEGER NOT NULL)")
            db.execute("CREATE TABLE session_message (id TEXT PRIMARY KEY, session_id TEXT NOT NULL)")
        bin_dir = self.root / "fake-bin"
        bin_dir.mkdir()
        (bin_dir / "delete.py").write_text(DELETE)
        self.calls = self.root / "opencode-calls"
        self.opencode = bin_dir / "opencode"
        self.opencode.write_text(f'#!/bin/sh\necho "$*" >> {self.calls}\n'
                                 f'exec python3 {bin_dir / "delete.py"} {self.db} "$4"\n')
        self.opencode.chmod(0o755)
        self.stack.enter_context(patch.dict(os.environ, {"PATH": f"{bin_dir}:{os.environ['PATH']}"}))

    def session(self, name, age, parent=None):
        with contextlib.closing(sqlite3.connect(self.db)) as db, db:
            db.execute("INSERT INTO session_v2 VALUES (?, ?, ?)",
                       (name, parent, int((time.time() - age) * 1000)))
            db.execute("INSERT INTO session_message VALUES (?, ?)", (f"msg_{name}", name))

    def kept(self):
        with contextlib.closing(sqlite3.connect(self.db)) as db:
            return {name for name, in db.execute("SELECT session_id FROM session_message")}

    def test_a_session_untouched_for_thirty_days_is_deleted_with_its_children(self):
        self.session("ses_acmeold", 31 * DAY)
        self.session("ses_acmeoldchild", 31 * DAY, parent="ses_acmeold")
        self.session("ses_acmerecent", 29 * DAY)
        self.session("ses_acmechild", 31 * DAY, parent="ses_acmerecent")
        self.session("ses_acmeresumed", 31 * DAY)
        self.assertEqual({item["path"] for item in gc.gc_plan() if item["kind"] == "conversation"},
                         {"ses_acmeold", "ses_acmeresumed"})
        planned = gc.idle_conversations

        def resumed_after_the_plan(before):
            found = planned(before)
            with contextlib.closing(sqlite3.connect(self.db)) as db, db:
                db.execute("UPDATE session_v2 SET time_updated = ? WHERE id = 'ses_acmeresumed'",
                           (int(time.time() * 1000),))
            return found

        with patch.object(gc, "idle_conversations", side_effect=resumed_after_the_plan):
            removed = gc.gc(lambda _: None)
        self.assertEqual(removed, ["ses_acmeold"])
        self.assertEqual(self.calls.read_text().splitlines(),
                         ["session delete --standalone ses_acmeold"])
        self.assertEqual(self.kept(), {"ses_acmerecent", "ses_acmechild", "ses_acmeresumed"})

    def test_a_database_reached_through_a_link_keeps_its_sessions(self):
        self.session("ses_acmelinked", 31 * DAY)
        link = Path.home() / "acme.db"
        link.symlink_to(self.db)
        os.environ["OPENCODE_DB"] = str(link)
        gc.gc(lambda _: None)
        self.assertFalse(self.calls.exists())
        self.assertEqual(self.kept(), {"ses_acmelinked"})

    def test_a_failed_delete_leaves_opencode_alone_for_the_pass(self):
        for name in ("ses_acmeone", "ses_acmetwo"):
            self.session(name, 31 * DAY)
        self.opencode.write_text(f'#!/bin/sh\necho "$*" >> {self.calls}\nexit 1\n')
        said = []
        gc.gc(said.append)
        self.assertEqual(len(self.calls.read_text().splitlines()), 1)
        self.assertEqual(sum(line.startswith("gc: kept") for line in said), 1, said)
        self.assertEqual(self.kept(), {"ses_acmeone", "ses_acmetwo"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
