"""Before its review a round runs, as one more of its checks, the `tests:` line handed the tests its
change edits: each that the project's time record holds a time for, named as the record spells it,
in the file AK_ONLY names.  Its failing exit sends the round back, as any check's does.  A change
that edits no timed test runs none of the project's tests, nor does a project with no record, and
no round starts the whole suite: that runs at landing alone.

Owner, 16 Nov 2026, amending 10 Nov's "no round runs a suite": "Yes, this small set … And make sure
this also happens for new repos we work on".

Black-box, as tests/test_key_the_suite_runs_at_landing_alone.py: the program `AK_BIN` names runs
three tasks in turn from outside through tests/fixtures/akbin.py, against the bare origin of
gitrig.py and the GitHub of fakegh.py, with scripted harnesses from fakeadapter.py.  A boxed check
writes none of the test's files, so the suite notes each start, and the tests it was handed, on
the test's socket, as the reviewer notes each review.
"""

import json
import os
from pathlib import Path
import shlex
import socket
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

# A runner that reports to ak: each test in tests/ is a shell script it names `./tests/<name>`,
# timing each that passes as ak reads a time, running just those AK_ONLY lists where it is set
# and naming them as run in AK_RAN.  A failing one is named in upper case, so that no prompt reads
# it off the command.
SUITE = """import os, socket, subprocess, sys
only = os.environ.get("AK_ONLY")
tests = (open(only).read().split() if only else
         [os.path.join(".", "tests", name) for name in sorted(os.listdir("tests"))])
socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM).sendto(
    ("suite " + (" ".join(tests) if only else "whole")).encode(), {said!r})
failed = [test for test in tests if subprocess.run(["sh", test]).returncode]
for test in tests:
    print(test.upper() + " IS BROKEN" if test in failed else "PASS  " + test + " (0.1s)")
if os.environ.get("AK_RAN"):
    open(os.environ["AK_RAN"], "w").write("".join(test + "\\n" for test in tests))
sys.exit(bool(failed))
"""
SAID = "./TESTS/GADGET.SH IS BROKEN"
# One task each, in turn: its check is that its file exists.
TASKS = ("one", "two", "three")
WORK = [
    # No record yet: the edited test is timed by nothing.
    {"write": {"one.txt": "1\n", "tests/gadget.sh": "grep -x v1 widget.txt >/dev/null\n"},
     "commit": "one", "final": "## Summary\none", "hand_in": [["done"]]},
    # The record now times gadget.sh and gizmo.sh: this edits neither, and adds a test.
    {"write": {"two.txt": "2\n", "notes.txt": "two\n", "tests/new.sh": "true\n"},
     "commit": "two", "final": "## Summary\ntwo", "hand_in": [["done"]]},
    # Edits gadget.sh, which then fails, and the fix makes it pass.
    {"write": {"three.txt": "3\n", "tests/gadget.sh": "grep -qx v2 widget.txt\n"},
     "commit": "three", "final": "## Summary\nthree", "hand_in": [["done"]]},
    {"write": {"widget.txt": "v2\n"}, "commit": "widget v2", "final": "## Summary\nwidget v2",
     "hand_in": [["done"]]},
]


class ThreeRuns(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        said = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        cls.addClassCleanup(said.close)
        said.bind(address := f"\0ak-round-runs-its-tests-{os.getpid()}")
        said.setblocking(False)
        cls.rig = Rig(cls.home, "widgets", files={
            "AGENTS.md": "---\nhealth: none\ntests: python3 suite.py\n---\n# widgets\n",
            "suite.py": SUITE.format(said=address), "widget.txt": "v1\n",
            "tests/gadget.sh": "grep -qx v1 widget.txt\n", "tests/gizmo.sh": "test -f widget.txt\n"})
        GitHub(cls.home).grant(cls.rig.slug, "WRITE")
        akconfig.write(cls.home, ["opus", "astra"])
        review = ("import socket; socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)"
                  f".sendto(b'review', {address!r})")
        cls.fakes = fakeadapter.install(cls.home, claude=WORK, codex={
            "sh": f"python3 -c {shlex.quote(review)}", "final": "Handed in.",
            "hand_in": [["done"]]})
        cls.done, cls.notes, cls.states = {}, {}, {}
        for name in TASKS:
            task = taskfile.write(cls.home, cls.rig.path, f"Add {name}",
                                  done_when=(f"test -f {name}.txt",))
            cls.done[name] = cls.home.ak("run", str(task), timeout=300)
            cls.notes[name] = []
            while True:
                try:
                    cls.notes[name].append(said.recv(4096).decode())
                except BlockingIOError:
                    break
            run_dir = next(path for path in taskfile.runs(cls.home)
                           if path.name.endswith(f"-add-{name}"))
            cls.states[name] = (run_dir, json.loads((run_dir / "run.json").read_text()))

    def test_each_run_merges(self):
        for name in TASKS:
            done, (_, state) = self.done[name], self.states[name]
            self.assertEqual(done.code, 0, f"{name}: {done.out}{done.err}")
            self.assertEqual((state["state"], state["merged"]), ("pass", True), name)

    def test_a_project_with_no_time_record_runs_none_of_its_tests(self):
        self.assertEqual(self.notes["one"], ["review", "suite whole"])

    def test_a_change_that_edits_no_timed_test_runs_none_of_its_tests(self):
        self.assertEqual(self.notes["two"], ["review", "suite whole"])

    def test_an_edited_timed_test_runs_before_review_and_its_failing_exit_sends_the_round_back(self):
        # failing, its re-run failing, then passing after the fixer's turn
        self.assertEqual(self.notes["three"], ["suite ./tests/gadget.sh"] * 3
                         + ["review", "suite whole"])
        self.assertEqual([run["role"] for run in self.fakes["claude"].runs()],
                         ["executor", "executor", "executor", "fixer"])
        run_dir, state = self.states["three"]
        self.assertIn(SAID, (run_dir / "round-1/fixer/prompt.md").read_text())
        self.assertEqual([summary["verdict"] for summary in state["round_summaries"]], ["PASS"])

    def test_no_round_starts_the_whole_suite(self):
        for name in TASKS:
            notes = self.notes[name]
            self.assertNotIn("suite whole", notes[:notes.index("review")], name)


if __name__ == "__main__":
    unittest.main()
