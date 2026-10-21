"""A turn the harness started itself is neither the seat's turn nor the owner's answer.

A sub-agent's prompt runs through the seat's own hooks (Codex: `agent_id`; Grok: `subagentType`)
and ends with a SubagentStop, never the seat's Stop; a turn the harness wakes on finished work
(Grok: `<system-reminder>` under a `task-completed-` or `subagent-completed-` prompt id) is not
the owner typing.  And background work a Stop hands over is a wait under either spelling,
Claude Code's `background_tasks` or Grok Build's `backgroundTasks`.  Offline: real hook input,
fake tmux, a temporary HOME -- the harness of tests/test_answer_closes_question.py.
"""

import json
import unittest

import test_answer_closes_question as answering
from agentkit import config

SEAT = answering.SEAT


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
