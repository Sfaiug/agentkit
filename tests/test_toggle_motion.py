"""Every mark in ak fills when set and empties when cleared, a refused one shakes, and a model just
added glows into the highlight.

On the `c` screen, the `n` screen and a project's feature switches a mark goes `□ ▣ ■` or
`○ ◉ ●` over two frames, 80 ms, and back the same way, saved at the key; one ak refuses nudges
a cell left, right, left and back over 240 ms, the reason under the rows and nothing saved; a
model just added comes back highlighted on a soft glow that fades over a second into the
highlight.  All of it is on the menu's one clock, beside the rule gliding while a project's
switches are asked, and the cell a click lit stays lit through it; a key during it is answered
within 100 ms and ends it on its last frame.

Each screen runs in a child on a pty of its own through the harness of its own test --
tests/test_config_matrix.py's `c` on the seat `fix-api`, tests/test_new_session_screen.py's
menu for `n`, tests/test_features_screen.py's menu over a fake ACME project -- each in a
temporary HOME, the catalog, meters and project command faked as there.  The cells a frame
writes are read back from where it places the cursor.  Nothing here reads or writes the
owner's ~/.agentkit, and the only process signalled is each test's own child.
"""

import json
import os
import re
import time
import unittest
from unittest.mock import patch

import test_features_screen as features
import test_new_session_screen as new_session
from test_config_matrix import DOWN, ENTER, RIGHT, Screen, highlighted, row
from agentkit import motion, terminal

PLACE = re.compile(r"\x1b\[(\d+);(\d+)H")      # where a frame writes a cell
MARKS = "●○■□◉▣—"
BACK = re.compile(r"\x1b\[[0-9;]*48;2;(\d+);(\d+);(\d+)m")   # a background, in true colour
# the background the pointer lights a cell on, at 256 colours, on the dark one a pty answers with
LIT = f"48;5;{terminal.xterm_colour(terminal.POINTED[False])}m"


def moved(screen, keys, wait=1.0):
    """Keys, then every cell the frames wrote in the `wait` seconds after them: [(row, column,
    what it shows, as written)]."""
    mark = len(screen.text())
    os.write(screen.master, keys)
    time.sleep(wait)
    parts, cells = PLACE.split(screen.text()[mark:]), []
    for at, column, text in zip(parts[1::3], parts[2::3], parts[3::3]):
        text = text.split("\x1b[H")[0]            # a whole draw after it is no frame's
        cells.append((int(at), int(column), terminal.ANSI.sub("", text), text))
    return cells


def glyphs(cells, number):
    """The marks the frames wrote on screen row `number`, in order."""
    return [char for at, _, text, _ in cells if at == number for char in text if char in MARKS]


def shifts(cells, number, column):
    """How far each frame on screen row `number` put its mark from `column`, where it is drawn."""
    return [first + next(at for at, char in enumerate(text) if char in MARKS) - column
            for at, first, text, _ in cells if at == number]


def click(column, number):
    """The left button down and up at `column` on screen row `number`, as mode 1006 reports it."""
    return f"\x1b[<0;{column};{number}M\x1b[<0;{column};{number}m".encode()


def lit_through(case, cells, number):
    """Every frame on screen row `number` shows the clicked cell as the draw did: in the
    pointer's light, the keys' reverse given way to it."""
    frames = [written for at, _, _, written in cells if at == number]
    case.assertTrue(frames)
    for frame, written in enumerate(frames):
        with case.subTest(frame=frame):
            case.assertIn(LIT, written)
            case.assertNotIn("\x1b[7m", written)


def mark_column(line, number):
    """The terminal column of a drawn line's `number`th mark, counted from 1."""
    return [at for at, char in enumerate(line, 1) if char in MARKS][number]


def numbered(lines, name):
    """(the terminal row, the line) of the first line `name` is on."""
    return next((number, line) for number, line in enumerate(lines, 1) if name in line)


