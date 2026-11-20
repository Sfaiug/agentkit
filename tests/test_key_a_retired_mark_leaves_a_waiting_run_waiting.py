"""A queued run whose saved marks hold a model the config dropped waits for a window.

A run keeps the role lists it was launched with while the config moves on: a spare retired
since is still in them.  The pick passes over it, and so does the question a launch asks before
it waits, whether the run's lists could ever run here.  Started while every window is spent,
such a run waits for one, exit 1, instead of ending in error on a name the config no longer
has.  Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py,
with harnesses from fakeadapter.py whose meters the test sets, on the bare origin of gitrig.py;
the run is a launch receipt as a queued launch leaves one, its launcher gone.
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

# ak asks the public boards and fetches the checkout it runs from: a test reaches neither.
OFFLINE = {"https_proxy": "http://127.0.0.1:9", "http_proxy": "http://127.0.0.1:9",
           "GIT_ALLOW_PROTOCOL": "file"}
SPENT = {"meters": [{"name": "weekly", "used": 100, "resets_at": int(time.time() + 86400),
                     "window_secs": 604800}], "error": None}


class RetiredMarkLeavesAWaitingRunWaiting(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        home.env.update(OFFLINE)
        rig = Rig(home, "widgets")
        akconfig.write(home, ["opus", "astra"], workers=["opus", "astra"], reviewers=["opus"])
        cls.fakes = fakeadapter.install(home, claude="work", codex="pass")
        for fake in cls.fakes.values():
            fake.answer("usage", json.dumps(SPENT))
        cls.run_dir = home.path / ".agentkit/runs/20261120-1200-add-retry-file"
        cls.run_dir.mkdir(parents=True)
        (cls.run_dir / "task.md").write_bytes(taskfile.write(home, rig.path).read_bytes())
        (cls.run_dir / "run.json").write_text(json.dumps({
            "run_id": cls.run_dir.name, "state": "queued", "slot_waiting": True,
            "repo": str(rig.path), "no_merge": True, "launched_session": None,
            "launch_opts": {"--no-merge": True},
            "workers": ["opus", "astra", "nova"], "reviewers": ["opus", "nova"]}))
        cls.done = home.ak("run", "resume", cls.run_dir.name, timeout=300)
        cls.state = json.loads((cls.run_dir / "run.json").read_text())

    def test_the_run_waits_for_a_window(self):
        self.assertEqual(self.done.code, 1, self.done.out + self.done.err)
        # parked on a spent window, which the tick resumes once it resets, not on a stop
        # nothing moves
        self.assertEqual((self.state["state"], self.state.get("quota_dry")), ("exhausted", True))
        self.assertEqual([run for fake in self.fakes.values() for run in fake.runs()], [])


if __name__ == "__main__":
    unittest.main()
