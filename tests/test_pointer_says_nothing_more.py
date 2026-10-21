"""Pointing lights what it rests on and says nothing more: the key line stays the keys on every
screen, whatever the pointer is on.  The owner's words (14 Oct 2026): "I dont think hovering
should show extra info anywhere."  The one line under a thing the pointer opens is its own --
a subscription's, under the grid -- and `i` is no key, its page gone.

The main menu runs as tests/test_close_and_info.py runs it, in a child process on a pty of its own,
with the seats faked and its usage read from one fake meter in the child's own HOME: 40% of its
week gone and 68% left.  The screens under it -- `c` and `n` -- run in this process on the real
`terminal.read_key`, their keys on a pipe (tests/test_hover.py's `run`).  A move of the pointer
is the SGR report a terminal in modes 1003 and 1006 sends.  Nothing here reads the owner's
~/.agentkit, starts a session or reaches a provider; the only process signalled is the test's
own child.
"""

import os
from pathlib import Path
import re
import sys
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
from agentkit import config, menu, terminal, watch
import test_close_and_info
from test_hover import ESC, at, move, played, run, texts
from fixtures.sandbox import Sandbox

# The child: test_close_and_info's fakes for what a seat is, every seat in one project, and the
# cache holding one meter for the first provider's row: 40% of its week gone, 32% of it used.
CHILD = r"""
import json, os, sys, time
sys.path.insert(0, os.environ["CLOSE_REPO"])
from pathlib import Path
from agentkit import config, menu, orch

SEATS = json.loads(Path(os.environ["CLOSE_SEATS"]).read_text())
orch.listing = lambda reconcile=True: [
    {"name": name, "repo": "/code/acme", "path": "/", "created": 0} for name in SEATS]
orch.checkout_of = lambda repo, **_kw: Path(repo) if repo else None
orch.checkouts = lambda **_kw: []
orch.job_notices = lambda: []
menu.seat_row_state = lambda cfg, session, **facts: {
    "word": SEATS[session["name"]], "reason": "", "since": None}
menu.Live.probe = lambda self, now=None: False
menu.usage.collect = lambda cfg, **kwargs: {}
menu.show_config = lambda *args, **kwargs: print("<config>", flush=True)
config.ensure_dirs()
week, now = 7 * 86400, time.time()
(config.STATE / "usage.json").write_text(json.dumps({"fetched_at": now, "providers": {
    "anthropic": {"fetched_at": now, "meters": [
        {"name": "weekly", "used": 32, "window_secs": week, "resets_at": now + 0.6 * week}]}}}))
sys.exit(menu.loop(config.load()))
"""
SEATS = {"fix-api": "needs you", "web-portal": "done"}


def menu_child(case, **size):
    """The main menu in a child on a pty, in true colour: `test_close_and_info.Menu`'s."""
    with patch.object(test_close_and_info, "CHILD", CHILD), \
            patch.dict(os.environ, {"COLORTERM": "truecolor"}):
        return test_close_and_info.Menu(case, SEATS, **size)


def says_nothing(case, child, places, keys):
    """With the pointer at each (column, row) of `places` on `child`'s screen, and then on
    nothing at all, its key line is `keys`."""
    for place in places:
        with case.subTest(place=place):
            child.send(move(*place))
            time.sleep(0.3)
            child.until(lambda text: keyline(text) == keys, "the keys")


def keys_of(grid):
    """The key line of a screen played onto `grid`: its last row with anything on it."""
    return [line for line in texts(grid) if line][-1]


def keyline(text):
    """The key line as the screen `text` leaves shows it now."""
    return keys_of(played(text))


class MainMenu(unittest.TestCase):
    def test_a_seat_its_word_a_heading_and_each_key_say_nothing_on_the_key_line(self):
        child = menu_child(self)
        lines = child.frame()
        keys = lines[-1]
        self.assertEqual(keys, "  ↑↓ move   ⏎ open   n new   x stop   c config   esc leave")
        seat = next(row for row, line in enumerate(lines, 1) if "fix-api" in line)
        heading = lines.index("acme") + 1
        says_nothing(self, child, [
            (lines[seat - 1].index("fix-api") + 1, seat),
            (lines[seat - 1].index("needs you") + 1, seat), (3, heading),
            (keys.index("n new") + 1, len(lines)), (keys.index("c config") + 3, len(lines))],
            keys)
        child.leave()

    def test_a_subscription_under_the_pointer_says_the_rest_under_the_grid(self):
        child = menu_child(self)
        lines = child.frame()
        row = next(number for number, line in enumerate(lines, 1) if line.startswith("  Claude"))
        under = next(number for number in range(row, len(lines)) if not lines[number])
        child.send(move(5, row))
        # its name in its colour, then when its week resets, on the line under the grid; the
        # keys stay where they are
        child.until(lambda text: re.fullmatch(r"  Claude  resets \w{3} \d\d:\d\d",
                                              texts(played(text))[under]), "its line")
        self.assertEqual(keyline(child.text()), lines[-1])
        child.send(move(1, 2))
        child.until(lambda text: not texts(played(text))[under], "the line gone")
        child.leave()

    def test_i_is_no_key_and_its_page_is_gone(self):
        self.assertNotIn("i info", menu.KEYS)
        self.assertFalse(hasattr(menu, "show_info"))
        child = menu_child(self)
        lines = child.frame()
        mark = child.mark()
        child.send(b"i")
        time.sleep(0.5)
        self.assertNotIn("info", child.text()[mark:])
        self.assertNotIn("<config>", child.text()[mark:])
        self.assertEqual(keyline(child.text()), lines[-1])    # the menu as it was
        child.leave()


class ConfigScreen(Sandbox):
    """The `c` screen on fix-api's marks, tall enough for every row."""

    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.object(terminal, "height", return_value=40))
        self.selected = {"orchestrator": "opus", "workers": ["opus"], "reviewers": ["astra"]}

    def matrix(self, *keys, token="claude worker token expires 2027-09-22 (in 356 days)"):
        with patch.object(watch, "worker_token_note", return_value=token):
            return run(lambda: menu.config_matrix(self.cfg, None, "abc1234", "fix-api",
                                                  self.selected, {}), *(keys or [ESC]))[1]

    def test_a_model_its_marks_and_a_provider_say_nothing_on_the_key_line(self):
        first = self.matrix()[0]
        label = at(first, config.model_name(self.cfg, "astra"))      # its row, by its full name
        for place in (label, (at(first, "orch")[0] + 1, label[1]), at(first, "Claude", 1)):
            with self.subTest(place=place):
                # the keys for what the pointer moved the highlight onto, and nothing else
                self.assertRegex(keys_of(self.matrix(move(*place), ESC)[1]),
                                 r"^  ↑↓←→ move   ⏎ \w+   esc back$")

    def test_the_worker_token_stands_under_the_rows_from_fourteen_days_out(self):
        later = "claude worker token expires 2027-09-22 (in 356 days)"
        self.assertNotIn(later, texts(self.matrix(token=later)[0]))
        soon = "claude worker token expires 2026-10-10 (in 9 days)"
        self.assertIn("  " + soon, texts(self.matrix(token=soon)[0]))
        gone = "claude worker token expired 2026-09-20"
        self.assertIn("  " + gone, texts(self.matrix(token=gone)[0]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
