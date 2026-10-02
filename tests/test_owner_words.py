"""Jobs keep original owner input; every transcript and seat here lives in a temporary HOME."""

from contextlib import ExitStack
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, harness, job, notify, orch, watch
from agentkit.harness import claude, codex, grokbuild


def stamp(at):
    return datetime.fromtimestamp(at, timezone.utc).isoformat()


def prompt(at, text, **fields):
    return {"type": "user", "timestamp": stamp(at),
            "message": {"role": "user", "content": text}, **fields}


def update(at, text, *, sid="thread", kind="user_message_chunk", index=0, **meta):
    return {"timestamp": at, "method": "session/update", "params": {
        "sessionId": sid, "update": {"sessionUpdate": kind,
            "content": {"type": "text", "text": text}, "_meta": {"promptIndex": index, **meta}}}}


class OwnerWords(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-owner-words-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "GROK_HOME": str(self.root / ".grok"),
            "AGENTKIT_SESSION": "lagoon", "AGENTKIT_RUN": "", "AK_PARENT_RUN": "",
            "AK_RUN_LOG": "", "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0"}))
        for name in ("HOME", "STATE", "RUNS", "WT", "WORK", "TMP", "SECRETS", "ENV", "CODE"):
            self.stack.enter_context(patch.object(config, name, self.root / ".agentkit" / name.lower()))
        self.stack.enter_context(patch.object(orch, "tmux_out", side_effect=AssertionError("real tmux")))
        self.stack.enter_context(patch.object(orch, "sessions", return_value=[]))
        self.stack.enter_context(patch.object(watch.time, "time", return_value=100))
        self.stack.enter_context(patch.object(watch.time, "sleep"))
        self.stack.enter_context(patch.object(watch, "KEY_GAP", 0))
        self.stack.enter_context(patch.object(watch, "pane_text", return_value=""))
        self.cfg = config.load()
        config.ensure_dirs()
        self.seat = {"name": "lagoon", "created": 10, "legacy": False}
        config.save_session(self.cfg, "lagoon", "opus", ["astra"], {
            "cwd": str(self.root / "acme"), "conversation": "thread", "id_source": harness.LAUNCHER})
        self.path = claude.transcript_path(self.record(), "thread")
        self.path.parent.mkdir(parents=True)
        self.path.touch()
        self.task = self.root / "fix-api.md"
        self.task.write_text("---\nrepo: none\n---\n# Fix API\n\n## Done when\n```bash\n"
                             "python3 -c 'assert True'\n```\n")

    def record(self):
        return config.session_records()[config.current_session()]

    def append(self, *items, path=None):
        with (path or self.path).open("a", encoding="utf-8") as fh:
            for item in items:
                fh.write(json.dumps(item, ensure_ascii=False) + "\n")

    def messages(self):
        record = self.record()
        plugin = orch.seat_plugin(record)
        return plugin.user_messages(record, record["cwd"], plugin.conversation(record),
                                    seat=config.current_session())

    def launch(self):
        directory, receipt = job.job_create(self.cfg, [str(self.task)], {"--anyway": True}, None)
        self.assertEqual(job.read_job(directory), receipt)
        return directory, receipt

    def type(self, text, **kwargs):
        with patch.object(orch, "tmux_out", return_value=(0, "")):
            return watch.type_checked(self.seat, text, lambda _: None, "claude", **kwargs)

    def test_claude_keeps_original_words_and_times_in_order(self):
        text = "  Keep this exact: 雪\nsecond line  "
        self.append(prompt(30, text), prompt(20, [
            {"type": "text", "text": "Earlier"}, {"type": "image", "source": {}},
            {"type": "text", "text": "words"}]),
            {"type": "system", "timestamp": stamp(21), "message": {"content": "notice"}},
            {"type": "assistant", "timestamp": stamp(22), "message": {"content": "answer"}},
            prompt(23, [{"type": "tool_result", "content": "tool output"}]),
            prompt(24, "rules", isMeta=True), prompt(25, "summary", isCompactSummary=True),
            prompt(26, "agent", isSidechain=True), prompt(27, "notice", isVisibleInTranscriptOnly=True),
            prompt(28, 42), {"type": "user", "message": {"role": "user", "content": "no time"}})
        with self.path.open("ab") as fh:
            fh.write(b'not json\n[]\n\xff\n{"type":"user"')
        self.assertEqual(self.messages(), [{"at": 20, "text": "Earlier\nwords"},
                                          {"at": 30, "text": text}])

    def test_codex_uses_submission_events_once_without_user_role_injections(self):
        path = self.root / ".codex" / "rollout.jsonl"
        path.parent.mkdir()
        path.write_text(json.dumps({"type": "session_meta", "payload": {
            "id": "thread", "cwd": str(self.root / "acme")}}) + "\n")
        token = "a" * 32
        config.update_session("lagoon", orchestrator="astra", codex_launch=token,
                              id_source=codex.SOURCE)
        codex.path_for(self.record()).write_text(json.dumps({"launch": token,
            "cwd": str(self.root / "acme"), "expected": "thread", "event": {
                "hook_event_name": "SessionStart", "source": "startup", "session_id": "thread",
                "cwd": str(self.root / "acme"), "transcript_path": str(path)}}))
        self.append({"type": "response_item", "timestamp": stamp(20), "payload": {
            "type": "message", "role": "user", "content": [{"type": "input_text", "text": "rules"}]}},
            {"type": "event_msg", "timestamp": stamp(30), "payload": {
                "type": "user_message", "message": "Use the API.\nExact words.", "images": []}},
            {"type": "response_item", "timestamp": stamp(30), "payload": {
                "type": "message", "role": "user", "content": [
                    {"type": "input_text", "text": "Use the API.\nExact words."}]}},
            {"type": "event_msg", "timestamp": stamp(40), "payload": {
                "type": "user_message", "message": "notice", "is_meta": True}},
            {"type": "response_item", "timestamp": stamp(50), "payload": {
                "type": "function_call_output", "output": "tool output"}}, path=path)
        self.assertEqual(self.messages(), [{"at": 30, "text": "Use the API.\nExact words."}])

    def test_grok_durable_chunks_keep_prompts_and_owner_interjections(self):
        config.update_session("lagoon", orchestrator="grok")
        path = grokbuild.session_dir(self.record()["cwd"], "thread") / "updates.jsonl"
        path.parent.mkdir(parents=True)
        path.touch()
        interjection = update(40, "model framing", index=None, interjection=True)
        interjection["params"]["update"]["content"]["_meta"] = {"displayText": "My exact steering."}
        self.append(update(20, "Keep "), update(20, " "), update(20, "the API."),
            update(21, "answer", kind="agent_message_chunk"),
            update(22, "tool output", kind="tool_call_update"),
            update(23, "notice", hostTurn=True), update(24, "foreign", sid="other"),
            update(30, "Then ship.", index=1), interjection, path=path)
        # chat_history can be compacted or absent without losing the owner's record.
        self.assertEqual(self.messages(), [{"at": 20, "text": "Keep  the API."},
            {"at": 30, "text": "Then ship."}, {"at": 40, "text": "My exact steering."}])

    def test_harness_without_a_reader_and_unopened_conversations_return_none(self):
        for name in ("opencode", "muse", "acme"):
            self.assertEqual(harness.load(name).user_messages({}, None, None), [])
        self.path.unlink()
        self.assertEqual(self.messages(), [])

    def test_typing_receipts_exclude_only_the_recorded_occurrences(self):
        self.append(prompt(100, "continue"))
        self.assertTrue(self.type("continue"))
        self.append(prompt(100, "continue"), prompt(101, "continue"),
                    prompt(102, "Your subscription ran out. An owner can say this too."))
        self.assertTrue(self.type("Yes, ship.", source="owner"))
        self.append(prompt(103, "Yes, ship."))
        self.assertTrue(self.type("Yes, ship."))
        self.append(prompt(104, "Yes, ship."))
        self.assertEqual([message["text"] for message in self.messages()], [
            "continue", "continue", "Your subscription ran out. An owner can say this too.", "Yes, ship."])
        rows = list(harness.entries(config.seat_file("input", "lagoon")))
        self.assertEqual([row["source"] for row in rows], ["ak", "owner", "ak"])
        self.assertEqual([row["after"] for row in rows], [1, 4, 5])

    def test_enter_retry_records_once_and_failed_or_vetoed_typing_records_nothing(self):
        def enter_fails(*args, **_kw):
            return (1, "fake failure") if args[-1] == "Enter" else (0, "")
        with patch.object(orch, "tmux_out", side_effect=enter_fails):
            self.assertFalse(watch.type_checked(self.seat, "ak notice", lambda _: None, "claude"))
        self.assertTrue(self.type("ak notice", pending=True))
        self.append(prompt(101, "ak notice"))
        self.assertEqual(self.messages(), [])
        self.assertEqual(len(list(harness.entries(config.seat_file("input", "lagoon")))), 1)
        with patch.object(orch, "tmux_out", return_value=(1, "fake failure")):
            self.assertFalse(watch.type_checked(self.seat, "owner later", lambda _: None, "claude"))
        self.assertFalse(self.type("owner later", veto=lambda _: True))
        self.append(prompt(102, "owner later"))
        self.assertEqual(self.messages(), [{"at": 102, "text": "owner later"}])

    def test_all_typing_wrappers_use_the_receipt_and_owner_source(self):
        with patch.object(orch, "tmux_out", return_value=(0, "")), \
                patch.object(watch, "at_prompt", return_value=True):
            self.assertTrue(watch.type_into(self.seat, "ak notice", lambda _: None))
            self.append(prompt(101, "ak notice"))
            self.assertTrue(watch.type_at_prompt(self.seat, "Owner reply", lambda _: None, source="owner"))
            self.append(prompt(102, "Owner reply"))
        self.assertEqual(self.messages(), [{"at": 102, "text": "Owner reply"}])

    def test_jobs_save_first_conversation_then_only_new_owner_words(self):
        self.append(prompt(20, "Build the API."), prompt(30, "Keep the names."))
        directory, first = self.launch()
        self.assertEqual(first["owner_words"], self.messages())
        self.assertEqual(first["tasks"][0]["run_id"], None)
        self.assertTrue(self.type("continue"))
        self.append(prompt(100, "continue"), prompt(100, "Use this name."))
        # No process memory or retained job receipt is needed for the launch boundary.
        job.receipt_path(directory).unlink()
        _, second = self.launch()
        self.assertEqual(second["owner_words"], [{"at": 100, "text": "Use this name."}])
        _, third = self.launch()
        self.assertEqual(third["owner_words"], [])

    def test_rename_moves_the_receipts_and_the_job_cursor(self):
        self.append(prompt(20, "Build the API."))
        self.type("ak notice")
        self.append(prompt(30, "ak notice"))
        self.launch()
        config.rename_session("lagoon", "quay")
        self.seat["name"] = "quay"
        self.append(prompt(40, "Next words."))
        _, receipt = self.launch()
        self.assertEqual(receipt["seat"], "quay")
        self.assertEqual(receipt["owner_words"], [{"at": 40, "text": "Next words."}])
        self.assertFalse(config.seat_file("input", "lagoon").exists())

    def test_conversation_change_uses_the_previous_launch_time(self):
        self.append(prompt(20, "Old request."))
        self.type("continue")
        self.append(prompt(30, "continue"))
        self.launch()
        config.update_session("lagoon", conversation="new-thread")
        self.path = self.path.with_name("new-thread.jsonl")
        self.path.touch()
        self.append(prompt(80, "Old context."), prompt(101, "continue"))
        _, receipt = self.launch()
        self.assertEqual(receipt["owner_words"], [{"at": 101, "text": "continue"}])

    def test_byte_cap_keeps_newest_unicode_words_and_exact_suffix(self):
        self.append(prompt(20, "old" * job.OWNER_WORDS_BYTES),
                    prompt(30, "雪\n\"" * job.OWNER_WORDS_BYTES), prompt(40, "Newest words."))
        _, receipt = self.launch()
        words = receipt["owner_words"]
        self.assertLessEqual(len(json.dumps(words, ensure_ascii=False).encode("utf-8")), job.OWNER_WORDS_BYTES)
        self.assertEqual(words[-1], {"at": 40, "text": "Newest words."})
        self.assertEqual(words[0]["at"], 30)
        self.assertTrue(("雪\n\"" * job.OWNER_WORDS_BYTES).endswith(words[0]["text"]))
        self.assertGreater(len(words[0]["text"]), 0)
        # Discarded older words never leak into the following job.
        self.assertEqual(self.launch()[1]["owner_words"], [])

    def test_no_seat_and_unsupported_seats_have_empty_owner_words(self):
        with patch.dict(os.environ, {"AGENTKIT_SESSION": ""}):
            self.assertEqual(self.launch()[1]["owner_words"], [])
        config.update_session("lagoon", orchestrator="mimo")
        self.assertEqual(self.launch()[1]["owner_words"], [])

    def test_failed_job_write_does_not_consume_owner_words(self):
        self.append(prompt(20, "Build the API."))
        with patch.object(job, "save_job", side_effect=OSError("fake write failure")):
            with self.assertRaises(OSError):
                self.launch()
        self.assertNotIn("owner_words_cursor", self.record())
        self.assertEqual(self.launch()[1]["owner_words"], [{"at": 20, "text": "Build the API."}])


if __name__ == "__main__":
    unittest.main(verbosity=2)
