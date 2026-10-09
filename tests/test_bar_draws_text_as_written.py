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

from fixtures.sandbox import Sandbox
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
        # the mark ak's own start leaves on a seat: without it a session with no agent in it is
        # nobody's, and no bar's right end is written on it
        self.assertEqual(orch.tmux_out("set-option", "-t", "=fix-api:", orch.MARK, "1")[0], 0)
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
            statusbar._write("fix-api", "fable", word, [SAID] * len(statusbar.BARS), self.cfg)
            self.assertIn("  " + SAID + " ", self.screen(SAID)[1], word)

    def test_b_a_tasks_bar_keeps_every_cell(self):
        for lang in ("C.UTF-8", "C"):
            with self.subTest(lang=lang), patch.dict(os.environ, {"LANG": lang, "LC_ALL": lang}):
                bars = [menu.last_column("working", "", 4, 8, (), cells, tmux=True)
                        for cells in statusbar.BARS]
                bar = bars[0]
                cells = re.sub(r"#\[[^\]]*\]", "", bar)
                self.assertEqual(len(cells), statusbar.CELLS)
                statusbar._write("fix-api", "fable", "working", bars, self.cfg)
                line = self.screen(" 4/8 ")[0].rstrip()
                self.assertTrue(line.endswith("fable orchestrates   " + cells.rstrip()), line)

    def test_c_a_seat_s_window_title_keeps_its_name_as_it_is(self):
        # a seat made by hand on ak's server keeps whatever name it was given
        self.assertEqual(orch.tmux_out("rename-session", "-t", "=fix-api:", "fix-%H")[0], 0)
        statusbar._write("fix-%H", "fable", "working", None, self.cfg)
        self.screen("fix-%H")
        for _ in range(50):
            title = self.view("display-message", "-p", "-t", "=view:", "#{pane_title}").strip()
            if title == "fix-%H · working":
                break
            time.sleep(.1)
        self.assertEqual(title, "fix-%H · working")

    def test_d_line_one_s_end_names_seats_and_no_session_made_by_hand(self):
        # sessions made by hand under names no seat can have -- tmux reads the name it is given as
        # a format, and keeps these -- are no seats: never named, never counted, so no cell of
        # theirs can stand where tmux draws another's; the seat beside them is named as it is.
        # Each carries a seat's mark, so its name alone is what keeps it off the bar.
        for name in ("## web #{session_name} 50% %H", "z-\U0001F468\u200d\U0001F469-0",
                     "web_2-api"):
            rc, sid = orch.tmux_out("new-session", "-d", "-P", "-F", "#{session_id}", "-s",
                                    orch.tmux_text(name), "sleep 600")
            self.assertEqual(rc, 0, sid)
            self.assertEqual(orch.tmux_out("set-option", "-t", sid, orch.MARK, "1")[0], 0)
            watch.seat_write(name, word="needs you", reason="", word_since=None)
        statusbar._write("fix-api", "fable", "working", None, self.cfg)
        said = "! web_2-api needs you"
        line = self.screen(said)[0].rstrip()
        self.assertTrue(line.endswith(said), line)
        self.assertNotIn("##", line)
        self.assertNotIn("z-", line)


if __name__ == "__main__":
    unittest.main(verbosity=2)
