"""Line one of a working seat's bar gives its progress line 36 cells, and where the client is
short of room it narrows that line to 24 and then 12 cells, then folds how many other seats need
you to `! 1 needs you`, and only then cuts.  Reads line one the way tmux 3.5a draws it, on a server of its own.
"""

import os
import re
import shutil
import tempfile
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import config, menu, orch, statusbar, watch

NEEDING = "! 1 other seat needs you"     # orbit-proxies, the other seat, needs you


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
        for name in ("fix-api", "orbit-proxies"):
            self.assertEqual(orch.tmux_out("new-session", "-d", "-s", name, "sleep 600")[0], 0)
            # the mark ak's own start leaves on a seat: a session without it and with no agent
            # in it is nobody's, and no bar names it
            self.assertEqual(orch.tmux_out("set-option", "-t", f"={name}:", orch.MARK, "1")[0], 0)
        watch.seat_write("orbit-proxies", word="needs you", reason="", word_since=None)
        watch.seat_write("fix-api", word="working", reason="", word_since=None)
        self.dress(1, 4, [(0, "moving")])

    def dress(self, done, total, tasks):
        """Dress fix-api's bar the way every write does (`statusbar.redress`)."""
        with patch.object(menu, "seat_progress", return_value=(done, total)), \
                patch.object(menu, "seat_tasks", return_value=tasks), \
                patch.object(config, "load_session", return_value={"orchestrator": "fable",
                                                                   "workers": []}):
            statusbar.redress({"name": "fix-api"}, {"word": "working", "reason": ""}, self.cfg)
        self.lasts = [orch.tmux_out("show-options", "-v", "-t", "=fix-api:", top)[1]
                      for top in statusbar.TOPS]

    def line(self, width):
        shown = statusbar.FORMATS[0].replace("#{client_width}", str(width))
        rc, out = orch.tmux_out("display-message", "-p", "-t", "=fix-api:", shown)
        self.assertEqual(rc, 0, out)
        return drawn(out)

    def test_a_the_tasks_bar_takes_36_cells_where_line_one_has_room(self):
        self.assertEqual(statusbar.BARS, (36, 24, 12))
        bar = drawn(self.lasts[0]).split("Fable 5.1   ")[1]
        self.assertEqual(len(bar), 36, bar)
        shown = self.line(200)
        self.assertTrue(shown.startswith(" ● working   fix-api   Fable 5.1   " + bar), shown)
        self.assertTrue(shown.rstrip().endswith(NEEDING), shown)

    def test_b_line_one_narrows_its_tasks_bar_before_anything_is_cut(self):
        lefts = []
        for width in (100, 90, 75):
            shown = self.line(width)
            self.assertNotIn("…", shown, width)
            self.assertTrue(shown.rstrip().endswith(NEEDING), shown)
            lefts.append(len(shown.split(NEEDING)[0].rstrip()))
        self.assertEqual(lefts, sorted(lefts, reverse=True))     # the bar narrows as room goes
        self.assertEqual(len(set(lefts)), len(statusbar.BARS))
        # then the count folds, and a phone keeps this seat's own state, its name and who needs
        # you; the rest is cut
        shown = self.line(40)
        self.assertTrue(shown.startswith(" ● working   fix-api"), shown)
        self.assertTrue(shown.rstrip().endswith("… ! 1 needs you"), shown)
        self.assertLessEqual(len(shown.rstrip()), 40)

    def test_c_each_tasks_bar_keeps_to_its_width_however_long_its_count(self):
        for total in (10, 100):
            self.dress(0, total, [(0, "moving")] * 8)
            for top, cells in zip(self.lasts, statusbar.BARS):
                bar = drawn(top).split("Fable 5.1   ")[1]
                self.assertEqual(len(bar), cells, (total, bar))
            shown = self.line(84)       # the 12-cell bar fits beside the name, so it stays
            self.assertTrue(shown.rstrip().endswith(NEEDING), shown)

    def test_d_a_line_one_that_fits_is_never_cut_even_to_the_cell(self):
        # the narrowest bar beside who needs you folded, whole, in the cells tmux counts
        least = 2 + sum(int(orch.tmux_out("display-message", "-p", "-t", "=fix-api:",
                                          "#{w:" + option + "}")[1])
                        for option in (statusbar.TOPS[-1], statusbar.FOLD))
        for width in range(least - 3, 200):
            shown = self.line(width)
            self.assertEqual("…" in shown, width < least, (width, shown))
            self.assertLessEqual(len(shown.rstrip()), width, width)


if __name__ == "__main__":
    unittest.main(verbosity=2)