class Frames(unittest.TestCase):
    """What each motion shows at each moment of its clock."""

    def setUp(self):
        patcher = patch.object(terminal, "colour_depth", return_value=24)
        patcher.start()
        self.addCleanup(patcher.stop)

    def animation(self, start, before, cell):
        clock, since = motion.Clock(), time.monotonic()
        start(clock, 5, since, before)
        (at, until), = [clock.cells[cell]]
        return at, until - since, since

    def test_a_mark_fills_and_empties_over_two_frames_in_80_ms(self):
        for before, after, half in (("□", "■", "▣"), ("■", "□", "▣"), ("○", "●", "◉"),
                                    ("●", "○", "◉")):
            with self.subTest(before=before, after=after):
                at, lasts, since = self.animation(motion.toggled(after, 4, None, False, 10),
                                                  before, (5, 10))
                self.assertAlmostEqual(lasts, 0.08)
                # the frame the draw writes, and the one a frame later, each its whole column
                self.assertEqual([at(since + t) for t in (0, motion.FRAME)],
                                 [f" {half}  ", f" {after}  "])

    def test_a_refused_mark_nudges_left_right_left_and_back_in_240_ms(self):
        at, lasts, since = self.animation(motion.toggled("■", 4, None, False, 10), "■", (5, 9))
        self.assertAlmostEqual(lasts, 0.24)
        frames = [at(since + t) for t in (0, 0.07, 0.13, 0.19, 0.24)]
        self.assertEqual([text.index("■") - 2 for text in frames], [-1, 1, -1, 0, 0])
        self.assertEqual(frames[-1], "  ■   ")      # back where the draw has it

    def test_a_row_just_added_glows_and_fades_into_it_over_a_second(self):
        line = terminal.highlight("  claude-haiku  claude")
        at, lasts, since = self.animation(motion.glowing(line), None, (5, 1))
        self.assertAlmostEqual(lasts, 1.0)
        backs = [set(BACK.findall(at(since + t))) for t in (0, 0.5)]
        glow = terminal.faded("accent", motion.GLOWING)
        self.assertEqual(backs[0], {tuple(str(int(glow[i:i + 2], 16)) for i in (1, 3, 5))})
        self.assertEqual(len(backs[1]), 1)
        self.assertNotEqual(backs[1], backs[0])
        self.assertEqual(at(since + 1.0), line)     # then the highlight, as drawn

    def test_without_utf8_a_mark_lands_at_once(self):
        clock = motion.Clock()
        motion.toggled("x", 4, None, False, 10)(clock, 5, time.monotonic(), ".")
        self.assertEqual(clock.cells, {})


class ConfigScreen(unittest.TestCase):
    def test_a_mark_fills_when_set_and_empties_when_cleared(self):
        screen = Screen(self)
        number, line = row(screen.press(RIGHT), "fable")  # fable's exec, not the seat's
        column = mark_column(line, 1)
        cells = moved(screen, ENTER)
        self.assertEqual(glyphs(cells, number), ["▣", "■"])
        self.assertEqual({at for at, _, _, _ in cells}, {number})
        self.assertEqual(screen.record()["workers"], ["opus", "astra", "fable"])
        cells = moved(screen, click(column, number))
        self.assertEqual(glyphs(cells, number), ["▣", "□"])
        self.assertEqual(shifts(cells, number, column), [0, 0])     # in place, no nudge
        lit_through(self, cells, number)
        self.assertEqual(screen.record()["workers"], ["opus", "astra"])
        screen.leave()

    def test_the_last_executor_refused_shakes_and_nothing_is_saved(self):
        screen = Screen(self, workers=["opus"])
        number, line = row(screen.frame(), "opus")
        before = screen.record()
        cells = moved(screen, click(mark_column(line, 1), number))
        self.assertIn("  exec needs one model", screen.frame())
        self.assertEqual(glyphs(cells, number), ["■"] * 4)
        self.assertEqual(shifts(cells, number, mark_column(line, 1)), [-1, 1, -1, 0])
        lit_through(self, cells, number)
        self.assertEqual(screen.record(), before)
        screen.leave()

    def test_a_model_just_added_glows_and_a_key_ends_it_at_once(self):
        screen = Screen(self, env={"COLORTERM": "truecolor"})     # a glow fades in fine steps
        lines = screen.frame()
        down = sum(1 for line in lines[3:next(n for n, line in enumerate(lines)
                                              if "+ add a model" in line)]
                   if line.startswith(("  ", "›")))
        screen.press(DOWN * down, lambda lines: highlighted(lines).startswith("› + add a model"))
        for step in ("harness", "model", "effort"):     # claude, its haiku, at none
            screen.press(ENTER, lambda lines, step=step: f"  {step}" in lines)
        cells = moved(screen, ENTER, wait=0.4)
        lines = screen.frame(lambda lines: highlighted(lines).startswith("› claude-haiku"))
        number, line = row(lines, "claude-haiku")
        glows = [written for at, column, text, written in cells
                 if (at, column) == (number, 1) and text == line]
        self.assertGreater(len(glows), 2)
        tones = [sum(map(int, BACK.findall(written)[0])) for written in glows]
        self.assertEqual(tones, sorted(tones, reverse=True))       # fading
        self.assertGreater(tones[0], tones[-1])
        # a key mid-glow, the highlight staying on the row: drawn within 100 ms, the glow over
        # at once, nothing moving after it
        mark = len(screen.text())
        pressed = time.monotonic()
        os.write(screen.master, RIGHT)
        while "\x1b[J" not in screen.text()[mark:]:
            time.sleep(0.002)
        self.assertLess(time.monotonic() - pressed, 0.1)
        lines = screen.frame(lambda lines: highlighted(lines).startswith("› claude-haiku"),
                             after=mark)
        time.sleep(1.0)
        self.assertNotRegex(screen.text()[mark:].rpartition("\x1b[J")[2], PLACE)
        self.assertEqual(screen.saved()["models"]["claude-haiku"]["effort"], "none")
        screen.leave()


