"""A recorded question must reach the assistant's closing message before its Stop stands.

Real hook calls, invented questions and an isolated HOME; no live seat or notification.
"""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

REPO = Path(__file__).resolve().parents[1]
SEAT = "acme-question"
FIRST = "Keep the current schema? I recommend keeping it while v2 is assessed."
SECOND = "Which account should acme use? Options: 1. Test · 2. Production"


class QuestionInChat(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-question-chat-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        self.state = self.home / ".agentkit/state"
        self.state.mkdir(parents=True)
        self.env = {"PATH": os.environ["PATH"], "HOME": str(self.home),
                    "AGENTKIT_SESSION": SEAT, "AK_RUN_ROLE": "orchestrator"}
        self.write("stop", {"session": SEAT, "turn": time.time() - 60, "blocks": 0})

    def write(self, kind, value):
        (self.state / f"{kind}-{SEAT}.json").write_text(json.dumps(value))

    def read(self, kind):
        return json.loads((self.state / f"{kind}-{SEAT}.json").read_text())

    def kept(self, *texts):
        self.write("seat", {"unasked": {"questions": [
            {"text": text, "at": time.time() - 30} for text in texts]}})

    def stop(self, message, **payload):
        done = subprocess.run(["bash", str(REPO / "hooks/orchestrator-stop.sh")],
                              input=json.dumps({"hook_event_name": "Stop",
                                                "last_assistant_message": message, **payload}),
                              capture_output=True, text=True, env=self.env)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout) if done.stdout.strip() else None

    def test_a_question_hidden_in_tool_output_is_written_before_the_turn_ends(self):
        for message in (None, "", "Waiting for PR #42.", "Waiting for your answer."):
            with self.subTest(message=message):
                self.write("stop", {**self.read("stop"), "blocks": 0})
                self.kept(FIRST)
                answer = self.stop(message)
                self.assertIsNotNone(answer)
                self.assertEqual(answer["decision"], "block")
                self.assertIn(FIRST, answer["reason"])
                self.assertIn("assistant message", answer["reason"])
                self.assertNotIn("ended", self.read("seat")["unasked"]["questions"][0])
                self.assertIsNone(self.stop(FIRST))
                self.assertIn("ended", self.read("seat")["unasked"]["questions"][0])

    def test_every_unanswered_question_and_its_choices_are_written(self):
        self.kept(FIRST, SECOND)
        answer = self.stop(FIRST)
        self.assertIn(SECOND, answer["reason"])
        self.assertNotIn(FIRST, answer["reason"])
        self.assertIsNotNone(self.stop(FIRST + "\nWhich account should acme use?"))
        self.assertIsNone(self.stop("**" + FIRST + "**\n\n" + SECOND.replace(" · ", "\n")))

    def test_the_same_choices_in_a_markdown_list_are_visible(self):
        self.kept(SECOND)
        for choices in ("1. Test\n2. Production", "- Test\n- Production", "* Test\n* Production"):
            with self.subTest(choices=choices):
                self.assertIsNone(self.stop("Which account should acme use?\n\n" + choices))

    def test_a_later_turn_repeats_a_question_still_waiting_for_an_answer(self):
        self.write("notify", {"kind": "needs", "text": FIRST, "time": time.time() - 300})
        self.assertIn(FIRST, self.stop("The other run finished.")["reason"])
        self.assertIsNone(self.stop(FIRST))

    def test_an_answered_question_or_a_watchers_alert_is_not_asked_again(self):
        for extra in ({"answered_at": time.time()}, {"seen": True}, {"watcher": True}):
            with self.subTest(extra=extra):
                self.write("notify", {"kind": "needs", "text": FIRST,
                                      "time": time.time() - 300, **extra})
                self.assertIsNone(self.stop("Finished."))

    def test_background_work_does_not_bury_a_question_at_the_stop(self):
        for key in ("background_tasks", "backgroundTasks"):
            with self.subTest(key=key):
                self.kept(FIRST)
                payload = {key: [{"type": "subagent"}]}
                answer = self.stop("The worker will finish later.", **payload)
                self.assertIn(FIRST, answer["reason"])
                self.assertEqual(self.read("hook")["kind"], "held")
                self.assertNotIn("ended", self.read("seat")["unasked"]["questions"][0])
                self.assertIsNone(self.stop(FIRST, **payload))
                self.assertEqual(self.read("hook")["kind"], "background")
                self.assertIn("ended", self.read("seat")["unasked"]["questions"][0])

    def test_missing_delivery_uses_the_turns_two_block_limit(self):
        for payload in ({}, {"background_tasks": [{"type": "subagent"}]},
                        {"backgroundTasks": [{"type": "subagent"}]}):
            for message in (None, "", "Waiting."):
                with self.subTest(payload=payload, message=message):
                    self.write("stop", {**self.read("stop"), "blocks": 0})
                    self.kept(FIRST)
                    for count in (1, 2):
                        self.assertEqual(self.stop(message, **payload)["decision"], "block")
                        self.assertEqual(self.read("stop")["blocks"], count)
                        self.assertNotIn("ended", self.read("seat")["unasked"]["questions"][0])
                    self.assertIsNone(self.stop(message, **payload))
                    self.assertEqual(self.read("stop")["blocks"], 2)
                    kept = self.read("seat")["unasked"]["questions"]
                    self.assertEqual([q["text"] for q in kept], [FIRST])
                    self.assertIn("ended", kept[0])

    def test_delivery_shares_the_budget_with_a_stop_on_open_work(self):
        (self.state / f"plan-{SEAT}.md").write_text(
            '- [ ] the parser parses · check: `false` · acme · written 2026-10-09 12:00\n')
        self.assertEqual(self.stop("Waiting.")["decision"], "block")
        self.kept(FIRST)
        self.assertIn(FIRST, self.stop("Waiting.")["reason"])
        self.assertIsNone(self.stop("Waiting."))
        self.assertEqual(self.read("stop")["blocks"], 2)

    def test_user_text_and_tool_results_are_not_assistant_delivery(self):
        self.kept(FIRST)
        transcript = self.home / "transcript.jsonl"
        transcript.write_text("\n".join(json.dumps(entry) for entry in [
            {"type": "user", "message": {"role": "user", "content": FIRST}},
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "tool_use", "input": FIRST}]}},
            {"type": "user", "message": {"role": "user", "content": [
                {"type": "tool_result", "content": FIRST}]}}]))
        self.assertIn(FIRST, self.stop(None, transcript_path=str(transcript))["reason"])

    def test_workers_and_subagents_do_not_ask_the_owners_question(self):
        self.kept(FIRST)
        self.assertIsNone(self.stop("Finished.", agent_id="child"))
        self.env["AK_RUN_ROLE"] = "worker"
        self.assertIsNone(self.stop("Finished."))


if __name__ == "__main__":
    unittest.main()
