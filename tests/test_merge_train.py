"""Only the member that turns a green stack red fixes it; later members keep stacking.

Offline: real Git and checks, sandbox records, fake processes and wakes.
"""

from pathlib import Path
import unittest
from unittest.mock import patch

from test_lander import LanderFixture, ONCE, SUITE, land, record, run, gate


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
        run.git(self.repo, "checkout", original["branch"].replace("clash", "first"))
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
