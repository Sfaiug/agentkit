"""A transient provider answer resumes the same worker session; only the account hands over."""

from contextlib import ExitStack
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, run, usage, watch  # noqa: E402


class TransientResume(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix=".transient-resume-", dir=REPO)
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.root = root
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for key in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, key, root / key.lower()))
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(root), "AGENTKIT_SESSION": "", "AGENTKIT_RUN_DIR": "",
            "AGENTKIT_RUN": "",
            "AGENTKIT_DISCORD_WEBHOOK": "off", "AGENTKIT_TMUX_SOCKET": "transient-test",
            "TMUX_TMPDIR": str(root), "PYTHONDONTWRITEBYTECODE": "1"}))
        config.ensure_dirs()
        self.cfg = config.load()
        self.marked = []
        self.stack.enter_context(patch.object(
            usage, "replenish", return_value=(False, 0.0)))
        self.stack.enter_context(patch.object(
            usage, "mark_exhausted",
            side_effect=lambda cfg, provider, until=None: self.marked.append(
                (provider, until)) or until))

    def worker(self, answers):
        """A fake worker.call playing `answers` back: (code, text, session[, stderr]) each."""
        calls = []

        def call(*args, **kwargs):
            code, text, session, *stderr = answers[min(len(calls), len(answers) - 1)]
            calls.append(args)
            out = Path(args[4])
            out.mkdir(parents=True, exist_ok=True)
            (out / "prompt.md").write_text("You are the executor.\n")
            (out / "final.md").write_text(text)
            (out / "stderr.log").write_text("".join(stderr))
            (out / "events.jsonl").write_text("")
            (out / "session_id").write_text(session)
            return code, text, session, False

        return calls, call

    def test_500_resumes_the_same_session_id(self):
        calls, fake = self.worker([
            (1, "API Error: 500 {\"type\":\"error\"}\n", "sess-1"),
            (0, "## Summary\nDone after the outage.\n", "sess-1"),
        ])
        sleeps, logs = [], []
        with patch.object(run.worker, "call", side_effect=fake), \
                patch.object(run.time, "sleep", side_effect=sleeps.append):
            code, text, session, dead = run.call_retrying(
                self.cfg, "opus", "body", self.root, self.root / "out", "executor",
                None, logs.append)
        self.assertEqual((code, dead, session), (0, False, "sess-1"))
        self.assertIn("Done after the outage.", text)
        self.assertEqual(len(calls), 2)
        # the retry resumed the session the dead attempt left behind, after a minute
        self.assertEqual(calls[0][6], None)
        self.assertEqual(calls[1][6], "sess-1")
        self.assertEqual(sleeps, [60])
        self.assertTrue(any("sess-1" in line for line in logs), logs)
        self.assertEqual(self.marked, [])

    def test_waits_grow_1_5_15_30_60_then_hourly(self):
        transient = (1, "Overloaded: the provider is busy\n", "s1")
        calls, fake = self.worker([transient] * 6 + [(0, "## Summary\nDone.\n", "s1")])
        sleeps, logs = [], []
        with patch.object(run.worker, "call", side_effect=fake), \
                patch.object(run.time, "sleep", side_effect=sleeps.append):
            code, _, session, dead = run.call_retrying(
                self.cfg, "opus", "body", self.root, self.root / "out", "executor",
                None, logs.append)
        self.assertEqual((code, dead, session), (0, False, "s1"))
        self.assertEqual(len(calls), 7)
        self.assertEqual(sleeps, [60, 300, 900, 1800, 3600, 3600])
        self.assertTrue(any("attempt 6" in line and "retrying in 3600s" in line
                            for line in logs), logs)
        # every retry resumed the same session, each in its own directory
        self.assertEqual([args[6] for args in calls[1:]], ["s1"] * 6)
        self.assertEqual(sorted(Path(args[4]).name for args in calls),
                         ["out", "out-retry1", "out-retry2", "out-retry3",
                          "out-retry4", "out-retry5", "out-retry6"])

    def test_usage_limit_hands_over_instead_of_resuming(self):
        calls, fake = self.worker([
            (1, "You've hit your usage limit. Try again at Oct 12th, 2026 11:39 PM\n",
             "dead-session"),
        ])
        sleeps, logs = [], []
        with patch.object(run.worker, "call", side_effect=fake), \
                patch.object(run.time, "sleep", side_effect=sleeps.append):
            with self.assertRaises(run.RanDry) as refused:
                run.call_retrying(self.cfg, "astra", "body", self.root,
                                  self.root / "out", "executor", None, logs.append)
        # one call, no wait: the round goes to another provider, as today
        self.assertEqual(len(calls), 1)
        self.assertEqual(sleeps, [])
        self.assertTrue(refused.exception.quota)
        self.assertEqual(refused.exception.session, "dead-session")
        self.assertIn("usage limit", refused.exception.message.lower())
        self.assertTrue(any("refused" in line for line in logs), logs)
        self.assertFalse(any("transient" in line for line in logs), logs)
        self.assertEqual(self.marked[0][0], "openai")

    def test_muse_idle_timeout_is_transient(self):
        self.assertIn("model stream idle timeout", watch.refusals("muse"))
        self.assertNotIn("model stream idle timeout", watch.quotas("muse"))
        calls, fake = self.worker([
            (1, "model stream idle timeout after 120s\n", "muse-1"),
            (0, "## Summary\nDone after the idle stream.\n", "muse-1"),
        ])
        sleeps, logs = [], []
        with patch.object(run.worker, "call", side_effect=fake), \
                patch.object(run.time, "sleep", side_effect=sleeps.append):
            code, text, session, dead = run.call_retrying(
                self.cfg, "spark", "body", self.root, self.root / "out", "executor",
                None, logs.append)
        self.assertEqual((code, dead, session), (0, False, "muse-1"))
        self.assertIn("Done after the idle stream.", text)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1][6], "muse-1")
        self.assertEqual(sleeps, [60])
        self.assertTrue(any("transient" in line and "idle timeout" in line
                            for line in logs), logs)
        self.assertEqual(self.marked, [])

    def test_sigterm_reads_killed_and_parks_on_the_second_kill(self):
        from agentkit import menu
        calls, fake = self.worker([(-15, "", "k1"), (-15, "", "k1")])
        sleeps, logs = [], []
        with patch.object(run.worker, "call", side_effect=fake), \
                patch.object(run.time, "sleep", side_effect=sleeps.append):
            with self.assertRaises(run.Killed) as killed:
                run.call_retrying(self.cfg, "opus", "body", self.root,
                                  self.root / "out", "executor", None, logs.append)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1][6], "k1")
        self.assertEqual(sleeps, [])
        self.assertEqual(killed.exception.session, "k1")
        self.assertIn("killed (SIGTERM)", str(killed.exception))
        self.assertIn("twice within a minute", str(killed.exception))
        self.assertNotIn("died on", str(killed.exception))
        self.assertTrue(any("killed (SIGTERM)" in line and "resuming once" in line
                            for line in logs), logs)
        self.assertFalse(any("died on" in line for line in logs), logs)
        # parked, resumable, reading `needs you` with the signal for a reason
        state = {"run_id": "fixture", "state": "running", "title": "Fixture"}
        run.interrupt(state, str(killed.exception))
        self.assertTrue(run.needs_recovery(state))
        self.assertEqual(menu.run_state_word(state), "needs you")
        self.assertIn("killed (SIGTERM)", run.recovery_reason(state))

    def test_sigkill_resumes_once_at_once(self):
        calls, fake = self.worker([
            (-9, "", "k9"),
            (0, "## Summary\nDone after the kill.\n", "k9"),
        ])
        sleeps, logs = [], []
        with patch.object(run.worker, "call", side_effect=fake), \
                patch.object(run.time, "sleep", side_effect=sleeps.append):
            code, text, session, dead = run.call_retrying(
                self.cfg, "opus", "body", self.root, self.root / "out", "executor",
                None, logs.append)
        self.assertEqual((code, dead, session), (0, False, "k9"))
        self.assertIn("Done after the kill.", text)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1][6], "k9")
        self.assertEqual(sleeps, [])
        self.assertTrue(any("killed (SIGKILL)" in line and "resuming once" in line
                            for line in logs), logs)
        self.assertFalse(any("died on" in line for line in logs), logs)

    def test_an_outage_of_hours_continues_the_same_session_while_the_tick_looks_in(self):
        # The run of 2026-09-22: a 30-minute wait read as a 20-minute silence, the tick killed
        # and resumed the loop, the waits began again at a minute, and the third stall parked
        # it.  Here the tick looks in a second before every wait ends and finds nothing to do.
        # Nothing real is killed or launched: every rung of the ladder is a mock.
        run_dir = config.RUNS / "20260922-2124-outage"
        run_dir.mkdir(parents=True)
        run.save_state(run_dir, {"run_id": run_dir.name, "state": "running",
                                 "round_summaries": [], "stalls": [], **run.process_owner()})
        outage = (1, "API Error: 500 Internal server error\n", "s1")
        calls, fake = self.worker([outage] * 7 + [(0, "## Summary\nDone.\n", "s1")])
        sleeps, ticks = [], []

        def sleep(seconds):
            sleeps.append(seconds)
            wait = run.read_state(run_dir)["transient_wait"]
            self.assertEqual(wait["pid"], os.getpid())
            self.assertAlmostEqual(wait["until"], time.time() + seconds, delta=5)
            watch.recover_runs({}, log=ticks.append, now=time.time() + seconds - 1)

        with patch.object(run.worker, "call", side_effect=fake), \
                patch.object(run.time, "sleep", side_effect=sleep), \
                patch.object(watch, "step_for_run",
                             return_value=("none", "no child", None, [])), \
                patch.object(watch, "kill_tree") as kill, \
                patch.object(watch, "stop_run_scope", return_value=False) as scope, \
                patch.object(watch, "launch_resume") as resume, \
                patch.object(run, "handover_executor") as handover:
            code, text, session, dead = run.call_retrying(
                self.cfg, "opus", "body", self.root, run_dir / "round-1" / "executor",
                "executor", None, lambda _: None)
        self.assertEqual((code, dead, session), (0, False, "s1"))
        self.assertIn("Done.", text)
        self.assertEqual(sleeps, [60, 300, 900, 1800, 3600, 3600, 3600])
        self.assertEqual([args[6] for args in calls[1:]], ["s1"] * 7)
        for rung in (kill, scope, resume, handover):
            rung.assert_not_called()
        self.assertEqual(ticks, [])
        state = run.read_state(run_dir)
        self.assertEqual((state["state"], state["stalls"]), ("running", []))

    def test_a_harness_that_cannot_run_is_not_transient(self):
        # An empty answer is read by its stderr: the harness never ran, and no wait changes it
        # -- not even where the line carries a refusal word, `API Error` or Codex's
        # `try a different model`, that its manifest also uses for an outage.
        for model, line in (("mimo", "opencode.sh: opencode is not installed"),
                            ("opus", "/home/u/agentkit/adapters/claude.sh: line 70: claude: "
                                     "command not found"),
                            ("opus", "error: unknown option '--effort'"),
                            ("opus", "Error: model not found: claude-nonexistent"),
                            ("opus", "Error: 401 Unauthorized"),
                            ("opus", "API Error: 404 model not found: nonexistent"),
                            ("opus", "API Error: 401 Unauthorized"),
                            ("astra", "The model gpt-nonexistent was not found. "
                                      "Try a different model.")):
            with self.subTest(line=line):
                calls, fake = self.worker([(2, "", "s1", f"{line}\n")])
                logs = []
                with patch.object(run.worker, "call", side_effect=fake), \
                        patch.object(run.time, "sleep", side_effect=AssertionError("waited")):
                    with self.assertRaises(run.CannotRun) as broken:
                        run.call_retrying(self.cfg, model, "body", self.root,
                                          self.root / "out", "executor", None, logs.append)
                self.assertEqual(len(calls), 1)
                self.assertIsInstance(broken.exception, run.Blocked)
                self.assertIn(line, str(broken.exception))
                self.assertIn(line, broken.exception.section)
                self.assertTrue(any("cannot run" in said and line in said for said in logs),
                                logs)
                self.assertFalse(any("retrying" in said for said in logs), logs)

    def test_an_outage_on_stderr_with_an_empty_answer_stays_transient(self):
        for model, line in (("opus", "API Error: 529 Overloaded"),
                            ("astra", "Selected model is at capacity. Try a different model."),
                            ("spark", "HTTP 503 Service Unavailable"),
                            ("spark", "boom"),
                            ("opus", "warning: jq is not installed\n"
                                     "API Error: 500 Internal server error")):
            with self.subTest(line=line):
                calls, fake = self.worker([(1, "", "s1", f"{line}\n"),
                                           (0, "## Summary\nDone.\n", "s1")])
                sleeps = []
                with patch.object(run.worker, "call", side_effect=fake), \
                        patch.object(run.time, "sleep", side_effect=sleeps.append):
                    code, _, session, dead = run.call_retrying(
                        self.cfg, model, "body", self.root, self.root / f"out-{len(line)}",
                        "executor", None, lambda _: None)
                self.assertEqual((code, dead, session, sleeps), (0, False, "s1", [60]))
                self.assertEqual(calls[1][6], "s1")

    def executor_loop(self):
        from types import SimpleNamespace
        return SimpleNamespace(cfg=self.cfg, state={"executor": "opus"}, executor="opus",
                               exec_sid=None, wt=self.root, turn_limit=60, rnd=1,
                               dir=lambda name: self.root / "round-1" / name,
                               role=lambda role: role, save=lambda: None, log=lambda _: None)

    def test_an_executor_that_cannot_run_hands_over_at_once(self):
        line = "opencode.sh: opencode is not installed"
        calls, fake = self.worker([(2, "", "s1", f"{line}\n"),
                                   (0, "## Summary\nDone elsewhere.\n", "s2")])
        lp, handed, sleeps = self.executor_loop(), [], []

        def hand(lp, why, detail, dry):
            handed.append((lp.executor, why, detail))
            lp.executor, lp.exec_sid = "astra", None
            return "astra"

        with patch.object(run.worker, "call", side_effect=fake), \
                patch.object(run.time, "sleep", side_effect=sleeps.append), \
                patch.object(run, "hand_executor", side_effect=hand):
            summary = run.execute(lp, "executor", "Do the task.", "executor")
        self.assertIn("Done elsewhere.", summary)
        self.assertEqual(handed, [("opus", "cannot run", f"cannot run: {line}")])
        self.assertEqual([args[1] for args in calls], ["opus", "astra"])
        self.assertIn("Do the task.", calls[1][2])
        self.assertEqual(sleeps, [])

    def test_an_executor_that_cannot_run_with_nobody_to_take_it_is_blocked_on_the_line(self):
        line = "error: unknown option '--effort'"
        calls, fake = self.worker([(1, "", "s1", f"{line}\n")])
        with patch.object(run.worker, "call", side_effect=fake), \
                patch.object(run.time, "sleep", side_effect=AssertionError("waited")), \
                patch.object(run, "hand_executor", return_value=None):
            with self.assertRaises(run.Blocked) as blocked:
                run.execute(self.executor_loop(), "executor", "Do the task.", "executor")
        self.assertEqual(len(calls), 1)
        self.assertIn(line, str(blocked.exception))
        self.assertTrue(blocked.exception.section.startswith("## Blocked\n"))
        self.assertIn(line, blocked.exception.section)

    def test_an_adapter_that_stops_before_its_harness_is_read_off_its_own_stderr(self):
        # opencode.sh says `opencode is not installed` on its own stderr, before it hands the
        # harness `2>"$out/stderr.log"`: the real worker.call has to carry that line into the
        # turn's diagnostics, or the classifier never sees it.
        adapter = self.root / "opencode.sh"
        adapter.write_text(f"#!{sys.executable}\nimport sys\n"
                           "if sys.argv[1] == 'run':\n"
                           "    print('opencode.sh: opencode is not installed', file=sys.stderr)\n"
                           "sys.exit(2)\n")
        adapter.chmod(0o755)
        out = self.root / "round-1" / "executor"
        logs = []
        with patch.object(config, "adapter", return_value=adapter), \
                patch.object(run, "transient_wait", side_effect=AssertionError("waited")):
            with self.assertRaises(run.CannotRun) as broken:
                run.call_retrying(self.cfg, "mimo", "body", self.root, out, "executor", None,
                                  logs.append)
        self.assertIn("opencode.sh: opencode is not installed", str(broken.exception))
        self.assertIn("opencode is not installed", (out / "stderr.log").read_text())
        self.assertFalse((out / "adapter-stderr.log").exists())

    def test_a_pr_review_whose_reviewers_cannot_run_ends_blocked(self):
        # `--review-pr` has no task loop around its review: a CannotRun out of it must still
        # end `blocked` on the line, not in an `error` the tick would retry into that harness.
        run_dir = config.RUNS / "20260923-1200-review-pr"
        run_dir.mkdir(parents=True)
        (run_dir / "log.txt").touch()
        run.save_state(run_dir, {"run_id": run_dir.name, "state": "running",
                                 "launched_session": None})
        repo, wt = self.root / "repo", self.root / "pr-checkout"
        repo.mkdir()
        wt.mkdir()
        info = {"state": "OPEN", "headRefOid": "abc", "baseRefName": "main",
                "title": "T", "author": "a", "body": ""}
        line = "opencode.sh: opencode is not installed"
        with patch.object(run, "pr_view", return_value=info), \
                patch.object(run, "checkout_for", return_value=repo), \
                patch.object(run, "disk_pressure", return_value=False), \
                patch.object(run, "git", return_value="sha"), \
                patch.object(run, "make_worktree", return_value=(wt, "b")), \
                patch.object(run, "history_start"), \
                patch.object(run, "exclude_junk"), \
                patch.object(run, "collect_usage", return_value={}), \
                patch.object(run, "project_lessons", return_value=""), \
                patch.object(run, "review", side_effect=run.CannotRun("mimo", line)), \
                patch.object(run, "post_review", side_effect=AssertionError("posted")):
            state = run.review_pr(self.cfg, run_dir, "https://github.com/o/r/pull/1",
                                  {"--review": "mimo"}, lambda _: None)
        saved = run.read_state(run_dir)
        for record in (state, saved):
            self.assertEqual((record["state"], record["verdict"]), ("blocked", "BLOCKED"))
            self.assertIn(line, record["error"])
            self.assertIn(line, record["blocked"])
        self.assertIn(line, (run_dir / "result.md").read_text())


if __name__ == "__main__":
    unittest.main()
