"""`ak run task.md --bg` returns at once with the run's id and result path; the run goes on.

An orchestrator starts many runs and must not sit in one: with --bg the command hands back as
soon as the run is launched, its last two lines the run's id and where its result will be, and
the run carries on detached, its own live process recorded in run.json, to the same end a
foreground run reaches.  Black-box: the program `AK_BIN` names runs from outside through
tests/fixtures/akbin.py, on a project from gitrig.py, with scripted harnesses from
fakeadapter.py whose executor holds its turn until the test lets it go.
"""

import json
import os
import shlex
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.gitrig import Rig


def alive(pid):
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, TypeError):
        return False
    except PermissionError:
        pass
    return True


def first_line(path):
    try:
        return path.read_text().split("\n", 1)[0]
    except FileNotFoundError:
        return ""


def wait_for(read, bound=120):
    """`read()` once it is true, or the last thing it said after `bound` seconds."""
    deadline = time.monotonic() + bound
    while not (seen := read()) and time.monotonic() < deadline:
        time.sleep(0.1)
    return seen


class BackgroundRun(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        rig = Rig(cls.home, "widgets")
        akconfig.write(cls.home, ["opus", "astra"])
        cls.release = cls.home.root / "adapters" / "release"
        # The executor's turn waits for the release (at most 100 s), then does the work.
        hold = {"sh": f"i=0; while [ ! -f {shlex.quote(str(cls.release))} ] && [ $i -lt 1000 ]"
                      "; do sleep 0.1; i=$((i+1)); done",
                **fakeadapter.WORK}
        cls.fakes = fakeadapter.install(cls.home, claude=[hold], codex="pass")
        task = taskfile.write(cls.home, rig.path, "Add retry file")
        cls.done = cls.home.ak("run", str(task), "--no-merge", "--bg", timeout=300)
        cls.run_dir = taskfile.only_run(cls.home)
        cls.addClassCleanup(cls.stop)
        cls.at_once = json.loads((cls.run_dir / "run.json").read_text())
        cls.held_turns = cls.fakes["claude"].runs()
        cls.alive_at_once = alive(cls.at_once.get("pid"))
        cls.turn_started = wait_for(lambda: cls.fakes["claude"].n == 1)
        cls.release.write_text("")
        cls.settled = wait_for(lambda: cls.state()["state"] != "running" and cls.state())

    @classmethod
    def state(cls):
        return json.loads((cls.run_dir / "run.json").read_text())

    @classmethod
    def stop(cls):
        # A run still going would outlive this Home, so it is stopped before the Home goes.
        cls.release.write_text("")
        if cls.state().get("state") in ("running", "queued"):
            cls.home.ak("run", "stop", cls.run_dir.name)

    def test_it_returns_at_once_with_the_run_id_and_result_path_last(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertRegex(self.run_dir.name, r"^\d{8}-\d{4}-add-retry-file$")
        self.assertEqual(self.done.out.rstrip("\n").splitlines()[-2:],
                         [self.run_dir.name, str(self.run_dir / "result.md")])
        # The executor's turn was still held when the command returned.
        self.assertEqual(self.held_turns, [])

    def test_the_run_is_recorded_running_in_a_live_process_of_its_own(self):
        self.assertEqual(self.at_once.get("state"), "running")
        self.assertIsInstance(self.at_once.get("pid"), int)
        # The command that launched it has exited, so a live pid is the detached run's.
        self.assertTrue(self.alive_at_once, self.at_once)

    def test_the_detached_run_goes_on_to_pass(self):
        self.assertTrue(self.turn_started, "the executor's turn never started")
        self.assertTrue(self.settled, "the run was still running")
        self.assertEqual((self.settled["state"], self.settled["verdict"]), ("pass", "PASS"))
        self.assertEqual((self.fakes["claude"].n, self.fakes["codex"].n), (1, 1))
        result = self.run_dir / "result.md"
        # run.json may say pass a moment before result.md is written.
        first = wait_for(lambda: first_line(result).startswith("# PASS") and first_line(result))
        self.assertEqual(first, "# PASS, not merged: --no-merge — Add retry file")
        worktree = Path(self.settled["worktree"])
        tree = self.home.run("git", "-C", str(worktree), "ls-tree", "--name-only", "HEAD")
        self.assertIn("retry.txt", tree.out.split())


if __name__ == "__main__":
    unittest.main()
