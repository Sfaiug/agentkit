"""A round runs the repository's suite on the tests its change can affect, when the suite can narrow.

A `tests:` line naming `AK_CHANGED` opts in: after the executor hands in, every round runs that
suite besides the task's own checks, with `AK_CHANGED` naming a file of the paths the change
edits relative to the target, on the round's tree merged onto the target as it is now, or as
the run last integrated it where the target has since moved with a conflicting change, which
landing resolves outside the task budget.  A red goes back to the executor as any failing
check does, unless every test that failed fails on the target alone too (`AK_ONLY`), which ak
names.  A line without `AK_CHANGED` runs nothing extra.
The fake suite here treats each file in tests/ as a test failing when it says bad, and runs
just those a changed path names by its file name.  Black-box: the program `AK_BIN` names runs
from outside through tests/fixtures/akbin.py, against the bare origin of gitrig.py and the
GitHub of fakegh.py, with scripted harnesses from fakeadapter.py.
"""

import json
import shlex
import sys
import threading
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

SUITE_SH = """\
if [ -n "$AK_ONLY" ]; then names=$(cat "$AK_ONLY")
elif [ -n "$1" ]; then
  echo "changed: $(tr '\\n' ' ' < "$1")"
  echo "tree: $(ls | tr '\\n' ' ')"
  names=$(sed 's|.*/||; s|[.].*||' "$1")
else names=$(ls tests 2>/dev/null); fi
code=0
for t in $names; do
  [ -f "tests/$t" ] || continue
  [ -z "$AK_RAN" ] || echo "$t" >> "$AK_RAN"
  if grep -q bad "tests/$t"; then
    echo "FAILED $t"; [ -z "$AK_FAILED" ] || echo "$t" >> "$AK_FAILED"; code=1
  fi
done
exit $code
"""
NARROWS = 'sh suite.sh "$AK_CHANGED"'


def edit(files, then=None):
    """An executor's turn writing `files` and handing in, after the command `then`."""
    return {**({"sh": then} if then else {}), "write": {"retry.txt": "hello\n", **files},
            "commit": "edit", "final": "## Summary\nedited", "hand_in": [["done"]]}


def sibling(case, files):
    """The command an executor's turn runs to wait there while a sibling merges `files` into
    the target, whose commit is then `case.sibling`."""
    flag = case.fakes["claude"].dir
    started, release = flag / "started", flag / "release"

    def merge():
        deadline = time.monotonic() + 120
        while not started.exists() and time.monotonic() < deadline:
            time.sleep(0.1)
        case.sibling = case.rig.commit(files, "a sibling merges")
        release.touch()
    thread = threading.Thread(target=merge)
    thread.start()
    case.addClassCleanup(thread.join)
    return (f"touch {shlex.quote(str(started))}; "
            f"while [ ! -f {shlex.quote(str(release))} ]; do sleep 0.1; done")


class Round:
    """One run of a task in widgets, in a Home of the class's own."""
    suite = NARROWS
    tests = {"widget": "ok\n", "gadget": "ok\n"}
    claude = codex = "work"
    front = None
    done_when = ("test -f retry.txt",)

    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        files = {"AGENTS.md": f"---\ntests: {cls.suite}\n---\n# widgets\n", "suite.sh": SUITE_SH,
                 "widget.txt": "v1\n", **{f"tests/{n}": t for n, t in cls.tests.items()}}
        cls.rig = Rig(cls.home, "widgets", files=files)
        GitHub(cls.home).grant(cls.rig.slug, "WRITE")
        akconfig.write(cls.home, ["opus", "astra"])
        cls.fakes = fakeadapter.install(cls.home, claude=cls.claude, codex=cls.codex)
        task = taskfile.write(cls.home, cls.rig.path, front=cls.front,
                              done_when=cls.done_when)
        cls.during()
        cls.done = cls.home.ak("run", str(task), timeout=300)
        cls.run_dir = taskfile.only_run(cls.home)
        cls.state = json.loads((cls.run_dir / "run.json").read_text())

    @classmethod
    def during(cls):
        """What happens beside the run while it goes."""

    def roles(self):
        return [run["role"] for run in self.fakes["claude"].runs()]

    def checks(self, n=1):
        return (self.run_dir / f"round-{n}" / "donewhen.log").read_text()


