"""A follow-up never blocks a round and is deferred to a run of its own after the merge.

A reviewer hands one in with `--before` for a defect from before the task, or without it
for a smaller defect of this change that need not hold it: then its `--run` must fail on
the reviewed commit, where ak re-proves it.  After the merge it is a deferred line in the
owning seat's plan -- open until its check passes on the default branch, yet holding no
`ak notify done` -- and a fix run with that command as its done-when
(tests/test_followup_runs.py).  Offline: a real repository and plan; proofs run in a clone
of the reviewed commit.
"""

from contextlib import ExitStack
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from fixtures.sandbox import Sandbox, account_home
from agentkit import config, hand_in, plan, run

SEAT = "fix-api"


def probe(expression):
    return f"python3 -c 'import api; raise SystemExit(0 if ({expression}) else 7)'"


def followup(site, what, command, before=None):
    row = {"kind": "follow-up", "path": site.split(":")[0], "line": int(site.split(":")[1]),
           "what": what, "why": "breaks callers",
           "evidence": {"run": command, "returncode": 7, "output": ""}}
    if before:
        row["before"] = before
    return row


class HandedIn(unittest.TestCase):
    """What `ak hand-in follow-up` accepts, judged where the reviewer runs it."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-deferred-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.workspace = Path(tmp.name)
        (self.workspace / "api.py").write_text('mode = "branch"\n')

    def check(self, *args):
        return hand_in.checked(["follow-up", "api.py:1", "mode is wrong", "breaks callers", *args],
                               self.workspace)

    def test_without_before_a_follow_up_needs_a_command_that_fails_now(self):
        row = self.check("--run", "exit 7")
        self.assertEqual(row["kind"], "follow-up")
        self.assertNotIn("before", row)
        self.assertNotIn("Before the task", hand_in.item_text(row))
        with self.assertRaisesRegex(config.Error, "--run"):
            self.check("--quote", "mode")
        with self.assertRaisesRegex(config.Error, "exited 0"):
            self.check("--run", "true")
        # with --before it is proven on base later, whatever the command does here
        row = self.check("--run", "true", "--before", "base abc123")
        self.assertEqual(row["before"], "base abc123")
        self.assertIn("Before the task: base abc123", hand_in.item_text(row))


class Weighed(unittest.TestCase):
    """How the loop weighs a follow-up: on the reviewed commit without `--before`, on base
    with it; never as a reason to fail."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-deferred-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(account_home(self.root))
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
            "PYTHONDONTWRITEBYTECODE": "", "PYTHONPYCACHEPREFIX": "",
            "AGENTKIT_SESSION": "", "AGENTKIT_RUN_DIR": "",
            "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0"}))
        for key in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, key, self.root / key.lower()))
        for module, name in ((run.orch, "stop_scope"), (run, "note_turn_meters"),
                             (run, "history_role_tokens"), (run, "memory_cap_note"),
                             (run.history, "update_run")):
            self.stack.enter_context(patch.object(module, name, return_value=None))
        config.ensure_dirs()
        self.cfg = config.load()
        self.wt = self.root / "acme"
        self.wt.mkdir()
        run.git(self.wt, "init", "-qb", "main")
        run.git(self.wt, "config", "user.name", "Fixture")
        run.git(self.wt, "config", "user.email", "fixture@example.invalid")
        (self.wt / "api.py").write_text('mode = "base"\n')
        (self.wt / ".gitignore").write_text("__pycache__/\n")
        self.commit("Existing behaviour")
        self.base = run.git(self.wt, "rev-parse", "HEAD")
        run.git(self.wt, "checkout", "-qb", "ak/fix-api")
        (self.wt / "api.py").write_text('mode = "branch"\n')
        self.commit("Change the mode")
        self.head = run.git(self.wt, "rev-parse", "HEAD")
        directory = self.root / "run"
        (directory / "round-1").mkdir(parents=True)
        state = {"run_id": "deferred-fixture", "title": "Deferred", "state": "running",
                 "base": "main", "base_sha": self.base, "branch": "ak/fix-api", "rounds": 3,
                 "executor": "opus", "reviewer": "astra", "round_summaries": [],
                 "repo": str(self.wt), "worktree": str(self.wt)}
        self.lp = run.Loop(self.cfg, directory, state, {}, lambda _: None, self.wt,
                           "# Fixture", ["true"], "context", [])
        self.lp.rnd = 1

    def commit(self, message):
        run.git(self.wt, "add", ".")
        run.git(self.wt, "commit", "-qm", message)

    def weigh(self, *rows):
        submitted = run.weigh_review(self.lp, hand_in.Review([*rows, {"kind": "done"}]), self.head)
        return submitted, submitted.records[0]

    def test_a_follow_up_of_this_change_is_proven_on_the_reviewed_commit_and_never_blocks(self):
        submitted, row = self.weigh(followup("api.py:1", "mode is wrong", probe('api.mode == "fixed"')))
        self.assertEqual(submitted.verdict, "PASS")
        self.assertEqual(row["kind"], "follow-up")
        self.assertEqual(row["evidence"]["commit"], self.head)
        self.assertNotIn("base", row["evidence"])
        self.assertNotIn("before", row)
        self.assertEqual(submitted.followup_checks, {hand_in.item_text(row): probe('api.mode == "fixed"')})
        self.assertEqual(submitted.followup_commits, {hand_in.item_text(row): self.head})
        self.assertEqual(submitted.preexisting, [])
        # one whose command passes on the reviewed commit proves nothing: a note, dropped
        submitted, row = self.weigh(followup("api.py:1", "mode is wrong", probe('api.mode == "branch"')))
        self.assertEqual(submitted.verdict, "PASS")
        self.assertEqual((row["kind"], row["dropped"]), ("note", "the command did not fail on this commit"))
        self.assertEqual(submitted.followups, [])
        # one from before the task is proven on base, as ever
        submitted, row = self.weigh(followup("api.py:1", "mode is wrong", probe('api.mode == "fixed"'),
                                             before=f"base {self.base}"))
        self.assertEqual(row["kind"], "follow-up")
        self.assertEqual(row["evidence"]["commit"], self.base)
        self.assertIn("Before the task", hand_in.item_text(row))
        self.assertEqual(submitted.followup_commits, {hand_in.item_text(row): self.base})
        self.assertEqual(submitted.preexisting, [row])


