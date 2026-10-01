"""agentkit: a fetch that meets another fetch on the same ref goes again, never ends a passed run.

Offline: a throwaway bare `origin` and a passed run's clone of it in the system temp dir
(never the checkout, where an interrupted run's fake `git` could be committed), with a
temporary HOME. A fake `git` first on PATH answers the run's first fetches the way the
loser of two fetches racing for `refs/remotes/origin/main` hears it, and hands every other
call to the real git. The landing is the real one; the PR steps after the push are stubs.
"""

from contextlib import ExitStack
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import host, config, run

URL = "https://github.com/acme/widget/pull/7"
LOCKED = ("error: cannot lock ref 'refs/remotes/origin/main': is at 1111111 but expected 2222222\n"
          " ! 2222222..3333333  main       -> origin/main  (unable to update local ref)")
UNREACHABLE = "fatal: unable to access 'https://github.com/acme/widget/': Could not resolve host"
# another fetch holding git's lock, apostrophes in the ref name and the checkout path included
HELD = ("error: cannot lock ref 'refs/remotes/origin/acme's-fix': Unable to create "
        "'/srv/acme's repo/.git/refs/remotes/origin/acme's-fix.lock': File exists.\n\n"
        "Another git process seems to be running in this repository, e.g.\n"
        "remove the file manually to continue.\nFrom /srv/acme's repo/origin\n"
        " ! 2222222..3333333  acme's-fix -> origin/acme's-fix  (unable to update local ref)")
# beside a lost race, a stale name in the way of one ref, or a tag the fetch would clobber:
# no retry writes either
STALE = (LOCKED + "\nerror: cannot lock ref 'refs/remotes/origin/topic': "
         "'refs/remotes/origin/topic/child' exists; cannot create 'refs/remotes/origin/topic'")
CLOBBER = LOCKED + "\n ! [rejected]        v1         -> v1  (would clobber existing tag)"
ALWAYS = 10 ** 6
FAKE_GIT = """#!/bin/sh
if [ "$1" = -C ] && [ "$3" = fetch ]; then
    echo fetch >> "$FRR_FETCHES"
    if [ $(wc -l < "$FRR_FETCHES") -le "$FRR_FAILS" ]; then
        sleep "$FRR_DELAY"
        printf '%s\\n' "$FRR_ANSWER" >&2
        exit 1
    fi
fi
exec {git} "$@"
"""


