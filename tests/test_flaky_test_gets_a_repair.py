"""A test that failed, then passed, on two trees of the landing line within a week -- named so
by the checks, or confirmed red by one and passing on the same tree later -- gets one repair
run naming it, owned by the run whose check saw it the second time; one tree gets none, and
no second starts until a merged change edits the test or the week has passed.  A test is
kept toward its file, its name up to its first `::` or `#`, as a ledger's full names are.

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

    def kept(self, **tests):
        """A ledger from before files, keeping `tests` (`a` for `TEST::test_a`) by full name."""
        self.turn.with_suffix(".flakes").write_text(json.dumps(
            {"tests": {f"{TEST}::test_{name}": entry for name, entry in tests.items()}}))

    def held(self, at):
        """A repair held from `at` on the target's tip."""
        return {"repair": {"run": "fix-old", "at": at,
                           "sha": run.git(self.repo, "rev-parse", "origin/main")}}

    def test_what_a_ledger_keeps_under_a_test_s_full_name_counts_toward_its_file(self):
        self.kept(a={"seen": [{"tree": "elsewhere", "at": self.now, "logs": ["elsewhere.log"]}]})
        self.seen("one", flaky=[f"{TEST}::test_b"])
        (directory, _, origin, *_), = (call.args for call in self.launch.call_args_list)
        self.assertEqual(origin["repair"]["command"], TEST)
        task = (directory / "task.md").read_text()
        self.assertIn(f"`{TEST}::test_a`:\n- elsewhere.log", task)
        self.assertIn(f"`{TEST}::test_b`", task)
        self.kept(a=self.held(self.now))
        self.seen("two", flaky=[f"{TEST}::test_b"])
        self.seen("three", flaky=[f"{TEST}::test_b"])
        self.assertEqual(self.launch.call_count, 1)

    def test_a_ledger_s_newest_hold_holds_the_file(self):
        self.kept(a=self.held(self.now), b=self.held(self.now - land.FLAKY + 1))
        self.seen("other", flaky=["tests/test_other.py"])
        self.now += 1
        self.seen("one", flaky=[f"{TEST}::test_c"])
        self.seen("two", flaky=[f"{TEST}::test_c"])
        self.launch.assert_not_called()

    def test_a_ledger_s_released_hold_leaves_the_sightings_after_it(self):
        self.kept(a=self.held(self.now),
                  b={"seen": [{"tree": "elsewhere", "at": self.now, "logs": ["elsewhere.log"]}]})
        self.merge(TEST)
        self.seen("one", flaky=[f"{TEST}::test_c"])
        self.assertEqual(self.launch.call_count, 1)

    def test_each_sighting_of_a_ledger_ages_alone(self):
        self.kept(a={"seen": [{"tree": "elsewhere", "at": at, "logs": ["elsewhere.log"]}
                              for at in (self.now - land.FLAKY + 1, self.now)]},
                  b={"seen": [{"tree": "gone", "at": self.now - land.FLAKY + 1, "logs": []}]})
        self.seen("other", flaky=["tests/test_other.py"])
        self.now += 1
        self.seen("one", flaky=[f"{TEST}::test_a"])
        self.assertEqual(self.launch.call_count, 1)

if __name__ == "__main__":
    unittest.main()
