"""Claude custom titles name seats; fake tmux and transcripts under a temporary HOME."""

import json
from importlib import reload
import os
from pathlib import Path
import re
import unittest
from unittest.mock import ANY, patch

from fixtures.sandbox import REPO, Sandbox
from agentkit import config, orch, watch
from agentkit.harness import claude


class SeatFollowsTitle(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {
            "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0", "AGENTKIT_SESSION": "",
            "CLAUDE_CONFIG_DIR": str(self.root / "unrelated-login"),
            "AK_NOTIFY_SINK": str(self.root / "notices")}))
        self.seat = {"name": "lagoon", "path": str(self.root), "created": 100,
                     "attached": True, "exited": False, "legacy": False}
        self.typed = []
        self.pane = self.fixture("prompt")
        self.stack.enter_context(patch.object(orch, "sessions", side_effect=lambda: [self.seat]))
        self.stack.enter_context(patch.object(orch, "tmux_out", side_effect=self.tmux))
        self.stack.enter_context(patch.object(watch, "KEY_GAP", 0))
        for method in ("poll_worker_token", "seat_account", "stop_nudge", "announce_state"):
            self.stack.enter_context(patch.object(watch, method, return_value=False))
        config.save_session(self.cfg, "lagoon", "opus", ["opus"], {
            "cwd": str(self.root), "conversation": "fake-conversation", "id_source": orch.LAUNCHER,
            "session_title": "lagoon", "account": "default"})
        self.transcript = self.path()

    def fixture(self, kind):
        return (REPO / "tests/fixtures" / f"claude-{kind}-pane.txt").read_text()

    def path(self, account=None, conversation="fake-conversation"):
        directory = self.root / (f".claude-{account}" if account else ".claude")
        slug = re.sub(r"[^A-Za-z0-9]", "-", str(self.root))
        path = directory / "projects" / slug / f"{conversation}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def title(self, title, path=None, conversation="fake-conversation"):
        with (path or self.transcript).open("a") as handle:
            handle.write(json.dumps({"type": "custom-title", "customTitle": title,
                                     "sessionId": conversation}) + "\n")

    def tmux(self, *args, **kwargs):
        if args[0] == "rename-session":
            self.seat = dict(self.seat, name=args[-1])
        elif args[0] == "capture-pane":
            self.assertEqual(args[-1], f"={self.seat['name']}:")
            return 0, self.pane
        elif args[0] == "send-keys":
            self.assertEqual(args[2], f"={self.seat['name']}:")
            if "-l" in args:
                self.typed.append(args[-1])
                self.pane = self.pane.replace("❯\u00a0\n", f"❯ {args[-1]}\n")
            elif args[-1] == "Enter":
                self.pane = self.pane.replace(f"❯ {self.typed[-1]}\n", "❯\u00a0\n")
                self.title(self.typed[-1].removeprefix("/rename "))
        return 0, ""

    def record(self):
        return config.session_records()[self.seat["name"]]

    def read_title(self, start, title):
        original = Path.open
        reads = []

        def opened(path, *args, **kwargs):
            handle = original(path, *args, **kwargs)
            if path == self.transcript:
                read = handle.readline

                def readline(*args):
                    reads.append(handle.tell())
                    return read(*args)

                self.stack.enter_context(patch.object(handle, "readline", readline))
            return handle

        with patch.object(Path, "open", opened):
            self.assertEqual(claude.session_title(self.record()), title)
        self.assertTrue(reads, "transcript was not read line by line")
        self.assertEqual(reads[0], start)
        self.assertTrue(all(position >= start for position in reads))

    def tick(self, dry=False):
        state = watch.load_state()
        watch.health(self.cfg, state, dry, lambda _: None)
        if not dry:
            watch.save_state(state)

    def title_failure(self, method):
        seats = [self.seat, dict(self.seat, name="quay")]
        config.save_session(self.cfg, "quay", "opus", ["opus"], {
            "cwd": str(self.root), "conversation": "fake-quay", "id_source": orch.LAUNCHER,
            "session_title": "quay", "account": "default"})
        self.title("lagoon")
        self.title("quay", self.path(conversation="fake-quay"), "fake-quay")
        original = getattr(watch, method)

        def fail_first(session, log):
            if session["name"] == "lagoon":
                raise config.Error("fake title failure")
            return original(session, log)

        def tmux(*args, **kwargs):
            if args[0] == "capture-pane":
                self.assertIn(args[-1], ("=lagoon:", "=quay:"))
                return 0, self.pane
            return self.tmux(*args, **kwargs)

        logs = []
        with patch.object(orch, "sessions", return_value=seats), \
                patch.object(orch, "tmux_out", side_effect=tmux), \
                patch.object(watch, method, side_effect=fail_first) as titles:
            watch.health(self.cfg, watch.load_state(), False, logs.append)
        self.assertEqual([call.args[0]["name"] for call in titles.call_args_list],
                         ["lagoon", "quay"])
        for action, index in ((watch.seat_account, 1), (watch.stop_nudge, 0),
                              (watch.announce_state, 0)):
            self.assertEqual([call.args[index]["name"] for call in action.call_args_list],
                             ["lagoon", "quay"])
        self.assertTrue(any("lagoon" in line and "fake title failure" in line for line in logs))

    def test_sync_title_failure_leaves_both_seats_health_work_running(self):
        self.title_failure("sync_title")

    def test_follow_title_failure_leaves_both_seats_health_work_running(self):
        self.title_failure("follow_title")

    def test_only_custom_title_candidates_are_parsed(self):
        self.transcript.write_text('{"type":"user","message":"hello"}\n[]\n{"type":\n')
        self.title("Checkout Bug")
        record = self.record()
        with patch.object(config, "session_records", return_value={"lagoon": record}), \
                patch.object(claude.json, "loads", wraps=json.loads) as loads:
            self.assertEqual(claude.session_title(record), "Checkout Bug")
        loads.assert_called_once()
        self.assertEqual(json.loads(loads.call_args.args[0])["type"], "custom-title")

    def test_unchanged_transcript_is_not_read_again_even_in_a_fresh_import(self):
        record = self.record()
        original = Path.open

        def cached_only(path, *args, **kwargs):
            self.assertNotEqual(path, self.transcript, "unchanged transcript was reopened")
            return original(path, *args, **kwargs)

        for title in ("", "Checkout Bug", None):
            with self.subTest(title=title):
                self.transcript.write_bytes(b"\xff" if title is None else
                                            b'{"type":"user","message":"hello"}\n')
                if title:
                    self.title(title)
                self.assertEqual(claude.session_title(record), title)
                reload(claude)
                with patch.object(Path, "open", cached_only):
                    self.assertEqual(claude.session_title(record), title)

    def test_appended_title_is_found_even_with_the_same_mtime(self):
        self.title("Checkout Bug")
        record = self.record()
        self.assertEqual(claude.session_title(record), "Checkout Bug")
        before = self.transcript.stat()
        self.title("Search Fix")
        os.utime(self.transcript, ns=(before.st_atime_ns, before.st_mtime_ns))
        reload(claude)
        self.read_title(before.st_size, "Search Fix")

    def test_appended_messages_keep_the_title_and_read_only_the_addition(self):
        for title in ("", "Checkout Bug", None):
            with self.subTest(title=title):
                (config.STATE / "title-lagoon.json").unlink(missing_ok=True)
                self.transcript.write_bytes(b"\xff\n" if title is None else
                                            b'{"type":"user","message":"hello"}\n')
                if title:
                    self.title(title)
                self.assertEqual(claude.session_title(self.record()), title)
                before = self.transcript.stat().st_size
                with self.transcript.open("a") as handle:
                    handle.write('{"type":"user","message":"more work"}\n')
                self.read_title(before, title)

    def test_half_written_line_is_read_whole_when_finished(self):
        self.title("Checkout Bug")
        before = self.transcript.stat().st_size
        line = json.dumps({"type": "custom-title", "customTitle": "Café Fix",
                           "sessionId": "fake-conversation"}, ensure_ascii=False).encode()
        split = line.index(b"\xc3") + 1
        with self.transcript.open("ab") as handle:
            handle.write(line[:split])
        self.assertEqual(claude.session_title(self.record()), "Checkout Bug")
        with self.transcript.open("ab") as handle:
            handle.write(line[split:])
        self.read_title(before, "Checkout Bug")
        with self.transcript.open("ab") as handle:
            handle.write(b"\n")
        self.read_title(before, "Café Fix")

    def test_replaced_transcript_is_read_from_the_start(self):
        self.title("Checkout Bug")
        self.assertEqual(claude.session_title(self.record()), "Checkout Bug")
        replacement = self.transcript.with_suffix(".new")
        self.title("Search Fix", replacement)
        with replacement.open("a") as handle:
            handle.write('{"type":"user","message":"more work"}\n')
        replacement.replace(self.transcript)
        self.read_title(0, "Search Fix")

    def test_shrunken_or_rewritten_transcript_is_read_from_the_start(self):
        self.title("Checkout Bug")
        self.assertEqual(claude.session_title(self.record()), "Checkout Bug")
        self.transcript.write_text("")
        self.title("Search Fix")
        self.read_title(0, "Search Fix")
        before = self.transcript.stat()
        self.transcript.write_text("")
        self.title("Parser Fix")
        os.utime(self.transcript, ns=(before.st_atime_ns, before.st_mtime_ns + 1))
        self.read_title(0, "Parser Fix")
        self.transcript.write_text('{"type":"user","message":"hello"}\n')
        self.read_title(0, "")

    def test_one_reading_follows_the_seat_and_goes_with_its_files(self):
        self.title("Checkout Bug")
        self.assertEqual(claude.session_title(self.record()), "Checkout Bug")
        cache = config.STATE / "title-lagoon.json"
        reading = cache.read_bytes()
        self.pane = self.fixture("draft")
        orch.rename("lagoon", "quay")
        moved = config.STATE / "title-quay.json"
        self.assertFalse(cache.exists())
        self.assertEqual(moved.read_bytes(), reading)
        self.assertIn(moved, orch.session_owned_files("quay"))
        before = self.transcript.stat().st_size
        self.title("Search Fix")
        self.read_title(before, "Search Fix")
        config.update_session("quay", conversation="next-conversation")
        self.transcript = self.path(conversation="next-conversation")
        self.transcript.write_text('{"type":"user","message":"hello"}\n')
        self.read_title(0, "")
        self.assertEqual(list(config.STATE.glob("title-*.json")), [moved])
        for path in orch.session_owned_files("quay"):
            path.unlink()
        self.assertFalse(moved.exists())
        self.assertEqual(list(config.STATE.glob("title-*.json")), [])

    def test_old_conversation_caches_are_removed_even_without_a_transcript(self):
        old = config.STATE / ("claude-title-" + "a" * 64 + ".json")
        old.write_text("{}\n")
        self.assertIsNone(claude.session_title(self.record()))
        self.assertFalse(old.exists())

    def test_newest_custom_title_renames_and_normalizes_then_its_echo_is_ignored(self):
        self.title("Old Topic")
        self.title("Checkout Bug")
        with self.transcript.open("a") as handle:
            handle.write('{"type":"user","message":"a later message"}\n[]\n{"type":\n')
        with patch.object(orch, "rename", wraps=orch.rename) as rename:
            self.tick()
            rename.assert_called_once_with("lagoon", "checkout-bug", log=ANY)
        self.assertEqual(self.seat["name"], "checkout-bug")
        self.assertEqual(config.resolve_session("lagoon"), "checkout-bug")
        self.assertEqual(self.record()["conversation"], "fake-conversation")
        self.assertEqual(self.typed, ["/rename checkout-bug"])
        self.assertEqual(self.record()["session_title"], "checkout-bug")
        with patch.object(orch, "rename") as rename:
            self.tick()
            self.tick()
            rename.assert_not_called()
        self.assertEqual(self.typed, ["/rename checkout-bug"])

    def test_taken_name_gets_its_variant(self):
        for name in ("checkout-bug", "checkout-bug-2"):
            config.save_session(self.cfg, name, "opus", ["opus"], {
                "cwd": str(self.root), "conversation": f"fake-{name}", "id_source": orch.LAUNCHER})
        self.title("Checkout Bug")
        self.tick()
        self.tick()
        self.assertEqual(self.seat["name"], "checkout-bug-3")
        self.assertEqual(self.typed, ["/rename checkout-bug-3"])

    def test_title_can_take_back_its_seats_former_name(self):
        self.title("Quay")
        self.tick()
        self.title("Lagoon")
        self.tick()
        self.tick()
        self.assertEqual(self.seat["name"], "lagoon")
        self.assertEqual(config.resolve_session("quay"), "lagoon")
        self.assertEqual(config.resolve_session("lagoon"), "lagoon")
        self.assertEqual(self.typed, ["/rename quay", "/rename lagoon"])

    def test_another_seats_former_name_gets_a_variant(self):
        config.save_session(self.cfg, "quay", "opus", ["opus"])
        config.rename_session("quay", "harbor")
        self.title("Quay")
        self.tick()
        self.tick()
        self.assertEqual(self.seat["name"], "quay-2")
        self.assertEqual(config.resolve_session("quay"), "harbor")
        self.assertEqual(self.typed, ["/rename quay-2"])

    def test_agentkits_recorded_title_does_not_rename_the_seat_back(self):
        self.title("lagoon")
        self.pane = self.fixture("draft")
        orch.rename("lagoon", "quay")
        self.assertEqual(self.record()["session_title"], "lagoon")
        before = self.record()
        self.tick()
        self.assertEqual(self.seat["name"], "quay")
        self.assertEqual(self.record(), before)
        self.assertEqual(self.typed, [])
        self.pane = self.fixture("prompt")
        with patch.object(orch, "rename") as rename:
            self.tick()
            self.tick()
            rename.assert_not_called()
        self.assertEqual(self.typed, ["/rename quay"])

    def test_missing_or_unreadable_transcript_changes_nothing(self):
        before = self.record()
        self.tick()
        self.title("Checkout Bug")
        original = Path.open

        def unreadable(path, *args, **kwargs):
            if path == self.transcript:
                raise PermissionError("fake unreadable transcript")
            return original(path, *args, **kwargs)

        with patch.object(Path, "open", unreadable):
            self.tick()
        with self.transcript.open("ab") as handle:
            handle.write(b"\xff\n")
        self.tick()
        self.assertEqual(self.record(), before)
        self.assertEqual(self.seat["name"], "lagoon")
        self.assertEqual(self.typed, [])

    def test_unnamed_seat_counts_as_named_after_the_rename(self):
        config.update_session("lagoon", unnamed=True)
        self.title("Checkout Bug")
        self.tick()
        self.assertEqual(self.seat["name"], "checkout-bug")
        self.assertNotIn("unnamed", self.record())
        before = self.record()
        self.assertIsNone(orch.rename("lagoon", "parser", auto=True))
        self.assertEqual(self.seat["name"], "checkout-bug")
        self.assertEqual(self.record(), before)

    def test_named_login_and_recorded_conversation_select_the_transcript(self):
        self.title("Wrong Login")
        config.update_session("lagoon", account="second")
        self.title("Wrong Conversation", self.path("second", "other-conversation"),
                   "other-conversation")
        self.transcript = self.path("second")
        self.title("Checkout Bug")
        self.title("Wrong Session", conversation="other-conversation")
        self.tick()
        self.assertEqual(self.seat["name"], "checkout-bug")
        self.assertEqual(self.record()["account"], "second")

    def test_other_harnesses_read_no_title(self):
        self.title("Checkout Bug")
        for model in ("astra", "spark"):
            with self.subTest(model=model), patch.object(claude, "session_title") as reader:
                config.update_session("lagoon", orchestrator=model)
                self.tick()
                reader.assert_not_called()
                self.assertEqual(self.seat["name"], "lagoon")
                self.assertEqual(self.typed, [])

    def test_dry_run_and_closed_seat_do_not_rename(self):
        self.title("Checkout Bug")
        self.tick(dry=True)
        self.seat["exited"] = True
        self.tick()
        self.assertEqual(self.seat["name"], "lagoon")
        self.assertEqual(self.typed, [])

    def test_normalized_title_waits_past_a_draft_without_renaming_again(self):
        self.title("Checkout Bug")
        self.pane = self.fixture("draft")
        self.tick()
        self.assertEqual(self.seat["name"], "checkout-bug")
        self.assertEqual(self.typed, [])
        self.pane = self.fixture("prompt")
        self.tick()
        self.tick()
        self.assertEqual(self.seat["name"], "checkout-bug")
        self.assertEqual(self.typed, ["/rename checkout-bug"])

    def test_title_normalizing_to_current_name_still_ends_auto_naming(self):
        config.update_session("lagoon", unnamed=True)
        self.title("Lagoon")
        self.pane = self.fixture("draft")
        self.tick()
        self.assertNotIn("unnamed", self.record())
        self.assertEqual(self.record()["session_title"], "lagoon")
        self.assertEqual(self.typed, [])
        self.pane = self.fixture("prompt")
        self.tick()
        self.tick()
        self.assertEqual(self.seat["name"], "lagoon")
        self.assertNotIn("unnamed", self.record())
        self.assertEqual(self.typed, ["/rename lagoon"])


if __name__ == "__main__":
    unittest.main()
