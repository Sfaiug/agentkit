"""`/model` typed inside a seat becomes the seat's orchestrator, and a move on `c` stays.

The owner (20 Oct 2026) asked that a model or effort changed inside a session move that
session's own choice, for its orchestrator.  The harness records each answer's model, effort
and time, and only an answer made since the harness in the seat was launched counts: before
that, the conversation still ends on what the model it replaced said.  Offline: a temporary
HOME, transcripts written the way Claude Code and Codex write theirs and OpenCode its
database, no tmux.
"""

from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import config, harness, watch
from agentkit.harness import claude, codex, opencode

NAME, THREAD, LAUNCHED = "acme-api", "6b1d0c4e-0000-4000-8000-00000000000a", 1_800_000_000


def stamp(late):
    """The time `late` seconds after the launch, as a transcript writes one."""
    return datetime.fromtimestamp(LAUNCHED + late, timezone.utc).isoformat()


class SeatFollows(Sandbox):
    def setUp(self):
        super().setUp()
        # a second entry on Opus, one effort down: the one an answer at that effort is on
        self.cfg["models"]["opus-high"] = dict(self.cfg["models"]["opus"], effort="high")
        config.save_session(self.cfg, NAME, "opus", ["astra"], {
            "cwd": str(self.root), "conversation": THREAD, "id_source": harness.LAUNCHER,
            "launched": LAUNCHED})
        self.path = claude.transcript_path(config.session_records()[NAME], THREAD)
        self.path.parent.mkdir(parents=True)

    def looked(self, *said, ask=False):
        """The seat's orchestrator once a look, or the watch's pass where `ask`, has read its
        transcript ending on what was `said`, each (the entry's or a bare model id, seconds after
        the launch, its effort, and more of the entry); a model id is what Claude Code records."""
        ids = {name: entry["model"] for name, entry in self.cfg["models"].items()}
        with self.path.open("a", encoding="utf-8") as fh:
            for model, late, effort, *more in said:
                fh.write(json.dumps({"type": "assistant", "timestamp": stamp(late),
                                     "effort": effort, **(more[0] if more else {}),
                                     "message": {"model": ids.get(model, model)}}) + "\n")
        watch.follow_model(self.cfg, NAME, ask=ask)
        return config.session_records()[NAME]["orchestrator"]

    def test_an_answer_since_the_launch_on_another_model_moves_the_seat(self):
        self.assertEqual(self.looked(("fable", 30, None)), "fable")
        self.assertEqual(self.looked(("opus", 60, "xhigh")), "opus")
        self.assertEqual(self.looked(("opus", 90, "high")), "opus-high")    # `/effort`

    def test_an_effort_typed_inside_becomes_the_seat_s_orchestrator_effort_alone(self):
        def held():
            return config.session_records()[NAME]["efforts"]["opus"]
        config.change_efforts(NAME, lambda data: {"opus": {"effort": "xhigh",
                                                            "review_effort": "max"}})
        self.assertEqual(self.looked(("opus", 30, "low")), "opus")
        self.assertEqual(held(), {"effort": "low", "exec_effort": "xhigh", "review_effort": "max"})
        self.looked(("opus", 60, None))
        self.looked(("opus", 90, "turbo"))          # no effort Opus takes
        self.assertEqual(held()["effort"], "low")

    def test_an_answer_up_to_the_launch_moves_nothing(self):
        self.assertEqual(self.looked(("fable", -30, None)), "opus")
        self.assertEqual(self.looked(("fable", 0, None)), "opus")

    def test_a_seat_launched_before_launches_were_written_down_follows_its_answers(self):
        config.update_session(NAME, launched=None)
        self.assertEqual(self.looked(("fable", -30, None)), "fable")

    def test_what_no_table_names_a_subagent_or_a_transcript_it_cannot_read_moves_nothing(self):
        self.assertEqual(self.looked(("claude-haiku-9", 30, None)), "opus")
        self.assertEqual(self.looked(("fable", 60, None, {"isSidechain": True})), "opus")
        with patch.object(claude, "running", side_effect=PermissionError("denied")):
            self.assertEqual(self.looked(("fable", 90, None)), "opus")

    def test_a_model_no_entry_runs_is_added_to_the_file_as_it_is_and_becomes_the_seat_s(self):
        disk = config.load()
        disk["models"]["kept"] = dict(disk["models"]["opus"], effort="low")    # another's since
        config.save(disk)
        home = sorted(config.HOME.iterdir())
        self.assertEqual(self.looked(("claude-sonnet-5-5", 30, "turbo")), "sonnet")
        self.assertEqual(sorted(config.HOME.iterdir()), home)    # no lock file to collect
        sonnet = {"harness": "claude", "model": "claude-sonnet-5-5", "effort": "max",
                  "provider": "anthropic"}          # no effort Sonnet takes: the last it does
        self.assertEqual(config.load()["models"]["sonnet"], sonnet)
        self.assertIn("kept", config.load()["models"])
        self.assertEqual(self.cfg["models"]["sonnet"], sonnet)      # what the tick reads next

    def test_a_model_claude_s_api_lists_beyond_claude_s_own_table_is_added_by_a_look_too(self):
        # Haiku 5.5 is in Claude's picker and was in no row until 13 Nov 2026
        self.assertEqual(self.looked(("claude-haiku-5-5", 30, "high")), "haiku")
        self.assertEqual(config.load()["models"]["haiku"]["effort"], "high")

    def test_an_id_only_the_table_names_is_added_by_a_pass_that_asks_no_listing(self):
        held = [{"id": "claude-opus-5-5", "label": "Opus 5.5", "efforts": ["high"]}]  # no Sonnet
        with patch.object(config, "catalog_held", return_value=held), \
                patch.object(config, "catalog", side_effect=AssertionError("asked")):
            self.assertEqual(self.looked(("claude-sonnet-5-5", 30, "high"), ask=True), "sonnet")

    def test_a_model_another_look_added_moves_the_seat_there_and_adds_none(self):
        disk = config.load()
        disk["providers"]["acme-login"] = {"mode": "subscription"}      # added with it
        disk["models"]["sonnet-low"] = {"harness": "claude", "model": "claude-sonnet-5-5",
                                        "effort": "low", "provider": "acme-login"}
        config.save(disk)
        self.assertEqual(self.looked(("claude-sonnet-5-5", 30, "high")), "sonnet-low")
        self.assertEqual(config.model(self.cfg, "sonnet-low")["provider"], "acme-login")
        self.assertEqual(config.running(config.load(), "claude", "claude-sonnet-5-5"),
                         ["sonnet-low"])
        self.assertEqual(config.session_records()[NAME]["efforts"]["sonnet-low"]["effort"],
                         "high")

    def test_a_provider_the_file_lost_since_the_config_was_read_adds_nothing(self):
        disk = config.load()
        config.remove_provider(disk, "anthropic")
        config.save(disk)
        self.assertEqual(self.looked(("claude-sonnet-5-5", 30, "high")), "opus")
        self.assertEqual(config.load()["models"], disk["models"])

    def test_an_entry_it_cannot_run_any_provider_s_harness_or_a_failed_save_adds_nothing(self):
        self.cfg["models"]["broken"] = {"harness": "claude", "model": "claude-sonnet-5",
                                        "provider": "anthropic"}            # no effort
        with patch.object(config, "provider_hosts", return_value={"claude": "Claude"}):
            self.assertEqual(self.looked(("claude-sonnet-5", 30, "high")), "opus")
        with patch.object(config, "save", side_effect=OSError("read-only")):
            self.assertEqual(self.looked(("claude-sonnet-5", 60, "high")), "opus")
        self.assertNotIn("sonnet", self.cfg["models"])
        self.assertEqual(self.looked(("claude-sonnet-5", 90, "high")), "sonnet")

    def test_codex_reads_the_model_effort_and_time_of_its_latest_answer(self):
        rollout = self.root / "rollout.jsonl"
        rollout.write_text("".join(json.dumps(line) + "\n" for line in (
            {"type": "turn_context", "timestamp": stamp(5),
             "payload": {"model": "gpt-6-astra", "effort": "high"}},
            {"type": "turn_context", "timestamp": stamp(9),
             "payload": {"model": "gpt-6.1-sol", "effort": "max"}},
            {"type": "event_msg", "timestamp": stamp(12), "payload": {
                "type": "item_completed",
                "item": {"type": "AgentMessage", "content": [{"type": "Text", "text": "ok"}]}}},
            # a later turn that failed before answering, on another model, shows nothing
            {"type": "turn_context", "timestamp": stamp(20),
             "payload": {"model": "gpt-6-astra", "effort": "xhigh"}},
            {"type": "event_msg", "timestamp": stamp(21), "payload": {
                "type": "task_complete", "error": {"message": "usage limit"}}})))
        with patch.object(codex, "transcript", return_value=str(rollout)):
            self.assertEqual(codex.running({}, None, THREAD), ("gpt-6.1-sol", "max", LAUNCHED + 12))

    def test_opencode_reads_its_latest_answer_a_failed_one_and_no_variant_set_among_them(self):
        db, session = self.root / "opencode.db", "ses_0fa1c2d3e4ffAcmeFollow1"
        with closing(sqlite3.connect(db)) as conn, conn:
            conn.executescript((Path(__file__).parent / "fixtures/said-opencode.sql").read_text())
            for seq, model, variant, finish in ((90, "mimo-v2.6-pro", "high", "stop"),
                                                (91, "mimo-v2.6-flash", "default", "error")):
                at = (LAUNCHED + seq) * 1000
                conn.execute("INSERT INTO session_message VALUES (?, ?, 'assistant', ?, ?, ?, ?)",
                             (f"msg_{seq}", session, seq, at, at, json.dumps({
                                 "time": {"created": at}, "finish": finish, "model": {
                                     "id": model, "providerID": "mimo", "variant": variant}})))
        with patch.object(opencode, "database", return_value=db):
            self.assertEqual(opencode.running({}, None, session),
                             ("mimo/mimo-v2.6-flash", None, LAUNCHED + 91))

    def test_codex_settings_apply_without_an_answer_and_a_later_answer_supersedes_them(self):
        rollout = self.root / "rollout.jsonl"
        lines = []

        def read(entry):
            lines.append(entry)
            rollout.write_text("".join(json.dumps(line) + "\n" for line in lines))
            with patch.object(codex, "transcript", return_value=str(rollout)):
                return codex.running({}, None, THREAD)

        settings = {"type": "event_msg", "timestamp": stamp(5), "payload": {
            "type": "thread_settings_applied",
            "thread_settings": {"model": "gpt-6-astra", "reasoning_effort": "low"}}}
        selected = ("gpt-6-astra", "low", LAUNCHED + 5)
        self.assertEqual(read(settings), selected)
        context = {"type": "turn_context", "timestamp": stamp(9),
                   "payload": {"model": "gpt-6.1-sol", "effort": "high"}}
        self.assertEqual(read(context), selected)     # an unanswered turn changes nothing
        answered = {"type": "event_msg", "timestamp": stamp(12), "payload": {
            "type": "item_completed",
            "item": {"type": "AgentMessage", "content": [{"type": "Text", "text": "ok"}]}}}
        self.assertEqual(read(answered), ("gpt-6.1-sol", "high", LAUNCHED + 12))
        self.assertEqual(read({**settings, "timestamp": stamp(15)}),
                         ("gpt-6-astra", "low", LAUNCHED + 15))
        for invalid in (None, "bad", {}, {"model": None}):
            self.assertEqual(read({**settings, "payload": {
                "type": "thread_settings_applied", "thread_settings": invalid}}),
                ("gpt-6-astra", "low", LAUNCHED + 15))
        self.assertEqual(read({**context, "timestamp": stamp(20)}),
                         ("gpt-6-astra", "low", LAUNCHED + 15))
        self.assertEqual(read({**answered, "timestamp": stamp(21)}),
                         ("gpt-6.1-sol", "high", LAUNCHED + 21))
        self.assertEqual(read({**settings, "timestamp": stamp(22)}),
                         ("gpt-6-astra", "low", LAUNCHED + 22))
        self.assertEqual(read({**answered, "timestamp": stamp(23)}),
                         ("gpt-6-astra", "low", LAUNCHED + 22))


if __name__ == "__main__":
    unittest.main()
