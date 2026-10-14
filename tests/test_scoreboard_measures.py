"""What the scoreboard measures is pinned here, so the board changes only with the owner's yes
and a visible test change (AGENTS.md, Owner rules, 14 Oct 2026): the rows and the parts each
cell is built from (`scoreboard.MEASURES`), the keys `compute` answers with, and the labels
`render` shows, in that order.

Offline: an empty sandbox HOME with no history database, and git answering nothing.
"""

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, scoreboard, terminal

NOW = 1_800_000_000

# The owner's yes: these rows and parts, nothing else.  A measure added, dropped or renamed
# changes this tuple in the same change, under the owner line that allows it.
PINNED = (
    ("products", "products", ("runs", "merged", "first_round", "unmerged", "hours", "tokens")),
    ("ak", "ak", ("runs", "merged", "first_round", "unmerged", "hours", "tokens", "token_share")),
    ("waits", "waits", ("compute", "merge_hours", "lander_hours")),
    ("merged", "merged", ("model", "ak", "waiting", "seat")),
    ("escaped", "escaped", ("merged", "escaped", "open", "unknown", "reviewers")),
    ("size", "ak size", ("code_lines", "readme_words")),
)


class Measures(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-measures-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        for name, value in (("HOME", root / ".agentkit"), ("RUNS", root / ".agentkit" / "runs"),
                            ("REPO", root / "toolkit")):
            patcher = patch.object(config, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        env = patch.dict(os.environ, {"HOME": str(root), "NO_COLOR": "1"})
        env.start()
        self.addCleanup(env.stop)
        for target, kwargs in ((scoreboard, {"_git": lambda *args, **kw: None}),
                               (scoreboard.time, {"time": lambda: NOW})):
            for name, value in kwargs.items():
                patcher = patch.object(target, name, value)
                patcher.start()
                self.addCleanup(patcher.stop)

    def test_the_measures_are_the_pinned_ones(self):
        self.assertEqual(scoreboard.MEASURES, PINNED)

    def test_compute_answers_with_exactly_the_pinned_rows(self):
        board = scoreboard.compute(NOW)
        self.assertEqual(list(board), [key for key, _, _ in PINNED])
        # two weeks a row, and a new install has no runs, no merges and no size to show
        self.assertEqual(board, {key: [None, None] for key, _, _ in PINNED})

    def test_render_shows_each_pinned_row_under_its_label(self):
        empty = {key: [None, None] for key, _, _ in PINNED}
        with patch.object(scoreboard, "compute", return_value=empty), \
                patch.object(terminal, "content_width", return_value=100):
            lines = scoreboard.render()
        # the title, the two weeks' heading, then one line a row: an empty row says so in one
        self.assertEqual([line[:8].strip() for line in lines[2:]], [label for _, label, _ in PINNED])


if __name__ == "__main__":
    unittest.main()
