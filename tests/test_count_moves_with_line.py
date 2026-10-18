"""A seat's count moves with its line: from 0 as the line grows in when ak opens, and on to a
task ticked as the line glides there, saying at every frame what the line shows; whatever else
moves the line -- a new total, fewer done, the light crossing a seat turned done -- has the
count as drawn, so it never runs backward.  The owner's pick of 18 Oct 2026 (motion, count).
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


class CountMoves(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}))
        self.stack.enter_context(patch.object(terminal, "colour_depth", return_value=24))
        self.stack.enter_context(patch.object(terminal, "_POINTER", None))
        self.word = "needs you"
        self.stack.enter_context(patch.object(menu, "seat_row_state", side_effect=lambda *_a, **_kw:
                                              {"word": self.word, "reason": "", "since": None}))
        self.seats = [{"name": "acme-api", "repo": "", "path": "", "created": 9000}]
        config.save_session(self.cfg, "acme-api", "opus", ["astra"])
        self.plan(17, 28)
        self.clock = motion.Clock()

    def plan(self, done, total):
        config.plan_path("acme-api").write_text("- [x] a\n" * done + "- [ ] b\n" * (total - done))

    def frames(self, now, took=motion.GLIDE):
        """A draw at `now`, then its line and count as the clock shows them a frame apart till
        `took` has passed: (share of the line filled, done, total) each."""
        with patch.object(terminal, "width", return_value=100), \
                patch.object(terminal, "height", return_value=30), \
                patch.object(motion.time, "monotonic", return_value=now), \
                redirect_stdout(io.StringIO()) as out:
            menu.draw(self.cfg, self.seats, menu.KEYS, 0, "acme-api", {}, look=False,
                      records=[], clock=self.clock)
        row, drawn = next((n, line) for n, line in enumerate(
            out.getvalue().split("\033[J")[0].replace("\033[K", "").split("\n"), 1)
            if " acme-api " in line)
        shown = []
        for at in (now + n * motion.FRAME + 1e-6 for n in range(int(took / motion.FRAME) + 2)):
            column, text = 1, ""
            for cell in terminal.cell_texts(drawn):
                animation = self.clock.cells.get((row, column))
                text += terminal.ANSI.sub("", animation[0](at) if animation else cell)
                column += terminal.cells(cell)
            track, done, total = re.search(r"([━╸─]+) +(\d+) of (\d+)", text).groups()
            shown.append(((track.count("━") + track.count("╸") / 2) / len(track),
                          int(done), int(total)))
        return shown

    def assert_counts_with_line(self, frames, start, end):
        counts = [done for _, done, _ in frames]
        self.assertEqual((counts[0], counts[-1]), (start, end))
        self.assertEqual(counts, sorted(counts))
        self.assertGreater(len(set(counts)), 2, counts)
        for share, done, total in frames:      # to a task, give or take a cell and a half
            self.assertLessEqual(abs(share * total - done), 0.5 + 1.5 * total / 60, frames)

    def test_as_ak_opens_the_count_counts_up_from_0_with_its_line(self):
        self.assert_counts_with_line(self.frames(10, motion.GROW), 0, 17)

    def test_a_task_ticked_counts_on_with_its_glide_and_any_other_move_draws_it_as_it_is(self):
        self.frames(10)
        self.plan(17, 30)                     # a new total as ak opens: written at once
        self.assertEqual({frame[1:] for frame in self.frames(10.1)}, {(17, 30)})
        self.plan(22, 30)
        self.assert_counts_with_line(self.frames(20), 17, 22)
        self.plan(20, 30)                     # fewer done
        self.assertEqual({frame[1:] for frame in self.frames(30)}, {(20, 30)})
        self.plan(30, 30)                     # the last ticked, the seat turned done
        self.word = "done"
        for now in (40, 40 + motion.SWEEP / 2, 40 + motion.SWEEP + motion.FRAME):
            self.assertEqual({frame[1:] for frame in self.frames(now)}, {(30, 30)})


if __name__ == "__main__":
    unittest.main()
