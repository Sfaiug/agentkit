"""A test that failed, then passed, on two trees of the landing line within a week -- named so
by the checks, or confirmed red by one and passing on the same tree later -- gets one repair
run naming it, owned by the run whose check saw it the second time; one tree gets none, and
no second starts until a merged change edits the test or the week has passed.

Offline: real Git and the lander's own check, the suite faked to say what it found, sandbox
records, an injected clock and the repair's launch caught, leaving the record it would.
"""

from contextlib import nullcontext
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_lander
from agentkit import config, gate, land, record, run, watch

TEST, LINT = "test_timing.py", "acme-lint"
CMDS = [LINT, test_lander.SUITE]


class FlakyTestGetsARepair(test_lander.LanderFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.now = 1000.0
        self.stack.enter_context(patch.object(land, "time", SimpleNamespace(time=lambda: self.now)))
        self.stack.enter_context(patch.object(gate, "gate_turn", return_value=nullcontext()))
        self.stack.enter_context(patch.object(watch, "seat_closed", return_value=False))
        self.launch = self.stack.enter_context(patch.object(
            run, "launch_for_seat", side_effect=lambda directory, state, origin, *_, **_kw:
            (directory / "run.json").write_text(json.dumps(
                {**origin, "run_id": directory.name, "state": "running"}))))

    def check(self, cmds, cwd, log_path, *args, flaky, marks, pieces, confirmed, **kw):
        """The checks as `found` says: tests failing, then passing, and by command those
        confirmed `failed`, an empty list for a command red with none named."""
        flaky.extend(self.found.get("flaky", ()))
        for cmd in cmds:
            failed = self.found.get("failed", {}).get(cmd)
            marks.append(int(failed is not None))
            pieces[cmd], confirmed[cmd] = {"1/1": marks[-1]}, {"1/1": failed or []}
        return not any(marks), json.dumps(self.found)

    def seen(self, name, files=None, **found):
        """Member `name`, its tree adding `files` (its name by default), checked once more."""
        directory = config.RUNS / name
        if not directory.exists():
            self.member(name, **({f"{name}.txt": name} if files is None else files))
        state = {**record.read_state(directory), "launched_session": "seat"}
        run.git(self.repo, "checkout", "-q", "--detach", state["review"]["head_sha"])
        self.found = found or {"flaky": [TEST]}
        land._check(directory, state, self.repo, CMDS, directory / "lander.log", lambda _: None)
        run.git(self.repo, "checkout", "-q", "main")

    def shown(self):
        """The logs the last repair's task names: the run of each, and what its check found."""
        task = (self.launch.call_args.args[0] / "task.md").read_text()
        logs = [Path(line[2:]) for line in task.splitlines() if line.startswith(f"- {config.RUNS}")]
        return [(log.parent.name, json.loads(log.read_text().split("\n\n")[1])) for log in logs]

    def merge(self, path):
        """A change to `path` merged on the target."""
        (self.repo / path).write_text(f"{self.now}\n")
        self.commit(f"edit {path}")
        run.git(self.repo, "push", "-q", "origin", "main")

    def test_a_test_flaky_on_two_trees_gets_one_repair_run_naming_it(self):
        self.seen("one")
        self.launch.assert_not_called()
        self.seen("two")
        (directory, state, origin, *_), = (call.args for call in self.launch.call_args_list)
        self.assertEqual(state["run_id"], "two")
        self.assertEqual(origin["repair"], {"target": "main", "command": TEST, "flaky": 1000.0})
        self.assertEqual(origin["repair_tip"], run.git(self.repo, "rev-parse", "origin/main"))
        task = (directory / "task.md").read_text()
        for said in (f"# Make {TEST} deterministic", f"`{TEST}` in {self.repo}", "2 times",
                     "without weakening what it checks",
                     f"```bash\n{test_lander.SUITE}  # once\n```"):
            self.assertIn(said, task)
        self.assertNotIn("not-needed", task)
        self.assertEqual(self.shown(), [("one", {"flaky": [TEST]}), ("two", {"flaky": [TEST]})])

    def test_a_red_test_its_command_passes_later_on_its_tree_is_one_of_them(self):
        red = {"failed": {LINT: ["lint.py"], test_lander.SUITE: [TEST]}}
        green = {"failed": {LINT: []}}
        self.seen("one", **red)
        self.seen("one", **green)       # its log written over, in the same second
        self.launch.assert_not_called()
        self.seen("two")
        self.assertEqual(self.shown(), [("one", red), ("one", green), ("two", {"flaky": [TEST]})])
        self.seen("three", {"three.txt": "3"}, flaky=["lint.py"])
        self.assertEqual(self.launch.call_count, 1)     # its command never passed on one's tree

    def test_one_flake_or_two_on_one_tree_start_none(self):
        self.seen("one", {})
        self.seen("same", {})
        self.seen("other", {}, flaky=["tests/test_other.py"])
        self.launch.assert_not_called()

    def test_no_second_repair_starts_while_the_test_is_unfixed_within_a_week(self):
        self.seen("one")
        self.seen("two")
        self.merge("docs.md")
        self.now += land.FLAKY - 1
        self.seen("three")
        self.seen("four")
        self.assertEqual(self.launch.call_count, 1)
        self.now += 1
        self.seen("five")
        self.assertEqual(self.launch.call_count, 1)
        self.seen("six")
        self.assertEqual(self.launch.call_count, 2)

    def test_a_merged_change_editing_the_test_clears_it(self):
        self.seen("one")
        self.seen("two")
        self.merge(TEST)
        self.now += 1
        self.seen("three")
        self.assertEqual(self.launch.call_count, 1)
        self.seen("four")
        self.assertEqual(self.launch.call_count, 2)
        self.assertIn("2 times", (self.launch.call_args.args[0] / "task.md").read_text())


if __name__ == "__main__":
    unittest.main()
