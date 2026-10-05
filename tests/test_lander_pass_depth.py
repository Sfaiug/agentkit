"""A crowded pass checks the deepest stack and narrows failures; deliveries lead the stack.

Offline: real Git and checks, sandbox records, fake process ownership and wakes.
"""

import json
import threading
import unittest
from unittest.mock import patch

from test_lander import LanderFixture, config, gate, land, record, run
from agentkit import status


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

    def members(self, *, red=None, count=5):
        members = [self.member(f"member-{n}", joined=n, **{
            f"member-{n}.txt": f"{n}\n", **({"broken.txt": "broken\n"} if n == red else {})})
            for n in range(1, count + 1)]
        self.advance()
        return members

    def checked_prefix(self, *, red=3):
        members = self.members(count=2)
        land.check_line(self.turn)
        members.extend(self.member(f"member-{n}", joined=n, **{
            f"member-{n}.txt": f"{n}\n", **({"broken.txt": "broken\n"} if n == red else {})})
            for n in range(3, 6))
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

    def test_two_turns_check_the_deepest_of_five_and_keep_a_woken_prefix(self):
        members = self.members()
        self.capacity.side_effect = [2, 2]
        land.check_line(self.turn)
        self.assertEqual(len(self.checks), 1)
        self.capacity.assert_called_once_with()
        self.assertEqual(self.checked_members(), {frozenset(f"member-{n}.txt" for n in range(1, 6))})
        self.assertEqual([call.args[0] for call in self.wake.call_args_list],
                         [member.name for member in members])
        second_tree = self.wait(members[1])["land"]
        deepest = self.checked[0][0]
        for index, member in enumerate(members):
            wait = self.wait(member)
            self.assertEqual(land.passed(self.turn, wait["land"])["tested"], deepest)
            self.assertEqual(wait["after"], {m.name: self.wait(m)["land"] for m in members[:index]})

        # An explicit resume keeps the old parked death while its fresh loop delivers.
        with record.record(members[0]) as current:
            current.update(state="running", pid=5678, deaths=[{"parked": True}])
        self.checked.clear()
        self.wake.reset_mock()
        with patch.object(record, "process_active", side_effect=lambda state: state.get("pid") == 5678):
            land.check_line(self.turn)
        self.assertEqual(self.wait(members[1])["land"], second_tree)
        self.assertEqual([call.args[0] for call in self.wake.call_args_list],
                         [member.name for member in members[1:]])
        self.assertEqual(self.checked_members(), set())
        self.assertEqual(len(self.checks), 1)
        self.capacity.assert_called_once_with()
        self.assert_cleaned()

    def test_the_head_gets_its_verdict_and_wake_before_the_second_check_finishes(self):
        self.capacity.return_value = 5
        members = self.members()
        woken = threading.Event()

        def check(cmds, cwd, log_path, *args, **kw):
            files = run.git(cwd, "ls-tree", "--name-only", "HEAD").splitlines()
            if "member-2.txt" in files:
                self.assertTrue(woken.wait(timeout=5), "the head waited for the suffix check")
            return self.check(cmds, cwd, log_path, *args, **kw)

        def wake(name, _log):
            self.assertIn(name, [member.name for member in members])
            self.assertIn("land", self.wait(config.RUNS / name))
            if name == members[0].name:
                woken.set()
            return 999

        self.wake.side_effect = wake
        with patch.object(gate, "run_done_when", side_effect=check):
            land.check_line(self.turn)
        self.assertTrue(woken.is_set())
        self.assertEqual(len(self.checks), 5)
        self.assert_cleaned()

    def test_rebuilding_after_a_red_stack_continues_in_the_same_pass(self):
        members = self.members(red=2)
        land.check_line(self.turn)
        self.assertEqual(len(self.checks), 4)
        self.assertIn("land", self.wait(members[0]))
        self.assertIn("fix", self.wait(members[1]))
        self.assertTrue(all("land" in self.wait(member) and "fix" not in self.wait(member)
                            for member in members[2:]))
        self.capacity.assert_called_once_with()
        self.assert_cleaned()

    def test_a_red_member_is_woken_after_the_head_records_its_new_owner_and_scope(self):
        self.capacity.return_value = 5
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
                              [member.name for member in members])
        self.assert_cleaned()

    def test_a_red_member_is_woken_while_the_prefix_saves_its_rebase_and_final_check(self):
        self.prefix_delivery()

    def test_a_red_member_is_woken_after_the_prefix_finishes_landing(self):
        self.prefix_delivery(landed=True)

    def prefix_delivery(self, *, landed=False):
        members = self.checked_prefix()
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
                              [member.name for member in members])
        for member in (members[2], members[4]):
            self.assertIn("land", self.wait(member))
        self.assert_cleaned()

    def test_a_changed_or_stopped_prefix_still_invalidates_the_red_verdict(self):
        members = self.checked_prefix()
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
                # Delivery reparks the follower when its tested prefix leaves the line.
                with record.record(members[1]) as current:
                    current["waiting_on"].pop("land", None)
                    current["waiting_on"].pop("after", None)
                for _ in range(3):
                    self.wake.reset_mock()
                    land.check_line(self.turn)
                    tree = self.wait(members[1])["land"]
                    self.assertNotIn("member-1.txt",
                                     run.git(self.repo, "ls-tree", "--name-only", tree).splitlines())
                    self.wake.assert_called_once_with(members[1].name, unittest.mock.ANY)
                    with record.record(members[1]) as current:
                        current["waiting_on"].pop("land")
                        current["waiting_on"].pop("after")
                self.assert_cleaned()

    def test_a_live_rejoiner_behind_a_green_prefix_prevents_a_pass(self):
        members = self.members()
        land.check_line(self.turn)
        with record.record(members[0]) as current:
            current.update(state="running", pid=5678)
        for member in members[1:]:
            with record.record(member) as current:
                if member == members[1]:
                    current.update(pid=4321)
                current["waiting_on"].pop("land")
                current["waiting_on"].pop("after")
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

    def test_cached_green_and_red_suffixes_cover_the_unanswered_prefix(self):
        members = self.members(red=5)
        self.capacity.return_value = 5
        with patch.object(record, "record", side_effect=RuntimeError("before verdict")):
            with self.assertRaisesRegex(RuntimeError, "before verdict"):
                land.check_line(self.turn)
        self.assertEqual(len(self.checks), 5)
        cache = self.turn.with_suffix(".green")
        evidence = json.loads(cache.read_text())
        for tree, files in self.checked:
            if "member-4.txt" not in files:
                evidence["trees"].pop(tree)
        checked_at = next(iter(evidence["trees"].values()))["at"]
        cache.write_text(json.dumps(evidence))
        self.checked.clear()
        self.checks.clear()
        self.capacity.return_value = 2
        with patch.object(land.time, "time", return_value=checked_at + land.KEEP - 1):
            land.check_line(self.turn)
        self.assertEqual(self.checks, [])
        self.assertEqual(self.checked_members(), set())
        self.assertIn("land", self.wait(members[0]))
        self.assertIn("fix", self.wait(members[4]))
        self.assertCountEqual([call.args[0] for call in self.wake.call_args_list],
                              [member.name for member in members])
        for member in members[:4]:
            self.assertIn("land", self.wait(member))
        # Reusing a check does not buy another day of suite evidence.
        with patch.object(land.time, "time", return_value=checked_at + land.KEEP + 1):
            for member in members[:4]:
                self.assertIsNone(land.passed(self.turn, self.wait(member)["land"]))
        self.assert_cleaned()

    def assert_a_departed_tested_tip_is_rechecked(self, count, *, crash=False):
        suite = "test -f base.txt && { test ! -f a.txt || test -f b.txt; }"
        members = [self.member(f"member-{n}", joined=n, once="true", **{
            "a.txt" if n == 1 else "b.txt" if n == count else f"member-{n}.txt": f"{n}\n"})
            for n in range(1, count + 1)]
        self.advance(**{"AGENTS.md": f"---\ntests: {suite}\n---\n"})
        self.capacity.return_value = 1

        def stop_tip(cmds, cwd, log_path, *args, **kw):
            result = self.check(cmds, cwd, log_path, *args, **kw)
            with record.record(members[-1]) as current:
                current.update(state="stopped")
                current.pop("waiting_on")
            return result

        if crash:
            with patch.object(record, "record", side_effect=RuntimeError("before verdict")):
                with self.assertRaisesRegex(RuntimeError, "before verdict"):
                    land.check_line(self.turn)
            with record.record(members[-1]) as current:
                current.update(state="stopped")
                current.pop("waiting_on")
        else:
            with patch.object(gate, "run_done_when", side_effect=stop_tip):
                land.check_line(self.turn)
        tested = self.checked[0][0]
        self.assertTrue(all("land" not in self.wait(m) for m in members[:-1]))
        self.assertTrue(all(land.passed(self.turn, tree)["tested"] == tested
                            for tree in land._trees(self.turn)[1]))
        self.checked.clear()
        self.checks.clear()
        self.wake.reset_mock()
        # Exercise both direct cached answers and the crowded pass's prefix replay.
        self.capacity.return_value = 9 if crash else 1
        land.check_line(self.turn)
        self.assertTrue(self.checks)
        self.assertIn("fix", self.wait(members[0]))
        self.assertNotIn("land", self.wait(members[0]))
        for member in members[1:-1]:
            wait = self.wait(member)
            self.assertIn("land", wait)
            self.assertNotEqual(wait.get("tested", wait["land"]), tested)
            self.assertNotIn("a.txt", run.git(self.repo, "ls-tree", "--name-only", wait["land"]).splitlines())
            self.assertIn(land.passed(self.turn, wait["land"])["tested"],
                          [tree for tree, _ in self.checked])
        self.assert_cleaned()

    def test_a_tip_stopped_during_the_check_cannot_supply_cached_batch_coverage(self):
        self.assert_a_departed_tested_tip_is_rechecked(5)

    def test_a_tip_departing_after_a_crash_cannot_answer_stacks_that_all_fit(self):
        self.assert_a_departed_tested_tip_is_rechecked(3, crash=True)

    def test_a_cached_batch_is_reused_while_its_tested_tip_remains(self):
        members = self.members()
        self.capacity.return_value = 1
        with patch.object(record, "record", side_effect=RuntimeError("before verdict")):
            with self.assertRaisesRegex(RuntimeError, "before verdict"):
                land.check_line(self.turn)
        tested = self.checked[0][0]
        self.checks.clear()
        self.capacity.return_value = 9
        land.check_line(self.turn)
        self.assertEqual(self.checks, [])
        for member in members:
            wait = self.wait(member)
            self.assertEqual(wait.get("tested", wait["land"]), tested)
        self.assert_cleaned()

    def test_covered_evidence_still_owes_a_replacement_members_own_checks(self):
        suite = "test -f base.txt && { test ! -f a.txt || test -f b.txt; }"
        first = self.member("first", once="true", **{"a.txt": "a\n"})
        second = self.member("second", joined=2, once="true", **{"c.txt": "c\n"})
        third = self.member("third", joined=3, once="true", **{"b.txt": "b\n"})
        self.advance(**{"AGENTS.md": f"---\ntests: {suite}\n---\n"})
        self.capacity.return_value = 1
        with patch.object(record, "record", side_effect=RuntimeError("before verdict")):
            with self.assertRaisesRegex(RuntimeError, "before verdict"):
                land.check_line(self.turn)
        tested = self.checked[0][0]
        with record.record(third) as state:
            state.update(state="stopped")
            state.pop("waiting_on")
        replacement = self.member("replacement", joined=4, once="test -f acceptance.txt",
                                  **{"b.txt": "b\n"})
        self.checked.clear()
        self.checks.clear()
        land.check_line(self.turn)
        self.assertEqual(self.checked[0][0], tested)
        for member in (first, replacement):
            self.assertIn("fix", self.wait(member))
            self.assertNotIn("land", self.wait(member))
        tree = self.wait(second)["land"]
        self.assertNotIn("a.txt", run.git(self.repo, "ls-tree", "--name-only", tree).splitlines())
        self.assertIn(tree, [checked for checked, _ in self.checked])
        self.assert_cleaned()

    def test_the_deepest_stack_covers_every_member_when_only_one_check_fits(self):
        members = self.members()
        self.capacity.return_value = 1
        land.check_line(self.turn)
        self.assertEqual(len(self.checks), 1)
        self.assertTrue(all("land" in self.wait(member) for member in members))
        self.assertEqual(self.checked_members(), {frozenset(f"member-{n}.txt" for n in range(1, 6))})
        self.assert_cleaned()

    def test_a_pinned_turn_count_selects_the_deepest_stack(self):
        members = self.members()
        self.capacity.return_value = 3
        with patch.object(config, "max_gates", return_value=1):
            land.check_line(self.turn)
        self.assertEqual(len(self.checks), 1)
        self.assertTrue(all("land" in self.wait(member) for member in members))
        self.assert_cleaned()

    def test_a_batch_runs_each_covered_members_once_commands(self):
        members = [self.member(f"member-{n}", joined=n, once=f"test -f member-{n}.txt",
                               **{f"member-{n}.txt": f"{n}\n"}) for n in range(1, 4)]
        self.advance()
        self.capacity.return_value = 1
        land.check_line(self.turn)
        self.assertEqual(len(self.checks), 1)
        self.assertTrue(all("land" in self.wait(member) for member in members))
        for n in range(1, 4):
            self.assertIn(f"test -f member-{n}.txt", self.checks[0][0])
        self.assert_cleaned()

    def test_a_batch_keeps_once_commands_in_order_and_runs_the_suite_last(self):
        first = self.member("first", once="true")
        second = self.member("second", joined=2, once="touch acceptance.txt")
        third = self.member("third", joined=3, once="test -f acceptance.txt")
        self.advance(**{"AGENTS.md": "---\ntests: test -f acceptance.txt && test -f tip.txt\n---\n"})
        self.capacity.return_value = 1
        land.check_line(self.turn)
        self.assertEqual(len(self.checks), 1)
        self.assertEqual(self.checks[0][0], ["true", "touch acceptance.txt", "test -f acceptance.txt",
                                          "test -f acceptance.txt && test -f tip.txt"])
        self.assertTrue(all("land" in self.wait(member) for member in (first, second, third)))
        self.assert_cleaned()

    def test_a_sharded_suite_checks_the_deepest_stack_to_cover_every_member(self):
        members = [self.member(f"member-{n}", joined=n, **{f"member-{n}.txt": f"{n}\n"})
                   for n in range(1, 4)]
        self.advance(**{"AGENTS.md": "---\ntests: test -f base.txt  # AK_SHARD\n---\n"})
        self.capacity.return_value = 3
        land.check_line(self.turn)
        self.assertEqual(self.checked_members(), {frozenset(f"member-{n}.txt" for n in range(1, 4))})
        self.assertTrue(all("land" in self.wait(member) for member in members))
        self.assert_cleaned()

    def test_a_red_suffix_is_not_blamed_while_a_stack_ahead_is_unanswered(self):
        suite = "test ! -f bad.txt || { test -f mitigation.txt && test ! -f tail.txt; }"
        head = self.member("head", joined=1, once="true", **{"bad.txt": "bad\n"})
        mitigation = self.member("mitigation", joined=2, once="true", **{"mitigation.txt": "ok\n"})
        tail = self.member("tail", joined=3, once="true", **{"tail.txt": "ok\n"})
        self.advance(**{"AGENTS.md": f"---\ntests: {suite}\n---\n"})
        self.capacity.return_value = 6

        def suffixes_first(futures):
            futures = list(futures)
            # The shorter suffix checks finish while the head's own check still runs.
            return iter([futures[1], futures[2], futures[0]] if len(futures) == 3 else futures)

        with patch.object(land, "as_completed", side_effect=suffixes_first):
            land.check_line(self.turn)
        self.assertIn("fix", self.wait(head))
        self.assertNotIn("fix", self.wait(tail))
        self.assertEqual([call.args[0] for call in self.wake.call_args_list],
                         [head.name, mitigation.name, tail.name])
        self.assertIn("land", self.wait(mitigation))
        self.assertIn("land", self.wait(tail))
        self.assert_cleaned()

    def test_a_green_delivery_stays_ahead_of_earlier_waiting_members(self):
        earlier = self.member("earlier", joined=5, **{"earlier.txt": "earlier\n"})
        green = self.member("green", joined=30, **{"green.txt": "green\n"})
        with record.record(green) as state:
            state["waiting_on"] = {**state["waiting_on"], "land": "tree"}
        self.assertEqual([directory for directory, _ in land.line(self.turn)], [green, earlier])
        self.assertEqual(status.parked_line(record.read_state(earlier)),
                         "waiting · 2nd in line to land on main")

    def test_two_green_deliveries_leave_the_next_pass_to_the_member_behind_them(self):
        head = self.member("head", joined=1, **{"head.txt": "head\n"})
        self.advance()
        land.check_line(self.turn)
        second = self.member("second", joined=2, **{"second.txt": "second\n"})
        tail = self.member("tail", joined=3, **{"tail.txt": "tail\n"})
        land.check_line(self.turn)
        self.assertIn("land", self.wait(head))
        self.assertIn("land", self.wait(second))
        for member in (head, second):
            with record.record(member) as state:
                state.update(state="running", pid=5678)
        with patch.object(record, "process_active",
                          side_effect=lambda state: state.get("pid") == 5678):
            self.assertEqual([directory for directory, _ in land.line(self.turn)],
                             [head, second, tail])
            land.check_line(self.turn)
        self.assertIn("land", self.wait(tail))
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
