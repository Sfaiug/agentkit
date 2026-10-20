"""`/model` typed inside a seat becomes the seat's orchestrator, and a move on `c` stays.

The owner (20 Oct 2026) asked that a model or effort changed inside a session move that
session's own choice, for its orchestrator.  The harness records each answer's model, effort
and time, and only an answer made since the harness in the seat was launched counts: before
that, the conversation still ends on what the model it replaced said.  Offline: a temporary
HOME, transcripts written the way Claude Code and Codex write theirs, no tmux.
"""

from datetime import datetime, timezone
import json
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import config, harness, watch
from agentkit.harness import claude, codex

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

    def looked(self, *said):
        """The seat's orchestrator once a look has read its transcript ending on what was
        `said`, each (the entry's or a bare model id, seconds after the launch, its effort,
        and more of the entry); a model id is what Claude Code records."""
        ids = {name: entry["model"] for name, entry in self.cfg["models"].items()}
        with self.path.open("a", encoding="utf-8") as fh:
            for model, late, effort, *more in said:
                fh.write(json.dumps({"type": "assistant", "timestamp": stamp(late),
                                     "effort": effort, **(more[0] if more else {}),
                                     "message": {"model": ids.get(model, model)}}) + "\n")
        watch.follow_model(self.cfg, NAME)
        return config.session_records()[NAME]["orchestrator"]

    def test_an_answer_since_the_launch_on_another_model_moves_the_seat(self):
        self.assertEqual(self.looked(("fable", 30, None)), "fable")
        self.assertEqual(self.looked(("opus", 60, "xhigh")), "opus")
        self.assertEqual(self.looked(("opus", 90, "high")), "opus")    # `/effort`: its own
        self.assertEqual(config.session_records()[NAME]["effort"], "high")
        config.update_session(NAME, orchestrator="fable")
        self.assertEqual(self.looked(("opus", 120, "high")), "opus-high")  # an entry at it

    def test_an_answer_up_to_the_launch_moves_nothing(self):
        self.assertEqual(self.looked(("fable", -30, None)), "opus")
        self.assertEqual(self.looked(("fable", 0, None)), "opus")

    def test_a_seat_launched_before_launches_were_written_down_follows_its_answers(self):
        config.update_session(NAME, launched=None)
        self.assertEqual(self.looked(("fable", -30, None)), "fable")

    def test_what_no_entry_runs_a_subagent_or_a_transcript_it_cannot_read_moves_nothing(self):
        self.assertEqual(self.looked(("claude-haiku-9", 30, None)), "opus")
        self.assertEqual(self.looked(("fable", 60, None, {"isSidechain": True})), "opus")
        with patch.object(claude, "running", side_effect=PermissionError("denied")):
            self.assertEqual(self.looked(("fable", 90, None)), "opus")

    def test_codex_reads_its_latest_turns_model_effort_and_time(self):
        rollout = self.root / "rollout.jsonl"
        rollout.write_text("".join(json.dumps(line) + "\n" for line in (
            {"type": "turn_context", "timestamp": stamp(5),
             "payload": {"model": "gpt-6-astra", "effort": "high"}},
            {"type": "turn_context", "timestamp": stamp(9),
             "payload": {"model": "gpt-6.1-sol", "effort": "max"}},
            {"type": "event_msg", "timestamp": stamp(12), "payload": {"type": "agent_message"}})))
        with patch.object(codex, "transcript", return_value=str(rollout)):
            self.assertEqual(codex.running({}, None, THREAD), ("gpt-6.1-sol", "max", LAUNCHED + 9))


if __name__ == "__main__":
    unittest.main()
