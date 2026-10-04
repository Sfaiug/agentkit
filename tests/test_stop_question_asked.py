"""Only a question prompt or a needs notice makes an orchestrator's question visible.

The hooks run against invented transcripts and records in a temporary HOME. No real seat,
process, harness or notification is touched.
"""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

REPO = Path(__file__).resolve().parents[1]
HOOK = REPO / "hooks/orchestrator-stop.sh"
SEAT = "acme-question"
QUESTION = "Which schema should it read?"
ACCEPTED = '{"accepted":true}'   # how Codex records an async question it sent


class StopQuestionAsked(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-stop-question-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        self.state = self.home / ".agentkit/state"
        self.state.mkdir(parents=True)
        self.env = {"PATH": os.environ["PATH"], "HOME": str(self.home),
                    "AGENTKIT_SESSION": SEAT, "AK_RUN_ROLE": "orchestrator"}
        self.turn = time.time() - 60
        self.latch = self.state / f"stop-{SEAT}.json"
        self.latch.write_text(json.dumps({"session": SEAT, "turn": self.turn, "blocks": 0}))
        self.transcript = self.home / "transcript.jsonl"

    def stop(self, said=QUESTION, entries=(), **payload):
        lines = [{"type": "user", "message": {"role": "user", "content": "Build the parser."}},
                 *entries,
                 {"type": "assistant", "message": {"role": "assistant", "content": [
                     {"type": "text", "text": said}]}}]
        self.transcript.write_text("".join(json.dumps(line) + "\n" for line in lines))
        done = subprocess.run(["bash", str(HOOK)], input=json.dumps({
            "hook_event_name": "Stop", "transcript_path": str(self.transcript),
            "last_assistant_message": said, **payload}), text=True, capture_output=True,
            env=self.env)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout) if done.stdout.strip() else None

    def question(self, tool_id="question", **extra):
        return {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": tool_id, "name": "AskUserQuestion", "input": {"questions": [
                {"question": QUESTION}]}}]}, **extra}

    def codex_question(self, tool):
        return {"type": "response_item", "payload": {
            "type": "function_call", "call_id": "question", "name": tool,
            "arguments": json.dumps({"questions": [{"question": QUESTION}]})}}

    def codex_said(self, text):
        """A message submitted to Codex, as its rollout records it: the user response item
        beside the completed UserMessage item, which alone is the owner's words."""
        return [{"type": "response_item", "payload": {"type": "message", "role": "user",
                                                      "content": [{"type": "input_text",
                                                                   "text": text}]}},
                {"type": "event_msg", "payload": {"type": "item_completed", "item": {
                    "type": "UserMessage", "content": [{"type": "text", "text": text}]}}}]

    def codex_output(self, output):
        return {"type": "response_item", "payload": {"type": "function_call_output",
                                                     "call_id": "question", "output": output}}

    def notice(self, when):
        (self.state / f"notify-{SEAT}.json").write_text(json.dumps({
            "session": SEAT, "kind": "needs", "time": when, "text": QUESTION}))

    def test_a_question_only_in_prose_ends_nothing(self):
        """A question mark is no ending: the block names the two ways that alert the owner."""
        for _ in range(2):
            reason = self.stop(background_tasks=[])["reason"]
            self.assertIn("question prompt", reason)
            self.assertIn("ak notify needs", reason)
        self.assertIsNone(self.stop(background_tasks=[]))   # the third stop stands, as always
        self.assertEqual(json.loads(self.latch.read_text())["blocks"], 2)

    def test_a_run_going_ends_the_turn_whatever_its_last_words(self):
        """Reading prose for a question is judgement, not this hook's: the run going decides."""
        run = self.home / ".agentkit/runs/fix-api"
        run.mkdir(parents=True)
        (run / "run.json").write_text(json.dumps({
            "run_id": "fix-api", "launched_session": SEAT, "state": "running"}))
        self.assertIsNone(self.stop())

    def test_a_question_prompt_this_turn_ends_it_without_a_prose_question(self):
        self.assertIsNone(self.stop("Waiting for your answer.", entries=[self.question()]))
        self.assertEqual(json.loads(self.latch.read_text())["blocks"], 0)

    def test_an_unrelated_tool_result_does_not_answer_the_question(self):
        result = {"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "check", "content": "checks passed"}]}}
        self.assertIsNone(self.stop("Waiting for your answer.", entries=[self.question(), result]))

    def test_answered_questions_do_not_exempt_later_stops(self):
        for tool in ("AskUserQuestion", "request_user_input", "functions.request_user_input_async"):
            for ending in ("recommendation", "parked", "prose"):
                with self.subTest(tool=tool, ending=ending):
                    self.setUp()
                    if tool == "AskUserQuestion":
                        entries = [self.question(), {"type": "user", "message": {
                            "role": "user", "content": [{"type": "tool_result",
                                "tool_use_id": "question", "content": "schema-a"}]}}]
                    elif tool.endswith("_async"):
                        # the call's output only says the question went out; the owner's
                        # answer comes back later as the user's own input
                        entries = [self.codex_question(tool), self.codex_output(
                            ACCEPTED), *self.codex_said("schema-a")]
                    else:
                        entries = [self.codex_question(tool), self.codex_output("schema-a")]
                    if ending == "parked":
                        run = self.home / ".agentkit/runs/fix-api"
                        run.mkdir(parents=True)
                        (run / "run.json").write_text(json.dumps({
                            "run_id": "fix-api", "launched_session": SEAT, "state": "interrupted",
                            "started_at": self.turn - 9000, "finished_at": self.turn - 1,
                            "interruption_reason": "the check stopped"}))
                    said = "Should I also migrate the old data?" if ending == "prose" else (
                        "Parser set up on schema-a. Here is my recommendation for the next step.")
                    result = self.stop(said, entries=entries, background_tasks=[])
                    self.assertIsNotNone(result)
                    self.assertEqual(result["decision"], "block")
                    self.assertIn({"recommendation": "Continue: decide the next step",
                                   "parked": "run fix-api parked:", "prose": "question prompt"}
                                  [ending], result["reason"])

    def test_a_new_pending_question_still_ends_a_turn_after_an_answer(self):
        result = {"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "question", "content": "schema-a"}]}}
        self.assertIsNone(self.stop("Waiting for your answer.", entries=[
            self.question(), result, self.question(tool_id="next-question")]))

    def test_an_earlier_or_sidechain_question_prompt_does_not_end_this_turn(self):
        for entries in ([self.question(), {"type": "user", "message": {
                "role": "user", "content": "Now build it."}}],
                [self.question(isSidechain=True)],
                [self.question(), {"type": "user", "message": {"role": "user", "content": [
                    {"type": "text", "text": "Now build it."}]}}]):
            with self.subTest(entries=entries):
                self.setUp()
                self.assertEqual(self.stop(entries=entries)["decision"], "block")

    def test_codex_question_calls_are_scoped_to_the_current_turn(self):
        for tool in ("request_user_input", "functions.request_user_input_async"):
            for old in (False, True):
                with self.subTest(tool=tool, old=old):
                    self.setUp()
                    entries = [{"type": "event_msg", "payload": {"type": "task_started"}},
                               {"type": "response_item", "payload": {
                                   "type": "function_call", "call_id": "question", "name": tool,
                                   "arguments": json.dumps({"questions": [{"question": QUESTION}]})}}]
                    if tool.endswith("_async"):
                        entries.append(self.codex_output(ACCEPTED))
                    if old:
                        entries += self.codex_said("Now build it.")
                    result = self.stop(entries=entries)
                    if old:
                        self.assertEqual(result["decision"], "block")
                    else:
                        self.assertIsNone(result)

    def test_an_async_questions_acknowledgment_is_no_answer(self):
        entries = [{"type": "event_msg", "payload": {"type": "task_started"}},
                   self.codex_question("functions.request_user_input_async"),
                   self.codex_output(ACCEPTED)]
        self.assertIsNone(self.stop(entries=entries))
        # the owner's answer, as Codex records a submitted message, ends that question
        self.setUp()
        entries.append({"type": "event_msg", "payload": {"type": "item_completed", "item": {
            "type": "UserMessage", "content": [{"type": "text", "text": "Use main."}]}}})
        self.assertEqual(self.stop(entries=entries)["decision"], "block")

    def test_a_refused_async_question_asked_nothing(self):
        """Codex records a question it sent as accepted; any other output is a call refused."""
        for output in ("Error parsing function call: missing field `questions`",
                       '{"accepted":false}', ""):
            with self.subTest(output=output):
                self.setUp()
                entries = [{"type": "event_msg", "payload": {"type": "task_started"}},
                           self.codex_question("functions.request_user_input_async"),
                           self.codex_output(output)]
                self.assertEqual(self.stop("Waiting for your answer.", entries=entries)["decision"],
                                 "block")

    def asked(self):
        return [{"type": "event_msg", "payload": {"type": "task_started"}},
                self.codex_question("functions.request_user_input_async"),
                self.codex_output(ACCEPTED)]

    def test_a_question_stays_open_past_any_amount_of_later_output(self):
        output = {"type": "response_item", "payload": {"type": "function_call_output",
                                                       "call_id": "check", "output": "x" * 65536}}
        self.assertIsNone(self.stop(entries=[*self.asked(), *[output] * 1100]))

    def test_harness_bookkeeping_answers_nothing(self):
        """Lines a harness writes in the user's role that are not the owner's words."""
        def user(content, **fields):
            return {"type": "user", "message": {"role": "user", "content": content}, **fields}
        frames = [user("Internal rules.", isMeta=True),
                  user("Internal summary.", isCompactSummary=True),
                  user("Internal notice.", isVisibleInTranscriptOnly=True),
                  user("Background check passed.", origin={"kind": "task-notification"}),
                  user([{"type": "tool_result", "tool_use_id": "check", "content": "passed"},
                        {"type": "text", "text": "<system-reminder>Rules.</system-reminder>"}]),
                  user("<local-command-stdout>Compacted</local-command-stdout>"),
                  {"type": "response_item", "payload": {"type": "message", "role": "user",
                                                        "content": [{"type": "input_text",
                                                                     "text": "<environment_context>"
                                                                     "</environment_context>"}]}}]
        for frame in frames:
            for question in ([self.question()], self.asked()):
                with self.subTest(frame=frame, question=question[-1]):
                    self.setUp()
                    self.assertIsNone(self.stop(entries=[*question, frame]))

    def test_only_a_needs_notice_recorded_this_turn_ends_the_question(self):
        self.notice(self.turn - 1)
        self.assertEqual(self.stop()["decision"], "block")
        self.notice(self.turn + 1)
        self.assertIsNone(self.stop())

    def test_a_harness_with_no_transcript_is_told_to_use_notify_needs(self):
        self.assertIn("ak notify needs", self.stop(transcript_path="")["reason"])

if __name__ == "__main__":
    unittest.main(verbosity=2)
