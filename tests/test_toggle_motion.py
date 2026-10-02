"""Every mark in ak fills when set and empties when cleared, a refused one shakes, and a model just
added glows into the highlight.

On the `c` screen, the `n` screen and a project's feature switches a mark goes `□ ▣ ■` or
`○ ◉ ●` over two frames, 80 ms, and back the same way, saved at the key; one ak refuses nudges
a cell left, right, left and back over 240 ms, the reason under the rows and nothing saved; a
model just added comes back highlighted on a soft glow that fades over a second into the
highlight.  All of it is on the menu's one clock, beside the rule gliding while a project's
switches are asked, and the cell a click lit stays lit through it; a key during it ends it on
its last frame.

Each screen runs in a child on a pty of its own through the harness of its own test --
tests/test_config_matrix.py's `c` on the seat `fix-api`, tests/test_new_session_screen.py's
menu for `n`, tests/test_features_screen.py's menu over a fake ACME project -- each in a
temporary HOME, the catalog, meters and project command faked as there.  The cells a frame
writes are read back from where it places the cursor.  Nothing here reads or writes the
owner's ~/.agentkit, and the only process signalled is each test's own child.
The unit clock tests sample every phase; a descheduled pty child may skip intermediate frames
but must reach the last one.
"""

import json
import os
import re
import time
import unittest
from unittest.mock import patch

import test_features_screen as features
import test_new_session_screen as new_session
from test_config_matrix import CHILD, DOWN, ENTER, RIGHT, Screen, highlighted, row
from agentkit import motion, terminal

PLACE = re.compile(r"\x1b\[(\d+);(\d+)H")      # where a frame writes a cell
MARKS = "●○■□◉▣—"
BACK = re.compile(r"\x1b\[[0-9;]*48;2;(\d+);(\d+);(\d+)m")   # a background, in true colour
# the background the pointer lights a cell on, at 256 colours, on the dark one a pty answers with
LIT = f"48;5;{terminal.xterm_colour(terminal.POINTED[False])}m"

# Completion is observed after the real clock's last frame, including a skipped animation.
OBSERVE = r'''
from pathlib import Path
from agentkit import motion
start, frame, glowing = motion.Clock.start, motion.Clock.frame, motion.glowing
def started(clock, cells, animation, until=None):
    if until is not None:
        clock.test_moving = True
    return start(clock, cells, animation, until)
def framed(clock):
    out = frame(clock)
    if getattr(clock, "test_moving", False) and not any(
            until is not None for _, until in clock.cells.values()):
        clock.test_moving = False
        out += "<motion settled>"
    return out
motion.Clock.start, motion.Clock.frame = started, framed

def held_glow(line):
    real = glowing(line)
    def begin(clock, row, since, before):
        hold = Path.home() / ".agentkit" / "glow.hold"
        if hold.exists():
            class Held:
                def start(self, cells, animation, until=None):
                    clock.start(cells, lambda now: animation(since + float(hold.read_text())),
                                float("inf"))
            real(Held(), row, since, before)
        else:
            real(clock, row, since, before)
    return begin
motion.glowing = held_glow
'''


class Screens(unittest.TestCase):
    def setUp(self):
        create = Screen
        self.enterContext(patch(__name__ + ".Screen", side_effect=lambda *args, child=CHILD,
                               **kwargs: create(*args, child=child.replace(
                                   "with closing(", OBSERVE + "\nwith closing(", 1), **kwargs)))
        for module in (features, new_session):
            self.enterContext(patch.object(module, "CHILD", module.CHILD.replace(
                "sys.exit(", OBSERVE + "\nsys.exit(", 1)))
        self.enterContext(patch.object(features, "FAKE", features.FAKE.replace(
            'if sys.argv[1] == "list":', 'if sys.argv[1] == "list":\n'
            '    while (here / "list.hold").exists(): time.sleep(.01)')))


def written(screen, mark):
    """Every cell written since `mark`: [(row, column, what it shows, as written)]."""
    parts, cells = PLACE.split(screen.text()[mark:]), []
    for at, column, text in zip(parts[1::3], parts[2::3], parts[3::3]):
        text = text.split("\x1b[H")[0]            # a whole draw after it is no frame's
        text = text.split("<motion settled>")[0]
        cells.append((int(at), int(column), terminal.ANSI.sub("", text), text))
    return cells


def until(screen, ready, what):
    deadline = time.monotonic() + 15
    while not ready():
        screen.case.assertLess(time.monotonic(), deadline,
                               f"timed out waiting for {what}:\n{screen.text()[-3000:]!r}")
        time.sleep(.01)


