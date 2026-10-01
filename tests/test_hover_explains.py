"""Hovering explains: while the pointer rests on anything that means more than its label, the key
line says what it is in one sentence (`menu.TIPS`), and the keys come back when it leaves; a usage
row under it sends one glint across its bar and stands a hairline tick at the share that would be
left had it been spent as fast as time passes; and `i` is no key, its page gone.

The main menu runs as tests/test_close_and_info.py runs it, in a child process on a pty of its own,
with the seats faked and its usage rows read from one fake meter in the child's own HOME: 40% of
its week gone and 68% left.  The `c` screen runs in this process on the real `terminal.read_key`,
its keys on a pipe (tests/test_hover.py's `run`).  A move of the pointer is the SGR report a
terminal in modes 1003 and 1006 sends.  Nothing here reads the owner's ~/.agentkit, starts a
session or reaches a provider; the only process signalled is the test's own child.
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
from agentkit import menu, motion, terminal, watch
import test_close_and_info
from test_hover import ESC, at, move, played, run, texts
from test_v4n import Sandbox

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
orch.checkout_of = lambda repo: Path(repo) if repo else None
orch.checkouts = lambda: []
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
USAGE = re.compile(r"  Claude · 68% left · resets \w{3} \d\d:\d\d \(in 4 d 4 h\) · "
                   r"slower than time")


def menu_child(case):
    """The main menu in a child on a pty, in true colour: `test_close_and_info.Menu`'s."""
    with patch.object(test_close_and_info, "CHILD", CHILD), \
            patch.dict(os.environ, {"COLORTERM": "truecolor"}):
        return test_close_and_info.Menu(case, SEATS)


def keys_of(grid):
    """The key line of a screen played onto `grid`: its last row with anything on it."""
    return [line for line in texts(grid) if line][-1]


def keyline(text):
    """The key line as the screen `text` leaves shows it now."""
    return keys_of(played(text))


class MainMenu(unittest.TestCase):
    def test_each_thing_on_the_main_screen_says_what_it_is_and_the_keys_come_back(self):
        child = menu_child(self)
        lines = child.frame()
        keys = lines[-1]
        self.assertEqual(keys, "  ↑↓ move   ⏎ open   n new   x stop   c config   esc leave")
        seat = next(row for row, line in enumerate(lines, 1) if "fix-api" in line)
        heading = lines.index("acme") + 1
        usage = next(row for row, line in enumerate(lines, 1) if line.startswith("  Claude"))
        places = [
            ((lines[seat - 1].index("fix-api") + 1, seat),
             "  " + menu.TIPS["session"].format(name="fix-api")),
            ((lines[seat - 1].index("needs you") + 1, seat), "  " + menu.TIPS["needs you"]),
            ((3, heading), "  " + menu.TIPS["project"].format(name="acme")),
            ((keys.index("n new") + 1, len(lines)), "  " + menu.TIPS["n new"]),
            ((keys.index("c config") + 3, len(lines)), "  " + menu.TIPS["c config"]),
            ((5, usage), USAGE)]
        for place, said in places:
            with self.subTest(said=str(said)):
                child.send(move(*place))
                child.until(lambda text: (said.fullmatch(keyline(text))
                                          if isinstance(said, re.Pattern)
                                          else keyline(text) == said), f"the key line: {said}")
                child.send(move(1, 2))            # the rule: on nothing at all
                child.until(lambda text: keyline(text) == keys, "the keys back")
        child.leave()

    def test_a_usage_row_glints_then_ticks_at_the_pace_share_until_the_pointer_leaves(self):
        child = menu_child(self)
        lines = child.frame()
        row = next(number for number, line in enumerate(lines, 1) if line.startswith("  Claude"))
        bar = re.search("[█░]+", lines[row - 1])
        self.assertEqual(bar.group(), "████████░░░░")      # 68% left of twelve cells
        mark = child.mark()
        child.send(move(5, row))
        child.until(lambda text: USAGE.fullmatch(keyline(text)), "the usage row's sentence")
        time.sleep(motion.SWEEP + 0.3)                        # the glint is over
        grid = played(child.text())
        cells = grid[row][bar.start():bar.end()]
        shown = "".join(cell.char for cell in cells)
        # 40% of the week gone: the tick at 60%, the seventh of twelve cells cut out of the fill
        self.assertEqual(shown, "███████│░░░░")
        self.assertTrue(cells[7].reverse)
        # and before it one light crossed the bar, left to right
        with patch.object(terminal, "colour_depth", return_value=24), \
                patch.object(terminal, "_LIGHT", False):
            light = terminal.faded(menu.COLOURS["anthropic"], -motion.BRIGHTER)
            lit = [terminal.styled(char, light) for char in shown]
        # each frame lights the cell the light has reached, so a slow one may pass one by
        after = child.text()[mark:]
        places = [after.find(f"\x1b[{row};{bar.start() + 1 + n}H{text}")
                  for n, text in enumerate(lit)]
        crossed = [place for place in places if place >= 0]
        self.assertGreaterEqual(len(crossed), 2, after[-2000:])
        self.assertEqual(crossed, sorted(crossed))
        # off the row the tick goes, with the sentence
        child.send(move(1, 2))
        child.until(lambda text: keyline(text) == lines[-1], "the keys back")
        shown = "".join(cell.char for cell in played(child.text())[row][bar.start():bar.end()])
        self.assertEqual(shown, "████████░░░░")
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

    def test_a_model_its_marks_its_effort_and_a_provider_say_what_they_are(self):
        first = self.matrix()[0]
        label = at(first, "astra")
        # a mark is its whole column, under its heading; the effort starts under `effort`
        orch_mark, exec_mark, review_mark, effort = (
            (at(first, head)[0] + 1, label[1]) for head in ("orch", "exec", "review", "effort"))
        entry = self.cfg["models"]["astra"]
        said = {label: menu.TIPS["model"].format(name="astra", harness=entry["harness"],
                                                 effort=entry["effort"]),
                orch_mark: menu.TIPS["orch"], exec_mark: menu.TIPS["exec"],
                review_mark: menu.TIPS["review"],
                effort: menu.TIPS["effort"].format(name="astra"),
                at(first, "Claude", 1): "Claude: its worker token expires 2027-09-22 (in 356 days)",
                at(first, "ChatGPT", 1): menu.TIPS["account"].format(name="ChatGPT")}
        for place, sentence in said.items():
            with self.subTest(sentence=sentence):
                screens = self.matrix(move(*place), move(1, 1), ESC)
                self.assertEqual(keys_of(screens[1]), "  " + terminal.cut(sentence, 98))
                self.assertRegex(keys_of(screens[2]), r"^  ↑↓(←→)? move   ⏎ \w+   esc back$")

    def test_the_worker_token_stands_under_the_rows_from_fourteen_days_out(self):
        later = "claude worker token expires 2027-09-22 (in 356 days)"
        self.assertNotIn(later, texts(self.matrix(token=later)[0]))
        soon = "claude worker token expires 2026-10-10 (in 9 days)"
        self.assertIn("  " + soon, texts(self.matrix(token=soon)[0]))
        gone = "claude worker token expired 2026-09-20"
        self.assertIn("  " + gone, texts(self.matrix(token=gone)[0]))


class Table(unittest.TestCase):
    def test_docs_cli_design_lists_every_sentence(self):
        design = (REPO / "docs/cli-design.md").read_text()
        for name, sentence in menu.TIPS.items():
            self.assertIn(sentence, design, name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
