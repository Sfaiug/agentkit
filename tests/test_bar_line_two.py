"""Line two of a seat's bar draws the most of its tasks' squares that fit beside the key, then who
builds and reviews, cut with one `…` where it does not fit: after the squares and the three
cells between, never in them, where it would read as a cut square.  Reads line two the way tmux
draws it, on a server of its own.
"""

import os
import re
import shutil
import tempfile
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import config, menu, orch, statusbar, watch

CREW = "build and review: 6 Astra xhigh"
TWO = "■□□  ■■□"        # one task building, one in review


def drawn(value):
    """tmux text as tmux draws it: styles dropped, the doubled `#` single."""
    return re.sub(r"#\[[^\]]*\]", "", value).replace("##", "#")


class LineTwo(Sandbox):
    def setUp(self):
        super().setUp()
        if not shutil.which("tmux"):
            self.skipTest("tmux not installed")
        sockets = tempfile.mkdtemp(prefix="ak", dir="/tmp")   # a socket path has a length limit
        self.addCleanup(shutil.rmtree, sockets, ignore_errors=True)
        self.stack.enter_context(patch.dict(os.environ, {
            "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TMUX_TMPDIR": sockets,
            orch.SOCKET_ENV: "line-two"}))
        os.environ.pop("TMUX", None)
        self.addCleanup(orch.tmux_out, "kill-server")
        self.assertEqual(orch.tmux_out("new-session", "-d", "-s", "fix-api", "sleep 600")[0], 0)
        # the mark ak's own start leaves on a seat: no bar names a session without it
        self.assertEqual(orch.tmux_out("set-option", "-t", "=fix-api:", orch.MARK, "1")[0], 0)
        watch.seat_write("fix-api", word="working", reason="", word_since=None)

    def dress(self, tasks):
        """Dress fix-api's bar the way every write does (`statusbar.redress`)."""
        with patch.object(menu, "seat_progress", return_value=(0, 0)), \
                patch.object(menu, "seat_tasks", return_value=tasks), \
                patch.object(config, "load_session", return_value={"orchestrator": "fable",
                                                                   "workers": ["astra"]}):
            statusbar.redress({"name": "fix-api"}, {"word": "working", "reason": ""}, self.cfg)

    def left(self, width):
        """Line two on a client `width` cells wide, short of its key, which is whole."""
        shown = statusbar.FORMATS[1].replace("#{client_width}", str(width))
        rc, out = orch.tmux_out("display-message", "-p", "-t", "=fix-api:", shown)
        self.assertEqual(rc, 0, out)
        line = drawn(out).rstrip()
        self.assertTrue(line.endswith(statusbar.HINT) and len(line) <= width, (width, line))
        return line.removesuffix(statusbar.HINT).strip()

    def test_a_the_crew_is_cut_after_the_squares_and_the_cells_between_never_in_them(self):
        self.dress([(0, "moving"), (1, "moving")])
        lefts = [left for left in map(self.left, range(20, 80)) if left.startswith(TWO)]
        whole = f"{TWO}   {CREW}"
        cut = [left for left in lefts if left not in (TWO, whole)]
        # narrowest first: the squares alone, then the crew from its first cell on, then whole
        self.assertEqual(lefts, [TWO] * lefts.count(TWO) + cut + [whole] * lefts.count(whole))
        self.assertTrue(lefts.count(TWO) and lefts.count(whole), lefts)
        self.assertEqual(cut[0], f"{whole[:len(TWO) + 4]}…")
        for left in cut:
            self.assertTrue(left.endswith("…") and whole.startswith(left[:-1]), left)

    def test_b_all_the_squares_come_first_and_six_keep_the_crew_where_all_do_not_fit(self):
        self.dress([(0, "moving")] * 15)
        every = "  ".join(["■□□"] * 15)
        self.assertTrue(self.left(100).startswith(f"{every}   b"), self.left(100))
        self.assertEqual(self.left(87), "  ".join(["■□□"] * 6 + ["+9"]) + f"   {CREW}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
