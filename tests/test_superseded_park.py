"""A parked run whose work a later run merged no longer says needs you.

An `exhausted`, `fail` or `error` run superseded by a later *merged* run -- the
same title, or relaunched `from:` its branch -- is settled: no `needs you`,
not unfinished, and the tick does not resume it. A parked run whose
replacement has not merged still needs you, exactly as before.

Entirely offline: a throwaway HOME, fake run receipts, fake usage providers,
and a fake hook on run.spawn_bg. No real adapter, model call or resume runs.
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
from agentkit import config, menu, notify, orch, run, watch

WEEK = 604800
SPENT = ("unfinished review; done-when and review are pending at round 4, but the round "
         "budget (3) is spent; split or re-scope the task")


def meter(name, used, resets_at, window=WEEK):
    return {"name": name, "used": used, "resets_at": resets_at, "window_secs": window,
            "pace": None}


class SupersededPark(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".run-superseded-park-", dir=REPO)
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
        config.ensure_dirs()
        self.cfg = config.load()
        config.save_session(self.cfg, "seat", "fable", ["opus", "astra", "spark"])
        self.now = time.time()
        self.logs = []
        self.log = self.logs.append

    def providers(self, openai_used=10, anthropic_used=100, meta_used=100):
        """Fake usage providers: openai refilled, the rest dry, unless told otherwise."""
        return {
            "anthropic": {"meters": [meter("weekly_all", anthropic_used, self.now + WEEK),
                                     meter("weekly_scoped", anthropic_used, self.now + WEEK)]},
            "openai": {"meters": [meter("weekly", openai_used, self.now + WEEK)]},
            "meta": {"meters": [meter("weekly", meta_used, self.now + WEEK)]},
        }

    def receipt(self, name, **extra):
        run_dir = config.RUNS / name
        run_dir.mkdir(parents=True)
        wt = self.root / f"wt-{name}"
        wt.mkdir(parents=True)
        base = {"run_id": name, "title": f"Parked run ({name})", "state": "exhausted",
                "verdict": None, "executor": "astra", "reviewer": "spark",
                "rounds": 3, "round_summaries": [{}, {}, {}],
                "launched_session": "seat", "repo": str(self.root),
                "worktree": str(wt), "branch": "run-x", "base": "main",
                "base_sha": "0" * 40, "error": SPENT,
                "started_at": self.now - 3600, "finished_at": self.now - 600}
        base.update(extra)
        run.save_state(run_dir, base)
        return run_dir

    def records(self):
        return [(directory, run.read_state(directory)) for directory in config.RUNS.iterdir()]

    def test_exhausted_run_replaced_by_a_merged_retry_is_settled(self):
        parked = self.receipt("20260925-1257-parked", title="Fix the parser")
        self.receipt("20260925-1713-retry", title="Fix the parser", state="pass",
                     verdict="PASS", merged=True, branch="run-y",
                     round_summaries=[{}], error=None,
                     started_at=self.now - 300, finished_at=self.now - 60)
        index = run.supersession_index(self.records())
        state = run.read_state(parked)
        self.assertTrue(run.is_superseded(state, None, index))
        self.assertTrue(run.settled(state, index))
        self.assertFalse(run.unfinished(state, index=index))
        self.assertFalse(menu.v5o_needs_look(state, index=index, now=self.now))
        self.assertEqual(run.status_state_word(state, index), "done")
        # without the index supersession is not read, as with any other ending
        self.assertFalse(run.settled(state))
        self.assertTrue(run.unfinished(state))

    def test_exhausted_run_with_an_unmerged_replacement_still_needs_you(self):
        parked = self.receipt("20260925-1257-parked", title="Fix the parser")
        self.receipt("20260925-1713-retry", title="Fix the parser", state="fail",
                     verdict="FAIL", branch="run-y", round_summaries=[{}],
                     error="the done-when failed",
                     started_at=self.now - 300, finished_at=self.now - 60)
        index = run.supersession_index(self.records())
        state = run.read_state(parked)
        self.assertFalse(run.settled(state, index))
        self.assertTrue(run.unfinished(state, index=index))
        self.assertTrue(menu.v5o_needs_look(state, index=index, now=self.now))
        self.assertEqual(run.status_state_word(state, index), "needs you")

    def test_failed_run_with_a_merged_from_relaunch_does_not_block_notify_done(self):
        failed = self.receipt("20260925-1308-failed", title="Fix the parser",
                              state="fail", verdict="FAIL", branch="ak/parser",
                              error="the done-when failed",
                              finished_at=self.now - 10)
        notify.record("seat", "done", "Shipped it", time=self.now - 30)
        facts = dict(session={"name": "seat"}, cfg=self.cfg, live={}, harness="claude",
                     auth_out={}, gh_out={}, token_out={}, previous={})
        found = watch.session_state("seat", self.now, records=self.records(), **facts)
        self.assertEqual(found["word"], "needs you")
        self.assertIn(f"run {failed.name} failed; declaration dropped", found["reason"])
        self.receipt("20260925-1713-relaunch", title="Fix the parser (continued)",
                     state="pass", verdict="PASS", merged=True, branch="ak/parser-2",
                     **{"from": "ak/parser", "repo": str(self.root)},
                     round_summaries=[{}], error=None,
                     started_at=self.now - 300, finished_at=self.now - 5)
        found = watch.session_state("seat", self.now, records=self.records(), **facts)
        self.assertEqual((found["word"], found["reason"]), ("done", "Shipped it"))

    def test_tick_does_not_resume_a_run_whose_replacement_merged(self):
        quota = self.receipt("20260925-1257-quota", title="Fix the parser",
                             quota_dry=True, error="every provider is out of budget")
        retry_at = self.now - 1
        errored = self.receipt("20260925-1258-error", title="Fix the dial",
                               state="error", error_retry_at=retry_at, error_retries=0,
                               error="executor astra died on API/transport errors")
        (errored / "task.md").write_text("# Fix the dial\n\n## Done when\n\n```bash\ntrue\n```\n")
        self.receipt("20260925-1713-retry", title="Fix the parser", state="pass",
                     verdict="PASS", merged=True, branch="run-y",
                     round_summaries=[{}], error=None,
                     started_at=self.now - 300, finished_at=self.now - 60)
        self.receipt("20260925-1714-retry", title="Fix the dial", state="pass",
                     verdict="PASS", merged=True, branch="run-z",
                     round_summaries=[{}], error=None,
                     started_at=self.now - 300, finished_at=self.now - 60)
        with patch.object(run, "spawn_bg",
                          side_effect=AssertionError("superseded: never resumed")):
            watch.resume_exhausted(self.cfg, self.providers(), log=self.log, now=self.now)
            watch.resume_errored(log=self.log, now=self.now)
        self.assertEqual(self.logs, [])
        self.assertEqual(run.read_state(quota)["state"], "exhausted")
        self.assertEqual(run.read_state(errored)["state"], "error")


if __name__ == "__main__":
    unittest.main()
