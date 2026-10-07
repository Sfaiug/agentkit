"""`ak notify needs` takes a question that asks first.

A seat's bar and its menu row show a question from its start and cut the rest, so a question
whose ask comes after its context reads as a status line: the owner saw `needs you` beside a
sentence of background and took the seat for broken.  A question whose `?` is not within
`notify.ASK_CAP` characters is refused and records nothing; one that asks first is recorded
whole, its context after the ask.
"""

from contextlib import ExitStack
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agentkit import config, notify, orch

CONTEXT = ("Account deletion (Settings, Delete account): when a member with a running trial "
           "or membership deletes their account, I recommend it ends the membership at once.")


class AskFirst(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix=".ask-first-")
        self.root = Path(self.tmp.name)
        home = self.root / ".agentkit"
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.addCleanup(self.tmp.cleanup)
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK"):
            self.stack.enter_context(patch.object(config, name,
                                                  home if name == "HOME" else home / name.lower()))
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "AGENTKIT_SESSION": "seat", "AGENTKIT_DISCORD_WEBHOOK": "off",
            "AK_NOTIFY_SINK": "off", "AK_RUN_ROLE": ""}, clear=False))
        config.ensure_dirs()
        self.posts = []

        def post(payload, files, message, receipt):
            self.posts.append(payload)
            receipt.update(status="disabled", message_id=str(len(self.posts)), webhook="sink")
            return 0
        self.stack.enter_context(patch.object(notify, "post", side_effect=post))
        self.stack.enter_context(patch.object(orch, "tmux_out", return_value=(0, "")))

    def refused(self, text):
        with self.assertRaises(config.Error) as caught:
            notify.main(["needs", text])
        self.assertIn(f"within {notify.ASK_CAP} characters", str(caught.exception))
        self.assertIsNone(notify.last("seat", include_seen=True))
        self.assertEqual(self.posts, [])

    def test_context_before_the_ask_is_refused(self):
        self.refused(f"{CONTEXT} Yes, or should Delete wait until the membership has ended?")

    def test_a_needs_without_a_question_is_refused(self):
        self.refused("Choose a branch")

    def test_the_ask_counts_from_the_first_word_whatever_the_spacing(self):
        ask = "x" * (notify.ASK_CAP - 1) + "?"
        self.refused("\n  " + "x" * notify.ASK_CAP + "?")
        self.assertEqual(notify.main(["needs", f"\n  {ask} {CONTEXT}"]), 0)
        self.assertEqual(notify.last("seat")["text"], f"{ask} {CONTEXT}")

    def test_a_question_that_asks_first_is_recorded_whole(self):
        text = f"End a running membership at once when its member deletes the account? {CONTEXT}"
        self.assertEqual(notify.main(["needs", text]), 0)
        self.assertEqual(notify.last("seat")["text"], text)

    def test_a_done_is_no_question(self):
        self.assertEqual(notify.main(["done", CONTEXT]), 0)
        self.assertEqual(notify.last("seat", include_seen=True)["text"], CONTEXT)

    def test_the_command_says_why_and_exits_2(self):
        done = subprocess.run([str(ROOT / "bin" / "ak"), "notify", "needs", CONTEXT, "--dry-run"],
                              capture_output=True, text=True, timeout=60,
                              env={**os.environ, "HOME": str(self.root)})
        self.assertEqual(done.returncode, 2, done.stderr)
        self.assertIn('put the question first', done.stderr)
        self.assertEqual(done.stdout, "")


if __name__ == "__main__":
    unittest.main()
