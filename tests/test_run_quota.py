"""Quota behavior on this tree: dry providers exclude, stop, hand over, resume.

Entirely offline. Usage data is fake, worker turns and launches are faked, and no
real adapter, reset or model call is made anywhere in here. What is pinned is what
the code actually does: a gate meter at 100% removes the model from the pick order,
a dying harness is retried twice and then given up on, a dry executor hands over to
another provider, an `Exhausted` stop ends the run `exhausted` (never `error`), and
an exhausted run is resumable through `ak run resume`.

The v5i half below drives the same roads with fake adapter scripts answering from a
plan file: a worker whose provider runs dry gets a reset or another provider, never
an error.
"""

from contextlib import ExitStack, redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, notify, run, usage, watch

WEEK = 604800
TASK = "---\nrepo: none\nrounds: 1\n---\n# Quota fixture\n\n## Done when\n```bash\ntest -f deliverable\n```\n"


def meter(name, used, resets_at, window=WEEK):
    return {"name": name, "used": used, "resets_at": resets_at, "window_secs": window,
            "pace": None}


METERED = ("anthropic", "openai", "meta")


class Clock:
    """`time` as run.py sees it, with only run.py's own sleeps going to `sleep`.

    Patching `time.sleep` itself would also record `subprocess`'s wait-polling under
    every timed git, gh or adapter call -- hundreds of tiny sleeps whenever a child
    outlives its first waitpid -- and the exact lists below would fail by host load.
    """

    def __init__(self, sleep):
        self.sleep = sleep

    def __getattr__(self, name):
        return getattr(time, name)


def scope_defaults(cfg):
    """Quota mechanics are metered-provider mechanics: every scenario below answers for
    three companies and a Fable seat, so its default workers are scoped to them and the
    meterless harnesses stay out."""
    cfg["defaults"] = {"orchestrator": "fable",
                       "workers": [m for m in config.offered(cfg) if m != "fable"
                                   and cfg["models"][m]["provider"] in METERED]}
    return cfg