class Planned(Sandbox):
    """A deferred line: open until its check passes, holding no done."""

    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {
            config.SESSION_ENV: SEAT, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}))
        self.stack.enter_context(patch.object(plan.os, "killpg"))
        self.repo = config.CODE / "acme"
        self.repo.mkdir(parents=True)
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Plan test")
        self.git("config", "user.email", "plan@localhost")
        (self.repo / "base.txt").write_text("base\n")
        self.git("add", ".")
        self.git("commit", "-qm", "base")
        self.base = self.git("rev-parse", "HEAD")
        self.origin = self.root / "origin.git"
        subprocess.run(["git", "clone", "-q", "--bare", str(self.repo), str(self.origin)],
                       check=True, capture_output=True)
        self.git("remote", "add", "origin", str(self.origin))
        self.git("fetch", "-q", "origin")
        self.git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
        config.save_session(self.cfg, SEAT, "opus", ["opus"],
                            {"cwd": str(self.root), "repo": str(self.repo)})

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    def test_a_deferred_line_is_open_yet_owed_by_nobody_and_ticks_itself(self):
        line = plan.add(SEAT, "Fix api.py:1 - mode is wrong", "test -f feature.txt", self.repo,
                        proven=self.base, deferred=True)
        self.assertIn(f" · {plan.named(self.repo)} · deferred · written ", line)
        self.assertTrue(plan.deferred(line))
        self.assertEqual(plan.open_lines(SEAT), [line])
        self.assertEqual(plan.outcomes(SEAT), [])
        proven = plan.require_done(SEAT)            # nothing owed: a done may be recorded ...
        plan.still_done(SEAT, proven)
        self.assertEqual(plan.open_lines(SEAT), [line])    # ... while the line stays open
        plan.add(SEAT, "the hero looks calm", None)          # ... and an owed line still holds it
        with self.assertRaisesRegex(config.Error, r"1 plan line\(s\) still open"):
            plan.require_done(SEAT)
        # its fix lands: the check passes on the default branch and the line ticks
        (self.repo / "feature.txt").write_text("fixed\n")
        self.git("add", ".")
        self.git("commit", "-qm", "Fix the follow-up")
        self.git("push", "-q", "origin", "main")
        plan.verify(SEAT)
        [ticked, _] = plan.lines(SEAT)
        self.assertRegex(ticked, r"^- \[x\] Fix api\.py:1 - mode is wrong · check: `test -f feature\.txt` · .+ · deferred · written .+ · done [0-9a-f]{12} Fix the follow-up$")
        self.assertFalse(plan.is_open(ticked))


if __name__ == "__main__":
    unittest.main(verbosity=2)
