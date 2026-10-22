"""A `# once` check and a repository's declared suite run once, at landing, never in a round.

Rounds are where work is built and reviewed, and they run only the task's own checks.  A
done-when line ending `# once`, and the `tests:` suite a repository declares in its AGENTS.md
front matter, are the heavy checks: each runs once, at landing, on the reviewed work about to
merge, before it merges.  A task line that is the declared suite itself is that suite and runs
once with it.  Each check here appends what it saw to one log in the project's git directory,
the one place both a check's box and the test reach, and asking GitHub to merge appends there
too, so the log's lines are the order things happened in.  The work takes two rounds: the
first review finds `retry.txt` says broken, and the fixer's round mends it.  Black-box: the
program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, against the bare
origin of gitrig.py and the GitHub of fakegh.py, with scripted harnesses from fakeadapter.py.
"""

import json
import shlex
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

CHECK = "test -f retry.txt"
# Round 1's work, which its review fails; the fixer's `work` then writes "hello".
BROKEN = {"write": {"retry.txt": "broken\n"}, "commit": "add retry.txt", "final": "wrote it",
          "hand_in": [["done"]]}
FINDING = {"final": "Found one.", "hand_in": [
    ["finding", "retry.txt:1", "it says broken", "the file says broken", "--run",
     "! grep -q broken retry.txt"], ["done"]]}


def noting(word):
    """A check appending `<word> <what retry.txt holds>` to the events log."""
    return f'echo "{word} $(cat retry.txt)" >> "$(git rev-parse --git-common-dir)/events.log"'


SUITE = noting("suite")
DECLARED = {"AGENTS.md": f"---\ntests: {SUITE}\n---\n# widgets\n"}


class Landing:
    """One run of a task in widgets to its merge, in a Home of the class's own."""
    files = {}
    done_when = (CHECK,)
    rounds = 2

    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.rig = Rig(cls.home, "widgets", files=cls.files)
        GitHub(cls.home).grant(cls.rig.slug, "WRITE")
        cls.events = cls.rig.path / ".git" / "events.log"
        github = cls.home.root / "github"
        (cls.home.bin / "gh").rename(github)
        cls.home.fake("gh", f'#!/bin/sh\ncase " $* " in *" pr merge "*)\n'
                            f'  echo merge >> {shlex.quote(str(cls.events))} ;;\nesac\n'
                            f'exec {shlex.quote(str(github))} "$@"\n')
        akconfig.write(cls.home, ["opus", "astra"])
        if cls.rounds == 2:
            fakeadapter.install(cls.home, claude=[BROKEN, "work"], codex=[FINDING, "pass"])
        else:
            fakeadapter.install(cls.home, claude="work", codex="pass")
        task = taskfile.write(cls.home, cls.rig.path, done_when=cls.done_when)
        cls.done = cls.home.ak("run", str(task), timeout=300)
        cls.run_dir = taskfile.only_run(cls.home)
        cls.state = json.loads((cls.run_dir / "run.json").read_text())

    def logged(self):
        return self.events.read_text().splitlines() if self.events.exists() else []

    def test_the_work_passes_its_last_review_and_merges(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual([summary["verdict"] for summary in self.state["round_summaries"]],
                         ["FAIL", "PASS"][2 - self.rounds:])
        self.assertEqual((self.state["state"], self.state["merged"]), ("pass", True))

    def test_each_round_runs_only_the_task_s_own_check(self):
        for n in range(1, self.rounds + 1):
            with self.subTest(round=n):
                log = (self.run_dir / f"round-{n}" / "donewhen.log").read_text()
                self.assertEqual([line for line in log.splitlines() if line.startswith("$ ")],
                                 [f"$ {CHECK}"])


class OnceLine(Landing, unittest.TestCase):
    done_when = (CHECK, noting("once") + "  # once")

    def test_the_once_line_runs_once_on_the_reviewed_work_before_the_merge(self):
        self.assertEqual(self.logged(), ["once hello", "merge"])
        landing = self.state["final_check"]
        self.assertEqual((landing["outcome"], landing["where"], landing["sha"]),
                         ("passed", "landing", self.state["review"]["head_sha"]))


class DeclaredSuite(Landing, unittest.TestCase):
    files = DECLARED

    def test_the_suite_runs_once_on_the_reviewed_work_before_the_merge(self):
        self.assertEqual(self.logged(), ["suite hello", "merge"])


class TaskNamesTheSuite(Landing, unittest.TestCase):
    files = DECLARED
    done_when = (CHECK, SUITE)
    rounds = 1

    def test_a_task_line_that_is_the_suite_runs_once_with_it_at_landing(self):
        self.assertEqual(self.logged(), ["suite hello", "merge"])


if __name__ == "__main__":
    unittest.main()
