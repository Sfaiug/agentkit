"""A follow-up a later round hands in again at a site an earlier round's names starts one fix run.

A later round's reviewer re-finds on the new head the defect an earlier round already handed in
as a follow-up, words it its own way, and often writes the check again.  It is the same defect:
a follow-up is one by its site, the `path:line` its fix run goes by, so the run keeps the first
round's alone, and its merge starts one fix run for it, not two racing to land at one site.
Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, from a
seat of akseat.py with executors, against the origin of gitrig.py and the GitHub of fakegh.py,
with scripted harnesses from fakeadapter.py; this test fails against `/bin/false`.
"""

import json
import os
import re
import shlex
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import PLAN_LINE, Seat
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

CHECK = "test -f sturdy.txt"
OUTCOME = "Fix retry.txt:1 - flimsy widget - it breaks later"
WORK = {"write": {"retry.txt": "hello\n", "words.txt": "first\n"},
        "commit": "add retry.txt and words.txt", "final": "## Summary\nwrote both",
        "hand_in": [["done"]]}
# passes on base, which has no words.txt, and fails on the change: a finding the fixer answers
FINDING = "! grep -qx first words.txt"
FIRST = {"final": "One finding, one defect beyond the task.", "hand_in": [
    ["finding", "words.txt:1", "the first word is lower case", "it opens the file",
     "--run", FINDING],
    ["follow-up", "retry.txt:1", "flimsy widget", "it breaks later", "--run", CHECK],
    ["done"]]}
FIX = {"write": {"words.txt": "First\n"}, "commit": "capitalise the first word",
       "final": "## Summary\ncapitalised it", "hand_in": [["done"]]}
# the same site again, in other words and with another failing check
AGAIN = {"final": "The widget is still weak.", "hand_in": [
    ["follow-up", "retry.txt:1", "the widget cracks", "it snaps under load",
     "--run", "test -f strong.txt"],
    ["done"]]}


def wait_for(read, bound=60):
    """`read()` once it is true, or the last thing it said after `bound` seconds."""
    deadline = time.monotonic() + bound
    while not (seen := read()) and time.monotonic() < deadline:
        time.sleep(0.1)
    return seen


def alive(pid):
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, TypeError):
        return False
    except PermissionError:
        pass
    return True


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ASiteHandedInAgain(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        rig = Rig(cls.home, "widgets")
        GitHub(cls.home).grant(rig.slug, "WRITE")
        akconfig.write(cls.home, ["opus", "astra"])
        Seat(cls.home, "acme", cwd=rig.path, record={"reviewers": ["astra"]}, planned=True)
        cls.release = cls.home.root / "adapters" / "release"
        # a fix run's turn waits for the test, so every one started is still on its way when read
        wait = (f"i=0; while [ ! -f {shlex.quote(str(cls.release))} ] && [ $i -lt 1000 ]; "
                "do sleep 0.1; i=$((i+1)); done")
        fakeadapter.install(cls.home, claude=[WORK, FIX, {"sh": wait, **fakeadapter.PASS}],
                            codex=[FIRST, AGAIN, "pass"])
        task = taskfile.write(cls.home, rig.path, "Add retry file")
        cls.done = cls.home.ak("run", str(task), env={"AGENTKIT_SESSION": "acme"}, timeout=300)
        cls.parent_dir, *cls.fixes = taskfile.runs(cls.home)
        cls.addClassCleanup(cls.settle)
        cls.parent = json.loads((cls.parent_dir / "run.json").read_text())
        plan = (cls.home.path / ".agentkit/state/plan-acme.md").read_text()
        cls.plan = [line for line in plan.replace(PLAN_LINE + "\n", "", 1).splitlines() if line]

    @classmethod
    def settle(cls):
        # A fix run still going would outlive this Home, so each ends before the Home goes.
        cls.release.write_text("")
        for fix in cls.fixes:
            state = lambda: json.loads((fix / "run.json").read_text())
            if not wait_for(lambda: not alive(state().get("pid"))):
                cls.home.ak("run", "stop", fix.name)

    def test_the_run_merges_after_two_rounds(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual((self.parent["state"], self.parent["merged"]), ("pass", True))
        self.assertEqual([summary["verdict"] for summary in self.parent["round_summaries"]],
                         ["FAIL", "PASS"])

    def test_run_json_and_result_md_list_one_follow_up_at_the_site(self):
        followups = self.parent["followups"]
        self.assertEqual([item.splitlines()[:2] for item in followups],
                         [[OUTCOME.removeprefix("Fix "), f"$ {CHECK}"]])
        result = (self.parent_dir / "result.md").read_text().splitlines()
        listed = result[result.index("## Follow-ups") + 1:]
        listed = listed[:next((i for i, line in enumerate(listed) if line.startswith("#")),
                              len(listed))]
        self.assertEqual([line for line in listed if line.startswith("- ")],
                         ["- " + OUTCOME.removeprefix("Fix ")])

    def test_the_seat_s_plan_gets_one_line_for_it(self):
        self.assertEqual(len(self.plan), 1, self.plan)
        self.assertRegex(self.plan[0], r"^- \[ \] " + re.escape(OUTCOME) + r" · check: `"
                         + re.escape(CHECK) + "` · ")

    def test_one_fix_run_starts(self):
        self.assertEqual(len(self.fixes), 1, self.fixes)
        task = (self.fixes[0] / "task.md").read_text()
        self.assertIn(f"## Done when\n```bash\n{CHECK}\n```", task)
        self.assertEqual(self.parent.get("followup_runs"), [self.fixes[0].name])


if __name__ == "__main__":
    unittest.main()
