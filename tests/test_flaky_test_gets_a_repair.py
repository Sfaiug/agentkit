"""A test that failed, then passed, on two trees of the landing line within a week gets one
repair run of the target naming it, owned by the run whose check saw it the second time: those
the checks name so, and those a red check confirmed once a check passes on the same tree.  One
tree is not enough, and no second repair starts until a merged change edits the test or the
week has passed.

Offline: real Git and the lander's own check of each member's tree, the suite faked to say what
it found, sandbox records, an injected clock and the repair's launch caught.
"""

from contextlib import nullcontext
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_lander
from agentkit import config, gate, land, record, run, watch

TEST = "tests/test_timing.py"


class FlakyTestGetsARepair(test_lander.LanderFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.now, self.launched, self.found = 1000.0, [], {"flaky": [TEST]}
        self.stack.enter_context(patch.object(land, "time", SimpleNamespace(time=lambda: self.now)))
        self.stack.enter_context(patch.object(gate, "gate_turn", return_value=nullcontext()))
        self.stack.enter_context(patch.object(watch, "seat_closed", return_value=False))
        self.stack.enter_context(patch.object(run, "launch_for_seat", side_effect=lambda
                                              directory, state, origin, *_a, **_kw:
                                              self.launched.append((directory, state, origin))))

    def check(self, cmds, cwd, log_path, *args, flaky, marks, pieces, confirmed, **kw):
        """The suite as `found` says: the tests it found failing, then passing, or a red piece
        confirming its `failed` tests."""
        flaky.extend(self.found.get("flaky", ()))
        failed = self.found.get("failed")
        marks.append(1 if failed else 0)
        if failed:
            pieces.setdefault(cmds[0], {})["1/1"] = 1
            confirmed.setdefault(cmds[0], {})["1/1"] = failed
        return not failed, f"$ {cmds[0]}\n[exit {1 if failed else 0}]\n"

    def seen(self, name, files=None, **found):
        """Member `name`, its tree adding `files` (its name by default), checked once."""
        directory = self.member(name, **({f"{name}.txt": name} if files is None else files))
        state = {**record.read_state(directory), "launched_session": "seat"}
        run.git(self.repo, "checkout", "-q", "--detach", state["review"]["head_sha"])
        self.found = found or {"flaky": [TEST]}
        land._check(directory, state, self.repo, [test_lander.SUITE], directory / "lander.log",
                    lambda _: None)
        run.git(self.repo, "checkout", "-q", "main")

    def merge(self, path):
        """A change to `path` merged on the target."""
        (self.repo / path).parent.mkdir(exist_ok=True)
        (self.repo / path).write_text(f"{self.now}\n")
        self.commit(f"edit {path}")
        run.git(self.repo, "push", "-q", "origin", "main")

    def test_a_test_flaky_on_two_trees_gets_one_repair_run_naming_it(self):
        self.seen("one")
        self.assertEqual(self.launched, [])
        self.seen("two")
        (directory, state, origin), = self.launched
        self.assertEqual(state["run_id"], "two")
        self.assertEqual(origin["repair"], {"target": "main", "command": TEST})
        self.assertEqual(origin["repair_tip"], run.git(self.repo, "rev-parse", "origin/main"))
        task = (directory / "task.md").read_text()
        for said in (f"# Make {TEST} deterministic", f"`{TEST}` in {self.repo}", "2 times",
                     str(config.RUNS / "one" / "lander.log"), str(config.RUNS / "two" / "lander.log"),
                     "without weakening what it checks",
                     f"## Done when\n```bash\n{test_lander.SUITE}  # once\n```"):
            self.assertIn(said, task)
        self.assertNotIn("not-needed", task)

    def test_a_red_that_passes_on_its_own_tree_is_one_of_them(self):
        self.seen("one", failed=[TEST])
        self.seen("again", {"one.txt": "one"}, flaky=[])
        self.assertEqual(self.launched, [])
        self.seen("two")
        self.assertEqual(len(self.launched), 1)

    def test_one_flake_or_two_on_one_tree_start_none(self):
        self.seen("one", {})
        self.seen("same", {})
        self.seen("other", {}, flaky=["tests/test_other.py"])
        self.assertEqual(self.launched, [])

    def test_no_second_repair_starts_while_the_test_is_unfixed_within_a_week(self):
        self.seen("one")
        self.seen("two")
        self.merge("docs.md")
        self.now += land.FLAKY - 1
        self.seen("three")
        self.seen("four")
        self.assertEqual(len(self.launched), 1)
        self.now += 1
        self.seen("five")
        self.assertEqual(len(self.launched), 1)
        self.seen("six")
        self.assertEqual(len(self.launched), 2)

    def test_a_merged_change_editing_the_test_clears_it(self):
        self.seen("one")
        self.seen("two")
        self.merge(TEST)
        self.seen("three")
        self.assertEqual(len(self.launched), 1)
        self.seen("four")
        self.assertEqual(len(self.launched), 2)
        self.assertIn("2 times", (self.launched[1][0] / "task.md").read_text())


if __name__ == "__main__":
    unittest.main()
