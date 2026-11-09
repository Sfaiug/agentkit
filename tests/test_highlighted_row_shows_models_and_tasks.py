"""A highlighted seat's line shows its models and its tasks, never what it said.

The owner, 9 Nov 2026: "when the user wants to see what the session said, he can just press on
it, I think only models and the current runs should be shown."  Whatever a seat's word, the line
its highlighted row opens is who builds and who reviews its work and each task in flight as its
squares (`menu.detail`): never the question of a seat that needs the owner, what a done one got
done or an idle one's way back in.  Text the owner left unsent still opens first, whole: those
are the owner's own words.  From a pipe there is no highlight, so every row opens its line.
Offline: a temporary HOME, seats as their records say, fake run records, no tmux.
"""

from contextlib import redirect_stdout
import io
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.sandbox import Sandbox  # noqa: E402
from agentkit import config, menu, terminal, watch  # noqa: E402

QUESTION = "Which schema should acme use, the old one or the new one?"
SAID = {"acme-ask": ("needs you", QUESTION),
        "acme-done": ("done", "The parser is shipped and the readme says how to call it."),
        "acme-idle": ("idle", "session closed: press 3 to reopen")}
UNSENT = ("Fix the login redirect for acme, then check that the session cookie survives the "
          "round trip through the proxy and tell me what broke")
CREW = "GPT-6-Astra xhigh ⚒   Fable 5.1 xhigh ◎"


def run(name, step):
    return Path(name), {"run_id": name, "launched_session": "acme-ask", "state": "running",
                        "step": step, "task_file": f"/t/{name}.md"}


class HighlightedRow(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}))
        self.seats = []
        for name, (word, reason) in SAID.items():
            self.seats.append({"name": name, "created": 9000 + len(self.seats)})
            config.save_session(self.cfg, name, "opus", ["astra"], {"reviewers": ["fable"]})
            watch.seat_write(name, word=word, reason=reason)
        # two tasks in flight, one building and one in review
        self.records = [run("g1-parser", "executor"), run("g2-schema", "reviewer")]

    def screen(self, cursor=None):
        """The screen's lines, as plain text: with the keyboard on `cursor`, else from a pipe."""
        drawn, keys = ({}, terminal.keys(menu.KEYS, enter="open")) if cursor else (None, menu.KEYS)
        with patch.object(terminal, "width", return_value=100), \
                patch.object(terminal, "height", return_value=30), \
                patch.object(terminal, "_POINTER", None), redirect_stdout(io.StringIO()) as out:
            menu.draw(self.cfg, self.seats, keys, 0, cursor, drawn, look=False,
                      records=self.records)
        return [line.rstrip() for line in
                terminal.ANSI.sub("", out.getvalue().replace("\033[K", "")).split("\n")]

    def opened(self, name, lines):
        """The lines under `name`'s row, up to the next row or the blank line."""
        at = next(n for n, line in enumerate(lines) if f" {name} " in line)
        under = []
        for line in lines[at + 1:]:
            if not line.startswith(" " * 5):
                break
            under.append(line)
        # under the name, as every line a row opens
        self.assertTrue(all(line.index(line.strip()) == lines[at].index(name) for line in under))
        return [line.strip() for line in under]

    def assertSaysNothing(self, lines):
        for _, said in SAID.values():
            self.assertNotIn(said.split(",")[0], "\n".join(lines))

    def test_a_seat_that_needs_you_opens_its_models_and_its_tasks_never_its_question(self):
        lines = self.screen("acme-ask")
        self.assertEqual(self.opened("acme-ask", lines), [f"{CREW}   ■□□  ■■□"])
        self.assertSaysNothing(lines)

    def test_a_done_seat_and_an_idle_one_open_their_models_alone(self):
        for name in ("acme-done", "acme-idle"):
            with self.subTest(name=name):
                lines = self.screen(name)
                self.assertEqual(self.opened(name, lines), [CREW])
                self.assertSaysNothing(lines)

    def test_text_the_owner_left_unsent_opens_first_whole_then_the_same_line(self):
        watch.seat_write("acme-ask", unsent=UNSENT)
        under = self.opened("acme-ask", self.screen("acme-ask"))
        self.assertTrue(under[0].startswith("✎ Fix the login"), under)
        self.assertEqual(" ".join(under[:-1]), f"✎ {UNSENT}")
        self.assertEqual(under[-1], f"{CREW}   ■□□  ■■□")

    def test_the_highlight_alone_opens_a_line_and_moving_it_moves_no_other_row(self):
        screens = {name: self.screen(name) for name in SAID}
        self.assertEqual(len({len(lines) for lines in screens.values()}), 1)
        for name, lines in screens.items():
            for other in SAID.keys() - {name}:
                self.assertEqual(self.opened(other, lines), [])

    def test_from_a_pipe_every_row_opens_its_line(self):
        lines = self.screen()
        self.assertEqual({name: self.opened(name, lines) for name in SAID},
                         {"acme-ask": [f"{CREW}   ■□□  ■■□"], "acme-done": [CREW],
                          "acme-idle": [CREW]})
        self.assertSaysNothing(lines)


if __name__ == "__main__":
    unittest.main()
