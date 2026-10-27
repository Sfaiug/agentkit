"""What the scoreboard measures is pinned here, so the board changes only with a visible test
change (AGENTS.md, Owner rules, 14 Oct 2026): the rows and the parts each
cell is built from (`scoreboard.MEASURES`), the rows and parts `compute` answers with, and
the labels `render` shows, in that order; tests/test_scoreboard.py holds the words `render`
says of each part, tests/test_who_built.py those of `built` and `parks`,
tests/test_sunk_tokens.py those of `sunk`, tests/test_owner_row.py those of `owner`,
tests/test_intent_row.py those of `intent`.

Offline: an empty sandbox HOME with no history database, and git answering nothing; the
filled board reads literal history rows, parks, owner moments and dones, and git answering
one line to everything.
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

# These rows and parts, nothing else.  A measure added, dropped or renamed changes this tuple
# in the same change, under a line saying who decided it and when.
PINNED = (
    ("products", "products", ("runs", "merged", "first_round", "unmerged", "hours", "tokens")),
    ("ak", "ak", ("runs", "merged", "first_round", "unmerged", "hours", "tokens", "token_share")),
    # Every token, seats and their subagents beside runs: the owner's yes, 21 Oct 2026.
    ("tokens", "tokens", ("total_tokens", "seat_tokens", "not_counted")),
    # `intent`, `owner`, `built`, `parks` and `sunk`: the owner's yes, 14 Oct 2026.
    ("intent", "intent", ("measured", "hours", "live", "live_hours")),
    ("owner", "owner", ("asked", "paged", "hours")),
    ("built", "built", ("seat_merged", "seat_first_round", "worker_merged", "worker_first_round")),
    ("waits", "waits", ("compute", "merge_hours", "lander_hours")),
    ("merged", "merged", ("model", "ak", "waiting", "seat")),
    ("parks", "parks", ("parked",)),
    ("sunk", "sunk", ("share", "tokens")),
    # a review miss counts only when it breaks, at landing or after merge, never a rewrite
    # later: the owner's yes, 16 Oct 2026, in place of `escaped`
    ("broke", "broke", ("merged", "after_merge", "landing", "unknown")),
    # AGENTS.md words beside README words: the owner's yes, 15 Oct 2026, so its growth shows.
    ("size", "ak size", ("code_lines", "readme_words", "agents_words")),
)


class Measures(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-measures-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        for name, value in (("HOME", root / ".agentkit"), ("RUNS", root / ".agentkit" / "runs"),
                            ("REPO", root / "toolkit"), ("CODE", root / "code")):
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

    def test_every_filled_cell_answers_with_exactly_its_pinned_parts(self):
        # a merged run this week in a product and in ak, with its waits, and a question the
        # owner answered, and a done ending their intent: every row has a cell
        rows = [{"run_id": f"fix-{repo}", "repo": repo, "final_state": "pass", "rounds_used": 1,
                 "started_at": NOW - 3600, "finished_at": NOW - 60, "changed_lines": 1,
                 "executor_tokens": 1, "reviewer_tokens": 1, "total_seconds": 3540,
                 "slot_wait_seconds": 0, "suite_wait_seconds": 0, "merge_wait_seconds": 0,
                 "lander_wait_seconds": 0} for repo in ("acme", "toolkit")]
        with patch.object(scoreboard.history, "ended_runs", return_value=rows), \
                patch.object(scoreboard.history, "parks", return_value=[NOW - 60]), \
                patch.object(scoreboard.history, "owner",
                             return_value=[(NOW - 90, "asked", None), (NOW - 80, "paged", None),
                                           (NOW - 60, "answered", 30)]), \
                patch.object(scoreboard.history, "dones", return_value=[(NOW - 60, NOW - 7200, None)]), \
                patch.object(scoreboard, "_git", lambda *args, **kw: b"x\n"):
            board = scoreboard.compute(NOW)
        self.assertEqual({key: list(cells[0]) for key, cells in board.items()},
                         {key: list(parts) for key, _, parts in PINNED})

    def test_render_shows_each_pinned_row_under_its_label(self):
        empty = {key: [None, None] for key, _, _ in PINNED}
        with patch.object(scoreboard, "compute", return_value=empty), \
                patch.object(terminal, "content_width", return_value=100):
            lines = scoreboard.render()
        # the title, the two weeks' heading, then one line a row: an empty row says so in one
        self.assertEqual([line[:8].strip() for line in lines[2:]], [label for _, label, _ in PINNED])


if __name__ == "__main__":
    unittest.main()
