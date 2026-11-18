"""A spare removed from the config leaves a spent run waiting for the window of the one left.

The run launches with opus and fable as its workers; opus spends its week and the run waits
`exhausted`, and then fable's entry leaves the config.  `ak run resume` parks the run again on
opus's spent week instead of stopping on `unknown model 'fable'`, and `ak run status` says the
run waits for anthropic until the hour opus's week resets, not for a window with no hour.  A
worker the config dropped but the run's launch recorded, its provider still there, is one the
resume still runs (`config.as_launched`), so the status waits on its window too.

Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, on a
run record written by hand where ak keeps it, gitrig.py's checkout and fakeadapter.py's
harnesses, whose meters the test sets.
"""

import json
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.gitrig import Rig

RUN = "20261118-0700-add-retry-file"


class ARetiredSpareLeavesARunWaitingForTheOneLeft(unittest.TestCase):
    def waits(self, cfg, **record):
        """`ak run resume`, then `ak run status`, on an exhausted run whose executor opus is
        spent, under a config of `cfg`'s models with astra reviewing."""
        home = Home()
        self.addCleanup(home.close)
        rig = Rig(home, "widgets")
        akconfig.write(home, cfg, workers=cfg[:1], reviewers=["astra"])
        fakes = fakeadapter.install(home, claude="work", codex="pass")
        now = time.time()
        resets = int(now) + 3 * 3600
        week = {"name": "week", "window_secs": 604800, "resets_at": resets}
        for harness, used in (("claude", 100), ("codex", 10)):
            fakes[harness].answer("usage", json.dumps({"meters": [{**week, "used": used}],
                                                       "error": None}))
        run_dir = home.path / ".agentkit" / "runs" / RUN
        run_dir.mkdir(parents=True)
        (run_dir / "task.md").write_text(taskfile.write(home, rig.path).read_text())
        path = home.write(f".agentkit/runs/{RUN}/run.json", {
            "run_id": RUN, "title": "Add retry file", "state": "exhausted", "quota_dry": True,
            "step": "executor", "executor": "opus", "reviewer": "astra",
            "reviewers": ["astra"], "rounds": 2,
            "repo": str(rig.path), "worktree": str(rig.path), "branch": "main",
            "base": "origin/main", "base_sha": rig.head(), "started_at": now - 3600, **record})

        done = home.ak("run", "resume", RUN)
        state = json.loads(path.read_text())
        self.assertEqual((done.code, state["state"], state["executor"]), (1, "exhausted", "opus"),
                         done.out + done.err)
        self.assertIn("week", state.get("error", ""), done.out + done.err)
        self.assertEqual([fake.n for fake in fakes.values()], [0, 0])

        shown = home.ak("run", "status", "--plain")
        self.assertEqual(shown.code, 0, shown.err)
        (row,) = [line for line in shown.out.splitlines() if line.startswith(RUN)]
        self.assertIn(f"waiting for anthropic until {time.strftime('%H:%M', time.gmtime(resets))}",
                      row)

    def test_the_run_waits_for_the_spent_worker_s_reset(self):
        self.waits(["opus", "astra"], workers=["opus", "fable"])

    def test_a_worker_the_launch_recorded_is_waited_for(self):
        self.waits(["fable", "astra"], workers=["opus"],
                   models={"opus": akconfig.SHIPPED["opus"]})


if __name__ == "__main__":
    unittest.main()
