"""A resume launch that never started leaves its run where the pass found it.

Four tick passes resume a parked run the same way: stamp the record, then `run.spawn_bg`.
When the launch never starts, the record reads exactly as the pass left it just before the
launch -- its state and its stamp, no interruption -- and the next tick retries on the
pass's own pacing.  A record another writer changed before the launch is theirs, and stays
exactly as they wrote it: an unrelated interruption is never undone as if it were ours.

Entirely offline: a temporary HOME, the real `spawn_bg` over a fake `orch.start_in_slice`
that cannot fork, fake usage providers, a stubbed upstream sha and login answer.  No process
is started and no model is called.
"""

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
from agentkit import config, orch, run, watch, worker

WEEK = 604800
SPAWN_BG = run.spawn_bg          # the real one, under every fake below
CONFLICT_NOTE = "the fixer did not finish the rebase of origin/main; it was aborted"
TASK = "# Fix the parser\n\n## Done when\n\n```bash\ntest -f deliverable\n```\n"
INTERRUPTION = ("recovery_pending", "interruption_reason", "interrupted_at")


def meter(name, used):
    return {"name": name, "used": used, "resets_at": time.time() + WEEK,
            "window_secs": WEEK, "pace": None}


class FailedLaunch(unittest.TestCase):
    """One patched home, and each pass's parked record next to its tick and its pacing."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-run-failed-launch-", dir=REPO)
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
            "AK_RUN_ROLE": "orchestrator"}))
        self.stack.enter_context(patch.object(orch, "user_manager", return_value=False))
        self.stack.enter_context(patch.object(run, "host_readings", return_value={
            "free_mb": 4096, "mem_total_mb": 16384, "load": 1, "cpus": 8,
            "unit_memory_current_mb": 100, "unit_memory_high_mb": 1000}))
        self.forks = []
        self.stack.enter_context(patch.object(orch, "start_in_slice", side_effect=self.fork))
        self.stack.enter_context(patch.object(worker, "auth_ok",
                                              return_value=(True, "claude: logged in")))
        self.stack.enter_context(patch.object(run, "upstream_sha", return_value="1" * 40))
        config.ensure_dirs()
        self.cfg = config.load()
        config.save_session(self.cfg, "seat", "fable", ["opus", "astra", "spark"])
        self.now = time.time()
        self.logs = []
        providers = {"anthropic": {"meters": [meter("weekly_all", 100),
                                              meter("weekly_scoped", 100)]},
                     "openai": {"meters": [meter("weekly", 10)]},
                     "meta": {"meters": [meter("weekly", 100)]}}
        # state: (its extra keys, one tick of its pass, when that pass may launch again)
        self.passes = {
            "waiting_login": (
                # the login came back on an earlier pass, which the pacing held
                {"waiting_for": "claude", "login_back_at": self.now - 300},
                lambda now: watch.resume_waiting_login(log=self.logs.append, now=now),
                lambda state: state["login_resume_at"] + watch.RESUME_EVERY),
            "exhausted": (
                {"quota_dry": True, "error": "every provider is out of budget"},
                lambda now: watch.resume_exhausted(self.cfg, providers, log=self.logs.append,
                                                   now=now),
                lambda state: state["exhausted_resume_at"] + watch.RESUME_EVERY),
            "error": (
                {"error_retry_at": self.now - 1, "error_retries": 2},
                lambda now: watch.resume_errored(log=self.logs.append, now=now),
                lambda state: state["error_retry_at"]),
            "waiting": (
                {"verdict": "FAIL", "error": CONFLICT_NOTE, "merge_note": CONFLICT_NOTE,
                 "waiting_on": {"ref": "origin/main", "sha": "0" * 40}},
                lambda now: watch.resume_waiting(log=self.logs.append, now=now),
                lambda state: state["waiting_resume_at"] + watch.RESUME_EVERY),
        }

    def fork(self, *args, **kwargs):
        self.forks.append(args)
        raise OSError("fixture cannot fork")

    def parked(self, word, tag=""):
        """A run parked as `word`, which its pass would resume now."""
        run_dir = config.RUNS / f"20260930-0314-{word.replace('_', '-')}{tag}"
        run_dir.mkdir(parents=True)
        wt = self.root / f"wt-{run_dir.name}"
        wt.mkdir()
        (run_dir / "task.md").write_text(TASK)
        run.save_state(run_dir, {
            "run_id": run_dir.name, "title": f"Parked run ({word})", "state": word,
            "verdict": None, "executor": "astra", "reviewer": "spark",
            "rounds": 3, "round_summaries": [], "launched_session": "seat",
            "repo": str(self.root), "worktree": str(wt),
            "branch": "run-x", "base": "main", "base_sha": "0" * 40,
            "error": "executor astra died on API/transport errors 3 times in round 1",
            "started_at": self.now - 600, "finished_at": self.now - 60,
            **self.passes[word][0]})
        return run_dir

    def tick(self, word, run_dir, now, change=None):
        """One pass over this run alone; `change` is another writer landing before the launch.

        Returns the record the pass handed `spawn_bg` as expected, and the one on disk when
        the launch began.
        """
        handed = []

        def spawn(directory, argv, expected=None, **kwargs):
            handed.append(dict(expected))
            if change:
                run.save_state(directory, change(dict(expected)))
            handed.append(run.read_state(directory))
            return SPAWN_BG(directory, argv, expected=expected, **kwargs)

        with patch.object(run, "run_dirs", return_value=[run_dir]), \
                patch.object(run, "spawn_bg", side_effect=spawn):
            self.passes[word][1](now)
        return handed

    def test_a_failed_launch_reads_as_the_pass_left_it_and_waits_out_its_pacing(self):
        for word in self.passes:
            with self.subTest(word):
                self.forks.clear()
                run_dir = self.parked(word)
                handed = self.tick(word, run_dir, self.now)
                self.assertEqual(len(self.forks), 1)
                after = run.read_state(run_dir)
                self.assertEqual(after, handed[0])
                self.assertEqual(after["state"], word)
                for key in INTERRUPTION:
                    self.assertNotIn(key, after)
                if word == "waiting_login":
                    self.assertTrue(after["login_back_at"])   # the login is back all the same
                due = self.passes[word][2](after)
                self.assertGreater(due, self.now)
                self.tick(word, run_dir, due - 1)
                self.assertEqual(len(self.forks), 1)          # paced
                self.tick(word, run_dir, due)
                self.assertEqual(len(self.forks), 2)          # retried once the pacing allows

    def test_a_record_another_writer_changed_before_the_launch_stays_theirs(self):
        stamps = {"waiting_login": "login_resume_at", "exhausted": "exhausted_resume_at",
                  "error": "error_retry_at", "waiting": "waiting_resume_at"}
        for word, stamp in stamps.items():
            changes = {
                "an unrelated interruption":
                    lambda state: run.interrupt(state, "the host restarted under it"),
                "the stamp taken off":
                    lambda state: {k: v for k, v in state.items() if k != stamp},
            }
            for tag, (what, change) in enumerate(changes.items()):
                with self.subTest(word, change=what):
                    self.forks.clear()
                    run_dir = self.parked(word, f"-{tag}")
                    _, written = self.tick(word, run_dir, self.now, change=change)
                    self.assertEqual(self.forks, [])          # nothing was launched
                    self.assertEqual(run.read_state(run_dir), written)


if __name__ == "__main__":
    unittest.main()
