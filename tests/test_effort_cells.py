"""A model's effort on `c` reads as a cell a level before its word, and its highest shimmers.

Before each effort word stands a cell for every level that model offers, full up to its effort
and the rest open and dim (`▰▰▰▱▱` for high of five, the owner's pick of 18 Oct 2026), the
words in one column; a model with one effort is its word alone.  A step lights each cell it
fills and dims each it empties, in turn from the level before it, on the menu's animation clock,
and a step onto the model's highest level sends one light through the word, once.  Without
UTF-8 a full cell is `#` and an open one `-`, and under NO_COLOR nothing moves.

Each screen is `menu.show_config` in a child on a pty of its own, through
tests/test_config_matrix.py's Screen: a temporary HOME whose config is the shipped default plus
a Haiku, the catalog faked (Haiku takes only `none`, Opus low to max), the seat `fix-api`.  The
cells a frame writes are read back from where it places the cursor.  Nothing here reads or
writes the owner's ~/.agentkit, and the only process signalled is the test's own child.
"""

import os
from pathlib import Path
import re
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch

from test_config_matrix import DOWN, ENTER, FULL, RIGHT, UP, Screen, on_effort, row
from agentkit import config, menu, motion, terminal

PLACE = re.compile(r"\x1b\[(\d+);(\d+)H")      # where a frame writes a cell
CELL = re.compile(r"(\x1b\[[0-9;]*m)?([▰▱])")
LIT = "38;"     # a colour of its own: a dim cell's, or the light's on a letter


def drawn(screen):
    """The last whole screen's lines as written, colours and all."""
    part = [part for part in screen.text().split("\x1b[H") if "\x1b[J" in part][-1]
    return part.split("\x1b[J")[0].split("\n")


def filled(screen, name):
    """How many of `name`'s orchestrator's cells, the first on its row, are drawn full in the
    foreground, with no colour of their own: its row is the one its full name opens."""
    line = next(line for line in drawn(screen)
                if terminal.ANSI.sub("", line)[2:].split("  ")[0] == FULL[name])
    first = []
    for match in CELL.finditer(line):
        if first and terminal.ANSI.sub("", line[first[-1].end():match.start()]):
            break                                 # past them: the word, then another role's
        first.append(match)
    return sum(1 for match in first if match[2] == "▰" and LIT not in ink(line, match.start(2)))


def ink(line, at):
    """The colours in force at `at` on a line as written: every code since the last reset."""
    codes = re.findall(r"\x1b\[[0-9;]*m", line[:at])
    resets = [n for n, code in enumerate(codes) if code[2:3] in ("0", "m")]
    return "".join(codes[resets[-1] if resets else 0:])


def beside(lines, name):
    """What stands beside `name`'s orchestrator mark: its effort's cells, if any, and word."""
    words = row(lines, name)[1].split()
    at = next(n for n, word in enumerate(words) if word in ("●", "○"))
    return words[at + 1:at + 3] if words[at + 1][0] in "▰▱" else words[at + 1:at + 2]


def shone(written):
    """Which letters of a word as written are in the light: those a colour of their own precedes."""
    return [n for n, codes in enumerate(re.findall(r"((?:\x1b\[[0-9;]*m)*)[^\x1b]", written))
            if LIT in codes]


def moved(screen, keys):
    """Keys, then every cell the frames after them wrote until the screen is still:
    [(row, column, what it shows, as written)]."""
    mark = len(screen.text())
    screen.press(keys)
    began, size, quiet = time.monotonic(), len(screen.text()), time.monotonic()
    while time.monotonic() - began < 1.0 or time.monotonic() - quiet < 0.3:
        time.sleep(0.02)
        if len(screen.text()) != size:
            size, quiet = len(screen.text()), time.monotonic()
    parts, cells = PLACE.split(screen.text()[mark:]), []
    for at, column, text in zip(parts[1::3], parts[2::3], parts[3::3]):
        text = text.split("\x1b[H")[0]            # a whole draw after it is no frame's
        cells.append((int(at), int(column), terminal.ANSI.sub("", text), text))
    return cells


def places(lines, name):
    """`name`'s row on the terminal, the column of its orchestrator's effort word and of its
    first cell."""
    number, line = row(lines, name)
    first = line.index(next(c for c in line if c in "▰▱"))
    after = first + len(line[first:].split()[0])
    return number, after + len(line[after:]) - len(line[after:].lstrip()) + 1, first + 1


