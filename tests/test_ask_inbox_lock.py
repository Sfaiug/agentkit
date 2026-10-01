"""The PR-merge question is typed under the inbox seat's lock, like every other line.

Offline: `orch.tmux_out` is a fake recording each send and serving one scripted pane, and
`watch.time.sleep` only runs the test's hook.  The second sender is `type_into`, the real
path `tell_parked` and revive type through; the lock is the real one.
"""

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import fcntl
import io
import os
from pathlib import Path
import sys
import tempfile
import textwrap
import threading
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, notify, orch, watch

PR = "https://example.test/acme/fix-api/pull/9"
SHA = "abc123def4567890"
QUESTION = "PR #9 by bob: Fix the api. Merge? yes/no"
# wrapped at 65 columns, its continuation row starts on the question's own `>`
QUOTED = "PR #9 by bob: Review the config comparison: keep the new defaults > earlier defaults. Merge? yes/no"
FIX = REPO / "tests/fixtures"
IDLE = "API Error: 500\n❯"


def fixture(kind):
    return (FIX / f"claude-{kind}-pane.txt").read_text(encoding="utf-8", errors="replace")


def above_footer(pane, *rows):
    lines = pane.splitlines()
    return "\n".join(lines[:-1] + list(rows) + lines[-1:])


WORKING = fixture("working").replace("\n❯\xa0\n", "\n❯\xa0Owner's unsent message\n")
HELD = {
    "draft": fixture("draft"),
    "dialog": fixture("dialog"),
    # the owner's text under a turn in flight: the screen reads `working`, not `draft`
    "working": WORKING,
    # ... and under a status line of the user's own that starts with a prompt mark
    "status": above_footer(WORKING, "❯", "? for shortcuts"),
    # an empty prompt row with the owner's text on the row under it reads `at_prompt`
    "continued": fixture("prompt").replace("\n❯\xa0\n", "\n❯\xa0\n  the rest of my line\n"),
}
# an empty composer, whatever is drawn under its rule
EMPTY = {
    "status": above_footer(fixture("prompt"), "❯ acme main*"),
    "inbound": fixture("prompt") + "\n" + next(
        row for row in fixture("question-with-message").splitlines() if "Message from" in row),
}


