"""Muse's refused names never become prompts or seat names; no real tmux or HOME."""

from contextlib import closing
import json
import os
import shlex
import sqlite3
import subprocess
import unittest
from unittest.mock import patch

from test_v4n import REPO, Sandbox
from agentkit import config, orch, watch


class MuseTitle(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {
            "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0", "AGENTKIT_SESSION": "lagoon",
            "XDG_CONFIG_HOME": str(self.root / ".config"),
            "XDG_DATA_HOME": str(self.root / ".local/share"),
            "AK_NOTIFY_SINK": str(self.root / "notices")}))
        self.seat = {"name": "lagoon", "path": str(self.root), "created": 100,
                     "attached": True, "exited": False, "legacy": False}
        self.pane = self.fixture("idle-refused-pane.txt")
        self.keys = []
        self.events = [json.loads(line) for line in
                       self.fixture("session.jsonl").splitlines()]
        self.sid = self.events[0]["stream"]["id"]
        self.store = self.root / ".local/share/muse"
        self.session(self.sid)
        index = json.loads(self.fixture("unavailable-index.json"))
        self.index = self.store / "session-index.db"
        with closing(sqlite3.connect(self.index)) as db, db:
            db.execute(index["sessions_schema"])
            db.execute("CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT)")
            db.executemany("INSERT INTO schema_meta VALUES (:key, :value)", index["schema_meta"])
        config.save_session(self.cfg, "lagoon", "spark", ["astra"], {"cwd": str(self.root)})
        self.stack.enter_context(patch.object(orch, "sessions", side_effect=lambda: [self.seat]))
        self.stack.enter_context(patch.object(orch, "tmux_out", side_effect=self.tmux))
        for method in ("poll_worker_token", "seat_account", "stop_nudge", "announce_state"):
            self.stack.enter_context(patch.object(watch, method, return_value=False))

    def fixture(self, name):
        return (REPO / "tests/fixtures" / f"muse-title-{name}").read_text()

    def session(self, sid):
        directory = self.store / "sessions/2026/09/28" / sid
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "session.jsonl").write_text(
            self.fixture("session.jsonl").replace(self.sid, sid))
        return directory

    def title(self, sid, name, provenance):
        # No successful title was observed. These are synthetic rows in the captured schema.
        directory = self.session(sid)
        with closing(sqlite3.connect(self.index)) as db, db:
            db.execute("""INSERT OR REPLACE INTO sessions
                (session_id, session_stream_id, session_dir, session_log_path, layout,
                 title, effective_long_title, title_provenance, title_name_fingerprint,
                 search_text, status, status_rank, indexed_at_us, session_name,
                 session_name_revision)
                VALUES (?, ?, ?, ?, 'dated', ?, ?, ?, 'fixture', ?, 'idle', 0, 0, ?, ?)""",
                       (sid, sid, str(directory), str(directory / "session.jsonl"),
                        name, name, provenance, name,
                        name if provenance == "manual" else None,
                        1 if provenance == "manual" else None))

    def record(self):
        return config.session_records()[self.seat["name"]]

    def tmux(self, *args, **kwargs):
        if args[0] == "rename-session":
            self.seat = dict(self.seat, name=args[-1])
        elif args[0] == "capture-pane":
            self.assertEqual(args[-1], f"={self.seat['name']}:")
            return 0, self.pane
        elif args[0] == "send-keys":
            self.keys.append(args)
        return 0, ""

    def tick(self):
        state = watch.load_state()
        watch.health(self.cfg, state, False, lambda _: None)
        watch.save_state(state)
        self.assertEqual(self.keys, [])
        self.assertNotIn("session_title", self.record())
        self.assertNotIn("title_sync", self.record())

    def test_new_launch_neither_passes_nor_records_a_name(self):
        result = subprocess.run(["bash", str(REPO / "adapters/muse.sh"), "interactive",
                                 "muse-spark-1.3", "minimal"],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        command = shlex.split(result.stdout)
        self.assertNotIn("--name", command)
        self.assertNotIn("/rename", result.stdout)
        with patch.object(orch, "start") as start:
            orch.launch("lagoon", "spark", self.root, command, None)
        start.assert_called_once_with("lagoon", self.root, command, "spark")
        self.tick()
        self.tick()

    def test_ak_rename_and_auto_name_never_type(self):
        self.assertEqual(orch.rename("lagoon", "quay"), "quay")
        self.tick()
        config.update_session("quay", unnamed=True)
        self.assertEqual(orch.rename("quay", "fix-api", auto=True), "fix-api")
        self.tick()
        self.tick()

    def test_idle_busy_and_owner_drafts_are_untouched(self):
        for kind in ("before-turn-refused", "idle-refused", "working-refused",
                     "idle-composed", "working-composed"):
            with self.subTest(kind=kind):
                self.pane = self.fixture(kind + "-pane.txt")
                self.assertFalse(watch.sync_title(self.seat, force=True))
                self.tick()

    def test_refused_owner_rename_does_not_rename_seat(self):
        config.update_session("lagoon", conversation=self.sid, id_source=orch.LAUNCHER)
        self.tick()
        self.assertEqual(self.seat["name"], "lagoon")
        self.assertIsNone(orch.seat_plugin(self.record()).session_title(self.record()))

    def test_generated_name_does_not_rename_seat(self):
        config.update_session("lagoon", conversation=self.sid, id_source=orch.LAUNCHER)
        self.title(self.sid, "pebble", "generated")
        self.tick()
        self.assertEqual(self.seat["name"], "lagoon")

    def test_another_sessions_manual_name_changes_nothing(self):
        config.update_session("lagoon", conversation=self.sid, id_source=orch.LAUNCHER)
        other = "00000000-0000-0000-0000-000000000099"
        self.title(other, "harbor", "manual")
        self.tick()
        self.assertEqual(self.seat["name"], "lagoon")

    def test_probe_covers_renames_before_after_and_during_real_turns(self):
        commands = [e["sequence"] for e in self.events if e["payload_type"] == "command.invoked"]
        runs = [e for e in self.events if e["payload"].get("kind") == "run"]
        starts = [e for e in runs if e["payload"]["event"]["kind"] == "started"]
        ends = [e for e in runs if e["payload"]["event"].get("terminal") == "completed"]
        self.assertEqual(len(commands), 3)
        self.assertEqual(len(starts), 2)
        self.assertEqual(len(ends), 2)
        self.assertLess(commands[0], starts[0]["sequence"])
        self.assertLess(ends[0]["sequence"], commands[1])
        self.assertLess(commands[1], starts[1]["sequence"])
        self.assertLess(starts[1]["sequence"], commands[2])
        self.assertLess(commands[2], ends[1]["sequence"])
        self.assertEqual([e["payload"]["event"]["prompt"] for e in starts], [
            "Reply with exactly: pebble",
            "List the integers from 1 to 120, one per line, with no tools."])
        for kind in ("before-turn", "idle", "working"):
            self.assertIn("naming is unavailable", self.fixture(kind + "-refused-pane.txt"))
        self.assertIn("unexpected argument '--name'", self.fixture("launch-refused.txt"))


if __name__ == "__main__":
    unittest.main()
