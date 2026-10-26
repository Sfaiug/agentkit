"""A seat's row is one line; what it asks or did opens under the row the owner points at.

The owner's design (14 Oct 2026): every row is its word and, while it has a plan, its line and
count.  The question of a seat that needs the owner, and what a done one got done, are read
under its row once the owner points at it, with the pointer or ↑/↓ -- the line under the row,
indented under the name -- so a long question never fills the screen.  From a pipe there is no
highlight, so every row asking or done opens its line.  Offline: a temporary HOME, fake seats,
no tmux.
"""

from contextlib import redirect_stdout
import io
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.sandbox import Sandbox  # noqa: E402
from agentkit import config, menu, notify, terminal  # noqa: E402

ASKED = {"acme-plan": "Which schema should acme use, the old one or the new one?",
         "acme-docs": "Can the docs say v2 only, or keep a note for v1 readers?"}


class RowOpens(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}))
        self.stack.enter_context(patch("agentkit.watch.live_state", side_effect=lambda seat, *a, **kw:
                                      {"state": "at_prompt", "rule": "fixture", "since": 9100,
                                       "began": 9100, "evidence": ""}))
        self.stack.enter_context(patch.object(menu.time, "strftime", return_value="14:02"))
        directory = config.CODE / "acme"
        directory.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", "-b", "main", str(directory)], check=True)
        self.seats = []
        for name in ("acme-plan", "acme-docs", "acme-fix"):
            self.seats.append({"name": name, "repo": str(directory), "path": str(directory),
                               "created": 9000})
            config.save_session(self.cfg, name, "fable", ["opus"],
                                {"repo": str(directory), "cwd": str(directory)})
        for name, question in ASKED.items():
            notify.record(name, "needs", question, time=9500)
        config.plan_path("acme-plan").write_text("- [x] a\n- [ ] b\n- [ ] c\n")

    def screen(self, cursor=None, owned=True):
        drawn = {} if owned else None
        keys = terminal.keys(menu.KEYS) if owned else menu.KEYS
        with patch.object(terminal, "width", return_value=100), \
                patch.object(terminal, "height", return_value=30), \
                redirect_stdout(io.StringIO()) as out:
            menu.draw(self.cfg, self.seats, keys, 0, cursor, drawn, look=False)
        return terminal.ANSI.sub("", out.getvalue().replace("\033[K", "")).split("\n")

    def test_the_highlighted_row_alone_opens_its_question_under_itself(self):
        for cursor, other in (("acme-plan", "acme-docs"), ("acme-docs", "acme-plan")):
            with self.subTest(cursor=cursor):
                lines = self.screen(cursor)
                row = next(n for n, line in enumerate(lines) if f" {cursor} " in line)
                self.assertEqual(lines[row + 1].strip(), ASKED[cursor])
                # under the name, as every line a row opens
                self.assertEqual(lines[row + 1].index(ASKED[cursor][:5]),
                                 lines[row].index(cursor))
                self.assertNotIn(ASKED[other], "\n".join(lines))

    def test_a_row_is_its_word_and_its_line_never_its_question(self):
        lines = self.screen("acme-fix")
        plan = next(line for line in lines if " acme-plan " in line)
        self.assertRegex(plan, r"! needs you  [━╸]+─+ 1 of 3$")
        for question in ASKED.values():
            self.assertNotIn(question, "\n".join(lines))

    def test_moving_the_highlight_moves_no_other_row(self):
        heights = {len(self.screen(cursor)) for cursor in ("acme-plan", "acme-docs", "acme-fix")}
        self.assertEqual(len(heights), 1, heights)

    def test_from_a_pipe_every_row_asking_opens_its_question(self):
        text = "\n".join(self.screen(owned=False))
        for question in ASKED.values():
            self.assertIn(question, text)


if __name__ == "__main__":
    unittest.main()
