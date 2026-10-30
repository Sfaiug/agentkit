"""The owner's prompt carries the open questions it may answer, even after compaction.

Offline: the real prompt hook, notify records and typing receipts, in a temporary HOME.
"""

import json
import os
import subprocess
import sys
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from fixtures.sandbox import REPO, Sandbox
from agentkit import config, notify

SEAT = "fix-api"
CONVERSATION = "acme-conversation"
QUESTION = ('Which schema should acme use?\n  Keep "v1", or use v2?\n'
            'The first keeps existing clients working; the second needs their migration. '
            'The migration changes the names, required fields and ordering of the response.')
ASKED = datetime(2026, 10, 16, 12, 34, 56, tzinfo=timezone.utc).timestamp()


class AnswerCarriesQuestion(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.object(config, "HOME", self.root / ".agentkit"))
        for name in ("RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK"):
            self.stack.enter_context(patch.object(config, name, config.HOME / name.lower()))
        config.ensure_dirs()
        config.save_session(self.cfg, SEAT, "opus", ["astra"], {
            "cwd": str(self.root), "conversation": CONVERSATION,
            "id_source": "launcher", "resumable": True})
        rules = config.seat_rulebook(SEAT)
        config.rulebook_path(SEAT).write_text(rules)
        config.update_session(SEAT, rulebook_sha=config.rulebook_digest(rules))

    def ask(self, question=QUESTION, at=ASKED):
        with notify.session_lock(SEAT):
            notify._said(SEAT, "needs", question, at=at)

    def typed(self, text, at=ASKED + 1, source="ak"):
        config.seat_file("input", SEAT).write_text(json.dumps({
            "text": text, "at": at, "source": source, "harness": "claude"}) + "\n")

    def hook(self, *, session=SEAT, role="orchestrator", environ=None, **payload):
        result = subprocess.run(
            ["bash", str(REPO / "hooks/seat-state.sh")],
            input=json.dumps({"hook_event_name": "UserPromptSubmit",
                              "session_id": CONVERSATION, "prompt": "Use v2.", **payload}),
            text=True, capture_output=True, timeout=30,
            env={"HOME": str(self.root), "PATH": os.environ["PATH"],
                 "AGENTKIT_SESSION": session, "AK_RUN_ROLE": role, **(environ or {})})
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        if not result.stdout:
            return ""
        output = json.loads(result.stdout)["hookSpecificOutput"]
        self.assertEqual(output["hookEventName"], "UserPromptSubmit")
        return output["additionalContext"]

    def test_the_answer_carries_the_whole_question_and_when_it_was_asked(self):
        self.ask()
        self.assertEqual(self.hook(hook_event_name="SessionStart", source="compact"), "")
        before = config.notify_path(SEAT).read_bytes()
        # Relaying an owner's answer may hold this lock while the prompt hook runs.
        with notify.session_lock(SEAT):
            context = self.hook()
        self.assertIn(QUESTION, context)
        self.assertIn("2026-10-16 12:34:56 UTC", context)
        self.assertIn("this prompt may answer", context)
        # The foreground hook reads only: answering stays with the background look.
        self.assertEqual(config.notify_path(SEAT).read_bytes(), before)

    def test_context_is_captured_before_the_look_can_answer_the_question(self):
        self.ask()
        scripts = self.root / "bin"
        scripts.mkdir()
        python = scripts / "python3"
        # Resolve immediately after the hook writes its lifecycle fact: a look has already
        # answered by the time the old hook would have read its prompt context.
        python.write_text('''#!/bin/bash
"$TEST_PYTHON" "$@"
result=$?
if [[ $result = 0 && $1 = -c && $2 = *config.record_hook_fact* ]]; then
  "$TEST_PYTHON" -c 'from agentkit import notify; import os; notify.answered(os.environ["AGENTKIT_SESSION"], float(os.environ["ANSWERED_AT"]))'
fi
exit "$result"
''')
        python.chmod(0o755)
        context = self.hook(environ={"PATH": f"{scripts}:{os.environ['PATH']}",
                                    "TEST_PYTHON": sys.executable, "PYTHONPATH": str(REPO),
                                    "ANSWERED_AT": str(ASKED + 7200)})
        self.assertIsNone(notify.last(SEAT))
        self.assertIn(QUESTION, context)

    def test_each_open_question_keeps_its_own_words_and_time(self):
        self.ask()
        second = "Which region should acme use?"
        self.ask(second, ASKED + 3600)
        context = self.hook()
        self.assertIn("2026-10-16 12:34:56 UTC:\n" + QUESTION, context)
        self.assertIn("2026-10-16 13:34:56 UTC:\n" + second, context)
        self.assertLess(context.index(QUESTION), context.index(second))

    def test_a_question_asked_again_uses_its_latest_ask_time(self):
        self.ask()
        self.ask(at=ASKED + 3600)
        context = self.hook()
        self.assertIn("2026-10-16 13:34:56 UTC:\n" + QUESTION, context)
        self.assertNotIn("2026-10-16 12:34:56 UTC", context)

    def test_a_notice_from_before_question_dates_were_recorded_uses_its_time(self):
        notify.record(SEAT, "needs", QUESTION, time=ASKED)
        self.assertIn("2026-10-16 12:34:56 UTC:\n" + QUESTION, self.hook())

    def test_ak_typing_carries_no_question_but_the_owners_relay_does(self):
        self.ask()
        for source in ("ak", "handback", None, "owner"):
            with self.subTest(source=source):
                self.typed("Use v2.", source=source)
                context = self.hook()
                if source == "owner":
                    self.assertIn(QUESTION, context)
                else:
                    self.assertEqual(context, "")
                self.assertIsNotNone(notify.last(SEAT))

    def test_other_typing_and_typing_before_the_question_are_history(self):
        self.ask()
        for text, at in (("Use v2.", ASKED - 1), ("Run fix-parser finished.", ASKED + 1)):
            with self.subTest(text=text, at=at):
                self.typed(text, at=at)
                self.assertIn(QUESTION, self.hook())

    def test_a_hook_newline_keeps_ak_typing_out_of_both_answer_paths(self):
        self.ask()
        self.typed("Use v2.")
        self.assertEqual(self.hook(prompt="Use v2.\n\n"), "")

    def test_no_open_question_carries_nothing(self):
        self.assertEqual(self.hook(), "")
        for kind, extra in (("done", {}), ("needs", {"answered_at": ASKED + 1}),
                            ("needs", {"seen": True}), ("needs", {"watcher": True})):
            with self.subTest(kind=kind, extra=extra):
                notify.record(SEAT, kind, QUESTION, time=ASKED, **extra)
                self.assertEqual(self.hook(), "")

    def test_rulebook_news_and_questions_arrive_together(self):
        self.ask()
        (config.HOME / "rules.md").write_text("A newer rule.\n")
        context = self.hook()
        self.assertIn("it wins", context)
        self.assertIn(QUESTION, context)
        self.typed("Use v2.")
        self.assertEqual(self.hook(), "")

    def test_only_the_seats_own_context_capable_prompt_hears_questions(self):
        self.ask()
        self.assertEqual(self.hook(role="worker"), "")
        self.assertEqual(self.hook(session=""), "")
        self.assertEqual(self.hook(session_id="acme-nested"), "")
        self.assertEqual(self.hook(hook_event_name="Stop"), "")
        config.update_session(SEAT, orchestrator="mimo")
        self.assertEqual(self.hook(), "")

    def test_bookkeeping_and_subagents_are_not_owner_answers(self):
        self.ask()
        for payload in ({"prompt": "/compact"}, {"prompt": "<task-notification>done"},
                        {"prompt": "<system-reminder>done"},
                        {"promptId": "task-completed-acme"}, {"agent_id": "acme-agent"}):
            with self.subTest(payload=payload):
                self.assertEqual(self.hook(**payload), "")
        self.assertIn(QUESTION, self.hook(prompt=None, message="Use v2."))

    def test_a_renamed_seat_carries_its_question(self):
        self.ask()
        config.rename_session(SEAT, "fix-parser")
        self.assertIn(QUESTION, self.hook())


if __name__ == "__main__":
    unittest.main()
