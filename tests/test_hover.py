"""Whatever the pointer is over lights up, on every screen: the row under it takes the keys' own
highlight, a key-line item or a cell a subtle background, and that goes when the pointer leaves;
the keys and the pointer never show two highlights, nothing is acted on while the pointer has
the highlight out, and a flood of moves is one draw.

The screens under the menu run in this process on the real `terminal.read_key`, the keyboard
taken, their keys on a pipe written whole before they read, the way one read finds a flood:
a move of the pointer is the SGR report a terminal in modes 1003 and 1006 sends.  What a screen
writes is played onto a grid of cells (`played`), so a test reads what the screen shows, not how
it was written.  The main menu runs as tests/test_menu_keys.py runs it, in a child process on a
pty of its own, so the terminal it takes and gives back is a real one.  Nothing here reads the
owner's ~/.agentkit, starts a session or reaches a project; the only process signalled is the
test's own child.
"""

from collections import namedtuple
import io
import os
from pathlib import Path
import re
import select
import sys
import termios
import threading
import time
import types
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, menu, orch, terminal
from test_menu_keys import Menu
from test_v4n import Sandbox

ESC, RIGHT, DOWN = b"\x1b", b"\x1b[C", b"\x1b[B"
Cell = namedtuple("Cell", "char lit reverse")
FEATURES = [
    {"id": "dark", "name": "Dark mode", "you": False, "everyone": False, "you_switchable": True},
    {"id": "beta", "name": "Beta search", "you": True, "everyone": False, "you_switchable": True},
]


def move(col, row):
    """The pointer moved to `col`, `row` with no button down, as mode 1003 reports it in 1006."""
    return f"\x1b[<35;{col};{row}M".encode()


