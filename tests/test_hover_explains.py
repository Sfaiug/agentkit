"""Hovering explains: while the pointer rests on anything that means more than its label, the key
line says what it is in one sentence (`terminal.TIPS`), and the keys come back when it leaves, on
every screen; a usage row under it sends one glint across its bar and stands a hairline tick at
the share that would be left had it been spent as fast as time passes, through a glide too; and
`i` is no key, its page gone.

The main menu runs as tests/test_close_and_info.py runs it, in a child process on a pty of its own,
with the seats faked and its usage rows read from one fake meter in the child's own HOME: 40% of
its week gone and 68% left.  The screens under it -- `c`, a model's own, `n`, a list -- run in
this process on the real `terminal.read_key`, their keys on a pipe (tests/test_hover.py's
`run`).  A move of the pointer is the SGR report a terminal in modes 1003 and 1006 sends.
Nothing here reads the owner's ~/.agentkit, starts a session or reaches a provider; the only
process signalled is the test's own child.
"""

import io
import json
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
from agentkit import config, menu, motion, orch, terminal, watch
from agentkit.terminal import TIPS
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
                   r"lasts at this pace")


def menu_child(case, **size):
    """The main menu in a child on a pty, in true colour: `test_close_and_info.Menu`'s."""
    with patch.object(test_close_and_info, "CHILD", CHILD), \
            patch.dict(os.environ, {"COLORTERM": "truecolor"}):
        return test_close_and_info.Menu(case, SEATS, **size)


def explains(case, child, places, keys):
    """Each (column, row) of `places` puts its sentence -- or what matches its pattern -- on the
    key line of `child`'s screen while the pointer is there, and `keys` are back once it is on
    nothing at all."""
    for place, said in places:
        with case.subTest(said=str(said)):
            child.send(move(*place))
            child.until(lambda text: (said.fullmatch(keyline(text)) if isinstance(said, re.Pattern)
                                      else keyline(text) == said), f"the key line: {said}")
            child.send(move(1, 2))            # the rule: on nothing at all
            child.until(lambda text: keyline(text) == keys, "the keys back")


def keys_of(grid):
    """The key line of a screen played onto `grid`: its last row with anything on it."""
    return [line for line in texts(grid) if line][-1]


def keyline(text):
    """The key line as the screen `text` leaves shows it now."""
    return keys_of(played(text))


def explanation(grid, row):
    """The whole sentence from the first key row, rejoining its wrapped lines."""
    return " ".join(line.strip() for line in texts(grid)[row - 1:] if line)


class UsagePace(unittest.TestCase):
    def test_the_pace_says_whether_the_allowance_lasts_the_week(self):
        now, week = 1_800_000_000, 7 * 86400
        for used, words in ((42, "runs out early at this pace"), (32, "lasts at this pace"),
                            (40, "on pace")):
            with self.subTest(used=used):
                prov = {"meters": [{"name": "weekly", "used": used, "window_secs": week,
                                    "resets_at": now + 0.6 * week}]}
                with patch.object(menu, "usage_rows", return_value=[("acme", "Acme II", prov, None)]):
                    sentence, pace = menu.usage_tip({"models": {}}, 1, now)
                self.assertTrue(sentence.endswith(" · " + words), sentence)
                self.assertIn(f"{100 - used}% left", sentence)
                self.assertAlmostEqual(pace, 0.6)

    def test_a_spent_meter_has_no_pace_words(self):
        now, week = 1_800_000_000, 7 * 86400
        prov = {"meters": [{"name": "weekly", "used": 100, "window_secs": week,
                            "resets_at": now + 0.6 * week}]}
        with patch.object(menu, "usage_rows", return_value=[("acme", "Acme II", prov, None)]):
            sentence, pace = menu.usage_tip({"models": {}}, 1, now)
        self.assertIn("0% left", sentence)
        self.assertTrue(sentence.endswith(" (in 4 d 4 h)"), sentence)
        self.assertAlmostEqual(pace, 0.6)

    def test_a_spent_meter_on_credits_says_its_credits_where_its_0_stood(self):
        now, week = 1_800_000_000, 7 * 86400
        prov = {"meters": [{"name": "weekly", "used": 100, "window_secs": week,
                            "resets_at": now + 0.6 * week}], "credits": 62469.67}
        with patch.object(menu, "usage_rows", return_value=[("acme", "Acme II", prov, None)]):
            sentence, _ = menu.usage_tip({"models": {}}, 1, now)
        self.assertTrue(sentence.startswith("Acme II · 62,469 credits left · resets "), sentence)
        self.assertNotIn("% left", sentence)
        self.assertTrue(sentence.endswith(" (in 4 d 4 h)"), sentence)