class AskInboxLock(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-ask-inbox-lock-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        stack = ExitStack()
        self.addCleanup(stack.close)
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            stack.enter_context(patch.object(config, name, root / name.lower()))
        stack.enter_context(patch.dict(os.environ, {
            "HOME": str(root), "AGENTKIT_TMUX_SOCKET": "agentkit-test",
            "AGENTKIT_INBOX_SESSION": "inbox",
            "AGENTKIT_DISCORD_WEBHOOK": "", "AGENTKIT_DISCORD_USER_ID": "",
        }))
        stack.enter_context(redirect_stdout(io.StringIO()))
        stack.enter_context(redirect_stderr(io.StringIO()))
        config.ensure_dirs()
        self.sent, self.logs, self.pane = [], [], IDLE
        stack.enter_context(patch.object(orch, "tmux_out", side_effect=self.tmux))
        stack.enter_context(patch.object(orch, "ensure", return_value=False))
        stack.enter_context(patch.object(orch, "find", return_value={"name": "inbox"}))
        stack.enter_context(patch.object(watch, "seat_model", return_value=("claude", "anthropic")))
        self.pinged = stack.enter_context(patch.object(notify, "shaped", return_value=0))

    def tmux(self, *args, socket=None, client=False):
        if args[0] == "send-keys":
            self.sent.append(args[-1])
        if args[0] != "capture-pane":
            return 0, ""
        return 0, self.pane() if callable(self.pane) else self.pane

    def ask(self, question=QUESTION):
        return watch.ask_inbox({}, question, PR, SHA, self.logs.append)

    def test_another_sender_waits_for_the_question_and_its_enter(self):
        reached = threading.Event()

        def second():
            with config.notify_path("inbox").with_suffix(".lock").open("a") as handle:
                try:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    held = True
                else:
                    held = False
                    fcntl.flock(handle, fcntl.LOCK_UN)
            if held:
                reached.set()     # it waits on the lock; the question's Enter comes first
            try:
                return watch.type_into({"name": "inbox"}, "/rename quay", self.logs.append)
            finally:
                reached.set()

        senders = []

        def sleep(seconds):
            # the question is in the composer and its Enter not yet sent: the key gap
            if seconds == watch.KEY_GAP and len(self.sent) == 1:
                senders.append(pool.submit(second))
                self.assertTrue(reached.wait(5), "the second sender never reached the lock")

        with ThreadPoolExecutor(max_workers=1) as pool, \
                patch.object(watch.time, "sleep", side_effect=sleep):
            self.assertEqual(self.ask(), 0)
            self.assertTrue(senders[0].result(timeout=5))
        self.assertEqual([sent[:9] for sent in self.sent],
                         [QUESTION[:9], "Enter", "/rename q", "Enter"])
        self.assertIn(f"asked the inbox seat: {QUESTION}", self.logs)

    def test_the_question_is_never_typed_onto_text_or_a_dialog(self):
        for kind, pane in HELD.items():
            with self.subTest(kind=kind), patch.object(watch.time, "sleep"):
                del self.sent[:], self.logs[:]
                self.pane = pane
                self.assertNotEqual(self.ask(), 0)
                self.assertEqual(self.sent, [])
                self.assertIn("WARN could not type the question into the inbox seat", self.logs)
                self.pinged.assert_not_called()     # nor is the user asked what the seat was not

    def test_an_empty_composer_takes_it_under_a_status_line_or_a_queued_message(self):
        for kind, pane in EMPTY.items():
            with self.subTest(kind=kind), patch.object(watch.time, "sleep"):
                del self.sent[:], self.logs[:]
                self.pane = pane
                self.assertEqual(self.ask(), 0)
                self.assertEqual([sent[:9] for sent in self.sent], [QUESTION[:9], "Enter"])

    def test_the_question_still_in_its_composer_gets_its_second_enter(self):
        def screen():
            # this composer takes the question only on the second Enter
            held = self.sent and self.sent.count("Enter") < 2
            return IDLE + (" " + self.sent[0] if held else "")

        self.pane = screen
        with patch.object(watch.time, "sleep"):
            self.assertEqual(self.ask(), 0)
        self.assertEqual([sent[:9] for sent in self.sent], [QUESTION[:9], "Enter", "Enter"])
        self.assertIn(f"asked the inbox seat: {QUESTION}", self.logs)

    def test_a_question_whose_enter_failed_is_sent_by_the_next_try(self):
        def unruled(line):
            return IDLE + (" " + line if line else "")

        def wrapped(line):
            # a long question wraps under a real composer, past the bottom rows of the pane
            return fixture("draft").replace("Fix the login redirect",
                                            "\n  ".join(textwrap.wrap(line, 65)))

        def agy(line):
            # Antigravity's composer is a `>` between two rules
            if not line:
                return (FIX / "antigravity-prompt-pane.txt").read_text(encoding="utf-8")
            return (FIX / "antigravity-draft-pane.txt").read_text(encoding="utf-8").replace(
                "Please look at the failing test in the", "\n  ".join(textwrap.wrap(line, 65)))

        def opencode(line):
            # OpenCode's is a `┃` box, wrapping a typed line on that edge over its model line
            pane = (FIX / "opencode-prompt-pane.txt").read_text(encoding="utf-8")
            return pane.replace('Ask anything… "What is the tech stack of this project?"',
                                "\n             ┃  ".join(textwrap.wrap(line, 70))) if line else pane

        lost = []

        def tmux(*args, socket=None, client=False):
            if args[0] == "send-keys" and args[-1] == "Enter" and not lost:
                lost.append(True)     # the one Enter that never arrives
                return 1, "lost server"
            return self.tmux(*args, socket=socket, client=client)

        for kind, harness, draw, question in (
                ("unruled", "claude", unruled, QUESTION), ("wrapped", "claude", wrapped, QUESTION),
                ("quoted", "claude", wrapped, QUOTED), ("antigravity", "antigravity", agy, QUESTION),
                ("antigravity quoted", "antigravity", agy, QUOTED),
                ("opencode", "opencode", opencode, QUESTION)):
            with self.subTest(kind=kind), patch.object(orch, "tmux_out", side_effect=tmux), \
                    patch.object(watch.time, "sleep"), \
                    patch.object(watch, "seat_model", return_value=(harness, "example")):
                del self.sent[:], lost[:]
                self.pinged.reset_mock()
                # the composer lets the question go only on the second Enter that arrives
                self.pane = lambda: draw(self.sent[0] if self.sent and self.sent.count("Enter") < 2
                                         else "")
                self.assertNotEqual(self.ask(question), 0)
                self.pinged.assert_not_called()
                self.assertEqual(self.ask(question), 0)
                self.assertEqual([sent[:9] for sent in self.sent], [QUESTION[:9], "Enter", "Enter"])
                self.pinged.assert_called_once()

    def test_an_owner_question_stops_it_and_an_earlier_merge_question_does_not(self):
        with patch.object(watch.time, "sleep"):
            notify.record("inbox", "needs", "Which branch should I use?")
            self.assertNotEqual(self.ask(), 0)
            self.assertEqual(self.sent, [])
            notify.record("inbox", "needs", "PR #8 by bob: Fix the cli. Merge? yes/no",
                          source=f"inbox:{PR[:-1]}8:{SHA}")
            self.assertEqual(self.ask(), 0)
        self.assertEqual([sent[:9] for sent in self.sent], [QUESTION[:9], "Enter"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
