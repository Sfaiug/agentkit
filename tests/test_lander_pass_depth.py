"""A pass checks only the front stacks that fit; woken members still lead the stack.

Offline: real Git and checks, sandbox records, fake process ownership and wakes.
"""

import json
import threading
import unittest
from unittest.mock import patch

from test_lander import LanderFixture, config, gate, land, record, run


class LanderPassDepth(LanderFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.capacity = self.stack.enter_context(patch.object(
            gate, "derived_heavy_limit", return_value=2))
        self.checked = []

    def check(self, cmds, cwd, log_path, *args, **kw):
        self.checked.append((run.git(cwd, "rev-parse", "HEAD^{tree}"),
                             set(run.git(cwd, "ls-tree", "--name-only", "HEAD").splitlines())))
        return super().check(cmds, cwd, log_path, *args, **kw)

    def members(self, *, red=None):
        members = [self.member(f"member-{n}", joined=n, **{
            f"member-{n}.txt": f"{n}\n", **({"broken.txt": "broken\n"} if n == red else {})})
            for n in range(1, 6)]
        self.advance()
        return members

    def checked_members(self):
        return {frozenset(name for name in files if name.startswith("member-"))
                for _, files in self.checked}

    def resume_writes(self, name, _log):
        with record.record(config.RUNS / name) as current:
            current.update(state="running", scope=f"agentkit-run-{name}-2", pid=5678,
                           process_identity={"boot": "fixture", "ticks": 2})
            if "fix" in current["waiting_on"]:
                current["waiting_on"] = {**current["waiting_on"], "fixing": True}
        return 999

    def test_two_turns_check_only_the_first_two_of_five_and_keep_a_woken_prefix(self):
        members = self.members()
        self.capacity.side_effect = [2, 2]
        land.check_line(self.turn)
        self.assertEqual(len(self.checks), 2)
        self.capacity.assert_called_once_with()
        self.assertEqual(self.checked_members(), {
            frozenset({"member-1.txt"}), frozenset({"member-1.txt", "member-2.txt"})})
        self.wake.assert_called_once_with(members[0].name, unittest.mock.ANY)
        self.assertTrue(all("land" not in self.wait(member) for member in members[1:]))
        second_tree = next(tree for tree, files in self.checked if "member-2.txt" in files)

        # An explicit resume keeps the old parked death while its fresh loop delivers.
        with record.record(members[0]) as current:
            current.update(state="running", pid=5678, deaths=[{"parked": True}])
        self.checked.clear()
        self.wake.reset_mock()
        with patch.object(record, "process_active", side_effect=lambda state: state.get("pid") == 5678):
            land.check_line(self.turn)
        self.assertEqual(self.wait(members[1])["land"], second_tree)
        self.wake.assert_called_once_with(members[1].name, unittest.mock.ANY)
        self.assertEqual(self.checked_members(), {
            frozenset({"member-1.txt", "member-2.txt", "member-3.txt"}),
            frozenset({"member-1.txt", "member-2.txt", "member-3.txt", "member-4.txt"})})
        self.assertEqual(len(self.checks), 4)
        self.assertEqual(self.capacity.call_count, 2)
        self.assert_cleaned()

    def test_the_head_gets_its_verdict_and_wake_before_the_second_check_finishes(self):
        members = self.members()
        woken = threading.Event()

        def check(cmds, cwd, log_path, *args, **kw):
            files = run.git(cwd, "ls-tree", "--name-only", "HEAD").splitlines()
            if "member-2.txt" in files:
                self.assertTrue(woken.wait(timeout=5), "the head waited for the suffix check")
            return self.check(cmds, cwd, log_path, *args, **kw)

        def wake(name, _log):
            self.assertEqual(name, members[0].name)
            self.assertIn("land", self.wait(members[0]))
            woken.set()
            return 999

        self.wake.side_effect = wake
        with patch.object(gate, "run_done_when", side_effect=check):
            land.check_line(self.turn)
        self.assertTrue(woken.is_set())
        self.assertEqual(len(self.checks), 2)
        self.assert_cleaned()

    def test_rebuilding_after_a_red_stack_uses_the_same_pass_budget(self):
        members = self.members(red=2)
        land.check_line(self.turn)
        self.assertEqual(len(self.checks), 2)
        self.assertIn("land", self.wait(members[0]))
        self.assertIn("fix", self.wait(members[1]))
        self.assertTrue(all("land" not in self.wait(member) and "fix" not in self.wait(member)
                            for member in members[2:]))
        self.capacity.assert_called_once_with()
        self.assert_cleaned()

    def test_a_red_member_is_woken_after_the_head_records_its_new_owner_and_scope(self):
        members = self.members(red=2)
        woken = threading.Event()

        def wake(name, log):
            self.resume_writes(name, log)
            woken.set()
            return 999

        def check(cmds, cwd, log_path, *args, **kw):
            if "member-2.txt" in run.git(cwd, "ls-tree", "--name-only", "HEAD").splitlines():
                self.assertTrue(woken.wait(timeout=5))
            return self.check(cmds, cwd, log_path, *args, **kw)

        self.wake.side_effect = wake
        with patch.object(record, "process_active", side_effect=lambda state: state.get("pid") == 5678), \
                patch.object(gate, "run_done_when", side_effect=check):
            land.check_line(self.turn)
        self.assertIn("land", self.wait(members[0]))
        self.assertIn("fix", self.wait(members[1]))
        self.assertCountEqual([call.args[0] for call in self.wake.call_args_list],
                              [members[0].name, members[1].name])
        self.assert_cleaned()

    def test_a_red_member_is_woken_while_the_prefix_saves_its_rebase_and_final_check(self):
        self.prefix_delivery()

    def test_a_red_member_is_woken_after_the_prefix_finishes_landing(self):
        self.prefix_delivery(landed=True)

    def prefix_delivery(self, *, landed=False):
        members = self.members(red=3)
        land.check_line(self.turn)
        first = record.read_state(members[0])
        run.git(self.repo, "checkout", first["branch"])
        run.git(self.repo, "rebase", "origin/main")
        identity = run.commit_identity(self.repo)
        run.git(self.repo, "checkout", "main")
        self.assertEqual(identity["tree_sha"], first["waiting_on"]["land"])
        self.assertNotEqual(identity["head_sha"], first["review"]["head_sha"])
        with record.record(members[0]) as current:
            current.update(state="running", pid=5678)
        self.wake.reset_mock()

        def check(cmds, cwd, log_path, *args, **kw):
            if "member-3.txt" in run.git(cwd, "ls-tree", "--name-only", "HEAD").splitlines():
                with record.record(members[0]) as current:
                    current["base_sha"] = run.git(self.repo, "rev-parse", "origin/main")
                    current["review"] = {**first["review"], **identity,
                                         "rebased_from": first["review"]["head_sha"]}
                    current["final_check"] = {"outcome": "passed", "where": "landing",
                                              "sha": identity["head_sha"],
                                              "tree_sha": identity["tree_sha"]}
                    if landed:
                        current.update(state="pass", merged=True)
                        current.pop("waiting_on", None)
            return self.check(cmds, cwd, log_path, *args, **kw)

        with patch.object(record, "process_active", side_effect=lambda state: state.get("pid") == 5678), \
                patch.object(gate, "run_done_when", side_effect=check):
            land.check_line(self.turn)
        self.assertIn("fix", self.wait(members[2]))
        self.assertIn(members[2].name, [call.args[0] for call in self.wake.call_args_list])
        self.assertEqual(record.read_state(members[0])["review"]["head_sha"], identity["head_sha"])
        self.assert_cleaned()

    def test_a_red_member_starting_its_fixer_does_not_block_the_next_red_verdict(self):
        self.capacity.return_value = 9
        members = [self.member(f"member-{n}", joined=n, **{
            f"member-{n}.txt": f"{n}\n", **({"broken.txt": "broken\n"} if n in (2, 4) else {})})
            for n in range(1, 6)]
        self.advance()
        self.wake.side_effect = self.resume_writes
        with patch.object(record, "process_active", side_effect=lambda state: state.get("pid") == 5678):
            land.check_line(self.turn)
        self.assertIn("land", self.wait(members[0]))
        for member in (members[1], members[3]):
            self.assertIn("fix", self.wait(member))
            self.assertTrue(self.wait(member)["fixing"])
        self.assertCountEqual([call.args[0] for call in self.wake.call_args_list],
                              [members[0].name, members[1].name, members[3].name])
        self.assert_cleaned()

    def test_a_changed_or_stopped_prefix_still_invalidates_the_red_verdict(self):
        members = self.members(red=3)
        land.check_line(self.turn)
        first = record.read_state(members[0])
        first.update(state="running", pid=5678)
        for change in ({"review": {**first["review"], "passed_head_sha": "f" * 40}},
                       {"review": {**first["review"], "tree_sha": "f" * 40}},
                       {"waiting_on": {"line": self.turn.name, "joined": 1}},
                       {"state": "stalled"},
                       {"state": "interrupted", "deaths": [{"parked": True}]},
                       {"state": "interrupted", "deaths": []},
                       {"worktree": str(self.root / "gone"), "pid": None},
                       {"state": "stopped"}):
            with self.subTest(change=change):
                with record.record(members[0]) as current:
                    current.clear()
                    current.update(first)
                land.note(self.turn, [], members[0].name, red_stacks={})
                self.wake.reset_mock()
                changed = threading.Event()

                def check(cmds, cwd, log_path, *args, **kw):
                    if "member-3.txt" in run.git(cwd, "ls-tree", "--name-only", "HEAD").splitlines():
                        with record.record(members[0]) as current:
                            current.update(change)
                        changed.set()
                    return self.check(cmds, cwd, log_path, *args, **kw)

                with patch.object(record, "process_active", side_effect=lambda state: state.get("pid") == 5678), \
                        patch.object(gate, "run_done_when", side_effect=check):
                    land.check_line(self.turn)
                self.assertTrue(changed.is_set())
                self.assertNotIn("fix", self.wait(members[2]))
                self.assertNotIn(members[2].name, [call.args[0] for call in self.wake.call_args_list])
                self.assert_cleaned()

    def test_a_parked_green_member_leaves_later_members_on_trees_that_can_land(self):
        members = [self.member(f"member-{n}", joined=n, **{f"member-{n}.txt": f"{n}\n"})
                   for n in (1, 2)]
        self.advance()
        land.check_line(self.turn)
        first = record.read_state(members[0])
        for change in ({"state": "interrupted", "deaths": [{"parked": True}],
                        "recovery_pending": True, "interruption_reason": "loop process gone"},
                       {"state": "stalled"},
                       {"state": "running", "worktree": str(self.root / "gone")},
                       {"state": "interrupted", "deaths": []}):
            with self.subTest(change=change):
                with record.record(members[0]) as current:
                    current.clear()
                    current.update(first, pid=None, process_identity=None, **change)
                for _ in range(3):
                    self.wake.reset_mock()
                    land.check_line(self.turn)
                    tree = self.wait(members[1])["land"]
                    self.assertNotIn("member-1.txt",
                                     run.git(self.repo, "ls-tree", "--name-only", tree).splitlines())
                    self.wake.assert_called_once_with(members[1].name, unittest.mock.ANY)
                    with record.record(members[1]) as current:
                        current["waiting_on"].pop("land")
                self.assert_cleaned()

    def test_a_live_rejoiner_behind_a_green_prefix_prevents_a_pass(self):
        members = self.members()
        land.check_line(self.turn)
        with record.record(members[0]) as current:
            current.update(state="running", pid=5678)
        with record.record(members[1]) as current:
            current.update(pid=4321)
        self.checks.clear()
        self.wake.reset_mock()
        with patch.object(record, "process_active", side_effect=lambda state: state.get("pid") in (5678, 4321)):
            land.check_line(self.turn)
        self.assertEqual(self.checks, [])
        self.wake.assert_not_called()
        self.assertTrue(all("land" not in self.wait(member) for member in members[1:]))
        self.assert_cleaned()

    def test_candidate_stacks_stop_before_a_live_rejoiner(self):
        members = self.members()
        with record.record(members[1]) as current:
            current.update(pid=4321)
        with patch.object(record, "process_active", side_effect=lambda state: state.get("pid") == 4321):
            land.check_line(self.turn)
        self.assertEqual(self.checked_members(), {frozenset({"member-1.txt"})})
        self.assertIn("land", self.wait(members[0]))
        self.assertTrue(all("land" not in self.wait(member) for member in members[1:]))
        self.assert_cleaned()

    def test_cached_green_and_red_suffixes_answer_beyond_the_two_new_checks(self):
        members = self.members(red=5)
        self.capacity.return_value = 5
        with patch.object(record, "record", side_effect=RuntimeError("before verdict")):
            with self.assertRaisesRegex(RuntimeError, "before verdict"):
                land.check_line(self.turn)
        self.assertEqual(len(self.checks), 5)
        cache = self.turn.with_suffix(".green")
        evidence = json.loads(cache.read_text())
        for tree, files in self.checked:
            if not {"member-3.txt", "member-4.txt", "member-5.txt"} & files:
                evidence["trees"].pop(tree)
        cache.write_text(json.dumps(evidence))
        self.checked.clear()
        self.checks.clear()
        self.capacity.return_value = 2
        land.check_line(self.turn)
        self.assertEqual(len(self.checks), 2)
        self.assertEqual(self.checked_members(), {
            frozenset({"member-1.txt"}), frozenset({"member-1.txt", "member-2.txt"})})
        self.assertIn("land", self.wait(members[0]))
        self.assertIn("fix", self.wait(members[4]))
        self.assertCountEqual([call.args[0] for call in self.wake.call_args_list],
                              [members[0].name, members[4].name])
        self.assert_cleaned()

    def test_one_stack_checks_when_the_gate_has_room_for_only_one(self):
        members = self.members()
        self.capacity.return_value = 1
        land.check_line(self.turn)
        self.assertEqual(len(self.checks), 1)
        self.assertIn("land", self.wait(members[0]))
        self.assertTrue(all("land" not in self.wait(member) for member in members[1:]))
        self.assert_cleaned()

    def test_a_pinned_turn_count_bounds_the_checks_in_a_pass(self):
        members = self.members()
        self.capacity.return_value = 3
        with patch.object(config, "max_gates", return_value=1):
            land.check_line(self.turn)
        self.assertEqual(len(self.checks), 1)
        self.assertIn("land", self.wait(members[0]))
        self.assert_cleaned()

    def test_a_sharded_suite_takes_every_turn_so_a_pass_checks_one_stack(self):
        members = [self.member(f"member-{n}", joined=n, **{f"member-{n}.txt": f"{n}\n"})
                   for n in range(1, 4)]
        self.advance(**{"AGENTS.md": "---\ntests: test -f base.txt  # AK_SHARD\n---\n"})
        self.capacity.return_value = 3
        land.check_line(self.turn)
        self.assertEqual(self.checked_members(), {frozenset({"member-1.txt"})})
        self.assertIn("land", self.wait(members[0]))
        self.assert_cleaned()

    def test_a_green_member_leaves_the_line_after_landing_or_stopping(self):
        members = self.members()
        land.check_line(self.turn)
        for change in ({"state": "queued", "slot_waiting": True},
                       {"state": "running", "slot_waiting": False},
                       {"state": "interrupted", "deaths": [{"pid": 5678}]}):
            with self.subTest(change=change):
                with record.record(members[0]) as current:
                    current.update(**change)
                self.assertEqual(land.line(self.turn)[0][0], members[0])
        for change in ({"state": "pass"}, {"state": "running", "merged": True},
                       {"state": "stopped", "merged": False}):
            with self.subTest(change=change):
                with record.record(members[0]) as current:
                    current.update(**change)
                self.assertNotIn(members[0], [member for member, _ in land.line(self.turn)])


if __name__ == "__main__":
    unittest.main(verbosity=2)