class Quota(unittest.TestCase):
    """Patched home, the shipped default config, fake meters everywhere else."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".run-quota-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for key in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, key, self.root / key.lower()))
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "AGENTKIT_SESSION": "", "AGENTKIT_RUN_DIR": "",
            "AGENTKIT_DISCORD_WEBHOOK": "off", "AGENTKIT_TMUX_SOCKET": "agentkit-test",
            "TMUX_TMPDIR": str(self.root), "PYTHONDONTWRITEBYTECODE": "1",
            # top-level runs, whatever run the suite itself is nested in: a nested
            # run's depth would claim a slot without the steady-readings poll pinned below
            "AK_RUN_ROLE": "orchestrator", "AK_RUN_DEPTH": "0"}))
        self.stack.enter_context(patch.object(run, "host_readings", return_value={
            "free_mb": 4096, "mem_total_mb": 16384, "load": 1, "cpus": 8,
            "unit_memory_current_mb": 100, "unit_memory_high_mb": 1000}))
        self.stack.enter_context(patch.object(run, "SLOT_POLL", .01))
        config.ensure_dirs()
        self.cfg = scope_defaults(config.load())
        self.now = time.time()

    def providers(self, openai_used=10, anthropic_used=100, meta_used=100):
        return {
            "anthropic": {"meters": [meter("weekly_all", anthropic_used, self.now + WEEK),
                                     meter("weekly_scoped", anthropic_used, self.now + WEEK)]},
            "openai": {"meters": [meter("weekly", openai_used, self.now + WEEK)]},
            "meta": {"meters": [meter("weekly", meta_used, self.now + WEEK)]},
        }

    def test_quota_gate_meter_at_100_excludes_the_model(self):
        providers = self.providers()
        self.assertTrue(usage.model_exhausted(self.cfg, "opus", providers)[0])
        self.assertTrue(usage.model_exhausted(self.cfg, "fable", providers)[0])
        self.assertTrue(usage.model_exhausted(self.cfg, "spark", providers)[0])
        order = usage.pick_order(self.cfg, providers, quiet=True)
        self.assertEqual(order, ["astra"])

    def test_quota_model_below_100_stays_eligible_with_budget(self):
        providers = self.providers(openai_used=40, anthropic_used=100, meta_used=100)
        self.assertFalse(usage.model_exhausted(self.cfg, "astra", providers)[0])
        budget, reason = usage.model_budget(self.cfg, "astra", providers, self.now)
        self.assertIsNone(reason)
        self.assertGreater(budget, 0)
        self.assertIn("astra", usage.pick_order(self.cfg, providers, quiet=True))

    def test_quota_transient_refusal_is_retried_then_answered(self):
        calls, sleeps, logs = [], [], []
        # transient means the transport died, not the window: neither text may carry
        # a [stall] quotas word, which the quota rule reads as a refusal instead.
        answers = [(1, "API Error: upstream connect failed", "s1", False),
                   (1, "HTTP 503 Service Unavailable", "s1", False),
                   (0, "## Summary\nDone.", "s1", False)]
        with patch.object(run.worker, "call",
                          side_effect=lambda *a, **k: calls.append(a) or answers[len(calls) - 1]), \
                patch.object(run, "time", Clock(sleeps.append)):
            code, text, session, dead = run.call_retrying(
                self.cfg, "astra", "body", self.root, self.root / "round-1" / "executor", "executor",
                None, logs.append)
        self.assertEqual((code, dead, session), (0, False, "s1"))
        self.assertIn("Done.", text)
        self.assertEqual(len(calls), 3)
        self.assertEqual(sleeps, [60, 300])
        self.assertTrue(any("attempt 1" in line for line in logs))

    def test_quota_persistent_outage_keeps_resuming_with_growing_waits(self):
        calls, sleeps, logs = [], [], []
        answers = [(1, "", None, False)] * 6 + [(0, "## Summary\nDone.", "s1", False)]
        with patch.object(run.worker, "call",
                          side_effect=lambda *a, **k: calls.append(a) or answers[len(calls) - 1]), \
                patch.object(run, "time", Clock(sleeps.append)):
            code, text, session, dead = run.call_retrying(
                self.cfg, "astra", "body", self.root, self.root / "round-1" / "executor", "executor",
                None, logs.append)
        self.assertEqual((code, dead, session), (0, False, "s1"))
        self.assertEqual(len(calls), 7)
        self.assertEqual(sleeps, [60, 300, 900, 1800, 3600, 3600])
        self.assertFalse(any("giving up" in line for line in logs), logs)

    def test_quota_handover_moves_a_dry_executor_to_another_provider(self):
        state = {"executor": "opus", "reviewer": "spark"}
        # meta stays funded: the handover needs a legal pair to land on, not just a model
        with patch.object(usage, "collect", return_value=self.providers(meta_used=50)), \
                redirect_stderr(io.StringIO()):
            self.assertEqual(run.handover_executor(state, self.cfg, "dry"), "astra")
        self.assertEqual(state["executor"], "astra")
        self.assertIsNone(state["exec_session"])
        self.assertEqual(state["executor_history"][0]["from"], "opus")
        self.assertEqual(state["executor_history"][0]["to"], "astra")

    def test_quota_handover_with_nothing_eligible_returns_none(self):
        providers = self.providers(openai_used=100, anthropic_used=100, meta_used=100)
        state = {"executor": "opus", "reviewer": "spark"}
        with patch.object(usage, "collect", return_value=providers), \
                redirect_stderr(io.StringIO()):
            self.assertIsNone(run.handover_executor(state, self.cfg, "dry"))
        self.assertEqual(state["executor"], "opus")
        self.assertIn("no other provider", state["executor_history"][0]["reason"])

    def receipt(self, name, scratch=True):
        run_dir = config.RUNS / name
        run_dir.mkdir(parents=True)
        (run_dir / "task.md").write_text(TASK)
        (run_dir / "log.txt").touch()
        wt = config.WORK / f"ws-{name}"
        wt.mkdir(parents=True)
        state = {"run_id": name, "title": name, "state": "exhausted", "verdict": None,
                 "executor": "astra", "reviewer": "spark", "rounds": 1, "round_summaries": [],
                 "repo": None, "worktree": str(wt), "branch": None, "base": None,
                 "base_sha": None, "scratch": scratch, "no_merge": True, "findings": "",
                 "error": "every provider is out of budget",
                 "started_at": self.now - 600, "finished_at": self.now - 60}
        run.save_state(run_dir, state)
        return run_dir, state

    def test_quota_dry_executor_hands_over_mid_round_and_answers(self):
        # a real execute(): the harness's own refusal moves the turn, which answers.
        from types import SimpleNamespace
        run_dir = config.RUNS / "20260916-1202-quota-hand"
        run_dir.mkdir(parents=True)
        wt = self.root / "wt-hand"
        wt.mkdir(parents=True)
        state = {"run_id": run_dir.name, "title": run_dir.name, "state": "running",
                 "verdict": None, "executor": "astra", "reviewer": "spark",
                 "rounds": 2, "round_summaries": [], "findings": ""}
        run.save_state(run_dir, state)
        logs = []
        lp = SimpleNamespace(cfg=self.cfg, run_dir=run_dir, state=state, wt=wt,
                             executor="astra", reviewer="spark", exec_sid=None, rnd=1,
                             turn_limit=60, log=logs.append,
                             save=lambda: run.save_state(run_dir, lp.state),
                             role=lambda role: f"{role}-scratch",
                             dir=lambda name: run_dir / "round-1" / name)
        bodies = {}
        def turn(cfg, name, body, workspace, out_dir, role, session, env=None, limit=None):
            bodies[name] = body
            if name == "astra":
                return 1, "usage limit reached", "s-astra", False
            return 0, "## Summary\nDone.", "s-opus", False
        # The handover must leave a reviewer with budget too.
        providers = self.providers(openai_used=100, anthropic_used=40, meta_used=50)
        with patch.object(run.worker, "call", side_effect=turn), \
                patch.object(usage, "collect", return_value=providers), \
                patch.object(run, "time", Clock(
                    MagicMock(side_effect=AssertionError("quota waits on nothing")))), \
                redirect_stderr(io.StringIO()):
            self.assertEqual(run.execute(lp, "executor", "Do the task.", "executor"),
                             "## Summary\nDone.")
        self.assertEqual((lp.executor, lp.exec_sid), ("opus", "s-opus"))
        self.assertIn("Another model started this round", bodies["opus"])
        self.assertIn("Do the task.", bodies["opus"])
        history = run.read_state(run_dir)["executor_history"]
        self.assertEqual([(entry["from"], entry["to"], entry["reason"]) for entry in history],
                         [("astra", "opus", "dry")])
        self.assertTrue(any("handing executor to opus" in line for line in logs), logs)

    def test_quota_refusal_through_the_loop_ends_exhausted_not_error(self):
        # the reviewer's repro: mocked quota refusals through the real drive->loop path.
        # Each harness refuses in its own manifest words; the fake makes the out dir the
        # way the real worker.call does.
        run_dir, state = self.receipt("20260916-1200-quota-end")
        providers = self.providers(openai_used=100, anthropic_used=100, meta_used=50)
        def turn(cfg, name, body, workspace, out_dir, role, session, env=None, limit=None):
            Path(out_dir).mkdir(parents=True, exist_ok=True)
            if config.model(cfg, name)["harness"] == "muse":
                return 1, "quota exhausted for muse-spark", "s", False
            return 1, "usage limit reached", "s", False
        sent, sleeps = [], []
        opts = {"--rounds": None, "--exec": None, "--review": None, "--review-pr": None,
                "--no-merge": True, "--no-worktree": True, "--bg": False}
        with patch.object(run.worker, "call", side_effect=turn), \
                patch.object(usage, "collect", return_value=providers), \
                patch.object(run, "time", Clock(sleeps.append)), \
                patch.object(notify, "shaped",
                             side_effect=lambda *a, **k: sent.append((a, k)) or 0), \
                redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
            self.assertEqual(run.drive(self.cfg, run_dir, opts, run.logger(run_dir, False),
                                       prior=state), 1)
        saved = run.read_state(run_dir)
        self.assertEqual(saved["state"], "exhausted")
        self.assertIn("ran dry", saved["error"])
        self.assertTrue(saved["quota_dry"])   # the tick may watch this one refill
        self.assertTrue((run_dir / "result.md").exists())
        self.assertEqual(sent, [])

    def test_quota_finished_run_leaves_no_mark_behind(self):
        # a quota-marked exhausted run that is resumed and passes: the finished PASS
        # carries no mark, so a later delivery retry starts clean.
        run_dir, state = self.receipt("20260916-1207-quota-pass")
        state.update(state="exhausted", error="every provider is out of budget",
                     quota_dry=True)
        run.save_state(run_dir, state)
        providers = self.providers(openai_used=40, anthropic_used=100, meta_used=50)
        def turn(cfg, name, body, workspace, out_dir, role, session, env=None, limit=None):
            Path(out_dir).mkdir(parents=True, exist_ok=True)
            if role.startswith("reviewer"):
                return 0, "VERDICT: PASS\nNo findings.", "s-review", False
            Path(workspace, "deliverable").write_text("done")
            return 0, "## Summary\nDone.", "s-exec", False
        sent, sleeps = [], []
        opts = {"--rounds": None, "--exec": None, "--review": None, "--review-pr": None,
                "--no-merge": True, "--no-worktree": True, "--bg": False}
        with patch.object(run.worker, "call", side_effect=turn), \
                patch.object(usage, "collect", return_value=providers), \
                patch.object(run, "time", Clock(sleeps.append)), \
                patch.object(notify, "shaped",
                             side_effect=lambda *a, **k: sent.append((a, k)) or 0), \
                patch.object(notify, "post", return_value=None), \
                redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
            self.assertEqual(run.drive(self.cfg, run_dir, opts, run.logger(run_dir, False),
                                       prior=state), 0)
        saved = run.read_state(run_dir)
        self.assertEqual(saved["state"], "pass")
        self.assertNotIn("quota_dry", saved)
        self.assertEqual(sent, [])
        self.assertEqual(sleeps, [run.SLOT_POLL])

    def test_quota_merge_retry_on_a_marked_pass_stops_clean(self):
        # the reviewer's repro: a PASS carrying a leftover mark whose gh call stops
        # ends exhausted without the mark, so the tick never relaunches a delivery.
        run_dir = config.RUNS / "20260916-1208-quota-merge"
        run_dir.mkdir(parents=True)
        (run_dir / "task.md").write_text(TASK)
        (run_dir / "log.txt").touch()
        wt = self.root / "wt-merge"
        wt.mkdir(parents=True)
        review = {"executor": "astra", "executor_provider": "openai", "reviewer": "spark",
                  "reviewer_provider": "meta", "returncode": 0, "verdict": "PASS",
                  "done_when": True}
        run.save_state(run_dir, {
            "run_id": run_dir.name, "title": run_dir.name, "state": "pass", "verdict": "PASS",
            "executor": "astra", "reviewer": "spark", "review": review,
            "rounds": 1, "round_summaries": [{"round": 1, "verdict": "PASS", "done_when": True,
                                              "finding_count": 0, "summary": "Done."}],
            "repo": None, "worktree": str(wt), "branch": "run-x", "base": "main",
            "base_sha": "0" * 40, "scratch": False, "no_merge": False,
            "pr": "https://github.com/o/r/pull/1", "delivery_sha": "0" * 40,
            "merge_failed": True, "merge_note": "pushing failed", "review_pending": True,
            "quota_dry": True, "findings": "",
            "started_at": self.now - 600, "finished_at": self.now - 60})
        with patch.object(run, "pr_view",
                          side_effect=config.Error("gh api stopped: timed out")), \
                patch.object(notify, "shaped", return_value=0), \
                redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
            self.assertEqual(run.cmd_merge([run_dir.name]), 1)
        saved = run.read_state(run_dir)
        self.assertEqual(saved["state"], "exhausted")
        self.assertIn("gh api stopped", saved["error"])
        self.assertNotIn("quota_dry", saved)

    def test_quota_tool_stop_ends_exhausted_without_the_quota_mark(self):
        # drive's other exhausted road: a stopped git/gh stays resumable by hand, but
        # the tick must never relaunch it by itself.
        run_dir, state = self.receipt("20260916-1204-quota-toolstop")
        with patch.object(run, "loop", side_effect=run.Stopped("git push stopped: timed out")), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(run.drive(self.cfg, run_dir, {"--rounds": None}, run.logger(
                run_dir, False), prior=state), 1)
        saved = run.read_state(run_dir)
        self.assertEqual(saved["state"], "exhausted")
        self.assertNotIn("quota_dry", saved)

    def test_quota_later_tool_stop_clears_a_stale_quota_mark(self):
        # the reviewer's repro: quota-dry once, resumed, then stopped by git. The new
        # stop is not a quota stop, so the mark must go with it -- or the tick would
        # relaunch a tool-stopped run every RESUME_EVERY for a window never spent.
        run_dir, state = self.receipt("20260916-1206-quota-stale")
        state["quota_dry"] = True
        run.save_state(run_dir, state)
        with patch.object(run, "loop", side_effect=run.Stopped("git push stopped: timed out")), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(run.drive(self.cfg, run_dir, {"--rounds": None}, run.logger(
                run_dir, False), prior=state), 1)
        saved = run.read_state(run_dir)
        self.assertEqual(saved["state"], "exhausted")
        self.assertNotIn("quota_dry", saved)

    def test_quota_handover_never_lands_on_the_reviewers_provider(self):
        # opus is live but reviews: handing the turn to it would error in review(),
        # so the round ends exhausted instead.
        from types import SimpleNamespace
        run_dir = config.RUNS / "20260916-1205-quota-reviewer"
        run_dir.mkdir(parents=True)
        wt = self.root / "wt-reviewer"
        wt.mkdir(parents=True)
        state = {"run_id": run_dir.name, "title": run_dir.name, "state": "running",
                 "verdict": None, "executor": "astra", "reviewer": "opus",
                 "rounds": 2, "round_summaries": [], "findings": ""}
        run.save_state(run_dir, state)
        logs = []
        lp = SimpleNamespace(cfg=self.cfg, run_dir=run_dir, state=state, wt=wt,
                             executor="astra", reviewer="opus", exec_sid=None, rnd=1,
                             turn_limit=60, log=logs.append,
                             save=lambda: run.save_state(run_dir, lp.state),
                             role=lambda role: f"{role}-scratch",
                             dir=lambda name: run_dir / "round-1" / name)
        def turn(cfg, name, body, workspace, out_dir, role, session, env=None, limit=None):
            return 1, "usage limit reached", "s", False
        providers = self.providers(openai_used=100, anthropic_used=40, meta_used=100)
        with patch.object(run.worker, "call", side_effect=turn), \
                patch.object(usage, "collect", return_value=providers), \
                patch.object(run, "time", Clock(
                    MagicMock(side_effect=AssertionError("quota waits on nothing")))), \
                redirect_stderr(io.StringIO()):
            with self.assertRaises(run.QuotaDry):
                run.execute(lp, "executor", "Do the task.", "executor")
        self.assertEqual(lp.executor, "astra")
        history = run.read_state(run_dir)["executor_history"]
        self.assertTrue(any(entry["reason"] == "dry (no other provider)" for entry in history),
                        history)

    def test_quota_words_must_stand_on_their_own(self):
        self.assertEqual(run.worker_dry(self.cfg, "astra", "API Error: rate limit exceeded"),
                         "rate limit")
        self.assertIsNone(run.worker_dry(self.cfg, "spark", "wrote 4294967296 bytes in 12s"))
        self.assertIsNone(run.worker_dry(self.cfg, "astra", ""))
        self.assertIsNone(run.worker_dry(self.cfg, "astra", "all green"))

    def test_quota_exhausted_run_resumes_through_the_command(self):
        run_dir, _ = self.receipt("20260916-1201-quota-resume")
        launched = []

        def fake_popen(*a, **k):
            # a launched child is a running one, and one placed in the slice leaves the mark
            # its `sh` writes before it becomes the work
            launched.append((a, k))
            marker = next((arg for arg in a[0] if arg.endswith(".launched")), None)
            if marker:
                Path(marker).write_text("12345")
            return type("Proc", (), {"pid": 12345, "poll": lambda self: None})()

        with patch.object(run.subprocess, "Popen", side_effect=fake_popen), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(run.cmd_resume([run_dir.name, "--bg"]), 0)
        self.assertEqual(len(launched), 1)
        self.assertEqual(launched[0][0][0][-3:], ["run", "resume", run_dir.name])
        saved = run.read_state(run_dir)
        self.assertEqual(saved["state"], "queued")
        self.assertEqual(saved["resume_from"], "exhausted")


class QuotaDry(unittest.TestCase):
    """One run directory, fake adapters that speak each harness's real refusal, fake meters."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".run-quota-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for key in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, key, self.root / key.lower()))
        sockets = self.root / "sockets"
        sockets.mkdir(mode=0o700)
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "AGENTKIT_SESSION": "", "AGENTKIT_RUN_DIR": "",
            "AGENTKIT_DISCORD_WEBHOOK": "off", "AGENTKIT_TMUX_SOCKET": "agentkit-test",
            "TMUX_TMPDIR": str(sockets), "PYTHONDONTWRITEBYTECODE": "1",
            "QUOTA_FIXTURE": str(self.root), "AK_RUN_DEPTH": "0"}))
        self.stack.enter_context(patch.object(run, "host_readings", return_value={
            "free_mb": 4096, "mem_total_mb": 16384, "load": 1, "cpus": 8,
            "unit_memory_current_mb": 100, "unit_memory_high_mb": 1000}))
        config.ensure_dirs()
        self.cfg = scope_defaults(config.load())
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.stack.enter_context(patch.dict(os.environ,
                                            {"PATH": f"{self.bin}:{os.environ['PATH']}"}))
        self.script(self.bin / "tmux", 'import sys\n'
                    'assert sys.argv[1:3] == ["-L", "agentkit-test"], sys.argv\nsys.exit(1)\n')
        self.stack.enter_context(patch.object(run, "gh", side_effect=AssertionError("GitHub call")))
        self.stack.enter_context(patch.object(run.notify, "shaped",
                                              side_effect=AssertionError("notification")))
        self.sleep = MagicMock()
        self.stack.enter_context(patch.object(run, "time", Clock(self.sleep)))
        self.now = time.mktime(time.strptime("2026-09-15 07:00", "%Y-%m-%d %H:%M"))
        self.stack.enter_context(patch.object(usage.time, "time", side_effect=lambda: self.now))

        # --- the fake usage layer: meters, the reset policy and the exhausted mark ----------
        self.providers = self.meters()
        self.resets = {"openai": 0}
        self.replenished = []
        self.marked = []
        # the real cache-level policy, for the checks that drive it instead of the fake
        self.real_replenish, self.real_collect = usage.replenish, usage.collect
        self.real_mark = usage.mark_exhausted
        self.stack.enter_context(patch.object(usage, "collect", side_effect=self.collect))
        self.stack.enter_context(patch.object(usage, "replenish", side_effect=self.replenish))
        self.stack.enter_context(patch.object(usage, "mark_exhausted", side_effect=self.mark))
        self.stack.enter_context(patch.object(config, "workers",
                                              side_effect=lambda cfg: list(self.eligible)))
        self.eligible = [*self.cfg["defaults"]["workers"], "fable"]

        # --- the fake harnesses -------------------------------------------------------------
        adapters = self.root / "adapters"
        adapters.mkdir()
        self.stack.enter_context(patch.dict(os.environ, {config.ADAPTER_DIR_ENV: str(adapters)}))
        (self.root / "models.json").write_text(json.dumps(
            {entry["model"]: name for name, entry in self.cfg["models"].items()}))
        for harness in {entry["harness"] for entry in self.cfg["models"].values()}:
            self.script(adapters / f"{harness}.sh", ADAPTER)
            # the manifests are the repository's own: signatures are read, never invented here
            (adapters / f"{harness}.toml").symlink_to(REPO / f"adapters/{harness}.toml")
        self.plan({})
        self.task = self.root / "task.md"
        self.task.write_text("---\nrepo: none\nrounds: 1\n---\n# Ran dry\n\n"
                             "## Done when\n```bash\ntest -f deliverable\n```\n")
        self.out = self.stack.enter_context(redirect_stdout(io.StringIO()))

    # --- fixture plumbing -----------------------------------------------------------------

    def script(self, path, body):
        path.write_text(f"#!{sys.executable}\n{body}")
        path.chmod(0o755)

    def plan(self, responses):
        """model -> list of {code, final, stderr, events} rows, consumed one call at a time."""
        (self.root / "plan.json").write_text(json.dumps(responses))

    def calls(self, role=None):
        path = self.root / "calls.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
        return [row for row in rows if role is None or row["role"] == role]

    def meter(self, used, window=WEEK):
        return {"name": "weekly_all", "used": used, "window_secs": window,
                "resets_at": self.now + window / 2, "elapsed": 50, "pace": used - 50,
                "exhausted": used >= 100}

    def meters(self, **used):
        return {name: {"provider": name, "resets": 0, "error": None,
                       "meters": [self.meter(used.get(name, 10))]}
                for name in self.cfg["providers"]}

    def collect(self, cfg):
        return usage._gate_flags(self.providers, self.now, cfg)

    def replenish(self, cfg, provider):
        """The real policy's contract: one credit at most, and only while the day allows."""
        self.replenished.append(provider)
        claimed = config.STATE / f"{provider}-reset.json"
        if self.resets.get(provider, 0) <= 0 or claimed.exists():
            return False, float(max(0, self.resets.get(provider, 0)))
        claimed.write_text(json.dumps({"applied_at": self.now, "outcome": "reset"}))
        self.resets[provider] -= 1
        self.providers[provider]["meters"] = [self.meter(0)]
        return True, float(self.resets[provider])

    def mark(self, cfg, provider, until=None):
        """The real contract: the time named, else the soonest window, else DRY_FOR."""
        if until is None or until <= self.now:
            ends = [m.get("resets_at") for m in self.providers[provider].get("meters") or []]
            until = min([end for end in ends if end and end > self.now],
                        default=self.now + usage.DRY_FOR)
        self.providers[provider]["exhausted_until"] = float(until)
        self.marked.append((provider, float(until)))
        return float(until)

    def launch(self, *flags):
        before = set(run.run_dirs())
        code = run.main([str(self.task), *flags])
        directory = (set(run.run_dirs()) - before).pop()
        return code, directory, run.read_state(directory)

    def repository(self):
        repo = self.root / "repo"
        repo.mkdir()
        for args in (("init", "-q", "-b", "main"), ("config", "user.email", "t@example.invalid"),
                     ("config", "user.name", "Fixture")):
            subprocess.run(["git", "-C", str(repo), *args], check=True)
        (repo / "README.md").write_text("fixture\n")
        subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-qm", "init"], check=True,
                       env={**os.environ, "GIT_AUTHOR_DATE": "@1 +0000",
                            "GIT_COMMITTER_DATE": "@1 +0000"})
        self.task.write_text(f"---\nrepo: {repo}\nbase: main\nrounds: 1\n---\n# Ran dry\n\n"
                             "## Done when\n```bash\ntest -f deliverable\n```\n")
        return repo

    def out_dir(self, name, said, prompt="You are the executor. Do the task.\n\nthe task",
                final=""):
        """One worker out dir as an adapter leaves it: the prompt, the answer, an event log."""
        directory = self.root / name
        directory.mkdir()
        (directory / "prompt.md").write_text(prompt)
        (directory / "final.md").write_text(final)
        (directory / "stderr.log").write_text("")
        (directory / "events.jsonl").write_text(said)
        (directory / "session_id").write_text("sid")
        return directory

    def logged(self):
        lines = []
        return lines, lines.append

    # --- (a) and (b): recognition, from each harness's own manifest ------------------------

    def said(self, name, harness):
        """What `call_retrying` reads back from an out dir that harness's adapter just filled."""
        row = REFUSALS[harness]
        out = self.out_dir(name, row["events"], final=row["final"])
        return run.harness_said(out, row["final"], harness)

    def test_v5i_codex_refusal_with_an_empty_final_md_is_quota_and_not_transient(self):
        """The Sat 23:49 exit itself: nothing in final.md, the refusal in its own event log."""
        said = self.said("codex-exit", "codex")
        self.assertEqual(run.ran_dry(1, said, "codex"), "usage limit")
        self.assertIn("usage limit", watch.quotas("codex"))
        # what happened instead before v5i: an empty final.md read as a transport death
        self.assertEqual(run.transient(1, ""), "exited 1 with an empty final.md")
        # the refusal names when to come back, and that is parsed rather than guessed at
        self.assertEqual(run.try_again_at(said),
                         time.mktime(time.strptime("2026-10-12 23:39", "%Y-%m-%d %H:%M")))
        # and a zero exit is still a worker saying what it meant to say
        self.assertIsNone(run.ran_dry(0, said, "codex"))

    def test_v5i_claude_and_muse_refusals_match_their_own_manifest_signatures(self):
        for harness, mark in (("claude", "Usage limit reached"), ("muse", "usage limit reached")):
            with self.subTest(harness=harness):
                said = self.said(f"{harness}-exit", harness)
                self.assertIn(mark, watch.quotas(harness))
                self.assertEqual(run.ran_dry(1, said, harness), mark)
                # neither names a date, so the meters decide when the provider comes back
                self.assertIsNone(run.try_again_at(said))
        # a run whose own task text discusses a refusal has not been refused
        quoting = self.out_dir("quoting", "", prompt="You are the executor. Fix the handling of "
                               "\"You've hit your usage limit\" and of 429 Too Many Requests.")
        (quoting / "events.jsonl").write_text(
            '{"type":"user","text":"You are the executor. Fix the handling of \\"You\'ve hit '
            'your usage limit\\" and of 429 Too Many Requests."}')
        self.assertIsNone(run.ran_dry(1, run.harness_said(quoting, "", "codex"), "codex"))

    def test_v5i_muse_run_terminal_refusal_with_an_empty_final_is_quota(self):
        """The round-3 repro: Muse's terminal diagnostic alone, final.md empty, exit 1."""
        said = self.said("muse-exit", "muse")
        self.assertIn("usage limit reached", watch.quotas("muse"))
        self.assertEqual(run.ran_dry(1, said, "muse"), "usage limit reached")
        # a spent reset retries the same worker at once: asked before any retry, no backoff,
        # and the quota exit costs none of the transport attempts
        self.resets["meta"] = 1
        self.plan({"spark": [{"code": 1, **REFUSALS["muse"], "session": "dead-session"},
                             {"code": 0, "final": "## Summary\nDone."}]})
        lines, log = self.logged()
        code, text, session, dead = run.call_retrying(
            self.cfg, "spark", "the task", self.root, self.root / "round-1" / "executor",
            "executor", None, log)
        self.assertEqual((code, dead), (0, False))
        self.assertIn("Done.", text)
        self.assertEqual(self.replenished, ["meta"])
        self.assertEqual(self.resets["meta"], 0)
        self.assertIn("executor spark ran dry; reset spent (0 left), retrying", lines[0])
        self.sleep.assert_not_called()
        self.assertEqual(len(self.calls()), 2)
        self.assertEqual([row["model"] for row in self.calls()], ["spark", "spark"])
        self.assertEqual([row["session"] for row in self.calls()], [[], ["dead-session"]])
        self.assertEqual(session, "session-spark")
        self.assertEqual(self.marked, [])
        # and with no reset left the run is handed over, never an error
        self.plan({"spark": [{"code": 1, **REFUSALS["muse"]}]})
        # astra is the cheaper executor now, so the cheapest legal pair is (astra, opus)
        self.providers["openai"]["meters"] = [self.meter(5)]
        self.replenished.clear()
        self.marked.clear()
        (self.root / "calls.jsonl").unlink()
        code, _, state = self.launch("--exec", "spark", "--review", "opus", "--no-merge")
        self.assertEqual(code, 0)
        self.assertEqual(state["state"], "pass")
        self.assertEqual(self.replenished, ["meta"])
        self.assertEqual(self.marked, [("meta", self.now + WEEK / 2)])
        self.assertEqual([row["model"] for row in self.calls()], ["spark", "astra", "opus"])
        self.assertEqual(state["executor"], "astra")
        self.assertEqual(state["executor_history"],
                         [{"from": "spark", "to": "astra", "reason": "dry",
                           "model": "spark", "rounds": [1], "why": "ran dry"}])
        self.assertEqual(run.executor_line(state), "spark \u2192 astra (ran dry)")

    def test_v5i_each_harness_is_recognised_from_its_event_log_alone(self):
        """The invariant: each harness's terminal record plus an empty final.md is a quota."""
        for harness, mark in (("codex", "usage limit"),
                              ("claude", "Usage limit reached"),
                              ("muse", "usage limit reached")):
            with self.subTest(harness=harness):
                out = self.out_dir(f"{harness}-event-only", REFUSALS[harness]["events"],
                                   final="")
                said = run.harness_said(out, "", harness)
                self.assertEqual(run.ran_dry(1, said, harness), mark)
                self.assertIn(mark, watch.quotas(harness))

    def test_v5i_a_muse_answer_that_mentions_the_limit_is_not_a_refusal(self):
        """An answer-shaped run_terminal text is the worker's answer, never a refusal."""
        answers = {
            "heading": "## Summary\nQuoted the words `usage limit reached` while fixing the retry.",
            "verdict": "VERDICT: PASS\n## Findings\n- none; `usage limit reached` was quoted.",
            "long": "the worker quotes `usage limit reached` at length. " * 40,
        }
        for name, text in answers.items():
            with self.subTest(shape=name):
                events = json.dumps({"payload": {"kind": "run_terminal", "text": text}})
                out = self.out_dir(f"muse-answer-{name}", events, final="")
                said = run.harness_said(out, "", "muse")
                self.assertIsNone(run.ran_dry(1, said, "muse"))
                self.assertNotIn("usage limit reached", said)
        # end to end: a transient, so the waits run and no reset is touched
        row = {"code": 1, "final": "",
               "events": json.dumps({"payload": {"kind": "run_terminal",
                                                 "text": answers["heading"]}})}
        self.plan({"spark": [row, row, {"code": 0, "final": "## Summary\nDone."}]})
        lines, log = self.logged()
        code, _, _, dead = run.call_retrying(
            self.cfg, "spark", "the task", self.root, self.root / "round-1" / "executor",
            "executor", None, log)
        self.assertEqual((code, dead), (0, False))
        self.assertEqual(len(self.calls()), 3)
        self.assertEqual(self.sleep.call_args_list,
                         [((delay,),) for delay in run.TRANSIENT_BACKOFF[:2]])
        self.assertEqual((self.replenished, self.marked), ([], []))
        self.assertFalse([line for line in lines if "ran dry" in line])

    def test_v5i_a_long_self_declared_terminal_failure_is_still_a_refusal(self):
        """A failure the harness declares is one whatever shape its text has."""
        rows = {
            "codex": ("usage limit", json.dumps(
                {"type": "turn.failed",
                 "error": {"message": ("You've hit your usage limit. "
                                       "The work is waiting. ") * 40}})),
            "claude": ("Usage limit reached", json.dumps(
                {"type": "result", "subtype": "error_during_execution", "is_error": True,
                 "result": "Usage limit reached; the window is spent. " * 30})),
        }
        for harness, (mark, events) in rows.items():
            with self.subTest(harness=harness):
                # long past REFUSAL_CAP, so the answer-shape test alone would call it an answer
                self.assertGreater(len(events), run.REFUSAL_CAP)
                out = self.out_dir(f"{harness}-long-refusal", events, final="")
                said = run.harness_said(out, "", harness)
                self.assertEqual(run.ran_dry(1, said, harness), mark)
                self.assertIn(mark, watch.quotas(harness))

    def test_v5i_a_refusal_spread_over_two_lines_is_read_whole(self):
        """The signature and the date it names need not share a line."""
        out = self.out_dir("wrapped", "", final="You've hit your usage limit.\n"
                           "Try again at Oct 12th, 2026 11:39 PM\n")
        said = run.harness_said(out, (out / "final.md").read_text(), "codex")
        self.assertEqual(run.ran_dry(1, said, "codex"), "usage limit")
        self.assertEqual(run.try_again_at(said),
                         time.mktime(time.strptime("2026-10-12 23:39", "%Y-%m-%d %H:%M")))
        # an answer that mentions the same words is an answer: it has the shape one was asked for
        answer = self.out_dir("answer", "", final="## Summary\nTaught the loop to read "
                              "\"You've hit your usage limit.\" and to try again at the date.\n")
        self.assertIsNone(run.ran_dry(1, run.harness_said(
            answer, (answer / "final.md").read_text(), "codex"), "codex"))

    # --- (c) and (h): the reset policy at the moment of need -------------------------------

    def test_v5i_a_spent_reset_retries_the_same_worker_on_its_session_without_backoff(self):
        self.resets["openai"] = 2
        self.plan({"astra": [{"code": 1, **REFUSALS["codex"], "session": "dead-session"},
                             {"code": 0, "final": "## Summary\nDone."}]})
        lines, log = self.logged()
        code, text, session, dead = run.call_retrying(
            self.cfg, "astra", "the task", self.root, self.root / "round-1" / "executor",
            "executor", None, log)
        self.assertEqual((code, dead), (0, False))
        self.assertIn("Done.", text)
        # the policy was asked before anything was retried, and the credit really went
        self.assertEqual(self.replenished, ["openai"])
        self.assertEqual(self.resets["openai"], 1)
        self.assertIn("executor astra ran dry; reset spent (1 left), retrying", lines[0])
        self.sleep.assert_not_called()
        # the same worker, resuming the session the refused attempt left behind
        self.assertEqual([row["model"] for row in self.calls()], ["astra", "astra"])
        self.assertEqual([row["session"] for row in self.calls()], [[], ["dead-session"]])
        self.assertEqual(session, "session-astra")
        self.assertEqual(self.marked, [])

    def test_v5i_a_quota_exit_costs_none_of_the_transport_attempts(self):
        self.resets["openai"] = 1
        self.plan({"astra": [{"code": 1, **REFUSALS["codex"]},
                             {"code": 1, "final": "API Error: 500 upstream"},
                             {"code": 1, "final": "API Error: 500 upstream"},
                             {"code": 0, "final": "## Summary\nDone."}]})
        lines, log = self.logged()
        code, _, _, dead = run.call_retrying(
            self.cfg, "astra", "the task", self.root, self.root / "round-1" / "executor",
            "executor", None, log)
        self.assertEqual((code, dead), (0, False))
        self.assertEqual(len(self.calls()), 4)
        self.assertEqual(self.sleep.call_args_list,
                         [((delay,),) for delay in run.TRANSIENT_BACKOFF[:2]])
        self.assertEqual(sum("attempt 3" in line for line in lines), 0)
        # every attempt keeps its own diagnostics, the refused one included
        self.assertEqual(sorted(Path(row["out"]).name for row in self.calls()),
                         ["executor", "executor-retry1", "executor-retry2", "executor-retry3"])

    # --- (d): no reset -> the provider is parked and the work changes hands ----------------

    def test_v5i_no_reset_parks_the_provider_and_hands_the_round_to_another(self):
        repo = self.repository()
        # spark is the cheaper executor here: the cheapest legal pair hands it the round
        self.providers["meta"]["meters"] = [self.meter(5)]
        self.plan({"astra": [{"code": 1, **REFUSALS["codex"]}]})
        code, directory, state = self.launch("--exec", "astra", "--review", "opus", "--no-merge")
        self.assertEqual(code, 0)
        self.assertEqual(state["state"], "pass")
        # the refusal named the date, so that is what the provider is parked until
        until = time.mktime(time.strptime("2026-10-12 23:39", "%Y-%m-%d %H:%M"))
        self.assertEqual(self.marked, [("openai", until)])
        self.assertEqual(self.providers["openai"]["exhausted_until"], until)
        # and nothing picks openai again while the mark stands, in this run or any other
        self.assertTrue(usage.model_exhausted(self.cfg, "astra", self.collect(self.cfg))[0])
        self.assertNotIn("astra", usage.pick_order(self.cfg, self.collect(self.cfg)))
        # the work went to the cheapest legal pair: spark executes, opus reviews
        self.assertEqual(state["executor"], "spark")
        self.assertEqual(state["reviewer"], "opus")
        self.assertEqual([row["model"] for row in self.calls()], ["astra", "spark", "opus"])
        # same worktree, same branch, same round, and a fresh session for the new model
        self.assertEqual(state["repo"], str(repo))
        self.assertEqual({row["workspace"] for row in self.calls("executor")},
                         {state["worktree"]})
        self.assertEqual(run.git(state["worktree"], "rev-parse", "--abbrev-ref", "HEAD"),
                         state["branch"])
        self.assertEqual([entry["round"] for entry in state["round_summaries"]], [1])
        self.assertEqual(self.calls()[1]["session"], [])
        self.assertEqual(self.calls()[1]["out"].rsplit("/", 2)[-2], "round-1")
        # the note the new executor is given, and nothing else about the round changed
        self.assertIn("astra began this round", self.calls()[1]["prompt"])
        self.assertIn("uncommitted edits", self.calls()[1]["prompt"])
        # run.json says who held which round and why it changed
        self.assertEqual(state["executor_history"],
                         [{"from": "astra", "to": "spark", "reason": "dry",
                           "model": "astra", "rounds": [1], "why": "ran dry"}])
        self.assertEqual(run.executor_line(state), "astra \u2192 spark (ran dry)")
        # the table carries executor/reviewer; the handover sentence lives on
        # in --plain, which keeps today's lines for scripts
        with redirect_stdout(io.StringIO()) as out:
            run.cmd_status(["--plain", directory.name])
        self.assertIn("astra \u2192 spark (ran dry)/opus", out.getvalue())

    # --- (e): the reviewer's own refusal takes the spares road -----------------------------

    def test_v5i_a_reviewer_that_runs_dry_hands_to_a_spare_on_a_third_provider(self):
        self.repository()
        self.plan({"astra": [{"code": 1, **REFUSALS["codex"]}]})
        code, _, state = self.launch("--exec", "opus", "--review", "astra", "--no-merge")
        self.assertEqual((code, state["state"]), (0, "pass"))
        self.assertEqual([row["model"] for row in self.calls()], ["opus", "astra", "spark"])
        # the executor never reviewed its own work, and its provider was never asked to
        self.assertEqual(state["executor"], "opus")
        self.assertEqual(state["reviewer"], "spark")
        self.assertEqual(state["review"]["executor_provider"], "anthropic")
        self.assertEqual(state["review"]["reviewer_provider"], "meta")
        self.assertNotIn("opus", [row["model"] for row in self.calls("reviewer")])
        # the reviewer's provider is parked exactly as an executor's would be
        self.assertEqual([provider for provider, _ in self.marked], ["openai"])
        self.assertIsNone(state.get("executor_history"))

    # --- (f): nothing left is `exhausted`, and resume hands over ----------------------------

    def test_v5i_nothing_left_is_exhausted_and_resume_hands_over_instead_of_relaunching(self):
        # One model per company: no same-company pair survives the refusals.
        self.eligible.remove("fable")
        self.repository()
        self.providers["meta"]["meters"] = [self.meter(100)]
        self.plan({"astra": [{"code": 1, **REFUSALS["codex"]}]})
        code, directory, state = self.launch("--exec", "astra", "--review", "opus", "--no-merge")
        self.assertEqual(code, 1)
        self.assertEqual(state["state"], "exhausted")      # never `error`: this is resumable
        self.assertNotEqual(state["verdict"], "ERROR")
        self.assertIn("no other provider can execute", state["error"])
        self.assertIn("nothing is picked on openai until",
                      (directory / "log.txt").read_text())
        self.assertEqual([row["model"] for row in self.calls()], ["astra"])
        self.assertEqual(state["executor"], "astra")
        self.assertTrue(run.needs_recovery(state) or state["state"] == "exhausted")
        # a meter refills; the resume must not put the work back on the model that ran dry.
        # refilled spark is the cheaper executor, so the cheapest legal pair takes the round
        self.providers["meta"]["meters"] = [self.meter(5)]
        self.assertEqual(run.cmd_resume([directory.name]), 0)
        state = run.read_state(directory)
        self.assertEqual(state["state"], "pass")
        self.assertEqual(state["executor"], "spark")
        self.assertEqual(state["reviewer"], "opus")
        self.assertEqual([row["model"] for row in self.calls()], ["astra", "spark", "opus"])
        # astra started round 1 and never finished it, and that is what it is credited with;
        # the failed first handover attempt stays on the record beside the move itself
        self.assertEqual(state["executor_history"],
                         [{"from": "astra", "to": "astra", "reason": "dry (no other provider)",
                           "model": "astra", "rounds": [1], "why": "ran dry"},
                          {"from": "astra", "to": "spark", "reason": "dry",
                           "model": "astra", "rounds": [1], "why": "ran dry"}])
        self.assertEqual(self.calls()[1]["session"], [])   # a fresh session, not astra's
        # the model taking over is told it is joining a round somebody else started
        self.assertIn("astra began this round", self.calls()[1]["prompt"])
        self.assertIn("uncommitted edits", self.calls()[1]["prompt"])
        # and it writes beside the refused attempt, never over it
        refused, resumed = (Path(row["out"]) for row in self.calls()[:2])
        self.assertEqual((refused.parent.name, resumed.parent.name), ("round-1", "round-1"))
        self.assertNotEqual(refused, resumed)
        self.assertEqual((refused / "events.jsonl").read_text(), REFUSALS["codex"]["events"])

    # --- the mark itself: it lives in the cache, so every later pick in every run sees it ---

    def test_v5i_a_parked_provider_stays_out_across_probes_until_its_own_deadline(self):
        until = self.now + 3 * 3600

        def probe(cfg, provider, now, account=None):
            return {"provider": provider, "error": None, "resets": 0.0, "pace": None,
                    "harness": config.provider_harness(cfg, provider)[0],
                    "exhausted": False, "meters": [self.meter(40)]}

        cache = config.STATE / "usage.json"
        with patch.object(usage, "collect", self.real_collect), \
                patch.object(usage, "mark_exhausted", self.real_mark), \
                patch.object(usage, "_probe", side_effect=probe):
            self.assertEqual(usage.mark_exhausted(self.cfg, "openai", until), until)
            for _ in range(2):
                blob = json.loads(cache.read_text())
                blob["fetched_at"] = self.now - usage.CACHE_TTL - 1   # every meter read again
                cache.write_text(json.dumps(blob))
                providers = usage.collect(self.cfg)
                self.assertEqual(providers["openai"]["meters"][0]["used"], 40)
                self.assertTrue(providers["openai"]["exhausted"])
                self.assertTrue(usage.model_exhausted(self.cfg, "astra", providers)[0])
                self.assertNotIn("astra", usage.pick_order(self.cfg, providers, quiet=True))
                self.assertIn("opus", usage.pick_order(self.cfg, providers, quiet=True))
            # past the deadline the probe decides again, and nothing of the mark is left behind
            self.now = until + 1
            providers = usage.collect(self.cfg)
            self.assertNotIn("exhausted_until", providers["openai"])
            self.assertFalse(providers["openai"]["exhausted"])
            self.assertIn("astra", usage.pick_order(self.cfg, providers, quiet=True))
            stored = json.loads(cache.read_text())["providers"]["openai"]
            self.assertNotIn("exhausted_until", stored)

    def test_v5i_tool_output_quoting_a_refusal_is_a_transport_death_not_one(self):
        """A command that greps for the words is not the provider saying them.

        Last in the log and with a failing exit code, which is where the transport death left
        it: what a command printed is the work's own output wherever it sits in the stream.
        """
        events = "\n".join([
            '{"type":"item.started","item":{"type":"agent_message"}}',
            '{"type":"item.completed","item":{"type":"command_execution","exit_code":1,'
            '"status":"failed","command":"grep -n \'usage limit\' agentkit/run.py",'
            '"aggregated_output":"345: You have hit your usage limit. Try again at '
            'Oct 12th, 2026 11:39 PM"}}'])
        stderr = "codex: connection failed: error sending request for url"
        out = self.out_dir("tool-output", events, final="")
        (out / "stderr.log").write_text(stderr)
        said = run.harness_said(out, "", "codex")
        self.assertIsNone(run.ran_dry(1, said, "codex"))
        self.assertIn("connection failed", said)     # the diagnostics are read; the output is not
        self.assertNotIn("usage limit", said)
        self.assertNotIn("grep", said)
        # end to end: the transport retries run, and no reset is asked for or spent
        self.resets["openai"] = 2
        row = {"code": 1, "final": "", "events": events, "stderr": stderr}
        self.plan({"astra": [row, row, {"code": 0, "final": "## Summary\nDone."}]})
        lines, log = self.logged()
        code, _, _, dead = run.call_retrying(
            self.cfg, "astra", "the task", self.root, self.root / "round-1" / "executor",
            "executor", None, log)
        self.assertEqual((code, dead), (0, False))
        self.assertEqual((self.replenished, self.marked, self.resets["openai"]), ([], [], 2))
        self.assertEqual(self.sleep.call_args_list,
                         [((delay,),) for delay in run.TRANSIENT_BACKOFF[:2]])
        self.assertEqual(len(self.calls()), 3)
        self.assertFalse([line for line in lines if "ran dry" in line])

    def test_v5i_two_models_that_shared_a_round_both_hold_it(self):
        """astra hands round 1 to spark, spark runs dry too, and a resume records both."""
        # One model per company: no same-company pair survives the refusals.
        self.eligible.remove("fable")
        self.repository()
        # spark and then astra are the cheaper executors of their handovers, which is the
        # pair the cheapest-legal-pair rule picks both times
        self.providers["meta"]["meters"] = [self.meter(5)]
        self.providers["openai"]["meters"] = [self.meter(5)]
        self.plan({"astra": [{"code": 1, **REFUSALS["codex"]}],
                   "spark": [{"code": 1, "final": "model failed: usage limit reached"}]})
        code, directory, state = self.launch("--exec", "astra", "--review", "opus", "--no-merge")
        self.assertEqual((code, state["state"]), (1, "exhausted"))
        self.assertEqual([row["model"] for row in self.calls()], ["astra", "spark"])
        self.assertEqual(state["executor"], "spark")
        self.assertEqual(state["executor_history"],
                         [{"from": "astra", "to": "spark", "reason": "dry",
                           "model": "astra", "rounds": [1], "why": "ran dry"},
                          {"from": "spark", "to": "spark", "reason": "dry (no other provider)",
                           "model": "spark", "rounds": [1], "why": "ran dry"}])
        # openai refills; the resume takes the work off spark, which held round 1 as well
        self.providers["openai"].pop("exhausted_until")
        self.plan({})
        self.assertEqual(run.cmd_resume([directory.name]), 0)
        state = run.read_state(directory)
        self.assertEqual((state["state"], state["executor"]), ("pass", "astra"))
        self.assertEqual(state["executor_history"],
                         [{"from": "astra", "to": "spark", "reason": "dry",
                           "model": "astra", "rounds": [1], "why": "ran dry"},
                          {"from": "spark", "to": "spark", "reason": "dry (no other provider)",
                           "model": "spark", "rounds": [1], "why": "ran dry"},
                          {"from": "spark", "to": "astra", "reason": "dry",
                           "model": "spark", "rounds": [1], "why": "ran dry"}])
        self.assertEqual(run.executor_line(state), "astra \u2192 spark \u2192 astra (ran dry)")

    def test_v5i_a_tick_handover_still_names_its_models_and_rounds(self):
        """A babysitter `{at, from, to, reason}` entry has no model half: the status line
        reads `from` and `reason` for it, and a dry handover on top of it credits the
        outgoing model with only the round being handed over."""
        state = {"executor": "spark",
                 "executor_history": [{"at": self.now, "from": "astra", "to": "spark",
                                       "reason": "stalled"}]}
        self.assertEqual(run.executor_line(state), "astra \u2192 spark (stalled)")
        run.note_handover(state, "spark", "ran dry", 3, to="opus", reason="dry")
        self.assertEqual(state["executor_history"][-1]["rounds"], [3])
        state["executor"] = "opus"
        self.assertEqual(run.executor_line(state), "astra \u2192 spark \u2192 opus (ran dry)")

    def test_v5i_an_undated_refusal_still_parks_and_a_handover_cannot_circle(self):
        """Nothing naming a time is still a refusal; without a mark the work would come back."""
        # One model per company: no same-company pair survives the refusals.
        self.eligible.remove("fable")
        self.repository()
        for prov in self.providers.values():         # meters that name no window either
            for meter in prov["meters"]:
                meter.pop("resets_at")
        undated = {"astra": {"final": "", "events":
                             '{"type":"turn.failed","error":'
                             '{"message":"You have hit your usage limit."}}'},
                   "opus": {"final": "Usage limit reached", "events": ""},
                   "spark": {"final": "model failed: usage limit reached", "events": ""}}
        self.plan({name: [{"code": 1, **row}] for name, row in undated.items()})
        code, directory, state = self.launch("--exec", "astra", "--review", "opus", "--no-merge")
        self.assertEqual((code, state["state"]), (1, "exhausted"))
        # no provider was asked twice: the handover never circled back to one
        self.assertEqual([row["model"] for row in self.calls()], ["astra", "opus"])
        self.assertEqual(sorted(provider for provider, _ in self.marked),
                         ["anthropic", "openai"])
        # with nothing to go on, an hour is what a refusal buys
        self.assertEqual({until - self.now for _, until in self.marked}, {usage.DRY_FOR})
        self.assertIn("ran dry", (directory / "log.txt").read_text())

    def test_v5i_a_spent_session_parks_only_until_the_session_refills(self):
        """The 5h window is a gate of its own: a spent one is not a spent week."""
        session, week = self.now + 100, self.now + 302400

        def probe(cfg, provider, now, account=None):
            return {"provider": provider, "error": None, "resets": 0.0, "pace": None,
                    "harness": config.provider_harness(cfg, provider)[0], "exhausted": False,
                    "meters": [{**self.meter(100, usage.SESSION_SECS), "resets_at": session},
                               {**self.meter(50), "resets_at": week}]}

        with patch.object(usage, "collect", self.real_collect), \
                patch.object(usage, "mark_exhausted", self.real_mark), \
                patch.object(usage, "_probe", side_effect=probe):
            self.assertEqual(usage.mark_exhausted(self.cfg, "openai"), session)
            self.assertTrue(usage.model_exhausted(self.cfg, "astra", usage.collect(self.cfg))[0])
            # past the session's own reset the provider is eligible again, week or no week
            self.now = session + 1
            self.assertNotIn("exhausted_until", usage.collect(self.cfg)["openai"])

    def test_v5i_a_spent_reset_lifts_the_mark_the_refusal_before_it_left(self):
        """A fresh week is exactly the capacity the mark says is missing."""
        used, resets = [95], [0.0]

        def probe(cfg, provider, now, account=None):
            return {"provider": provider, "error": None, "pace": None, "exhausted": False,
                    "resets": resets[0] if provider == "openai" else 0.0,
                    "harness": config.provider_harness(cfg, provider)[0],
                    "meters": [self.meter(used[0] if provider == "openai" else 10)]}

        def adapter_json(harness, verb, timeout):
            used[0], resets[0] = 0, 0.0
            return {"code": "reset", "available": 0, "weekly_used": 0}

        cache = config.STATE / "usage.json"
        with patch.object(usage, "collect", self.real_collect), \
                patch.object(usage, "mark_exhausted", self.real_mark), \
                patch.object(usage, "_probe", side_effect=probe), \
                patch.object(usage, "_adapter_json", side_effect=adapter_json):
            # the refusal came with no credit in hand, so the provider is simply parked
            usage.mark_exhausted(self.cfg, "openai", self.now + 5 * 86400)
            self.assertTrue(usage.model_exhausted(self.cfg, "astra", usage.collect(self.cfg))[0])
            resets[0] = 1.0                          # a credit the account earns later
            self.now += usage.PROBE_EVERY            # read by the next probe, a minute on
            blob = json.loads(cache.read_text())
            blob["fetched_at"] = self.now - usage.CACHE_TTL - 1      # both clocks go stale, so
            blob["reset_checked_at"] = self.now - usage.RESET_EVERY_SECS   # the policy may fire
            cache.write_text(json.dumps(blob))
            providers = usage.collect(self.cfg)
            # the spent week is gone, and the fresh one is the next probe's to read
            self.assertEqual(providers["openai"]["meters"], [])
            self.assertNotIn("exhausted_until", providers["openai"])
            self.assertFalse(providers["openai"]["exhausted"])
            self.assertIn("astra", usage.pick_order(self.cfg, providers, quiet=True))
            self.assertNotIn("exhausted_until",
                             json.loads(cache.read_text())["providers"]["openai"])

    # --- (g): the cap inside the real replenish -------------------------------------------

    def test_v5i_replenish_bypasses_the_threshold_but_never_the_once_a_day_cap(self):
        asked = []

        def adapter_json(harness, verb, timeout):
            asked.append(verb)
            return {"code": "reset", "available": 0, "weekly_used": 5}

        probed = []

        def probe(cfg, provider, now, account=None):
            probed.append(provider)
            used = 5 if len(probed) > 1 else 12
            return {"provider": provider, "harness": "codex", "error": None, "resets": 1.0,
                    "pace": None, "exhausted": False, "meters": [self.meter(used)]}

        with patch.object(usage, "_adapter_json", side_effect=adapter_json), \
                patch.object(usage, "_probe", side_effect=probe):
            # 12% used is nowhere near RESET_AT_USED; the refusal is the proof, not the meter
            self.assertGreater(usage.RESET_AT_USED, 12)
            self.assertEqual(self.real_replenish(self.cfg, "openai"), (True, 0.0))
            self.assertEqual(asked.count("reset"), 1)
            claim = json.loads((config.STATE / "openai-reset.json").read_text())
            self.assertEqual((claim["outcome"], claim["depleted"], claim["weekly_before"]),
                             ("reset", True, 12))
            # inside the host's minute nothing reads it again: the spent week is gone from the
            # cache until the next probe reads the new one, and the count is the spend's own
            cached = json.loads((config.STATE / "usage.json").read_text())
            self.assertEqual(cached["providers"]["openai"]["meters"], [])
            self.assertEqual(cached["providers"]["openai"]["resets"], 0.0)
            self.assertEqual(len(probed), 1)
            # a second refusal inside the same day spends nothing at all
            for _ in range(3):
                self.assertEqual(self.real_replenish(self.cfg, "openai"), (False, 0.0))
            self.assertEqual(asked.count("reset"), 1)
            # and once the day is over the policy is eligible again
            self.now += usage.RESET_EVERY_SECS
            self.assertEqual(self.real_replenish(self.cfg, "openai"), (True, 0.0))
            self.assertEqual(asked.count("reset"), 2)


