"""Detached work's scope is stopped once the work has ended, with everything it left running.

`start_in_slice` places a lander or a job in a scope of its own: a stand-in `systemd-run` runs
the scope's command where it is, and the `systemctl` beside it writes down what it was asked.
The work is the test's own: it leaves a server running in a session of its own and ends when
told.  A run's scope is left for its reaper, which reads it after the run.  No real unit is
touched.
"""

import json
import os
import signal
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
from fixtures.sandbox import Sandbox  # noqa: E402
from agentkit import orch  # noqa: E402

RECORD = '''#!{python}
import json, os, sys
with open(os.environ["AK_TEST_{what}"], "a") as fh:
    fh.write(json.dumps(sys.argv[1:]) + "\\n")
'''
# Runs the scope's command in place, as the manager's scope does once the unit is made.
SYSTEMD_RUN = RECORD + '''args = sys.argv[1:]
rest = args[args.index("--") + 1:] if "--" in args else args[args.index("sh"):]
os.execvp(rest[0], rest)
'''
WORK = [sys.executable, "-c", """if True:
    import os, pathlib, subprocess, sys, time
    here = pathlib.Path(sys.argv[1])
    server = subprocess.Popen(["sleep", "300"], start_new_session=True)
    (here / "pids").write_text(f"{os.getpid()} {server.pid}")
    while not (here / "end").exists():
        time.sleep(0.05)
    (here / "ended").touch()
"""]
STOP = ["--user", "stop", "--no-block", "agentkit-lander-acme.scope"]


def wait_for(test, done, what):
    deadline = time.monotonic() + 60
    while not done():
        test.assertLess(time.monotonic(), deadline, what)
        time.sleep(0.05)


class DetachedScopeEndsWithWork(Sandbox):
    def setUp(self):
        super().setUp()
        bin_ = self.root / "bin"
        bin_.mkdir()
        for name, text, what in (("systemd-run", SYSTEMD_RUN, "RUNS"),
                                 ("systemctl", RECORD, "STOPS")):
            (bin_ / name).write_text(text.format(python=sys.executable, what=what))
            (bin_ / name).chmod(0o755)
        self.stops = self.root / "stops.jsonl"
        self.stack.enter_context(patch.dict(os.environ, {
            "AK_TEST_RUNS": str(self.root / "runs.jsonl"), "AK_TEST_STOPS": str(self.stops),
            "XDG_RUNTIME_DIR": str(self.root),
            "PATH": f"{bin_}{os.pathsep}{os.environ['PATH']}"}))
        self.stack.enter_context(patch.object(orch, "user_manager", lambda: True))
        self.stack.enter_context(patch.object(orch, "can_scope", lambda: True))
        self.servers = []
        self.addCleanup(self.end_servers)

    def end_servers(self):
        for server in self.servers:
            os.kill(server, signal.SIGKILL)

    def start(self, name, **kw):
        """The work's pid and its folder, once it has left its server running."""
        here = self.root / name
        here.mkdir()
        pid = orch.start_in_slice([*WORK, str(here)], f"agentkit-lander-{name}", dict(os.environ),
                                  here / "log.txt", **kw)
        wait_for(self, (here / "pids").exists, f"{name} never started")
        work, server = map(int, (here / "pids").read_text().split())
        self.servers.append(server)
        # the witness hands the work its process
        self.assertEqual(work, pid)
        return here

    def stopped(self):
        return ([json.loads(line) for line in self.stops.read_text().splitlines()]
                if self.stops.exists() else [])

    def test_the_scope_is_stopped_once_the_work_has_ended_and_not_before(self):
        lander = self.start("acme")
        time.sleep(2.5)                  # more than one look by the scope's ending
        self.assertEqual(self.stopped(), [], "a scope is stopped under its live work")

        (lander / "end").touch()
        wait_for(self, self.stopped, "the ended work's scope was never stopped")
        # what it left is still running until that stop takes it with the scope
        os.kill(self.servers[0], 0)
        self.assertEqual(self.stopped(), [STOP])

    def test_a_scope_kept_for_its_reaper_outlives_its_work(self):
        kept = self.start("fix-api", ends=False)
        ended = self.start("acme")
        for here in (kept, ended):
            (here / "end").touch()
        wait_for(self, self.stopped, "the ended work's scope was never stopped")
        wait_for(self, (kept / "ended").exists, "the kept work never ended")
        time.sleep(2.5)                  # more than one look by a scope's ending
        self.assertEqual(self.stopped(), [STOP])


if __name__ == "__main__":
    unittest.main()
