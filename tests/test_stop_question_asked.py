"""Only a question prompt or a needs notice makes an orchestrator's question visible.

The hooks run against invented transcripts and records in a temporary HOME. No real seat,
process, harness or notification is touched.
"""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

REPO = Path(__file__).resolve().parents[1]
HOOK = REPO / "hooks/orchestrator-stop.sh"
SEAT_STATE = REPO / "hooks/seat-state.sh"
SEAT = "acme-question"
QUESTION = "Which schema should it read?"


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

    def prompt(self, text):
        done = subprocess.run(["bash", str(SEAT_STATE)], input=json.dumps({
            "hook_event_name": "UserPromptSubmit", "prompt": text}),
            text=True, capture_output=True, env=self.env)
        self.assertEqual(done.returncode, 0, done.stderr)

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

    def test_the_watcher_correction_shares_the_two_block_limit(self):
        self.assertEqual(self.stop("A recommendation.")["decision"], "block")
        self.assertIn("tmux", self.stop("Waiting for the watcher.", background_tasks=[
            {"id": "watcher", "command": "sleep 3600"}])["reason"])
        self.assertIsNone(self.stop("A recommendation."))
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
                            "Question sent to the user."), *self.codex_said("schema-a")]
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
                   self.codex_output("Question sent to the user.")]
        self.assertIsNone(self.stop(entries=entries))
        # the owner's answer, as Codex records a submitted message, ends that question
        self.setUp()
        entries.append({"type": "event_msg", "payload": {"type": "item_completed", "item": {
            "type": "UserMessage", "content": [{"type": "text", "text": "Use main."}]}}})
        self.assertEqual(self.stop(entries=entries)["decision"], "block")

    def asked(self):
        return [{"type": "event_msg", "payload": {"type": "task_started"}},
                self.codex_question("functions.request_user_input_async"),
                self.codex_output("Question sent to the user.")]

    def test_only_the_owners_own_input_answers_an_async_question(self):
        """Another session's message, a task notification or a report ak typed leaves it open,
        however Codex marks the turn it opened; the owner's reply answers it."""
        peer = '<cross-session-message from="acme-api">The parser checks passed.</cross-session-message>'
        notification = "<task-notification>The parser checks passed.</task-notification>"
        report = "Run fix-parser finished: PASS. Decide the next step."
        for text in (peer, notification, report):
            for opening in ([], [{"type": "event_msg", "payload": {"type": "task_started"}}],
                            [{"type": "event_msg", "payload": {"type": "user_message",
                                                               "message": text}}]):
                with self.subTest(text=text, opening=opening):
                    self.setUp()
                    if text == report:
                        self.typed(report)
                    self.prompt(text)
                    self.assertIsNone(self.stop(entries=[*self.asked(), *opening,
                                                         *self.codex_said(text)]))
        self.setUp()
        self.prompt(peer)
        self.prompt(notification)
        entries = [*self.asked(), *self.codex_said(peer), *self.codex_said(notification)]
        self.assertIsNone(self.stop(entries=entries))
        self.prompt("Use schema-a.")
        self.assertEqual(self.stop(entries=[*entries, *self.codex_said("Use schema-a.")])
                         ["decision"], "block")

    def typed(self, text, age=0):
        (self.state / f"input-{SEAT}.jsonl").write_text(json.dumps(
            {"at": time.time() - age, "text": text, "source": "ak"}) + "\n")

    def test_a_report_ak_typed_long_ago_is_still_ak_s(self):
        """ak may press Enter on a line it typed well after typing it."""
        report = "Run fix-parser finished: PASS. Decide the next step."
        self.typed(report, age=7200)
        self.prompt(report)
        self.assertIsNone(self.stop(entries=[*self.asked(), *self.codex_said(report)]))

    def test_the_owners_answer_stands_when_ak_later_types_the_same_words(self):
        """Each prompt not the owner's is looked past once: ak's `continue` hides only itself."""
        self.prompt("continue")
        entries = [*self.asked(), *self.codex_said("continue")]
        self.assertEqual(self.stop("Here is my recommendation.", entries=entries)["decision"],
                         "block")
        self.setUp()
        self.prompt("continue")
        self.typed("continue")
        self.prompt("continue")
        entries += [{"type": "response_item", "payload": {"type": "message", "role": "assistant",
                                                          "content": [{"type": "output_text",
                                                                       "text": "On it."}]}},
                    *self.codex_said("continue")]
        self.assertEqual(self.stop("Here is my recommendation.", entries=entries)["decision"],
                         "block")

    def test_a_question_stays_open_however_many_messages_arrive(self):
        texts = [f'<cross-session-message from="acme-api">Check {number} passed.'
                 "</cross-session-message>" for number in range(200)]
        self.latch.write_text(json.dumps({"session": SEAT, "turn": self.turn, "blocks": 0,
                                          "others": [hashlib.sha256(text.encode()).hexdigest()
                                                     for text in texts[:-1]]}))
        self.prompt(texts[-1])
        # the prompt hook keeps every one until the owner speaks again
        self.assertEqual(len(json.loads(self.latch.read_text())["others"]), len(texts))
        self.assertIsNone(self.stop(entries=[*self.asked(), *(
            entry for text in texts for entry in self.codex_said(text))]))

    def test_a_renamed_seat_keeps_its_record_relaunched_under_the_new_name(self):
        peers = [f'<cross-session-message from="acme-api">Check {number} passed.'
                 "</cross-session-message>" for number in range(3)]
        self.prompt(peers[0])
        (self.state / f"session-{SEAT}.json").write_text(json.dumps({"renamed": "acme-renamed"}))
        self.latch.replace(self.state / "stop-acme-renamed.json")     # as the rename moves it
        self.prompt(peers[1])
        self.env["AGENTKIT_SESSION"] = "acme-renamed"
        self.prompt(peers[2])
        self.latch = self.state / "stop-acme-renamed.json"
        self.assertEqual(len(json.loads(self.latch.read_text())["others"]), 3)
        self.assertIsNone(self.stop(entries=[*self.asked(), *(
            entry for text in peers for entry in self.codex_said(text))]))

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

    def test_a_command_that_starts_with_a_loop_or_a_sleep_gets_one_correction(self):
        for command in ("while true; do bin/ak run status; sleep 30; done",
                        "until test -f ready; do sleep 1; done",
                        "for task in a b; do bin/ak run status; done",
                        "sleep 3600", "/bin/sleep 3600", "  sleep 60 && bin/ak run status",
                        "for((i=0;i<10;i++)); do sleep 1; done", "while((1)); do sleep 60; done",
                        "while(true); do sleep 60; done", "until(false); do sleep 60; done",
                        "while>/dev/null true; do sleep 60; done",
                        "until</dev/null false; do sleep 60; done",
                        "while\\\n true; do sleep 60; done", "for\\\n task in a b; do sleep 1; done",
                        "\\\nsleep 60", "sleep\\\n 60"):
            with self.subTest(command=command):
                self.setUp()
                tasks = [{"id": "watcher", "type": "shell", "command": command}]
                first = self.stop("Waiting for the watcher.", background_tasks=tasks)
                self.assertEqual(first["decision"], "block")
                self.assertIn("ak run", first["reason"])
                self.assertIn("tmux", first["reason"])
                self.assertEqual(json.loads((self.state / f"hook-{SEAT}.json").read_text())
                                 ["kind"], "held")
                self.assertIsNone(self.stop("Waiting for the watcher.", background_tasks=tasks))
                self.assertEqual(json.loads(self.latch.read_text())["blocks"], 1)
                self.assertEqual(json.loads((self.state / f"hook-{SEAT}.json").read_text())
                                 ["kind"], "")

    def test_finite_commands_and_background_agents_still_end_a_turn(self):
        for task in ({"id": "check", "type": "shell", "command": "python3 tests/test_api.py"},
                     {"id": "loop", "type": "shell",
                      "command": "python3 -c 'for value in range(3): print(value)'"},
                     {"id": "quoted", "type": "shell",
                      "command": "printf '%s\\n' 'example; sleep 3600'"},
                     {"id": "review", "type": "subagent", "description": "Review the parser"}):
            with self.subTest(task=task):
                self.assertIsNone(self.stop("Waiting for the checks.", background_tasks=[task]))
                self.assertEqual(json.loads((self.state / f"hook-{SEAT}.json").read_text())
                                 ["kind"], "background")

    def test_finite_work_stays_a_wait_beside_a_sleeping_watcher(self):
        payload = json.loads((REPO / "tests/fixtures/claude-stop-background.json").read_text())
        self.assertIn("tmux", self.stop(payload["last_assistant_message"],
                                       background_tasks=payload["background_tasks"])["reason"])
        self.assertIsNone(self.stop(payload["last_assistant_message"],
                                    background_tasks=payload["background_tasks"]))
        self.assertEqual(json.loads((self.state / f"hook-{SEAT}.json").read_text())
                         ["kind"], "background")

    def test_a_new_prompt_resets_the_correction(self):
        self.assertEqual(self.stop()["decision"], "block")
        done = subprocess.run(["bash", str(SEAT_STATE)], input=json.dumps({
            "hook_event_name": "UserPromptSubmit", "prompt": "Build the parser."}),
            text=True, capture_output=True, env=self.env)
        self.assertEqual(done.returncode, 0, done.stderr)
        # the owner's new request starts the count again, with its own one nudge
        self.assertIn("did not end on a question", self.stop()["reason"])
        self.assertEqual(json.loads(self.latch.read_text())["blocks"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
