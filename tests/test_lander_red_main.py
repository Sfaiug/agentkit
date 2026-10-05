"""A red target gets one repair; the other line members keep their places and no blame.

Offline: local Git and real suites, with isolated state and fake repair launches and wakes.
"""

from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_lander as fixture
from agentkit import config, land, record, run, watch

SUITE = "test ! -f broken.txt"


class RedMain(unittest.TestCase):
    commit = fixture.Lander.commit
    advance = fixture.Lander.advance
    check = fixture.Lander.check
    wait = fixture.Lander.wait
    assert_cleaned = fixture.Lander.assert_cleaned

    def setUp(self):
        fixture.Lander.setUp(self)
        (self.repo / "AGENTS.md").write_text(f"---\ntests: {SUITE}\n---\n")
        self.commit("declare target suite")
        run.git(self.repo, "push", "origin", "main")
        self.base = run.git(self.repo, "rev-parse", "HEAD")
        self.prepared = []
        self.stack.enter_context(patch.object(run, "prepare", side_effect=self.prepare))
        self.spawn = self.stack.enter_context(patch.object(run, "spawn_bg", return_value=0))
        self.stack.enter_context(patch.object(watch, "seat_closed", return_value=False))
        config.session_path("seat").write_text("{}")

    def prepare(self, directory, opts, log, cfg, **_kw):
        self.prepared.append((directory, opts))
        record.save_state(directory, {**record.read_state(directory), "run_id": directory.name,
                                      "state": "queued", "slot_waiting": True,
                                      "first": bool(opts.get("--first"))})

    def member(self, name="first", joined=1, **files):
        directory = fixture.Lander.member(self, name, joined, once="true", **files)
        with record.record(directory) as state:
            state["launched_session"] = "seat"
        return directory

    def red_line(self):
        first = self.member()
        later = self.member("later", joined=2)
        self.advance(**{"broken.txt": "target breakage\n"})
        before = {directory: (directory / "run.json").read_bytes()
                  for directory in (first, later)}
        land.check_line(self.turn)
        return first, later, before

    def assert_parked(self, before):
        for directory, original in before.items():
            self.assertEqual((directory / "run.json").read_bytes(), original)

    def ready_repair(self, directory):
        tip = run.git(self.repo, "rev-parse", "origin/main")
        branch = f"ak/{directory.name}"
        run.git(self.repo, "checkout", "-b", branch, tip)
        run.git(self.repo, "rm", "broken.txt")
        (self.repo / "work.txt").write_text("work\n")
        self.commit("repair target")
        identity = run.commit_identity(self.repo)
        run.git(self.repo, "checkout", "main")
        with record.record(directory) as state:
            state.update(state="waiting", worktree=str(self.repo), branch=branch,
                         base="origin/main", target="main", base_sha=tip,
                         merge_method="squash", review={"verdict": "PASS", **identity},
                         waiting_on={"line": self.turn.name, "joined": 100},
                         finished_at=time.time())
        return branch

    def test_one_bare_probe_and_one_repair_leave_every_member_unblamed(self):
        first, _, before = self.red_line()
        self.assert_parked(before)
        self.wake.assert_not_called()
        self.assertEqual(len(self.checks), 2)
        self.assertEqual(self.checks[1][0], [SUITE])
        self.assertEqual(len(self.prepared), 1)
        directory, opts = self.prepared[0]
        self.assertTrue(opts["--first"])
        repair = record.read_state(directory)
        self.assertEqual(repair["repair"], {"target": "main", "command": SUITE})
        self.assertEqual(repair["repair_tip"], run.git(self.repo, "rev-parse", "origin/main"))
        self.assertIn("target's own tip", (directory / "task.md").read_text())
        for _ in range(3):
            land.check_line(self.turn)
        self.assertEqual(len(self.prepared), 1)
        self.assertEqual(len(self.checks), 2)
        self.assert_parked(before)
        self.wake.assert_not_called()
        self.assertIn("Tree: ", (first / "target-probe.log").read_text())
        self.assert_cleaned()

    def test_only_the_repair_lands_until_the_target_tree_changes(self):
        first, later, before = self.red_line()
        self.assertEqual(len(self.prepared), 1)
        repair = self.prepared[0][0]
        branch = self.ready_repair(repair)
        self.assertEqual([directory.name for directory, _ in land.line(self.turn)],
                         [first.name, later.name, repair.name])
        land.check_line(self.turn)
        tree = self.wait(repair)["land"]
        self.wake.assert_called_once_with(repair.name, unittest.mock.ANY)
        self.assert_parked(before)
        checks = len(self.checks)
        land.check_line(self.turn)
        self.assertEqual(len(self.checks), checks)
        self.assert_parked(before)
        run.git(self.repo, "merge", "--ff-only", branch)
        run.git(self.repo, "push", "origin", "main")
        with record.record(repair) as state:
            state.update(state="pass", merged=True)
        self.wake.reset_mock()
        land.check_line(self.turn)
        self.assertEqual(self.wait(first)["land"], tree)
        self.assertEqual([call.args[0] for call in self.wake.call_args_list],
                         [first.name, later.name])
        self.assertEqual(self.wait(later)["land"], tree)
        # The repair's green tree is first's too, but first's own `# once` check still runs.
        self.assertEqual(len(self.checks), checks + 1)
        self.assertIn("true", self.checks[-1][0])

    def test_a_green_bare_target_wakes_only_the_members_that_fail(self):
        first = self.member(**{"broken.txt": "branch breakage\n"})
        later = self.member("later", joined=2, **{"broken.txt": "other breakage\n"})
        self.advance()
        land.check_line(self.turn)
        self.assertIn(SUITE, self.wait(first)["fix"]["line"])
        self.assertIn(SUITE, self.wait(later)["fix"]["line"])
        self.assertCountEqual([call.args[0] for call in self.wake.call_args_list],
                              [first.name, later.name])
        self.assertEqual(len(self.checks), 3)
        self.assertIsNotNone(land.passed(self.turn, run.git(self.repo, "rev-parse",
                                                          "origin/main^{tree}")))
        self.assertEqual(self.prepared, [])
        with record.record(first) as state:
            state["state"] = "running"
        land.check_line(self.turn)
        self.assertIn("fix", self.wait(later))
        self.assertEqual(len(self.checks), 3)
        self.assertEqual(self.prepared, [])

    def test_a_recorded_green_target_needs_no_bare_probe(self):
        first = self.member(**{"broken.txt": "branch breakage\n"})
        self.advance()
        run.fetch(self.repo, "origin")
        tree = run.git(self.repo, "rev-parse", "origin/main^{tree}")
        land.note(self.turn, [tree], "earlier")
        land.check_line(self.turn)
        self.assertIn("fix", self.wait(first))
        self.assertEqual(len(self.checks), 1)
        self.assertEqual(self.prepared, [])

    def assert_skipped_head(self, failure, target_red=True):
        first = self.member(**{"base.txt": "branch\n"})
        later = self.member("later", joined=2,
                            **({} if target_red else {"broken.txt": "branch breakage\n"}))
        last = self.member("last", joined=3, **{"last.txt": "last\n"})
        if failure == "unavailable":
            with record.record(first) as state:
                state["review"]["head_sha"] = "f" * 40
        head = record.read_state(first)["review"]["head_sha"]
        self.advance(**{"base.txt": "target\n",
                        **({"broken.txt": "target breakage\n"} if target_red else {})})
        before = {directory: (directory / "run.json").read_bytes()
                  for directory in (later, last)}
        git_out = run.git_out

        def checkout(repo, *args, **kw):
            if failure == "checkout" and args[:2] == ("worktree", "add") and args[-1] == head:
                return 1, "checkout failed"
            return git_out(repo, *args, **kw)

        with patch.object(run, "git_out", side_effect=checkout):
            land.check_line(self.turn)
        self.assertIn("fix", self.wait(first))
        self.assertIn("Tree: ", (later / "target-probe.log").read_text())
        if target_red:
            self.assert_parked(before)
            self.wake.assert_called_once_with(first.name, unittest.mock.ANY)
            self.assertEqual(len(self.prepared), 1)
        else:
            self.assertIn(SUITE, self.wait(later)["fix"]["line"])
            self.assertCountEqual([call.args[0] for call in self.wake.call_args_list],
                                  [first.name, later.name, last.name])
            self.assertIn("land", self.wait(last))
            self.assertEqual(self.prepared, [])
        self.assert_cleaned()

    def test_a_conflicting_head_leaves_red_target_followers_unblamed(self):
        self.assert_skipped_head("conflict")

    def test_an_unavailable_head_leaves_red_target_followers_unblamed(self):
        self.assert_skipped_head("unavailable")

    def test_a_failed_head_checkout_leaves_red_target_followers_unblamed(self):
        self.assert_skipped_head("checkout")

    def test_a_green_target_blames_the_red_follower_after_a_skipped_head(self):
        self.assert_skipped_head("conflict", target_red=False)

    def test_another_commit_with_the_same_red_tree_gets_no_probe_or_repair(self):
        _, _, before = self.red_line()
        self.assertEqual(len(self.prepared), 1)
        run.git(self.repo, "commit", "--allow-empty", "-m", "same target tree")
        run.git(self.repo, "push", "origin", "main")
        land.check_line(self.turn)
        self.assertEqual(len(self.prepared), 1)
        self.assertEqual(len(self.checks), 2)
        self.assert_parked(before)
        self.wake.assert_not_called()

    def test_an_unmerged_repair_holds_its_tree_without_blame_or_relaunch(self):
        _, _, before = self.red_line()
        self.assertEqual(len(self.prepared), 1)
        repair = self.prepared[0][0]
        for ending in ("fail", "blocked", "pass", "error", "stopped"):
            with self.subTest(ending=ending):
                with record.record(repair) as state:
                    state.update(state=ending, slot_waiting=False, finished_at=time.time())
                    if ending == "error":
                        run.schedule_error_retry(state)
                land.check_line(self.turn)
                self.assertEqual(len(self.prepared), 1)
                self.assertEqual(len(self.checks), 2)
                self.assert_parked(before)
                self.wake.assert_not_called()

    def test_a_not_needed_repair_releases_the_same_target_tree(self):
        suite = f"{SUITE} && test ! -f ../flake"
        (self.repo / "AGENTS.md").write_text(f"---\ntests: {suite}\n---\n")
        self.commit("declare transient suite")
        run.git(self.repo, "push", "origin", "main")
        self.base = run.git(self.repo, "rev-parse", "HEAD")
        first = self.member()
        later = self.member("later", joined=2)
        self.advance()
        tree = run.git(self.repo, "rev-parse", "HEAD^{tree}")
        flake = config.WT / "flake"
        config.WT.mkdir(parents=True, exist_ok=True)
        flake.write_text("transient\n")
        land.check_line(self.turn)
        self.assertEqual(len(self.prepared), 1)
        self.wake.assert_not_called()
        flake.unlink()
        with record.record(self.prepared[0][0]) as state:
            state.update(state="not_needed", slot_waiting=False)
        land.check_line(self.turn)
        self.assertIn("land", self.wait(first))
        self.assertEqual([call.args[0] for call in self.wake.call_args_list],
                         [first.name, later.name])
        self.assertEqual(len(self.prepared), 1)
        self.assertEqual(len(self.checks), 3)
        self.assertEqual(run.git(self.repo, "rev-parse", "origin/main^{tree}"), tree)
        self.assertEqual(self.wait(later)["land"], self.wait(first)["land"])
        self.assert_cleaned()

    def test_a_reverted_target_tree_gets_a_new_repair_after_the_old_one_merged(self):
        _, _, before = self.red_line()
        tree = run.git(self.repo, "rev-parse", "origin/main^{tree}")
        repair = self.prepared[0][0]
        branch = self.ready_repair(repair)
        land.check_line(self.turn)
        run.git(self.repo, "merge", "--ff-only", branch)
        run.git(self.repo, "push", "origin", "main")
        with record.record(repair) as state:
            state.update(state="pass", merged=True)
        run.git(self.repo, "revert", "--no-edit", "HEAD")
        run.git(self.repo, "push", "origin", "main")
        self.assertEqual(run.git(self.repo, "rev-parse", "HEAD^{tree}"), tree)
        self.wake.reset_mock()
        land.check_line(self.turn)
        self.assertEqual(len(self.prepared), 2)
        new = self.prepared[1][0]
        self.assertNotEqual(new, repair)
        self.assertEqual(record.read_state(new)["repair_tip"],
                         run.git(self.repo, "rev-parse", "origin/main"))
        self.assert_parked(before)
        self.wake.assert_not_called()
        checks = len(self.checks)
        land.check_line(self.turn)
        self.assertEqual(len(self.prepared), 2)
        self.assertEqual(len(self.checks), checks)
        self.assert_parked(before)
        self.assert_cleaned()

    def test_a_crash_after_launch_reuses_the_receipt_without_another_probe(self):
        first = self.member()
        self.advance(**{"broken.txt": "target breakage\n"})
        before = {first: (first / "run.json").read_bytes()}
        start = run.start_followups

        def crash(*args, **kw):
            start(*args, **kw)
            raise RuntimeError("crash after receipt")

        with patch.object(run, "start_followups", side_effect=crash):
            land.check_line(self.turn)
        land.check_line(self.turn)
        self.assertEqual(len(self.prepared), 1)
        self.assertEqual(len(self.checks), 2)
        self.assert_parked(before)
        self.wake.assert_not_called()

    def test_a_changed_target_releases_the_line_while_the_repair_is_still_open(self):
        first, later, _ = self.red_line()
        run.git(self.repo, "rm", "broken.txt")
        self.commit("target repaired externally")
        run.git(self.repo, "push", "origin", "main")
        land.check_line(self.turn)
        self.assertIn("land", self.wait(first))
        self.assertEqual(self.wait(later)["land"], self.wait(first)["land"])
        self.assertEqual(len(self.prepared), 1)
        self.assertEqual([call.args[0] for call in self.wake.call_args_list],
                         [first.name, later.name])


if __name__ == "__main__":
    unittest.main(verbosity=2)