# Each harness's own refusal, where its own adapter leaves it: Codex's `turn.failed` event
# and Muse's `run_terminal` event, each with nothing in final.md at all -- the Sat 23:49 exit
# for Codex, and Muse's where `jq .payload.text` found no text to pull -- and Claude's in
# final.md, which is what `jq .result` pulls out of its stream.  The signature that has to
# match each one is read from adapters/<harness>.toml and never written down here.
REFUSALS = {
    "codex": {"final": "", "events":
              '{"type":"turn.failed","error":{"message":"You\'ve hit your usage limit. '
              'Try again at Oct 12th, 2026 11:39 PM"}}'},
    "claude": {"final": "Usage limit reached \u00b7 continuing automatically when it resets",
               "events": '{"type":"result","subtype":"error_during_execution","is_error":true,'
                         '"result":"Usage limit reached"}'},
    "muse": {"final": "", "events":
             '{"payload":{"kind":"run_terminal","text":"model failed: usage limit '
             'reached (after 10 provider attempts)"}}'},
}


ADAPTER = '''import json, os, pathlib, sys
assert sys.argv[1] == "run", sys.argv
root = pathlib.Path(os.environ["QUOTA_FIXTURE"])
name = json.loads((root / "models.json").read_text())[sys.argv[2]]
out = pathlib.Path(sys.argv[6])
prompt = pathlib.Path(sys.argv[5]).read_text()
role = "reviewer" if prompt.startswith("You are the reviewer") else "executor"
with (root / "calls.jsonl").open("a") as f:
    f.write(json.dumps({"model": name, "role": role, "out": str(out), "prompt": prompt,
                        "workspace": sys.argv[4], "session": sys.argv[7:]}) + "\\n")
plan = json.loads((root / "plan.json").read_text())
rows = plan.get(name)
if rows:
    row = rows.pop(0) if len(rows) > 1 else rows[0]
    plan[name] = rows
    (root / "plan.json").write_text(json.dumps(plan))
elif role == "executor":
    row = {"code": 0, "final": "## Summary\\nProduced the fixture."}
else:
    row = {"code": 0, "final": "VERDICT: PASS\\n## Findings\\n- none"}
if role == "executor" and row.get("code", 0) == 0:
    pathlib.Path(sys.argv[4], "deliverable").write_text("fixture work\\n")
(out / "final.md").write_text(row.get("final", ""))
(out / "stderr.log").write_text(row.get("stderr", "diagnostic for " + name))
(out / "events.jsonl").write_text(row.get("events", ""))
(out / "session_id").write_text(row.get("session", "session-" + name))
sys.exit(row.get("code", 0))
'''


if __name__ == "__main__":
    unittest.main()