class NewSessionScreen(unittest.TestCase):
    def picker(self):
        screen = new_session.Screen(self)
        screen.menu()
        screen.send(b"n")
        screen.saw("Name: ")
        screen.send(ENTER)
        screen.picker()
        mark = len(screen.text())
        screen.send(RIGHT)                              # Opus's exec
        return screen, screen.picker(after=mark)

    def test_a_mark_empties_when_cleared_and_fills_when_set(self):
        screen, lines = self.picker()
        number, line = numbered(lines, "opus")
        cells = moved(screen, new_session.SPACE)
        self.assertEqual(glyphs(cells, number), ["▣", "□"])
        cells = moved(screen, click(mark_column(line, 1), number))
        self.assertEqual(glyphs(cells, number), ["▣", "■"])
        lit_through(self, cells, number)
        screen.send(ENTER)
        screen.saw("<created new opus astra,opus opus,astra>")
        screen.leave()

    def test_the_last_executor_refused_shakes_and_stays_chosen(self):
        screen, lines = self.picker()
        screen.send(new_session.SPACE)                  # Opus off: Astra is the last one
        lines = screen.picker(lambda lines: new_session.marks(highlighted(lines)) == "●□■")
        number, line = numbered(lines, "astra")
        cells = moved(screen, click(mark_column(line, 1), number))
        self.assertIn("exec needs one model", "\n".join(screen.picker()))
        self.assertEqual(shifts(cells, number, mark_column(line, 1)), [-1, 1, -1, 0])
        lit_through(self, cells, number)
        self.assertEqual(new_session.marks(highlighted(screen.picker())), "○■■")
        screen.send(ENTER)
        screen.saw("<created new opus astra opus,astra>")
        screen.leave()


class FeaturesScreen(unittest.TestCase):
    def test_a_switch_fills_when_set_on_and_empties_when_set_off(self):
        menu = features.Menu(self)
        number, _ = numbered(menu.opened(), "Dark mode")
        cells = moved(menu, ENTER, wait=1.5)            # the project's `set` answers first
        self.assertEqual(glyphs(cells, number), ["◉", "●"])
        cells = moved(menu, ENTER, wait=1.5)
        self.assertEqual(glyphs(cells, number), ["◉", "○"])
        self.assertEqual(menu.calls().count("set dark you on"), 1)
        self.assertIn("set dark you off", menu.calls())
        menu.leave(screen=True)

    def test_a_switch_the_project_refused_shakes_and_stays(self):
        menu = features.Menu(self)
        number, line = numbered(menu.opened(), "Dark mode")
        (menu.fake / "refuse").write_text("only the owner may switch dark\n")
        before = (menu.fake / "features.json").read_text()
        cells = moved(menu, click(mark_column(line, 0), number), wait=1.5)
        self.assertIn("  only the owner may switch dark",
                      menu.frame(features.SCREEN, features.has("only the owner")))
        self.assertEqual(shifts(cells, number, mark_column(line, 0)), [-1, 1, -1, 0])
        lit_through(self, cells, number)
        self.assertEqual((menu.fake / "features.json").read_text(), before)
        self.assertEqual(json.loads(before)[0]["you"], False)
        menu.leave(screen=True)

    def test_a_switch_moves_on_while_its_list_is_asked(self):
        # the list asked again every second and three in answering: one is nearly always going,
        # its rule gliding, while a `set` answers
        with patch.object(features, "CHILD", features.CHILD.replace(
                "sys.exit(", "menu.TICK = 1.0\nsys.exit(")):
            menu = features.Menu(self)
        number, line = numbered(menu.opened(), "Dark mode")
        (menu.fake / "slow").write_text("3")

        def asked():        # a list just asked, three seconds from answering
            started = menu.calls().count("list")
            menu.until(lambda: menu.calls().count("list") > started, "a list asked")
        asked()
        cells = moved(menu, ENTER)
        self.assertEqual(glyphs(cells, number), ["◉", "●"])
        (menu.fake / "refuse").write_text("only the owner may switch dark\n")
        asked()
        cells = moved(menu, ENTER)
        self.assertEqual(shifts(cells, number, mark_column(line, 0)), [-1, 1, -1, 0])
        menu.leave(screen=True)


if __name__ == "__main__":
    unittest.main()
