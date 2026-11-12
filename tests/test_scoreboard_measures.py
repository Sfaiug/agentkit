"""What the scoreboard measures is pinned here, so the board changes only with a visible test
change (test_the_measures_are_the_pinned_ones, 14 Oct 2026): the rows and the parts each
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
    # answer_share: write-up task 15, changed on review under the Owner rule of 27 Oct 2026.
    ("intent", "intent", ("measured", "hours", "live", "live_hours", "answer_share")),
    ("owner", "owner", ("asked", "paged", "hours")),
    ("built", "built", ("seat_merged", "seat_first_round", "worker_merged", "worker_first_round")),
    ("waits", "waits", ("compute", "merge_hours", "lander_hours")),
    ("merged", "merged", ("model", "ak", "waiting", "seat")),
    # checks: write-up task 1 (30 Oct 2026), changed on review under the Owner rule of 27 Oct 2026.
    ("checks", "checks", ("suites", "hours")),
    ("parks", "parks", ("parked",)),
    # conflicts: write-up task 20, 4 Nov 2026, under the Owner rule of 27 Oct 2026.
    ("conflicts", "conflicts", ("share", "files")),
    ("sunk", "sunk", ("share", "tokens")),
    # a review miss counts only when it breaks, at landing or after merge, never a rewrite
    # later: the owner's yes, 16 Oct 2026, in place of `escaped`
    # Landing flakes apart from review misses: write-up task 21, 3 Nov 2026.
    ("broke", "broke", ("merged", "after_merge", "landing", "flakes", "unknown")),
    # pairs: the orchestrator's decision of 3 Nov 2026, changed on review under the Owner rule of 27 Oct 2026.
    ("pairs", "review pairs", ("self", "self_landing", "same_provider", "same_provider_landing", "other_landing")),
    # findings: write-up task 18 (30 Oct 2026), changed on review under the Owner rule of 27 Oct 2026.
    # let_go and let_go_broke: write-up task 18, under the Owner rule of 27 Oct 2026.
    # later and inside_fix: write-up task 18, under the Owner rule of 27 Oct 2026.
    ("findings", "findings", ("blocking", "disputed", "conceded", "raised_again", "let_go", "let_go_broke",
                              "later", "inside_fix")),
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

    # what the board measures is pinned by `tests/test_scoreboard_measures.py`.
    # [2 Oct, 14 Oct, 27 Oct]
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
                 "lander_wait_seconds": 0, "review_pair": "self", "landing_breaks": 0}
                for repo in ("acme", "toolkit")]
        checks = [{"run_id": row["run_id"], "round": 1, "kind": "rules", "tree": "cedar",
                   "command": "AK_SHARD=0/2 suite", "started_at": NOW - 300,
                   "finished_at": NOW - 60} for row in rows]
        with patch.object(scoreboard.history, "ended_runs", return_value=rows), \
                patch.object(scoreboard.history, "checks", return_value=checks), \
                patch.object(scoreboard.history, "findings", return_value=[{
                    "at": NOW - 60, "kind": "finding", "handed": "finding", "replayed": None,
                    "inside_fix": 1, "outcome": None, "raised_again": False}]), \
                patch.object(scoreboard.history, "parks", return_value=[NOW - 60]), \
                patch.object(scoreboard.history, "owner",
                             return_value=[(NOW - 90, "asked", None), (NOW - 80, "paged", None),
                                           (NOW - 60, "answered", 30)]), \
                patch.object(scoreboard.history, "dones", return_value=[(NOW - 60, NOW - 7200, None, 30)]), \
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
        width = max(len(label) for _, label, _ in PINNED)
        self.assertEqual([line[:width].strip() for line in lines[2:]], [label for _, label, _ in PINNED])


if __name__ == "__main__":
    unittest.main()
