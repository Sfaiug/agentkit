"""The highlighted seat on the `ak` screen opens its live line under its row.

The line is the seat bar's second line (`statusbar.live`) at the row's width, indented under the
name and lit as the row is; no other row grows, and the height kept for it means no page
overflows or turns as the highlight moves.  The orchestrator column draws each model in its
company's colour.  Offline: fake seats and run records, the real renderer.
"""

from contextlib import redirect_stdout
import io
import os
import re
import unittest
from unittest.mock import patch

from test_v4n import Sandbox
from agentkit import config, menu, record, terminal

NOW = 1_800_000_000


def screen(text):
    """The lines a draw wrote over the screen, colours dropped."""
    return [terminal.ANSI.sub("", line) for line in
            text.removeprefix("\033[H").split("\033[J")[0].replace("\033[K", "").split("\n")[:-1]]


class MenuLiveLine(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}))
        self.stack.enter_context(patch.object(menu.time, "time", return_value=NOW))
        self.stack.enter_context(patch.object(menu.time, "strftime", return_value="14:02"))
        self.stack.enter_context(patch("agentkit.watch.live_state", side_effect=lambda seat, *a,
                                       **kw: {"state": seat["live"], "rule": "fixture",
                                              "evidence": "", "began": NOW - 600,
                                              "since": NOW - 600}))
        repo = config.CODE / "acme"
        (repo / ".git").mkdir(parents=True)
        self.seats = []
        for name, live in (("fix-api", "working"), ("web", "working"), ("zeta", "at_prompt")):
            self.seats.append({"name": name, "repo": str(repo), "path": str(repo), "live": live,
                               "created": NOW - 86400})
            config.save_session(self.cfg, name, "fable", ["opus"],
                                {"repo": str(repo), "cwd": str(repo)})
        for name, seat, step in (("20260101-0900-gh2-x", "fix-api", "executor"),
                                 ("20260101-0901-lg1-y", "web", "reviewer")):
            directory = config.RUNS / name
            directory.mkdir(parents=True)
            record.save_state(directory, {
                "run_id": name, "title": "Task", "state": "running", "step": "executor",
                "step_at": NOW - 180, "launched_session": seat, "repo": str(repo),
                "task_file": f"/t/{name.split('-')[2]}-task.md", "executor": "opus",
                "reviewer": "astra", "rounds": 3, "started_at": NOW - 600, **{"step": step}})

    def draw(self, cursor, width=100, height=30):
        with patch.object(terminal, "width", return_value=width), \
                patch.object(terminal, "height", return_value=height), \
                redirect_stdout(io.StringIO()) as out:
            pages = menu.draw(self.cfg, self.seats, cursor=cursor, drawn={})
        return screen(out.getvalue()), pages

    def under(self, lines, name):
        row = next(n for n, line in enumerate(lines) if re.search(rf"\d  {name}\b", line))
        return lines[row + 1]

    def test_a_the_highlighted_seat_opens_its_live_line_and_no_other_row_grows(self):
        lines, _ = self.draw("fix-api")
        indent = " " * (2 + 1 + 2)                     # under the name
        self.assertEqual(self.under(lines, "fix-api"),
                         indent + "gh2 ■□□□ opus building · 3m")
        self.assertNotIn("lg1", "\n".join(lines))      # web is not highlighted
        lines, _ = self.draw("web")
        self.assertEqual(self.under(lines, "web"), indent + "lg1 ■■■□ astra reviewing · 3m")
        self.assertNotIn("gh2", "\n".join(lines))
        lines, _ = self.draw("zeta")                   # done: nothing to open
        self.assertNotIn("gh2", "\n".join(lines))
        self.assertNotIn("lg1", "\n".join(lines))

    def test_b_no_page_overflows_or_turns_as_the_highlight_moves(self):
        for height in range(8, 24):
            for width in (44, 100):
                drawn = {name: self.draw(name, width, height) for name in ("fix-api", "web", "zeta")}
                self.assertEqual(len({pages[1] for _, pages in drawn.values()}), 1, (height, width))
                for name, (lines, _) in drawn.items():
                    # one line for the prompt and one to spare, as every draw keeps
                    self.assertLessEqual(len(lines), height - 2, (name, height, width, lines))

    def test_c_the_orchestrator_column_wears_its_company_s_colour(self):
        os.environ.pop("NO_COLOR", None)
        with patch.dict(os.environ, {"TERM": "xterm-256color", "COLORTERM": "truecolor"}):
            infos = [menu.v5o_seat_info(self.cfg, n, seat, [], {}, None, NOW)
                     for n, seat in enumerate(self.seats, 1)]
            row = menu.v5o_seat_blocks(infos, 100)[0][0]
        self.assertIn(terminal.styled("fable", menu.model_colour(self.cfg, "fable")), row)
        self.assertEqual(menu.model_colour(self.cfg, "fable"), menu.COLOURS["anthropic"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
