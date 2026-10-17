"""A merge question ak types into the inbox seat stays open, and pages the owner, until he answers.

ak types the question before it records it, so the seat's prompt hook hears ak's own line on
either side of the record; that line is never the owner's answer.

Offline: a temporary HOME, a fake tmux, a fake notification sink (a patched urlopen behind
$AK_NOTIFY_SINK) and the seat's prompt hook called as hooks/seat-state.sh calls it.
"""

from contextlib import ExitStack, redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, notify, orch, watch

SEAT = "inbox"
PR = "https://example.test/acme/fix-api/pull/9"
SHA = "abc123def4567890"
QUESTION = "PR #9 by bob: Fix the api. Merge? yes/no"
SINK = "https://sink.invalid/api/webhooks/suite/token"


class InboxQuestionPages(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-inbox-question-pages-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        stack = ExitStack()
        self.addCleanup(stack.close)
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            stack.enter_context(patch.object(config, name, root / name.lower()))
        stack.enter_context(patch.dict(os.environ, {
            "HOME": str(root), "AGENTKIT_TMUX_SOCKET": "agentkit-test",
            "AGENTKIT_INBOX_SESSION": SEAT, config.SESSION_ENV: "", "AK_RUN_ROLE": "",
            "AK_RUN_LOG": "", config.RUN_DIR_ENV: "", notify.SINK_ENV: SINK,
            "AGENTKIT_DISCORD_WEBHOOK": "", "AGENTKIT_DISCORD_USER_ID": "",
            # the hook's look runs in the seat's own pane, on the seat's own server
            "TMUX": "/fake/agentkit-test,1,0", "TMUX_PANE": "%7"}))
        stack.enter_context(redirect_stdout(io.StringIO()))
        stack.enter_context(redirect_stderr(io.StringIO()))
        config.ensure_dirs()
        self.typed, self.posts = [], []
        seat = {"name": SEAT, "path": str(root), "created": 100, "attached": False,
                "exited": False, "legacy": False}
        stack.enter_context(patch.object(orch, "tmux_out", side_effect=self.tmux))
        stack.enter_context(patch.object(orch, "sessions", return_value=[seat]))
        stack.enter_context(patch.object(orch, "ensure", return_value=False))
        stack.enter_context(patch.object(orch, "find", return_value=seat))
        stack.enter_context(patch.object(watch, "seat_model", return_value=("claude", "anthropic")))
        stack.enter_context(patch.object(watch, "KEY_GAP", 0))
        stack.enter_context(patch.object(notify.urllib.request, "urlopen", side_effect=self.post))

    def tmux(self, *args, **_kw):
        if args[0] == "send-keys" and "-l" in args:
            self.typed.append(args[-1])
        if args[0] == "display-message" and args[-1] == "#{socket_path}\t#{session_name}":
            return 0, f"/fake/agentkit-test\t{SEAT}"
        return 0, ""     # a pane painting no composer: a delivered send is sent

    def post(self, request, **_kw):
        self.posts.append(json.loads(request.data))
        return io.BytesIO(b'{"id":"1234"}')

    def prompt(self, said, at):
        """The seat's prompt hook, as hooks/seat-state.sh hands it on: its words and its moment."""
        watch.hook_look(SEAT, at, said)

    def pages(self):
        return [json.loads(path.read_text()) for path in notify.outbox().glob("*.json")]

    def assert_open_and_paged_until_the_owner_answers(self):
        notice = notify.last(SEAT)
        self.assertTrue(watch.owner_question(notice))
        self.assertFalse(notify.resolved(notice))
        self.assertEqual([(page["kind"], page["session"]) for page in self.pages()],
                         [("needs", SEAT)])
        self.assertIn(QUESTION, self.pages()[0]["text"])
        self.assertEqual(len(self.posts), 1)
        self.prompt("yes", notice["time"] + 2)
        self.assertTrue(notify.resolved(notify.last(SEAT, include_seen=True)))
        self.assertFalse(watch.owner_question(notify.last(SEAT)))
        self.assertEqual(len(self.pages()), 1)

    def test_its_own_line_heard_after_the_record_answers_nothing(self):
        self.assertEqual(watch.ask_inbox({}, QUESTION, PR, SHA, lambda _: None), 0)
        self.assertEqual(len(self.typed), 1)
        self.assertIn(QUESTION, self.typed[0])
        self.prompt(self.typed[0], notify.last(SEAT)["time"] + 1)
        self.assert_open_and_paged_until_the_owner_answers()

    def test_its_own_line_asking_again_in_other_spelling_answers_nothing(self):
        """The notice keeps a question's first words; the PR retitled at its new head asks
        the same one."""
        self.assertEqual(watch.ask_inbox({}, QUESTION, PR, SHA, lambda _: None), 0)
        again = QUESTION.replace("api", "API")
        self.assertEqual(watch.ask_inbox({}, again, PR, "def456abc1237890", lambda _: None), 0)
        self.assertEqual(notify.last(SEAT)["text"], QUESTION)
        self.prompt(self.typed[-1], notify.last(SEAT)["time"] + 1)
        self.assert_open_and_paged_until_the_owner_answers()

    def test_its_own_line_heard_before_the_record_answers_nothing(self):
        shaped = notify.shaped

        def heard_first(*args, **kw):
            self.prompt(self.typed[0], time.time())
            return shaped(*args, **kw)

        with patch.object(notify, "shaped", side_effect=heard_first):
            self.assertEqual(watch.ask_inbox({}, QUESTION, PR, SHA, lambda _: None), 0)
        self.assert_open_and_paged_until_the_owner_answers()


if __name__ == "__main__":
    unittest.main()
