"""A round runs the task's own checks; the repository's suite runs once, whole, at landing.

Owner, 10 Nov 2026: no round runs a suite, on any project, and no project can opt in.  The
`tests:` suite runs once, whole, at landing, and a red found there goes to the run's fixer.
`AK_CHANGED` is a name ak neither sets nor reads: a line naming it, as this one does, runs at
landing like any other, the variable unset.  A boxed check writes none of the test's files, so the suite notes
each start, and what `AK_CHANGED` held, on the test's socket, as the reviewer notes each review.
Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, against
the bare origin of gitrig.py and the GitHub of fakegh.py, with scripted harnesses from
fakeadapter.py.
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

# Each test in tests/ is a shell script; a failing one is named in upper case, so that no prompt
# reads it off the command.
SUITE = """import os, socket, subprocess, sys
socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM).sendto(
    ("suite " + os.environ.get("AK_CHANGED", "(unset)")).encode(), {said!r})
failed = [t for t in sorted(os.listdir("tests")) if subprocess.run(["sh", "tests/" + t]).returncode]
print("".join(t.upper() + " IS BROKEN\\n" for t in failed), end="")
sys.exit(bool(failed))
"""
SAID = "GADGET.SH IS BROKEN"
BREAK = {"write": {"retry.txt": "hello\n", "widget.txt": "v2\n"}, "commit": "widget v2",
         "final": "## Summary\nwidget v2", "hand_in": [["done"]]}
FIX = {"write": {"tests/gadget.sh": "grep -qx v2 widget.txt\n"}, "commit": "gadget reads v2",
       "final": "## Summary\ngadget reads v2", "hand_in": [["done"]]}


class Run:
    """One run of a task whose own check is `test -f retry.txt`, in widgets, whose suite's one
    test reads widget.txt; the executor's turns are `work`."""
    work = "work"

    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.said = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        cls.addClassCleanup(cls.said.close)
        cls.said.bind(address := f"\0ak-landing-alone-{os.getpid()}-{cls.__name__}")
        cls.rig = Rig(cls.home, "widgets", files={
            "AGENTS.md": '---\nhealth: none\ntests: python3 suite.py "$AK_CHANGED"\n---\n# widgets\n',
            "suite.py": SUITE.format(said=address), "widget.txt": "v1\n",
            "tests/gadget.sh": "grep -qx v1 widget.txt\n"})
        cls.base = cls.rig.head()
        GitHub(cls.home).grant(cls.rig.slug, "WRITE")
        akconfig.write(cls.home, ["opus", "astra"])
        review = ("import socket; socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)"
                  f".sendto(b'review', {address!r})")
        cls.fakes = fakeadapter.install(cls.home, claude=cls.work, codex={
            "sh": f"python3 -c {shlex.quote(review)}", "final": "Handed in.",
            "hand_in": [["done"]]})
        cls.done = cls.home.ak("run", str(taskfile.write(cls.home, cls.rig.path)), timeout=300)
        cls.run_dir = taskfile.only_run(cls.home)
        cls.state = json.loads((cls.run_dir / "run.json").read_text())
        cls.said.setblocking(False)
        cls.notes = []
        while True:
            try:
                cls.notes.append(cls.said.recv(4096).decode())
            except BlockingIOError:
                break

    def test_the_run_merges(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual((self.state["state"], self.state["merged"]), ("pass", True))

    def test_the_reviewer_is_asked_before_the_suite_ever_starts(self):
        self.assertEqual(self.notes[0], "review", self.notes)

    def test_the_suite_runs_only_whole_with_ak_changed_unset(self):
        self.assertEqual({note for note in self.notes if note != "review"}, {"suite (unset)"},
                         self.notes)


class TheSuiteRunsOnceAtLanding(Run, unittest.TestCase):
    def test_once(self):
        self.assertEqual(self.notes, ["review", "suite (unset)"])


class ARedAtLandingGoesToTheFixer(Run, unittest.TestCase):
    """The change breaks the suite's test, which the task's own check does not run."""
    work = [BREAK, FIX]

    def test_the_round_passes_and_the_landing_check_s_red_goes_to_the_fixer(self):
        self.assertEqual([summary["verdict"] for summary in self.state["round_summaries"]],
                         ["PASS"])
        self.assertEqual([run["role"] for run in self.fakes["claude"].runs()],
                         ["executor", "fixer"])
        self.assertIn(SAID, (self.run_dir / "round-1/final-fixer/prompt.md").read_text())

    def test_nothing_is_merged_until_the_suite_is_green(self):
        self.assertEqual(len(self.rig.origin("rev-list", f"{self.base}..main").split()), 1)
        self.assertEqual(self.rig.origin("show", "main:tests/gadget.sh"),
                         "grep -qx v2 widget.txt")
        self.assertEqual(self.rig.origin("show", "main:widget.txt"), "v2")


if __name__ == "__main__":
    unittest.main()