class Wrapping(unittest.TestCase):
    def test_key_line_contains_only_keys_and_key_height_reserves_the_explanations(self):
        for cols in (26, 30, 40):
            for keys, first in (("↑↓←→ move   ⏎ open", "  ↑↓←→ move   ⏎ open"),
                                ("arrows move   enter open", "  arrows move   enter open")):
                expected = [first + "   esc back"] if cols == 40 else [first, "  esc back"]
                for taken in (False, True):
                    with self.subTest(cols=cols, keys=keys, taken=taken), \
                            patch.object(terminal, "taken", return_value=taken), \
                            patch.object(terminal, "colour_depth", return_value=0):
                        text = keys + "   esc back"
                        self.assertEqual(terminal.key_line(text, cols), expected)
                        height = terminal.key_height(text, term_width=cols)
                        if taken:
                            self.assertGreater(height, len(expected))
                            self.assertGreater(terminal.key_height(text, {0: "a long row " * 20}, cols),
                                               height)
                        else:
                            self.assertEqual(height, len(expected))

    def test_full_lists_leave_room_for_the_whole_explanation_without_scrolling(self):
        body = [f"  model-{number:02}" for number in range(40)]
        long = "model-00: " + " ".join(["a complete explanation"] * 7)
        cases = (("add", "⏎ add", TIPS["⏎ add"]),
                 ("matrix", "↑↓←→ move", TIPS["↑↓ move"]),
                 ("row", "model-00", long))
        for cols, rows in ((cols, rows) for cols in (26, 30, 40) for rows in (16, 24)):
            for kind, item, sentence in cases:
                with self.subTest(cols=cols, rows=rows, screen=kind):
                    out, before, step, restored = io.StringIO(), [], 0, False

                    def read(*_args, **_kw):
                        nonlocal step, restored
                        if restored:
                            return terminal.Key("esc")
                        if kind == "add" and step < 2:
                            step += 1
                            return terminal.Key("enter")
                        grid = played(out.getvalue(), rows)
                        keys = terminal._KEYS
                        if not before:
                            before[:] = texts(grid)
                            terminal._POINTER = terminal.Key("point", "", *at(grid, item))
                            return terminal._POINTER
                        if terminal._POINTER is not None:
                            self.assertEqual(texts(grid)[:keys - 1], before[:keys - 1])
                            self.assertEqual(explanation(grid, keys), sentence)
                            self.assertTrue(texts(grid)[0].startswith("agentkit · config"))
                            terminal._POINTER = None
                            return terminal.Key("point", "", 1, 2)
                        self.assertEqual(texts(grid)[:len(before)], before)
                        self.assertFalse(any(texts(grid)[len(before):]))
                        restored = True
                        return terminal.Key("esc")

                    def matrix():
                        keys = "↑↓←→ move   ⏎ mark   esc back"
                        places = {number: (number, []) for number in range(len(body))}
                        top = 0
                        while True:
                            act, _, _, top = menu.matrix_key(
                                "config", body, places, list(range(len(body))), 0, top, "", keys,
                                tips={(0, None): long} if kind == "row" else None)
                            if act == "back":
                                return

                    choices = [(number, (f"model-{number:02}",)) for number in range(40)]
                    with patch.object(sys, "stdout", out), \
                            patch.dict(os.environ, {"LC_ALL": "C.UTF-8"}), \
                            patch.object(terminal.time, "strftime", return_value="14:06"), \
                            patch.object(terminal, "width", return_value=cols), \
                            patch.object(terminal, "height", return_value=rows), \
                            patch.object(terminal, "colour_depth", return_value=0), \
                            patch.object(terminal, "taken", return_value=True), \
                            patch.object(terminal, "read_key", side_effect=read), \
                            patch.multiple(terminal, _POINTER=None, _SPOTS={}, _POINTED=terminal.Spot(),
                                           _SHOWN=[], _PAINTED=[], _TIPS={}, _KEYS=None), \
                            patch.object(menu, "_add_choices", return_value=choices):
                        menu.config_add({}) if kind == "add" else matrix()

    def test_relighting_adds_and_clears_wrapped_lines_without_moving_the_rows_above(self):
        lines = ["agentkit", "a rule", "  a row", "", "  s solo   esc back"]
        spots = {3: ("row", []), **terminal.key_spots(lines[-1:], 5)}
        sentence = TIPS["n new"]
        out = io.StringIO()
        with patch.object(sys, "stdout", out), patch.object(terminal, "width", return_value=40), \
                patch.object(terminal, "colour_depth", return_value=0), \
                patch.multiple(terminal, _POINTER=None, _SPOTS={}, _POINTED=terminal.Spot(),
                               _SHOWN=[], _PAINTED=[], _TIPS={}, _KEYS=None):
            terminal.show(lines, spots, {("row", None): sentence}, 5)
            terminal._POINTER = terminal.Key("point", "", 3, 3)
            terminal.relight()
            grid = played(out.getvalue())
            wrapped = texts(grid)
            self.assertEqual(wrapped[:4], lines[:4])
            self.assertEqual(explanation(grid, 5), sentence)
            self.assertGreater(len(wrapped), len(lines))
            self.assertTrue(all(terminal.cells(line) <= 40 for line in wrapped))
            self.assertNotIn("…", "\n".join(wrapped))
            terminal._POINTER = terminal.Key("point", "", 3, 5)
            terminal.relight()
            self.assertEqual(explanation(played(out.getvalue()), 5), TIPS["s solo"])
            terminal._POINTER = None
            terminal.relight()
            self.assertEqual([line for line in texts(played(out.getvalue())) if line],
                             [line for line in lines if line])