class FetchRefRace(unittest.TestCase):
    def setUp(self):
        real_git = shutil.which("git")
        tmp = tempfile.TemporaryDirectory(prefix="fetch-ref-race-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        stack = ExitStack()
        self.addCleanup(stack.close)
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            stack.enter_context(patch.object(config, name, self.root / name.lower()))
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        (bin_dir / "git").write_text(FAKE_GIT.format(git=real_git))
        (bin_dir / "gh").write_text("#!/bin/sh\nexit 1\n")
        for tool in ("git", "gh"):
            (bin_dir / tool).chmod(0o755)
        self.fetches = self.root / "fetches"
        stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
            "PYTHONDONTWRITEBYTECODE": "1", "AGENTKIT_SESSION": "", "AGENTKIT_RUN_DIR": "",
            "AK_RUN_ROLE": "", "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0", "AGENTKIT_TMUX_SOCKET": "agentkit-test",
            "FRR_FETCHES": str(self.fetches), "FRR_FAILS": "0", "FRR_ANSWER": "",
            "FRR_DELAY": "0",
            "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"}))
        stack.enter_context(patch.object(host, "host_readings", return_value={
            "free_mb": 4096, "mem_total_mb": 16384, "load": 1, "cpus": 8,
            "unit_memory_current_mb": 100, "unit_memory_high_mb": 1000}))
        stack.enter_context(patch.object(run, "pickup_new_code", return_value=False))
        stack.enter_context(patch.object(run, "final_check", return_value=True))
        stack.enter_context(patch.object(run, "execute", side_effect=AssertionError("fixer")))
        stack.enter_context(patch.object(run, "call_retrying",
                                         side_effect=AssertionError("reviewer")))
        stack.enter_context(patch.object(run, "rights", return_value=(None, None)))
        stack.enter_context(patch.object(run, "open_pr", return_value=URL))
        stack.enter_context(patch.object(run, "wait_checks", return_value=True))
        self.merges = stack.enter_context(patch.object(
            run, "do_merge", side_effect=lambda lp, url, upstream, **_kw:
            lp.state.update(merged=True) or True))
        config.ensure_dirs()
        self.lp = self.passed_run()

    def passed_run(self):
        """A run of a bare origin whose ak/fix-api passed review and is ready to land."""
        remote, wt = self.root / "origin.git", self.root / "fix-api"
        run.git(self.root, "init", "--bare", "--initial-branch=main", str(remote))
        run.git(self.root, "clone", str(remote), str(wt))
        run.git(wt, "config", "user.name", "fixture")
        run.git(wt, "config", "user.email", "fixture@localhost")
        for name in ("base.txt", "api.txt"):
            (wt / name).write_text(f"{name}\n")
            run.git(wt, "add", name)
            run.git(wt, "commit", "-m", name)
            if name == "base.txt":
                run.git(wt, "push", "origin", "main")
                run.git(wt, "checkout", "-b", "ak/fix-api")
        run_dir = config.RUNS / "fix-api"
        run_dir.mkdir(parents=True)
        (run_dir / "log.txt").touch()
        head = run.git(wt, "rev-parse", "HEAD")
        tree = run.git(wt, "rev-parse", "HEAD^{tree}")
        cfg = config.load()
        executor_provider, reviewer_provider = run.review_providers(cfg, "opus", "astra")

        def log(msg):
            with (run_dir / "log.txt").open("a") as fh:
                fh.write(f"[00:00:00] {msg}\n")

        state = {
            "run_id": run_dir.name, "title": "fix-api", "state": "running", "verdict": "PASS",
            **run.process_owner(), "started_at": time.time(),
            "review": {"executor": "opus", "executor_provider": executor_provider,
                       "reviewer": "astra", "reviewer_provider": reviewer_provider,
                       "returncode": 0, "verdict": "PASS", "done_when": True,
                       "head_sha": head, "tree_sha": tree},
            "round_summaries": [{"round": 1, "verdict": "PASS", "done_when": True,
                                 "summary": "work", "head_sha": head, "tree_sha": tree}],
            "rounds": 3, "base": "origin/main", "target": "origin/main",
            "base_sha": run.git(wt, "rev-parse", "origin/main^{commit}"),
            "branch": "ak/fix-api", "worktree": str(wt), "repo": str(wt), "executor": "opus",
            "reviewer": "astra", "merge_method": "squash", "merged": False,
            "merge_failed": False, "merge_note": None, "findings": "",
        }
        run.save_state(run_dir, state)
        return run.Loop(cfg, run_dir, state, {}, log, wt, "body", ["true"], "context", [])

    def land(self, fails, answer, delay=0):
        """Land the run while its first `fails` fetches answer `answer` after `delay` seconds."""
        self.fetches.unlink(missing_ok=True)
        os.environ.update(FRR_FAILS=str(fails), FRR_ANSWER=answer, FRR_DELAY=str(delay))
        return run.merge(self.lp)

    def attempts(self):
        return len(self.fetches.read_text().splitlines())

    def test_a_fetch_that_lost_the_ref_lock_twice_goes_again_and_the_run_merges(self):
        self.assertTrue(self.land(2, HELD))
        self.merges.assert_called_once()
        self.assertTrue(self.lp.state["merged"])
        self.assertIsNone(self.lp.state["merge_note"])
        self.assertFalse(self.lp.state["merge_failed"])
        self.assertGreater(self.attempts(), 2)

    def test_any_other_fetch_failure_is_reported_as_before(self):
        for answer in (UNREACHABLE, STALE, CLOBBER):
            with self.subTest(answer=answer):
                self.assertFalse(self.land(ALWAYS, answer))
                self.assertEqual(self.attempts(), 1)
                self.assertEqual(self.lp.state["merge_note"],
                                 " ".join(f"git fetch origin failed: {answer}".split()))
                self.assertTrue(self.lp.state["merge_failed"])
        self.merges.assert_not_called()

    def test_a_ref_lock_outlasting_the_git_limit_is_reported_not_retried_forever(self):
        # The second call gets the remaining 0.5s, then one retry with that same budget.
        started = time.monotonic()
        with patch.object(run, "TOOL_CAP", 2):
            self.assertFalse(self.land(ALWAYS, LOCKED, delay=1.5))
        self.assertLess(time.monotonic() - started, 4)
        self.assertEqual(self.attempts(), 3)
        self.assertTrue(self.lp.state["merge_note"].startswith(
            "git fetch origin failed: error: cannot lock ref 'refs/remotes/origin/main'"))
        self.assertTrue(self.lp.state["merge_failed"])
        self.merges.assert_not_called()


if __name__ == "__main__":
    unittest.main()
