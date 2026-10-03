"""Only the member that turns a green stack red fixes it; later members keep stacking.

Offline: real Git and checks, sandbox records, fake processes and wakes.
"""

from contextlib import contextmanager
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

from test_lander import LanderFixture, SUITE, land, record, run, gate


class MergeTrain(LanderFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.trees = []

    def check(self, cmds, cwd, log_path, *args, **kw):
        self.trees.append((run.git(cwd, "rev-parse", "HEAD^{tree}"),
                           set(run.git(cwd, "ls-tree", "--name-only", "HEAD").splitlines())))
        return super().check(cmds, cwd, log_path, *args, **kw)

    def stacked_files(self, tree):
        return set(run.git(self.repo, "ls-tree", "--name-only", tree).splitlines())

    def test_a_head_parked_again_rechecks_its_failed_tree(self):
        member = self.member()
        self.advance()
        land.note(self.turn, [run.git(self.repo, "rev-parse", "main^{tree}")], "earlier")
        calls = []

        def killed_once(cmds, cwd, log_path, *args, **kw):
            calls.append(cwd)
            if len(calls) == 1:
                return False, "$ suite\n[exit 137]\nkilled: silent for 60 minutes\n"
            return self.check(cmds, cwd, log_path, *args, **kw)

        with patch.object(gate, "run_done_when", side_effect=killed_once):
            land.check_line(self.turn)
            self.assertIn("fix", self.wait(member))
            with record.record(member) as current:
                current["waiting_on"].pop("fix")
            land.check_line(self.turn)
        self.assertEqual(len(calls), 2)
        self.assertIn("land", self.wait(member))
        self.assertEqual(land._trees(self.turn, "red_stacks")[1], {})
        self.assert_cleaned()

    def test_an_undecided_red_head_still_gets_its_own_check(self):
        member = self.member()
        self.advance()
        land.note(self.turn, [run.git(self.repo, "rev-parse", "main^{tree}")], "earlier")
        with (patch.object(gate, "run_done_when", return_value=(
                False, "$ suite\n[exit 137]\nkilled: silent for 60 minutes\n")),
              patch.object(record, "record", side_effect=RuntimeError("before verdict"))):
            with self.assertRaisesRegex(RuntimeError, "before verdict"):
                land.check_line(self.turn)
        self.assertNotIn("fix", self.wait(member))
        land.check_line(self.turn)
        self.assertEqual(len(self.checks), 1)
        self.assertIn("land", self.wait(member))
        self.assert_cleaned()

    def test_deciding_a_red_member_drops_the_red_stacks_behind_it(self):
        self.member("head")
        self.member("red", joined=2, **{"broken.txt": "x\n"})
        self.member("later", joined=3, **{"later.txt": "later\n"})
        self.advance()
        land.check_line(self.turn)
        self.assertEqual(land._trees(self.turn, "red_stacks")[1], {})
        self.assert_cleaned()

    def test_members_from_another_clone_stack_without_changing_its_branches(self):
        first = self.member("first", **{"first.txt": "first\n"})
        other = self.root / "acme-two"
        run.git(self.root, "clone", str(self.remote), str(other))
        run.git(other, "config", "user.name", "fixture")
        run.git(other, "config", "user.email", "fixture@localhost")
        with patch.object(self, "repo", other):
            later = self.member("later", joined=2, **{"later.txt": "later\n"})
        original = record.read_state(later)
        head = original["review"]["head_sha"]
        self.assertNotEqual(run.git_out(self.repo, "cat-file", "-e", head)[0], 0)
        self.member("last", joined=3, **{"last.txt": "last\n"})
        self.advance()
        land.check_line(self.turn)
        self.assertIn("land", self.wait(first))
        self.wake.assert_called_once_with(first.name, unittest.mock.ANY)
        self.assertTrue(any({"first.txt", "later.txt", "last.txt"} <= self.stacked_files(tree)
                            for tree in land._trees(self.turn)[1]))
        self.assertEqual(record.read_state(later), original)
        self.assertEqual(run.git(other, "rev-parse", original["branch"]), head)
        self.assertEqual(run.git(other, "worktree", "list", "--porcelain").count("worktree "), 1)
        self.assert_cleaned()

    def test_a_later_clone_uses_the_target_fetched_for_this_pass(self):
        first = self.member("first", **{"first.txt": "first\n"})
        other = self.root / "acme-two"
        run.git(self.root, "clone", str(self.remote), str(other))
        run.git(other, "config", "user.name", "fixture")
        run.git(other, "config", "user.email", "fixture@localhost")
        with patch.object(self, "repo", other):
            later = self.member("later", joined=2, **{"later.txt": "later\n"})
        original = record.read_state(later)
        self.advance()
        tip = run.git(self.repo, "rev-parse", "main")
        self.assertNotEqual(run.git_out(other, "cat-file", "-e", tip)[0], 0)
        land.check_line(self.turn)
        self.assertIn("land", self.wait(first))
        land.check_line(self.turn)
        self.assertIn("land", self.wait(later))
        self.assertEqual(run.git(other, "rev-parse", original["branch"]),
                         original["review"]["head_sha"])
        self.assertEqual(run.git(other, "worktree", "list", "--porcelain").count("worktree "), 1)
        self.assert_cleaned()

    def test_an_unavailable_follower_commit_does_not_stop_later_stacks(self):
        first = self.member("first", **{"first.txt": "first\n"})
        missing = self.member("missing", joined=2)
        with record.record(missing) as current:
            current["worktree"] = str(self.root / "gone-clone")
            current["review"]["head_sha"] = "f" * 40
        original = record.read_state(missing)
        self.member("later", joined=3, **{"later.txt": "later\n"})
        self.advance()
        land.check_line(self.turn)
        self.wake.assert_called_once_with(first.name, unittest.mock.ANY)
        self.assertIn("land", self.wait(first))
        self.assertEqual(record.read_state(missing), original)
        self.assertTrue(any({"first.txt", "later.txt"} <= self.stacked_files(tree)
                            for tree in land._trees(self.turn)[1]))
        self.assert_cleaned()

    def test_a_follower_checkout_failure_does_not_stop_later_stacks(self):
        first = self.member("first", **{"first.txt": "first\n"})
        failed = self.member("failed", joined=2, **{"failed.txt": "failed\n"})
        head = record.read_state(failed)["review"]["head_sha"]
        self.member("later", joined=3, **{"later.txt": "later\n"})
        self.advance()
        git_out = run.git_out

        def fail_checkout(repo, *args, **kw):
            if args[:2] == ("worktree", "add") and args[-1] == head:
                return 1, "checkout failed"
            return git_out(repo, *args, **kw)

        with patch.object(run, "git_out", side_effect=fail_checkout):
            land.check_line(self.turn)
        self.wake.assert_called_once_with(first.name, unittest.mock.ANY)
        self.assertTrue(any({"first.txt", "later.txt"} <= self.stacked_files(tree)
                            and "failed.txt" not in self.stacked_files(tree)
                            for tree in land._trees(self.turn)[1]))
        self.assertNotIn("fix", self.wait(failed))
        self.assert_cleaned()

    def test_only_the_newest_member_of_a_red_stack_gets_its_failure(self):
        suite = "test ! -f api.txt || test ! -f client.txt"
        first = self.member("api", **{"api.txt": "api\n",
            "AGENTS.md": f"---\ntests: {suite}\n---\n"})
        red = self.member("client", joined=2, **{"client.txt": "client\n"})
        later = self.member("later", joined=3, **{"later.txt": "later\n"})
        originals = {d: record.read_state(d) for d in (first, red, later)}
        self.advance()
        land.check_line(self.turn)
        self.assertEqual({call.args[0] for call in self.wake.call_args_list}, {first.name, red.name})
        self.assertIn("land", self.wait(first))
        fix = self.wait(red)["fix"]
        self.assertIn(suite, fix["line"])
        text = Path(fix["log"]).read_text()
        red_tree = text.split("Tree: ", 1)[1].splitlines()[0]
        self.assertTrue({"api.txt", "client.txt"} <= self.stacked_files(red_tree))
        self.assertIsNone(land.passed(self.turn, red_tree))
        self.assertTrue(any({"api.txt", "later.txt"} <= self.stacked_files(tree)
                            and "client.txt" not in self.stacked_files(tree)
                            for tree in land._trees(self.turn)[1]))
        self.assertEqual(self.wait(later), originals[later]["waiting_on"])
        for directory, key in ((first, "land"), (red, "fix")):
            current = record.read_state(directory)
            current["waiting_on"].pop(key)
            self.assertEqual(current, originals[directory])
        self.assert_cleaned()

    def test_each_red_member_leaves_only_itself_out_of_later_stacks(self):
        first = self.member("first", **{"first.txt": "first\n"})
        red = self.member("red", joined=2, **{"broken.txt": "broken\n"})
        middle = self.member("middle", joined=3, **{"middle.txt": "middle\n"})
        other = self.member("other-red", joined=4, **{"broken.txt": "other\n"})
        last = self.member("last", joined=5, **{"last.txt": "last\n"})
        self.advance()
        land.check_line(self.turn)
        self.assertEqual({call.args[0] for call in self.wake.call_args_list},
                         {first.name, red.name, other.name})
        for directory in (red, other):
            self.assertIn(SUITE, self.wait(directory)["fix"]["line"])
        for directory in (middle, last):
            self.assertNotIn("fix", self.wait(directory))
        self.assertTrue(any({"first.txt", "middle.txt", "last.txt"} <= self.stacked_files(tree)
                            for tree in land._trees(self.turn)[1]))
        self.assertTrue(all("broken.txt" not in self.stacked_files(tree)
                            for tree in land._trees(self.turn)[1]))
        self.assert_cleaned()

    def test_a_conflicting_member_does_not_stop_the_members_behind_it(self):
        first = self.member("first", **{"base.txt": "first\n"})
        clash = self.member("clash", joined=2, **{"base.txt": "clash\n"})
        later = self.member("later", joined=3, **{"later.txt": "later\n"})
        last = self.member("last", joined=4, **{"last.txt": "last\n"})
        self.advance()
        run.git(self.repo, "config", "rebase.updateRefs", "true")
        original = record.read_state(clash)
        land.check_line(self.turn)
        self.wake.assert_called_once_with(first.name, unittest.mock.ANY)
        self.assertEqual(record.read_state(clash), original)
        self.assertEqual(run.git(self.repo, "rev-parse", original["branch"]),
                         original["review"]["head_sha"])
        self.assertTrue(any({"later.txt", "last.txt"} <= files for _, files in self.trees))
        self.assertTrue(any({"later.txt", "last.txt"} <= self.stacked_files(tree)
                            for tree in land._trees(self.turn)[1]))
        self.assertNotIn("fix", self.wait(later))
        self.assertNotIn("fix", self.wait(last))
        self.assert_cleaned()

        # After the first lands, the conflict belongs to the clash's own head check.
        run.git(self.repo, "checkout", "ak/first")
        run.git(self.repo, "rebase", "origin/main")
        run.git(self.repo, "checkout", "main")
        run.git(self.repo, "merge", "--ff-only", "ak/first")
        run.git(self.repo, "push", "origin", "main")
        with record.record(first) as current:
            current["state"] = "running"
        self.wake.reset_mock()
        land.check_line(self.turn)
        self.wake.assert_called_once_with(clash.name, unittest.mock.ANY)
        self.assertIn("rebase of origin/main failed", self.wait(clash)["fix"]["line"])
        self.assert_cleaned()

    def test_a_red_head_is_removed_before_checking_the_members_behind_it(self):
        head = self.member("head", **{"broken.txt": "x\n"})
        self.member("later", joined=2, **{"later.txt": "later\n"})
        self.member("last", joined=3, **{"last.txt": "last\n"})
        self.advance()
        land.check_line(self.turn)
        self.wake.assert_called_once_with(head.name, unittest.mock.ANY)
        self.assertIn("fix", self.wait(head))
        self.assertTrue(any({"later.txt", "last.txt"} <= self.stacked_files(tree)
                            and "broken.txt" not in self.stacked_files(tree)
                            for tree in land._trees(self.turn)[1]))
        self.assert_cleaned()

    def test_a_crash_before_verdicts_reuses_each_tree_and_its_red_log(self):
        head = self.member("head")
        red = self.member("red", joined=2, **{"broken.txt": "x\n"})
        self.member("later", joined=3, **{"later.txt": "later\n"})
        self.advance()
        with patch.object(record, "record", side_effect=RuntimeError("crash before verdicts")):
            with self.assertRaisesRegex(RuntimeError, "crash before verdicts"):
                land.check_line(self.turn)
        count = len(self.checks)
        failures = land._trees(self.turn, "red_stacks")[1]
        self.assertTrue(failures)
        self.wake.assert_not_called()
        land.check_line(self.turn)
        self.assertEqual(len(self.checks), count)
        self.assertIn(self.wait(red)["fix"]["log"], [entry["log"] for entry in failures.values()])
        self.assertIn("land", self.wait(head))
        self.assert_cleaned()

    def test_a_crash_between_verdicts_keeps_the_red_stack_failure(self):
        suite = "test ! -f api.txt || test ! -f client.txt"
        head = self.member("api", **{"api.txt": "api\n",
            "AGENTS.md": f"---\ntests: {suite}\n---\n"})
        red = self.member("client", joined=2, **{"client.txt": "client\n"})
        later = self.member("later", joined=3, **{"later.txt": "later\n"})
        original = record.read_state(later)
        self.advance()
        save = record.record

        @contextmanager
        def crash_after_verdict(member):
            with save(member) as current:
                yield current
            raise RuntimeError("crash after one verdict")

        with patch.object(record, "record", side_effect=crash_after_verdict):
            with self.assertRaisesRegex(RuntimeError, "crash after one verdict"):
                land.check_line(self.turn)
        self.wake.assert_not_called()
        land.check_line(self.turn)
        self.assertIn("land", self.wait(head))
        fix = self.wait(red)["fix"]
        self.assertIn(suite, fix["line"])
        tree = Path(fix["log"]).read_text().split("Tree: ", 1)[1].splitlines()[0]
        self.assertTrue({"api.txt", "client.txt"} <= self.stacked_files(tree))
        self.assertEqual(record.read_state(later), original)
        with record.record(head) as current:
            current["state"] = "running"
        self.wake.reset_mock()
        land.check_line(self.turn)
        self.assertIn(red.name, [call.args[0] for call in self.wake.call_args_list])
        self.assertEqual(self.wait(red)["fix"], fix)
        self.assert_cleaned()

    def test_prefix_checks_can_run_side_by_side(self):
        self.member("head")
        self.member("later", joined=2, **{"later.txt": "later\n"})
        self.advance()
        started = threading.Barrier(2)

        def together(cmds, cwd, log_path, *args, **kw):
            started.wait(timeout=5)
            return self.check(cmds, cwd, log_path, *args, **kw)

        with patch.object(gate, "run_done_when", side_effect=together):
            land.check_line(self.turn)
        self.assertEqual(len(self.checks), 2)
        self.assertEqual(len({cwd for _, cwd, _ in self.checks}), 2)
        self.assert_cleaned()

    def test_rebuilding_retries_a_conflict_with_the_removed_red_member(self):
        first = self.member("first", **{"first.txt": "first\n"})
        red = self.member("red", joined=2, **{"base.txt": "red\n", "broken.txt": "x\n"})
        clash = self.member("clash", joined=3, **{"base.txt": "clash\n"})
        later = self.member("later", joined=4, **{"later.txt": "later\n"})
        self.advance()
        land.check_line(self.turn)
        self.assertEqual({call.args[0] for call in self.wake.call_args_list}, {first.name, red.name})
        self.assertNotIn("fix", self.wait(clash))
        self.assertNotIn("fix", self.wait(later))
        self.assertTrue(any("later.txt" in self.stacked_files(tree)
                            and run.git(self.repo, "show", f"{tree}:base.txt") == "clash"
                            for tree in land._trees(self.turn)[1]))
        self.assert_cleaned()

    def test_a_member_claimed_during_a_stack_check_is_never_sent_a_fix(self):
        first = self.member("first")
        red = self.member("red", joined=2, **{"broken.txt": "x\n"})
        self.advance()
        changed = []

        def race(cmds, cwd, log_path, *args, **kw):
            result = self.check(cmds, cwd, log_path, *args, **kw)
            if "broken.txt" in run.git(cwd, "ls-tree", "--name-only", "HEAD").splitlines():
                with record.record(red) as current:
                    current.update(state="running", pid=5678)
                changed.append((red / "run.json").read_bytes())
            return result

        with patch.object(gate, "run_done_when", side_effect=race):
            land.check_line(self.turn)
        self.assertTrue(changed)
        self.assertEqual((red / "run.json").read_bytes(), changed[-1])
        self.assertNotIn(red.name, [call.args[0] for call in self.wake.call_args_list])
        self.assert_cleaned()


if __name__ == "__main__":
    unittest.main(verbosity=2)
