"""A lander checks parked line members, then each member resumes to land or fix itself.

Offline: real git and gate commands in an acme sandbox, fake process ownership and wakes.
No model, delivery, live state or process cleanup is allowed.
"""

from contextlib import ExitStack
import fcntl
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, gate, gc, land, record, run, watch, worker

SUITE = "test -f base.txt && test ! -f broken.txt"
ONCE = "test -f tip.txt && test -f work.txt"


class LanderFixture:
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-lander-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "AGENTKIT_RUN": "", "AK_PARENT_RUN": "",
            "AK_RUN_LOG": "", "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0",
            "AK_HOST_READINGS": json.dumps({"cpus": 16, "load": 0, "free_mb": 16000}),
            "AGENTKIT_SESSION": "", "AGENTKIT_RUN_DIR": "",
            "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}))
        for name in ("HOME", "RUNS", "JOBS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, name, self.root / name.lower()))
        config.ensure_dirs()
        self.stack.enter_context(patch.object(land, "start_line"))
        self.stack.enter_context(patch.object(record, "process_active", return_value=False))
        self.wake = self.stack.enter_context(patch.object(watch, "launch_resume", return_value=999))
        self.stack.enter_context(patch.object(worker, "kill_marked"))
        for module, name in ((worker, "turn"), (worker, "call"), (run, "resolve_conflicts"),
                             (run, "do_merge"), (run, "stop_run_tree")):
            self.stack.enter_context(patch.object(module, name, side_effect=AssertionError(name)))
        self.remote = self.root / "origin.git"
        run.git(self.root, "init", "--bare", "--initial-branch=main", str(self.remote))
        self.repo = self.root / "acme"
        run.git(self.root, "clone", str(self.remote), str(self.repo))
        run.git(self.repo, "config", "user.name", "fixture")
        run.git(self.repo, "config", "user.email", "fixture@localhost")
        (self.repo / "base.txt").write_text("base\n")
        (self.repo / "AGENTS.md").write_text(f"---\ntests: {SUITE}\n---\n")
        self.commit("base")
        run.git(self.repo, "push", "origin", "main")
        self.base = run.git(self.repo, "rev-parse", "HEAD")
        self.turn = run.merge_lock_path(str(self.remote), "origin/main")
        self.checks = []
        self.gate_run = gate.run_done_when
        self.stack.enter_context(patch.object(gate, "run_done_when", side_effect=self.check))

    def commit(self, message):
        run.git(self.repo, "add", ".")
        run.git(self.repo, "commit", "-m", message)

    def advance(self, **files):
        run.git(self.repo, "checkout", "main")
        for name, text in {"tip.txt": "tip\n", **files}.items():
            (self.repo / name).write_text(text)
        self.commit("target moved")
        run.git(self.repo, "push", "origin", "main")
        # The checker must fetch rather than trust the previously recorded target tip.
        run.git(self.repo, "update-ref", "refs/remotes/origin/main", self.base)

    def member(self, name="fix-api", joined=1, method="squash", once=ONCE, **files):
        branch = f"ak/{name}"
        run.git(self.repo, "checkout", "-b", branch, self.base)
        for path, text in {"work.txt": "work\n", **files}.items():
            (self.repo / path).write_text(text)
        self.commit(name)
        identity = run.commit_identity(self.repo)
        run.git(self.repo, "checkout", "main")
        directory = config.RUNS / name
        directory.mkdir()
        (directory / "task.md").write_text(
            f"# {name}\n\n## Done when\n```bash\nfalse\n{once}  # once\n{SUITE}\n```\n")
        record.save_state(directory, {
            "run_id": name, "state": "waiting", "pid": 1234, "rounds": 3,
            "process_identity": {"boot": "fixture", "ticks": 1}, "scope": "none",
            "repo": str(self.repo), "worktree": str(self.repo), "branch": branch,
            "base": "origin/main", "target": "main", "base_sha": self.base,
            "merge_method": method, "review": {"verdict": "PASS", "done_when": True,
                "passed_head_sha": identity["head_sha"], **identity},
            "waiting_on": {"line": self.turn.name, "joined": joined}})
        return directory

    def check(self, cmds, cwd, log_path, *args, **kw):
        self.checks.append((list(cmds), Path(cwd), kw))
        self.assertNotEqual(Path(cwd), self.repo)
        self.assertTrue(kw["heavy"])
        self.assertIsNone(kw.get("run_dir"))
        return self.gate_run(cmds, cwd, log_path, *args, **kw)

    def wait(self, directory):
        return record.read_state(directory)["waiting_on"]

    def assert_cleaned(self):
        self.assertEqual(list(config.WT.glob("land-*")), [])
        self.assertEqual(run.git(self.repo, "worktree", "list", "--porcelain").count("worktree "), 1)

    def assert_only_target_green(self):
        tree = run.git(self.repo, "rev-parse", "origin/main^{tree}")
        self.assertEqual(set(land._trees(self.turn)[1]), {tree})


class Lander(LanderFixture, unittest.TestCase):
    def test_a_recorded_tree_is_forgotten_after_a_day(self):
        now = 1_000_000
        with patch.object(land.time, "time", return_value=now):
            land.note(self.turn, ["a", "b"], "leader")
        with patch.object(land.time, "time", return_value=now + land.KEEP - 1):
            for tree in ("a", "b"):
                self.assertEqual(land.passed(self.turn, tree)["tested"], tree)
        with patch.object(land.time, "time", return_value=now + land.KEEP + 1):
            for tree in ("a", "b"):
                self.assertIsNone(land.passed(self.turn, tree))

    def assert_a_shared_tree_runs_each_tasks_own_checks(self):
        head = self.member("head", once="true")
        tail = self.member("tail", joined=2, once="test -f acceptance.txt")
        self.advance()
        land.check_line(self.turn)
        land.check_line(self.turn)
        tree = self.wait(head)["land"]
        self.assertEqual(Path(self.wait(tail)["fix"]["log"]).name, f"lander-{tree}.log")
        self.assertIn("test -f acceptance.txt", [cmd for cmds, _, _ in self.checks for cmd in cmds])
        self.assert_cleaned()

    def test_a_tree_checked_in_the_same_pass_still_runs_another_tasks_checks(self):
        self.assert_a_shared_tree_runs_each_tasks_own_checks()

    def test_a_tree_green_from_an_earlier_pass_still_runs_another_tasks_checks(self):
        with patch.object(gate, "derived_heavy_limit", return_value=1):
            self.assert_a_shared_tree_runs_each_tasks_own_checks()

    def test_join_order_one_check_and_only_the_parked_verdict_changes(self):
        later = self.member("a-later", 20)
        first = self.member("z-first", 10.5)
        original = record.read_state(first)
        self.advance()
        run.git(self.repo, "config", "rebase.updateRefs", "true")
        land.check_line(self.turn)
        self.assertEqual([cmds for cmds, _, _ in self.checks], [[ONCE, SUITE]])
        self.wake.assert_called_once_with(first.name, unittest.mock.ANY)
        self.assertNotIn("land", self.wait(later))
        current = record.read_state(first)
        tree = current["waiting_on"].pop("land")
        self.assertEqual(current, original)
        self.assertEqual(land.passed(self.turn, tree)["tested"], tree)
        self.assertEqual(land.passed(self.turn, tree)["leader"], first.name)
        self.assertEqual(run.git(self.repo, "rev-parse", original["branch"]),
                         original["review"]["head_sha"])
        self.assert_cleaned()

    def test_running_live_and_other_line_records_are_never_written(self):
        directory = self.member()
        self.advance()
        for state, wait, active in (("running", {"line": self.turn.name, "joined": 1}, False),
                                     ("waiting", {"line": ".merge-other.lock", "joined": 1}, False),
                                     ("waiting", {"line": self.turn.name}, False),
                                     ("waiting", "not a line", False),
                                     ("waiting", {"line": self.turn.name, "joined": 1}, True)):
            with self.subTest(state=state, wait=wait, active=active):
                with record.record(directory) as current:
                    current.update(state=state, waiting_on=wait)
                before = (directory / "run.json").read_bytes()
                with patch.object(record, "process_active", return_value=active):
                    land.check_line(self.turn)
                self.assertEqual((directory / "run.json").read_bytes(), before)
        self.assertEqual(self.checks, [])
        self.wake.assert_not_called()

    def test_the_first_failing_once_command_and_log_wake_a_fix(self):
        failing = "printf 'FAIL once check\\n'; exit 1"
        directory = self.member(once=failing, **{"broken.txt": "broken\n"})
        self.advance()
        land.check_line(self.turn)
        fix = self.wait(directory)["fix"]
        self.assertIn(failing, fix["line"])
        self.assertIn("FAIL once check", fix["line"])
        self.assertIn(SUITE, Path(fix["log"]).read_text())
        self.assertIn("Tree: ", Path(fix["log"]).read_text())
        self.assert_only_target_green()
        self.wake.assert_called_once()
        self.assert_cleaned()

    def test_a_failing_declared_suite_wakes_a_fix(self):
        directory = self.member(**{"broken.txt": "broken\n"})
        self.advance()
        land.check_line(self.turn)
        self.assertIn(SUITE, self.wait(directory)["fix"]["line"])
        self.assert_only_target_green()
        self.wake.assert_called_once()

    def test_recorded_verdicts_resume_the_member_with_its_own_process(self):
        green = self.member("acme-land")
        red = self.member("acme-fix", joined=2, **{"broken.txt": "broken\n"})
        self.advance()
        owner = {"pid": 5678, "process_identity": {"boot": "fixture", "ticks": 2}}
        land.check_line(self.turn)
        self.assertCountEqual([call.args[0] for call in self.wake.call_args_list],
                              [green.name, red.name])
        for directory, verdict in ((green, "land"), (red, "fix")):
            with self.subTest(verdict=verdict):
                parked = record.read_state(directory)
                self.assertIn(verdict, parked["waiting_on"])
                with (patch.object(config, "load", return_value={}),
                      patch.object(record, "process_owner", return_value=owner),
                      patch.object(run, "place_here", return_value=None),
                      patch.object(run, "drive", return_value=0) as drive):
                    self.assertEqual(run.resume_run([directory.name]), 0)
                current = record.read_state(directory)
                self.assertEqual(current["waiting_on"], parked["waiting_on"])
                self.assertEqual(current["state"], "queued")
                self.assertEqual(current["resume_from"], "waiting")
                self.assertEqual(current["pid"], owner["pid"])
                self.assertEqual(current["process_identity"], owner["process_identity"])
                self.assertEqual(current["review"], parked["review"])
                drive.assert_called_once()
                self.assertEqual(drive.call_args.kwargs["prior"], current)

    def test_conflict_wakes_a_fix_without_a_gate_or_a_fixer(self):
        directory = self.member(**{"base.txt": "branch\n"})
        original = record.read_state(directory)
        self.advance(**{"base.txt": "target\n"})
        land.check_line(self.turn)
        fix = self.wait(directory)["fix"]
        self.assertIn("rebase of origin/main failed", fix["line"])
        self.assertIn("CONFLICT", Path(fix["log"]).read_text())
        self.assertEqual(self.checks, [])
        self.assertEqual(run.git(self.repo, "rev-parse", original["branch"]),
                         original["review"]["head_sha"])
        self.assertEqual(land._trees(self.turn)[1], {})
        self.wake.assert_called_once()
        self.assert_cleaned()

    def test_the_same_integration_tree_skips_the_suite_on_the_members_landing(self):
        for method in ("squash", "rebase", "merge"):
            with self.subTest(method=method):
                directory = self.member(method, method=method, **{"broken.txt": "broken\n"})
                state = record.read_state(directory)
                run.git(self.repo, "checkout", state["branch"])
                run.git(self.repo, "rm", "broken.txt")
                self.commit("landing fix")
                # A landing re-review keeps the earlier probe head after reviewing the fix.
                with record.record(directory) as current:
                    current["review"].update(run.commit_identity(self.repo))
                self.advance(**{f"{method}.txt": method})
                land.check_line(self.turn)
                state = record.read_state(directory)
                tree = state["waiting_on"]["land"]
                run.git(self.repo, "checkout", state["branch"])
                if method == "merge":
                    run.git(self.repo, "merge", "--no-edit", "origin/main")
                else:
                    run.git(self.repo, "rebase", "origin/main")
                self.assertEqual(run.git(self.repo, "rev-parse", "HEAD^{tree}"), tree)
                lp = SimpleNamespace(state=state, wt=self.repo, run_dir=directory,
                                     base_sha=state["base_sha"], target=state["target"],
                                     log=lambda _: None,
                                     write=lambda: record.save_state(directory, state))
                checks = len(self.checks)
                self.assertTrue(run.land_from_line(lp, "origin/main", lambda: True))
                self.assertEqual(state["final_check"]["tree_sha"], tree)
                self.assertEqual(state["final_check"]["suite"], SUITE)
                self.assertEqual(len(self.checks), checks)
                with record.record(directory) as current:
                    current["state"] = "running"

    def test_a_crash_after_green_reuses_the_tree_before_writing_the_verdict(self):
        directory = self.member()
        self.advance()
        with patch.object(record, "record", side_effect=RuntimeError("crash after green")):
            with self.assertRaisesRegex(RuntimeError, "crash after green"):
                land.check_line(self.turn)
        self.assertEqual(len(self.checks), 1)
        self.assertEqual(len(land._trees(self.turn)[1]), 1)
        self.assertNotIn("land", self.wait(directory))
        self.wake.assert_not_called()
        self.assert_cleaned()
        land.check_line(self.turn)
        self.assertEqual(len(self.checks), 1)
        self.assertIn("land", self.wait(directory))
        self.wake.assert_called_once()

    def test_a_crash_after_the_verdict_retries_the_wake_without_checking(self):
        directory = self.member()
        self.advance()
        self.wake.side_effect = [RuntimeError("crash before wake"), 999]
        with self.assertRaisesRegex(RuntimeError, "crash before wake"):
            land.check_line(self.turn)
        verdict = self.wait(directory)
        land.check_line(self.turn)
        self.assertEqual(self.wait(directory), verdict)
        self.assertEqual(len(self.checks), 1)
        self.assertEqual(self.wake.call_count, 2)

    def test_a_refused_wake_preserves_red_and_retries_without_a_check(self):
        directory = self.member(once="false")
        self.advance()
        self.wake.side_effect = [False, 999]
        land.check_line(self.turn)
        verdict = self.wait(directory)
        self.assertIn("fix", verdict)
        land.check_line(self.turn)
        self.assertEqual(self.wait(directory), verdict)
        self.assertEqual(len(self.checks), 2)
        self.assertEqual(self.wake.call_count, 2)

    def test_a_member_changed_during_the_check_is_never_written_or_woken(self):
        for ending in ("running", "stopped", "waiting"):
            with self.subTest(ending=ending):
                directory = self.member(ending)
                self.advance(**{f"{ending}.txt": ending})
                changed = []

                def race(cmds, cwd, log_path, *args, **kw):
                    answer = self.check(cmds, cwd, log_path, *args, **kw)
                    with record.record(directory) as current:
                        current.update(state=ending, waiting_on={"ref": "origin/main"},
                                       pid=5678, error="a concurrent change")
                    changed.append((directory / "run.json").read_bytes())
                    return answer

                with patch.object(gate, "run_done_when", side_effect=race):
                    land.check_line(self.turn)
                self.assertEqual((directory / "run.json").read_bytes(), changed[0])
                self.wake.assert_not_called()
                self.assert_cleaned()

    def test_one_pass_per_line(self):
        self.member()
        self.advance()
        with self.turn.with_suffix(".lander.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            land.check_line(self.turn)
        self.assertEqual(self.checks, [])
        self.wake.assert_not_called()
        land.check_line(self.turn)
        self.assertEqual(len(self.checks), 1)
        self.wake.assert_called_once()

    def test_a_delivery_does_not_block_a_pass(self):
        directory = self.member()
        self.advance()
        lp = SimpleNamespace(wt=self.repo, state={}, write=lambda: None)
        with run.merge_lock(lp, "origin/main"):
            land.check_line(self.turn)
            self.assertIn("land", self.wait(directory))
            with self.turn.open("a") as probe:
                with self.assertRaises(BlockingIOError):
                    fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.assertEqual(len(self.checks), 1)
        self.wake.assert_called_once()

    def test_a_heavy_turn_wait_never_marks_a_member_even_if_it_resumes(self):
        directory = self.member()
        self.advance()
        (config.HOME / config.CONFIG_NAME).write_text("max_gates = 1\n")
        changed = []
        with gate.gate_lock(None, 0).open("a") as holder:
            fcntl.flock(holder, fcntl.LOCK_EX)

            def poll(_seconds, **_kw):
                with record.record(directory) as current:
                    current.update(state="running", pid=5678)
                changed.append((directory / "run.json").read_bytes())
                fcntl.flock(holder, fcntl.LOCK_UN)

            def check(cmds, cwd, log_path, *args, **kw):
                self.assertEqual(gate._heavy_running(), 1)
                return self.check(cmds, cwd, log_path, *args, **kw)

            with (patch.dict(os.environ, {"AK_MAX_RUNS": ""}),
                  patch.object(gate, "time", wraps=gate.time) as clock,
                  patch.object(gate, "run_done_when", side_effect=check),
                  patch.object(gate, "mark_gate_wait", side_effect=AssertionError("member write")),
                  patch.object(gate.history, "close_step", side_effect=AssertionError("member step"))):
                clock.sleep.side_effect = poll
                land.check_line(self.turn)
        self.assertEqual((directory / "run.json").read_bytes(), changed[0])
        self.assertEqual(gate._heavy_running(), 0)
        self.assertFalse(gate.turn_held())
        self.wake.assert_not_called()

    def test_a_busy_suite_gives_back_and_retakes_the_checkers_heavy_turn(self):
        flag = self.root / "busy"
        cmd = (f"test -f '{flag}' || {{ touch '{flag}'; exit 75; }}; "
               'test "$AK_HEAVY_TURN" = 1')
        directory = self.member(once=cmd)
        self.advance()
        (config.HOME / config.CONFIG_NAME).write_text("max_gates = 1\n")
        released = []

        def poll(_seconds, **_kw):
            released.append(gate._heavy_running())

        with (patch.dict(os.environ, {"AK_MAX_RUNS": ""}),
              patch.object(gate, "time", wraps=gate.time) as clock,
              patch.object(gate, "mark_gate_wait", side_effect=AssertionError("member write")),
              patch.object(gate.history, "close_step", side_effect=AssertionError("member step"))):
            clock.sleep.side_effect = poll
            land.check_line(self.turn)
        self.assertEqual(released, [0])
        self.assertIn("land", self.wait(directory))
        self.assertEqual(gate._heavy_running(), 0)
        self.assertFalse(gate.turn_held())
        self.wake.assert_called_once()

    def test_a_sharded_suite_holds_derived_turns_without_claiming_its_member(self):
        pieces = self.root / "pieces"
        suite = f'printf "%s\\n" "$AK_SHARD" >> "{pieces}" && {SUITE}'
        directory = self.member()
        original = record.read_state(directory)
        self.advance(**{"AGENTS.md": f"---\ntests: {suite}\n---\n"})
        (config.HOME / config.CONFIG_NAME).write_text("max_gates = 9\n")

        def check(cmds, cwd, log_path, *args, **kw):
            self.assertEqual(gate._heavy_running(), 2)
            return self.check(cmds, cwd, log_path, *args, **kw)

        with (patch.dict(os.environ, {"AK_MAX_RUNS": "", "AK_HOST_READINGS": json.dumps(
                {"cpus": 4, "load": 0, "free_mb": 820})}),
              patch.object(gate, "run_done_when", side_effect=check),
              patch.object(gate, "mark_gate_wait", side_effect=AssertionError("member write")),
              patch.object(gate.history, "close_step", side_effect=AssertionError("member step"))):
            land.check_line(self.turn)
        self.assertEqual(sorted(pieces.read_text().splitlines()), ["1/2", "2/2"])
        current = record.read_state(directory)
        tree = current["waiting_on"].pop("land")
        self.assertEqual(current, original)
        self.assertEqual(land.passed(self.turn, tree)["tested"], tree)
        self.assertEqual(gate._heavy_running(), 0)
        self.assertFalse(gate.turn_held())
        self.wake.assert_called_once()
        self.assert_cleaned()

    def test_a_checked_member_claimed_before_the_verdict_ends_the_pass(self):
        first = self.member("first", joined=1)
        later = self.member("later", joined=2)
        self.advance()
        before = (first / "run.json").read_bytes()
        with patch.object(record, "process_active", side_effect=[False, False, True]):
            land.check_line(self.turn)
        self.assertEqual(len(self.checks), 1)
        self.assertEqual((first / "run.json").read_bytes(), before)
        self.assertNotIn("land", self.wait(later))
        self.wake.assert_not_called()

    def test_a_gate_changing_the_pinned_tree_never_marks_it_green(self):
        directory = self.member(once="printf changed >> work.txt")
        self.advance()
        land.check_line(self.turn)
        self.assertIn("Checkout changed during", self.wait(directory)["fix"]["line"])
        self.assert_only_target_green()
        self.wake.assert_called_once()
        self.assert_cleaned()

    def test_a_check_uses_a_symlinked_worktree_home_without_noatime_support(self):
        disk = self.root / "disk"
        (disk / "wt").mkdir(parents=True)
        linked = self.root / "linked"
        linked.symlink_to(disk, target_is_directory=True)
        directory = self.member()
        self.advance()
        with patch.object(config, "WT", linked / "wt"), \
                patch.object(os, "O_NOATIME", create=True):
            del os.O_NOATIME
            land.check_line(self.turn)
            self.assertIn("land", self.wait(directory))
            self.assert_cleaned()

    def test_an_abandoned_check_is_collected_with_its_git_registration(self):
        self.member()
        self.advance()
        temporary, git_out = tempfile.TemporaryDirectory, run.git_out
        abandoned = []

        def uncleaned(*args, **kw):
            tmp = temporary(*args, **kw)
            tmp._finalizer.detach()
            tmp.cleanup = lambda: None
            return tmp

        def leave_checkout(cwd, *args, **kw):
            if args[:2] == ("worktree", "remove"):
                return 1, "interrupted before cleanup"
            return git_out(cwd, *args, **kw)

        def interrupted(cmds, cwd, *args, **kw):
            scratch = Path(cwd)
            (scratch / "build").mkdir()
            (scratch / "build/output").write_text("unfinished output\n")
            abandoned.append(scratch)
            raise RuntimeError("simulated hard kill")

        # Skip both cleanup paths, as a hard kill does, without killing a real process.
        with patch.object(land.tempfile, "TemporaryDirectory", side_effect=uncleaned), \
                patch.object(run, "git_out", side_effect=leave_checkout), \
                patch.object(gate, "run_done_when", side_effect=interrupted):
            with self.assertRaisesRegex(RuntimeError, "simulated hard kill"):
                land.check_line(self.turn)
        scratch, = abandoned
        self.assertTrue(scratch.is_dir())
        self.assertIn(str(scratch), run.git(self.repo, "worktree", "list", "--porcelain"))
        later = time.time() + 30 * 86400
        self.assertEqual(gc.stale_worktrees(later, {str(scratch)}), [])
        planned = gc.stale_worktrees(later, set())
        self.assertEqual([item["path"] for item in planned], [str(scratch)])
        self.assertEqual(planned[0]["kind"], "orphan-worktree")
        gc.clear_tree(scratch, lambda _: None)
        self.assert_cleaned()


if __name__ == "__main__":
    unittest.main(verbosity=2)
