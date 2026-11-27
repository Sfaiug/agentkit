"""A green chosen-tests check on a commit is not run again when its review is asked again.

Owner, 20 Nov 2026: "Once, after review passes"; 22 Nov, told an interrupted run repeats them:
"No, keep trying".

Black-box, on the fixtures of tests/test_key_a_reviewers_pass_runs_the_quick_set.py: `AK_BIN`
runs two tasks editing tests/often.sh, timed by the project's record.  A one-shot git wrapper
stops each after its chosen tests end and before its verdict is saved: the first's chosen tests
ended green and its resume passes without running them again; the second's ended red and its
resume runs them again.
"""

import contextlib
import json
import os
from pathlib import Path
import shlex
import shutil
import sqlite3
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home, SYSTEM
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig
from fixtures.notes import Notes
from test_key_a_reviewers_pass_runs_the_quick_set import CHOSEN, OFTEN, review
from test_key_a_round_runs_its_changes_tests import SUITE
from test_key_history_db import OWNERS

REAL_GIT = shutil.which("git", path=os.pathsep.join(SYSTEM))
STOP_GIT = """#!/bin/sh
if [ -f {arm} ]; then
  name=$(cat {arm})
  for log in {runs}/*-add-"$name"/round-1/donewhen.log; do
    if [ -f "$log" ] && grep -q '^Commit:' "$log" && grep -q '^\\$ python3 suite\\.py$' "$log"; then
      rm -f {arm}
      echo 'fatal: could not read Username: terminal prompts disabled' >&2
      exit 1
    fi
  done
fi
exec {git} "$@"
"""
WORK = [
    {"write": {"green.txt": "1\n", "tests/often.sh": f"# green\n{OFTEN}"}, "commit": "green",
     "final": "## Summary\ngreen", "hand_in": [["done"]]},
    {"write": {"red.txt": "2\n", "widget.txt": "v2\n", "tests/often.sh": f"# red\n{OFTEN}"},
     "commit": "red", "final": "## Summary\nred", "hand_in": [["done"]]},
]


class ChosenNotRepeated(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        said = Notes()
        cls.addClassCleanup(said.close)
        cls.rig = Rig(cls.home, "widgets", files={
            "AGENTS.md": "---\nhealth: none\ntests: python3 suite.py\n---\n# widgets\n",
            "suite.py": SUITE.format(said=said.address), "widget.txt": "v1\n",
            "tests/often.sh": OFTEN, "tests/other.sh": "true\n"})
        cls.rig.git("config", "ak.repository", "0123456789ab")
        cls.home.write(".agentkit/state/test-times-0123456789ab.json",
                       {"./tests/often.sh": 1, "./tests/other.sh": 1})
        GitHub(cls.home).grant(cls.rig.slug, "WRITE")
        akconfig.write(cls.home, ["opus", "astra"])
        arm = cls.home.root / "stop-after-chosen"
        cls.home.fake("git", STOP_GIT.format(
            arm=shlex.quote(str(arm)),
            runs=shlex.quote(str(cls.home.path / ".agentkit/runs")),
            git=shlex.quote(REAL_GIT)))
        cls.fakes = fakeadapter.install(cls.home, claude=WORK, codex=[review(said)] * 4)
        cls.stopped, cls.done, cls.notes, cls.states = {}, {}, {}, {}
        for name, rounds in (("green", 2), ("red", 1)):
            arm.write_text(name)
            task = taskfile.write(cls.home, cls.rig.path, f"Add {name}",
                                  front={"rounds": rounds}, done_when=(f"test -f {name}.txt",))
            first = cls.home.ak("run", str(task), env=OWNERS, timeout=300)
            run_dir = next(path for path in taskfile.runs(cls.home)
                           if path.name.endswith(f"-add-{name}"))
            cls.stopped[name] = (first, json.loads((run_dir / "run.json").read_text()))
            cls.done[name] = cls.home.ak("run", "resume", run_dir.name, env=OWNERS, timeout=300)
            cls.notes[name] = said.since()
            cls.states[name] = (run_dir, json.loads((run_dir / "run.json").read_text()))

    def checks(self, run_dir, kind):
        with contextlib.closing(sqlite3.connect(self.home.path / ".agentkit/history.db")) as db:
            return db.execute(
                "SELECT exit FROM checks WHERE run_id=? AND kind=? ORDER BY rowid",
                (run_dir.name, kind)).fetchall()

    def test_stopped_after_green_chosen_tests_resumes_without_running_them_again(self):
        first, before = self.stopped["green"]
        self.assertEqual(first.code, 1, first.out + first.err)
        self.assertEqual((before.get("verdict"), before["round_summaries"]), (None, []))
        done, (run_dir, state) = self.done["green"], self.states["green"]
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertEqual((state["state"], state["merged"]), ("pass", True))
        self.assertEqual([s["verdict"] for s in state["round_summaries"]], ["PASS"])
        self.assertEqual(self.notes["green"], ["review", CHOSEN, "review", "suite whole"])
        self.assertEqual(self.checks(run_dir, "chosen"), [(0,)])
        self.assertNotIn("$ python3 suite.py", (run_dir / "round-1/donewhen.log").read_text())
        self.assertIn("not running again", (run_dir / "log.txt").read_text())

    def test_stopped_after_red_chosen_tests_runs_them_again_on_resume(self):
        first, before = self.stopped["red"]
        self.assertEqual(first.code, 1, first.out + first.err)
        self.assertEqual((before.get("verdict"), before["round_summaries"]), (None, []))
        done, (run_dir, state) = self.done["red"], self.states["red"]
        self.assertEqual(done.code, 1, done.out + done.err)
        self.assertEqual((state["state"], state["merged"]), ("fail", False))
        self.assertEqual([s["verdict"] for s in state["round_summaries"]], ["FAIL"])
        self.assertEqual(self.notes["red"],
                         ["review", CHOSEN, CHOSEN, "review", CHOSEN, CHOSEN])
        self.assertEqual(self.checks(run_dir, "chosen"), [(1,), (1,), (1,), (1,)])


if __name__ == "__main__":
    unittest.main()
