"""While a card asks (terminal.confirm), the screen around it draws no highlight of its own, as it
draws none once the pointer leaves its rows (terminal.away): from the card's first frame the one
`›` is the card's answer's, and no cell but that answer's has a background, wherever the card
moved the row it asks about -- but what the row had lit and the card left where it was, which
fades as the highlight does where it leaves (motion.LEAVES; the owner, 20 Nov 2026:
"Build the fade"), the pointer moving under the card or not -- and what that row opened stays
open; Keep gives the row all its highlight back, glowing as it comes (motion.LANDS).  The owner,
10 Nov 2026: "I want absolute consistency!!!"

Each screen that asks on a clock of its own -- past sessions' `x`, the ak screen's `x` over a
seat, config's Apply, removing a subscription and the models screen's Restart -- runs in this
process as tests/test_a_card_comes_up.py runs them, on a true-colour terminal that sets no
background, in the black theme, and a clock moving only as its waits run
(tests/test_breathing.py): what each wait had written before it is played onto a grid of cells,
each with its background.
"""

from contextlib import ExitStack, redirect_stdout
import copy
import io
import os
import re
import threading
import unittest
from unittest.mock import Mock, patch

import test_breathing
from fixtures.sandbox import menu_input
from agentkit import config, menu, motion, orch, terminal

Key = terminal.Key
SELECTION, COMES = "08305d", "2764a6"       # the black theme's, and where the highlight comes
LANDS = 0.25                                # the seconds it takes to settle (motion.LANDS)
TOKEN = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b[78]|.", re.S)
# Keep's lit cells (`terminal.choose`): its text and a cell each side, after the mark's
KEEP = dict.fromkeys(range(2, terminal.cells("✓ Keep") + 4), SELECTION)


class Grid:
    """The screen what is written leaves: {row: {column: (character, its background `rrggbb`, or
    None)}}, both counted from 1."""

    def __init__(self):
        self.rows, self.at, self.saved, self.back = {}, (1, 1), (1, 1), None

    def play(self, text):
        row, col = self.at
        for token in TOKEN.findall(text):
            if token in ("\x1b7", "\x1b8"):      # the cursor kept, and back where it was
                self.saved, (row, col) = ((row, col), (row, col)) if token == "\x1b7" else (
                    self.saved, self.saved)
            elif token in "\r\n":
                row, col = row + (token == "\n"), 1     # the terminal's own \r\n
            elif not token.startswith("\x1b"):
                self.rows.setdefault(row, {})[col] = (token, self.back)
                col += terminal.cells(token)
            elif token[-1] == "H":
                row, col = map(int, token[2:-1].split(";")) if token[2:-1] else (1, 1)
            elif token[-1] in "KJ":
                self.rows[row] = {at: cell for at, cell in self.rows.get(row, {}).items()
                                  if at < col}
                if token[-1] == "J":
                    self.rows = {number: cells for number, cells in self.rows.items()
                                 if number <= row}
            elif token[-1] == "m":
                codes = [int(code or 0) for code in token[2:-1].split(";")]
                while codes:
                    code = codes.pop(0)
                    if code in (38, 48):
                        size = 2 if codes[:1] == [5] else 4         # 5;n or 2;r;g;b
                        self.back = bytes(codes[1:4]).hex() if code == 48 and size == 4 \
                            else self.back
                        codes = codes[size:]
                    elif code in (0, 49):
                        self.back = None
        self.at = row, col

    def text(self, row):
        cells = self.rows.get(row, {})
        return "".join(cells.get(col, (" ",))[0] for col in range(1, max(cells, default=0) + 1))

    def find(self, word):
        """The rows `word` is on, top down."""
        return [row for row in sorted(self.rows) if word in self.text(row)]

    def marks(self):
        """(row, column) of each `›` on the screen."""
        return [(row, col) for row, cells in sorted(self.rows.items())
                for col, (char, _) in sorted(cells.items()) if char == "›"]

    def backs(self, row):
        """{column: background} of each of `row`'s cells on one."""
        return {col: back for col, (_, back) in self.rows.get(row, {}).items() if back}