def played(text, rows=40):
    """The screen `text` leaves: {row: [Cell]}, rows from 1; `lit` where a background is set."""
    grid, row, col, back, reverse, saved = {}, 1, 1, False, False, (1, 1)
    for token in re.findall(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b[78]|.", text, re.S):
        if token in ("\x1b7", "\x1b8"):              # the cursor kept, and back where it was
            saved, (row, col) = ((row, col), (row, col)) if token == "\x1b7" else (saved, saved)
        elif not token.startswith("\x1b["):
            if token == "\r":
                col = 1
            elif token == "\n":                  # the terminal's own \r\n
                row, col = row + 1, 1
            else:
                line = grid.setdefault(row, [])
                line += [Cell(" ", False, False)] * (col - 1 - len(line))
                line[col - 1:col] = [Cell(token, back, reverse)]
                col += 1
            continue
        params, final = token[2:-1], token[-1]
        if final == "H":
            row, col = (int(part) for part in params.split(";")) if params else (1, 1)
        elif final == "A":
            row -= int(params or 1)
        elif final in "KJ":
            grid[row] = grid.get(row, [])[:col - 1]
            for below in range(row + 1, rows + 1) if final == "J" else ():
                grid.pop(below, None)
        elif final == "m":
            codes = [int(code or 0) for code in params.split(";")]
            while codes:
                code = codes.pop(0)
                if code in (38, 48):
                    back = back if code == 38 else True
                    codes = codes[1:] if codes[0] == 5 else codes[3:]
                    codes.pop(0)
                else:
                    back = back and code not in (0, 49)
                    reverse = code == 7 or reverse and code not in (0, 27)
    return grid


def texts(grid):
    """Each row's text, row 1 first, its trailing blanks gone."""
    return ["".join(cell.char for cell in grid.get(row, [])).rstrip()
            for row in range(1, max(grid, default=0) + 1)]


def marked(grid, kind):
    """{row: the text of the cells drawn `lit` or `reverse` on it}."""
    return {row: "".join(cell.char for cell in line if getattr(cell, kind)).strip()
            for row, line in grid.items() if any(getattr(cell, kind) for cell in line)}


def highlighted(grid):
    """The rows the keys' highlight is on: the ones starting with its `›`."""
    return [line for line in texts(grid) if line.startswith("›")]


def at(grid, text, nth=0):
    """(column, row) of the `nth` place `text` is drawn, counted from 1."""
    found = [(line.index(text) + 1, row) for row, line in enumerate(texts(grid), 1)
             if text in line]
    return found[nth]


def run(screen, *keys, cols=100, rows=40, depth=256):
    """`screen()` read off `keys` on a taken keyboard in `depth` colours: what it answered, each
    whole screen it wrote -- the writes from one top-left to the next -- played (`played`).

    The first of `keys` is on the pipe whole before the screen reads, the way one read finds a
    flood, and each after it once the screen has read all before it and drawn what they asked
    for; the pipe is closed behind the last, so a screen reading past them ends on its EOF.
    """
    read, write = os.pipe()
    os.write(write, keys[0])
    out = io.StringIO()

    def feed():
        for chunk in keys[1:]:
            size = -1
            while select.select([read], [], [], 0)[0] or size != len(out.getvalue()):
                size = len(out.getvalue())
                time.sleep(0.15)
            os.write(write, chunk)
        os.close(write)
    feeder = threading.Thread(target=feed, daemon=True)
    feeder.start()
    with open(read, "rb", buffering=0) as stdin, patch.object(sys, "stdin", stdin), \
            redirect_stdout(out), \
            patch.multiple(terminal, _TAKEN=types.SimpleNamespace(again=(None, None)),
                           _KEYED=b"", _PRESSED=False, _POINTER=None, _SPOTS={},
                           _POINTED=terminal.Spot(), _MOVED=0.0, _NEXT=None, _HELD=None,
                           _AWAY=False, _ASKED=False), \
            patch.object(terminal, "colour_depth", return_value=depth), \
            patch.dict(os.environ, {"COLUMNS": str(cols), "LINES": str(rows),
                                    "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}):
        answer = screen()
        feeder.join()
    text, screens = out.getvalue(), []
    for end in [match.start() for match in re.finditer(re.escape("\x1b[H"), text)][1:] + [None]:
        screens.append(played(text[:end], rows))
    return answer, screens


class Screens(Sandbox):
    """Each screen under the menu, read in this process."""

    def setUp(self):
        super().setUp()
        self.selected = {"orchestrator": "opus", "workers": ["opus"], "reviewers": ["astra"]}

    def matrix(self, *keys):
        """The `c` screen on fix-api's marks: each screen it drew."""
        return run(lambda: menu.config_matrix(self.cfg, None, "abc1234", "fix-api",
                                              self.selected, {}), *(keys or [ESC]))[1]

    def assertOneHighlight(self, grid, text):
        rows = highlighted(grid)
        self.assertEqual(len(rows), 1, texts(grid))
        self.assertIn(text, rows[0])

    def test_the_matrix_lights_the_row_and_the_cell_under_the_pointer(self):
        first = self.matrix()[0]
        self.assertOneHighlight(first, "fable")
        label, harness = at(first, "astra"), at(first, "codex")
        line = texts(first)[label[1] - 1]
        mark = (line.index("○", label[0]) + 1, label[1])          # its orchestrator mark
        # on its row the keys' highlight moves there, and off its cells none lights
        last = self.matrix(move(*harness) + ESC)[-1]
        self.assertOneHighlight(last, "astra")
        self.assertEqual(marked(last, "lit"), {})
        # its label is a cell, Enter's to open
        self.assertEqual(marked(self.matrix(move(*label) + ESC)[-1], "lit"), {label[1]: "astra"})
        # on a mark the cell lights, in place of the keys' reverse: one highlight, not two
        last = self.matrix(move(*mark) + ESC)[-1]
        self.assertOneHighlight(last, "astra")
        self.assertEqual(marked(last, "lit"), {mark[1]: "○"})
        self.assertEqual(marked(last, "reverse"), {})
        # a key takes it from there: the next cell is the keys', and nothing is lit
        last = self.matrix(move(*mark) + RIGHT + ESC)[-1]
        self.assertOneHighlight(last, "astra")
        self.assertEqual(marked(last, "lit"), {})
        self.assertEqual(marked(last, "reverse"), {mark[1]: "□"})
        # off every row the row and its cell lose it, a key-line item lighting alone and
        # nothing on no item at all, and an arrow moves it on from where it was
        keys = at(first, "esc back")
        screens = self.matrix(move(*harness), move(*keys), move(1, len(texts(first)) + 2), RIGHT,
                              ESC)
        self.assertEqual(len(screens), 5)
        self.assertEqual(marked(screens[2], "lit"), {keys[1]: "esc back"})
        self.assertEqual((highlighted(screens[2]), marked(screens[2], "reverse")), ([], {}))
        self.assertEqual(marked(screens[3], "lit"), {})
        self.assertEqual((highlighted(screens[3]), marked(screens[3], "reverse")), ([], {}))
        self.assertOneHighlight(screens[4], "astra")
        self.assertEqual(marked(screens[4], "reverse"), {mark[1]: "□"})

    def test_moves_sent_while_the_rule_glides_are_one_draw(self):
        checkout = self.root / "code" / "ACME"
        entry = {"rows": FEATURES, "error": "", "asked": time.monotonic(), "going": True,
                 "set": 0, "flips": {}}
        with patch.object(menu, "switches", return_value=FEATURES), \
                patch.dict(menu._SWITCHES, {str(checkout): entry}):
            first = run(lambda: menu.show_features(checkout), ESC)[1][0]
            dark, beta = at(first, "Dark mode"), at(first, "Beta search")
            flood = b"".join(move(*(dark if n % 2 else beta)) for n in range(499))
            screens = run(lambda: menu.show_features(checkout), flood + move(*dark) + ESC)[1]
        self.assertEqual(len(screens), 2)               # the first draw, and one for them all
        self.assertEqual(len(highlighted(screens[-1])), 1)
        self.assertIn("Dark mode", highlighted(screens[-1])[0])

    def test_five_hundred_moves_in_one_read_draw_one_frame(self):
        first = self.matrix()[0]
        rows = len(texts(first))
        flood = b"".join(move(1 + n % 60, 1 + n % rows) for n in range(499))
        label = at(first, "grok")
        screens = self.matrix(flood + move(*label) + ESC)
        self.assertEqual(len(screens), 2)               # the first draw, and the one for them
        self.assertOneHighlight(screens[-1], "grok")    # where the pointer ended

    def test_the_switches_screen_lights_a_feature_and_its_mark(self):
        checkout = self.root / "code" / "ACME"
        entry = {"rows": FEATURES, "error": "", "asked": None, "going": False, "set": 0,
                 "flips": {}}
        with patch.object(menu, "switches", return_value=FEATURES), \
                patch.dict(menu._SWITCHES, {str(checkout): entry}):
            first = run(lambda: menu.show_features(checkout), ESC)[1][0]
            self.assertOneHighlight(first, "Dark mode")
            row = at(first, "Beta search")[1]
            everyone = (at(first, "everyone")[0] + 3, row)
            last = run(lambda: menu.show_features(checkout), move(*everyone) + ESC)[1][-1]
        self.assertOneHighlight(last, "Beta search")
        self.assertEqual(marked(last, "lit"), {row: "○"})
        self.assertEqual(marked(last, "reverse"), {})

    def test_the_new_session_screen_lights_a_model_and_its_mark(self):
        notes = {name: "" for name in config.offered(self.cfg)}

        def picking(keys):
            return run(lambda: orch._picking(self.cfg, {}, notes, dict(self.selected)), keys)

        answer, screens = picking(ESC)
        self.assertIs(answer, orch.BACK)
        self.assertOneHighlight(screens[0], "Opus")
        row = at(screens[0], "Astra")[1]
        review = (at(screens[0], "review")[0] + 3, row)
        last = picking(move(*review) + ESC)[1][-1]
        self.assertEqual(len(highlighted(last)), 1)
        self.assertEqual(at(last, highlighted(last)[0])[1], row)
        self.assertEqual(marked(last, "lit"), {row: "■"})
        self.assertEqual(marked(last, "reverse"), {})

    def test_a_list_and_a_question_move_their_highlight_onto_the_pointer(self):
        def around():
            terminal.frame("config · add a provider", [""] * 3, "↑↓ move   ⏎ add   esc back")
            return 3

        choices = ["Claude", "ChatGPT", "Grok"]
        answer, screens = run(lambda: terminal.choose(choices, around=around),
                              move(5, 5) + ESC)
        self.assertIsNone(answer)
        self.assertEqual(highlighted(screens[-1]), ["› Grok"])
        keys = at(screens[0], "esc back")
        last = run(lambda: terminal.choose(choices, around=around), move(*keys) + ESC)[1][-1]
        self.assertEqual((marked(last, "lit"), highlighted(last)), ({keys[1]: "esc back"}, []))
        # from Grok onto `esc back` only that is lit; `k` goes on from Grok, the key line's
        # light out with the rest of it
        screens = run(lambda: terminal.choose(choices, around=around), move(5, 5), move(*keys),
                      b"k", move(1, 2), ESC)[1]
        self.assertEqual([(marked(grid, "lit"), highlighted(grid)) for grid in screens[1:]],
                         [({}, ["› Grok"]), ({keys[1]: "esc back"}, []), ({}, ["› ChatGPT"])])
        # on nothing the highlight is out, Enter only brings it back, and the next one picks
        answer, screens = run(lambda: terminal.choose(choices, around=around), move(5, 5),
                              move(1, 2), b"\r", ESC)
        self.assertIsNone(answer)
        self.assertEqual([highlighted(grid) for grid in screens[1:]],
                         [["› Grok"], [], ["› Grok"]])
        self.assertEqual(run(lambda: terminal.choose(choices, around=around), move(5, 5),
                             move(1, 2), b"\r", b"\r")[0], "Grok")
        # asked over a screen's own rows, the pointer on one of them is on nothing of the list's

        def over():
            terminal.frame("agentkit", ["  1  seat-a", "", ""], "esc back",
                           places={0: ("seat-a", [])})
            return 4

        screens = run(lambda: terminal.choose(["Keep", "Stop"], around=over), move(5, 5),
                      move(5, 3), ESC)[1]
        self.assertEqual([highlighted(grid) for grid in screens[1:]], [["› Stop"], []])
        # what the pointer lit is what a click there picks
        self.assertEqual(run(lambda: terminal.choose(choices, around=around),
                             move(5, 4) + b"\x1b[<0;5;4M\x1b[<0;5;4m")[0], "ChatGPT")

        def asked(card):
            terminal.frame("stop", card, "esc back")
            return 3

        answer, screens = run(lambda: terminal.confirm("Stop acme?", "it stops", "Stop", asked),
                              ESC)
        self.assertFalse(answer)
        stop = at(screens[0], "Stop", 1)
        answer, screens = run(lambda: terminal.confirm("Stop acme?", "it stops", "Stop", asked),
                              move(*stop) + ESC)
        self.assertFalse(answer)                        # Esc keeps, wherever the pointer is
        self.assertEqual(len(highlighted(screens[-1])), 1)
        self.assertIn("Stop", highlighted(screens[-1])[0])

    def test_add_a_model_and_a_models_own_screen(self):
        first = run(lambda: menu.config_add(self.cfg), ESC)[1][0]
        answer, screens = run(lambda: menu.config_add(self.cfg), move(*at(first, "codex")) + ESC)
        self.assertIsNone(answer)
        self.assertOneHighlight(screens[-1], "codex")
        first = run(lambda: menu.config_model(self.cfg, "opus"), ESC)[1][0]
        right = at(first, "›", 1)                       # the effort's, after the id's
        last = run(lambda: menu.config_model(self.cfg, "opus"), move(*right) + ESC)[1][-1]
        self.assertOneHighlight(last, "effort")
        self.assertEqual(marked(last, "lit"), {right[1]: "›"})
        # off every row ←/→ only bring the highlight back; a click on an arrow names its row
        stepped = []
        click = "\x1b[<0;{0};{1}M\x1b[<0;{0};{1}m".format(*right).encode()
        with patch.object(menu, "config_effort",
                          lambda cfg, name, step, **_kw: stepped.append(step) or ""):
            run(lambda: menu.config_model(self.cfg, "opus"), move(*right), move(1, 1), RIGHT,
                ESC)
            self.assertEqual(stepped, [])
            run(lambda: menu.config_model(self.cfg, "opus"), move(*right), move(1, 1),
                click + ESC)
        self.assertEqual(stepped, [1])

    def test_the_info_page_lights_the_key_line_item_under_the_pointer(self):
        from agentkit import watch
        with patch.object(menu, "installed", return_value="abc1234"), \
                patch.object(watch, "worker_token_note", return_value=""):
            first = run(menu.show_info, ESC)[1][0]
            keys = at(first, "esc back")
            screens = run(menu.show_info, move(*keys), move(keys[0] + 3, keys[1]), ESC)[1]
            self.assertEqual(marked(screens[-1], "lit"), {keys[1]: "esc back"})
            self.assertEqual(len(screens), 2)           # a move within the item draws nothing
            screens = run(menu.show_info, move(*keys), move(1, 1), ESC)[1]
            self.assertEqual(len(screens), 3)
            self.assertEqual(marked(screens[-1], "lit"), {})    # and one off it puts it out
            last = run(menu.show_info, move(*keys), ESC, depth=8)[1][-1]
        self.assertEqual(marked(last, "reverse"), {keys[1]: "esc back"})    # eight colours

    def test_a_question_typed_on_a_screen_lights_its_key_line(self):
        def typed():
            terminal.frame("new session", [], "esc back")
            return terminal.field("Name: ", "auto")

        first = run(typed, ESC)[1][0]
        keys = at(first, "esc back")
        answer, screens = run(typed, move(*keys), ESC)
        self.assertEqual(answer, terminal.ESC)
        self.assertEqual(marked(screens[-1], "lit"), {keys[1]: "esc back"})
        self.assertIn("Name: auto", texts(screens[-1]))         # the answer's line kept

    def test_a_move_is_answered_at_once_and_one_within_its_spot_never(self):
        read, write = os.pipe()
        self.addCleanup(os.close, write)
        with open(read, "rb", buffering=0) as stdin, patch.object(sys, "stdin", stdin), \
                patch.multiple(terminal, _TAKEN=types.SimpleNamespace(again=(None, None)),
                               _KEYED=b"", _POINTER=None, _POINTED=terminal.Spot(), _MOVED=0.0,
                               _NEXT=None):
            terminal.lit((), {3: ("a", []), 4: ("b", [])})
            os.write(write, move(2, 3))
            began = time.monotonic()
            self.assertEqual(terminal.read_key(1).name, "point")
            self.assertLess(time.monotonic() - began, 0.1)
            terminal.lit((), {3: ("a", []), 4: ("b", [])})     # drawn: a is highlighted
            os.write(write, move(9, 3))
            self.assertIsNone(terminal.read_key(0.2))
            os.write(write, move(9, 4) + b"j")                  # a key read past a move is next
            self.assertEqual(terminal.read_key(1), terminal.Key("point", "", 9, 4))
            self.assertEqual(terminal.read_key(1), terminal.Key("char", "j"))
            self.assertIsNone(terminal._POINTER)                # and hands the highlight back
            # a move a frame has not come for is answered by a later read, once it has
            terminal.lit((), {3: ("a", []), 4: ("b", [])})
            time.sleep(0.06)                                    # a frame since the last move
            os.write(write, move(2, 3))
            self.assertEqual(terminal.read_key(0).name, "point")
            began = time.monotonic()
            os.write(write, move(2, 4))
            self.assertIsNone(terminal.read_key(0))
            self.assertEqual(terminal.read_key(1), terminal.Key("point", "", 2, 4))
            self.assertGreaterEqual(time.monotonic() - began, 0.04)
            # moves on and on within one spot keep to the read's time
            terminal.lit((), {3: ("a", []), 4: ("b", [])})
            going = threading.Event()

            def stream():
                while not going.is_set():
                    os.write(write, move(5, 4))
                    time.sleep(0.001)
            streamer = threading.Thread(target=stream, daemon=True)
            streamer.start()
            began = time.monotonic()
            self.assertIsNone(terminal.read_key(0.05))
            self.assertLess(time.monotonic() - began, 0.1)
            going.set()
            streamer.join()


class MainMenu(unittest.TestCase):
    def test_the_main_list_and_its_key_line_follow_the_pointer_and_the_terminal_comes_back(self):
        menu = Menu(self, ["seat-a", "seat-b", "seat-c"])
        lines = menu.frame()
        self.assertIn("\x1b[?1003h\x1b[?1006h", menu.text())     # every move, in SGR form
        row = next(number for number, line in enumerate(lines, 1) if "seat-c" in line)
        menu.send(move(20, row))
        menu.frame(lambda lines: "seat-c" in menu.highlighted(lines))
        keyline = (lines[-1].index("c config") + 1, len(lines))
        menu.send(move(*keyline))
        menu.until(lambda text: marked(played(text), "lit") == {keyline[1]: "c config"}
                   and not highlighted(played(text)), "c config lit, and no seat")
        # a key moves the one highlight on from the pointer's, and the key line's light goes
        menu.send(b"k")
        menu.frame(lambda lines: any(line.startswith("› 2  seat-b") for line in lines))
        menu.until(lambda text: marked(played(text), "lit") == {}, "nothing lit")
        # on nothing the highlight is out, and `x` only brings it back: no seat is acted on
        # that is not seen
        top = next(number for number, line in enumerate(lines, 1) if "seat-a" in line)
        mark = len(menu.text())
        menu.send(move(20, top))
        menu.frame(lambda lines: "seat-a" in menu.highlighted(lines))
        menu.send(move(1, 2))
        menu.until(lambda text: not highlighted(played(text)), "no seat highlighted")
        menu.send(b"x")
        menu.frame(lambda lines: any(line.startswith("› 1  seat-a") for line in lines))
        time.sleep(0.3)
        self.assertNotIn("everything it runs?", menu.text()[mark:])
        # five hundred moves at once are one draw, the highlight where they ended
        drawn = menu.text().count("<drawing")
        menu.send(b"".join(move(1 + n % 90, top) for n in range(500)))
        menu.frame(lambda lines: "seat-a" in menu.highlighted(lines))
        time.sleep(0.5)
        self.assertLessEqual(menu.text().count("<drawing") - drawn, 1)
        menu.leave()
        self.assertEqual(termios.tcgetattr(menu.slave), menu.before)
        self.assertIn("\x1b[?1006l\x1b[?1003l", menu.text().rsplit("\x1b[J", 1)[-1])

    def test_x_on_a_seat_the_pointer_left_brings_it_back_and_only_the_next_closes_it(self):
        menu = Menu(self, ["seat-a", "done-b"])
        lines = menu.frame()
        row = next(number for number, line in enumerate(lines, 1) if "done-b" in line)
        menu.send(move(20, row))
        lines = menu.frame(lambda lines: "done-b" in menu.highlighted(lines))
        keyline = (lines[-1].index("x close") + 1, len(lines))
        menu.send(move(*keyline))
        menu.until(lambda text: marked(played(text), "lit") == {keyline[1]: "x close"}
                   and not highlighted(played(text)), "x close lit, and no seat")
        mark = len(menu.text())
        menu.send(b"x")
        menu.frame(lambda lines: any(line.startswith("› 2  done-b") for line in lines),
                   after=mark)
        time.sleep(0.3)
        self.assertNotIn("<closed", menu.text())
        menu.send(b"x")
        menu.saw("<closed done-b>")
        menu.leave()
        self.assertEqual(menu.text().count("<closed"), 1)

    def test_the_pointer_moves_the_highlight_while_a_digit_waits_for_a_second(self):
        menu = Menu(self, [f"seat-{n:02d}" for n in range(1, 13)])
        lines = menu.frame()
        row = next(number for number, line in enumerate(lines, 1) if "seat-05" in line)
        menu.send(b"1" + move(20, row))
        text = menu.saw("<opened seat-01>")
        before = played(text[:text.index("<opened seat-01>")])
        self.assertEqual(len(highlighted(before)), 1)
        self.assertIn("seat-05", highlighted(before)[0])        # drawn inside the half second
        menu.frame(lambda lines: "seat-01" in menu.highlighted(lines))
        menu.leave()


if __name__ == "__main__":
    unittest.main(verbosity=2)
