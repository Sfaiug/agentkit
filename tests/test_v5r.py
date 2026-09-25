"""v5r: an exhausted run resumes itself when a window refills.

Entirely offline. The usage cache is a fake dict (or a fake usage.json on disk), the
resume is a fake hook on run.spawn_bg, and no real adapter, reset or model call is
made anywhere in here. Never a real webhook: notify.shaped is faked where counted.
"""

from contextlib import ExitStack, redirect_stdout
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, menu, notify, orch, run, usage, watch

WEEK = 604800


def meter(name, used, resets_at, window=WEEK):
    return {"name": name, "used": used, "resets_at": resets_at, "window_secs": window,
            "pace": None}


class ExhaustedResume(unittest.TestCase):
    """One patched home, the shipped default config, fake providers, a fake resume hook."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".run-v5r-", dir=REPO)
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
            # notify.shaped is suppressed for a worker; the tick is not one.
            "AK_RUN_ROLE": "orchestrator",
            # this HOME's OpenCode config, never the caller's: mimo is payg
            "OPENCODE_CONFIG_DIR": str(self.root / ".config/opencode")}))
        # this file is about when a resume is retried, not where it runs; the slice a launch
        # is placed in has its own tests, and a host with a manager must not change these
        # counts on the host that happens to run the suite
        self.stack.enter_context(patch.object(orch, "user_manager", return_value=False))
        self.stack.enter_context(patch.object(run, "host_readings", return_value={
            "free_mb": 4096, "mem_total_mb": 16384, "load": 1, "cpus": 8,
            "unit_memory_current_mb": 100, "unit_memory_high_mb": 1000}))
        config.ensure_dirs()
        self.cfg = config.load()
        # every model works but Fable, so a handover off one company leaves two to pair
        self.cfg["defaults"]["workers"] = [n for n in config.offered(self.cfg) if n != "fable"]
        self.now = time.time()
        self.logs = []
        self.log = self.logs.append

    def providers(self, openai_used=10, anthropic_used=100, meta_used=100, resets_in=None):
        """Fake usage providers: openai refilled, the rest dry, unless told otherwise."""
        resets_in = WEEK if resets_in is None else resets_in
        return {
            "anthropic": {"meters": [meter("weekly_all", anthropic_used, self.now + WEEK),
                                     meter("weekly_scoped", anthropic_used, self.now + WEEK)]},
            "openai": {"meters": [meter("weekly", openai_used, self.now + resets_in)]},
            "meta": {"meters": [meter("weekly", meta_used, self.now + WEEK)]},
        }

    def receipt(self, name, executor="astra", worktree=True):
        run_dir = config.RUNS / name
        run_dir.mkdir(parents=True)
        wt = self.root / f"wt-{name}"
        if worktree:
            wt.mkdir(parents=True)
        run.save_state(run_dir, {"run_id": name, "title": f"A run out of budget ({name})",
                                 "state": "exhausted", "verdict": None,
                                 "executor": executor, "reviewer": "spark",
                                 "rounds": 2, "round_summaries": [],
                                 "repo": str(self.root), "worktree": str(wt),
                                 "branch": "run-x", "base": "main", "base_sha": "0" * 40,
                                 "error": "every provider is out of budget",
                                 "quota_dry": True,
                                 "started_at": self.now - 600, "finished_at": self.now - 60})
        return run_dir

    def test_v5r_tick_resumes_exhausted_run_when_window_refills(self):
        run_dir = self.receipt("20260916-1200-refill", executor="astra")
        calls = []
        with patch.object(run, "spawn_bg", side_effect=lambda d, a, expected=None:
                          calls.append((d, a, expected)) or 0):
            watch.resume_exhausted(self.cfg, self.providers(), log=self.log, now=self.now)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1], ["resume", run_dir.name])
        self.assertIn(f"resumed {run_dir.name}: openai window refilled", self.logs)
        state = run.read_state(run_dir)
        self.assertEqual(state["executor"], "astra")   # still good: no handover
        self.assertNotIn("executor_history", state)
        self.assertEqual(state["exhausted_resume_at"], self.now)

    def test_v5r_tick_hands_over_a_saved_executor_that_is_still_dry(self):
        run_dir = self.receipt("20260916-1201-handover", executor="opus")
        calls = []
        with patch.object(run, "spawn_bg", side_effect=lambda d, a, expected=None:
                          calls.append((d, a, expected)) or 0):
            watch.resume_exhausted(self.cfg, self.providers(), log=self.log, now=self.now)
        self.assertEqual(len(calls), 1)
        state = run.read_state(run_dir)
        self.assertEqual(state["executor"], "astra")
        self.assertEqual(state["executor_history"],
                         [{"at": self.now, "from": "opus", "to": "astra", "reason": "dry"}])
        self.assertIn(f"resumed {run_dir.name}: openai window refilled", self.logs)

    def test_v5r_tick_leaves_exhausted_run_while_every_provider_dry(self):
        run_dir = self.receipt("20260916-1202-dry")
        providers = self.providers(openai_used=100, anthropic_used=100, meta_used=100)
        with patch.object(run, "spawn_bg",
                          side_effect=AssertionError("no resume while dry")):
            watch.resume_exhausted(self.cfg, providers, log=self.log, now=self.now)
        self.assertNotIn("resumed", " ".join(self.logs))
        state = run.read_state(run_dir)
        self.assertEqual(state["state"], "exhausted")
        self.assertNotIn("exhausted_resume_at", state)

    def test_v5r_failed_resume_retries_after_resume_every_only(self):
        # the real spawn_bg, which parks a failed launch as interrupted: the tick must
        # put the run back to exhausted, stay silent, and relaunch after RESUME_EVERY.
        from types import SimpleNamespace
        run_dir = self.receipt("20260916-1203-retry")
        state = run.read_state(run_dir)
        state["launched_session"] = "seat"
        run.save_state(run_dir, state)
        launches = []
        def fork(*args, **kwargs):
            launches.append(args)
            if len(launches) == 1:
                raise OSError("fixture cannot fork")
            return SimpleNamespace(pid=99999999)
        sent = []
        with patch.object(run.subprocess, "Popen", side_effect=fork), \
                patch.object(notify, "shaped",
                             side_effect=lambda *a, **k: sent.append((a, k)) or 0), \
                patch("agentkit.orch.find", return_value=None):
            watch.resume_exhausted(self.cfg, self.providers(), log=self.log, now=self.now)
            self.assertEqual(len(launches), 1)
            self.assertTrue(any("WARN could not resume" in line for line in self.logs),
                            self.logs)
            state = run.read_state(run_dir)
            self.assertEqual(state["state"], "exhausted")
            self.assertNotIn("recovery_pending", state)
            run.reap(run_dir, state)           # the same tick's reaper stays silent too
            watch.resume_exhausted(self.cfg, self.providers(), log=self.log, now=self.now)
            self.assertEqual(len(launches), 1)    # throttled inside RESUME_EVERY
            watch.resume_exhausted(self.cfg, self.providers(), log=self.log,
                                   now=self.now + watch.RESUME_EVERY)
            self.assertEqual(len(launches), 2)    # retried once the window allows
            state = run.read_state(run_dir)
            self.assertEqual((state["state"], state["resume_from"]), ("queued", "exhausted"))
        self.assertEqual(sent, [])

    def test_v5r_automatic_resume_emits_only_its_log_line(self):
        from types import SimpleNamespace
        run_dir = self.receipt("20260916-1207-one-line")
        out = io.StringIO()
        with patch.object(run.subprocess, "Popen",
                          return_value=SimpleNamespace(pid=99999999)), \
                redirect_stdout(out):
            watch.resume_exhausted(self.cfg, self.providers(), log=self.log, now=self.now)
        self.assertEqual(out.getvalue(), "")   # spawn_bg's own prints stay captured
        self.assertEqual(self.logs, [f"resumed {run_dir.name}: openai window refilled"])

    def test_v5r_gone_worktree_warns_even_while_every_provider_dry(self):
        run_dir = self.receipt("20260916-1208-gone-dry", worktree=False)
        providers = self.providers(openai_used=100, anthropic_used=100, meta_used=100)
        with patch.object(run, "spawn_bg",
                          side_effect=AssertionError("no resume without a worktree")):
            watch.resume_exhausted(self.cfg, providers, log=self.log, now=self.now)
        self.assertTrue(any("WARN" in line and "gone" in line for line in self.logs),
                        self.logs)
        self.assertEqual(run.read_state(run_dir)["state"], "exhausted")

    def test_v5r_session_worker_selection_excludes_other_providers(self):
        config.save_session(self.cfg, "seat", "astra", ["astra", "spark"])
        run_dir = self.receipt("20260916-1209-selection", executor="astra")
        providers = self.providers(openai_used=100, anthropic_used=40, meta_used=100)
        with patch.dict(os.environ, {"AGENTKIT_SESSION": "seat"}), \
                patch.object(run, "spawn_bg",
                             side_effect=AssertionError("opus is not this session's worker")):
            watch.resume_exhausted(self.cfg, providers, log=self.log, now=self.now)
        self.assertNotIn("resumed", " ".join(self.logs))
        self.assertEqual(run.read_state(run_dir)["state"], "exhausted")
        for prov, at in (("anthropic", self.now + 3600), ("openai", self.now + 7200)):
            providers[prov]["meters"][0]["resets_at"] = at
        with patch.dict(os.environ, {"AGENTKIT_SESSION": "seat"}):
            provider, _, dry = run.exhausted_waits_for(state=run.read_state(run_dir),
                                                       providers=providers, cfg=self.cfg,
                                                       now=self.now)
        self.assertTrue(dry)
        self.assertEqual(provider, "openai")   # anthropic refilled first, but is excluded

    def test_v5r_non_quota_exhausted_run_is_never_resumed(self):
        # a git-stopped exhausted run carries no quota_dry flag: the tick leaves it
        # alone however refilled the providers are, and the row keeps the state word.
        run_dir = self.receipt("20260916-1211-toolstop")
        state = run.read_state(run_dir)
        state["error"] = "git push stopped: timed out"
        del state["quota_dry"]   # a tool stop is exhausted, but waits on no window
        run.save_state(run_dir, state)
        with patch.object(run, "spawn_bg",
                          side_effect=AssertionError("no window was ever spent")):
            watch.resume_exhausted(self.cfg, self.providers(), log=self.log, now=self.now)
        self.assertEqual(self.logs, [])
        self.assertEqual(run.read_state(run_dir)["state"], "exhausted")
        self.assertEqual(run.waiting_word(run.read_state(run_dir), self.providers(),
                                          self.cfg, now=self.now), "exhausted")
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(run.cmd_status([run_dir.name]), 0)
        # the table reads STATES words: no window, no waiting sentence, and
        # the column reads `needs you` for a run nothing will resume by itself
        self.assertNotIn("waiting", out.getvalue())
        row = next(line for line in out.getvalue().splitlines() if run_dir.name in line)
        self.assertIn("! needs you", row)
        row = menu.run_row(1, run_dir, run.read_state(run_dir))
        self.assertIn("exhausted", row[4])

    def test_v5r_handover_repicks_the_pair_by_budget(self):
        # opus is dry; spark is the cheaper executor and was this run's reviewer, so the
        # pair is re-picked by budget under the one-provider rule: spark executes and
        # astra reviews, rather than keeping the reviewer and forcing a dearer executor.
        run_dir = self.receipt("20260916-1212-spare-reviewer", executor="opus")
        state = run.read_state(run_dir)
        state["reviewer"] = "spark"
        run.save_state(run_dir, state)
        providers = self.providers(openai_used=10, anthropic_used=100, meta_used=5)
        calls = []
        with patch.object(run, "spawn_bg", side_effect=lambda d, a, expected=None:
                          calls.append((d, a, expected)) or 0):
            watch.resume_exhausted(self.cfg, providers, log=self.log, now=self.now)
        self.assertEqual(len(calls), 1)
        state = run.read_state(run_dir)
        self.assertEqual((state["executor"], state["reviewer"]), ("spark", "astra"))
        self.assertIn(f"resumed {run_dir.name}: meta window refilled", self.logs)

    def test_v5r_dry_run_changes_nothing_on_disk(self):
        run_dir = self.receipt("20260916-1210-dryrun")
        before = (run_dir / "run.json").read_bytes()
        watch.resume_exhausted(self.cfg, self.providers(), dry_run=True, log=self.log,
                               now=self.now)
        self.assertEqual((run_dir / "run.json").read_bytes(), before)
        self.assertIn(f"would resume {run_dir.name}: openai window refilled", self.logs)

    def test_v5r_gone_worktree_left_alone_with_warn(self):
        run_dir = self.receipt("20260916-1204-gone", worktree=False)
        with patch.object(run, "spawn_bg",
                          side_effect=AssertionError("no resume without a worktree")):
            watch.resume_exhausted(self.cfg, self.providers(), log=self.log, now=self.now)
        self.assertTrue(any("gone" in line and "WARN" in line for line in self.logs),
                        self.logs)
        self.assertEqual(run.read_state(run_dir)["state"], "exhausted")

    def test_v5r_status_and_row_wait_on_window(self):
        run_dir = self.receipt("20260916-1205-waiting")
        known = self.now + 3700
        (config.STATE / "usage.json").write_text(json.dumps({
            "fetched_at": self.now, "providers": {
                "anthropic": {"meters": [meter("weekly_all", 100, self.now + 7200)]},
                "openai": {"meters": [meter("weekly", 100, known)]},
                "meta": {"meters": [meter("weekly", 100, None)]},
                "other": {"meters": [meter("weekly", 100, self.now + 60)]}}}))
        want = (f"waiting for openai until "
                f"{time.strftime('%H:%M', time.localtime(known))}")
        state = run.read_state(run_dir)
        self.assertEqual(run.exhausted_waits_for(state, json.loads(
            (config.STATE / "usage.json").read_text())["providers"], cfg=self.cfg,
            now=self.now), ("openai", known, True))
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(run.cmd_status([run_dir.name]), 0)
        self.assertIn(want, out.getvalue())
        lines = out.getvalue().splitlines()
        self.assertTrue(lines[0].startswith("host: "), lines[0])
        status_row = next(line for line in lines if want in line)
        self.assertNotIn("exhausted", status_row)
        row = menu.run_row(1, run_dir, state)
        self.assertIn(want, row[4])
        self.assertEqual(run.read_state(run_dir)["state"], "exhausted")  # drill-down keeps it
        (config.STATE / "usage.json").unlink()
        self.assertEqual(run.waiting_word(state), "waiting for a provider window")

    def test_v5r_no_notification_on_exhaustion_or_resume(self):
        run_dir = self.receipt("20260916-1206-quiet")
        state = run.read_state(run_dir)
        state["launched_session"] = "seat"
        run.save_state(run_dir, state)
        sent = []
        with patch.object(notify, "shaped",
                          side_effect=lambda *a, **k: sent.append((a, k)) or 0), \
                patch("agentkit.orch.find", return_value=None):
            run.reap(run_dir, run.read_state(run_dir))   # the exhaustion path notifies nobody
            self.assertEqual(run.read_state(run_dir)["state"], "exhausted")
            with patch.object(run, "spawn_bg", return_value=0):
                watch.resume_exhausted(self.cfg, self.providers(), log=self.log,
                                       now=self.now)
            self.assertIn(f"resumed {run_dir.name}: openai window refilled", self.logs)
        kinds = [args[0] for args, _ in sent]
        self.assertNotIn("needs", kinds)
        self.assertNotIn("done", kinds)


if __name__ == "__main__":
    unittest.main(verbosity=2)
