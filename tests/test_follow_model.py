"""A model changed inside a seat moves the seat's own choice with it; a move on `c` stays.

The owner (20 Oct 2026): "when the user is inside a session and changes model there and or
effort, the model selection for this session should update accordingly instantly as well.
This really only counts for orchestrator."  Claude Code records each answer's model and effort;
the seat's record takes the configured model running that one.  A move on `c` keeps the
conversation, which still ends on the old model's answer: that is no change to follow.
Offline: a temporary HOME, a transcript written as Claude Code writes one, no tmux.
"""

import json
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import config, harness, watch
from agentkit.harness import claude, codex

SEAT = "fix-api"
CONVERSATION = "3f0c2a5e-0000-4000-8000-000000000002"


class FollowModel(Sandbox):
    def setUp(self):
        super().setUp()
        self.ids = {name: self.cfg["models"][name]["model"] for name in ("opus", "fable")}
        config.save_session(self.cfg, SEAT, "opus", ["astra"], {
            "cwd": str(self.root), "conversation": CONVERSATION, "id_source": harness.LAUNCHER})
        self.transcript = claude.transcript_path(config.session_records()[SEAT], CONVERSATION)
        self.transcript.parent.mkdir(parents=True, exist_ok=True)

    def answered(self, name, effort="xhigh", **extra):
        with self.transcript.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"type": "assistant", "effort": effort, **extra,
                                 "message": {"model": self.ids.get(name, name),
                                             "content": [{"type": "text", "text": "ok"}]}})
                     + "\n")
        watch.follow_model(self.cfg, SEAT)
        return config.session_records()[SEAT]["orchestrator"]

    def test_a_model_typed_in_the_seat_becomes_its_orchestrator(self):
        self.assertEqual(self.answered("opus"), "opus")
        self.assertEqual(self.answered("fable"), "fable")

    def test_a_move_on_c_is_not_undone_by_the_old_models_last_answer(self):
        self.assertEqual(self.answered("opus"), "opus")
        config.update_session(SEAT, orchestrator="fable")      # `c` moved it; nothing answered yet
        watch.follow_model(self.cfg, SEAT)
        self.assertEqual(config.session_records()[SEAT]["orchestrator"], "fable")
        self.assertEqual(self.answered("fable"), "fable")

    def test_a_model_no_entry_runs_and_a_subagents_answer_change_nothing(self):
        self.assertEqual(self.answered("claude-haiku-9"), "opus")
        self.assertEqual(self.answered("fable", isSidechain=True), "opus")


class CodexRunning(Sandbox):
    def test_codex_says_the_model_and_effort_of_its_latest_turn(self):
        rollout = self.root / "rollout.jsonl"
        rollout.write_text("".join(json.dumps(line) + "\n" for line in (
            {"type": "turn_context", "payload": {"model": "gpt-6-astra", "effort": "high"}},
            {"type": "response_item", "payload": {"type": "message"}},
            {"type": "turn_context", "payload": {"model": "gpt-6.1-sol", "effort": "max"}},
            {"type": "response_item", "payload": {"type": "message"}})))
        with patch.object(codex, "transcript", lambda *_args: str(rollout)):
            self.assertEqual(codex.running({}, None, "thread"), ("gpt-6.1-sol", "max"))


if __name__ == "__main__":
    unittest.main()
