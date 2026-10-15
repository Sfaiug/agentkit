"""What the scoreboard measures is pinned here, so the board changes only with the owner's yes
and a visible test change (AGENTS.md, Owner rules, 14 Oct 2026): the rows and the parts each
cell is built from (`scoreboard.MEASURES`), the rows and parts `compute` answers with, and
what `render` shows of them, in that order.

Offline: an empty sandbox HOME with no history database, and git answering nothing; the
filled board reads literal history rows, and git answering one line to everything.
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
        # a merged run this week in a product and in ak, with its waits: every row has a cell
        rows = [{"run_id": f"fix-{repo}", "repo": repo, "final_state": "pass", "rounds_used": 1,
                 "started_at": NOW - 3600, "finished_at": NOW - 60, "changed_lines": 1,
                 "executor_tokens": 1, "reviewer_tokens": 1, "total_seconds": 3540,
                 "slot_wait_seconds": 0, "suite_wait_seconds": 0, "merge_wait_seconds": 0,
                 "lander_wait_seconds": 0} for repo in ("acme", "toolkit")]
        with patch.object(scoreboard.history, "ended_runs", return_value=rows), \
                patch.object(scoreboard, "_git", lambda *args, **kw: b"x\n"):
            board = scoreboard.compute(NOW)
        self.assertEqual({key: list(cells[0]) for key, cells in board.items()},
                         {key: list(parts) for key, _, parts in PINNED})

    def test_render_shows_each_pinned_part_under_its_row(self):
        # this week every part known, the week before every part that can be unknown so
        filled = {"products": ((3, 2, 1 / 3, 1 / 3, 1.5, 1500), (1, 1, 1, 0, None, None)),
                  "ak": ((2, 1, .5, .5, 2, 100, .25), (1, 0, 0, 1, None, None, None)),
                  "waits": ((.25, 1.5, .5), (0, 0, None)),
                  "merged": ((1.375, 1.875, .75, 1.0), None),
                  "escaped": ((2, 1, 1, 1, {"acme-reviewer": [1, 2]}), (0, 0, 0, 1, {})),
                  "size": ((17, 5), (None, None))}
        board = {key: [values and dict(zip(parts, values)) for values in filled[key]]
                 for key, _, parts in PINNED}
        with patch.object(scoreboard, "compute", return_value=board), \
                patch.object(terminal, "content_width", return_value=100):
            lines = scoreboard.render()
        # every part of every row is shown, and nothing else: a number added, dropped or
        # renamed on the board changes these lines
        self.assertEqual(lines, [
            "Scoreboard (reported tokens; size now and 7 days ago)",
            "          last 7 days                                   7 days before",
            "products  3 runs ended; 33% merged in round 1; 33%      1 runs ended; 100% merged in round 1; 0%",
            "          ended without merging; median 1.5 hours to    ended without merging; merge hours unknown;",
            "          merge; median 1,500 tokens per merged run     median tokens per merged run unknown",
            "ak        2 runs ended; 50% merged in round 1; 50%      1 runs ended; 0% merged in round 1; 100%",
            "          ended without merging; median 2 hours to      ended without merging; no merged runs; no",
            "          merge; median 100 tokens per merged run; 25%  tokens recorded",
            "          of all recorded tokens",
            "waits     25% of run time waiting for a slot or its     0% of run time waiting for a slot or its own",
            "          own suite turn; 1.5 hours in a landing line,  suite turn; 0.0 hours in a landing line,",
            "          where checks waited 0.5 hours for a suite     where checks' waits for a suite turn are not",
            "          turn                                          recorded",
            "merged    median hours per merged change: 1.4 in model  no merged change",
            "          turns, 1.9 ak's own work, 0.8 waiting, 1.0",
            "          with its seat between runs",
            "escaped   1 of 2 merged changes had a line rewritten    0 of 0 merged changes had a line rewritten",
            "          within 7 days (acme-reviewer 1 of 2); 1       within 7 days; 1 with no merge commit to",
            "          merged under 7 days ago may still be; 1 with  follow",
            "          no merge commit to follow",
            "ak size   17 code lines, 5 README words                 code lines unknown, README words unknown",
        ])


if __name__ == "__main__":
    unittest.main()