def moved(screen, keys):
    mark = len(screen.text())
    os.write(screen.master, keys)
    until(screen, lambda: "<motion settled>" in screen.text()[mark:], "motion to settle")
    return written(screen, mark)


def glyphs(cells, number):
    """The marks the frames wrote on screen row `number`, in order."""
    return [char for at, _, text, _ in cells if at == number for char in text if char in MARKS]


def shifts(cells, number, column):
    """How far each frame on screen row `number` put its mark from `column`, where it is drawn."""
    return [first + next(at for at, char in enumerate(text) if char in MARKS) - column
            for at, first, text, _ in cells if at == number]


def landed(case, actual, expected):
    """The frames a pty saw stay in order and land, even if its child was descheduled."""
    # A pause before Clock.start can skip the whole animation; the full draw already landed.
    if actual:
        case.assertEqual(actual[-1:], expected[-1:])
    remaining = iter(expected)
    for frame in actual:
        case.assertIn(frame, remaining, f"{actual} is not a subsequence of {expected}")


def click(column, number):
    """The left button down and up at `column` on screen row `number`, as mode 1006 reports it."""
    return f"\x1b[<0;{column};{number}M\x1b[<0;{column};{number}m".encode()


def lit_through(case, cells, number):
    """Every frame on screen row `number` shows the clicked cell as the draw did: in the
    pointer's light, the keys' reverse given way to it."""
    frames = [written for at, _, _, written in cells if at == number]
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


class ConfigScreen(Screens):
    def test_a_mark_fills_when_set_and_empties_when_cleared(self):
        screen = Screen(self)
        number, line = row(screen.press(RIGHT), "fable")  # fable's exec, not the seat's
        column = mark_column(line, 1)
        cells = moved(screen, ENTER)
        landed(self, glyphs(cells, number), ["▣", "■"])
        self.assertLessEqual({at for at, _, _, _ in cells}, {number})
        self.assertEqual(screen.record()["workers"], ["opus", "astra", "fable"])
        cells = moved(screen, click(column, number))
        landed(self, glyphs(cells, number), ["▣", "□"])
        landed(self, shifts(cells, number, column), [0, 0])     # in place, no nudge
        lit_through(self, cells, number)
        self.assertEqual(screen.record()["workers"], ["opus", "astra"])
        screen.leave()

    def test_the_last_reviewer_refused_shakes_and_nothing_is_saved(self):
        screen = Screen(self, workers=["opus"])
        number, line = row(screen.frame(), "opus")
        before = screen.record()
        cells = moved(screen, click(mark_column(line, 2), number))
        self.assertIn("  review needs one model", screen.frame())
        landed(self, glyphs(cells, number), ["■"] * 4)
        landed(self, shifts(cells, number, mark_column(line, 2)), [-1, 1, -1, 0])
        lit_through(self, cells, number)
        self.assertEqual(screen.record(), before)
        screen.leave()

    def test_the_last_reviewer_refusal_can_skip_frames(self):
        # A scheduler pause can outlast the shake without changing the refusal or its landing.
        child = CHILD.replace("with closing(", """
import time
from agentkit import motion
wait_key = menu.wait_key
def delayed_wait_key(prompt, timeout=None, wake=None):
    key = wait_key(prompt, timeout, wake)
    if key is None and timeout is not None and timeout <= motion.FRAME:
        time.sleep(motion.SHAKE)
    return key
menu.wait_key = delayed_wait_key
with closing(""", 1)
        create = Screen
        with patch(__name__ + ".Screen", side_effect=lambda *args, **kwargs:
                   create(*args, child=child, **kwargs)):
            self.test_the_last_reviewer_refused_shakes_and_nothing_is_saved()

    def test_a_model_just_added_glows_and_a_key_ends_it_at_once(self):
        screen = Screen(self, env={"COLORTERM": "truecolor"})     # a glow fades in fine steps
        lines = screen.frame()
        down = sum(1 for line in lines[3:next(n for n, line in enumerate(lines)
                                              if "+ add a model" in line)]
                   if line.startswith(("  ", "›")))
        screen.press(DOWN * down, lambda lines: highlighted(lines).startswith("› + add a model"))
        for step in ("harness", "model", "effort"):     # claude, its haiku, at none
            screen.press(ENTER, lambda lines, step=step: f"  {step}" in lines)
        hold = screen.path.parent / "glow.hold"
        hold.write_text("0")
        mark = len(screen.text())
        os.write(screen.master, ENTER)
        lines = screen.frame(lambda lines: highlighted(lines).startswith("› claude-haiku"),
                             after=mark)
        number, line = row(lines, "claude-haiku")

        def tones():
            return [sum(map(int, BACK.findall(frame)[0]))
                    for at, column, text, frame in written(screen, mark)
                    if (at, column) == (number, 1) and text == line and BACK.search(frame)]

        # Hold each phase until it is seen, so a busy host cannot miss the middle of the glow.
        for count, phase in enumerate(("0", "0.4", "0.7"), 1):
            hold.with_suffix(".next").write_text(phase)
            hold.with_suffix(".next").replace(hold)
            until(screen, lambda: len(set(tones())) >= count, f"glow phase {phase}")
        tones = tones()
        self.assertEqual(tones, sorted(tones, reverse=True))       # fading
        self.assertGreater(tones[0], tones[-1])
        # The glow stays held until a key ends it; the key cannot wait for its timer.
        mark = len(screen.text())
        moved(screen, RIGHT)
        lines = screen.frame(lambda lines: highlighted(lines).startswith("› claude-haiku"),
                             after=mark)
        self.assertNotRegex(screen.text()[mark:].rpartition("<motion settled>")[2], PLACE)
        self.assertEqual(screen.saved()["models"]["claude-haiku"]["effort"], "none")
        screen.leave()


