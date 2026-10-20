"""A turn the harness started itself is neither the seat's turn nor the owner's answer.

A sub-agent's prompt runs through the seat's own hooks (Codex: `agent_id`; Grok: `subagentType`)
and ends with a SubagentStop, never the seat's Stop; a turn the harness wakes on finished work
(Grok: `<system-reminder>` under a `task-completed-` or `subagent-completed-` prompt id) is not
the owner typing, and nor is one Claude Code begins on its own, which only its transcript marks.
And background work a Stop hands over is a wait under either spelling, Claude Code's
`background_tasks` or Grok Build's `backgroundTasks`.  Offline: real hook input, fake tmux, a
temporary HOME -- the harness of tests/test_answer_closes_question.py.
"""

from datetime import datetime, timezone
import json
import unittest

import test_answer_closes_question as answering
from agentkit import config
from agentkit.harness import claude

SEAT = answering.SEAT
CONVERSATION = "0c0ffee0-0000-4000-8000-00000000acme"
# The turns Claude Code 2.1.302 begins in a seat by itself, as its transcript writes each one.
CLAUDE_TURNS = {
    "a notice that a message was refused": {
        "isMeta": True, "promptSource": "system", "turnOrigin": "system",
        "text": "[Cross-session delivery notice] Your message to another session was refused."},
    "another session's message": {
        "isMeta": True, "promptSource": "system", "turnOrigin": "peer",
        "origin": {"kind": "peer", "name": "acme-other"},
        "text": "Another Claude session sent a message: <cross-session-message>The parser "
                "merged.</cross-session-message>"},
    "a scheduled check-in": {
        "isMeta": True, "promptSource": "system", "turnOrigin": "scheduled",
        "text": "Morning check: is acme's parser live?"},
    "a usage window's reset": {
        "isMeta": True, "promptSource": "system", "turnOrigin": "auto_continuation",
        "origin": {"kind": "auto-continuation"},
        "text": "Your usage limit has reset. Continue the task you were working on."},
}
OWNER = {"promptSource": "typed", "turnOrigin": "human", "origin": {"kind": "human"}}


class HarnessStartedTurns(answering.AnswerClosesQuestion):

    def test_a_sub_agents_prompt_is_not_the_seats_turn_nor_its_answer(self):
        self.notice()
        before = config.stop_path(SEAT).read_text() if config.stop_path(SEAT).exists() else None
        for marker in ({"agent_id": "acme-agent", "agent_type": "worker"},
                       {"agent_type": "worker"}, {"subagentType": "general"}):
            with self.subTest(marker=marker):
                self.hook("UserPromptSubmit", wait=False, env={"TMUX": "", "TMUX_PANE": ""},
                          prompt="Read fix-api's schema.", **marker)
                self.assertEqual(config.stop_path(SEAT).read_text()
                                 if config.stop_path(SEAT).exists() else None, before)
                self.assertNotEqual(json.loads(config.hook_facts_path(SEAT).read_text())
                                    .get("event") if config.hook_facts_path(SEAT).exists()
                                    else None, "UserPromptSubmit")
        self.assert_open()

    def test_a_sub_agents_stop_is_not_judged_nor_written_down(self):
        self.prompt()
        before = config.stop_path(SEAT).read_text()
        for marker in ({"agent_id": "acme-agent"}, {"subagentType": "general"}):
            with self.subTest(marker=marker):
                output = self.hook("Stop", script="orchestrator-stop.sh", background_tasks=[],
                                   last_assistant_message="Fix-api's schema is read.", **marker)
                self.assertEqual(output, "")
                self.assertEqual(config.stop_path(SEAT).read_text(), before)
                self.assertNotEqual(json.loads(config.hook_facts_path(SEAT).read_text())
                                    .get("event"), "Stop")

    def test_a_turn_the_harness_woke_on_finished_work_leaves_the_question_open(self):
        self.notice()
        for payload in ({"prompt": "<system-reminder>\nBackground task acme-build completed",
                         "promptId": "task-completed-1"},
                        {"prompt": "<system-reminder>\nA background subagent completed",
                         "promptId": "subagent-completed-2"},
                        {"prompt": "Background work is done.", "promptId": "task-completed-3"}):
            with self.subTest(payload=payload):
                self.prompt(**payload)
                self.assert_open()

    def said(self, text, at, **marks):
        """One prompt in the seat's Claude conversation, written down before its hook hears it."""
        path = claude.transcript_path({"cwd": str(self.root)}, CONVERSATION)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as fh:
            fh.write(json.dumps({"type": "user", **marks,
                                 "timestamp": datetime.fromtimestamp(at, timezone.utc).isoformat(),
                                 "message": {"role": "user", "content": text}}) + "\n")

    def test_a_turn_claude_code_began_leaves_the_question_open(self):
        """20 Oct 2026: a seat asked the owner, and a second later Claude Code began a turn to
        say a message to another session was refused.  Its prompt hook hears such a turn as it
        hears the owner, so the question was closed before its card went out.  The seat's
        conversation marks whose each one is: only a message of the owner's, written after the
        question, answers it."""
        config.save_session(self.cfg, SEAT, "opus", ["astra"], {
            "cwd": str(self.root), "session_title": SEAT, "conversation": CONVERSATION})
        self.said("Fix the parser.", 9000, **OWNER)
        self.notice()                                       # asked at the sandbox's 10000
        for after, (kind, turn) in enumerate(CLAUDE_TURNS.items(), 1):
            with self.subTest(kind=kind):
                marks = {key: value for key, value in turn.items() if key != "text"}
                self.said(turn["text"], 10000 + after, **marks)
                self.prompt(prompt=turn["text"])
                self.assert_open()
        self.said("Use the second schema.", 10010, **OWNER)
        self.prompt()
        self.assert_answered()

    def test_the_owners_own_prompt_still_answers_it(self):
        self.notice()
        self.prompt(prompt="Use the second schema.", promptId="acme-owner-4")
        self.assert_answered()

    def test_background_work_is_a_wait_under_either_spelling(self):
        for field in ("background_tasks", "backgroundTasks"):
            with self.subTest(field=field):
                self.prompt()
                self.hook("Stop", script="orchestrator-stop.sh",
                          last_assistant_message="Acme's build runs in the background.",
                          **{field: [{"type": "subagent", "status": "running"}]})
                fact = json.loads(config.hook_facts_path(SEAT).read_text())
                self.assertEqual((fact["event"], fact["kind"]), ("Stop", "background"), fact)


def load_tests(loader, tests, pattern):
    """Only this file's own cases: the harness's own run in tests/test_answer_closes_question.py."""
    return unittest.TestSuite(HarnessStartedTurns(name) for name in vars(HarnessStartedTurns)
                              if name.startswith("test_"))


if __name__ == "__main__":
    unittest.main()
