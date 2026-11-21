"""A resume started as a task's run ends for rescoping is refused as one started after.

A resume started while the run's first review still goes, its record naming an older ak, and
stopped until the run has ended on six findings is refused with the rescope sentence, the older
ak never running and no second round recorded: stopped as ak picks the version to run it on, at
its box check, or as it asks whether the run's loop lives.  Python's ak alone: the resume stops
itself at a named Python call (`STOP`), so this is no key a native ak passes.
"""

import json
import shlex
import signal
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig
from test_key_many_findings_end_a_run_for_rescoping import FIX, WORK, older, review, rounds

# What a resume's Python loads first: it stops itself at the call STOP_AT names, as a debugger would.
STOP = """import os, signal, sys
STOP_AT = tuple(os.environ["STOP_AT"].split())
def stop(frame, event, _arg):
    if (frame.f_globals.get("__name__"), frame.f_code.co_name, event,
            frame.f_back and frame.f_back.f_code.co_name) == STOP_AT:
        sys.setprofile(None)
        os.kill(os.getpid(), signal.SIGSTOP)
sys.setprofile(stop)
"""


class AResumeAsItsRunEndsForRescoping(unittest.TestCase):

    def test_it_is_refused(self):
        for at in ("agentkit.record read_state return dispatch", "agentkit.box check call resume_run",
                   "agentkit.record process_active call resume_run"):
            with self.subTest(at=at):
                self.stopped_at(at)

    def stopped_at(self, at):
        home = Home()
        self.addCleanup(home.close)
        rig = Rig(home, "widgets")
        GitHub(home).grant(rig.slug, "WRITE")
        akconfig.write(home, ["opus", "astra"], workers=["opus"], reviewers=["astra"])
        fakes = fakeadapter.install(home, claude=[WORK, FIX], codex="pass")
        reviewing, release = (fakes["codex"].dir / name for name in ("reviewing", "release"))
        fakes["codex"].behave({**review(6), "sh": f"touch {shlex.quote(str(reviewing))}; until [ -f "
                               f"{shlex.quote(str(release))} ]; do sleep .05; done"}, "pass")
        launch = home.spawn("run", str(taskfile.write(home, rig.path, "Add retry file")), "--no-merge")
        until(reviewing.exists)
        run_dir = taskfile.only_run(home)
        ran = older(home)
        record = {**json.loads((run_dir / "run.json").read_text()), "ak_checkout": str(ran.parent)}
        home.write(run_dir / "run.next", record).replace(run_dir / "run.json")
        hook = home.write("stop/sitecustomize.py", STOP)
        resume = home.spawn("run", "resume", run_dir.name, "--rounds", "3",
                            env={"PYTHONPATH": str(hook.parent), "STOP_AT": at})
        try:
            until(lambda: resume.poll() is not None
                  or ") T " in Path(f"/proc/{resume.pid}/stat").read_text())
        finally:
            release.touch()
        self.assertEqual(launch.wait(timeout=300), 1)
        resume.send_signal(signal.SIGCONT)
        self.assertEqual(resume.wait(timeout=300), 2, home.log("spawn-2.err").read_text())
        self.assertIn("rescope_findings = 6: rescope the task.", home.log("spawn-2.err").read_text())
        self.assertFalse(ran.exists())
        state = json.loads((run_dir / "run.json").read_text())
        self.assertEqual((state["state"], rounds(state)), ("fail", [(1, "FAIL", 6)]))


def until(check):
    deadline = time.monotonic() + 300
    while not check():
        assert time.monotonic() < deadline, "never came"
        time.sleep(0.05)


if __name__ == "__main__":
    unittest.main()
