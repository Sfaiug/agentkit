"""Provider refusals are handed over once, while transport deaths still retry."""

from contextlib import ExitStack
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, run, usage, watch  # noqa: E402


class RefusalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix=".refusal-", dir=REPO)
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.root = root
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for key in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, key, root / key.lower()))
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(root), "AGENTKIT_SESSION": "", "AGENTKIT_RUN_DIR": "",
            "AGENTKIT_DISCORD_WEBHOOK": "off", "AGENTKIT_TMUX_SOCKET": "refusal-test",
            "TMUX_TMPDIR": str(root), "PYTHONDONTWRITEBYTECODE": "1",
            # this HOME's OpenCode config, never the caller's: mimo is payg
            "OPENCODE_CONFIG_DIR": str(root / ".config/opencode")}))
        config.ensure_dirs()
        self.cfg = config.load()
        self.now = time.time()
        self.marked = []
        self.replenished = []
        self.stack.enter_context(patch.object(
            usage, "replenish",
            side_effect=lambda cfg, provider: self.replenished.append(provider) or (False, 0.0)))
        self.stack.enter_context(patch.object(
            usage, "mark_exhausted",
            side_effect=lambda cfg, provider, until=None: self.marked.append(
                (provider, until)) or until))

    def worker(self, *, calls=None, code=1, text="", session="s1", events="", stderr="",
                 final=""):
        calls = [] if calls is None else calls

        def call(*args, **kwargs):
            calls.append(args)
            out = Path(args[4])
            out.mkdir(parents=True, exist_ok=True)
            (out / "prompt.md").write_text("You are the executor.\n")
            (out / "final.md").write_text(final)
            (out / "stderr.log").write_text(stderr)
            (out / "events.jsonl").write_text(events)
            (out / "session_id").write_text(session)
            return code, text, session, False

        return calls, call

    def planned(self, *rows):
        """A fake worker.call playing one row of worker kwargs per call, holding the last."""
        calls = []
        fakes = [self.worker(calls=calls, **row)[1] for row in rows]

        def call(*args, **kwargs):
            return fakes[min(len(calls), len(fakes) - 1)](*args, **kwargs)

        return calls, call

    def providers(self, openai_used=100, anthropic_used=100, meta_used=100):
        def meter(name, used):
            return {"name": name, "used": used, "resets_at": self.now + 604800,
                    "window_secs": 604800, "pace": None}
        return {
            "openai": {"meters": [meter("weekly", openai_used)], "resets": 0},
            "anthropic": {"meters": [meter("weekly_all", anthropic_used)], "resets": 0},
            "meta": {"meters": [meter("weekly", meta_used)], "resets": 0},
        }

    def test_turn_failed_capacity_resumes_the_same_session_without_handover(self):
        calls, fake = self.planned(
            {"events": '{"type":"turn.failed","error":{"message":"Selected model is at '
                       'capacity. Try a different model"}}'},
            {"code": 0, "text": "## Summary\nDone.\n", "final": "## Summary\nDone.\n"})
        lines, sleeps = [], []
        with patch.object(run.worker, "call", side_effect=fake), \
                patch.object(run.time, "sleep", side_effect=sleeps.append):
            code, _, session, dead = run.call_retrying(
                self.cfg, "astra", "body", self.root, self.root / "out", "executor",
                None, lines.append)
        self.assertEqual((code, dead, session), (0, False, "s1"))
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1][6], "s1")
        self.assertEqual(sleeps, [60])
        self.assertTrue(any("transient" in line and "at capacity" in line for line in lines),
                        lines)
        self.assertEqual(self.marked, [])

    def test_stderr_capacity_resumes_without_handover(self):
        calls, fake = self.planned(
            {"stderr": "Selected model is at capacity"},
            {"code": 0, "text": "## Summary\nDone.\n", "final": "## Summary\nDone.\n"})
        lines, sleeps = [], []
        with patch.object(run.worker, "call", side_effect=fake), \
                patch.object(run.time, "sleep", side_effect=sleeps.append):
            code, _, _, dead = run.call_retrying(
                self.cfg, "astra", "body", self.root, self.root / "out", "executor",
                None, lines.append)
        self.assertEqual((code, dead, len(calls)), (0, False, 2))
        self.assertEqual(sleeps, [60])
        self.assertTrue(any("transient" in line for line in lines), lines)
        self.assertFalse(any("nothing is picked" in line for line in lines), lines)

    def test_empty_exit_without_signature_resumes_with_growing_waits(self):
        calls, fake = self.planned(
            {}, {},
            {"code": 0, "text": "## Summary\nDone.\n", "final": "## Summary\nDone.\n"})
        sleeps = []
        with patch.object(run.worker, "call", side_effect=fake), \
                patch.object(run.time, "sleep", side_effect=sleeps.append):
            code, _, _, dead = run.call_retrying(
                self.cfg, "astra", "body", self.root, self.root / "out", "executor", None,
                lambda _: None)
        self.assertEqual((code, dead, len(calls), sleeps), (0, False, 3, [60, 300]))

    def test_exit_zero_answer_ignores_stream_warning_and_does_not_spend_reset(self):
        calls, fake = self.worker(
            code=0, text="# Summary\n\nI finished the work and committed it.",
            final="# Summary\n\nI finished the work and committed it.",
            events='{"type":"stream_error","message":"429 Too Many Requests; retrying"}',
            stderr="[warn] request failed: rate limit; retried and succeeded")
        with patch.object(run.worker, "call", side_effect=fake):
            code, text, _, dead = run.call_retrying(
                self.cfg, "astra", "body", self.root, self.root / "out", "executor", None,
                lambda _: None)
        self.assertEqual((code, dead, len(calls)), (0, False, 1))
        self.assertIn("finished the work", text)
        self.assertEqual((self.marked, self.replenished), ([], []))

    def test_exit_zero_recovered_stream_error_does_not_discard_plain_answer(self):
        calls, fake = self.worker(
            code=0, text="Ran the tests and pushed the branch.",
            final="Ran the tests and pushed the branch.",
            events=('{"type":"stream_error","error":{"message":"rate limit reached, '
                    'retrying in 2s"}}\n{"type":"turn.completed"}'))
        with patch.object(run.worker, "call", side_effect=fake):
            code, text, _, dead = run.call_retrying(
                self.cfg, "astra", "body", self.root, self.root / "out", "executor", None,
                lambda _: None)
        self.assertEqual((code, dead, len(calls)), (0, False, 1))
        self.assertEqual(text, "Ran the tests and pushed the branch.")
        self.assertEqual((self.marked, self.replenished), ([], []))

    def test_exit_zero_terminal_capacity_event_is_transient(self):
        calls, fake = self.planned(
            {"code": 0,
             "events": '{"type":"turn.failed","error":{"message":"at capacity"}}'},
            {"code": 0, "text": "## Summary\nDone.\n", "final": "## Summary\nDone.\n"})
        lines, sleeps = [], []
        with patch.object(run.worker, "call", side_effect=fake), \
                patch.object(run.time, "sleep", side_effect=sleeps.append):
            code, _, _, dead = run.call_retrying(
                self.cfg, "astra", "body", self.root, self.root / "out", "executor",
                None, lines.append)
        self.assertEqual((code, dead, len(calls)), (0, False, 2))
        self.assertEqual(sleeps, [60])
        self.assertTrue(any("transient" in line for line in lines), lines)
        self.assertEqual(self.marked, [])

    def test_exit_zero_terminal_quota_event_uses_reset_policy(self):
        calls, fake = self.worker(
            code=0,
            events='{"type":"turn.failed","error":{"message":"usage limit"}}')
        with patch.object(run.worker, "call", side_effect=fake):
            with self.assertRaises(run.RanDry):
                run.call_retrying(self.cfg, "astra", "body", self.root,
                                  self.root / "out", "executor", None, lambda _: None)
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.marked[0][0], "openai")

    def test_overloaded_fault_resumes_without_parking_the_provider(self):
        calls, fake = self.planned(
            {"stderr": "529 overloaded"},
            {"code": 0, "text": "## Summary\nDone.\n", "final": "## Summary\nDone.\n"})
        sleeps = []
        with patch.object(run.worker, "call", side_effect=fake), \
                patch.object(run.time, "sleep", side_effect=sleeps.append):
            code, _, _, dead = run.call_retrying(
                self.cfg, "opus", "body", self.root, self.root / "out", "executor",
                None, lambda _: None)
        self.assertEqual((code, dead, len(calls)), (0, False, 2))
        self.assertEqual(sleeps, [60])
        self.assertEqual(self.marked, [])

    def test_nobody_to_hand_to_parks_exhausted_with_refusal_message(self):
        lp = SimpleNamespace(cfg=self.cfg, state={"executor": "astra"}, executor="astra",
                             exec_sid=None, wt=self.root, turn_limit=60, rnd=1,
                             dir=lambda name: self.root / "round-1" / name,
                             role=lambda role: role, save=lambda: None, log=lambda _: None)
        calls, fake = self.worker(
            events='{"type":"turn.failed","error":{"message":"You have hit your usage limit"}}')
        with patch.object(run.worker, "call", side_effect=fake), \
                patch.object(run, "hand_executor", return_value=None):
            with self.assertRaises(run.QuotaDry) as parked:
                run.execute(lp, "executor", "body", "executor")
        self.assertEqual(len(calls), 1)
        self.assertIn("usage limit", str(parked.exception))
        self.assertNotIn("refusal_retry", lp.state)

    def receipt(self, name, executor="astra", refusal_model="astra", refusal_at=None):
        run_dir = config.RUNS / name
        run_dir.mkdir(parents=True)
        worktree = self.root / f"wt-{name}"
        worktree.mkdir()
        run.save_state(run_dir, {
            "run_id": name, "title": name, "state": "exhausted", "verdict": None,
            "executor": executor, "reviewer": "opus", "rounds": 1,
            "round_summaries": [], "repo": None, "worktree": str(worktree),
            "scratch": True, "no_merge": True, "findings": "", "quota_dry": True,
            "refusal_retry": {"model": refusal_model,
                              "at": self.now + 600 if refusal_at is None else refusal_at},
        })
        return run_dir

    def resume(self, run_dir, providers, now):
        launched = []
        with patch.object(run, "spawn_bg", side_effect=lambda *args, **kwargs:
                          launched.append((args, kwargs))):
            watch.resume_exhausted(self.cfg, providers, log=lambda _: None, now=now)
        return launched

    def test_tick_does_not_retry_capacity_park_before_ten_minutes(self):
        run_dir = self.receipt("capacity-wait")
        launched = self.resume(run_dir, self.providers(openai_used=10), self.now + 599)
        self.assertEqual(launched, [])

    def test_tick_resumes_executor_for_a_reviewer_refusal_before_deadline(self):
        run_dir = self.receipt("reviewer-wait", refusal_model="opus")
        launched = self.resume(run_dir, self.providers(openai_used=10), self.now + 599)
        self.assertEqual(len(launched), 1)

    def test_tick_does_not_retry_stale_refusal_when_all_providers_are_dry(self):
        run_dir = self.receipt("stale-refusal", refusal_at=self.now - 1)
        launched = self.resume(run_dir, self.providers(), self.now + 600)
        self.assertEqual(launched, [])

    def test_tick_retries_capacity_park_after_ten_minutes(self):
        run_dir = self.receipt("capacity-retry")
        launched = self.resume(run_dir, self.providers(openai_used=10), self.now + 600)
        self.assertEqual(len(launched), 1)
        self.assertEqual(launched[0][0][1], ["resume", run_dir.name])

    def test_tick_uses_healthy_provider_when_refusing_model_is_still_ineligible(self):
        # every model works but Fable, so a third company is there to review opus
        self.cfg["defaults"]["workers"] = [n for n in config.offered(self.cfg) if n != "fable"]
        run_dir = self.receipt("capacity-handover")
        launched = self.resume(run_dir, self.providers(openai_used=100, anthropic_used=10),
                               self.now + 600)
        self.assertEqual(len(launched), 1)
        expected = launched[0][1]["expected"]
        self.assertNotEqual(expected["executor"], "astra")


if __name__ == "__main__":
    unittest.main()