class MainMenu(unittest.TestCase):
    def test_a_full_main_menu_does_not_scroll_under_key_or_long_session_explanations(self):
        name = "fix-api-00-" + "full-name-" * 12
        seats = {name: "needs you", **{f"fix-api-{n:02}": "needs you" for n in range(1, 40)}}
        for cols in (26, 30, 40):
            with self.subTest(cols=cols), patch.dict(SEATS, seats, clear=True):
                child = menu_child(self, cols=cols, rows=16)
                lines = child.frame()
                before = texts(played(child.text(), 16))
                keys = next(row for row, line in enumerate(lines, 1) if "↑↓ move" in line)
                grid = played(child.text(), 16)
                places = [(at(grid, "n new"), TIPS["n new"]),
                          (at(grid, "›"), TIPS["session"].format(name=name))]
                for place, sentence in places:
                    with self.subTest(sentence=sentence):
                        child.send(move(*place))
                        child.until(lambda text: explanation(played(text, 16), keys).replace(" ", "")
                                    == sentence.replace(" ", ""), "the whole explanation on a full page")
                        shown = texts(played(child.text(), 16))
                        self.assertEqual([line.replace("›", " ") for line in shown[:keys - 1]],
                                         [line.replace("›", " ") for line in before[:keys - 1]])
                        self.assertLess(len(shown), 16, shown)
                        self.assertTrue(all(terminal.cells(line) <= cols for line in shown), shown)
                        child.send(move(1, 1))
                        child.until(lambda text: [line.replace("›", " ")
                                                  for line in texts(played(text, 16))]
                                    == [line.replace("›", " ") for line in before],
                                    "the keys back without extra lines")
                child.leave()

    def test_the_whole_usage_and_key_explanations_fit_forty_columns(self):
        child = menu_child(self, cols=40, rows=24)
        lines = child.frame()
        row = next(number for number, line in enumerate(lines, 1) if line.startswith("  Claude"))
        keys = next(number for number, line in enumerate(lines, 1) if "↑↓ move" in line)
        places = [(5, row, USAGE),
                  (lines[keys - 1].index("n new") + 1, keys, "  " + TIPS["n new"])]
        for column, point_row, sentence in places:
            with self.subTest(sentence=str(sentence)):
                child.send(move(column, point_row))

                def ready(text):
                    said = "  " + explanation(played(text), keys)
                    return sentence.fullmatch(said) if isinstance(sentence, re.Pattern) else said == sentence

                child.until(ready, "the whole wrapped explanation")
                shown = texts(played(child.text()))
                self.assertTrue(all(terminal.cells(line) <= 40 for line in shown), shown)
                self.assertLess(len(shown), 24, shown)
                self.assertNotIn("…", "\n".join(shown[keys - 1:]))
                self.assertTrue(shown[row - 1].startswith("  Claude"))
                self.assertEqual(shown.index("acme"), lines.index("acme"))
                child.send(move(1, 2))
                child.until(lambda text: texts(played(text))[keys - 1:len(lines)] == lines[keys - 1:]
                            and not any(texts(played(text))[len(lines):]), "the keys back without extra lines")
        child.leave()

    def test_each_thing_on_the_main_screen_says_what_it_is_and_the_keys_come_back(self):
        child = menu_child(self)
        lines = child.frame()
        keys = lines[-1]
        self.assertEqual(keys, "  ↑↓ move   ⏎ open   n new   x stop   c config   s solo   esc leave")
        seat = next(row for row, line in enumerate(lines, 1) if "fix-api" in line)
        heading = lines.index("acme") + 1
        usage = next(row for row, line in enumerate(lines, 1) if line.startswith("  Claude"))
        unread = next(row for row, line in enumerate(lines, 1) if line.startswith("  MiMo"))
        places = [
            ((lines[seat - 1].index("fix-api") + 1, seat),
             "  " + TIPS["session"].format(name="fix-api")),
            ((lines[seat - 1].index("needs you") + 1, seat), "  " + TIPS["needs you"]),
            ((3, heading), "  " + TIPS["project"].format(name="acme")),
            ((keys.index("n new") + 1, len(lines)), "  " + TIPS["n new"]),
            ((keys.index("c config") + 3, len(lines)), "  " + TIPS["c config"]),
            ((keys.index("s solo") + 1, len(lines)), "  " + TIPS["s solo"]),
            ((keys.index("↑↓ move") + 1, len(lines)), "  " + TIPS["↑↓ move"]),
            ((5, usage), USAGE),
            ((5, unread), "  " + TIPS["unread"].format(name="MiMo", why="no reading yet"))]
        explains(self, child, places, keys)
        child.leave()

    def test_the_popups_own_keys_say_what_they_do(self):
        child = test_close_and_info.Menu(self, {"alpha": "working"}, own="alpha")
        child.frame()
        first = played(child.text())
        explains(self, child, [(at(first, item), "  " + TIPS[item]) for item in
                               ("n start a session", "r rename this session",
                                "x stop this session", "s solo")], keys_of(first))
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
        # a reading that moves glides there, and the tick stands through it: 58% left
        week, now = 7 * 86400, time.time()
        (child.seats.parent / ".agentkit/state/usage.json").write_text(json.dumps({
            "fetched_at": now, "providers": {"anthropic": {"fetched_at": now, "meters": [
                {"name": "weekly", "used": 42, "window_secs": week,
                 "resets_at": now + 0.6 * week}]}}}))
        child.until(lambda text: "58% left" in keyline(text), "the moved reading's sentence")
        self.assertTrue(keyline(child.text()).endswith("· runs out early at this pace"))
        time.sleep(motion.GLIDE + 0.3)                        # the glide is over
        shown = "".join(cell.char for cell in played(child.text())[row][bar.start():bar.end()])
        self.assertEqual(shown, "███████│░░░░")
        # off the row the tick goes, with the sentence
        child.send(move(1, 2))
        child.until(lambda text: keyline(text) == lines[-1], "the keys back")
        shown = "".join(cell.char for cell in played(child.text())[row][bar.start():bar.end()])
        self.assertEqual(shown, "███████░░░░░")
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

    def test_a_full_new_session_list_does_not_scroll_under_a_wrapped_explanation(self):
        notes = {name: "" for name in config.offered(self.cfg)}

        def picking():
            return orch._picking(self.cfg, {}, notes, dict(self.selected))

        for cols, rows in ((cols, rows) for cols in (26, 30, 40) for rows in (12, 16)):
            for item, sentence in (("↑↓←→ move", TIPS["↑↓ move"]),
                                   ("›", menu.model_tip("opus", self.cfg["models"]["opus"]))):
                with self.subTest(cols=cols, rows=rows, item=item), \
                        patch.object(terminal, "height", return_value=rows), \
                        patch.object(terminal.time, "strftime", return_value="14:06"):
                    first = run(picking, ESC, cols=cols, rows=rows)[1][0]
                    point = at(first, item)
                    keys = at(first, "↑↓←→ move")[1]
                    screens = run(picking, move(*point), move(1, 2), ESC,
                                  cols=cols, rows=rows)[1]
                    before, hovering, left = (texts(screen) for screen in screens[:3])
                    self.assertEqual([line.replace("›", " ") for line in hovering[:keys - 1]],
                                     [line.replace("›", " ") for line in before[:keys - 1]])
                    self.assertEqual(explanation(screens[1], keys), sentence)
                    self.assertTrue(hovering[0].startswith("agentkit · new"))
                    self.assertEqual([line.replace("›", " ") for line in left],
                                     [line.replace("›", " ") for line in before])

    def test_a_model_its_marks_its_effort_and_a_provider_say_what_they_are(self):
        first = self.matrix()[0]
        label = at(first, "astra")
        # a mark is its whole column, under its heading; the effort starts under `effort`
        orch_mark, exec_mark, review_mark, effort = (
            (at(first, head)[0] + 1, label[1]) for head in ("orch", "exec", "review", "effort"))
        said = {label: menu.model_tip("astra", self.cfg["models"]["astra"]),
                orch_mark: TIPS["orch"], exec_mark: TIPS["exec"],
                review_mark: TIPS["review"],
                effort: TIPS["effort"].format(name="astra"),
                at(first, "Claude", 1): "Claude: its worker token expires 2027-09-22 (in 356 days)",
                at(first, "ChatGPT", 1): TIPS["account"].format(name="ChatGPT"),
                at(first, "⏎ mark"): TIPS["⏎ mark"], at(first, "↑↓←→ move"): TIPS["↑↓ move"]}
        for place, sentence in said.items():
            with self.subTest(sentence=sentence):
                screens = self.matrix(move(*place), move(1, 1), ESC)
                self.assertEqual(explanation(screens[1], texts(screens[0]).index(keys_of(screens[0])) + 1),
                                 sentence)
                self.assertRegex(keys_of(screens[2]), r"^  ↑↓(←→)? move   ⏎ \w+   esc back$")

    def test_a_models_own_screen_the_new_session_screen_and_a_list_say_what_they_hold(self):
        def said(screen, *places):
            for place, sentence in places:
                with self.subTest(sentence=sentence):
                    screens = run(screen, move(*place), move(1, 1), ESC)[1]
                    self.assertEqual(explanation(screens[1], texts(screens[0]).index(keys_of(screens[0])) + 1),
                                     sentence)
                    self.assertTrue(keys_of(screens[2]).endswith("esc back"))

        def own():
            return menu.config_model(self.cfg, "opus")
        first = run(own, ESC)[1][0]
        said(own, (at(first, "model id"), TIPS["model id"].format(harness="claude")),
             (at(first, "effort"), TIPS["effort"].format(name="opus")))
        notes = {name: "" for name in config.offered(self.cfg)}

        def picking():
            return orch._picking(self.cfg, {}, notes, dict(self.selected))
        first = run(picking, ESC)[1][0]
        astra = at(first, "astra")
        said(picking, (astra, menu.model_tip("astra", self.cfg["models"]["astra"])),
             ((at(first, "review")[0] + 3, astra[1]), TIPS["review"]))
        self.cfg["providers"]["anthropic"]["accounts"] = ["default", "second"]

        def removing():
            return menu.config_remove_provider(self.cfg)
        first = run(removing, ESC)[1][0]
        said(removing, (at(first, "Claude II"), TIPS["account"].format(name="Claude II")))

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
        for name, sentence in TIPS.items():
            self.assertIn(sentence, design, name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
