"""A bar is written in one tmux call: a seat's own, and every seat's when a seat is dressed.

A start, a changed word or a redraw waits on one listing and one write, however many seats are
open.  Offline with a fake tmux that records each call it is asked, except the last case, which
runs tmux 3.5a on a server of its own in this test's HOME.
"""

import os
import shutil
import subprocess
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import orch, statusbar
from agentkit.guard import commands


class BarInOneCall(Sandbox):
    def setUp(self):
        super().setUp()
        self.calls, self.seats = [], []
        self.stack.enter_context(patch.object(orch, "tmux_out", side_effect=self.tmux))

    def tmux(self, *args, **_kw):
        self.calls.append(args)
        if args[0] == "list-sessions":
            return 0, "\n".join(f"${n}\t{name}\t1" for n, name in enumerate(self.seats))
        return 0, ""

    def test_a_seats_bar_is_one_call_with_its_title_last(self):
        statusbar.dress("acme", "opus")
        bar = [args for args in self.calls if "status-format[0]" in args]
        self.assertEqual(len(bar), 1)
        options = [command[3] for command in commands(bar[0]) if command[0] == "set-option"]
        self.assertTrue(all(command[:3] == ["set-option", "-t", "=acme:"]
                            for command in commands(bar[0]) if command[0] == "set-option"))
        self.assertEqual(options[-1], "set-titles-string")
        for option in (*(option for option, _ in statusbar.LAYOUT), *statusbar.TOPS,
                       *statusbar.WHYS, statusbar.KEY):
            self.assertIn(option, options)

    def test_a_seat_opened_among_thirty_waits_on_one_listing_and_one_write(self):
        self.seats = ["acme", *(f"seat-{n}" for n in range(29))]
        statusbar.dress("acme", "opus")
        self.assertEqual([args[0] for args in self.calls], ["list-sessions", "set-option"])
        # every seat's bar counts the new one again, and its own bar is whole, in that write
        told = {command[2] for command in commands(self.calls[-1])
                if command[0] == "set-option" and command[3] == statusbar.SEATS}
        self.assertEqual(told, {f"={name}:" for name in self.seats})
        self.assertIn("set-titles-string", self.calls[-1])

    def test_a_changed_word_tells_thirty_bars_in_one_write(self):
        self.seats = [f"seat-{n}" for n in range(30)]
        statusbar.retell({"name": "seat-0", "legacy": False})
        self.assertEqual([args[0] for args in self.calls], ["list-sessions", "set-option"])


class LongQuestion(Sandbox):
    """tmux 3.5a refuses a call past its 16 KiB message, header included, and sets nothing."""

    def setUp(self):
        super().setUp()
        self.options = {}
        self.stack.enter_context(patch.object(orch, "tmux_out", side_effect=self.tmux))

    def tmux(self, *args, **_kw):
        if sum(len(word.encode()) + 1 for word in args) + 16 > 16 * 1024:
            return 1, "command too long"
        for command in commands(args):
            if command[0] == "set-option":
                self.options[command[3]] = command[4]
        return 0, ""

    def test_a_seat_asking_a_long_question_still_says_so_on_its_bar(self):
        question = "May I merge acme? " + "The context of the question. " * 100
        statusbar._write("acme", "opus", word="needs you", lasts=[question] * len(statusbar.BARS))
        self.assertIn("needs you", self.options["set-titles-string"])
        self.assertIn("The context of the question.", self.options[statusbar.WHY])


class SeatGoneMidWrite(Sandbox):
    """tmux stops a call at the command that fails: a seat gone since it was listed."""

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

    def tmux(self, *args, **_kw):
        done = subprocess.run([*self.argv, *args], env=self.env, cwd=self.sockets,
                              capture_output=True, text=True, timeout=10)
        return done.returncode, (done.stdout + done.stderr).rstrip("\n")

    def test_every_other_seats_bar_is_still_told(self):
        for name in ("acme", "web", "zeta"):
            self.assertEqual(self.tmux("new-session", "-d", "-s", name, "sleep 600")[0], 0)
            self.assertEqual(self.tmux("set-option", "-t", f"={name}:", orch.MARK, "1")[0], 0)
        listed = statusbar.seats()
        self.assertEqual([name for _, name, _ in listed], ["acme", "web", "zeta"])
        self.assertEqual(self.tmux("kill-session", "-t", "=web")[0], 0)
        with patch.object(statusbar, "seats", return_value=listed):
            statusbar.dress("acme", "opus")
        for name in ("acme", "zeta"):
            self.assertEqual(self.tmux("show-options", "-t", f"={name}:", statusbar.SEATS)[0], 0,
                             name)
        self.assertEqual(self.tmux("show-options", "-v", "-t", "=acme:", "set-titles-string"),
                         (0, "acme"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
