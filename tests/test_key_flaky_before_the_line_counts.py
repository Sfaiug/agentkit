"""A test seen to fail, then pass, in a run's check before it joins the landing line counts as
one the line's own check sees: two trees, whichever check saw each, get one repair run of the
target naming it, owned by the run whose check saw the second; one tree gets none.
Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, from a
seat's record and plan, against the origin of gitrig.py and the GitHub of fakegh.py, with scripted
harnesses from fakeadapter.py, whose turns after the runs' own hand in blocked: the repair
ends where it starts.
"""

import json
from pathlib import Path
import sys
import threading
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.akseat import PLAN_LINE
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

# Fails on its first run on each tree, as the suite marks in the project's Git storage.
FLAKY = ('mark="$(git rev-parse --git-common-dir)/ran-$(git rev-parse HEAD^{tree})"\n'
         '[ -f "$mark" ] || { : >"$mark"; exit 1; }\n')
# Runs a failed test again and names it in `AK_FLAKY` when it passes; with hold.sh's first
# run it waits for the test to say `go` there.
SUITE = ('sh hold.sh; for t in t/*; do sh $t || { sh $t && echo $t >>"$AK_FLAKY"; } || exit 1; '
         'done')
HELD = ('own="$(git rev-parse --git-common-dir)"\n[ -f "$own/held" ] && exit 0\n: >"$own/held"\n'
        'i=0; while [ ! -f "$own/go" ] && [ $i -lt 1200 ]; do sleep 0.1; i=$((i+1)); done\n')


def work(name):
    return {"write": {f"{name}.txt": f"{name}\n"}, "commit": f"add {name}.txt",
            "final": f"## Summary\nwrote {name}.txt", "hand_in": [["done"]]}


class FlakyBeforeTheLineCounts(unittest.TestCase):
    def stage(self, hold, *names):
        """A seat's project whose suite has a flaky test, `hold` its hold.sh, and a harness
        writing `<name>.txt` in each of the runs `names`."""
        self.home = Home()
        self.addCleanup(self.home.close)
        self.rig = Rig(self.home, "acme", files={
            "AGENTS.md": f"---\ntests: {SUITE}\n---\n# acme\n", "hold.sh": hold,
            "t/flaky.sh": FLAKY, "t/fine.sh": "true\n"})
        GitHub(self.home).grant(self.rig.slug, "WRITE")
        akconfig.write(self.home, ["opus", "astra"])
        self.home.write(".agentkit/state/session-seat.json",
                        {"orchestrator": "opus", "workers": ["opus"], "reviewers": ["astra"]})
        self.home.write(".agentkit/state/plan-seat.md", PLAN_LINE + "\n")
        fakeadapter.install(self.home, claude=[*map(work, names), "blocked"],
                            codex=["pass"] * len(names) + ["blocked"])

    def run_one(self, name):
        """Run a task to its end from the seat; its run's directory."""
        task = taskfile.write(self.home, self.rig.path, f"Add {name}", name=name,
                              done_when=(f"test -f {name}.txt",))
        done = self.home.ak("run", str(task), env={"AGENTKIT_SESSION": "seat"}, timeout=300)
        self.assertEqual(done.code, 0, done.out + done.err)
        run, = (path for path in taskfile.runs(self.home) if path.name.endswith(f"-add-{name}"))
        self.assertTrue(json.loads((run / "run.json").read_text()).get("merged"), done.out)
        return run

    def repairs(self, *runs):
        """The repair runs: every run but `runs`, each record."""
        return [json.loads((path / "run.json").read_text())
                for path in taskfile.runs(self.home) if path not in runs]

    def assert_one_repair(self, owner, *runs):
        repair, = self.repairs(*runs)
        self.assertEqual(repair["followup"]["run"], owner.name)
        self.assertEqual({key: repair["repair"].get(key) for key in ("target", "command")},
                         {"target": "main", "command": "t/flaky.sh"})

    def test_two_runs_checks_before_the_line_start_one_repair_owned_by_the_second(self):
        self.stage("", "alpha", "beta")
        first = self.run_one("alpha")
        self.assertEqual(self.repairs(first), [])   # one tree only starts none
        second = self.run_one("beta")
        self.assert_one_repair(second, first, second)

    def test_a_check_before_the_line_and_the_lines_own_start_one_repair(self):
        self.stage(HELD, "alpha")
        own = self.rig.path / ".git"
        ran = []
        runner = threading.Thread(target=lambda: ran.append(self.run_one("alpha")))
        runner.start()
        deadline = time.monotonic() + 240
        while not (own / "held").exists() and time.monotonic() < deadline:
            time.sleep(0.2)
        self.assertTrue((own / "held").exists(), "the check before the line never ran")
        # the target moves past the tree the run checks, so the line checks it again itself
        self.rig.commit({"notes.txt": "moved\n"}, "move the target")
        (own / "go").touch()
        runner.join()
        self.assert_one_repair(ran[0], ran[0])


if __name__ == "__main__":
    unittest.main()
