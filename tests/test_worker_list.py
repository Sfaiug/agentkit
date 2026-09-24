"""The session's worker list binds every role of a run's picks.

Entirely offline. Usage providers are fake dicts, worker turns are fake callables, the
reset policy and the exhausted mark are fakes of their real contract, and no real
adapter, pid or model call appears anywhere in here. What is pinned is that a run picks
its executor, its reviewer, every handover and every fixer only from the `workers` list
its session held at launch -- never a wider list from the process's own seat, never one
the session record grew later -- parks `exhausted` with the reason when that list holds
nobody eligible, and re-picks both roles by budget on a handover so the cheapest legal
pair runs.
"""

from contextlib import ExitStack, contextmanager, redirect_stderr, redirect_stdout
import io
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, notify, run, usage, watch


class WorkerList(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".worker-list-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        # Fake turns have no children: a refusal must never sweep the hosting run's
        # inherited marker, and parking must never stop a real scope.
        self.stack.enter_context(patch.object(run.worker, "kill_marked", return_value=True))
        self.stack.enter_context(patch.object(run.orch, "stop_scope"))
        for key in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, key, self.root / key.lower()))
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "AGENTKIT_SESSION": "", "AGENTKIT_RUN_DIR": "",
            "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "", "AK_RUN_DEPTH": "0",
            "AK_MAX_RUNS": "0",
            "AGENTKIT_DISCORD_WEBHOOK": "off", "PYTHONDONTWRITEBYTECODE": "1"}))
        # the park test drives a whole run: what the host reads must not decide whether
        # its launch is admitted, or a loaded machine parks the test instead of the run
        self.stack.enter_context(patch.object(run, "host_readings", return_value={
            "free_mb": 4096, "mem_total_mb": 16384, "load": 1, "cpus": 8,
            "unit_memory_current_mb": 100, "unit_memory_high_mb": 1000}))
        # the process doing a pick may speak for a wider seat than the run's own list
        self.wide = {"name": "wide", "orchestrator": "seat",
                     "workers": ["alpha", "beta", "gamma", "delta"]}
        self.stack.enter_context(patch.object(config, "active_session", return_value=self.wide))
        # what each harness says when a pick asks whether it can run: nothing, unless a
        # test logs one out; no real adapter is ever asked from here
        self.why = {}
        self.stack.enter_context(patch.object(usage, "harness_unready",
                                              side_effect=lambda harness: self.why.get(harness)))
        config.ensure_dirs()
        self.cfg = {"defaults": {"orchestrator": "seat",
                                 "workers": ["alpha", "beta", "gamma", "delta"]},
                    "models": {}, "providers": {"a": {}, "b": {}, "c": {}}}
        for name, provider in (("seat", "a"), ("alpha", "a"), ("beta", "b"),
                               ("gamma", "b"), ("delta", "c")):
            self.cfg["models"][name] = {"harness": "claude", "model": name,
                                        "effort": "high", "provider": provider}
        self.now = time.time()
        self.logs = []

    def providers(self, **used):
        def meter(provider):
            spent = used.get(provider, 10)
            return {"name": "weekly", "used": spent, "pace": spent - 50, "elapsed": 50,
                    "window_secs": 604800, "resets_at": self.now + 302400}
        return {name: {"meters": [meter(name)], "resets": 0} for name in self.cfg["providers"]}

    def loop(self, executor, reviewer, workers):
        directory = self.root / "run"
        directory.mkdir(exist_ok=True)
        workspace = self.root / "work"
        workspace.mkdir(exist_ok=True)
        state = {"run_id": "fixture", "state": "running", "verdict": None,
                 "executor": executor, "reviewer": reviewer, "repo": None,
                 "scratch": True, "worktree": str(workspace), "base": None,
                 "rounds": 2, "round_summaries": [], "findings": "", "workers": list(workers)}
        lp = run.Loop(self.cfg, directory, state, {}, self.logs.append, workspace,
                      "Fix the work.", [], "Fixture", [])
        lp.rnd = 1
        lp.round_dir.mkdir(exist_ok=True)
        return lp

    def turn(self, answers):
        """A fake worker.call: `answers` maps a model to its (code, summary, session)."""
        calls = []

        def fake(cfg, name, body, workspace, out_dir, role, session, env=None, limit=None):
            calls.append(name)
            Path(out_dir).mkdir(parents=True, exist_ok=True)
            return answers.get(name, (0, "## Summary\nDone.", f"s-{name}", False))
        return calls, fake

    @contextmanager
    def refused(self, providers):
        """The fake usage layer beside a refusal: no probes, no reset, a mark of its own."""
        with patch.object(usage, "collect", return_value=providers), \
                patch.object(usage, "replenish", return_value=(False, 0.0)), \
                patch.object(usage, "mark_exhausted", return_value=self.now + 3600):
            yield

    def test_the_launch_list_survives_a_session_record_change(self):
        # the record can grow while the run lives; what launch recorded is what binds
        state = {"workers": ["alpha", "gamma"], "launched_session": "wide"}
        with patch.object(config, "load_session",
                          return_value={"workers": ["alpha", "beta", "gamma", "delta"]}):
            self.assertEqual(run.run_workers(self.cfg, state), ["alpha", "gamma"])

    def lagging_fable(self):
        self.cfg["models"]["fable"] = {**self.cfg["models"]["seat"], "model": "fable",
                                        "meter": "weekly_scoped"}
        self.cfg["defaults"]["orchestrator"] = "fable"
        providers = self.providers(a=80, b=50, c=55)
        shared = providers["a"]["meters"][0]
        shared["name"] = "weekly_all"
        providers["a"]["meters"].append({**shared, "name": "weekly_scoped", "used": 53})
        return providers

    def test_lagging_fable_omitted_is_never_picked(self):
        providers = self.lagging_fable()
        workers = ["alpha", "beta", "delta"]
        session = {"name": "fable-seat", "orchestrator": "fable", "workers": workers}
        with patch.object(config, "active_session", return_value=session):
            for bound in (None, workers):
                with self.subTest(bound=bound):
                    for role in ("executor", "reviewer"):
                        self.assertNotIn("fable", usage.pick_order(self.cfg, providers, bound,
                                                                  role=role))
                    self.assertEqual(run.pick_models(self.cfg, providers, None, None,
                                                     self.logs.append, workers=bound),
                                     ("beta", "delta"))
            # A wider current seat cannot admit a model the launch receipt omitted,
            # even as an explicit executor on resume after its preference closes.
            session["workers"] = [*workers, "fable"]
            for resuming in (False, True):
                for executor, reviewer in (("fable", "beta"), ("beta", "fable")):
                    with self.assertRaisesRegex(config.Error, "not a worker"):
                        run.pick_models(self.cfg, providers, executor, reviewer,
                                        self.logs.append, workers=workers, resuming=resuming)
            lp = self.loop("beta", "delta", workers)
            with patch.object(run, "collect_usage", return_value=providers):
                self.assertEqual(run.hand_executor(lp, "ran dry", "refused", set()), "delta")
            self.assertEqual(lp.reviewer, "alpha")

    def test_lagging_fable_listed_is_picked(self):
        providers = self.lagging_fable()
        workers = ["alpha", "beta", "delta", "fable"]
        session = {"name": "fable-seat", "orchestrator": "fable", "workers": workers}
        with patch.object(config, "active_session", return_value=session):
            for bound in (None, workers):
                with self.subTest(bound=bound):
                    self.assertEqual(run.pick_models(self.cfg, providers, None, None,
                                                     self.logs.append, workers=bound),
                                     ("fable", "beta"))

    def test_status_and_log_name_the_bound_workers(self):
        lp = self.loop("alpha", "gamma", ["alpha", "gamma"])
        run.save_state(lp.run_dir, lp.state)
        (lp.run_dir / "task.md").write_text(
            "---\nrepo: none\nrounds: 1\n---\n# Fixture\n\n## Done when\n```bash\ntrue\n```\n")
        opts = {"--review-pr": None, "--no-merge": True, "--no-worktree": True}
        with redirect_stdout(io.StringIO()):
            run.preflight(lp.run_dir, opts, run.logger(lp.run_dir, True))
        self.assertIn("workers: alpha, gamma", (lp.run_dir / "log.txt").read_text())
        self.assertIn("  workers: alpha, gamma", run.status_details(lp.run_dir, lp.state))

    def test_a_handover_never_leaves_the_workers_list(self):
        # delta tops every budget and sits in this process's session, but the run's own
        # list left it out: the stalled turn's handover lands inside the list all the same
        lp = self.loop("alpha", "gamma", ["alpha", "gamma", "beta"])
        state = {**lp.state, "review_session": "saved-review"}
        with patch.object(run, "collect_usage", return_value=self.providers(a=100, c=0)), \
                redirect_stderr(io.StringIO()):
            self.assertEqual(run.handover_executor(state, self.cfg, "stalled"), "gamma")
        self.assertIn(state["executor"], ["alpha", "gamma", "beta"])
        self.assertNotEqual(state["executor"], "delta")
        self.assertEqual((state["reviewer"], state["review_session"]), ("beta", None))
        run.review_providers(self.cfg, state["executor"], state["reviewer"])

    def test_a_fixer_never_leaves_the_workers_list(self):
        # the fixer's turn refuses and hands over mid-fix: the model that finishes the
        # fix is the cheapest in the list, never delta from outside it
        lp = self.loop("alpha", "gamma", ["alpha", "gamma", "beta"])
        calls, fake = self.turn({"alpha": (1, "usage limit reached", "s-alpha", False)})
        bodies = {}

        def remember(cfg, name, body, workspace, out_dir, role, session, env=None, limit=None):
            bodies[name] = body
            return fake(cfg, name, body, workspace, out_dir, role, session, env=env, limit=limit)

        with patch.object(run.worker, "call", side_effect=remember), \
                self.refused(self.providers(c=0)), \
                patch.object(run.time, "sleep",
                             side_effect=AssertionError("quota waits on nothing")), \
                redirect_stderr(io.StringIO()):
            self.assertEqual(run.execute(lp, "fixer", "Fix every finding.", "fixer"),
                             "## Summary\nDone.")
        self.assertEqual(calls, ["alpha", "gamma"])
        self.assertEqual(lp.executor, "gamma")
        self.assertIn("Another model started this round", bodies["gamma"])
        self.assertIn("Fix every finding.", bodies["gamma"])

    def test_a_fixer_never_hands_over_to_a_harness_it_cannot_run(self):
        # delta tops every budget, but its harness is logged out: the fix goes on with the
        # cheapest model that can run, and delta is given no role at all
        lp = self.loop("alpha", "gamma", ["alpha", "gamma", "beta", "delta"])
        calls, fake = self.turn({"alpha": (1, "usage limit reached", "s-alpha", False)})
        self.cfg["models"]["delta"]["harness"] = "codex"
        self.why["codex"] = "codex is not logged in"
        with patch.object(run.worker, "call", side_effect=fake), \
                self.refused(usage.Readings(self.providers(c=0))), \
                patch.object(run.time, "sleep",
                             side_effect=AssertionError("quota waits on nothing")), \
                redirect_stderr(io.StringIO()):
            self.assertEqual(run.execute(lp, "fixer", "Fix every finding.", "fixer"),
                             "## Summary\nDone.")
        self.assertEqual(calls, ["alpha", "gamma"])
        self.assertEqual((lp.executor, lp.reviewer), ("gamma", "beta"))
        self.assertEqual([line for line in self.logs if line.startswith("skipped")],
                         ["skipped delta: codex is not logged in"])

    def test_a_launch_its_skipped_harnesses_leave_without_a_pair_is_refused(self):
        # beta's harness is logged out, so alpha is alone and may not review itself: the
        # launch says so in one sentence and ends, rather than parking for a window
        run_dir = self.root / "refused"
        run_dir.mkdir()
        (run_dir / "task.md").write_text(
            "---\nrepo: none\nrounds: 1\n---\n# Fixture\n\n## Done when\n```bash\ntrue\n```\n")
        (run_dir / "log.txt").touch()
        run.save_state(run_dir, {"run_id": run_dir.name, "workers": ["alpha", "beta"]})
        self.cfg["models"]["beta"]["harness"] = "codex"
        self.why["codex"] = "codex is not logged in"
        opts = {"--rounds": None, "--exec": None, "--review": None, "--review-pr": None,
                "--no-merge": True, "--no-worktree": True, "--bg": False}
        refusal = ("no two of the workers alpha, beta make an allowed executor and reviewer "
                   "(beta: codex is not logged in); log in to another harness or add "
                   "another model to the workers")
        with patch.object(run.worker, "call", side_effect=AssertionError("no turn")), \
                self.refused(usage.Readings(self.providers())), \
                patch.object(notify, "shaped", return_value=0), \
                redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
            with self.assertRaises(config.Error) as refused:
                run.drive(self.cfg, run_dir, opts, run.logger(run_dir, True))
        self.assertEqual(str(refused.exception), refusal)
        saved = run.read_state(run_dir)
        self.assertEqual((saved["state"], saved["error"]), ("error", refusal))
        self.assertNotIn("quota_dry", saved)
        self.assertIn("skipped beta: codex is not logged in", (run_dir / "log.txt").read_text())

    def test_a_background_launch_with_no_allowed_pair_is_refused_before_its_child(self):
        # every harness but alpha's is logged out: the parent says so in one sentence and
        # ends the run it prepared, and no background child is ever started
        task = self.root / "bg.md"
        task.write_text("---\nrepo: none\nrounds: 1\n---\n# Background fixture\n\n"
                        "## Done when\n```bash\ntrue\n```\n")
        for name in ("beta", "gamma", "delta"):
            self.cfg["models"][name]["harness"] = "codex"
        self.why["codex"] = "codex is not logged in"
        with patch.object(config, "load", return_value=self.cfg), \
                patch.object(usage, "collect", return_value=usage.Readings(self.providers())), \
                patch.object(run, "spawn_bg", side_effect=AssertionError("child started")), \
                patch.object(notify, "shaped", return_value=0), \
                redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
            with self.assertRaises(config.Error) as refused:
                run.main([str(task), "--bg"])
        self.assertTrue(str(refused.exception).startswith(
            "no two of the workers alpha, beta, gamma, delta make an allowed executor and "
            "reviewer (beta: codex is not logged in;"), refused.exception)
        (run_dir,) = run.run_dirs()
        saved = run.read_state(run_dir)
        self.assertEqual((saved["state"], saved["error"]), ("error", str(refused.exception)))
        self.assertIn("skipped beta: codex is not logged in", (run_dir / "log.txt").read_text())

    def test_a_resume_hands_a_saved_executor_that_cannot_run_within_its_provider(self):
        # gamma's harness is logged out, and only its harness: beta, on the same provider
        # and another harness, is the cheapest model left and takes the work
        self.cfg["models"]["gamma"]["harness"] = "codex"
        self.why["codex"] = "codex is not logged in"
        run_dir = self.root / "resumed"
        run_dir.mkdir()
        (run_dir / "task.md").write_text(
            "---\nrepo: none\nrounds: 1\n---\n# Fixture\n\n## Done when\n```bash\ntrue\n```\n")
        (run_dir / "log.txt").touch()
        workspace = self.root / "resume-work"
        workspace.mkdir()
        state = {"run_id": run_dir.name, "title": "Fixture", "state": "interrupted",
                 "verdict": None, "executor": "gamma", "reviewer": "alpha", "rounds": 1,
                 "round_summaries": [], "repo": None, "worktree": str(workspace),
                 "branch": None, "base": None, "base_sha": None, "scratch": True,
                 "no_merge": True, "findings": "", "workers": ["alpha", "beta", "gamma"]}
        run.save_state(run_dir, state)
        calls = []

        def fake(cfg, name, body, workspace, out_dir, role, session, env=None, limit=None):
            calls.append(name)
            Path(out_dir).mkdir(parents=True, exist_ok=True)
            text = ("VERDICT: PASS\n\n## Findings\n- none\n" if role.startswith("reviewer")
                    else "## Summary\nDone.")
            return 0, text, f"s-{name}", False
        opts = {"--rounds": None, "--exec": None, "--review": None, "--review-pr": None,
                "--no-merge": True, "--no-worktree": True, "--bg": False}
        with patch.object(run.worker, "call", side_effect=fake), \
                self.refused(usage.Readings(self.providers(b=5))), \
                patch.object(notify, "shaped", return_value=0), \
                redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
            run.drive(self.cfg, run_dir, opts, run.logger(run_dir, True), prior=state)
        saved = run.read_state(run_dir)
        self.assertEqual((saved["executor"], saved["reviewer"]), ("beta", "alpha"))
        self.assertEqual(calls[0], "beta")
        self.assertIn("saved executor gamma cannot run: codex is not logged in",
                      (run_dir / "log.txt").read_text())

    def test_the_tick_never_hands_a_waiting_run_to_a_harness_that_cannot_run(self):
        # delta tops every budget, but its harness is logged out: the tick's resume of a run
        # waiting on a window picks the provider whose models can run
        self.cfg["models"]["delta"]["harness"] = "codex"
        self.why["codex"] = "codex is not logged in"
        run_dir = config.RUNS / "20260924-0000-waiting"
        run_dir.mkdir(parents=True)
        workspace = self.root / "waiting-work"
        workspace.mkdir()
        run.save_state(run_dir, {"run_id": run_dir.name, "state": "exhausted",
                                 "quota_dry": True, "executor": "alpha", "reviewer": "gamma",
                                 "worktree": str(workspace),
                                 "workers": ["alpha", "beta", "gamma", "delta"]})
        logs = []
        watch.resume_exhausted(self.cfg, usage.Readings(self.providers(a=100, c=0)),
                               dry_run=True, log=logs.append, now=self.now)
        self.assertIn(f"would resume {run_dir.name}: b window refilled", logs)
        self.assertFalse((run_dir / "log.txt").exists())
        # the pick that resumes it tells the run's own log what it skipped, once: the next
        # tick, still inside the resume's throttle, picks nothing and says nothing
        with patch.object(run, "spawn_bg") as spawn:
            for _ in range(2):
                watch.resume_exhausted(self.cfg, usage.Readings(self.providers(a=100, c=0)),
                                       log=logs.append, now=self.now)
        spawn.assert_called_once()
        lines = (run_dir / "log.txt").read_text().splitlines()
        self.assertEqual([line.split("] ", 1)[1] for line in lines],
                         ["skipped delta: codex is not logged in"])

    def test_a_tick_no_run_waits_on_asks_no_harness(self):
        # asking runs each harness's `auth`: a pass with nothing to pick asks nobody
        watch.resume_exhausted(self.cfg, usage.Readings(self.providers()),
                               log=self.logs.append, now=self.now)
        usage.harness_unready.assert_not_called()

    def test_a_stall_handover_logs_its_skips_in_the_run(self):
        # a stalled worker turn is handed over by the tick; delta, logged out, tops every
        # budget, and the run's own log -- not the tick's -- says it was passed over
        self.cfg["models"]["delta"]["harness"] = "codex"
        self.why["codex"] = "codex is not logged in"
        run_dir = config.RUNS / "20260924-0000-stalled"
        run_dir.mkdir(parents=True)
        run.save_state(run_dir, {"run_id": run_dir.name, "state": "running", "pid": 4242,
                                 "executor": "alpha", "reviewer": "gamma", "round_summaries": [],
                                 "stalls": [{"time": 0, "round": 1, "step": "executor turn",
                                             "action": "killed step"}],
                                 "workers": ["alpha", "beta", "gamma", "delta"]})
        logs = []
        with patch.object(usage, "collect",
                          return_value=usage.Readings(self.providers(a=50, c=0))), \
                patch.object(run, "process_active", return_value=True), \
                patch.object(watch, "frozen_cgroup", return_value=None), \
                patch.object(watch, "stall_clock", return_value=0), \
                patch.object(watch, "step_for_run",
                             return_value=("worker", "executor turn", 4243, ["claude"])), \
                patch.object(watch, "stop_run_scope", return_value=True), \
                patch.object(watch, "launch_resume") as resume:
            watch.recover_runs(self.cfg, log=logs.append, now=self.now)
        resume.assert_called_once()
        self.assertEqual(run.read_state(run_dir)["executor"], "beta")
        text = (run_dir / "log.txt").read_text()
        self.assertEqual(text.count("skipped delta: codex is not logged in"), 1)
        self.assertFalse([line for line in logs if line.startswith("skipped")])

    def test_an_empty_eligible_list_parks_exhausted(self):
        # the run's list holds only one provider's models and that provider refuses: the
        # run parks exhausted with the reason and borrows nobody from the wider seat
        self.cfg["models"]["beta"]["provider"] = "a"
        run_dir = self.root / "parked"
        run_dir.mkdir()
        (run_dir / "task.md").write_text(
            "---\nrepo: none\nrounds: 1\n---\n# Fixture\n\n## Done when\n```bash\ntrue\n```\n")
        (run_dir / "log.txt").touch()
        workspace = self.root / "park-work"
        workspace.mkdir()
        state = {"run_id": run_dir.name, "title": "Fixture", "state": "exhausted",
                 "verdict": None, "executor": "alpha", "reviewer": "beta", "rounds": 1,
                 "round_summaries": [], "repo": None, "worktree": str(workspace),
                 "branch": None, "base": None, "base_sha": None, "scratch": True,
                 "no_merge": True, "findings": "", "workers": ["alpha", "beta"],
                 "error": "every provider is out of budget"}
        run.save_state(run_dir, state)
        calls, fake = self.turn({"alpha": (1, "usage limit reached", "s", False),
                                 "beta": (1, "usage limit reached", "s", False)})
        sent = []
        opts = {"--rounds": None, "--exec": None, "--review": None, "--review-pr": None,
                "--no-merge": True, "--no-worktree": True, "--bg": False}
        with patch.object(run.worker, "call", side_effect=fake), \
                self.refused(self.providers()), \
                patch.object(run.time, "sleep"), \
                patch.object(notify, "shaped",
                             side_effect=lambda *a, **k: sent.append((a, k)) or 0), \
                redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
            self.assertEqual(run.drive(self.cfg, run_dir, opts, run.logger(run_dir, False),
                                       prior=state), 1)
        saved = run.read_state(run_dir)
        self.assertEqual(saved["state"], "exhausted")
        self.assertIn("no other provider can execute", saved["error"])
        self.assertTrue(saved["quota_dry"])
        self.assertEqual(calls, ["alpha"])
        self.assertEqual(sent, [])

    def test_a_handover_repicks_the_pair_by_budget(self):
        # the 2026-09-22 repro in miniature: a refusal with the reviewer's own model the
        # cheaper executor. Keeping the reviewer would force the dearer executor; both
        # roles are re-picked instead, so the cheapest legal pair runs
        lp = self.loop("alpha", "gamma", ["alpha", "gamma", "delta"])
        lp.review_sid = "saved-review"
        with patch.object(run, "collect_usage", return_value=self.providers(c=30)), \
                redirect_stderr(io.StringIO()):
            self.assertEqual(run.hand_executor(lp, "ran dry", "refused", set()), "gamma")
        self.assertEqual((lp.executor, lp.reviewer), ("gamma", "delta"))
        self.assertIsNone(lp.review_sid)
        self.assertTrue(any("reviewer re-picked for executor gamma: gamma -> delta"
                            in line for line in self.logs), self.logs)


if __name__ == "__main__":
    unittest.main()
