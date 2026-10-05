"""A seat's bar draws what it says as it was said: a `#`, a `%` or a `#{…}` in a question, a
summary or a seat's name is text, never a format, a style or a time, and a tasks bar keeps
every cell.

Runs tmux itself: the seat on a server of its own, and a client attached to it in a pane of a
second server, whose screen is read back as a person would see it.
"""

import os
import re
import shutil
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

from test_v4n import Sandbox
from agentkit import menu, orch, statusbar, watch

SAID = "## heading, a ## b, ### c, 50% at %H, #{session_name} and #[bold] end #"


class AsWritten(Sandbox):
    def setUp(self):
        super().setUp()
        if not shutil.which("tmux"):
            self.skipTest("tmux not installed")
        sockets = tempfile.mkdtemp(prefix="ak", dir="/tmp")   # a socket path has a length limit
        self.addCleanup(shutil.rmtree, sockets, ignore_errors=True)
        self.stack.enter_context(patch.dict(os.environ, {
            "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TMUX_TMPDIR": sockets,
            orch.SOCKET_ENV: "written"}))
        os.environ.pop("TMUX", None)
        self.addCleanup(orch.tmux_out, "kill-server")
        self.addCleanup(self.view, "kill-server")
        self.assertEqual(orch.tmux_out("new-session", "-d", "-s", "fix-api", "-x", "120", "-y",
                                       "8", "sleep 600")[0], 0)
        attach = f"env -u TMUX tmux -L {orch.socket_name()} attach-session -t =fix-api:"
        self.view("-f", "/dev/null", "new-session", "-d", "-s", "view", "-x", "120", "-y", "8",
                  attach)
        self.view("set-option", "-t", "=view:", "status", "off")

    def view(self, *args):
        return subprocess.run(["tmux", "-L", "view", *args], capture_output=True, text=True,
                              timeout=10).stdout

    def screen(self, wanted):
        """The attached client's two bar lines once they show `wanted`, or as they last were."""
        for _ in range(50):
            orch.tmux_out("refresh-client", "-S")
            lines = self.view("capture-pane", "-p", "-t", "=view:").rstrip("\n").split("\n")[-2:]
            if wanted in "\n".join(lines):
                break
            time.sleep(.1)
        return lines

    def test_a_a_question_and_a_summary_draw_every_hash_and_percent_as_said(self):
        for word in ("needs you", "done"):
            statusbar._write("fix-api", "fable", word, SAID, self.cfg)
            self.assertIn("  " + SAID + " ", self.screen(SAID)[1], word)

    def test_b_a_tasks_bar_keeps_every_cell(self):
        for lang in ("C.UTF-8", "C"):
            with self.subTest(lang=lang), patch.dict(os.environ, {"LANG": lang, "LC_ALL": lang}):
                bar = menu.last_column("working", "", 4, 8, (), statusbar.CELLS, tmux=True)
                cells = re.sub(r"#\[[^\]]*\]", "", bar)
                self.assertEqual(len(cells), statusbar.CELLS)
                statusbar._write("fix-api", "fable", "working", bar, self.cfg)
                line = self.screen(" 4/8 ")[0].rstrip()
                self.assertTrue(line.endswith("fable orchestrates   " + cells.rstrip()), line)

    def test_c_a_seat_s_window_title_keeps_its_name_as_it_is(self):
        # a seat made by hand on ak's server keeps whatever name it was given
        self.assertEqual(orch.tmux_out("rename-session", "-t", "=fix-api:", "fix-%H")[0], 0)
        statusbar._write("fix-%H", "fable", "working", "", self.cfg)
        self.screen("fix-%H")
        for _ in range(50):
            title = self.view("display-message", "-p", "-t", "=view:", "#{pane_title}").strip()
            if title == "fix-%H · working":
                break
            time.sleep(.1)
        self.assertEqual(title, "fix-%H · working")

    def test_d_another_seat_s_name_draws_as_it_is_at_line_one_s_end(self):
        name = "## web #{session_name} 50% %H"
        # a seat made by hand: tmux reads the name it is given as a format, and keeps this one
        self.assertEqual(orch.tmux_out("new-session", "-d", "-s", orch.tmux_text(name),
                                       "sleep 600")[0], 0)
        self.assertIn(name, orch.tmux_out("list-sessions", "-F", "#{session_name}")[1].split("\n"))
        watch.seat_write(name, word="needs you", reason="", word_since=None)
        statusbar._write("fix-api", "fable", "working", "", self.cfg)
        said = f"! {name} needs you"
        self.assertTrue(self.screen(said)[0].rstrip().endswith(said), self.screen(said))


if __name__ == "__main__":
    unittest.main(verbosity=2)