class EffortCells(unittest.TestCase):
    def test_each_model_has_a_cell_a_level_full_to_its_effort_and_its_word_after(self):
        screen = Screen(self)
        lines = screen.frame()
        # Claude's five, Codex's and Muse's six, Grok's four, Gemini Flash's three and MiMo's
        # two, each full to its effort in the shipped default
        for name, effort, cells in (
                ("fable", "xhigh", "▰▰▰▰▱"), ("opus", "xhigh", "▰▰▰▰▱"),
                ("astra", "xhigh", "▰▰▰▰▱▱"), ("spark", "xhigh", "▰▰▰▰▰▱"),
                ("grok", "xhigh", "▰▰▰▰"), ("gemini", "high", "▰▰▰"), ("mimo", "high", "▰▰")):
            with self.subTest(name=name):
                self.assertEqual(beside(lines, name), [cells, effort])
                # beside an open mark the cells are dim, the full ones too: only the
                # orchestrator's are in the foreground
                self.assertEqual(filled(screen, name), cells.count("▰") if name == "opus" else 0)
        # every word in one column, after the most cells any model has
        self.assertEqual(len({places(lines, name)[1] for name in ("fable", "astra", "mimo")}), 1)
        screen.leave()

    def test_a_model_with_one_effort_is_its_word_alone(self):
        screen = Screen(self)
        lines = screen.frame()
        self.assertEqual(row(lines, "haiku")[1].split(), [*FULL["haiku"].split(),
                                                          *["○", "xhigh"], *["□", "xhigh"] * 2])
        # its word still in the column the others' stand in
        self.assertEqual(row(lines, "haiku")[1].rindex(" "), row(lines, "fable")[1].rindex(" "))
        screen.press(DOWN * 2 + RIGHT, lambda lines: on_effort(lines, "haiku"))
        cells = moved(screen, ENTER)                    # onto none, its only effort
        lines = screen.frame()
        self.assertEqual(row(lines, "haiku")[1].split(),
                         ["›", *FULL["haiku"].split(), *["○", "none"], *["□", "xhigh"] * 2])
        self.assertEqual([cell for cell in cells if cell[0] == row(lines, "haiku")[0]], [])
        self.assertEqual(screen.record()["efforts"]["haiku"]["effort"], "none")
        screen.leave()

    def test_a_step_moves_the_cells_it_changes_in_turn_and_the_highest_shimmers_once(self):
        screen = Screen(self)
        lines = screen.press(DOWN + RIGHT, lambda lines: on_effort(lines, "opus"))
        number, word, first = places(lines, "opus")
        # a click on its second cell, down from xhigh: its fourth cell, then its third, stay
        # full but dim and then stand open and dim
        cells = moved(screen, f"\x1b[<0;{first + 1};{number}M\x1b[<0;{first + 1};{number}m"
                      .encode())
        self.assertEqual(screen.record()["efforts"]["opus"]["effort"], "medium")
        self.assertEqual({(at, column) for at, column, _, _ in cells},
                         {(number, first + 3), (number, first + 2)})
        self.assertEqual([column for _, column, text, _ in cells if text == "▱"],
                         [first + 3, first + 2], "in turn from the level before it")
        self.assertEqual({column for _, column, text, written in cells
                          if text == "▰" and LIT in written}, {first + 3, first + 2},
                         "each full but dim first")
        self.assertTrue(all(LIT in written for _, _, text, written in cells if text == "▱"))
        self.assertEqual(filled(screen, "opus"), 2)
        # up again: its third lights and settles into the foreground
        cells = moved(screen, ENTER)
        self.assertEqual({(at, column) for at, column, _, _ in cells}, {(number, first + 2)})
        self.assertEqual({text for _, _, text, _ in cells}, {"▰"})
        self.assertIn(LIT, cells[0][3])
        self.assertNotIn(LIT, cells[-1][3])
        # up onto max, Opus's highest, from the word: its last two fill, and one light crosses
        # the word, written whole from its first cell
        moved(screen, ENTER)
        cells = moved(screen, f"\x1b[<0;{word};{number}M\x1b[<0;{word};{number}m".encode())
        self.assertEqual(screen.record()["efforts"]["opus"]["effort"], "max")
        self.assertEqual({column for at, column, _, _ in cells if at == number},
                         {first + 4, word})
        words = [cell for cell in cells if cell[1] == word]
        self.assertEqual({text for _, _, text, _ in words}, {"max"})
        self.assertEqual([n for *_, written in words for n in shone(written)], [0, 1, 2],
                         "each letter lit once, left to right")
        self.assertEqual(shone(words[-1][3]), [])
        # and once: drawn again, moving off it and back, it is still
        for keys in (DOWN, UP):
            cells = moved(screen, keys)
            self.assertEqual([cell for cell in cells if cell[0] == number], [])
        screen.leave()

    def test_without_utf8_a_full_cell_is_a_hash_and_an_open_one_a_dash(self):
        screen = Screen(self, env={"LANG": "C", "LC_ALL": ""})
        lines = screen.frame()
        self.assertEqual(row(lines, "opus")[1].split()[-2:], ["####-", "xhigh"])
        self.assertEqual(row(lines, "gemini")[1].split()[-2:], ["###", "high"])
        self.assertEqual(row(lines, "haiku")[1].split()[-1], "xhigh")
        self.assertNotIn("#", row(lines, "haiku")[1])
        screen.leave()

    def test_under_no_color_nothing_moves(self):
        screen = Screen(self, env={"NO_COLOR": "1"})
        lines = screen.frame()
        self.assertEqual(row(lines, "opus")[1].split()[-2:], ["▰▰▰▰▱", "xhigh"])
        # with no colour to reverse, the effort is the highlighted row's cell with no mark bracketed
        screen.press(DOWN + RIGHT, lambda lines: row(lines, "opus")[1].startswith("›")
                     and "[" not in row(lines, "opus")[1])
        self.assertEqual(moved(screen, ENTER), [])
        self.assertEqual(beside(screen.frame(), "opus"), ["▰▰▰▰▰", "max"])
        screen.leave()

    def test_a_cell_takes_about_150_ms_and_the_light_about_600(self):
        with patch.object(terminal, "colour_depth", return_value=256), \
                patch.object(terminal, "utf8", return_value=True):
            fill, until = motion.filling(True, 10.0)
            self.assertEqual(until, 10.15)
            self.assertEqual(fill(9.9), terminal.styled("▱", "dim"))      # its turn to come
            self.assertIn(LIT, fill(10.0))
            self.assertEqual(terminal.ANSI.sub("", fill(10.0)), "▰")
            self.assertEqual(fill(10.15), "▰")
            empty, _ = motion.filling(False, 10.0)
            self.assertEqual(empty(10.0), terminal.styled("▰", "dim"))
            self.assertEqual(empty(10.15), terminal.styled("▱", "dim"))
            shimmer, until = motion.shimmering("max", 10.0)
            self.assertEqual(until, 10.6)
            for t, lit in ((0.1, [0]), (0.3, [1]), (0.5, [2]), (0.65, [])):
                self.assertEqual(shone(shimmer(10.0 + t)), lit)

    def test_the_cells_count_the_catalog_last_listed_whoever_asked(self):
        # a harness of the test's own, whose listing says its one model runs at no effort
        adapters = Path(tempfile.mkdtemp(prefix="effort-cells-"))
        self.addCleanup(shutil.rmtree, adapters)
        (adapters / "acme.sh").write_text("#!/usr/bin/env bash\n"
                                          "printf 'acme-fast\\tAcme Fast\\tnone\\n'\n")
        (adapters / "acme.sh").chmod(0o755)
        (adapters / "acme.toml").write_text('[effort]\nlevels = ["low", "medium", "high"]\n')
        entry = {"harness": "acme", "model": "acme-fast"}
        with patch.dict(os.environ, {config.ADAPTER_DIR_ENV: str(adapters)}):
            self.assertEqual(menu.effort_levels(entry), ["low", "medium", "high"])  # unlisted
            config.catalog("acme")                      # as `add a model` asks it
            self.assertEqual(menu.effort_levels(entry), ["none"])

    def test_a_wide_word_shimmers_whole_from_its_first_cell(self):
        with patch.object(terminal, "colour_depth", return_value=256):
            clock = motion.Clock()
            start = menu._effort_moves(["low", "最高"], "最高", None, False, 20, None)
            start(clock, 5, time.monotonic(), "low")
            frame = clock.frame()
        self.assertEqual(PLACE.findall(frame), [("5", "20")])     # its two cells written as one
        self.assertEqual(terminal.ANSI.sub("", frame), "最高")


if __name__ == "__main__":
    unittest.main()
