"""A highlighted seat's line shows its models and its tasks, never what it said.

The owner, 9 Nov 2026: "when the user wants to see what the session said, he can just press on
it, I think only models and the current runs should be shown."  Whatever a seat's word, its
highlighted row opens who builds and who reviews and each task in flight as its squares
(`menu.detail`): never a question, what got done or an idle seat's way back in.  Text the owner
left unsent still opens first, whole.  From a pipe every row opens its line.  Offline.
"""

from contextlib import redirect_stdout
import io
import itertools
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.sandbox import Sandbox  # noqa: E402
from agentkit import config, menu, terminal, watch  # noqa: E402

SAID = {"acme-plan": ("needs you", "Which schema should acme use, the old one or the new one?"),
        "acme-docs": ("done", "The docs say v2 only, with a note for v1 readers."),
        "acme-fix": ("idle", "session closed: press 3 to reopen")}
CREW = "GPT-6-Astra xhigh ⚒   Fable 5.1 xhigh ◎"
UNSENT = " ".join(["Fix the login redirect for acme and tell me what broke."] * 2)  # two lines


class RowOpens(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}))
        self.seats = []
        for name, (word, said) in SAID.items():
            self.seats.append({"name": name, "created": 9000})
            config.save_session(self.cfg, name, "opus", ["astra"], {"reviewers": ["fable"]})
            watch.seat_write(name, word=word, reason=said)
        # two tasks in flight, one building and one in review
        self.records = [(Path(run), {"run_id": run, "task_file": f"/t/{run}.md", "step": step,
                                     "state": "running", "launched_session": "acme-plan"})
                        for run, step in (("g1", "executor"), ("g2", "reviewer"))]

    def screen(self, cursor=None, owned=True):
        drawn = {} if owned else None
        keys = terminal.keys(menu.KEYS, enter="open") if owned else menu.KEYS
        with patch.object(terminal, "width", return_value=100), \
                patch.object(terminal, "height", return_value=30), \
                redirect_stdout(io.StringIO()) as out:
            menu.draw(self.cfg, self.seats, keys, 0, cursor, drawn, look=False,
                      records=self.records)
        return terminal.ANSI.sub("", out.getvalue().replace("\033[K", "")).split("\n")

    def opened(self, lines, name):
        """The lines `name`'s row opens, from its name's column: those indented under it."""
        at = next(n for n, line in enumerate(lines) if f" {name} " in line)
        column = lines[at].index(name)
        under = itertools.takewhile(lambda line: line[:column].isspace(), lines[at + 1:])
        return [line[column:].rstrip() for line in under]

    def test_a_seat_that_needs_you_opens_its_models_and_its_tasks_never_its_question(self):
        lines = self.screen("acme-plan")
        self.assertEqual(self.opened(lines, "acme-plan"), [f"{CREW}   ■□□  ■■□"])
        self.assertEqual(self.opened(lines, "acme-docs") + self.opened(lines, "acme-fix"), [])
        self.assertNotIn("Which schema", "\n".join(lines))

    def test_a_done_seat_and_an_idle_one_open_their_models_alone(self):
        for name in ("acme-docs", "acme-fix"):
            with self.subTest(name=name):
                lines = self.screen(name)
                self.assertEqual(self.opened(lines, name), [CREW])
                self.assertNotIn(SAID[name][1][:12], "\n".join(lines))

    def test_text_the_owner_left_unsent_opens_first_whole_then_the_same_line(self):
        watch.seat_write("acme-plan", unsent=UNSENT)
        under = self.opened(self.screen("acme-plan"), "acme-plan")
        self.assertEqual(" ".join(under[:-1]), f"✎ {UNSENT}")
        self.assertEqual(under[-1], f"{CREW}   ■□□  ■■□")

    def test_moving_the_highlight_moves_no_other_row(self):
        heights = {len(self.screen(cursor)) for cursor in ("acme-plan", "acme-docs", "acme-fix")}
        self.assertEqual(len(heights), 1, heights)

    def test_from_a_pipe_every_row_opens_its_line(self):
        lines = self.screen(owned=False)
        self.assertEqual([self.opened(lines, name) for name in SAID],
                         [[f"{CREW}   ■□□  ■■□"], [CREW], [CREW]])
        self.assertNotIn("Which schema", "\n".join(lines))


if __name__ == "__main__":
    unittest.main()
