"""Every run records the effort each role ran it at, and `ak models` splits ak's own numbers
by it.

The executor's turn records its effort for its role (the entry's `exec_effort`, else its
`effort`) on the run's record before the worker runs, which the loop's save keeps whatever the
config says since; the writer of a seat's own pull request is captured with the effort it runs
at, which a restart carries with it (tests/test_review_restart.py) and the finish writes; and
each finished review records its reviewer's (`review_effort`, else `effort`) on its review row.
`ak models` then shows a model's own numbers per effort its runs recorded (`opus @ max`, the
strongest first), the bare name for runs that recorded none.

Offline: a throwaway HOME holds the history and run records, the config is the sandbox's, the
boards and catalogs are faked (tests/test_model_rows.py), and the loop's save is driven on a
record without a repository.
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
from agentkit import boards, config, hand_in, history, matrix, record, run, terminal, transitions, turns
import test_model_rows as rows_test


class LiveByEffort(Sandbox):
    def review(self, run_id, reviewer, effort, verdict="PASS", n=0):
        entry = self.cfg["models"][reviewer]
        history.record_review(run_id, f"{run_id}/review-{n}", harness=entry["harness"],
                              model=entry["model"], blocking=0, followup=0, note=0, round=1,
                              verdict=verdict, effort=effort)

    def test_the_history_keeps_each_role_s_effort(self):
        history.start_run("r1", repo="acme", started_at=1)
        history.update_run("r1", executor_effort="max")
        self.review("r1", "astra", "low")
        self.review("r1", "astra", None, verdict="FAIL", n=1)     # from before efforts were kept
        history.finish_run("r1", finished_at=50, final_state="pass", verdict="PASS", rounds_used=1,
                           own_orchestrator="fable", own_orchestrator_effort="high")
        row, = history.ended_runs(0, 100)
        self.assertEqual((row["executor_effort"], row["own_orchestrator"],
                          row["own_orchestrator_effort"]), ("max", "fable", "high"))
        astra = self.cfg["models"]["astra"]
        self.assertEqual(history.reviewed_runs(astra["harness"], astra["model"]),
                         {"low": (1, 1), None: (1, 0)})

    def test_the_executor_s_turn_and_the_writer_s_capture_record_the_effort_each_runs_at(self):
        self.cfg["models"]["opus"]["exec_effort"] = "max"
        directory = config.RUNS / "fix-api"
        directory.mkdir()
        state = {"run_id": "fix-api", "title": "Fix the API", "state": "running", "started_at": 1,
                 "base": "main", "base_sha": "0" * 40, "branch": "ak/fix-api",
                 "executor": "opus", "reviewer": "astra", "rounds": 3, "round_summaries": []}
        lp = run.Loop(self.cfg, directory, state, {}, lambda _: None, directory, "Fix it.",
                      ["true"], "", [])
        lp.rnd = 1
        with patch.object(run.history, "update_run") as updated:
            lp.save()
        self.assertIsNone(updated.call_args.kwargs["executor_effort"])    # no executor ran yet
        self.assertNotIn("reviewer_effort", updated.call_args.kwargs)   # a review's is its row's
        on_record = []      # the record's executor effort as each worker starts

        def turn(_cfg, _model, _body, cwd, out, role, *_args, **_kw):
            on_record.append(record.read_state(directory).get("executor_effort"))
            out.mkdir(parents=True, exist_ok=True)
            with Path(hand_in.start(out, cwd, role=role)).open("a") as output:
                output.write(json.dumps({"kind": "done"}) + "\n")
            (out / "final.md").write_text("Handed in.")
            return 0, "Handed in.", "fixture-session", False
        with patch.object(turns, "call_retrying", side_effect=turn), \
                patch.object(transitions, "history_role_tokens"), \
                patch.object(run.history, "update_run") as updated:
            run.execute(lp, "executor", "Build the API.", "executor")
        self.assertEqual(updated.call_args.kwargs["executor_effort"], "max")
        self.assertEqual(on_record, ["max"])    # before the worker ran: a cut-off turn keeps it
        # a review-only resume saves under the config as it stands since: the executor ran at max
        self.cfg["models"]["opus"]["exec_effort"] = "low"
        with patch.object(run.history, "update_run") as updated:
            lp.save()
        self.assertEqual(updated.call_args.kwargs["executor_effort"], "max")
        # an entry that sets no effort of its own for the role runs at its effort
        lp.executor = "astra"
        with patch.object(turns, "call_retrying", side_effect=turn), \
                patch.object(transitions, "history_role_tokens"), \
                patch.object(run.history, "update_run") as updated:
            run.execute(lp, "executor", "Build the API.", "executor")
        self.assertEqual(updated.call_args.kwargs["executor_effort"],
                         self.cfg["models"]["astra"]["effort"])
        self.assertEqual(on_record[-1], self.cfg["models"]["astra"]["effort"])
        # the writer of a seat's own pull request is captured with the effort it runs at, and a
        # writer the record holds keeps the effort captured with it whatever the config says since
        self.cfg["models"]["opus"]["effort"] = "high"
        with patch.object(run, "own_pr_orchestrator", return_value=(True, "opus")):
            self.assertEqual(run.pr_writer(self.cfg, {}, "seat", "owner"), (True, "opus", "high"))
        self.cfg["models"]["opus"]["effort"] = "low"
        carried = {"own_pr": True, "own_orchestrator": "opus", "own_orchestrator_effort": "high"}
        self.assertEqual(run.pr_writer(self.cfg, carried, "seat", "owner"), (True, "opus", "high"))
        # a writer from before its effort was kept stays unknown; another's pull request has none
        self.assertEqual(run.pr_writer(self.cfg, {"own_pr": True, "own_orchestrator": "opus"},
                                       "seat", "owner"), (True, "opus", None))
        self.assertEqual(run.pr_writer(self.cfg, {"own_pr": False}, "seat", "owner"),
                         (False, None, None))

    def test_ak_models_splits_a_model_s_own_numbers_by_the_effort_it_ran_at(self):
        rows_test.prepare(self)
        clock = iter(range(100, 10000))

        def ended(run_id, executor="opus", effort=None, rounds=1, reviews=(), **fields):
            """A merged run, executed at `effort`, each review as (reviewer, effort); `fields`
            end it (a seat's own pull request names its writer and the writer's effort)."""
            history.start_run(run_id, repo="acme", executor=executor, started_at=next(clock))
            history.update_run(run_id, executor_effort=effort)
            for n, (reviewer, at) in enumerate(reviews):
                self.review(run_id, reviewer, at, n=n)
            history.finish_run(run_id, final_state="pass", rounds_used=rounds,
                               finished_at=next(clock), changed_lines=1, **fields)

        ended("t1", effort="max")
        ended("t2", effort="max", rounds=2)
        ended("t3", effort="high")
        ended("t4")                                           # before efforts were recorded
        ended("t5", executor="astra", reviews=[("opus", "max")])
        ended("p1", executor=None, own_orchestrator="fable", own_orchestrator_effort="high")
        ended("p2", executor=None, own_orchestrator="astra")  # before the writer's effort was kept
        own = matrix.live(self.cfg, now=10000)
        self.assertEqual([label for label in own if label.split(" @ ")[0] == "opus"],
                         ["opus @ max", "opus @ high", "opus"])   # the strongest first, none last
        self.assertEqual(own["opus @ max"], {"orchestrate": None,
                                             "execute": {"runs": 2, "round_1": 50},
                                             "review": {"runs": 1, "round_1": 100}})
        self.assertEqual(own["opus @ high"]["execute"], {"runs": 1, "round_1": 100})
        self.assertEqual(own["opus"]["execute"], {"runs": 1, "round_1": 100})
        self.assertEqual(own["fable @ high"]["orchestrate"], {"runs": 1, "round_1": 100})
        self.assertNotIn("fable", own)
        self.assertEqual(own["astra"], {"orchestrate": {"runs": 1, "round_1": 100},
                                        "execute": {"runs": 1, "round_1": 100}, "review": None})
        self.assertEqual(own["gemini"], {"orchestrate": None, "execute": None, "review": None})
        held = boards.collect(now=10000)
        table = matrix.rows(self.cfg, held, matrix.present())
        with patch.object(matrix.time, "time", return_value=10000):
            lines = [terminal.plain(line) for line in
                     matrix.render(matrix.scored(table), held, own).splitlines()]
        text = "\n".join(lines)
        self.assertTrue(all(terminal.cells(line) <= 100 for line in lines))
        self.assertRegex(text, r"\nopus @ max +- +50% of 2 +100% of 1\n")
        self.assertRegex(text, r"\nopus +- +100% of 1 +-\n")
        out = io.StringIO()
        with redirect_stdout(out), patch.object(config, "load", return_value=self.cfg):
            self.assertEqual(matrix.main(["--json"]), 0)
        self.assertEqual(json.loads(out.getvalue())["live"]["opus @ high"]["execute"],
                         {"runs": 1, "round_1": 100})


if __name__ == "__main__":
    unittest.main()
