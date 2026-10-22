"""An owner's prompt is told which open questions it may answer; a prompt that is not his is not.

A seat asks with `ak notify needs` and works on, so the prompt that answers may come turns later,
when the seat no longer has the question in view: the prompt hook hands the harness each question
still open, whole and dated, as that prompt's context, so the seat reads the owner's words as the
answer they are.  A slash command, a turn the harness begins on finished work, another
conversation inside the seat and a worker's prompt are no owner's answer and are told nothing.
The seat has said it read its rulebook, so a prompt carries no rulebook news beside it.
Black-box: Claude's hooks as ak's adapter registers them (tests/fixtures/hookdrive.py), fired
outside the seat's pane, so no look answers the question between prompts; this test fails
against `/bin/false`.
"""

from datetime import datetime, timezone
import json
import math
import re
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.hookdrive import Hooks

QUESTION = "Which schema should the parser read?"
HEAD = "Questions you asked the owner that this prompt may answer:\n\n"
ASKED = re.compile(r"Asked (\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) UTC:\n")


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class AnswerContext(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.hooks = Hooks(cls.home)

    def acknowledged(self, name):
        """A seat whose conversation said it read the rulebook its first prompt named."""
        Seat(self.home, name)
        fired = self.prompt(name, "hello")
        code = re.search(r"`ak orch rules (\S+)`", fired.said[0]["hookSpecificOutput"]
                         ["additionalContext"]).group(1)
        done = self.home.ak("orch", "rules", code, env={"AGENTKIT_SESSION": name})
        self.assertEqual(done.code, 0, done.err)

    def ask(self, name, question):
        """The seat's question, and the moments just before and after it was asked."""
        before = time.time()
        done = self.home.ak("notify", "needs", question, "--session", name,
                            env={"AK_NOTIFY_SINK": "off"})
        self.assertEqual(done.code, 0, done.err)
        return math.floor(before), time.time()

    def prompt(self, name, words, *, conversation=None, env=None, **payload):
        fired = self.hooks.fire("UserPromptSubmit", {
            "prompt": words, "session_id": conversation or f"conv-{name}", **payload},
            seat=name, env=env)
        self.assertEqual(fired.code, 0, fired.err)
        return fired

    def context(self, fired):
        """The one answer the harness reads back, as its prompt context."""
        answer, = fired.said
        self.assertEqual(answer["hookSpecificOutput"]["hookEventName"], "UserPromptSubmit")
        return answer["hookSpecificOutput"]["additionalContext"]

    def stamps(self, context):
        return [datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=timezone.utc).timestamp() for stamp in ASKED.findall(context)]

    def test_an_owner_s_prompt_is_told_the_open_question_and_when_it_was_asked(self):
        self.acknowledged("acme")
        before, after = self.ask("acme", QUESTION)
        notice = json.loads((self.home.path / ".agentkit/state/notify-acme.json").read_text())
        self.assertEqual(notice["kind"], "needs")
        self.assertEqual(self.prompt("acme", "/compact").out, "")
        context = self.context(self.prompt("acme", "the new one"))
        self.assertRegex(context, r"\AQuestions you asked the owner that this prompt may answer:"
                                  r"\n\nAsked \d{4}-\d\d-\d\d \d\d:\d\d:\d\d UTC:\n"
                                  r"Which schema should the parser read\?\Z")
        stamp, = self.stamps(context)
        self.assertTrue(before <= stamp <= after, (before, stamp, after))

    def test_a_prompt_that_is_no_owner_s_answer_is_told_nothing(self):
        self.acknowledged("fix-api")
        self.ask("fix-api", QUESTION)
        cases = {"a slash command": ("/compact", {}),
                 "a slash command after spaces": ("  /model opus", {}),
                 "a task's notification": ("<task-notification>done</task-notification>", {}),
                 "a system reminder": ("<system-reminder>later</system-reminder>", {}),
                 "a finished task's turn": ("the new one", {"prompt_id": "task-completed-1"}),
                 "another conversation": ("the new one", {"conversation": "conv-other"}),
                 "a worker": ("the new one", {"env": {"AK_RUN_ROLE": "worker"}})}
        for case, (words, extra) in cases.items():
            with self.subTest(case):
                self.assertEqual(self.prompt("fix-api", words, **extra).out, "")
        self.assertIn(QUESTION, self.context(self.prompt("fix-api", "the new one")))

    def test_each_question_asked_before_the_owner_answered_is_told_in_the_order_asked(self):
        self.acknowledged("beta")
        before, _ = self.ask("beta", "Which branch?")
        self.ask("beta", "And which schema?\n  v1 or v2?")
        # asked again in other spelling, a question is told once, in its first words
        _, after = self.ask("beta", "Which  BRANCH?")
        context = self.context(self.prompt("beta", "main, and v2"))
        self.assertEqual(ASKED.sub("Asked <when> UTC:\n", context),
                         HEAD + "Asked <when> UTC:\nWhich branch?\n\n"
                                "Asked <when> UTC:\nAnd which schema?\n  v1 or v2?")
        for stamp in self.stamps(context):
            self.assertTrue(before <= stamp <= after, (before, stamp, after))


if __name__ == "__main__":
    unittest.main()
