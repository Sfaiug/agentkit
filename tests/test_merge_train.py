"""Only the member that turns a green stack red fixes it; later members keep stacking.

Offline: real Git and checks, sandbox records, fake processes and wakes.
"""

from contextlib import contextmanager
import fcntl
from pathlib import Path
import threading
from types import SimpleNamespace
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

    def assert_members_deliver_in_order(self, members):
        waits = {d: self.wait(d) for d in members}
        loops, merged = {}, []
        for directory in members:
            state = record.read_state(directory)
            state.update(state="running")
            lp = SimpleNamespace(state=state, wt=self.repo, run_dir=directory,
                                 base_sha=self.base, target="main", log=lambda _: None)
            lp.write = lambda lp=lp: record.save_state(lp.run_dir, lp.state)
            lp.write()
            loops[directory] = lp

        def attempt(directory):
            lp = loops[directory]
            run.git(self.repo, "checkout", lp.state["branch"])

            def deliver():
                self.assertNotIn("delivery_wait", record.read_state(directory))
                self.assertEqual(run.git(self.repo, "rev-parse", "HEAD^{tree}"), waits[directory]["land"])
                checked = lp.state["final_check"]
                evidence = land.passed(self.turn, waits[directory]["land"]) or {"tested": waits[directory]["land"]}
                self.assertEqual(checked["tested"], waits[directory].get("tested", evidence["tested"]))
                body = run.merge_body(lp, run.git(self.repo, "rev-parse", "HEAD"))
                self.assertEqual(bool(body), checked["tested"] == waits[directory]["land"])
                run.git(self.repo, "push", "origin", "HEAD:main")
                lp.state.update(state="pass", merged=True)
                merged.append(directory)
                return True

            self.assertTrue(run.land_from_line(lp, "origin/main", deliver))

        def wait_for_prefix(_seconds):
            last = members[-1]
            self.assertEqual(merged, [])
            self.assertEqual(self.wait(last), waits[last])
            self.assertIn("delivery_wait", record.read_state(last))
            with self.turn.open("a") as probe:
                fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
            clock.sleep.side_effect = AssertionError("a predecessor waited for its dependent")
            for directory in members[:-1]:
                attempt(directory)
            run.git(self.repo, "checkout", loops[last].state["branch"])

        with patch.object(run, "time", wraps=run.time) as clock:
            clock.sleep.side_effect = wait_for_prefix
            attempt(members[-1])
        clock.sleep.assert_called_once_with(gate.SLOT_POLL)
        self.assertEqual(merged, members)
        self.assertEqual(run.git(self.repo, "rev-parse", "origin/main^{tree}"), waits[members[-1]]["land"])
        for directory in members:
            current = record.read_state(directory)
            self.assertTrue(current["merged"])
            self.assertNotIn("waiting_on", current)

    def test_five_waiting_members_land_in_order_after_one_green_check(self):
        members = [self.member(f"member-{n}", joined=n, **{f"member-{n}.txt": f"{n}\n"})
                   for n in range(1, 6)]
        self.advance()
        with patch.object(gate, "derived_heavy_limit", return_value=1):
            land.check_line(self.turn)
        self.assertEqual(len(self.checks), 1)
        self.assertEqual([call.args[0] for call in self.wake.call_args_list], [m.name for m in members])
        deepest, files = self.trees[0]
        self.assertTrue({f"member-{n}.txt" for n in range(1, 6)} <= files)
        for index, member in enumerate(members):
            wait = self.wait(member)
            self.assertEqual(land.passed(self.turn, wait["land"])["tested"], deepest)
            self.assertEqual(wait["after"], {m.name: self.wait(m)["land"] for m in members[:index]})
        # A delayed delivery keeps the real tested tree even after the cache expires.
        self.turn.with_suffix(".green").unlink()
        self.assert_members_deliver_in_order(members)
        self.assertEqual(len(self.checks), 1)
        self.assertEqual(land.line(self.turn), [])
        self.assert_cleaned()

    def test_a_bad_fourth_of_six_is_narrowed_and_the_others_land_in_the_same_pass(self):
        members = [self.member(f"member-{n}", joined=n, **{
            f"member-{n}.txt": f"{n}\n", **({"broken.txt": "broken\n"} if n == 4 else {})})
            for n in range(1, 7)]
        self.advance()
        with patch.object(gate, "derived_heavy_limit", return_value=1):
            land.check_line(self.turn)
        checked = [{f for f in files if f.startswith("member-")} for _, files in self.trees]
        self.assertEqual(checked, [
            {f"member-{n}.txt" for n in range(1, 7)},
            {f"member-{n}.txt" for n in range(1, 4)},
            {f"member-{n}.txt" for n in range(1, 5)},
            {f"member-{n}.txt" for n in (1, 2, 3, 5, 6)}])
        self.assertEqual([call.args[0] for call in self.wake.call_args_list], [m.name for m in members])
        self.assertIn("fix", self.wait(members[3]))
        good = members[:3] + members[4:]
        for index, member in enumerate(good):
            wait = self.wait(member)
            self.assertNotIn("fix", wait)
            self.assertEqual(wait["after"], {m.name: self.wait(m)["land"] for m in good[:index]})
            self.assertNotIn("broken.txt", self.stacked_files(wait["land"]))
        self.assert_members_deliver_in_order(good)
        self.assertEqual(len(self.checks), 4)
        self.assertEqual([m for m, _ in land.line(self.turn)], [members[3]])
        self.assert_cleaned()

    def test_a_woken_member_merges_while_a_later_stack_is_checking(self):
        first = self.member("head")
        self.advance()
        land.check_line(self.turn)
        tree = self.wait(first)["land"]
        later = self.member("later", joined=2, **{"later.txt": "later\n"})
        state = record.read_state(first)
        lp = SimpleNamespace(state=state, wt=self.repo, run_dir=first,
                             base_sha=self.base, target="main",
                             log=lambda _: None, write=lambda: record.save_state(first, state))
        run.git(self.repo, "checkout", state["branch"])

        def deliver():
            with self.turn.open("a") as probe:
                with self.assertRaises(BlockingIOError):
                    fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
            run.git(self.repo, "push", "origin", "HEAD:main")
            state.update(state="pass", merged=True)
            return True

        def mid_check(cmds, cwd, log_path, *args, **kw):
            with self.turn.open("a") as probe:
                fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.turn.with_suffix(".lander.lock").open("a") as probe:
                with self.assertRaises(BlockingIOError):
                    fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertTrue(run.land_from_line(lp, "origin/main", deliver))
            self.assertEqual(run.git(self.repo, "rev-parse", "origin/main^{tree}"), tree)
            return self.check(cmds, cwd, log_path, *args, **kw)

        with patch.object(gate, "run_done_when", side_effect=mid_check):
            land.check_line(self.turn)
        self.assertTrue(record.read_state(first)["merged"])
        self.assertNotIn("waiting_on", record.read_state(first))
        self.assertIn("land", self.wait(later))
        self.assertEqual(len(self.checks), 2)
        self.assert_cleaned()

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
        last = self.member("last", joined=3, **{"last.txt": "last\n"})
        self.advance()
        land.check_line(self.turn)
        self.assertIn("land", self.wait(first))
        self.assertEqual([call.args[0] for call in self.wake.call_args_list],
                         [first.name, later.name, last.name])
        self.assertTrue(any({"first.txt", "later.txt", "last.txt"} <= self.stacked_files(tree)
                            for tree in land._trees(self.turn)[1]))
        current = record.read_state(later)
        current["waiting_on"].pop("land")
        self.assertEqual(current["waiting_on"].pop("after"), {first.name: self.wait(first)["land"]})
        self.assertEqual(current, original)
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
        later = self.member("later", joined=3, **{"later.txt": "later\n"})
        self.advance()
        land.check_line(self.turn)
        self.assertEqual([call.args[0] for call in self.wake.call_args_list],
                         [first.name, later.name])
        self.assertIn("land", self.wait(first))
        self.assertEqual(record.read_state(missing), original)
        self.assertTrue(any({"first.txt", "later.txt"} <= self.stacked_files(tree)
                            for tree in land._trees(self.turn)[1]))
        self.assert_cleaned()

    def test_a_follower_checkout_failure_does_not_stop_later_stacks(self):
        first = self.member("first", **{"first.txt": "first\n"})
        failed = self.member("failed", joined=2, **{"failed.txt": "failed\n"})
        head = record.read_state(failed)["review"]["head_sha"]
        later = self.member("later", joined=3, **{"later.txt": "later\n"})
        self.advance()
        git_out = run.git_out

        def fail_checkout(repo, *args, **kw):
            if args[:2] == ("worktree", "add") and args[-1] == head:
                return 1, "checkout failed"
            return git_out(repo, *args, **kw)

        with patch.object(run, "git_out", side_effect=fail_checkout):
            land.check_line(self.turn)
        self.assertEqual([call.args[0] for call in self.wake.call_args_list],
                         [first.name, later.name])
        self.assertTrue(any({"first.txt", "later.txt"} <= self.stacked_files(tree)
                            and "failed.txt" not in self.stacked_files(tree)
                            for tree in land._trees(self.turn)[1]))
        self.assertNotIn("fix", self.wait(failed))
        self.assert_cleaned()

    def test_only_the_newest_member_of_a_red_stack_gets_its_failure(self):
        suite = "test ! -f api.txt || test ! -f client.txt"
        first = self.member("api", **{"api.txt": "api\n"})
        red = self.member("client", joined=2, **{"client.txt": "client\n"})
        later = self.member("later", joined=3, **{"later.txt": "later\n"})
        originals = {d: record.read_state(d) for d in (first, red, later)}
        self.advance(**{"AGENTS.md": f"---\ntests: {suite}\n---\n"})
        land.check_line(self.turn)
        self.assertEqual({call.args[0] for call in self.wake.call_args_list},
                         {first.name, red.name, later.name})
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
        self.assertIn("land", self.wait(later))
        for directory, key in ((first, "land"), (red, "fix"), (later, "land")):
            current = record.read_state(directory)
            current["waiting_on"].pop(key)
            if key == "land":
                self.assertEqual(current["waiting_on"].pop("after"),
                                 {} if directory == first else {first.name: self.wait(first)["land"]})
            expected = dict(originals[directory])
            if key == "fix":
                expected.pop("line_since")
            self.assertEqual(current, expected)
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
                         {first.name, red.name, middle.name, other.name, last.name})
        for directory in (red, other):
            self.assertIn(SUITE, self.wait(directory)["fix"]["line"])
        for directory in (middle, last):
            self.assertNotIn("fix", self.wait(directory))
            self.assertIn("land", self.wait(directory))
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
        self.assertEqual([call.args[0] for call in self.wake.call_args_list],
                         [first.name, later.name, last.name])
        self.assertEqual(record.read_state(clash), original)
        self.assertEqual(run.git(self.repo, "rev-parse", original["branch"]),
                         original["review"]["head_sha"])
        self.assertTrue(any({"later.txt", "last.txt"} <= files for _, files in self.trees))
        self.assertTrue(any({"later.txt", "last.txt"} <= self.stacked_files(tree)
                            for tree in land._trees(self.turn)[1]))
        self.assertNotIn("fix", self.wait(later))
        self.assertNotIn("fix", self.wait(last))
        self.assertIn("land", self.wait(later))
        self.assertIn("land", self.wait(last))
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
        self.assertIn(clash.name, [call.args[0] for call in self.wake.call_args_list])
        self.assertIn("rebase of origin/main failed", self.wait(clash)["fix"]["line"])
        self.assert_cleaned()

    def test_a_third_member_conflicting_with_the_tip_wakes_on_the_first_pass(self):
        base = self.base
        self.advance(**{"base.txt": "target\n"})
        self.base = run.git(self.repo, "rev-parse", "main")
        # The first member hides the third's target conflict if only the stack is tried.
        first = self.member("first", **{"base.txt": "branch\n", "first.txt": "first\n"})
        second = self.member("second", joined=2, **{"second.txt": "second\n"})
        self.base = base
        third = self.member("third", joined=3, **{"base.txt": "branch\n", "third.txt": "third\n"})
        original = record.read_state(third)
        run.git(self.repo, "config", "rebase.updateRefs", "true")
        land.check_line(self.turn)
        self.assertCountEqual([call.args[0] for call in self.wake.call_args_list],
                              [first.name, second.name, third.name])
        self.assertIn("land", self.wait(first))
        self.assertIn("land", self.wait(second))
        fix = self.wait(third)["fix"]
        self.assertIn("rebase of origin/main failed", fix["line"])
        self.assertIn("CONFLICT", Path(fix["log"]).read_text())
        self.assertEqual(len(self.trees), 2)
        self.assertTrue(any({"first.txt", "second.txt"} <= files for _, files in self.trees))
        self.assertTrue(all("third.txt" not in files for _, files in self.trees))
        current = record.read_state(third)
        current["waiting_on"].pop("fix")
        expected = dict(original)
        expected.pop("line_since")
        self.assertEqual(current, expected)
        self.assertEqual(run.git(self.repo, "rev-parse", original["branch"]),
                         original["review"]["head_sha"])
        self.assert_cleaned()

    def test_a_red_head_is_removed_before_checking_the_members_behind_it(self):
        head = self.member("head", **{"broken.txt": "x\n"})
        later = self.member("later", joined=2, **{"later.txt": "later\n"})
        last = self.member("last", joined=3, **{"last.txt": "last\n"})
        self.advance()
        land.check_line(self.turn)
        self.assertEqual([call.args[0] for call in self.wake.call_args_list],
                         [head.name, later.name, last.name])
        self.assertIn("fix", self.wait(head))
        self.assertIn("land", self.wait(later))
        self.assertIn("land", self.wait(last))
        self.assertTrue(any({"later.txt", "last.txt"} <= self.stacked_files(tree)
                            and "broken.txt" not in self.stacked_files(tree)
                            for tree in land._trees(self.turn)[1]))
        self.assert_cleaned()

    def test_a_crash_before_verdicts_reuses_checked_trees_and_rebuilds_the_red_suffix(self):
        head = self.member("head")
        red = self.member("red", joined=2, **{"broken.txt": "x\n"})
        self.member("later", joined=3, **{"later.txt": "later\n"})
        self.advance()
        with patch.object(record, "record", side_effect=RuntimeError("crash before verdicts")):
            with self.assertRaisesRegex(RuntimeError, "crash before verdicts"):
                land.check_line(self.turn)
        count = len(self.checks)
        checked = {tree for tree, _ in self.trees}
        failures = land._trees(self.turn, "red_stacks")[1]
        self.assertTrue(failures)
        self.wake.assert_not_called()
        land.check_line(self.turn)
        self.assertEqual(len(self.checks), count + 1)
        rebuilt, files = self.trees[-1]
        self.assertNotIn(rebuilt, checked)
        self.assertNotIn("broken.txt", files)
        self.assertIn(self.wait(red)["fix"]["log"], [entry["log"] for entry in failures.values()])
        self.assertIn("land", self.wait(head))
        self.assert_cleaned()

    def test_a_crash_between_verdicts_keeps_the_red_stack_failure(self):
        suite = "test ! -f api.txt || test ! -f client.txt"
        head = self.member("api", **{"api.txt": "api\n"})
        red = self.member("client", joined=2, **{"client.txt": "client\n"})
        later = self.member("later", joined=3, **{"later.txt": "later\n"})
        original = record.read_state(later)
        self.advance(**{"AGENTS.md": f"---\ntests: {suite}\n---\n"})
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
        self.assertEqual([checked for checked, _ in self.trees].count(tree), 1)
        current = record.read_state(later)
        current["waiting_on"].pop("land")
        self.assertEqual(current["waiting_on"].pop("after"), {head.name: self.wait(head)["land"]})
        self.assertEqual(current, original)
        with record.record(head) as current:
            current["state"] = "running"
        self.wake.reset_mock()
        land.check_line(self.turn)
        self.assertIn(red.name, [call.args[0] for call in self.wake.call_args_list])
        self.assertEqual(self.wait(red)["fix"], fix)
        self.assert_cleaned()

    def test_two_stacks_checked_side_by_side_merge_in_one_pass_in_line_order(self):
        first = self.member("head", **{"first.txt": "first\n"})
        later = self.member("later", joined=2, **{"later.txt": "later\n"})
        self.advance()
        started = threading.Barrier(2)

        def together(cmds, cwd, log_path, *args, **kw):
            started.wait(timeout=5)
            return self.check(cmds, cwd, log_path, *args, **kw)

        with patch.object(gate, "derived_heavy_limit", return_value=2), \
                patch.object(gate, "run_done_when", side_effect=together), \
                patch.object(land, "as_completed", side_effect=lambda futures: iter(reversed(list(futures)))):
            land.check_line(self.turn)
        self.assertEqual(len(self.checks), 2)
        self.assertEqual(len({cwd for _, cwd, _ in self.checks}), 2)
        self.assertEqual([call.args[0] for call in self.wake.call_args_list],
                         [first.name, later.name])
        self.assert_members_deliver_in_order([first, later])
        self.assertEqual(len(self.checks), 2)
        self.assertEqual(land.line(self.turn), [])
        self.assert_cleaned()

    def test_rebuilding_retries_a_conflict_with_the_removed_red_member(self):
        first = self.member("first", **{"first.txt": "first\n"})
        red = self.member("red", joined=2, **{"base.txt": "red\n", "broken.txt": "x\n"})
        clash = self.member("clash", joined=3, **{"base.txt": "clash\n"})
        later = self.member("later", joined=4, **{"later.txt": "later\n"})
        self.advance()
        land.check_line(self.turn)
        self.assertEqual({call.args[0] for call in self.wake.call_args_list},
                         {first.name, red.name, clash.name, later.name})
        self.assertNotIn("fix", self.wait(clash))
        self.assertNotIn("fix", self.wait(later))
        self.assertIn("land", self.wait(clash))
        self.assertIn("land", self.wait(later))
        self.assertTrue(any("later.txt" in self.stacked_files(tree)
                            and run.git(self.repo, "show", f"{tree}:base.txt") == "clash"
                            for tree in land._trees(self.turn)[1]))
        self.assert_cleaned()

    def assert_rejoining_member_follows_its_tested_prefix(self, kind):
        oldest = self.member("oldest", joined=1, **{
            "oldest.txt": "oldest\n",
            **({"broken.txt": "broken\n"} if kind == "red" else {}),
            **({"base.txt": "branch\n"} if kind == "conflict" else {})})
        later = self.member("later", joined=2, **{
            "later.txt": "later\n", **({"oldest.txt": "oldest\n"} if kind == "covered" else {})})
        last = self.member("last", joined=3, **{"last.txt": "last\n"})
        if kind == "unavailable":
            with record.record(oldest) as current:
                current["review"]["head_sha"] = "f" * 40
        self.advance(**({"base.txt": "target\n"} if kind == "conflict" else {}))
        with patch.object(gate, "derived_heavy_limit", return_value=5):
            land.check_line(self.turn)
        self.assertIn("land" if kind == "covered" else "fix", self.wait(oldest))
        self.assertIn("land", self.wait(later))
        self.assertIn("land", self.wait(last))
        for directory in (later, last):
            with record.record(directory) as current:
                current.update(state="running", pid=5678)
        run.git(self.repo, "checkout", "ak/oldest")
        if kind == "red":
            run.git(self.repo, "rm", "broken.txt")
            self.commit("repair the reviewed change")
        elif kind == "conflict":
            code, _ = run.git_out(self.repo, "rebase", "origin/main")
            self.assertNotEqual(code, 0)
            (self.repo / "base.txt").write_text("target\n")
            run.git(self.repo, "add", "base.txt")
            run.git(self.repo, "-c", "core.editor=true", "rebase", "--continue")
        with record.record(oldest) as current:
            current["review"].update(run.commit_identity(self.repo))
            current["waiting_on"] = {"line": self.turn.name, "joined": 1}
        run.git(self.repo, "checkout", "main")
        with patch.object(record, "process_active", side_effect=lambda state: state.get("pid") == 5678):
            land.check_line(self.turn)
            self.assertEqual([d for d, _ in land.line(self.turn)], [later, last, oldest])
            wait = self.wait(oldest)
            self.assertEqual(wait["joined"], 1)
            self.assertEqual(wait["after"], {d.name: self.wait(d)["land"] for d in (later, last)})
            self.assertTrue({"later.txt", "last.txt"} <= self.stacked_files(wait["land"]))
            loops, merged = {}, []
            for directory in (oldest, later, last):
                state = record.read_state(directory)
                state.update(state="running", pid=5678)
                lp = SimpleNamespace(state=state, wt=self.repo, run_dir=directory,
                                     base_sha=self.base, target="main", log=lambda _: None)
                lp.write = lambda lp=lp: record.save_state(lp.run_dir, lp.state)
                lp.write()
                loops[directory] = lp

            def attempt(directory):
                lp = loops[directory]
                tree = lp.state["waiting_on"]["land"]
                run.git(self.repo, "checkout", lp.state["branch"])

                def deliver():
                    self.assertEqual(run.git(self.repo, "rev-parse", "HEAD^{tree}"), tree)
                    run.git(self.repo, "push", "origin", "HEAD:main")
                    lp.state.update(state="pass", merged=True)
                    merged.append(directory)
                    return True

                result = run.land_from_line(lp, "origin/main", deliver)
                if directory == oldest and kind == "covered":
                    self.assertFalse(result)
                    self.assertTrue(lp.state["on_target"])
                    self.assertNotIn("waiting_on", lp.state)
                else:
                    self.assertTrue(result)

            def wait_for_prefix(_seconds):
                self.assertEqual(self.wait(oldest), wait)
                self.assertIn("delivery_wait", record.read_state(oldest))
                clock.sleep.side_effect = AssertionError("a predecessor waited for its dependent")
                attempt(later)
                attempt(last)
                run.git(self.repo, "checkout", loops[oldest].state["branch"])

            with patch.object(run, "time", wraps=run.time) as clock:
                clock.sleep.side_effect = wait_for_prefix
                attempt(oldest)
            clock.sleep.assert_called_once_with(gate.SLOT_POLL)
            self.assertEqual(merged, [later, last] if kind == "covered" else [later, last, oldest])
            self.assertEqual(land.line(self.turn), [])
        self.assert_cleaned()

    def test_a_repaired_red_member_follows_its_tested_prefix(self):
        self.assert_rejoining_member_follows_its_tested_prefix("red")

    def test_a_repaired_conflicting_member_follows_its_tested_prefix(self):
        self.assert_rejoining_member_follows_its_tested_prefix("conflict")

    def test_an_unavailable_member_rejoins_behind_its_tested_prefix(self):
        self.assert_rejoining_member_follows_its_tested_prefix("unavailable")

    def test_a_rejoining_member_ignores_dependencies_on_its_earlier_tree(self):
        self.assert_rejoining_member_follows_its_tested_prefix("covered")

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
