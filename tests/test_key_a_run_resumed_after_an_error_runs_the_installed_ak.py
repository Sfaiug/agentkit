"""A run resumed after an error runs the installed ak; a run parked for a person keeps its own.

A run that ended in error has no process left on its version: resumed by `ak run resume` or by
the tick's retry, it runs the installed ak and its record names that version as a new launch's
does, while the other version's `bin/ak` never runs.  A run parked for a person (`stalled`)
resumes on the version its record names, as today.  Black-box through `AK_BIN`.
"""

import json
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import REAL_TMUX, Home, rerun_boxed
from fixtures.akinstall import Install
from fixtures.akseat import Seat
from fixtures.gitrig import Rig

# Started by this test's own Python, keeping bin/ak as argv[0] for scripts and replacing the
# process for binaries, as test_key_run_keeps_its_version.py's wrapper does.
OTHER_AK = ("#!/bin/sh\n_=0#; exec '" + sys.executable.replace("'", "'\\''") + "' \"$0\" \"$@\"\n"
            ).replace("{", "{{").replace("}", "}}") + '''import os, sys
from pathlib import Path
Path({marker!r}).write_text("ran\\n")
program = Path(__file__).resolve().with_name("program")
with program.open("rb") as start:
    script = start.read(2) == b"#!"
if script:
    __file__ = str(program)
    exec(compile(program.read_bytes(), __file__, "exec"))
else:
    os.execv(program, sys.argv)
'''


def wait_for(read):
    until = time.monotonic() + 120
    while not (value := read()) and time.monotonic() < until:
        time.sleep(0.1)
    assert value, "the run did not finish"
    return value


def ended(directory):
    state = json.loads((directory / "run.json").read_text())
    if state.get("state") in ("pass", "fail", "error", "blocked", "exhausted"):
        return state


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ARunResumedAfterAnErrorRunsTheInstalledAk(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        home.env["AK_HOST_READINGS"] = json.dumps({"cpus": 4, "load": 0, "free_mb": 16000})
        cls.install = install = Install(home)
        cls.marker = home.root / "adapters/other-ran"
        cls.marker.parent.mkdir(parents=True, exist_ok=True)
        ak = install.seed / "bin/ak"
        ak.rename(ak.with_name("program"))
        ak.write_text(OTHER_AK.format(marker=str(cls.marker)))
        ak.chmod(0o755)
        cls.other_commit = install._push("other version writes a marker")
        cls.other = home.root / "other-ak"
        install._git(home.root, "clone", "-q", str(install.bare), str(cls.other))
        ak.with_name("program").replace(ak)
        cls.installed_commit = install._push("installed version")
        install.git("fetch", "-q", "origin")
        install.git("reset", "--hard", cls.installed_commit)
        akconfig.write(home, ["opus", "astra"])
        fakeadapter.install(home, claude="work", codex="pass")
        Seat(home, "acme")
        rig = Rig(home, "baseline")
        task = taskfile.write(home, rig.path, title="Baseline launch", name="baseline")
        done = home.run(install.ak, "run", str(task), "--no-merge", timeout=120)
        assert done.code == 0, done.out + done.err
        fresh = taskfile.only_run(home)
        cls.installed_checkout = json.loads((fresh / "run.json").read_text())["ak_checkout"]

    def setUp(self):
        self.marker.unlink(missing_ok=True)

    def make_run(self, run_id, *, state, ak_checkout, **extra):
        rig = Rig(self.home, run_id)
        wt = self.home.path / ".agentkit/wt" / run_id
        wt.parent.mkdir(parents=True, exist_ok=True)
        rig.git("worktree", "add", "-q", "-b", f"ak/{run_id}", str(wt), "main")
        task = taskfile.write(self.home, rig.path, title=f"Fix {run_id}", name=run_id)
        now = time.time()
        self.home.write(f".agentkit/runs/{run_id}/task.md", task.read_text())
        self.home.write(f".agentkit/runs/{run_id}/log.txt", "")
        self.home.write(f".agentkit/runs/{run_id}/run.json", {
            "run_id": run_id, "title": f"Fix {run_id}", "state": state,
            "verdict": "ERROR" if state == "error" else None,
            "error": "could not restore the checkout",
            "repo": str(rig.path), "worktree": str(wt), "branch": f"ak/{run_id}",
            "base": "origin/main", "target": "origin/main", "base_sha": rig.head("main"),
            "rounds": 2, "round_summaries": [], "executor": "opus", "reviewer": "astra",
            "no_merge": True, "silence_minutes": 20, "ceiling_hours": 6,
            "started_at": now - 120,
            "finished_at": now - 60 if state == "error" else None,
            "ak_checkout": str(ak_checkout), **extra})
        return self.home.path / ".agentkit/runs" / run_id

    def test_a_run_in_error_resumed_by_command_runs_the_installed_ak(self):
        directory = self.make_run("20261117-0100-err-cmd", state="error", ak_checkout=self.other)
        done = self.home.run(self.install.ak, "run", "resume", directory.name, timeout=120)
        self.assertEqual(done.code, 0, done.out + done.err)
        after = json.loads((directory / "run.json").read_text())
        self.assertEqual(after["state"], "pass", (directory / "log.txt").read_text())
        self.assertEqual(after["ak_checkout"], self.installed_checkout)
        self.assertFalse(self.marker.exists())

    def test_a_run_in_error_retried_by_the_tick_runs_the_installed_ak(self):
        pinned = Path(self.home.env["HOME"]) / ".agentkit/versions" / self.other_commit
        directory = self.make_run("20261117-0200-err-tick", state="error", ak_checkout=pinned,
                                  launched_session="acme", error_retries=0,
                                  error_retry_at=time.time() - 1)
        done = self.home.run(self.install.ak, "watch", timeout=300)
        self.assertEqual(done.code, 0, done.out + done.err)
        after = wait_for(lambda: ended(directory))
        detail = done.out + done.err + (directory / "log.txt").read_text() + json.dumps(after)
        self.assertEqual(after["state"], "pass", detail)
        self.assertEqual(after["ak_checkout"], self.installed_checkout)
        self.assertFalse(self.marker.exists())

    def test_a_run_parked_for_a_person_resumes_on_its_own_version(self):
        directory = self.make_run("20261117-0300-parked", state="stalled", ak_checkout=self.other,
                                  stalls=[{"step": "done-when"}])
        done = self.home.run(self.install.ak, "run", "resume", directory.name, timeout=120)
        self.assertEqual(done.code, 0, done.out + done.err)
        after = json.loads((directory / "run.json").read_text())
        self.assertEqual(after["state"], "pass", (directory / "log.txt").read_text())
        self.assertEqual(after["ak_checkout"], str(self.other))
        self.assertTrue(self.marker.exists())


if __name__ == "__main__":
    rerun_boxed()
    unittest.main()
