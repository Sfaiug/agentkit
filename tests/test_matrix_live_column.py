"""`ak models` shows ak's own numbers per configured model and role beside the public ones, with
their count, and they never rank.

Per model: of the runs it ended as executor, the share merged in round 1; as reviewer, the share
it let through in round 1; as the orchestrator of a seat's own pull request, the share merged in
round 1; each with how many runs.  Runs that ended without a verdict of the work (stopped, not
needed, errored) count for nothing.

Offline: the history rows are handed in, the boards and catalogs faked (tests/test_model_rows.py),
a throwaway HOME.
"""

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
from fixtures.sandbox import Sandbox
from agentkit import config, history, matrix, terminal
import test_model_rows as rows_test


def run(**fields):
    row = {"executor": "opus", "reviewer": "astra", "orchestrator": "fable", "final_state": "pass",
           "rounds_used": 1}
    row.update(fields)
    return row


RUNS = [run(), run(rounds_used=2), run(final_state="fail", rounds_used=3),
        run(executor="astra", reviewer="opus"), run(executor="astra", reviewer="opus", rounds_used=2),
        run(executor=None, orchestrator="fable"), run(executor=None, orchestrator="fable", rounds_used=2),
        run(executor=None, orchestrator="fable", final_state="blocked"),
        run(final_state="stopped"), run(final_state="not_needed"), run(final_state="error")]


class LiveColumn(Sandbox):
    def setUp(self):
        super().setUp()
        rows_test.prepare(self)
        self.stack.enter_context(patch.object(history, "ended_runs", return_value=list(RUNS)))

    def test_each_model_s_own_numbers_per_role_with_their_count(self):
        own = matrix.live(self.cfg, now=10000)
        self.assertEqual(own["opus"], {"orchestrate": None,
                                       "execute": {"runs": 3, "round_1": 33},
                                       "review": {"runs": 2, "round_1": 50}})
        # astra reviewed the three task runs and the three own pull requests
        self.assertEqual(own["astra"], {"orchestrate": None,
                                        "execute": {"runs": 2, "round_1": 50},
                                        "review": {"runs": 6, "round_1": 33}})
        # a seat's own pull request counts for its orchestrator; a blocked one ended too
        self.assertEqual(own["fable"], {"orchestrate": {"runs": 3, "round_1": 33},
                                        "execute": None, "review": None})
        self.assertIn("gemini", own)       # every configured model, with nothing where it ran nothing
        self.assertEqual(own["gemini"], {"orchestrate": None, "execute": None, "review": None})

    def test_the_table_shows_them_under_the_scores_and_json_carries_them(self):
        held = matrix.collect(now=10000)
        table = matrix.scored(matrix.rows(self.cfg, held))
        with patch.object(matrix.time, "time", return_value=10000):
            lines = [terminal.plain(line) for line in
                     matrix.render(table, held, matrix.live(self.cfg)).splitlines()]
        text = "\n".join(lines)
        self.assertTrue(all(terminal.cells(line) <= 100 for line in lines))
        at = next(i for i, line in enumerate(lines) if line.startswith("ak's own runs, never ranking"))
        heading = next(i for i, line in enumerate(lines) if line.split() == ["model", "orch", "exec", "review"])
        self.assertLess(at, heading)
        self.assertRegex(text, r"\nopus +- +33% of 3 +50% of 2\n")
        self.assertRegex(text, r"\nfable +33% of 3 +- +-\n")
        self.assertLess(at, next(i for i, line in enumerate(lines) if line.startswith("arena.ai:")))
        # the recommendation is the boards' alone: opus's own numbers change nothing
        self.assertEqual(matrix.row_label(matrix.recommended(table)["execute"]), "claude-opus-5-5 @ max")
        out = io.StringIO()
        with redirect_stdout(out), patch.object(config, "load", return_value=self.cfg):
            self.assertEqual(matrix.main(["--json"]), 0)
        self.assertEqual(json.loads(out.getvalue())["live"]["opus"]["execute"], {"runs": 3, "round_1": 33})


if __name__ == "__main__":
    unittest.main()
