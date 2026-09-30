"""The PR-merge question is typed under the inbox seat's lock, like every other line.

Offline: `orch.tmux_out` is a fake recording each send and serving one scripted pane, and
`watch.time.sleep` only runs the test's hook.  The second sender is `type_into`, the real
path hand-backs, `tell_parked` and revive type through; the lock is the real one.
"""

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import fcntl
import io
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, notify, orch, watch

PR = "https://example.test/acme/fix-api/pull/9"
SHA = "abc123def4567890"
QUESTION = "PR #9 by bob: Fix the api. Merge? yes/no"
FIX = REPO / "tests/fixtures"
IDLE = "API Error: 500\n❯"
DRAFT = (FIX / "claude-draft-pane.txt").read_text(encoding="utf-8", errors="replace")
DIALOG = (FIX / "claude-dialog-pane.txt").read_text(encoding="utf-8", errors="replace")


class AskInboxLock(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ask-inbox-lock-", dir=REPO)
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
        stack.enter_context(patch.object(notify, "shaped", return_value=0))

    def tmux(self, *args, socket=None, client=False):
        if args[0] == "send-keys":
            self.sent.append(args[-1])
        return 0, self.pane if args[0] == "capture-pane" else ""

    def ask(self):
        return watch.ask_inbox({}, QUESTION, PR, SHA, self.logs.append)

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

    def test_the_question_is_never_typed_onto_a_composer_or_dialog_holding_text(self):
        for kind, pane in (("draft", DRAFT), ("dialog", DIALOG)):
            with self.subTest(kind=kind), patch.object(watch.time, "sleep"):
                del self.sent[:], self.logs[:]
                self.pane = pane
                self.assertEqual(self.ask(), 0)
                self.assertEqual(self.sent, [])
                self.assertIn("WARN could not type the question into the inbox seat", self.logs)


if __name__ == "__main__":
    unittest.main(verbosity=2)