class AffectedRed(Round, unittest.TestCase):
    """A sibling merges into the target while the executor works, and the change breaks the
    test of what it edits; the fixer mends it."""

    @classmethod
    def during(cls):
        cls.fakes["claude"].behave(
            edit({"widget.txt": "v2\n", "tests/widget": "bad\n"},
                 sibling(cls, {"sibling.txt": "merged\n"})),
            edit({"tests/widget": "ok\n"}))

    def fixer(self):
        return (self.run_dir / "round-1" / "fixer" / "prompt.md").read_text()

    def test_the_suite_sees_exactly_the_change_s_paths_on_the_tree_merged_onto_the_target(self):
        # the fix put tests/widget back as the target has it: no longer a path the change edits
        for said, paths in ((self.fixer(), ["retry.txt", "tests/widget", "widget.txt"]),
                            (self.checks(), ["retry.txt", "widget.txt"])):
            lines = said.splitlines()
            self.assertEqual(next(l for l in lines if l.startswith("changed: ")).split()[1:], paths)
            tree = next(line for line in lines if line.startswith("tree: ")).split()
            self.assertIn("sibling.txt", tree)
            self.assertIn("retry.txt", tree)
            self.assertIn(f"onto origin/main at {self.sibling[:12]}", said)

    def test_a_red_goes_back_to_the_executor_in_the_same_run(self):
        self.assertEqual(self.roles(), ["executor", "fixer"])
        self.assertIn("FAILED widget", self.fixer())
        self.assertNotIn("FAILED", self.checks())
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual((self.state["state"], self.state["merged"]), ("pass", True))


class TargetsOwnRed(Round, unittest.TestCase):
    """The test the change affects fails on the target too; the one it does not affect is
    never run."""
    tests = {"widget": "bad\n", "gadget": "bad\n"}
    claude, codex, front = edit({"widget.txt": "v2\n"}), "fail", {"rounds": 1}

    def test_a_test_failing_on_the_target_alone_does_not_fail_the_round(self):
        self.assertEqual(self.roles(), ["executor"])
        said = self.checks()
        self.assertIn("FAILED widget", said)
        self.assertNotIn("FAILED gadget", said)
        self.assertRegex(said, r"Tests failing on origin/main at \w+ alone too, the target's "
                               r"own: widget\n")
        self.assertIn("done-when: all passed",
                      (self.run_dir / "log.txt").read_text())


class ConflictingSibling(Round, unittest.TestCase):
    """A sibling merges a change to the file the executor edits while it works, and moves the
    suite to a script only it holds: the conflict is landing's to resolve, so the round judges
    the change on the target it started from, by that target's own suite."""

    @classmethod
    def during(cls):
        conflicting = {"widget.txt": "v3\n", "suite-next.sh": SUITE_SH,
                       "AGENTS.md": '---\ntests: sh suite-next.sh "$AK_CHANGED"\n---\n# widgets\n'}
        cls.fakes["claude"].behave(
            edit({"widget.txt": "v2\n"}, sibling(cls, conflicting)),
            {"sh": "echo v3 v2 > widget.txt && git add widget.txt && "
                   "GIT_EDITOR=true git rebase --continue",
             "final": "Resolved.", "hand_in": [["done"]]})

    def test_the_round_passes_and_landing_resolves_the_conflict_outside_the_task_budget(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual((self.state["state"], self.state["merged"]), ("pass", True))
        self.assertEqual(len(self.state["round_summaries"]), 1)
        self.assertEqual(self.roles(), ["executor", "fixer"])
        log = (self.run_dir / "log.txt").read_text()
        self.assertIn(f"origin/main moved to {self.sibling[:12]} with a change conflicting", log)
        self.assertIn("conflict round 1/", log)
        self.assertEqual(self.rig.origin("show", "main:widget.txt"), "v3 v2")


class NotNarrowing(Round, unittest.TestCase):
    """Only the target's `tests:` line opts in: a task's own `# once` line naming the variable
    runs at landing alone."""
    suite = "sh suite.sh"
    done_when = ("test -f retry.txt", 'test -z "$AK_CHANGED"  # once')

    def test_a_line_without_ak_changed_runs_nothing_extra_in_a_round(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        for n in range(1, len(self.state["round_summaries"]) + 1):
            with self.subTest(round=n):
                self.assertEqual([line for line in self.checks(n).splitlines()
                                  if line.startswith("$ ")], ["$ test -f retry.txt"])


if __name__ == "__main__":
    unittest.main()
