"""A bar's text reaches its bar when it is longer than a tmux message.

tmux 3.5a refuses a client message past 16 KiB ("command too long") and sets nothing, so a
question longer than that left the earlier question on line two, and the right end of a hundred
seats needing you left the earlier names, counts and click targets.  What tmux refuses for its
length is told again in pieces, through calls like any other.  tmux itself, on a server of its
own in this test's HOME.
"""

import os
import shutil
import subprocess
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import orch, statusbar

RIGHT_END = (statusbar.SEATS, statusbar.FOLD, statusbar.NEED, statusbar.HIT)


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
        self.calls = []
        self.stack.enter_context(patch.object(orch, "tmux_out", side_effect=self.tmux))
        self.assertEqual(self.tmux("-f", "/dev/null", "new-session", "-d", "-s", "acme",
                                   "sleep 600")[0], 0)
        self.calls.clear()

    def tmux(self, *args, **_kw):
        self.calls.append(args)
        done = subprocess.run([*self.argv, *args], env=self.env, cwd=self.sockets,
                              capture_output=True, text=True, timeout=10)
        return done.returncode, (done.stdout + done.stderr).rstrip("\n")

    def option(self, name):
        done = subprocess.run([*self.argv, "show-options", "-v", "-t", "=acme:", name],
                              env=self.env, cwd=self.sockets, capture_output=True, text=True,
                              timeout=10)
        self.assertEqual(done.returncode, 0, (name, done.stderr))
        return done.stdout.removesuffix("\n")

    def right_end(self, seats):
        """Tell acme's bar that many other seats need you; what `others` says of them."""
        found = [(f"${n}", "acme" if not n else f"seat-{n}", "needs you")
                 for n in range(seats + 1)]
        self.assertEqual(self.tmux("set-option", "-t", "=acme:", statusbar.SEATS, "web")[0], 0)
        with patch.object(statusbar, "seats", return_value=found):
            statusbar._tell("acme")
        return statusbar.others(found, "acme")

    def test_a_question_longer_than_a_message_replaces_the_earlier_one(self):
        statusbar._write("acme", "opus", word="needs you",
                         lasts=["May I merge acme?"] * len(statusbar.BARS))
        question = "May I merge acme's fix; " + "The context of the question. " * 700
        self.assertGreater(len(question.encode()), 16 * 1024)
        statusbar._write("acme", "opus", word="needs you",
                         lasts=[question] * len(statusbar.BARS))
        for version in statusbar.WHYS:
            self.assertEqual(self.option(version), "  " + orch.tmux_text(question), version)
        # and its title is still what the bar is told last
        self.assertIn("set-titles-string", self.calls[-1])

    def test_a_hundred_seats_needing_you_are_on_the_right_end(self):
        told = self.right_end(100)
        # each fits a message, the four a bar is told in one list do not
        self.assertLess(max(len(text.encode()) for text in told), orch.TMUX_MESSAGE)
        self.assertGreater(sum(len(text.encode()) for text in told), 16 * 1024)
        for name, text in zip(RIGHT_END, told):
            self.assertEqual(self.option(name), text, name)

    def test_names_no_message_carries_are_on_the_right_end_too(self):
        told = self.right_end(300)
        self.assertGreater(len(told[0].encode()), 16 * 1024)
        for name, text in zip(RIGHT_END, told):
            self.assertEqual(self.option(name), text, name)

    def test_a_question_a_call_carries_is_told_as_it_was_before(self):
        # longer than what several lists are packed into, shorter than tmux's own limit
        question = "May I merge acme's fix? " + "The context of the question. " * 540
        self.assertGreater(len(question.encode()), orch.TMUX_MESSAGE)
        statusbar._write("acme", "opus", word="needs you",
                         lasts=[question] * len(statusbar.BARS))
        for version in statusbar.WHYS:
            self.assertEqual(self.option(version), "  " + orch.tmux_text(question), version)
        # one call for each version, none of them a piece, and the title's call last
        whys = [args for args in self.calls if set(statusbar.WHYS) & set(args)]
        self.assertEqual([len(args) for args in whys], [5] * len(statusbar.WHYS))
        self.assertIn("set-titles-string", self.calls[-1])

    def test_text_in_pieces_is_the_text_whatever_it_holds(self):
        # what a file of commands would read as more than text, and a call does not
        said = ("first line\n  # no comment \\\n\ttab 'q' \"d\" $HOME ~ {a} %if #{pane_id} `id` "
                "-a é 漢字 🙂; ").strip() * 800
        self.assertEqual(orch.tmux_option("=acme:", "@said", said), (0, ""))
        self.assertEqual(self.option("@said"), said)
        self.assertGreater(len([args for args in self.calls if "-a" in args[:2]]), 2)
        # and a shorter one after it leaves nothing of the longer behind
        self.assertEqual(orch.tmux_option("=acme:", "@said", "short;"), (0, ""))
        self.assertEqual(self.option("@said"), "short;")

    def test_a_seat_gone_is_the_answer_and_no_other_bar_s_loss(self):
        long = "The context of the question. " * 700
        rc, _ = orch.tmux_option("=gone:", "@said", long)
        self.assertNotEqual(rc, 0)
        # asked whole, then its first piece, and no more once tmux said why
        self.assertEqual(len(self.calls), 2, [args[:4] for args in self.calls])
        found = [("$0", "acme", "needs you"), ("$1", "gone", "working")]
        with patch.object(statusbar, "seats", return_value=found):
            statusbar._tell(None, [("=gone:", statusbar.WHY, long),
                                   ("=acme:", statusbar.WHY, long)])
        self.assertEqual(self.option(statusbar.WHY), long)


if __name__ == "__main__":
    unittest.main(verbosity=2)
