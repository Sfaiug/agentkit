"""A seat's progress is a smooth line of how much of its plan is done, and its count.

The done share is `━` in the word's colour, a half cell `╸` where it ends inside one, then a dim
`─` for the rest and `done of total`; on a terminal and on a seat's bar alike the line fades in
from half way to the background at its start to the colour at its tip.  It says nothing of the tasks in flight, which
the line under a highlighted row has, and no screen says when the work will finish.  The rows
draw it in the room they have, never wrapped or cut, and without colour or UTF-8 it reads in
plain characters.  Offline: a throwaway HOME, fake plans and run records, the real renderer.
"""

from contextlib import redirect_stdout
import io
import os
import re
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import config, history, menu, terminal
from agentkit import record

NOW = 1_800_000_000
WORKING, AMBER, DIM = (terminal.STATE_STYLES["working"][2], terminal.STATE_STYLES["needs you"][2],
                       terminal.STATE_STYLES["dim"][2])


def cells(bar):
    """A tmux-drawn line, a cell at a time: (glyph, ink), and what follows it."""
    found = []
    for ink, text in re.findall(r"#\[fg=#(\w+)\]([^#]*)", bar):
        found += [(char, ink) for char in text]
    return found, bar.rpartition("#[default]")[2]


class PlanBar(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}))
        self.stack.enter_context(patch.object(menu.time, "time", return_value=NOW))
        (config.CODE / "acme" / ".git").mkdir(parents=True)
        self.repo = str(config.CODE / "acme")

    def test_the_done_share_is_a_line_in_the_words_colour_then_its_count(self):
        drawn, after = cells(menu.last_column("working", 3, 8, 30, tmux=True))
        self.assertEqual(after, " 3 of 8")
        self.assertEqual(len(drawn), 30 - len(" 3 of 8"))
        # 23 cells, three eighths of them done: eight and a half
        self.assertEqual("".join(char for char, _ in drawn), "━" * 8 + "╸" + "─" * 14)
        self.assertEqual({ink for char, ink in drawn if char == "─"}, {DIM})

    def test_a_seat_s_bar_draws_the_line_its_row_draws(self):
        # cell for cell the row's inks on a dark terminal, fading in to the word's own colour at
        # the tip, whichever process writes the bar
        for word, colour in (("working", WORKING), ("needs you", AMBER)):
            with patch.object(terminal, "colour_depth", return_value=24):
                row = terminal.plan_bar(3, 8, 30, 8, word)
            screen = ["".join(f"{int(part):02x}" for part in ink.split(";"))
                      for ink in re.findall(r"38;2;([\d;]+)m[━╸]", row)]
            self.assertEqual(screen[-1], colour)
            self.assertNotEqual(screen[0], colour)
            for light in (False, True):
                with self.subTest(word=word, light=light), \
                        patch.object(terminal, "_LIGHT", light):
                    bar, _ = cells(terminal.plan_bar(3, 8, 30, 8, word, tmux=True))
                    self.assertEqual([ink for char, ink in bar if char in "━╸"], screen)

    def test_on_a_terminal_the_line_fades_in_toward_its_tip(self):
        with patch.object(terminal, "colour_depth", return_value=24):
            line = terminal.plan_bar(4, 8, 28, 8, "working")
        inks = re.findall(r"38;2;([\d;]+)m[━╸]", line)
        tip = ";".join(str(int(WORKING[at:at + 2], 16)) for at in (0, 2, 4))
        self.assertEqual(inks[-1], tip)
        self.assertNotEqual(inks[0], tip)
        self.assertTrue(terminal.plain(line).endswith(" 4 of 8"))

    def test_eight_colours_draw_the_whole_line_in_the_words_own_tone(self):
        # they hold no tone between the word's and the background, so nothing fades
        for light in (False, True):
            with self.subTest(light=light), patch.object(terminal, "_LIGHT", light), \
                    patch.object(terminal, "colour_depth", return_value=8):
                line = terminal.plan_bar(4, 8, 28, 8, "working")
            self.assertEqual(set(re.findall(r"\x1b\[(\d+)m[━╸]", line)),
                             {terminal.STATE_STYLES["working"][3]})
            self.assertTrue(terminal.plain(line).endswith(" 4 of 8"))

    def test_without_colour_or_utf8_it_reads_in_plain_characters(self):
        self.assertEqual(menu.last_column("working", 3, 7, 20), "━━━━━╸─────── 3 of 7")
        with patch.dict(os.environ, {"LANG": "C", "LC_ALL": ""}):
            self.assertEqual(menu.last_column("working", 3, 7, 20), "======------- 3 of 7")
        # a phone's line is all the room there is: the line takes that and never more
        self.assertEqual(menu.last_column("working", 3, 7, 10, narrow=True), "━╸─ 3 of 7")
        self.assertEqual(menu.last_column("working", 3, 7, 6, narrow=True), "3 of 7")
        self.assertEqual(menu.last_column("working", 3, 7, 6), "━━━╸──── 3 of 7")
        self.assertEqual(menu.last_column("working", 0, 0), "──────── no plan yet")

    def going(self, run_id, owner, ran=0, **extra):
        """A run that seat launched, its first `ran` rounds' directories made as the loop makes
        them when each round's executor starts."""
        directory = config.RUNS / run_id
        directory.mkdir(parents=True)
        for rnd in range(1, ran + 1):
            (directory / f"round-{rnd}").mkdir()
        record.save_state(directory, {
            "run_id": run_id, "title": run_id, "state": "running", "launched_session": owner,
            "repo": self.repo, "executor": "opus", "reviewer": "astra", "rounds": 3,
            "round_summaries": [], "started_at": NOW - 900, **extra})

    def draw(self, width):
        with patch.object(terminal, "width", return_value=width), \
                patch.object(menu, "seat_row_state",
                             return_value={"word": "working", "reason": "", "since": None}), \
                redirect_stdout(io.StringIO()) as out:
            menu.draw(self.cfg, [{"name": "acme-ci", "repo": self.repo, "path": self.repo,
                                  "created": NOW}])
        return out.getvalue().splitlines()

    def test_rows_draw_it_in_the_room_they_have_and_no_estimate(self):
        config.save_session(self.cfg, "acme-ci", "fable", ["opus"],
                            {"repo": self.repo, "cwd": self.repo})
        (config.STATE / "plan-acme-ci.md").write_text("- [x] a\n- [x] b\n- [ ] c\n- [ ] d\n")
        self.going("20261002-1500-fix-ci", "acme-ci", task_file="/t/gh2-fix-ci.md",
                   step="reviewer", step_at=NOW - 60)
        row = next(line for line in self.draw(100) if "acme-ci" in line)
        self.assertRegex(row, r"● working  [━╸]+─+ 2 of 4$")
        self.assertEqual(terminal.cells(row), 100)      # the whole room, to the content's edge
        # under 60 columns the bar goes on its own line, and still takes the room
        lines = self.draw(50)
        tail = lines[next(n for n, line in enumerate(lines) if "acme-ci" in line) + 1]
        self.assertRegex(tail, r"^    [━╸]+─+ 2 of 4$")
        self.assertEqual(terminal.cells(tail), 50)
        for line in self.draw(100) + lines:
            self.assertNotRegex(line, r"~\d+[mhd] left")
        # the room beside the row holds its line and its count, the line shorter as the room
        # is: never wrapped or cut, its colours kept, and never under the row on one screen
        # while beside it on another one as wide (the owner, 29 Oct 2026)
        info = {"number": "1", "name": "acme-progress-checks", "orchestrator": "gpt-astra",
                "count": "working", "word": "working", "sentence": "", "bar": (1, 6)}
        for width in (64, 63):
            with patch.object(terminal, "colour_depth", return_value=24):
                [line] = menu.v5o_seat_blocks([info], width)[0]
            self.assertEqual(terminal.cells(line), width)
            self.assertRegex(line, r"38;2;137;180;250m[━╸]")   # the tip, in working's colour
            self.assertTrue(terminal.plain(line).endswith(" 1 of 6"), line)
        self.assertFalse(hasattr(menu, "seat_estimate"))
        self.assertFalse(hasattr(history, "estimate_seconds"))

    def test_every_row_on_a_screen_draws_its_line_the_same_way(self):
        # the owner, 29 Oct 2026: short lines beside some rows and long ones under others were
        # one screen drawn two ways.  A phone draws every line under its row, a wider screen
        # every one beside it, a draft's mark and a count of any width alike
        rows = [{"number": str(n), "name": name, "orchestrator": "Opus 5.5", "count": "working",
                 "word": "working", "sentence": "", "bar": bar, "unsent": unsent}
                for n, (name, bar, unsent) in enumerate([
                    ("acme-review-flow", (113, 117), ""), ("acme-checkout", (12, 13), ""),
                    ("fix-api", (1, 1), ""), ("acme-web", None, ""),
                    ("acme-docs", (4, 8), "a draft")], 1)]
        for width in range(40, 121):
            with self.subTest(width=width):
                blocks = menu.v5o_seat_blocks(rows, width)
                self.assertEqual({len(block) for block in blocks}, {1 if width >= 60 else 2})
        # a draft's mark never takes its row's count's place: rows too long for the room beside
        # them all go under, theirs and every other row's
        rows += [dict(rows[3], unsent="a draft"), dict(rows[2], bar=(1, 6), unsent="a draft"),
                 dict(rows[0], word="out of usage", unsent="a draft", back=1800000000)]
        said = ["113 of 117", "12 of 13", "1 of 1", "no plan yet", "4 of 8", "no plan yet",
                "1 of 6", "back "]
        for width in range(40, 121):
            with self.subTest(width=width):
                blocks = menu.v5o_seat_blocks(rows, width)
                self.assertEqual(len({len(block) for block in blocks}), 1)
                for row, block, count in zip(rows, blocks, said):
                    drawn = " ".join(terminal.plain(line) for line in block)
                    self.assertIn(count, drawn)
                    self.assertEqual("unsent" in drawn, bool(row["unsent"]))

    def test_a_row_draws_its_last_column_in_the_cells_it_truly_has_left(self):
        # long name and model columns leave fewer than ten cells: neither the bar nor a sentence
        # runs past the edge, and each is there whole or cut with its `…`
        info = {"number": "1", "name": "acme-integration-checks", "orchestrator": "gpt-astra",
                "count": "working", "word": "working", "sentence": "", "bar": (1, 9), "runs": []}
        asks = dict(info, count="needs you", word="needs you", sentence="Merge #75 first?")
        for width in (60, 61, 62, 63, 70):
            for depth in (0, 8, 256, 24):
                with self.subTest(width=width, depth=depth), \
                        patch.object(terminal, "colour_depth", return_value=depth):
                    bar, ask = menu.v5o_seat_blocks([info, asks], width)
                    for line in bar + ask:
                        self.assertLessEqual(terminal.cells(line), width, line)
                    # under ten cells left, each goes under its row, with colour or without
                    free = menu.v5o_column_widths([info, asks], width)["free"]
                    self.assertEqual((len(bar), len(ask)), (2, 2) if free < 10 else (1, 1))
                    self.assertIn("1 of 9", terminal.plain("".join(bar)))
                    # a row asking draws its line too, and its question opens under it, never
                    # beside it
                    self.assertIn("1 of 9", terminal.plain("".join(ask)))
                    self.assertNotIn("Merge", terminal.plain(" ".join(ask)))

    def test_a_row_s_head_never_runs_past_the_screen(self):
        # the widest number, name, model and state at once: the name and the model share what
        # the number and the state leave; every head fits and states align beside or below it
        narrow = {"number": "1", "name": "acme", "orchestrator": "gpt-astra", "count": "working",
                  "word": "working", "sentence": "", "bar": (3, 7), "runs": []}
        wide = {"number": "1234", "name": "acme-integration-testing",
                "orchestrator": "acme-model-max", "count": "needs you", "word": "needs you",
                "sentence": "Merge first?", "bar": None, "runs": []}
        for width in range(6, 131):
            for depth in (0, 24):
                with self.subTest(width=width, depth=depth), \
                        patch.object(terminal, "colour_depth", return_value=depth):
                    rows = [menu.v5o_seat_blocks(infos, width) for infos in
                            ([narrow], [wide], [dict(wide, sentence="")], [narrow, wide])]
                    for line in (line for blocks in rows for block in blocks for line in block):
                        self.assertLessEqual(terminal.cells(line), min(width, 100), line)
                    if width >= 30 and not depth:
                        states = [next(line for line in block if label in line)
                                  for block, label in zip(rows[-1], ("● working", "! needs you"))]
                        self.assertEqual(states[0].index("● working"), states[1].index("! needs you"),
                                         states)

    def test_a_highlighted_head_keeps_its_number_at_any_width(self):
        # below the narrowest head the rest is cut, never the indent the highlight's `›` takes
        info = {"number": "1", "name": "acme", "orchestrator": "gpt-astra", "count": "working",
                "word": "working", "sentence": "", "runs": [], "repo": None}
        groups = ([{"name": "acme", "checkout": None, "seats": [info]}], [info], 0, {})
        for width in range(6, 41):
            for number in ("1", "1234"):
                for depth in (0, 24):
                    with self.subTest(width=width, number=number, depth=depth), \
                            patch.dict(info, number=number), \
                            patch.object(terminal, "width", return_value=width), \
                            patch.object(terminal, "height", return_value=100), \
                            patch.object(terminal, "colour_depth", return_value=depth), \
                            patch.object(menu, "usage_lines", return_value=[]), \
                            patch.object(menu, "usage_rows", return_value=[]), \
                            redirect_stdout(io.StringIO()) as output:
                        drawn = {}
                        menu.draw({}, [], groups=groups, drawn=drawn, cursor="acme")
                        lines = terminal.ANSI.sub("", output.getvalue()).splitlines()
                        row = next(row for row, spot in drawn["spots"].items()
                                   if spot[0] == "acme")
                        self.assertRegex(lines[row - 1], rf"^› +{number}(  |$)")
                        self.assertLessEqual(terminal.cells(lines[row - 1]), width)

    def test_a_phone_s_tasks_line_never_runs_past_the_screen(self):
        # the progress line keeps its room below a narrow row, even with a state line between
        for width, done, total in ((22, 127, 143), (24, 4999, 9999), (30, 3, 7), (40, 3, 7)):
            info = {"number": "1", "name": "acme", "orchestrator": "sol", "count": "working",
                    "word": "working", "sentence": "", "bar": (done, total), "solo": True}
            for depth in (0, 8, 256, 24):
                with self.subTest(width=width, depth=depth), \
                        patch.object(terminal, "colour_depth", return_value=depth):
                    block = menu.v5o_seat_blocks([info], width)[0]
                    for line in block:
                        self.assertLessEqual(terminal.cells(line), width, line)
                    self.assertIn(f"{done} of {total}", terminal.plain(block[-1]))

    def test_a_seat_waiting_to_land_wraps_or_cuts_its_sentence_as_any_row_does(self):
        info = {"number": "1", "name": "acme-ci", "orchestrator": "fable", "count": "working",
                "word": "working", "bar": (0, 6), "runs": [],
                "sentence": "waiting · 3rd in line to land on release/acme-api-integration"}
        for width in (40, 50, 60, 100):
            with self.subTest(width=width):
                for line in menu.v5o_seat_blocks([info], width)[0]:
                    self.assertLessEqual(terminal.cells(line), width, line)



if __name__ == "__main__":
    unittest.main(verbosity=2)
