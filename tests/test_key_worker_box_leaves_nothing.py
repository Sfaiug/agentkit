"""When an `ak worker` turn ends, nothing it started is left running, and ak says what it stopped.

A turn runs a model's commands, and a command may detach a child: a server, a watcher, a shell
in a session of its own, or one started with an empty environment.  However it left, the turn's
end stops it, and ak's stderr names each one it stopped.  A turn that ignores TERM is still
ended, and an interrupted `ak worker` first gives the harness TERM to save its session, then
ends the rest.  Black-box: the program `AK_BIN` names runs from outside through
tests/fixtures/akbin.py, with a scripted harness from fakeadapter.py whose turn starts holders
(below); a holder holds a lock while it runs, so a free lock is a holder gone.
"""

import fcntl
import shlex
import signal
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import boxable, Home

# Started in the workspace as `holder.py NAME [saves]`: it locks NAME.lock, with `saves` makes
# TERM write NAME.saved and end it, as a harness saves its session, then writes its pid in
# NAME.pid and sleeps.
HOLDER = """import fcntl, os, signal, sys, time
from pathlib import Path
name = sys.argv[1]
lock = open(f"{name}.lock", "a")
fcntl.flock(lock, fcntl.LOCK_EX)
if sys.argv[2:] == ["saves"]:
    def save(*_):
        Path(f"{name}.saved").write_text("session saved")
        sys.exit(0)
    signal.signal(signal.SIGTERM, save)
Path(f"{name}.part").write_text(str(os.getpid()))
Path(f"{name}.part").rename(f"{name}.pid")
time.sleep(600)
"""


@unittest.skipUnless(boxable(), "no bwrap able to box a turn here")
class WorkerBoxLeavesNothing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        akconfig.write(cls.home, {"beta": {"harness": "acme", "model": "beta-1",
                                           "effort": "low"}})
        cls.fake = fakeadapter.install(cls.home, acme="pass")["acme"]
        # The adapter ignores TERM, as one waiting on its harness does: what TERM does to a
        # turn is then the harness's own, and so is what ignores it.
        script = cls.fake.script.read_text()
        cls.fake.script.write_text(script.replace("\nexec ", "\ntrap '' TERM\nexec ", 1))
        cls.holder = cls.fake.dir / "holder.py"
        cls.holder.write_text(HOLDER)
        cls.task = cls.home.write("fix-api.md", "Fix the parser.\n")

    def setUp(self):
        self.ws = self.home.path / "code" / self.id().rsplit(".", 1)[1]
        self.ws.mkdir(parents=True)

    def start(self, name, *mode):
        """The words starting a holder, as the turn's shell runs them."""
        return shlex.join([sys.executable, str(self.holder), name, *mode])

    def step(self, sh):
        self.fake.behave({**fakeadapter.PASS, "sh": sh})

    def held(self, name):
        with (self.ws / f"{name}.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
        return False

    def interrupted(self, *names):
        """Start `ak worker`, wait until each holder named runs, ^C it; how it ended."""
        proc = self.home.spawn("worker", "beta", str(self.task), "--workspace", str(self.ws),
                               "--out", str(self.ws / "out"))
        deadline = time.monotonic() + 60
        while not all((self.ws / f"{name}.pid").exists() for name in names):
            self.assertIsNone(proc.poll(), "ak worker ended before its turn started")
            self.assertLess(time.monotonic(), deadline, "the turn never started its holders")
            time.sleep(0.05)
        proc.send_signal(signal.SIGINT)
        return proc.wait(timeout=60)

    def test_a_detached_child_unmarked_or_in_its_own_session_is_stopped_and_named(self):
        self.step(f"env -i {self.start('unmarked')} & setsid {self.start('session')} & "
                  "until [ -s unmarked.pid ] && [ -s session.pid ]; do sleep 0.05; done")
        done = self.home.ak("worker", "beta", str(self.task), "--workspace", str(self.ws),
                            "--out", str(self.ws / "out"))
        self.assertEqual(done.code, 0, done.err)
        for name in ("unmarked", "session"):
            with self.subTest(name):
                self.assertFalse(self.held(name), f"{name} still runs")
                pid = (self.ws / f"{name}.pid").read_text()
                self.assertIn(f"executor beta left process {pid}: {self.start(name)}; "
                              "stopping it\n", done.err)

    def test_a_turn_that_ignores_term_is_still_ended(self):
        self.step(self.start("deaf"))
        self.interrupted("deaf")
        self.assertFalse(self.held("deaf"), "the turn that ignores TERM still runs")

    def test_an_interrupted_worker_lets_the_harness_save_and_leaves_nothing_running(self):
        self.step(f"setsid {self.start('stray')} & {self.start('harness', 'saves')}")
        self.interrupted("stray", "harness")
        self.assertEqual((self.ws / "harness.saved").read_text(), "session saved")
        for name in ("harness", "stray"):
            with self.subTest(name):
                self.assertFalse(self.held(name), f"{name} still runs")


if __name__ == "__main__":
    unittest.main()
