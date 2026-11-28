"""A rebased change of looks alone keeps its place in the lane.

Where a reviewer's PASS ran its chosen tests green, the review's record carries that fact across a
clean rebase (`integrate`: "done-when passed again, review kept") so `land` counts the rebased
commit as of looks alone even though `history.checks` recorded its `chosen` go under the old
commit.  In a project where a landing on record was red on a test, a reviewed change of prose
alone whose target moves after its PASS and green chosen tests — so ak rebases it to a new commit
and keeps the review — lands with no whole suite started, its merge ending with
`Looks-Alone-Tree: <tree>`.  The same rebased change in a project where its review chooses no test
lands only through the whole suite, its merge ending with `Suite-Passed-Tree: <tree>`.

Black-box, on the fixtures of
tests/test_key_the_looks_lane_takes_only_a_change_whose_chosen_tests_passed.py: `AK_BIN` runs the
task scripted by fakeadapter.py, merged by fakegh.py's GitHub under injected host readings
(AK_HOST_READINGS); a one-shot `git` wrapper pauses integration's `fetch` once `run.json` records
`PASS` so the test advances `origin/main` on an unrelated file after the green review is on disk.
"""

import json
import os
from pathlib import Path
import shlex
import shutil
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import SYSTEM
from fixtures.fakegh import GitHub
import test_key_a_change_of_looks_alone_lands_on_its_quick_checks as quick
import test_key_the_looks_lane_takes_only_a_change_whose_chosen_tests_passed as looks

REAL_GIT = shutil.which("git", path=os.pathsep.join(SYSTEM))
PAUSE_FETCH = """#!/bin/sh
if [ -f {arm} ]; then
  case " $* " in
    *" fetch "*)
      for r in {runs}/*/run.json; do
        if [ -f "$r" ] && grep -q '"verdict": "PASS"' "$r"; then
          rm -f {arm}
          touch {ready}
          until [ -f {go} ]; do sleep 0.1; done
          break
        fi
      done ;;
  esac
fi
exec {git} "$@"
"""


class ARebasedChangeOfLooksAloneKeepsItsPlaceInTheLane(unittest.TestCase):
    line = vars(quick.AChangeOfLooksAloneLandsOnItsQuickChecks)["line"]

    def deliver(self, line, readings, *, chosen):
        """Deliver a prose change whose target moves after its PASS is recorded so ak rebases it
        and keeps its review: the target's tree and merge message."""
        home = line.home
        home.env["AK_HOST_READINGS"] = json.dumps(readings)
        GitHub(home).grant(line.rig.slug, "WRITE")
        akconfig.write(home, ["opus", "astra"], workers=["opus"], reviewers=["astra"])
        arm, ready, go = (home.root / name for name in ("arm", "ready", "go"))
        arm.touch()
        home.fake("git", PAUSE_FETCH.format(
            arm=shlex.quote(str(arm)), ready=shlex.quote(str(ready)), go=shlex.quote(str(go)),
            runs=shlex.quote(str(home.path / ".agentkit/runs")), git=shlex.quote(REAL_GIT)))
        fakes = fakeadapter.install(
            home, claude={**fakeadapter.WORK, "write": {"news.md": looks.NEWS},
                          "commit": "trim the news"}, codex="pass")
        proc = home.spawn("run", str(taskfile.write(home, line.rig.path, "Trim the news",
                                                    done_when=("test -s news.md",))))
        deadline = time.monotonic() + 300
        while not ready.exists():
            self.assertIsNone(proc.poll(), home.log("spawn-1.err").read_text())
            self.assertLess(time.monotonic(), deadline, "integration fetch never started")
            time.sleep(0.1)
        run_dir, = (path for path in taskfile.runs(home) if path.name.endswith("-trim-the-news"))
        before = quick.record(run_dir)
        self.assertEqual((before["review"]["verdict"], fakes["codex"].n), ("PASS", 1))
        self.assertEqual(line.runs(), [("alone", "")] if chosen else [])
        passed_head = before["review"]["head_sha"]
        line.rig.commit({"other.txt": "moved\n"}, "move target")
        go.touch()
        self.assertEqual(proc.wait(timeout=300), 0,
                         home.log("spawn-1.out").read_text() + home.log("spawn-1.err").read_text())
        state = quick.record(run_dir)
        self.assertTrue(state.get("merged"), state)
        self.assertEqual(fakes["codex"].n, 1)
        self.assertEqual(state["review"]["passed_head_sha"], passed_head)
        self.assertNotEqual(state["review"]["head_sha"], passed_head)
        tree = line.rig.origin("rev-parse", "main^{tree}")
        return tree, line.rig.origin("log", "-1", "--format=%B", "main").rstrip()

    def test_a_rebased_change_whose_chosen_tests_passed_lands_with_no_whole_suite(self):
        line = self.line(**{"news.md": looks.NEWS + "More news.\n"})
        quick.red(line)
        tree, message = self.deliver(line, quick.BUSY, chosen=True)
        self.assertEqual(line.runs(), [("alone", "")])
        self.assertTrue(message.endswith(f"\n\nLooks-Alone-Tree: {tree}"), message)

    def test_where_nothing_is_chosen_a_rebased_change_lands_only_through_the_whole_suite(self):
        line = self.line(**{"news.md": looks.NEWS + "More news.\n"})
        tree, message = self.deliver(line, quick.IDLE, chosen=False)
        self.assertEqual(line.whole(), 1, line.runs())
        self.assertNotIn(("alone", ""), line.runs())
        self.assertTrue(message.endswith(f"\n\nSuite-Passed-Tree: {tree}"), message)


if __name__ == "__main__":
    unittest.main()
