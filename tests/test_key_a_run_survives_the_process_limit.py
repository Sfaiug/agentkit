"""A run that cannot start a thread or process leaves its loop to the tick, instead of ending in error.

On 30 Oct 2026 ak's slice reached its task limit for about a minute, and 44 runs ended in `error`
on `RuntimeError("can't start new thread")` or `BlockingIOError(11, ...)`; resumed by hand, each
carried on as if nothing had happened.  So a run's process that hits either where it would end
in `error` ends there, its record reading as a loop that died, and the tick carries it on as it
carries on any; a run stopped meanwhile stays stopped.
Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, on a
project from gitrig.py with scripted harnesses from fakeadapter.py.  The executor's turn asks for
its run's process limit to go, and the test takes it with `prlimit --pid` (the turn's box hides
the run's pid from the turn); each tick runs in the box `home.tick()` builds.
"""

import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home, boxable
from fixtures.gitrig import Rig

STARVED = r"""(BlockingIOError\(11, 'Resource temporarily unavailable'\)|""" \
          r"""RuntimeError\("can't start new thread"\))"""
OFFLINE = "http://127.0.0.1:9"    # a refused port: the tick's public-board reads stay on loopback


def prlimit_bites():
    """Whether `prlimit --pid` takes the room for a thread from another process here: a child
    lowered to one task of its user's must then fail to start one."""
    if not shutil.which("prlimit"):
        return False
    child = subprocess.Popen([sys.executable, "-c", "import sys, threading\nsys.stdin.read()\n"
                              "threading.Thread(target=int).start()"],
                             stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
    lowered = subprocess.run(["prlimit", "--pid", str(child.pid), "--nproc=1:"],
                             capture_output=True).returncode == 0
    child.communicate(b"")
    return lowered and child.returncode != 0


def gone(pid):
    """Whether that process has ended, collected or not."""
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0] in "ZX"
    except OSError:
        return True


@unittest.skipUnless(prlimit_bites(), "prlimit cannot lower another process's task limit here")
@unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
class Starved(unittest.TestCase):
    """A `--bg` run whose executor's turn ends with no room left for its process to start a
    thread or a process; `states` are those its record went through, `ended` its record once
    that process is gone."""

    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        home.env.update(https_proxy=OFFLINE, HTTPS_PROXY=OFFLINE, no_proxy="127.0.0.1,localhost")
        rig = Rig(home, "widgets")
        akconfig.write(home, ["opus", "astra"])
        adapters = home.root / "adapters"
        ask, taken = adapters / "ask", adapters / "taken"
        starve = {**fakeadapter.WORK,
                  "sh": f"touch '{ask}'; while [ ! -f '{taken}' ]; do sleep 0.1; done"}
        cls.fakes = fakeadapter.install(home, claude=starve, codex="pass")
        launched = home.ak("run", str(taskfile.write(home, rig.path)), "--no-merge", "--bg")
        assert launched.code == 0, launched.out + launched.err
        cls.run_dir = taskfile.only_run(home)
        cls.states = []
        cls.watch(ask.exists, "the executor's turn asked for the limit")
        cls.pid = cls.record()["pid"]
        subprocess.run(["prlimit", "--pid", str(cls.pid), "--nproc=1:"], check=True)
        taken.touch()
        cls.watch(lambda: gone(cls.pid), "the run's process ending")
        cls.ended = cls.record()

    @classmethod
    def record(cls):
        try:
            return json.loads((cls.run_dir / "run.json").read_text())
        except (OSError, ValueError):
            return {}

    @classmethod
    def log(cls):
        return (cls.run_dir / "log.txt").read_text()

    @classmethod
    def watch(cls, test, what, bound=60, tick=False):
        """Every state the run's record says, until `test` holds; with `tick`, a tick runs
        every few seconds meanwhile."""
        deadline = time.monotonic() + bound
        ticked = 0
        while True:
            state = cls.record().get("state")
            if state and state != (cls.states or [None])[-1]:
                cls.states.append(state)
            if test():
                return
            if time.monotonic() > deadline:
                raise AssertionError(f"never: {what}; states {cls.states}\n{cls.log()}")
            if tick and time.monotonic() > ticked + 5:
                done = cls.home.tick()
                assert done.code == 0, done.out + done.err
                ticked = time.monotonic()
            time.sleep(0.05)


class TheTickCarriesItOn(Starved):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.watch(lambda: cls.states[-1] not in ("queued", "running"), "the run's end", 180,
                  tick=True)
        cls.end = cls.record()

    def test_the_process_ends_with_no_error_and_the_ticks_end_the_run_pass(self):
        self.assertEqual(self.ended.get("state"), "running", self.log())
        self.assertEqual((self.end.get("state"), self.end.get("verdict")), ("pass", "PASS"),
                         self.log())
        self.assertNotIn("error", self.states)

    def test_it_goes_on_in_the_round_where_it_stopped(self):
        self.assertEqual(self.end.get("worktree"), self.ended.get("worktree"))
        self.assertEqual([run["role"] for run in self.fakes["claude"].runs()], ["executor"])
        self.assertEqual([run["role"] for run in self.fakes["codex"].runs()], ["reviewer"])

    def test_its_log_names_the_failure_and_the_tick_s_resume(self):
        name = re.escape(self.run_dir.name)
        said = [STARVED + ": no room to start a thread or process; the tick carries the run on\n",
                rf"resumed {name}: loop died", rf"\] resume {name}: "]
        self.assertRegex(self.log(), "(?s)" + ".*".join(said))


class AStopStands(Starved):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.stopped = cls.home.ak("run", "stop", cls.run_dir.name)
        cls.ticks = [cls.home.tick() for _ in range(2)]

    def test_a_stop_after_the_process_ended_stays_whatever_ticks_follow(self):
        self.assertEqual(self.stopped.code, 0, self.stopped.out + self.stopped.err)
        self.assertEqual([tick.code for tick in self.ticks], [0, 0],
                         [tick.err for tick in self.ticks])
        self.assertEqual(self.record().get("state"), "stopped", self.log())
        self.assertEqual(self.fakes["codex"].n, 0)


if __name__ == "__main__":
    unittest.main()
