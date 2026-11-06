"""A fix whose own checks pass on the fetched target ends without a model turn.

Black-box: AK_BIN runs through akbin.Home with fakeadapter's counted executor.
"""

import json
from pathlib import Path
import shlex
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.akinstall import Install
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

FIX = ("Your checkout starts on the target branch's tip, fetched when this run started. "
       "ak checked the command below there before your first turn. "
       "Fix the root cause so it passes, and show it failing before the "
       "fix and passing afterwards in your summary. If only the owner can decide, "
       'run `ak hand-in blocked "<question>"`.')
OLD_FIX = ("Your checkout starts on the target branch's tip, fetched when this run started: run "
           "the command below there first. If it passes there now, run `ak hand-in not-needed "
           '"<why>"`, with no edits or PR. Otherwise fix the root cause so it passes, and show it '
           "failing before the fix and passing afterwards in your summary. If only the owner "
           'can decide, run `ak hand-in blocked "<question>"`.')


class FixOnTip(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.rig = Rig(self.home, "widgets")
        akconfig.write(self.home, ["opus", "astra"], workers=["opus"], reviewers=["astra"])
        self.fakes = fakeadapter.install(self.home, claude="blocked", codex="pass")

    def launch(self, checks, *, body=FIX, front=None, merge=False, receipt=None):
        before = set(taskfile.runs(self.home))
        task = taskfile.write(self.home, self.rig.path, "Fix the API",
                              body=body, done_when=checks, front=front)
        if receipt is None:
            done = self.home.ak("run", str(task), *([] if merge else ["--no-merge"]),
                                timeout=300)
        else:
            # An unstarted follow-up receipt, as handed to a queued run.
            directory = (self.home.path / ".agentkit/runs" /
                         f"20260101-{len(before):04d}-fix-the-api")
            directory.mkdir(parents=True)
            (directory / "task.md").write_bytes(task.read_bytes())
            (directory / "run.json").write_text(json.dumps({
                "run_id": directory.name, "state": "queued", "slot_waiting": True,
                "repo": str(self.rig.path), "no_merge": True, "launched_session": None,
                "launch_opts": {"--no-merge": True},
                "followup": {"run": "source", "text": "Fix the API", "place": "api.py:1"},
                **receipt}))
            done = self.home.ak("run", "resume", directory.name, timeout=300)
        created = set(taskfile.runs(self.home)) - before
        self.assertEqual(len(created), 1)
        directory, = created
        return done, directory, json.loads((directory / "run.json").read_text())

    def assert_no_turn(self, done, directory, state, checks, tip):
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertEqual(state["state"], "not_needed")
        self.assertEqual(state["round_summaries"], [])
        self.assertEqual((self.fakes["claude"].n, self.fakes["codex"].n), (0, 0))
        result = (directory / "result.md").read_text()
        for check in checks:
            self.assertIn(check, state["not_needed"])
            self.assertIn(check, result)
        self.assertIn(tip, state["not_needed"])
        self.assertIn(tip, result)
        self.assertFalse(list(directory.glob("round-*")))
        self.assertFalse(Path(state["worktree"]).exists())
        self.assertNotIn(state["branch"], self.rig.branches(remote=False))
        self.assertEqual(self.rig.branches(), ["main"])

    def test_every_check_passing_on_the_fetched_tip_spends_no_turn(self):
        old = self.rig.head()
        tip = self.rig.commit({"fixed.txt": "fixed\n"})
        # Both the local branch and the tracking ref are stale until ak fetches.
        self.rig.git("reset", "--hard", old)
        self.rig.git("update-ref", "refs/remotes/origin/main", old)
        checks = ("test -f fixed.txt", "test -f .keep")
        done, directory, state = self.launch(checks)
        self.assert_no_turn(done, directory, state, checks, tip)
        self.assertIn("origin/main", state["not_needed"])
        self.assertEqual(self.rig.head(remote=False), old)

    def test_one_failed_check_reaches_the_first_executor_turn(self):
        checks = ("test -f .keep", "test -f retry.txt")
        done, directory, state = self.launch(checks)
        self.assertEqual(done.code, 1, done.out + done.err)
        self.assertEqual(state["state"], "blocked")
        self.assertEqual((self.fakes["claude"].n, self.fakes["codex"].n), (1, 0))
        prompt = (directory / "round-1/executor/prompt.md").read_text()
        self.assertIn(FIX, prompt)
        self.assertNotIn("run the command below there first", prompt)

    def test_saved_fix_tasks_keep_both_the_tip_check_and_their_not_needed_hand_in(self):
        self.fakes["claude"].behave("not-needed")
        for check in ("true", "false"):
            done, _, state = self.launch((check,), body=OLD_FIX)
            self.assertEqual(done.code, 0, done.out + done.err)
            self.assertEqual(state["state"], "not_needed")
            self.assertEqual(self.fakes["codex"].n, 0)
        self.assertEqual(self.fakes["claude"].n, 1)

    def test_an_unavailable_check_checkout_keeps_the_first_turn(self):
        for argument in ("--shared", "--detach"):
            with self.subTest(argument=argument):
                self.home.fake("git", '#!/bin/sh\nfor arg do\n'
                               f'  [ "$arg" != "{argument}" ] || exit 128\ndone\n'
                               'exec /usr/bin/git "$@"\n')
                done, _, state = self.launch(("true",))
                self.assertEqual(done.code, 1, done.out + done.err)
                self.assertEqual(state["state"], "blocked")
        self.assertEqual(self.fakes["claude"].n, 2)

    def test_target_refs_with_unpushed_local_work_still_reach_the_executor(self):
        self.rig.commit({"fixed.txt": "only on local main\n"}, push=False)
        check = "git cat-file -e origin/main:fixed.txt"
        done, _, state = self.launch((check,))
        self.assertEqual(done.code, 1, done.out + done.err)
        self.assertEqual(state["state"], "blocked")
        self.assertEqual(self.fakes["claude"].n, 1)

    def test_local_replacement_refs_cannot_supply_the_target_fix(self):
        tip = self.rig.head()
        local = self.rig.commit({"fixed.txt": "local replacement only\n"}, push=False)
        tree = self.rig.git("rev-parse", f"{local}^{{tree}}")
        replacement = self.rig.git("commit-tree", tree, "-m", "local replacement")
        self.rig.git("replace", tip, replacement)
        self.rig.git("reset", "--hard", tip)
        self.assertNotIn("fixed.txt", self.rig.files())
        done, _, state = self.launch(("test -f fixed.txt",))
        self.assertEqual(done.code, 1, done.out + done.err)
        self.assertEqual(state["state"], "blocked")
        self.assertEqual(self.fakes["claude"].n, 1)

    def test_fetched_target_refs_passing_with_a_stale_local_branch_spend_no_turn(self):
        old = self.rig.head()
        tip = self.rig.commit({"fixed.txt": "on the target\n"})
        self.rig.git("reset", "--hard", old)
        checks = ("git cat-file -e origin/main:fixed.txt",
                  f'test "$(git remote get-url origin)" = {shlex.quote(str(self.rig.bare))}')
        done, directory, state = self.launch(checks)
        self.assert_no_turn(done, directory, state, checks, tip)

    def test_a_tip_that_could_not_be_fetched_keeps_the_first_turn(self):
        self.rig.git("remote", "set-url", "origin", str(self.home.root / "missing.git"))
        done, _, state = self.launch(("true",), front={"base": "main"})
        self.assertEqual(done.code, 1, done.out + done.err)
        self.assertEqual(state["state"], "blocked")
        self.assertEqual(self.fakes["claude"].n, 1)

    def test_checks_that_cannot_run_or_finish_still_reach_the_executor(self):
        for check in ("exit 126", "exit 127", "kill -TERM $$", "timeout 0.01 sleep 30"):
            with self.subTest(check=check):
                done, _, state = self.launch((check,))
                self.assertEqual(done.code, 1, done.out + done.err)
                self.assertEqual(state["state"], "blocked")
        self.assertEqual((self.fakes["claude"].n, self.fakes["codex"].n), (4, 0))

    def test_the_target_tip_decides_even_when_the_base_is_different(self):
        tip = self.rig.branch("release", {"fixed.txt": "fixed\n"})
        checks = ("test -f fixed.txt",)
        done, directory, state = self.launch(checks, front={"target": "release"})
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertEqual(state["state"], "not_needed")
        self.assertIn(tip, state["not_needed"])
        self.assertIn("origin/release", state["not_needed"])
        self.assertEqual(self.fakes["claude"].n, 0)

    def test_checks_deferred_to_landing_are_left_for_landing(self):
        gh = GitHub(self.home)
        gh.grant(self.rig.slug, "WRITE")
        checks = ("test -f .keep",)
        done, directory, state = self.launch((*checks, "exit 1 # once"), merge=True)
        self.assert_no_turn(done, directory, state, checks, self.rig.head())
        self.assertFalse([call for call in self.home.calls("gh")
                          if call[:2] in (["pr", "create"], ["pr", "merge"])])

    def test_a_followup_record_also_identifies_a_fix_without_the_task_words(self):
        checks = ("test -f .keep",)
        done, directory, state = self.launch(checks, body="", receipt={})
        self.assert_no_turn(done, directory, state, checks, self.rig.head())

    def test_ordinary_runs_flaky_repairs_and_suite_splits_keep_their_turn(self):
        receipts = (None, {"repair": {"target": "main", "command": "true", "flaky": 1}},
                    {"split_suite": "true"})
        for receipt in receipts:
            with self.subTest(receipt=receipt):
                done, _, state = self.launch(("true",), body="", receipt=receipt)
                self.assertEqual(done.code, 1, done.out + done.err)
                self.assertEqual(state["state"], "blocked")
        self.assertEqual(self.fakes["claude"].n, 3)

    def test_checkout_context_alone_does_not_identify_a_fix(self):
        GitHub(self.home).grant(self.rig.slug, "WRITE")
        body = FIX.partition(".")[0] + ".\n\nAdd a retry policy."
        done, _, state = self.launch(("true", "false # once"), body=body, merge=True)
        self.assertEqual(done.code, 1, done.out + done.err)
        self.assertEqual(state["state"], "blocked")
        self.assertEqual(self.fakes["claude"].n, 1)

    def test_resuming_after_a_turn_never_checks_the_tip_again(self):
        self.fakes["claude"].behave("work", "blocked")
        self.fakes["codex"].behave("fail")
        done, directory, state = self.launch(("test -f retry.txt",), front={"rounds": 1})
        self.assertEqual(state["state"], "fail", done.out + done.err)
        # Now the target passes too; the saved work must still get its next round.
        self.rig.commit({"retry.txt": "already fixed\n"})
        before = (directory / "tip.log").read_bytes()
        install = Install(self.home)
        (install.path / "agentkit").mkdir(exist_ok=True)
        (install.path / "agentkit/run.py").write_text("raise AssertionError('resumed on another checkout')\n")
        done = self.home.run(install.ak, "run", "resume", directory.name, "--rounds", "2", timeout=300)
        state = json.loads((directory / "run.json").read_text())
        self.assertEqual(done.code, 1, done.out + done.err)
        self.assertEqual(state["state"], "blocked")
        self.assertEqual((directory / "tip.log").read_bytes(), before)
        self.assertEqual((self.fakes["claude"].n, self.fakes["codex"].n), (2, 1))


if __name__ == "__main__":
    unittest.main()
