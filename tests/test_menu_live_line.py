"""The highlighted seat on the `ak` screen opens its line under its row.

For a working seat the line says who builds and who reviews and draws each task in flight as its
squares (`menu.detail`), indented under the name and lit as the row is, never a task's name; no
other row grows, and the height kept for it means no page overflows or turns as the highlight
moves.  The orchestrator column draws each model in its company's colour.  Offline: fake seats
and run records, the real renderer.
"""

from contextlib import redirect_stdout
import io
import os
import re
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import config, menu, record, statusbar, terminal

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

    def test_a_the_highlighted_seat_opens_its_line_and_no_other_row_grows(self):
        lines, _ = self.draw("fix-api")
        indent = " " * (2 + 1 + 2)                     # under the name
        self.assertEqual(self.under(lines, "fix-api"), indent + "Opus 5.5 ⚒◎   ■□□")
        self.assertEqual(sum("⚒" in line for line in lines), 1)   # web is not highlighted
        lines, _ = self.draw("web")
        self.assertEqual(self.under(lines, "web"), indent + "Opus 5.5 ⚒◎   ■■□")
        self.assertEqual(sum("⚒" in line for line in lines), 1)
        # no screen names a task
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

    def test_c_the_orchestrator_column_is_grey_at_rest(self):
        os.environ.pop("NO_COLOR", None)
        with patch.dict(os.environ, {"TERM": "xterm-256color", "COLORTERM": "truecolor"}):
            infos = [menu.v5o_seat_info(self.cfg, n, seat, [], {}, None, NOW)
                     for n, seat in enumerate(self.seats, 1)]
            row = menu.v5o_seat_blocks(infos, 100)[0][0]
        self.assertIn(terminal.styled("Fable 5.1", "dim"), row)

    def test_d_a_project_heading_highlighted_opens_nothing(self):
        # a project with switches has a heading the highlight can rest on; it is no seat
        with patch.object(menu, "switches_command", return_value="features"), \
                patch.object(menu, "switches", return_value=[]):
            lines, _ = self.draw(config.CODE / "acme")
        self.assertTrue(any(line.startswith("›") and "acme" in line for line in lines), lines)
        self.assertFalse(any("⚒" in line for line in lines), lines)

    def test_e_a_model_is_drawn_on_one_line_as_text(self):
        # it may be named anything, a control character or an escape among it, and so may the
        # id its full name is where its harness's catalog has no label for it
        model = "opus\x1b[2J\nfast"
        self.cfg["models"][model] = dict(self.cfg["models"]["opus"], model=model)
        config.save_session(self.cfg, "fix-api", "fable", [model],
                            {"repo": str(config.CODE / "acme"), "cwd": str(config.CODE / "acme")})
        with patch.object(terminal, "width", return_value=100), \
                patch.object(terminal, "height", return_value=30), \
                redirect_stdout(io.StringIO()) as out:
            menu.draw(self.cfg, self.seats, cursor="fix-api", drawn={})
        self.assertNotIn("\x1b[2J", out.getvalue())
        lines = screen(out.getvalue())
        self.assertEqual(self.under(lines, "fix-api").strip(),
                         "opus fast ⚒◎   ■□□")


if __name__ == "__main__":
    unittest.main(verbosity=2)
