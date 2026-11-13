"""What a bar shows is named on the bar, so a write that would tell the same does not happen:
what the answer key cannot see from outside.  Runs tmux itself, on a server of its own.
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import config, look, orch, statusbar, watch
from agentkit.guard import commands

SEATS = ("acme", "beta", "gamma")


class NamesWhatItTold(Sandbox):
    def setUp(self):
        super().setUp()
        if not shutil.which("tmux"):
            self.skipTest("tmux not installed")
        # a short directory of its own: a socket path has a length limit
        sockets = tempfile.mkdtemp(prefix="ak", dir="/tmp")
        self.addCleanup(shutil.rmtree, sockets, ignore_errors=True)
        self.stack.enter_context(patch.dict(os.environ, {
            "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TMUX_TMPDIR": sockets,
            orch.SOCKET_ENV: "told"}))
        os.environ.pop("TMUX", None)
        self.addCleanup(subprocess.run, ["tmux", "-L", "told", "kill-server"],
                        env={**os.environ, "TMUX_TMPDIR": sockets}, capture_output=True)
        self.tmux = orch.tmux_out
        self.calls, self.refused = [], None
        self.stack.enter_context(patch.object(orch, "tmux_out", side_effect=self.logged))
        self.stack.enter_context(patch.object(orch, "processes", return_value={}))
        for name in SEATS:
            self.assertEqual(self.tmux("new-session", "-d", "-s", name, "sleep 600")[0], 0)
            self.assertEqual(self.tmux("set-option", "-t", f"={name}:", orch.MARK, "1")[0], 0)
            watch.seat_write(name, word="idle", reason="", word_since=None)
        self.look()
        self.calls.clear()

    def logged(self, *args, **kw):
        self.calls.append(args)
        for at in range(len(args)):
            if args[at:at + 2] == self.refused:     # what came before it landed, and tmux stopped
                if at > 2:
                    self.tmux(*args[:at - 3])
                return 1, "refused"
        return self.tmux(*args, **kw)

    def look(self, word="idle"):
        for name in SEATS:
            statusbar._write(name, "fable", word, cfg=self.cfg)

    def option(self, name, option):
        return self.tmux("show-options", "-qv", "-t", f"={name}:", option)[1]

    def written(self):
        return {command[2] for args in self.calls for command in commands(args)
                if command[0] == "set-option"}

    def test_a_pass_over_bars_that_stayed_lists_once_and_writes_nothing(self):
        self.assertEqual(self.tmux("new-session", "-d", "-s", "by-hand", "sleep 600")[0], 0)
        with patch.object(statusbar.fcntl, "flock") as lock, look.one_look():
            self.look()
        lock.assert_not_called()
        # one ask of whose tag each stranger holds, and one of what its panes run
        self.assertEqual([args[0] for args in self.calls],
                         ["list-sessions", "source-file", "list-panes"])

    def test_a_recount_writes_only_the_bars_whose_right_end_moved(self):
        watch.seat_write("beta", word="needs you", reason="", word_since=None)
        statusbar.retell({"name": "beta"})
        self.assertEqual(self.written(), {"=acme:", "=gamma:"})
        self.assertIn("1 other seat needs you", self.option("acme", statusbar.NEED))
        self.calls.clear()
        self.look()      # each own options' digest is true still, and each right end's
        self.assertEqual(self.written(), set())

    def test_an_effort_change_is_told_once_with_the_same_word_and_model(self):
        config.save_session(self.cfg, "acme", "fable", ["fable"])
        config.change_efforts("acme", lambda record: {"fable": {"effort": "low"}})
        self.look()
        self.assertEqual(self.written(), {"=acme:"})
        self.assertIn("Fable 5.1 low#[default]", self.option("acme", statusbar.TOP))
        self.calls.clear()
        self.look()
        self.assertEqual(self.written(), set())

    def test_a_word_that_moves_mid_pass_is_read_by_the_write_after_it(self):
        with look.one_look():
            statusbar._write("acme", "fable", "idle", cfg=self.cfg)
            watch.seat_write("beta", word="needs you", reason="", word_since=None)
            statusbar._write("gamma", "fable", "working", cfg=self.cfg)
        self.assertIn("1 other seat needs you", self.option("gamma", statusbar.NEED))

    def test_own_options_refused_part_way_come_right_on_the_next_look_whatever_it_says(self):
        self.refused = ("=acme:", statusbar.TOPS[1])
        self.look("working")
        self.assertIn("working", self.option("acme", statusbar.TOP))
        self.refused = None
        self.look()      # what it told before the refused one, whose digest it had
        self.assertIn("idle", self.option("acme", statusbar.TOP))

    def test_a_right_end_refused_part_way_comes_right_on_the_next_look_whatever_it_says(self):
        self.refused = ("=acme:", statusbar.FOLD)
        watch.seat_write("beta", word="needs you", reason="", word_since=None)
        statusbar.retell({"name": "beta"})
        self.assertIn("1 other seat needs you", self.option("acme", statusbar.NEED))
        self.refused = None
        watch.seat_write("beta", word="idle", reason="", word_since=None)
        self.look()
        self.assertEqual(self.option("acme", statusbar.NEED), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
