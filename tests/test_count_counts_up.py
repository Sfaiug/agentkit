"""A seat's count counts up with its line: from 0 as the line grows in when ak opens, and on to
a task ticked as the line glides there, saying at every frame what the line shows.  A count
whose total changed is written at once.  The owner's pick of 18 Oct 2026 (motion, count).
Offline: a temporary HOME, fake seats, the motion clock read at chosen times, no terminal.
"""

from contextlib import redirect_stdout
import io
import os
from pathlib import Path
import re
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.sandbox import Sandbox  # noqa: E402
from agentkit import config, menu, motion, terminal  # noqa: E402


def plan(done, total):
    return "- [x] a\n" * done + "- [ ] b\n" * (total - done)


class Counts(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}))
        self.stack.enter_context(patch.object(terminal, "colour_depth", return_value=24))
        self.stack.enter_context(patch.object(terminal, "_POINTER", None))
        self.stack.enter_context(patch.object(menu, "seat_row_state", side_effect=lambda cfg, s, **_kw:
                                              {"word": "needs you", "reason": "", "since": None}))
        self.seats = [{"name": name, "repo": "", "path": "", "created": 9000}
                      for name in ("acme-api", "acme-docs")]
        for name, (done, total) in (("acme-api", (17, 28)), ("acme-docs", (3, 4))):
            config.save_session(self.cfg, name, "opus", ["astra"])
            self.plan(name, done, total)
        self.clock = motion.Clock()

    def plan(self, name, done, total):
        config.plan_path(name).write_text(plan(done, total))

    def draw(self, now):
        with patch.object(terminal, "width", return_value=100), \
                patch.object(terminal, "height", return_value=30), \
                patch.object(motion.time, "monotonic", return_value=now), \
                redirect_stdout(io.StringIO()) as out:
            menu.draw(self.cfg, self.seats, menu.KEYS, 0, "acme-api", {}, look=False,
                      records=[], clock=self.clock)
        return [line.replace("\033[K", "") for line in
                out.getvalue().split("\033[J")[0].split("\n")]

    def shown(self, lines, name, now):
        """The seat's line and count as the clock shows them at `now`: (filled, cells, done,
        total), and the count's cells."""
        row = next(n for n, line in enumerate(lines, 1) if f" {name} " in line)
        text = terminal.ANSI.sub("", lines[row - 1])
        line = re.search(r"[━╸─]+ \d+ of \d+", text)
        first = terminal.cells(text[:line.start()]) + 1
        columns = range(first, first + len(line.group()))
        drawn = terminal.cell_texts(lines[row - 1])
        written = "".join(terminal.ANSI.sub("", self.clock.cells[row, column][0](now)
                                            if (row, column) in self.clock.cells
                                            else drawn[column - 1]) for column in columns)
        track, count = written.split(" ", 1)
        done, total = map(int, count.split(" of "))
        filled = track.count("━") + track.count("╸") / 2
        return (filled, len(track), done, total), [(row, column) for column in columns
                                                   if column > first + len(track)]

    def assert_counts(self, lines, name, began, took, before, after):
        counts = []
        for n in range(int(took / motion.FRAME) + 2):
            now = began + n * motion.FRAME + 0.000001
            (filled, size, done, total), _ = self.shown(lines, name, now)
            counts.append(done)
            self.assertEqual(total, after[1])
            # the share the line shows, to the nearest task, give or take the line's rounding:
            # a cell either way, and the half cell at its end
            self.assertLessEqual(abs(filled * total / size - done), 0.5 + 1.5 * total / size,
                                 (name, n, filled, done))
        self.assertEqual((counts[0], counts[-1]), (before, after[0]))
        self.assertEqual(counts, sorted(counts))
        self.assertGreater(len(set(counts)), 2, counts)

    def test_as_ak_opens_each_count_counts_up_from_0_with_its_line_row_after_row(self):
        lines = self.draw(10)
        self.assert_counts(lines, "acme-api", 10, motion.GROW, 0, (17, 28))
        self.assert_counts(lines, "acme-docs", 10 + motion.STAGGER, motion.GROW, 0, (3, 4))

    def test_a_task_ticked_counts_on_with_its_glide_and_a_new_total_is_written_at_once(self):
        self.clock.grows = {}                       # opened long ago: nothing grows in
        self.draw(20)
        self.plan("acme-api", 22, 28)
        lines = self.draw(30)
        self.assert_counts(lines, "acme-api", 30, motion.GLIDE, 17, (22, 28))
        self.plan("acme-api", 22, 30)
        lines = self.draw(40)
        _, count = self.shown(lines, "acme-api", 40)
        self.assertEqual({cell for cell in count if (self.clock.cells.get(cell) or (0, 0))[1]
                          and self.clock.cells[cell][1] > 40}, set())

    def test_news_as_ak_opens_writes_a_new_total_or_fewer_done_at_once(self):
        for after in ((17, 30), (3, 28)):
            self.clock = motion.Clock()
            self.plan("acme-api", 17, 28)
            self.draw(10)
            self.plan("acme-api", *after)
            lines = self.draw(10.1)
            self.assertEqual(self.shown(lines, "acme-api", 10.1)[0][2:], after)

    def test_a_line_swept_done_shows_its_count_done(self):
        self.clock.grows = {}
        self.plan("acme-api", 27, 28)
        self.draw(20)
        self.plan("acme-api", 28, 28)
        with patch.object(menu, "seat_row_state", return_value={"word": "done", "reason": "",
                                                                 "since": None}):
            lines = self.draw(30)
        for now in (30, 30 + motion.GLIDE / 2):
            filled, size, done, total = self.shown(lines, "acme-api", now)[0]
            self.assertEqual((filled, done), (size, total))


if __name__ == "__main__":
    unittest.main()
