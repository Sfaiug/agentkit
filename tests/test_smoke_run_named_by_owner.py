"""An owner run whose title says `smoke-` counts like any other run.

The suite's own runs are told apart by `menu.smoke_run` -- their task or repo lives in
the suite's sandbox -- never by `smoke-` in a run directory's name, which an owner's
title can put there too.  So an owner's merged `smoke-` run supersedes an older errored
or exhausted run (the tick stands it down rather than retrying merged work) and votes
for its seat's project, while the suite's own merged run still does neither.

Entirely offline: a throwaway HOME, fake run receipts, fake usage providers and a
fake run.spawn_bg.  No real run directory, process or seat.
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
from agentkit import config, orch, run, watch

WEEK = 604800
TITLE = "Fix the smoke-test flake"


def meter(name, used, resets_at):
    return {"name": name, "used": used, "resets_at": resets_at, "window_secs": WEEK,
            "pace": None}


class SmokeRunNamedByOwner(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".run-smoke-named-", dir=REPO)
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
        self.repo = str(config.CODE / "acme")
        self.now = time.time()

    def receipt(self, name, **extra):
        run_dir = config.RUNS / name
        run_dir.mkdir(parents=True)
        wt = self.root / f"wt-{name}"
        wt.mkdir(parents=True)
        base = {"run_id": name, "title": TITLE, "state": "exhausted", "verdict": None,
                "executor": "astra", "reviewer": "spark", "rounds": 1,
                "round_summaries": [{}], "launched_session": "seat", "repo": self.repo,
                "worktree": str(wt), "branch": f"ak/{name}", "base": "main",
                "base_sha": "0" * 40, "error": "every provider is out of budget",
                "started_at": self.now - 3600, "finished_at": self.now - 600}
        base.update(extra)
        run.save_state(run_dir, base)
        return run_dir

    def merged(self, name, **extra):
        return self.receipt(name, **{"state": "pass", "verdict": "PASS", "merged": True,
                                     "error": None, "started_at": self.now - 300,
                                     "finished_at": self.now - 60, **extra})

    def test_exhausted_pass_stands_down_a_run_an_owner_smoke_run_merged(self):
        parked = self.receipt("20260925-1257-fix-the-smoke-test-flake", quota_dry=True)
        self.merged("20260925-1713-fix-the-smoke-test-flake")
        providers = {"openai": {"meters": [meter("weekly", 10, self.now + WEEK)]}}
        with patch.object(run, "spawn_bg") as spawn:
            watch.resume_exhausted(self.cfg, providers, log=lambda line: None, now=self.now)
        spawn.assert_not_called()
        self.assertTrue(run.read_state(parked).get("replaced"))

    def test_errored_pass_stands_down_a_run_an_owner_smoke_run_merged(self):
        parked = self.receipt("20260925-1257-fix-the-smoke-test-flake", state="error",
                              error_retry_at=self.now - 1, error_retries=0,
                              error="executor astra died on API/transport errors")
        (parked / "task.md").write_text(f"# {TITLE}\n\n## Done when\n\n```bash\ntrue\n```\n")
        self.merged("20260925-1713-fix-the-smoke-test-flake")
        with patch.object(run, "spawn_bg") as spawn:
            watch.resume_errored(log=lambda line: None, now=self.now)
        spawn.assert_not_called()
        self.assertNotIn("error_retry_at", run.read_state(parked))

    def test_superseded_by_reads_an_owner_smoke_run_but_not_the_suites(self):
        parked = run.read_state(self.receipt("20260925-1257-fix-the-smoke-test-flake"))
        # the suite's merged run of the same title, the newest of all, replaces nothing
        self.merged("20260925-1800-smoke-fix", repo=str(config.TMP / "smoke-abc" / "acme"),
                    finished_at=self.now - 30)
        self.assertIsNone(run.superseded_by(parked))
        self.merged("20260925-1713-fix-the-smoke-test-flake")
        self.assertEqual(run.superseded_by(parked), "20260925-1713-fix-the-smoke-test-flake")

    def test_an_owner_smoke_run_votes_for_its_seat(self):
        config.save_session(self.cfg, "suite", "fable", ["opus"])
        self.merged("20260925-1713-fix-the-smoke-test-flake")
        self.merged("20260925-1800-smoke-fix", launched_session="suite",
                    repo=str(config.TMP / "smoke-abc" / "acme"))
        found = orch.session_projects(config.session_records())
        self.assertEqual(found["seat"], self.repo)
        self.assertIsNone(found["suite"])


if __name__ == "__main__":
    unittest.main()
