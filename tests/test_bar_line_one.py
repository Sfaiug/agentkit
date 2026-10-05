"""Line one of a working seat's bar gives its tasks bar 36 cells, and where the client is short
of room it narrows that bar to 24 and then 12 cells before the other seats' names fold, then
keeps only who needs you, and only then cuts.  Reads line one the way tmux 3.5a draws it, on a
server of its own.
"""

import os
import re
import shutil
import tempfile
import unittest
from unittest.mock import patch

from test_v4n import Sandbox
from agentkit import menu, orch, statusbar, watch


def drawn(value):
    """tmux text as tmux draws it: styles dropped, the doubled `#` single."""
    return re.sub(r"#\[[^\]]*\]", "", value).replace("##", "#")


class LineOne(Sandbox):
    def setUp(self):
        super().setUp()
        if not shutil.which("tmux"):
            self.skipTest("tmux not installed")
        sockets = tempfile.mkdtemp(prefix="ak", dir="/tmp")   # a socket path has a length limit
        self.addCleanup(shutil.rmtree, sockets, ignore_errors=True)
        self.stack.enter_context(patch.dict(os.environ, {
            "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TMUX_TMPDIR": sockets,
            orch.SOCKET_ENV: "line-one"}))
        os.environ.pop("TMUX", None)
        self.addCleanup(orch.tmux_out, "kill-server")
        for name in ("fix-api", "atlas-proxies"):
            self.assertEqual(orch.tmux_out("new-session", "-d", "-s", name, "sleep 600")[0], 0)
        watch.seat_write("atlas-proxies", word="needs you", reason="", word_since=None)
        watch.seat_write("fix-api", word="working", reason="", word_since=None)
        runs = [{"task": "gh2", "step": "building", "since": 0, "round": 1, "rounds": 3,
                 "executor": "opus", "reviewer": "astra"}]
        self.lasts = [menu.last_column("working", "", 1, 4, runs, cells, tmux=True)
                      for cells in statusbar.BARS]
        statusbar._write("fix-api", "fable", "working", self.lasts, self.cfg)

    def line(self, width):
        shown = statusbar.FORMATS[0].replace("#{client_width}", str(width))
        rc, out = orch.tmux_out("display-message", "-p", "-t", "=fix-api:", shown)
        self.assertEqual(rc, 0, out)
        return drawn(out)

    def test_a_the_tasks_bar_takes_36_cells_where_line_one_has_room(self):
        self.assertEqual(statusbar.BARS, (36, 24, 12))
        bar = drawn(self.lasts[0])
        self.assertEqual(len(bar), 36, bar)
        shown = self.line(200)
        self.assertTrue(shown.startswith(" ▐● working▌  fix-api  fable orchestrates   " + bar),
                        shown)
        self.assertTrue(shown.rstrip().endswith("! atlas-proxies needs you"), shown)

    def test_b_line_one_narrows_its_tasks_bar_before_the_names_fold_or_anything_is_cut(self):
        lefts = []
        for width in (120, 100, 85):
            shown = self.line(width)
            self.assertNotIn("…", shown, width)
            self.assertTrue(shown.rstrip().endswith("! atlas-proxies needs you"), shown)
            lefts.append(len(shown.split("! atlas")[0].rstrip()))
        self.assertEqual(lefts, sorted(lefts, reverse=True))     # the bar narrows as room goes
        self.assertEqual(len(set(lefts)), len(statusbar.BARS))
        shown = self.line(75)                                     # then the names fold
        self.assertNotIn("…", shown)
        self.assertTrue(shown.rstrip().endswith("! 1 needs you"), shown)
        # a phone keeps this seat's own state and who needs you; the rest is cut
        shown = self.line(40)
        self.assertTrue(shown.startswith(" ▐● working▌  fix-api"), shown)
        self.assertTrue(shown.rstrip().endswith("… ! 1 needs you"), shown)
        self.assertLessEqual(len(shown.rstrip()), 40)


if __name__ == "__main__":
    unittest.main(verbosity=2)