class CardsHighlight(test_breathing.MainScreen):
    def setUp(self):
        super().setUp()
        self.words = dict.fromkeys(("fix-api", "tidy-docs", "web-portal"), "idle")
        repo = str(config.CODE / "acme")
        for target, name, fake in (
                (orch, "listing", lambda **_kw: [{"name": name, "repo": repo, "path": repo,
                                                  "created": 0} for name in self.words]),
                (orch, "listed", lambda: {}),
                (orch, "checkout_of", lambda repo, **_kw: repo),
                (menu, "past_said", lambda seat: ("", "")),
                (menu.transitions, "seat_runs", lambda name: []),
                (menu, "remove_seat", lambda *seat: self.fail("removed")),
                (menu, "stop_behind", lambda *seat: self.fail("stopped"))):
            self.stack.enter_context(patch.object(target, name, fake))

    def answered(self, script, run):
        """`run()` with each wait answered from `script` -- None running it to its frame, skipped
        where the wait has no end, a key at once, the pointer where a move puts it
        (terminal.read_key) -- then Esc: (when, the screen up, the key it read) at each wait."""
        steps, grid, shown, out = list(script), Grid(), [], io.StringIO()
        out.isatty = lambda: True           # a terminal, as far as colour is concerned

        def wait(timeout=None):
            grid.play(re.sub(r"\x1b\[\?2026[hl]", "", out.getvalue()))
            out.seek(0)
            out.truncate()
            while steps[:1] == [None] and timeout is None:
                steps.pop(0)                # nothing moves: the wait ends on the next key
            key = steps.pop(0) if steps else Key("esc")
            shown.append((self.now, copy.deepcopy(grid), key))
            self.assertLess(len(shown), 400, "the screen never went back")
            if key is None:
                self.sleep(timeout)
            elif key and key.name == "point":
                terminal._point(key)
            return key
        with menu_input(wait=lambda prompt, timeout=None, wake=None: wait(timeout),
                        return_value="q"), redirect_stdout(out), \
                patch.object(terminal, "read_key", lambda timeout=None, wake=None: wait(timeout)), \
                patch.object(terminal, "_TAKEN", test_breathing.Keyboard()), \
                patch.multiple(terminal, _UP=None, _SPOTS={}, _ASKED=False, _POINTER=None,
                               _AWAY=False):
            run()
        return shown

    def past(self, *script, first=()):
        """`x` on past sessions, fix-api-1 highlighted, after the keys `first`, then `script` on
        its card."""
        found = [dict(name=f"fix-api-{n}", repo="/x/acme", closed=1000.0 - n) for n in (1, 2, 3)]
        return self.answered([*first, Key("char", "x"), *script], lambda: menu.show_past(
            self.cfg, found, keyboard=Mock()))

    def ak(self, *script):
        """`x` in the popup over fix-api, its row highlighted, then `script` on its card."""
        def run():
            with patch.object(config, "current_session", return_value="fix-api"):
                self.assertEqual(menu.loop(self.cfg, dry_run=True, overlay=True), 0)
        return self.answered([Key("char", "x"), *script, Key("esc"), ""], run)

    def apply(self, *script, first=()):
        """`a` on a fresh window's `c`, its first model highlighted, after the keys `first`,
        then `script` on its card."""
        records = dict.fromkeys(self.words, {"orchestrator": "another"})
        with patch.object(config, "session_records", return_value=records), \
                patch.object(orch, "switch_lines", return_value=None):
            return self.answered([*first, Key("char", "a"), *script], lambda: menu.config_matrix(
                self.cfg, Mock(), "abc1234", None, copy.deepcopy(self.cfg["defaults"]), {},
                fresh=True))

    def remove(self, *script):
        """`− remove` under Claude II: `script` on its card, the page's own."""
        cfg = {"providers": {"anthropic": {"accounts": ["default", "b2"]}}}
        return self.answered(script, lambda: menu.config_remove_provider(
            cfg, ("anthropic", "b2", "Claude II")))

    def left(self, shown, up, when):
        """What the screen had lit as its card came up, at wait `up`, as it is at `when`: {row:
        {column: the colour a highlight that left then has by now}} (motion.LEAVES), each row's
        cells none once it is over."""
        since, before = shown[up][0], shown[up - 1][1]
        glow = motion.painted(motion.lighting(
            (since, motion.LEAVES, motion.SELECTED, motion.BACKGROUND, ()), when))
        return {row: dict.fromkeys(before.backs(row) if (when - since) / motion.LEAVES < 1 else (),
                                   glow) for row in before.rows if before.backs(row)}

    def asks(self, shown, answer, fades=False):
        """From the first frame with the card to the one its answer is read on, the one `›` is
        Keep's and the one cells with a background are Keep's lit ones -- and, where the screen
        `fades` what it had lit, those cells till they have (`left`): the wait the card is up
        at, and the one its answer is read at."""
        up = next(n for n, (_, grid, _) in enumerate(shown) if grid.find("✓ Keep"))
        read = next(n for n in range(up, len(shown)) if shown[n][2] is not None)
        self.assertEqual(bool(fades and self.left(shown, up, shown[up][0])), fades)
        for when, grid, _ in shown[up:read + 1]:
            (keep,), (act,) = grid.find("✓ Keep"), grid.find(f"× {answer}")
            self.assertEqual(grid.marks(), [(keep, 1)], [grid.text(row) for row in grid.rows])
            left = self.left(shown, up, when) if fades else {}
            self.assertEqual({row: grid.backs(row) for row in grid.rows if grid.backs(row)},
                             {**{row: cells for row, cells in left.items() if cells}, keep: KEEP})
        return up, read

    def kept(self, shown, read, words):
        """Keep read at wait `read`: the card gone, the one `›` back on the row starting with
        `words` it was on before the card came up, every cell it lit there on COMES, and on the
        selection again on the frame a quarter second on."""
        up = next(n for n, (_, grid, _) in enumerate(shown) if grid.find("✓ Keep"))
        before = shown[up - 1][1]
        (row, _), = before.marks()
        self.assertEqual(before.text(row)[1:].split()[:len(words)], words)
        lit = before.backs(row)
        self.assertEqual(set(lit.values()), {SELECTION}, before.text(row))
        since, grid, _ = shown[read + 1]
        self.assertEqual(grid.find("✓ Keep"), [])
        self.assertEqual((grid.marks(), grid.text(row)), (before.marks(), before.text(row)))
        self.assertEqual(grid.backs(row), dict.fromkeys(lit, COMES))
        when, landed, _ = next(frame for frame in shown[read + 1:]     # the clock's float drift
                               if frame[0] - since > LANDS - motion.FRAME / 2)
        self.assertAlmostEqual(when - since, LANDS)
        self.assertEqual(landed.backs(row), lit)

    def test_each_card_has_the_highlight_and_keep_gives_it_back_to_the_row(self):
        frames = [None] * (round(LANDS / motion.FRAME) + 1)     # past the quarter second
        model = config.model_name(self.cfg, next(iter(self.cfg["models"])))    # its first row
        for case, (run, answer, row) in {
                "past sessions": (self.past, "Remove", ["1", "fix-api-1"]),
                "the ak screen": (self.ak, "Stop", ["1", "fix-api"]),
                "config": (self.apply, menu.APPLY_ANSWER, model.split()),
                "a subscription": (self.remove, "Remove", None)}.items():     # the page's own: no row
            with self.subTest(case):
                shown = run(*frames, Key("enter"), *frames * 2)
                up, read = self.asks(shown, answer, bool(row))
                self.assertEqual(bool(up), bool(row))
                if row:             # asked over a screen, which Keep keeps
                    self.kept(shown, read, row)

    def test_a_row_of_lines_the_card_moves_up_one_is_lit_on_none(self):
        # the last: two more lines, reading alike, the second then where the first was
        for case, (run, size, name, said) in {
                "past sessions": (self.past, (30, 15), "fix-api-1", ()),
                "the ak screen": (self.ak, (40, 16), "fix-api", ()),
                "lines alike": (self.past, (30, 17), "fix-api-1", ("Run checks.",) * 2)}.items():
            with self.subTest(case), patch.object(terminal, "width", return_value=size[0]), \
                    patch.object(terminal, "height", return_value=size[1]), \
                    patch.object(menu, "past_said", lambda seat: said or ("", "")), \
                    patch.dict(self.words, {"fix-api": "working"}):    # the seat's no plan line
                shown = run(*[None] * 6)
                up, _ = self.asks(shown, "Stop" if run == self.ak else "Remove")
                before, grid = shown[up - 1][1], shown[up][1]
                lit = [row for row in sorted(before.rows)
                       if SELECTION in before.backs(row).values()]
                self.assertEqual(lit, list(range(lit[0], lit[0] + 2 + len(said))),
                                 [before.text(row) for row in before.rows])
                self.assertIn(name, before.text(lit[0]))
                moved = [row - 1 for row in lit]
                self.assertIn(name, grid.text(moved[0]))
                self.assertEqual([[screen.text(row).strip() for row in rows[2:]]
                                  for screen, rows in ((before, lit), (grid, moved))],
                                 [list(said)] * 2)
                self.assertEqual([grid.backs(row) for row in moved], [{}] * len(lit))

    def test_lines_of_a_row_past_its_page_the_card_brings_up_are_lit_on_none(self):
        # what fix-api-1 opened runs past its page, Down on to its next lines: the card under
        # its last brings those up, lit lower on that page, to where others of it were lit
        said = " ".join(f"Part-{n:02}" for n in range(50))
        with patch.object(terminal, "width", return_value=30), \
                patch.object(terminal, "height", return_value=18), \
                patch.object(menu, "past_said", lambda seat: (said, "")):
            shown = self.past(*[None] * 6, first=[Key("down")])
        up, _ = self.asks(shown, "Remove")
        before, grid = shown[up - 1][1], shown[up][1]
        over = [row for row in sorted(grid.rows) if "Part-" in grid.text(row)]
        was = [before.find(grid.text(row).strip())[0] for row in over]
        self.assertTrue(over and all(old > new for old, new in zip(was, over)), (was, over))
        self.assertTrue(all(SELECTION in before.backs(row).values() for row in was + over),
                        [before.text(row) for row in before.rows])

    def test_the_pointer_moved_onto_an_answer_leaves_the_fade_as_it_goes(self):
        for case, (run, answer) in {"past sessions": (self.past, "Remove"),
                                    "the ak screen": (self.ak, "Stop"),
                                    "config": (self.apply, menu.APPLY_ANSWER)}.items():
            with self.subTest(case):
                (row,) = next(grid for _, grid, _ in run() if grid.find("✓ Keep")).find(
                    f"× {answer}")
                shown = run(None, Key("point", row=row, col=3), *[None] * 5)
                up, read = self.asks(shown, answer, True)       # fading as the move is read
                moved = shown[read + 1:read + 6]    # drawn again at once, then frame by frame
                self.assertEqual(moved[0][0], shown[read][0])
                for when, grid, _ in moved:
                    self.assertEqual(grid.marks(), [(row, 1)])
                    left = self.left(shown, up, when)
                    self.assertEqual({at: grid.backs(at) for at in left}, left)
                self.assertEqual([any(self.left(shown, up, when).values())      # to its end
                                  for when, _, _ in (moved[0], moved[-1])], [True, False])

    def test_a_meter_the_keys_were_on_fades_under_configs_card(self):
        # ↑ past the first model, and the frames its meter's highlight takes to come
        shown = self.apply(*[None] * 6, first=[Key("up"), *[None] * 6])
        up, _ = self.asks(shown, menu.APPLY_ANSWER, True)
        self.assertEqual(shown[up - 1][1].marks(), [])      # a cell over the page, no row's

    def test_the_pointer_on_a_mark_under_configs_card_lights_nothing(self):
        # a mark is a cell the pointer lights on `c` (terminal.lit): the next model's, under the
        # one the keys were on, once that one has faded
        before = next(grid for _, grid, key in self.apply() if key == Key("char", "a"))
        ((row, cells),) = [(row, before.backs(row)) for row in before.rows if before.backs(row)]
        self.assertIn(before.text(row + 1)[min(cells) - 1:max(cells)].strip(), ("○", "●"))
        shown = self.apply(*[None] * 5, Key("point", row=row + 1, col=min(cells)), *[None] * 6)
        _, read = self.asks(shown, menu.APPLY_ANSWER, True)
        asked = [grid for _, grid, _ in shown[read + 1:] if grid.find("✓ Keep")]
        self.assertGreater(len(asked), 6)
        lit = [[at for at in grid.rows if grid.backs(at) and at not in grid.find("✓ Keep")]
               for grid in asked]
        self.assertEqual(lit, [[]] * len(asked))

    def test_what_a_past_row_opened_stays_open_unlit_over_its_card(self):
        with patch.object(menu, "past_said", lambda seat: ("Shipped the login page.", "")):
            shown = self.past(*[None] * 6)
        up, _ = self.asks(shown, "Remove", True)
        before, grid = shown[up - 1][1], shown[up][1]
        (opened,) = before.find("Shipped the login page.")
        self.assertEqual(set(before.backs(opened).values()), {SELECTION})
        # where it was, so the card under it and its answers are where they were
        self.assertEqual(grid.find("Shipped the login page."), [opened])
        self.assertEqual(grid.text(opened).rstrip(), before.text(opened).rstrip())  # its band fades
        self.assertGreater(grid.find("✓ Keep")[0], opened)

    def test_under_no_color_the_one_mark_is_keeps(self):
        with patch.dict(os.environ, {"NO_COLOR": "1"}):
            shown = self.past()
        grid = next(grid for _, grid, _ in shown if grid.find("✓ Keep"))
        self.assertEqual([grid.text(row) for row, _ in grid.marks()], ["› ✓ Keep"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
