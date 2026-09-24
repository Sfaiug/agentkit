"""History, estimates, and the small integrations that consume them."""

import io
import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from contextlib import closing, redirect_stdout
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, history, run, usage  # noqa: E402


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="agentkit-history-")
        self.home = Path(self.tmp.name) / ".agentkit"
        self.home.mkdir()
        self.patch = patch.object(config, "HOME", self.home)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(history._OPEN.clear)    # the steps this process counts

    def row(self, run_id="r1"):
        with sqlite3.connect(history.path()) as db:
            return db.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()

    def test_run_writes_and_updates_its_row(self):
        history.start_run("r1", repo="/tmp/project", executor="opus", reviewer="astra",
                          started_at=10, session="seat")
        history.update_run("r1", rounds_used=2, final_state="pass", verdict="PASS")
        row = self.row()
        self.assertEqual(row[1:7], ("project", "opus", "astra", 2, "pass", "PASS"))

    def test_step_seconds_are_summed(self):
        history.start_run("r1", started_at=10)
        history.add_seconds("r1", "executor", 2)
        history.add_seconds("r1", "executor", 3)
        self.assertEqual(self.row()[9], 5)

    def test_write_failure_does_not_raise(self):
        with patch.object(history, "_connect", side_effect=OSError("read only")):
            history.start_run("r1", log=lambda _: None)
            history.update_run("r1", verdict="FAIL", log=lambda _: None)

    def test_time_estimate_needs_five_runs(self):
        now = time.time()
        for n, seconds in enumerate((10, 20, 30, 40)):
            history.start_run(str(n), repo="project", started_at=now - seconds)
            history.add_seconds(str(n), "executor", seconds)
            history.finish_run(str(n), started_at=now - seconds, finished_at=now)
        self.assertIsNone(history.estimate_seconds("project"))
        history.start_run("four", repo="project", started_at=now - 60)
        history.add_seconds("four", "executor", 60)
        history.finish_run("four", started_at=now - 60, finished_at=now)
        self.assertEqual(history.estimate_seconds("project"), 30)

    def test_time_estimate_uses_median(self):
        now = time.time()
        for n, seconds in enumerate((10, 20, 30, 40, 100)):
            history.start_run(str(n), repo="project", started_at=now - seconds)
            history.add_seconds(str(n), "executor", seconds)
            history.finish_run(str(n), started_at=now - seconds, finished_at=now)
        self.assertEqual(history.estimate_seconds("project"), 30)

    def test_suite_runs_are_never_recorded_and_old_ones_never_counted(self):
        # a suite's clone, a repository under some HOME's .agentkit/tmp -- named once the
        # launch's row exists -- and a run launched under the suites' notify sink: no row
        history.start_run("smoke", repo="/x/agentkit-smoke", started_at=1)
        history.start_run("tmp", started_at=1)
        history.start_run("tmp", repo="/home/u/.agentkit/tmp/smoke-1/repo-retry", started_at=1)
        run.history_start({"run_id": "sink", "repo": "/tmp/project", "notify_sink": "dry-run"})
        for run_id in ("smoke", "tmp", "sink"):
            self.assertIsNone(history.get(run_id))
        # the smoke rows written before this rule are read past by every statistic
        now = time.time()
        with sqlite3.connect(history.path()) as db:
            for n in range(12):
                db.execute("INSERT INTO runs (run_id, repo, executor, rounds_used, final_state, "
                           "verdict, started_at, finished_at, executor_seconds) "
                           "VALUES (?,?,?,?,?,?,?,?,?)",
                           (f"old{n}", "agentkit-smoke", "opus", 1, "pass", "PASS", now - 5,
                            now, 5))
        self.assertIsNone(history.estimate_seconds("project"))
        self.assertIsNone(history.estimate_seconds("agentkit-smoke"))
        self.assertIsNone(history.role_stats("project", "executor", "opus"))
        self.assertIsNone(history.size_summary("agentkit-smoke"))
        self.assertEqual(history.finished_repos(), [])
        self.assertEqual(history.role_lines(), [])

    def test_estimate_and_speed_are_active_time_of_runs_not_stopped(self):
        now = time.time()
        for n in range(5):
            # a day on the clock each, parked most of it: fifteen minutes of steps
            history.start_run(f"r{n}", repo="ATOLL", executor="opus", started_at=now - 86400)
            history.add_seconds(f"r{n}", "executor", 600)
            history.add_seconds(f"r{n}", "done-when", 300)
            history.finish_run(f"r{n}", started_at=now - 86400, finished_at=now,
                               final_state="pass", verdict="PASS")
        history.start_run("stopped", repo="ATOLL", executor="opus", started_at=now - 350000)
        history.add_seconds("stopped", "executor", 90000)
        history.finish_run("stopped", started_at=now - 350000, finished_at=now,
                           final_state="stopped", verdict="STOPPED")
        self.assertEqual(history.estimate_seconds("ATOLL"), 900)
        self.assertEqual(history.role_stats("ATOLL", "executor", "opus"), (100, 5, 600))
        # a step closed when its run parked stays closed: the stop days later adds nothing
        history.start_run("parked", repo="ATOLL", started_at=0)
        history.open_step("parked", "executor", 100)
        run.history_finish({"run_id": "parked", "state": "waiting_login", "finished_at": 400})
        run.history_finish({"run_id": "parked", "state": "stopped",
                            "finished_at": 400 + 96 * 3600})
        self.assertEqual(history.get("parked")["executor_seconds"], 300)
        # a retry's sleep is no step's: forty seconds of work, a minute's wait, twenty more
        run_dir = self.home / "runs" / "retried"
        out = run_dir / "round-1" / "executor"
        out.mkdir(parents=True)
        run.save_state(run_dir, {"run_id": "retried", "state": "running", "step": "executor"})
        history.start_run("retried", repo="ATOLL", started_at=0)
        clock = [1000.0]

        def sleep(seconds):
            clock[0] += seconds

        with patch.object(run.time, "time", lambda: clock[0]), \
                patch.object(run.time, "sleep", sleep):
            history.open_step("retried", "executor")
            clock[0] += 40
            run.transient_wait(out, 60)
            clock[0] += 20
            history.close_step("retried")
        self.assertEqual(history.get("retried")["executor_seconds"], 60)
        # ... nor is the wait for another run's merge turn: thirty seconds' merging, then ten
        real_flock = run.fcntl.flock

        def flock(lock, flags):
            if ".merge-" not in lock.name:
                return real_flock(lock, flags)
            if flags & run.fcntl.LOCK_NB:
                raise BlockingIOError
            clock[0] += 600         # another run lands meanwhile

        state = {"run_id": "retried", "state": "running", "base": "main", "rounds": 1,
                 "repo": "/x/ATOLL", "executor": "opus", "reviewer": "astra",
                 "round_summaries": [{}]}
        lp = run.Loop({}, run_dir, state, {}, lambda _: None, run_dir, "", [], "", [])
        with patch.object(run.time, "time", lambda: clock[0]), \
                patch.object(run.fcntl, "flock", flock), \
                patch.object(config, "RUNS", self.home / "runs"):
            lp.step("merge")
            clock[0] += 30
            with run.merge_turn(lp, "origin/main"):
                clock[0] += 10
            history.close_step("retried")
        self.assertEqual(history.get("retried")["merge_seconds"], 40)

    def test_a_dead_loop_keeps_its_checkpointed_work_and_a_merge_retry_its_time(self):
        # the sampler counts the open step as the loop goes, so a loop that dies keeps its
        # minute of work, nobody adds the hours it lay dead, and the resume adds its own
        history.start_run("r1", repo="ATOLL", started_at=0)
        history.open_step("r1", "executor", 1000)
        history.close_step("r1", 1060, keep=True)
        history._OPEN.clear()                          # the loop dies with its process
        run.history_finish({"run_id": "r1", "state": "interrupted", "step": "executor",
                            "step_at": 1000, "finished_at": 90000})
        history.open_step("r1", "executor", 90000)     # the resume, the next morning
        history.close_step("r1", 90020)
        self.assertEqual(history.get("r1")["executor_seconds"], 80)
        # ... and the sampler a loop runs beside it is what takes that checkpoint
        history.start_run("r2", repo="ATOLL", started_at=0)
        history.open_step("r2", "executor", time.time() - 5)
        sampler = history.Sampler("r2", interval=0.01)
        sampler.start()
        deadline = time.time() + 5
        while not history.get("r2")["executor_seconds"] and time.time() < deadline:
            time.sleep(0.01)
        sampler.stop()
        sampler.join(timeout=2)
        self.assertGreaterEqual(history.get("r2")["executor_seconds"], 5)
        # `ak run merge` on a finished PASS runs a merge step of its own: its time counts
        run_dir = self.home / "runs" / "merged"
        run_dir.mkdir(parents=True)
        state = {"run_id": "merged", "state": "running", "base": "main", "rounds": 1,
                 "executor": "opus", "reviewer": "astra", "round_summaries": [{}]}
        run.save_state(run_dir, state)
        history.start_run("merged", repo="ATOLL", started_at=0)
        history.add_seconds("merged", "merge", 10)
        history.finish_run("merged", final_state="pass", verdict="PASS", finished_at=100)
        lp = run.Loop({}, run_dir, state, {}, lambda _: None, run_dir, "", [], "", [])
        lp.step("merge")
        state["finished_at"] = state["step_at"] + 200
        run.history_finish(state)
        self.assertAlmostEqual(history.get("merged")["merge_seconds"], 210, delta=1)

    def test_rows_from_before_are_read_as_written_and_never_rewritten(self):
        # the host's database as an earlier build of this change left it, and the rows an older
        # agentkit writes into it: steps that counted every retry's wait, the log naming one,
        # a stop days after a park that counted the park again, a repository only ever stopped,
        # and suite runs -- five in a repository under .agentkit/tmp, known by their records
        runs = self.home / "runs"
        (runs / "waited0").mkdir(parents=True)
        (runs / "waited0" / "log.txt").write_text(
            "WARN executor spark transient '500': down (attempt 1); retrying in 600s\n")
        for n in range(5):
            (runs / f"retry{n}").mkdir()
            (runs / f"retry{n}" / "run.json").write_text(json.dumps(
                {"repo": "/home/u/.agentkit/tmp/smoke-1/repo-retry"}))
        with closing(sqlite3.connect(history.path())) as db, db:
            db.execute(history.SCHEMA)
            db.execute("PRAGMA user_version=1")
            for run_id, repo, state, worked, checked in (
                    *((f"clean{n}", "ATOLL", "pass", 600, 300) for n in range(5)),
                    *((f"waited{n}", "ATOLL", "pass", 30000, 60000) for n in range(3)),
                    ("parked", "ATOLL", "stopped", 350000, 0),
                    ("dropped", "Dropped", "stopped", 60, 0),
                    ("going", "ATOLL", "running", 1000, 0),
                    ("smoke", "agentkit-smoke", "pass", 5, 0),
                    *((f"retry{n}", "repo-retry", "pass", 5, 0) for n in range(5))):
                db.execute("INSERT INTO runs (run_id, repo, executor, rounds_used, final_state, "
                           "verdict, started_at, finished_at, executor_seconds, "
                           "done_when_seconds, peak_rss_mb) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                           (run_id, repo, "opus", 30 if state == "stopped" else 1, state,
                            state.upper(), 0, None if state == "running" else 86400, worked,
                            checked, 4096 if state == "stopped" else 100))

        def written():
            with closing(sqlite3.connect(history.path())) as db:
                return db.execute("SELECT * FROM runs WHERE run_id != 'new' "
                                  "ORDER BY run_id").fetchall()

        before = written()
        with patch.object(config, "RUNS", runs):
            # a few rows whose time includes waits move a median a rank or two, no further
            self.assertEqual(history.estimate_seconds("ATOLL"), 900)
            self.assertEqual(history.role_stats("ATOLL", "executor", "opus"), (100, 8, 600))
            # suite and stopped rows stay, and no statistic reads them
            self.assertEqual(history.estimate_seconds("repo-retry"), 900)
            self.assertEqual(history.estimate_memory_mb("ATOLL"), 100)
            self.assertIsNone(history.size_summary("Dropped"))
            self.assertEqual(history.finished_repos(), ["ATOLL"])
            history.start_run("new", repo="/x/ATOLL", started_at=1)
            history.finish_run("new", finished_at=2, final_state="pass", verdict="PASS")
            self.assertEqual(written(), before)
            # ... and one this agentkit resumes keeps its steps; its own accounting adds to them
            history.start_run("going", repo="/x/ATOLL", started_at=0)
            self.assertEqual(history.get("going")["executor_seconds"], 1000)

    def test_an_attempt_that_ends_by_exception_still_has_its_tokens_read(self):
        root = self.home / "run"
        (root / "round-1").mkdir(parents=True)
        cfg = {"models": {"opus": {"harness": "claude", "model": "m", "effort": "e",
                                   "provider": "anthropic"}},
               "providers": {"anthropic": {}}}

        class Fixture:
            state = {"run_id": "r1", "round_summaries": []}
            executor, exec_sid, wt, scratch, turn_limit = "opus", None, root, True, 1

            def __init__(self):
                self.cfg = cfg

            def save(self):
                pass

            def log(self, _message):
                pass

            def role(self, name):
                return name

            def dir(self, name):
                return root / "round-1" / name

        def killed_after_spending(*args, **kwargs):
            out = args[4]
            out.mkdir(parents=True)
            (out / "events.jsonl").write_text(json.dumps(
                {"type": "result", "usage": {"input_tokens": 400, "output_tokens": 60}}) + "\n")
            raise run.Killed("executor opus SIGKILL twice within a minute", "sid")

        history.start_run("r1")
        env = {"AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0"}
        with patch.dict(os.environ, env), \
                patch.object(run, "call_retrying", side_effect=killed_after_spending):
            for name in ("AGENTKIT_RUN", "AK_PARENT_RUN", "AK_RUN_LOG"):
                os.environ.pop(name, None)
            with self.assertRaises(run.Killed):
                run.execute(Fixture(), "executor", "the task", "executor")
        self.assertEqual(history.get("r1")["executor_tokens"], 460)

    def test_row_names_its_orchestrator_and_history_reports_every_role(self):
        state = self.home / "state"
        state.mkdir()
        (state / "session-seat.json").write_text(json.dumps(
            {"orchestrator": "fable", "workers": ["opus", "astra"]}))
        with patch.object(config, "STATE", state):
            run.history_start({"run_id": "r1", "repo": "/tmp/project", "executor": "opus",
                               "reviewer": "astra", "launched_session": "seat", "started_at": 1})
        history.add_seconds("r1", "executor", 1200)
        history.add_seconds("r1", "reviewer", 600)
        history.finish_run("r1", finished_at=90000, final_state="pass", verdict="PASS")
        self.assertEqual(history.get("r1")["orchestrator"], "fable")
        runs = self.home / "runs"
        runs.mkdir()
        with patch.object(config, "RUNS", runs), redirect_stdout(io.StringIO()) as out:
            self.assertEqual(run.cmd_status(["--history"]), 0)
        self.assertIn("fable: orchestrator: 100% over 1 runs, ~30m", out.getvalue())
        self.assertIn("opus: executor: 100% over 1 runs, ~20m", out.getvalue())
        self.assertIn("astra: reviewer: 100% over 1 runs, ~10m", out.getvalue())

    def test_muse_tokens_come_from_its_session_store_and_silence_reads_unknown(self):
        out = self.home / "reviewer"
        out.mkdir()
        (out / "events.jsonl").write_text("\n".join(json.dumps(event) for event in (
            {"stream": {"kind": "session", "id": "s-1"}, "payload": {"kind": "command_accepted"}},
            {"stream": {"kind": "session", "id": "s-1"},
             "payload": {"kind": "session_run_linked", "run_stream": {"id": "run-2"}}})) + "\n")

        def usage(run_id, family, spent_in, spent_out):
            return json.dumps({"payload": {"kind": "run", "event": {
                "kind": "goal_usage_attribution", "record": {
                    "usage_family": family, "owner": {"run_id": run_id},
                    "quantity": {"input_tokens": spent_in, "output_tokens": spent_out,
                                 "reported": True}}}}})

        store = self.home / "data" / "muse" / "sessions" / "2026" / "09" / "23" / "s-1"
        store.mkdir(parents=True)
        # the resumed session's earlier turn is another run's, and a tool's usage is no model's
        (store / "session.jsonl").write_text("\n".join((
            usage("run-1", "provider", 1000, 10), usage("run-2", "provider", 300, 20),
            usage("run-2", "tool", 7, 7), usage("run-2", "provider", 500, 30))) + "\n")
        history.start_run("r1")
        cfg = {"models": {"spark": {"harness": "muse", "model": "m", "effort": "e",
                                    "provider": "meta"},
                          "opus": {"harness": "claude", "model": "m", "effort": "e",
                                   "provider": "anthropic"}},
               "providers": {"meta": {}, "anthropic": {}}}
        with patch.dict(os.environ, {"XDG_DATA_HOME": str(self.home / "data")}):
            run.history_role_tokens("r1", "reviewer", out, cfg=cfg, model="spark")
            run.history_role_tokens("r1", "executor", out, cfg=cfg, model="opus")
        self.assertEqual(history.get("r1")["reviewer_tokens"], 850)
        self.assertIsNone(history.get("r1")["executor_tokens"])

    def test_memory_estimate_feeds_slot_requirement(self):
        now = time.time()
        for n, rss in enumerate((100, 200, 300, 400, 500)):
            history.start_run(str(n), repo="project", started_at=now - 10)
            history.finish_run(str(n), started_at=now - 10, finished_at=now,
                               peak_rss_mb=rss)
        self.assertEqual(history.estimate_memory_mb("project"), 500)
        self.assertEqual(history.memory_requirement("project", 100), 600)

    def test_picker_history_only_reorders_close_budgets_with_five_runs(self):
        entry = {"harness": "x", "model": "x", "effort": "x", "meter": None}
        cfg = {"tiers": {"A": ["slow"], "B": ["slow", "fast"]}, "models": {
            "slow": {**entry, "provider": "p"}, "fast": {**entry, "provider": "q"}},
            "providers": {"p": {}, "q": {}}}
        with patch.object(usage, "model_exhausted", return_value=(False, None)), \
                patch.object(usage, "model_pace", return_value=(None, "provider meters")), \
                patch.object(usage, "model_budget", side_effect=lambda _c, name, _p, _n=None:
                             (1.0 if name == "slow" else .95, None)), \
                patch.object(history, "role_stats", side_effect=lambda _r, _role, name:
                             (90, 5, 60) if name == "fast" else (50, 5, 120)):
            self.assertEqual(usage.pick_order(cfg, {"p": {}, "q": {}}, ["slow", "fast"], repo="project"),
                             ["fast", "slow"])

    def test_picker_history_keeps_budget_gap_and_sparse_models_in_place(self):
        entry = {"harness": "x", "model": "x", "effort": "x", "meter": None}
        cfg = {"tiers": {"A": ["slow"], "B": ["slow", "fast"]}, "models": {
            "slow": {**entry, "provider": "p"}, "fast": {**entry, "provider": "q"}},
            "providers": {"p": {}, "q": {}}}
        with patch.object(usage, "model_exhausted", return_value=(False, None)), \
                patch.object(usage, "model_pace", return_value=(None, "provider meters")), \
                patch.object(usage, "model_budget", side_effect=lambda _c, name, _p, _n=None:
                             (1.0 if name == "slow" else .9, None)), \
                patch.object(history, "role_stats", return_value=(100, 4, 60)):
            self.assertEqual(usage.pick_order(cfg, {"p": {}, "q": {}}, ["slow", "fast"],
                                              repo="project"), ["slow", "fast"])
        with patch.object(usage, "model_exhausted", return_value=(False, None)), \
                patch.object(usage, "model_pace", return_value=(None, "provider meters")), \
                patch.object(usage, "model_budget", side_effect=lambda _c, name, _p, _n=None:
                             (1.0 if name == "slow" else .8, None)), \
                patch.object(history, "role_stats", return_value=(100, 10, 60)):
            self.assertEqual(usage.pick_order(cfg, {"p": {}, "q": {}}, ["slow", "fast"],
                                              repo="project"), ["slow", "fast"])

    def test_picker_history_ties_break_on_median_seconds(self):
        entry = {"harness": "x", "model": "x", "effort": "x", "meter": None}
        cfg = {"tiers": {"A": ["slow"], "B": ["slow", "fast"]}, "models": {
            "slow": {**entry, "provider": "p"}, "fast": {**entry, "provider": "q"}},
            "providers": {"p": {}, "q": {}}}
        stats = {"slow": (80, 5, 120), "fast": (80, 5, 30)}
        with patch.object(usage, "model_exhausted", return_value=(False, None)), \
                patch.object(usage, "model_pace", return_value=(None, "provider meters")), \
                patch.object(usage, "model_budget", return_value=(1.0, None)), \
                patch.object(history, "role_stats", side_effect=lambda _r, _role, name: stats[name]):
            self.assertEqual(usage.pick_order(cfg, {"p": {}, "q": {}}, ["slow", "fast"],
                                              repo="project"), ["fast", "slow"])

    def test_usage_render_prints_history_line(self):
        history.start_run("r1", repo="project", executor="opus", started_at=1)
        history.finish_run("r1", started_at=1, finished_at=61, verdict="PASS",
                           final_state="pass", executor="opus")
        with patch.object(usage, "rows", return_value=[]), \
                patch.object(usage, "review_pair", return_value=None):
            rendered = usage.render({}, {}, ["opus"], repo="project")
        self.assertIn("opus: executor: 100% over 1 runs", rendered)

    def test_run_status_json_carries_history_fields(self):
        runs = self.home / "runs"
        runs.mkdir()
        directory = runs / "r1"
        directory.mkdir()
        (directory / "run.json").write_text(json.dumps({"run_id": "r1", "state": "pass",
            "verdict": "PASS", "title": "done", "started_at": 1, "finished_at": 2,
            "rounds": 1, "round_summaries": [], "repo": "/tmp/project"}))
        with patch.object(config, "RUNS", runs), redirect_stdout(io.StringIO()) as out:
            history.start_run("r1", repo="project", started_at=1)
            history.finish_run("r1", repo="project", started_at=1, finished_at=2,
                               final_state="pass", verdict="PASS")
            self.assertEqual(run.cmd_status(["--json"]), 0)
        self.assertEqual(json.loads(out.getvalue())[0]["final_state"], "pass")

    def test_event_tokens_prefers_final_usage_and_ignores_content_numbers(self):
        events = self.home / "events.jsonl"
        events.write_text("\n".join((
            json.dumps({"type": "message", "usage": {"input_tokens": 100,
                                                         "output_tokens": 20}}),
            json.dumps({"type": "tool", "arguments": {"total_tokens": 999}}),
            json.dumps({"type": "result", "usage": {"input_tokens": 400,
                                                        "output_tokens": 60}}),
        )))
        self.assertEqual(history.event_tokens(events), 460)

    def test_history_role_tokens_sums_retry_event_logs(self):
        history.start_run("r1")
        first = self.home / "executor"
        retry = self.home / "executor-retry1"
        first.mkdir()
        retry.mkdir()
        for directory, tokens in ((first, 100), (retry, 50)):
            (directory / "events.jsonl").write_text(
                json.dumps({"type": "result", "total_token_usage": {"tokens": tokens}}) + "\n")
        run.history_role_tokens("r1", "executor", first)
        self.assertEqual(history.get("r1")["executor_tokens"], 150)


if __name__ == "__main__":
    unittest.main()