class NewSessionScreen(Screens):
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
        landed(self, glyphs(cells, number), ["▣", "□"])
        cells = moved(screen, click(mark_column(line, 1), number))
        landed(self, glyphs(cells, number), ["▣", "■"])
        lit_through(self, cells, number)
        screen.send(ENTER)
        screen.saw("<created new opus astra,opus opus,astra>")
        screen.leave()

    def test_the_last_reviewer_refused_shakes_and_stays_chosen(self):
        screen, lines = self.picker()
        screen.send(RIGHT + new_session.SPACE)          # Opus's review off: Astra is the last one
        lines = screen.picker(lambda lines: new_session.marks(highlighted(lines)) == "●■□")
        number, line = numbered(lines, "astra")
        cells = moved(screen, click(mark_column(line, 2), number))
        self.assertIn("review needs one model", "\n".join(screen.picker()))
        landed(self, shifts(cells, number, mark_column(line, 2)), [-1, 1, -1, 0])
        lit_through(self, cells, number)
        self.assertEqual(new_session.marks(highlighted(screen.picker())), "○■■")
        screen.send(ENTER)
        screen.saw("<created new opus opus,astra astra>")
        screen.leave()


class FeaturesScreen(Screens):
    def test_a_switch_fills_when_set_on_and_empties_when_set_off(self):
        menu = features.Menu(self)
        number, _ = numbered(menu.opened(), "Dark mode")
        cells = moved(menu, ENTER)                    # the project's `set` answers first
        landed(self, glyphs(cells, number), ["◉", "●"])
        cells = moved(menu, ENTER)
        landed(self, glyphs(cells, number), ["◉", "○"])
        self.assertEqual(menu.calls().count("set dark you on"), 1)
        self.assertIn("set dark you off", menu.calls())
        menu.leave(screen=True)

    def test_a_switch_the_project_refused_shakes_and_stays(self):
        menu = features.Menu(self)
        number, line = numbered(menu.opened(), "Dark mode")
        (menu.fake / "refuse").write_text("only the owner may switch dark\n")
        before = (menu.fake / "features.json").read_text()
        cells = moved(menu, click(mark_column(line, 0), number))
        self.assertIn("  only the owner may switch dark",
                      menu.frame(features.SCREEN, features.has("only the owner")))
        landed(self, shifts(cells, number, mark_column(line, 0)), [-1, 1, -1, 0])
        lit_through(self, cells, number)
        self.assertEqual((menu.fake / "features.json").read_text(), before)
        self.assertEqual(json.loads(before)[0]["you"], False)
        menu.leave(screen=True)

    def test_a_switch_moves_on_while_its_list_is_asked(self):
        # Keep the list unanswered while both switches land; elapsed time cannot release it.
        with patch.object(features, "CHILD", features.CHILD.replace(
                "sys.exit(", "menu.TICK = 1.0\nsys.exit(")):
            menu = features.Menu(self)
        number, line = numbered(menu.opened(), "Dark mode")
        hold = menu.fake / "list.hold"
        hold.touch()
        self.addCleanup(lambda: hold.unlink(missing_ok=True))
        started = menu.calls().count("list")
        menu.until(lambda: menu.calls().count("list") > started, "a list asked")
        cells = moved(menu, ENTER)
        landed(self, glyphs(cells, number), ["◉", "●"])
        (menu.fake / "refuse").write_text("only the owner may switch dark\n")
        cells = moved(menu, ENTER)
        landed(self, shifts(cells, number, mark_column(line, 0)), [-1, 1, -1, 0])
        hold.unlink()
        menu.leave(screen=True)


if __name__ == "__main__":
    unittest.main()
