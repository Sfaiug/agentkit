"""`ak models` shows ak's own numbers per configured model and role beside the public ones, with
their count, and they never rank.

Per model: of the runs it executed, the share merged in round 1; of the runs it reviewed, in
whichever round, the share it let through in round 1; of the pull requests its seat wrote, the
share merged in round 1; each with how many runs.  A merge is what the scoreboard tells one by
(the row's size, else its record), so a run passed without merging is none, and a run that
ended without a verdict of the work (stopped, not needed, errored) merged nothing; a review
counts by the harness and model id that ran it once finished, whatever became of its run since
(one still going, or errored after), a stopped run's never, and one from before its round was
recorded counts for nothing; a pull request another seat wrote is nobody's own, whichever seat
launched the review.

Offline: the history and run records written under a throwaway HOME, the boards and catalogs
faked (tests/test_model_rows.py).
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
from agentkit import boards, config, history, matrix, record, terminal
import test_model_rows as rows_test


class LiveColumn(Sandbox):
    def setUp(self):
        super().setUp()
        rows_test.prepare(self)
        clock = iter(range(100, 10000))

        def run(run_id, reviews, executor="opus", state="pass", rounds=1, **fields):
            """A run launched from fable's seat, with each finished review as (reviewer, round,
            verdict), ended as `state` after `rounds` rounds."""
            history.start_run(run_id, repo="acme", executor=executor, orchestrator="fable",
                              started_at=next(clock))
            for n, (reviewer, rnd, verdict) in enumerate(reviews):
                entry = self.cfg["models"][reviewer]
                history.record_review(run_id, f"{run_id}/review-{n}", harness=entry["harness"],
                                      model=entry["model"], blocking=0, followup=0, note=0,
                                      round=rnd, verdict=verdict)
            history.finish_run(run_id, final_state=state, rounds_used=rounds,
                               finished_at=next(clock), **fields)

        run("t1", [("astra", 1, "PASS")], changed_lines=12)
        run("t2", [("astra", 1, "FAIL"), ("astra", 2, "PASS")], rounds=2, changed_lines=3)
        run("t3", [("astra", 1, "FAIL"), ("opus", 2, "FAIL"), ("opus", 3, "FAIL")], state="fail", rounds=3)
        run("t4", [("opus", 1, "PASS")], executor="astra")     # an older merge, unsized: its record says
        (config.RUNS / "t4").mkdir()
        record.save_state(config.RUNS / "t4", {"run_id": "t4", "state": "pass", "merged": True})
        run("t5", [("opus", 1, "PASS")], executor="astra")     # passed with --no-merge: no merge
        run("t6", [("astra", None, None)], changed_lines=1)    # reviewed before its round was kept
        # fable's seat's own pull requests: merged in round 1, fixed by opus and merged in round
        # 2, blocked; then another's, which its seat launched the review of
        run("p1", [("astra", 1, "PASS")], executor=None, own_orchestrator="fable", changed_lines=5)
        run("p2", [("astra", 1, "FAIL"), ("astra", 2, "PASS")], rounds=2, own_orchestrator="fable",
            changed_lines=9)
        run("p3", [("astra", 1, "FAIL")], executor=None, state="blocked", own_orchestrator="fable")
        run("f1", [("astra", 1, "PASS")], executor=None)
        for state in ("stopped", "not_needed", "error"):
            run(state, [("astra", 1, "PASS")], state=state, changed_lines=1)
        history.start_run("going", repo="acme", executor="opus", started_at=next(clock))   # still going
        entry = self.cfg["models"]["astra"]
        history.record_review("going", "going/review-0", harness=entry["harness"], model=entry["model"],
                              blocking=1, followup=0, note=0, round=1, verdict="FAIL")

    def test_each_model_s_own_numbers_per_role_with_their_count(self):
        own = matrix.live(self.cfg, now=10000)
        self.assertEqual(own["opus"], {"orchestrate": None,
                                       "execute": {"runs": 5, "round_1": 40},
                                       "review": {"runs": 3, "round_1": 67}})
        # astra reviewed the judged runs, the run that errored after its pass, the one found not
        # needed and the one still going, never the stopped one or the one without a round
        self.assertEqual(own["astra"], {"orchestrate": None,
                                        "execute": {"runs": 2, "round_1": 50},
                                        "review": {"runs": 10, "round_1": 50}})
        self.assertEqual(own["fable"], {"orchestrate": {"runs": 3, "round_1": 33},
                                        "execute": None, "review": None})
        self.assertIn("gemini", own)       # every configured model, with nothing where it ran nothing
        self.assertEqual(own["gemini"], {"orchestrate": None, "execute": None, "review": None})

    def test_the_table_shows_them_under_the_scores_and_json_carries_them(self):
        held = boards.collect(now=10000)
        table = matrix.scored(matrix.rows(self.cfg, held, matrix.present()), matrix.bests(held))
        with patch.object(matrix.time, "time", return_value=10000):
            lines = [terminal.plain(line) for line in
                     matrix.render(table, held, matrix.live(self.cfg)).splitlines()]
        text = "\n".join(lines)
        self.assertTrue(all(terminal.cells(line) <= 100 for line in lines))
        at = next(i for i, line in enumerate(lines) if line.startswith("ak's own runs, never ranking"))
        heading = next(i for i, line in enumerate(lines) if line.split() == ["model", "orch", "exec", "review"])
        self.assertLess(at, heading)
        self.assertRegex(text, r"\nopus +- +40% of 5 +67% of 3\n")
        self.assertRegex(text, r"\nfable +33% of 3 +- +-\n")
        self.assertLess(at, next(i for i, line in enumerate(lines) if line.startswith("arena.ai:")))
        # the recommendation is the boards' alone: opus's own numbers change nothing (the boards
        # tell the two efforts apart by nothing, and Artificial Analysis priced only the max run)
        self.assertEqual(matrix.row_label(matrix.recommended(table)["execute"][0]), "claude-opus-5-5 @ max")
        out = io.StringIO()
        with redirect_stdout(out), patch.object(config, "load", return_value=self.cfg):
            self.assertEqual(matrix.main(["--json"]), 0)
        self.assertEqual(json.loads(out.getvalue())["live"]["opus"]["execute"], {"runs": 5, "round_1": 40})


if __name__ == "__main__":
    unittest.main()
