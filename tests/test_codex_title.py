"""Codex acknowledges ak's names without following ambiguous titles; fake tmux and HOME."""

import json
import os
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

from test_v4n import REPO, Sandbox
from agentkit import config, orch, watch
from agentkit.harness import codex


class CodexTitle(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {
            "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0", "AGENTKIT_SESSION": "",
            "CODEX_HOME": str(self.root / ".codex"),
            "AK_NOTIFY_SINK": str(self.root / "notices")}))
        self.seat = {"name": "lagoon", "path": str(self.root), "created": 100,
                     "attached": True, "exited": False, "legacy": False}
        self.pane = self.fixture("idle")
        self.typed, self.keys = [], []
        self.confirm = True
        self.drop_enter = False
        self.home = self.root / ".codex"
        self.home.mkdir()
        self.index = self.home / "session_index.jsonl"
        self.sid = self.index_fixture()[0]["id"]
        self.transcript = self.home / "sessions/rollout-owned.jsonl"
        self.transcript.parent.mkdir()
        self.transcript.write_text(json.dumps({"type": "session_meta", "payload": {
            "id": self.sid, "cwd": str(self.root)}}) + "\n")
        config.save_session(self.cfg, "lagoon", "astra", ["astra"], {
            "cwd": str(self.root), "session_title": "lagoon"})
        self.bind()
        orch.records()  # the health pass reconciles this receipt before reading titles
        self.title("lagoon")
        self.stack.enter_context(patch.object(orch, "sessions", side_effect=lambda: [self.seat]))
        self.stack.enter_context(patch.object(orch, "tmux_out", side_effect=self.tmux))
        self.stack.enter_context(patch.object(watch, "KEY_GAP", 0))
        self.stack.enter_context(patch.object(watch, "SENT_WAIT", watch.SENT_POLL))
        self.stack.enter_context(patch.object(watch.time, "sleep"))
        for method in ("poll_worker_token", "seat_account", "stop_nudge", "announce_state"):
            self.stack.enter_context(patch.object(watch, method, return_value=False))

    def bind(self):
        path = codex.prepare(self.seat["name"], self.root, None)
        codex.capture(path, {"session_id": self.sid, "transcript_path": str(self.transcript),
                            "cwd": str(self.root), "hook_event_name": "SessionStart",
                            "source": "startup"})

    def fixture(self, kind):
        return (REPO / "tests/fixtures" / f"codex-title-{kind}-pane.txt").read_text()

    def index_fixture(self):
        return [json.loads(line) for line in
                (REPO / "tests/fixtures/codex-title-index.jsonl").read_text().splitlines()]

    def title(self, name, sid=None):
        entry = dict(self.index_fixture()[-1], id=sid or self.sid, thread_name=name)
        with self.index.open("a") as handle:
            handle.write(json.dumps(entry) + "\n")
        if (self.home / "state_5.sqlite").exists():
            with sqlite3.connect(self.home / "state_5.sqlite") as db:
                db.execute("update threads set name = ? where id = ?", (name, entry["id"]))
            db.close()

    def snapshot(self, case, step):
        data = json.loads((REPO / "tests/fixtures/codex-title-prompts.json").read_text())
        snapshot = next(item for item in data[case] if item["step"] == step)
        self.index.write_text("".join(json.dumps(dict(entry, id=self.sid)) + "\n"
                                      for entry in snapshot["index"]))
        with sqlite3.connect(self.home / "state_5.sqlite") as db:
            db.execute("create table if not exists threads (id text, source text, title text, "
                       "first_user_message text, name text)")
            db.execute("delete from threads")
            for row in snapshot["rows"]:
                db.execute("insert into threads values (?, ?, ?, ?, ?)",
                           (self.sid, row["source"], row["title"],
                            row["first_user_message"], row["name"]))
        db.close()

    def thread_name(self):
        with sqlite3.connect(self.home / "state_5.sqlite") as db:
            name, = db.execute("select name from threads where id = ?", (self.sid,)).fetchone()
        db.close()
        return name

    def record(self):
        return config.session_records()[self.seat["name"]]

    def compose(self, text):
        rows = self.pane.splitlines()
        at = next(i for i in reversed(range(len(rows)))
                  if watch.strip_sgr(rows[i]).startswith("›"))
        rows[at] = "› " + text if text else "› \x1b[2mAsk Codex to do anything\x1b[0m"
        self.pane = "\n".join(rows) + "\n"

    def tmux(self, *args, **kwargs):
        if args[0] == "rename-session":
            self.seat = dict(self.seat, name=args[-1])
        elif args[0] == "capture-pane":
            self.assertEqual(args[-1], f"={self.seat['name']}:")
            return 0, self.pane
        elif args[0] == "send-keys":
            self.assertEqual(args[2], f"={self.seat['name']}:")
            self.keys.append(args[-1])
            if "-l" in args:
                self.typed.append(args[-1])
                self.compose(args[-1])
            elif args[-1] == "Enter" and not self.drop_enter:
                # Anything other than this literal slash command would be a model prompt.
                self.assertTrue(self.typed[-1].startswith("/rename "))
                self.compose("")
                if self.confirm:
                    self.title(self.typed[-1].removeprefix("/rename "))
        return 0, ""

    def tick(self):
        state = watch.load_state()
        watch.health(self.cfg, state, False, lambda _: None)
        watch.save_state(state)

    def test_ak_rename_types_once_and_requires_the_stored_name(self):
        self.confirm = False
        orch.rename("lagoon", "quay")
        self.assertEqual(self.typed, ["/rename quay"])
        self.assertEqual(self.record()["session_title"], "lagoon")
        self.title("quay")
        self.tick()
        self.tick()
        self.assertEqual(self.typed, ["/rename quay"])
        self.assertEqual(self.keys, ["/rename quay", "Enter"])
        self.assertEqual(self.record()["session_title"], "quay")
        self.assertNotIn("title_sync", self.record())

    def test_new_launch_waits_for_its_receipt_and_sets_the_title(self):
        with patch.object(orch, "start"):
            orch.launch("lagoon", "astra", self.root, ["codex"], None)
        self.assertNotIn("session_title", self.record())
        self.tick()
        self.assertEqual(self.typed, [])
        self.bind()
        self.index.unlink()
        self.tick()
        self.tick()
        self.assertEqual(self.typed, ["/rename lagoon"])
        self.assertEqual(self.record()["session_title"], "lagoon")

    def test_auto_name_uses_the_same_delivery(self):
        config.update_session("lagoon", unnamed=True)
        self.assertEqual(orch.rename("lagoon", "fix-api", auto=True), "fix-api")
        self.assertEqual(self.typed, ["/rename fix-api"])
        self.assertEqual(self.record()["session_title"], "fix-api")

    def test_mid_turn_accepts_inline_rename(self):
        self.pane = self.fixture("working")
        orch.rename("lagoon", "quay")
        self.tick()
        self.assertEqual(self.typed, ["/rename quay"])
        self.assertEqual(self.record()["session_title"], "quay")

    def test_mid_turn_refusal_waits_for_prompt_without_spending_retries(self):
        self.pane = self.fixture("working")
        self.confirm = False
        orch.rename("lagoon", "quay")
        for _ in range(5):
            self.tick()
        self.assertEqual(self.typed, ["/rename quay"])
        self.assertEqual(self.record()["title_sync"]["tries"], 1)
        self.assertEqual(self.record()["session_title"], "lagoon")
        self.pane = self.fixture("idle")
        self.confirm = True
        self.tick()
        self.tick()
        self.assertEqual(self.typed, ["/rename quay", "/rename quay"])
        self.assertEqual(self.record()["session_title"], "quay")

    def test_first_prompt_and_generated_names_never_name_the_seat(self):
        for case, step in (("race", "first-prompt"), ("plain", "after-prompt")):
            for already_named in (False, True):
                with self.subTest(case=case, already_named=already_named):
                    self.snapshot(case, step)
                    config.update_session("lagoon", session_title="lagoon" if already_named else None)
                    before = len(self.typed)
                    self.assertEqual(codex.session_title(self.record()), "")
                    self.tick()
                    self.assertEqual(self.seat["name"], "lagoon")
                    self.assertEqual(self.thread_name(), "lagoon")
                    for _ in range(5):
                        self.tick()
                    self.assertEqual(self.typed[before:], ["/rename lagoon"])
                    self.assertNotIn("title_sync", self.record())

    def test_owner_rename_after_prompt_cannot_be_distinguished_from_generation(self):
        # Both writers use name + thread_name with source=cli, so neither names a seat.
        self.snapshot("plain", "owner-rename")
        self.assertEqual(self.thread_name(), "quay")
        self.assertEqual(codex.session_title(self.record()), "")
        self.tick()
        self.tick()
        self.assertEqual(self.seat["name"], "lagoon")
        self.assertEqual(self.thread_name(), "lagoon")
        self.assertEqual(self.typed, ["/rename lagoon"])

    def test_ak_name_before_first_prompt_survives_and_repairs_a_late_auto_name_once(self):
        self.index.unlink()
        config.update_session("lagoon", session_title=None)
        self.tick()
        self.assertEqual(self.typed, ["/rename lagoon"])
        for step in ("named-idle", "after-prompt", "second-prompt"):
            self.snapshot("named", step)
            self.tick()
            self.assertEqual(self.thread_name(), "lagoon")
            self.assertEqual(self.typed, ["/rename lagoon"])
        # A late generator may replace an acknowledged name. Preserve both appends.
        generated = json.loads((REPO / "tests/fixtures/codex-title-prompts.json").read_text())
        self.title(generated["plain"][1]["rows"][0]["name"])
        for _ in range(5):
            self.tick()
        self.assertEqual(self.seat["name"], "lagoon")
        self.assertEqual(self.thread_name(), "lagoon")
        self.assertEqual(self.typed, ["/rename lagoon", "/rename lagoon"])

    def test_refused_repair_stops_after_three_attempts(self):
        self.snapshot("plain", "after-prompt")
        self.confirm = False
        for _ in range(8):
            self.tick()
        self.assertEqual(self.seat["name"], "lagoon")
        self.assertEqual(self.typed, ["/rename lagoon"] * 3)
        self.assertTrue(self.record()["title_sync"]["failed"])

    def test_generated_database_title_never_names_the_seat(self):
        row = json.loads((REPO / "tests/fixtures/codex-title-row.json").read_text())
        with sqlite3.connect(self.home / "state_5.sqlite") as db:
            db.execute("create table threads (id text, title text, name text)")
            db.execute("insert into threads values (?, ?, ?)",
                       (row["id"], "Generated task title", None))
        db.close()
        self.index.unlink()
        self.assertEqual(codex.session_title(self.record()), "")
        self.tick()
        self.assertEqual(self.seat["name"], "lagoon")
        self.assertEqual(codex.session_title(self.record()), "lagoon")

    def test_another_threads_rename_changes_nothing(self):
        self.title("foreign-name", sid="00000000-0000-4000-8000-000000000002")
        self.tick()
        self.assertEqual(self.seat["name"], "lagoon")
        self.assertEqual(self.typed, [])

    def test_unverified_thread_cannot_be_named_or_name_the_seat(self):
        for kind in ("missing-receipt", "wrong-thread", "ambiguous", "wrong-transcript"):
            with self.subTest(kind=kind):
                self.bind()
                record = self.record()
                path = codex.path_for(record)
                receipt = codex.read(record)
                if kind == "missing-receipt":
                    path.unlink()
                else:
                    if kind == "wrong-thread":
                        receipt["event"]["session_id"] = "another-thread"
                    elif kind == "ambiguous":
                        receipt["ambiguous"] = True
                    else:
                        receipt["event"]["transcript_path"] = str(self.root / "absent.jsonl")
                    path.write_text(json.dumps(receipt))
                config.update_session("lagoon", session_title=None)
                self.title("foreign-name")
                self.assertIsNone(watch.follow_title(self.seat))
                self.assertFalse(watch.sync_title(self.seat))
                self.assertEqual(self.typed, [])
                self.assertEqual(self.seat["name"], "lagoon")

    def test_drafts_and_dialogs_are_untouched(self):
        self.snapshot("plain", "after-prompt")
        panes = [self.fixture("composed"), self.fixture("working-composed"),
                 (REPO / "tests/fixtures/codex-dialog-pane.txt").read_text()]
        for confirmed in (None, "lagoon"):
            for pane in panes:
                with self.subTest(confirmed=confirmed, pane=pane):
                    self.pane = pane
                    config.update_session("lagoon", session_title=confirmed)
                    self.assertFalse(watch.sync_title(self.seat))
                    self.assertEqual(self.pane, pane)
                    self.assertEqual(self.keys, [])
        self.pane = self.fixture("idle")
        self.tick()
        self.assertEqual(self.typed, ["/rename lagoon"])

    def test_pending_line_is_not_retyped_or_merged_with_an_owner_draft(self):
        self.drop_enter = True
        orch.rename("lagoon", "quay", log=lambda _: None)
        self.tick()
        self.assertEqual(self.typed, ["/rename quay"])
        self.compose("/rename quay with my own draft")
        before = list(self.keys)
        self.tick()
        self.assertEqual(self.keys, before)
        self.compose("/rename quay")
        self.drop_enter = False
        self.tick()
        self.assertEqual(self.typed, ["/rename quay"])
        self.assertEqual(self.record()["session_title"], "quay")

    def test_working_composer_with_queue_footer_keeps_its_pending_line(self):
        self.drop_enter = True
        orch.rename("lagoon", "quay", log=lambda _: None)
        self.pane = self.fixture("working-composed")
        self.tick()
        self.assertTrue(self.record()["title_sync"]["pending"])
        self.assertEqual(self.typed, ["/rename quay"])
        self.drop_enter = False
        self.tick()
        self.assertEqual(self.record()["session_title"], "quay")
        self.assertEqual(self.typed, ["/rename quay"])

    def test_unreadable_index_does_not_confirm_a_cleared_composer(self):
        self.confirm = False
        self.index.unlink()
        self.index.mkdir()
        orch.rename("lagoon", "quay")
        self.assertEqual(self.typed, ["/rename quay"])
        self.assertEqual(self.record()["session_title"], "lagoon")

    def test_partial_and_unrelated_index_entries_are_not_receipts(self):
        config.update_session("lagoon", title_sync={"name": "quay", "tries": 1, "pending": False})
        self.index.write_text(json.dumps(self.index_fixture()[0]) + "\n[]\ninvalid\n" +
                              json.dumps(self.index_fixture()[1]))
        self.assertEqual(codex.session_title(self.record()), "lagoon")
        with self.index.open("a") as handle:
            handle.write("\n")
        self.assertEqual(codex.session_title(self.record()), "quay")

    def test_actual_launch_home_wins_over_the_watchers_environment(self):
        with patch.dict(os.environ, {"CODEX_HOME": str(self.root / "unrelated")}):
            self.assertEqual(codex.session_title(self.record()), "lagoon")
        other = self.root / ".codex-second"
        other.mkdir()
        self.index = other / "session_index.jsonl"
        with patch.dict(os.environ, {"CODEX_HOME": str(other)}):
            self.bind()
        config.update_session("lagoon", account="second")
        self.title("quay")
        self.tick()
        self.assertEqual(self.seat["name"], "lagoon")
        self.assertEqual(self.record()["session_title"], "lagoon")
        self.assertEqual(self.typed, ["/rename lagoon"])


if __name__ == "__main__":
    unittest.main()
