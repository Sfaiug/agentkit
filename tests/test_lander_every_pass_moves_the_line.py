"""Every pass of a landing line moves it.  A member that changes under a pass costs only the
verdicts stacked on it: those ahead of it are written and the pass goes on, while a changed
first member or green delivery ahead still ends the pass with nothing written.  A pass that
checked and moved nobody, or died, is followed by one of half the members, down to one alone,
and a pass that writes a verdict takes the whole line again, even one that died after it.
Black-box: test_key_every_pass_moves_the_line.

Offline: local Git and real suites, with isolated state and fake wakes, as in test_lander.
"""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_lander as fixture
from agentkit import gate, land, record

GONE = {"pid": 2 ** 22 + 1, "process_identity": {"boot": "gone", "ticks": 0}}


class EveryPassMovesTheLine(fixture.LanderFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.said = []
        self.taken = self.stack.enter_context(
            patch.object(land, "_check_members", side_effect=land._check_members))

    def line(self):
        # One check fits, so the pass narrows: the deepest stack (red, behind broken),
        # then the middle one, which is green, then broken's own
        members = [self.member("first", joined=1),
                   self.member("middle", joined=2, **{"middle.txt": "m\n"}),
                   self.member("broken", joined=3, **{"broken.txt": "b\n"}),
                   self.member("last", joined=4, **{"last.txt": "l\n"})]
        self.advance()
        return members

    def green_line(self):
        members = [self.member(f"member-{n}", joined=n, **{f"member-{n}.txt": f"{n}\n"})
                   for n in range(1, 5)]
        self.advance()
        return members

    def checked(self, changed=None, number=1):
        """One pass, one check at a time, `changed` changing under it once its check `number`
        has run."""
        self.checks.clear()
        inner = self.check

        def check(cmds, *args, **kw):
            answer = inner(cmds, *args, **kw)
            if changed and len(self.checks) == number:
                with record.record(changed) as current:
                    current["error"] = f"its seat pushed a new head ({len(self.taken.mock_calls)})"
            return answer

        with patch.object(gate, "derived_heavy_limit", return_value=1), \
                patch.object(gate, "run_done_when", side_effect=check):
            land.check_line(self.turn, log=self.said.append)

    def unanswered(self, *members):
        for directory in members:
            self.assertEqual(set(self.wait(directory)), {"line", "joined"}, directory.name)

    def taken_by_each_pass(self):
        return [len(call.args[1]) for call in self.taken.call_args_list]

    def test_a_change_behind_leaves_the_verdicts_ahead_written_and_the_pass_going(self):
        first, middle, broken, last = self.line()
        self.checked(last)
        self.assertEqual(len(self.checks), 3)
        for directory in (first, middle):
            self.assertIn("land", self.wait(directory))
        self.assertIn("fix", self.wait(broken))
        self.assertEqual(list(self.wait(broken)["after"]), [first.name, middle.name])
        self.unanswered(last)
        # the line's head alone: middle is woken as first's delivery ends (`deliver_next`)
        self.assertEqual([call.args[0] for call in self.wake.call_args_list], [first.name])
        self.assertTrue(any(line.startswith("last changed during this pass")
                            for line in self.said), self.said)

    def test_a_changed_first_member_ends_the_pass_with_nothing_written(self):
        members = self.line()
        self.checked(members[0])
        self.assertEqual(len(self.checks), 1)
        self.unanswered(*members)
        self.wake.assert_not_called()

    def test_a_changed_green_delivery_ahead_ends_the_pass_with_nothing_written(self):
        head = self.member("head", joined=0, **{"head.txt": "h\n"})
        self.advance()
        land.check_line(self.turn)
        self.assertIn("land", self.wait(head))
        with record.record(head) as current:
            current.update(state="running", pid=5678)
            review = dict(current["review"])
        behind = [self.member(f"member-{n}", joined=n, **{f"member-{n}.txt": f"{n}\n"})
                  for n in (1, 2)]
        self.wake.reset_mock()
        inner = self.check

        def check(cmds, *args, **kw):
            answer = inner(cmds, *args, **kw)
            with record.record(head) as current:
                current["review"] = {**review, "tree_sha": "f" * 40}
            return answer

        with patch.object(record, "process_active",
                          side_effect=lambda state: state.get("pid") == 5678), \
                patch.object(gate, "derived_heavy_limit", return_value=1), \
                patch.object(gate, "run_done_when", side_effect=check):
            self.checks.clear()
            land.check_line(self.turn)
        self.assertEqual(len(self.checks), 1)
        self.unanswered(*behind)
        self.wake.assert_not_called()

    def test_nothing_ahead_is_written_from_a_check_of_a_tree_holding_the_changed_member(self):
        # the deepest stack's green covers every member, and that stack holds the change: a
        # member ahead lands only with the members its check tested
        members = self.green_line()
        self.checked(members[2])
        self.assertEqual(len(self.checks), 1)
        self.unanswered(*members)
        self.wake.assert_not_called()

    def test_a_fruitless_pass_halves_the_next_down_to_one_and_a_verdict_restores_the_line(self):
        members = self.green_line()
        with patch.object(land, "CHECKED", 0):      # each pass here checked something
            for _ in range(3):
                self.checked(members[0])
            self.assertEqual(land.passes(self.turn)["fruitless"], 3)
            self.unanswered(*members)
            self.checked()      # one alone, however many moved nobody: its tree passed already
            self.assertIn("land", self.wait(members[0]))
            self.assertNotIn("fruitless", land.passes(self.turn))
            self.checked()
        self.assertEqual(self.taken_by_each_pass(), [4, 2, 1, 1, 3])
        for directory in members:
            self.assertIn("land", self.wait(directory))
        for line in ("1 pass in a row checked this line and moved nobody: this one checks the "
                     "first 2 of the 4 members waiting",
                     "2 passes in a row checked this line and moved nobody: this one checks the "
                     "first 1 of the 4 members waiting",
                     "3 passes in a row checked this line and moved nobody: this one checks the "
                     "first 1 of the 4 members waiting"):
            self.assertTrue(any(said.startswith(line) for said in self.said), self.said)

    def test_a_pass_that_only_waited_counts_for_nothing(self):
        members = self.green_line()
        with patch.object(land, "CHECKED", float("inf")):     # shorter than a check
            self.checked(members[0])
            self.checked(members[0])
        self.assertEqual(self.taken_by_each_pass(), [4, 4])
        self.assertNotIn("fruitless", land.passes(self.turn))

    def test_a_pass_that_waited_on_a_delivery_ahead_counts_for_nothing(self):
        head = self.member("head", joined=0, **{"head.txt": "h\n"})
        self.advance()
        land.check_line(self.turn)
        with record.record(head) as current:
            current.update(state="running", pid=5678)
            # a cut-short batch still delivering: its tested tree is not its own
            current["waiting_on"] = {**current["waiting_on"], "tested": "f" * 40}
        for n in range(1, 5):
            self.member(f"member-{n}", joined=n, **{f"member-{n}.txt": f"{n}\n"})
        self.taken.reset_mock()
        with patch.object(record, "process_active", side_effect=lambda state: state.get("pid") == 5678), \
                patch.object(land, "CHECKED", 0):   # each as long as a check, as on a busy host
            land.check_line(self.turn, log=self.said.append)
            land.check_line(self.turn, log=self.said.append)
        self.assertEqual(self.taken_by_each_pass(), [4, 4])
        self.assertNotIn("fruitless", land.passes(self.turn))

    def test_a_pass_that_died_counts_as_fruitless(self):
        members = self.green_line()
        land._keep_passes(self.turn, {"took": [], "started": 1.0, **GONE})
        self.checked()
        self.assertEqual(self.taken_by_each_pass(), [2])
        for directory in members[:2]:
            self.assertIn("land", self.wait(directory))
        self.unanswered(*members[2:])
        self.assertNotIn("fruitless", land.passes(self.turn))

    def test_a_pass_that_died_after_a_verdict_counts_for_nothing(self):
        members = self.green_line()
        land._keep_passes(self.turn, {"took": [], "fruitless": 1})
        keep = land._keep_passes
        # killed once its verdicts are written: no end is kept, which holds no `started`
        with patch.object(land, "_keep_passes",
                          side_effect=lambda turn, data: "started" in data and keep(turn, data)):
            self.checked()
        self.checked()
        self.assertEqual(self.taken_by_each_pass(), [2, 2])
        for directory in members:
            self.assertIn("land", self.wait(directory))


if __name__ == "__main__":
    unittest.main()
