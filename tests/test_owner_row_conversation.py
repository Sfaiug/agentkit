"""Owner moments keep their conversation across renames, reused names and schema upgrades."""

from contextlib import closing
import sqlite3
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import config, history, notify, orch


class OwnerRowConversation(Sandbox):
    def setUp(self):
        super().setUp()
        self.seats = {"fix-api": {"cwd": "/acme", "conversation": "c1"}}
        self.plugin = SimpleNamespace(name="claude", conversation=lambda record, cwd: record.get("conversation"))
        self.stack.enter_context(patch.object(config, "session_records", lambda: self.seats))
        self.stack.enter_context(patch.object(orch, "seat_plugin", lambda record, **_kw: self.plugin))

    def rows(self):
        with closing(sqlite3.connect(history.path())) as db:
            return db.execute("SELECT at, kind, waited, conversation FROM owner ORDER BY at").fetchall()

    def test_a_rename_or_reused_name_moves_no_moment(self):
        with notify.session_lock("fix-api") as name:
            notify._said(name, "needs", "Which schema?", at=100)
        self.seats["parser"] = self.seats.pop("fix-api")
        history.owner_time("answered", 200, 100, session="parser")
        self.seats["parser"]["conversation"] = "c2"
        history.owner_time("asked", 300, session="parser")
        self.assertEqual(self.rows(), [(100, "asked", None, "claude:c1"),
                                       (200, "answered", 100, "claude:c1"),
                                       (300, "asked", None, "claude:c2")])

    def test_a_missing_record_or_unknown_conversation_still_writes_the_moment(self):
        history.owner_time("asked", 100, session="gone")
        self.seats["fix-api"].pop("conversation")
        history.owner_time("paged", 200, session="fix-api")
        with patch.object(self.plugin, "conversation", side_effect=OSError("unreadable")):
            history.owner_time("answered", 300, 100, session="fix-api")
        self.assertEqual(self.rows(), [(100, "asked", None, None), (200, "paged", None, None),
                                       (300, "answered", 100, None)])

    def test_an_older_owner_table_keeps_its_rows_without_guessing_their_conversations(self):
        with closing(sqlite3.connect(history.path())) as db, db:
            db.execute("CREATE TABLE owner (at REAL, kind TEXT, waited REAL)")
            db.execute("INSERT INTO owner VALUES (100, 'answered', 40)")
        history.owner_time("asked", 200, session="fix-api")
        self.assertEqual(self.rows(), [(100, "answered", 40, None), (200, "asked", None, "claude:c1")])


if __name__ == "__main__":
    unittest.main()
