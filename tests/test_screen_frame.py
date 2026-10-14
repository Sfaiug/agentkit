"""The ak screen keeps its usage on top and its keys at the bottom, and turns pages with ← →.

The owner's words (14 Oct 2026): "usage always seen, also menu at the bottom always seen, and
if there are so many sessions to scroll, then it should be navigable in pages with the right
and left arrow keys."  Every page has the usage under the header and the key line at the
screen's bottom; seats that do not fit turn pages, the key line starting with where
he is, `←  1 / 2  →`; a screen too short for the block keeps it in one line.  Offline: a
temporary HOME, fake seats, no tmux.
"""

from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.sandbox import Sandbox  # noqa: E402
from agentkit import config, menu, terminal  # noqa: E402


class ScreenFrame(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}))
        self.stack.enter_context(patch("agentkit.watch.live_state", side_effect=lambda seat, *a, **kw:
                                      {"state": "at_prompt", "rule": "fixture", "since": 9100,
                                       "began": 9100, "evidence": ""}))
        self.stack.enter_context(patch.object(menu.time, "strftime", return_value="14:02"))
        self.seats = []
        for project in ("acme", "orbit"):
            directory = config.CODE / project
            directory.mkdir(parents=True)
            subprocess.run(["git", "init", "-q", "-b", "main", str(directory)], check=True)
            for n in range(7):
                name = f"{project}-{n}"
                self.seats.append({"name": name, "repo": str(directory), "path": str(directory),
                                   "created": 9000 + n})
                config.save_session(self.cfg, name, "fable", ["opus"],
                                    {"repo": str(directory), "cwd": str(directory)})
        (config.STATE / "usage.json").write_text(json.dumps({"fetched_at": 10000, "providers": {
            "anthropic": {"meters": [{"name": "weekly_all", "used": 79}]},
            "openai": {"meters": [{"name": "weekly", "used": 31, "window_secs": 604800}]}}}))

    def screen(self, cursor=None, width=100, height=24):
        """The screen as the menu with the keyboard draws it: its lines, and what it drew."""
        drawn = {}
        with patch.object(terminal, "width", return_value=width), \
                patch.object(terminal, "height", return_value=height), \
                redirect_stdout(io.StringIO()) as out:
            menu.draw(self.cfg, self.seats, f"{menu.move_keys()}   {menu.KEYS}", 0, cursor,
                      drawn, look=False)
        text = terminal.ANSI.sub("", out.getvalue().replace("\033[K", ""))
        return text.split("\n")[:-1], drawn

    def test_every_page_has_the_usage_on_top_and_the_keys_last(self):
        lines, drawn = self.screen()
        self.assertGreater(len(drawn["turns"]), 1, "fourteen seats fit one page")
        for number, first in enumerate(drawn["turns"], 1):
            with self.subTest(page=number):
                lines, _ = self.screen(first)
                self.assertIn("usage left", "\n".join(lines[:5]))
                self.assertRegex("\n".join(lines[:6]), r"Claude\s+[█░]+\s+21% left")
                self.assertEqual(len(lines), 22)      # the keys at the bottom, two lines kept
                self.assertTrue(lines[-1].startswith(f"  ←  {number} / {len(drawn['turns'])}  →"),
                                lines[-1])
                self.assertIn("n new", lines[-1])

    def test_left_and_right_turn_the_page_and_clicks_on_the_arrows_do(self):
        lines, drawn = self.screen()
        keys = len(lines)
        row = drawn["spots"][keys]
        cells = {cell: first for first, _, cell in row[1]}
        click = lambda col: terminal.Key("click", row=keys, col=col)   # noqa: E731
        self.assertEqual(menu.pressed(click(cells["←"]), drawn, self.seats), "←")
        self.assertEqual(menu.pressed(click(cells["→"]), drawn, self.seats), "→")
        # the page's place between them opens no seat
        self.assertEqual(menu.pressed(click(cells["1"]), drawn, self.seats), "")

    def test_a_short_screen_keeps_the_usage_in_one_line(self):
        lines, drawn = self.screen(height=14)
        self.assertNotIn("usage left", "\n".join(lines))
        summary = next(line.strip() for line in lines if line.strip().startswith("Claude 21% · "))
        self.assertIn("ChatGPT 69%", summary)
        self.assertTrue(lines[-1].startswith("  ←  1 / "), lines[-1])


if __name__ == "__main__":
    unittest.main()
