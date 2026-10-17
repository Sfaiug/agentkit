"""Every run records the effort each role ran it at, and `ak models` splits ak's own numbers
by it.

The executor's turn records its effort for its role (the entry's `exec_effort`, else its
`effort`) on the run's record, which the loop's save keeps whatever the config says since, the
launch receipt the seat's orchestrator's, and each finished review its reviewer's
(`review_effort`, else `effort`) on its review row; the history keeps them, the first write's
orchestrator effort as it keeps the orchestrator, unknown included.  `ak models` then shows a
model's own numbers per effort its runs recorded (`opus @ max`, the strongest first), the bare
name for runs that recorded none: a pull request its seat wrote counts under the receipt's
effort only where that seat launched the run, not where a lease restart launched it from the
seat running another model since.

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
from agentkit import config, hand_in, history, matrix, run, terminal, transitions, turns
import test_model_rows as rows_test


class LiveByEffort(Sandbox):
    def review(self, run_id, reviewer, effort, verdict="PASS", n=0):
        entry = self.cfg["models"][reviewer]
        history.record_review(run_id, f"{run_id}/review-{n}", harness=entry["harness"],
                              model=entry["model"], blocking=0, followup=0, note=0, round=1,
                              verdict=verdict, effort=effort)

    def test_the_history_keeps_each_role_s_effort_and_the_first_orchestrator_s(self):
        history.start_run("r1", repo="acme", started_at=1, orchestrator="fable",
                          orchestrator_effort="high")
        history.update_run("r1", executor_effort="max")
        # a resume writes the receipt again: the orchestrator and its effort stay the first's
        history.start_run("r1", repo="acme", started_at=1, orchestrator="opus",
                          orchestrator_effort="xhigh")
        self.review("r1", "astra", "low")
        self.review("r1", "astra", None, verdict="FAIL", n=1)     # from before efforts were kept
        history.finish_run("r1", finished_at=50, final_state="pass", verdict="PASS", rounds_used=1)
        row, = history.ended_runs(0, 100)
        self.assertEqual((row["orchestrator"], row["orchestrator_effort"], row["executor_effort"]),
                         ("fable", "high", "max"))
        astra = self.cfg["models"]["astra"]
        self.assertEqual(history.reviewed_runs(astra["harness"], astra["model"]),
                         {"low": (1, 1), None: (1, 0)})
        # a run from before efforts were recorded keeps its orchestrator's effort unknown: a
        # resume from the seat running another model since lends it neither model nor effort
        history.start_run("r2", repo="acme", started_at=2, orchestrator="fable")
        history.start_run("r2", repo="acme", started_at=2, orchestrator="opus",
                          orchestrator_effort="max")
        history.finish_run("r2", finished_at=60, final_state="pass", verdict="PASS", rounds_used=1)
        row, = [row for row in history.ended_runs(0, 100) if row["run_id"] == "r2"]
        self.assertEqual((row["orchestrator"], row["orchestrator_effort"]), ("fable", None))

    def test_the_executor_s_turn_and_the_receipt_record_the_effort_each_role_runs_at(self):
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

        def turn(_cfg, _model, _body, cwd, out, role, *_args, **_kw):
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
        # the receipt: the launching seat's orchestrator at the effort it runs at
        (config.STATE / "session-seat.json").write_text(json.dumps({"orchestrator": "opus"}))
        self.cfg["models"]["opus"]["effort"] = "high"
        with patch.object(run.history, "start_run") as started, \
                patch.object(config, "load", return_value=self.cfg):
            run.history_start({"run_id": "own-pr", "repo": "acme", "launched_session": "seat",
                               "started_at": 1})
        self.assertEqual((started.call_args.kwargs["orchestrator"],
                          started.call_args.kwargs["orchestrator_effort"]), ("opus", "high"))

    def test_ak_models_splits_a_model_s_own_numbers_by_the_effort_it_ran_at(self):
        rows_test.prepare(self)
        clock = iter(range(100, 10000))

        def ended(run_id, executor="opus", effort=None, rounds=1, reviews=(), orchestrator="fable",
                  **fields):
            """A merged run from `orchestrator`'s seat, executed at `effort`, each review as
            (reviewer, effort)."""
            history.start_run(run_id, repo="acme", executor=executor, orchestrator=orchestrator,
                              orchestrator_effort=fields.pop("orchestrator_effort", None),
                              started_at=next(clock))
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
        ended("p1", executor=None, own_orchestrator="fable", orchestrator_effort="high")
        # astra's PR, restarted from its seat running opus at low since: the writer's effort is
        # not the receipt's
        ended("p2", executor=None, own_orchestrator="astra", orchestrator="opus",
              orchestrator_effort="low")
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
        self.assertNotIn("astra @ low", own)
        self.assertEqual(own["gemini"], {"orchestrate": None, "execute": None, "review": None})
        held = matrix.collect(now=10000)
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
