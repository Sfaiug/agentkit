"""A bar's text reaches its bar when it is longer than a tmux message.

tmux 3.5a refuses a client message past 16 KiB ("command too long") and sets nothing, so a
question longer than that left the earlier question on line two, and the right end of a hundred
seats needing you left the earlier names, counts and click targets.  tmux itself, on a server of
its own in this test's HOME.
"""

import os
import shutil
import subprocess
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import orch, statusbar


class LongerThanAMessage(Sandbox):
    def setUp(self):
        super().setUp()
        if not shutil.which("tmux"):
            self.skipTest("tmux not installed")
        self.sockets = self.root / "sockets"
        self.sockets.mkdir()
        # the socket named from its own directory: below sockaddr_un's limit in any checkout
        self.env = {**os.environ, "TMUX_TMPDIR": str(self.sockets), "TERM": "xterm-256color"}
        self.env.pop("TMUX", None)
        self.argv = ["tmux", "-S", "agentkit-test"]
        self.addCleanup(subprocess.run, [*self.argv, "kill-server"], env=self.env,
                        cwd=self.sockets, capture_output=True)
        self.stack.enter_context(patch.object(orch, "tmux_out", side_effect=self.tmux))
        self.assertEqual(self.tmux("-f", "/dev/null", "new-session", "-d", "-s", "acme",
                                   "sleep 600")[0], 0)

    def tmux(self, *args, **_kw):
        done = subprocess.run([*self.argv, *args], env=self.env, cwd=self.sockets,
                              capture_output=True, text=True, timeout=10)
        return done.returncode, (done.stdout + done.stderr).rstrip("\n")

    def option(self, name):
        done = subprocess.run([*self.argv, "show-options", "-v", "-t", "=acme:", name],
                              env=self.env, cwd=self.sockets, capture_output=True, text=True,
                              timeout=10)
        self.assertEqual(done.returncode, 0, (name, done.stderr))
        return done.stdout.removesuffix("\n")

    def test_a_question_longer_than_a_message_replaces_the_earlier_one(self):
        statusbar._write("acme", "opus", word="needs you",
                         lasts=["May I merge acme?"] * len(statusbar.BARS))
        question = "May I merge acme's fix? " + "The context of the question. " * 700
        self.assertGreater(len(question.encode()), 16 * 1024)
        statusbar._write("acme", "opus", word="needs you",
                         lasts=[question] * len(statusbar.BARS))
        for version in statusbar.WHYS:
            self.assertEqual(self.option(version), "  " + orch.tmux_text(question), version)

    def test_a_hundred_seats_needing_you_are_on_the_right_end(self):
        found = [(f"${n}", "acme" if not n else f"seat-{n}", "needs you") for n in range(100)]
        told = statusbar.others(found, "acme")
        # each fits a message, the four a bar is told in one list do not
        self.assertLess(max(len(text.encode()) for text in told), orch.TMUX_MESSAGE)
        self.assertGreater(sum(len(text.encode()) for text in told), 16 * 1024)
        self.assertEqual(self.tmux("set-option", "-t", "=acme:", statusbar.SEATS, "web")[0], 0)
        with patch.object(statusbar, "seats", return_value=found):
            statusbar._tell("acme")
        for name, text in zip((statusbar.SEATS, statusbar.FOLD, statusbar.NEED, statusbar.HIT),
                              told):
            self.assertEqual(self.option(name), text, name)

    def test_a_long_list_s_words_arrive_whole_and_a_failing_one_is_the_answer(self):
        long = "x" * 20000
        # what tmux would read as more than text, were it not handed over whole
        odd = "it's \"quoted\" \\ $HOME ~ {a} %if #{pane_id} `id`\ttab\nline two" + long
        rc, out = orch.tmux_lists([
            ["set-option", "-t", "=acme:", "@short", "first"],
            ["set-option", "-t", "=acme:", "@odd", odd, ";",
             "set-option", "-t", "=acme:", "@ends", orch.tmux_literal(long + ";")],
            ["set-option", "-t", "=gone:", "@long", long, ";",
             "set-option", "-t", "=acme:", "@never", "set"],
            ["set-option", "-t", "=acme:", "@last", "last"]])
        self.assertEqual(rc, 1)
        self.assertIn("gone", out)
        self.assertEqual(self.option("@short"), "first")
        self.assertEqual(self.option("@odd"), odd)
        self.assertEqual(self.option("@ends"), long + ";")
        self.assertEqual(self.option("@last"), "last")
        # a list stops at its command that fails, as a call does
        self.assertNotEqual(self.tmux("show-options", "-v", "-t", "=acme:", "@never"), (0, "set"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
